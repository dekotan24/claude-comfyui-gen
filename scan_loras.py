#!/usr/bin/env python
"""Scan LoRA metadata files (.cm-info.json) and build lora_map.json.

Reads Stability Matrix's CivitAI metadata format to extract trigger words,
character names, and other useful information for automatic LoRA selection.
"""

import json
import os
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


class HTMLStripper(HTMLParser):
    """Strip HTML tags and return plain text."""
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, data):
        self.result.append(data)

    def get_text(self):
        return " ".join(self.result)


def strip_html(html_text):
    """Remove HTML tags from a string."""
    if not html_text:
        return ""
    stripper = HTMLStripper()
    try:
        stripper.feed(html_text)
        return stripper.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html_text)


def normalize_name(name):
    """Normalize a name for search indexing."""
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = name.strip("_")
    return name


def extract_name_from_filename(filename):
    """Extract the character/concept name from LoRA filename patterns.

    Patterns:
      [LoRA]_[NAME]_rest.safetensors -> NAME
      [LoRA]_[(COLLECTION_NAME)]_rest.safetensors -> COLLECTION_NAME
      [LoRA]_[CATEGORY]_[NAME]_rest.safetensors -> NAME (or CATEGORY_NAME)
    """
    # Remove extension
    base = filename.rsplit(".", 1)[0] if "." in filename else filename

    # Pattern: [LoRA]_[NAME]_rest
    matches = re.findall(r"\[([^\]]+)\]", base)
    if len(matches) >= 2:
        # First bracket is usually "LoRA" or "Lora"
        if matches[0].lower() in ("lora", "lora"):
            # Second bracket is the name/category
            name = matches[1]
            # If it starts with ( and ends with ), it's a collection/placeholder
            if name.startswith("(") and name.endswith(")"):
                name = name[1:-1]
            return name

    # No brackets found - just use the base filename
    return base


def categorize_lora(tags, name_from_file):
    """Determine if a LoRA is character, style, or concept type."""
    tags_lower = [t.lower() for t in tags] if tags else []

    if "character" in tags_lower or "anime" in tags_lower:
        return "character"
    if "style" in tags_lower:
        return "style"
    if "poses" in tags_lower or "concept" in tags_lower or "action" in tags_lower:
        return "concept"

    # Heuristic: if the extracted name looks like a person's name
    name_lower = name_from_file.lower()
    if any(word in tags_lower for word in ["woman", "girl", "female", "man", "boy", "male"]):
        return "character"

    return "concept"


def get_default_strength(category):
    """Get default strength based on LoRA category."""
    strengths = {
        "character": (0.8, 0.8),
        "style": (0.6, 0.6),
        "concept": (0.7, 0.7),
    }
    return strengths.get(category, (0.8, 0.8))


def scan_lora_directory(lora_dir):
    """Scan all .cm-info.json files in the LoRA directory."""
    lora_dir = Path(lora_dir)
    entries = []
    skipped = 0

    for cm_info_path in lora_dir.glob("*.cm-info.json"):
        # Corresponding .safetensors file
        safetensors_name = cm_info_path.name.replace(".cm-info.json", ".safetensors")
        safetensors_path = lora_dir / safetensors_name

        if not safetensors_path.exists():
            skipped += 1
            continue

        try:
            with open(cm_info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"Warning: Could not parse {cm_info_path.name}: {e}", file=sys.stderr)
            skipped += 1
            continue

        # Extract fields
        model_name = info.get("ModelName", "")
        model_id = info.get("ModelId")
        tags = info.get("Tags", [])
        trained_words = info.get("TrainedWords", [])
        base_model = info.get("BaseModel", "")
        nsfw = info.get("Nsfw", False)
        description = strip_html(info.get("ModelDescription", ""))

        # Extract name from filename
        name_from_file = extract_name_from_filename(safetensors_name)

        # Categorize
        category = categorize_lora(tags, name_from_file)
        str_model, str_clip = get_default_strength(category)

        entries.append({
            "filename": safetensors_name,
            "model_name": model_name,
            "model_id": model_id,
            "tags": tags,
            "trained_words": trained_words,
            "base_model": base_model,
            "nsfw": nsfw,
            "description_excerpt": description[:200] if description else "",
            "name_from_file": name_from_file,
            "category": category,
            "strength_model": str_model,
            "strength_clip": str_clip,
        })

    print(f"Scanned {len(entries)} LoRAs ({skipped} skipped)", file=sys.stderr)
    return entries


def build_lora_map(entries):
    """Build the lora_map.json structure from scanned entries."""
    loras = {}
    aliases = {}

    for entry in entries:
        # Create a canonical key from the filename-extracted name
        raw_name = entry["name_from_file"]
        canonical = normalize_name(raw_name)

        if not canonical:
            canonical = normalize_name(entry["filename"].replace(".safetensors", ""))

        # Handle duplicates by appending model_id
        if canonical in loras:
            canonical = f"{canonical}_{entry.get('model_id', 'dup')}"

        # Build the LoRA entry
        trigger_words = []
        for tw in (entry["trained_words"] or []):
            # Each trained_word entry may be a comma-separated string
            for word in tw.split(","):
                word = word.strip()
                if word and len(word) > 1:
                    trigger_words.append(word)

        loras[canonical] = {
            "filename": entry["filename"],
            "model_name": entry["model_name"],
            "trigger_words": trigger_words[:20],  # Limit to top 20
            "tags": entry["tags"],
            "base_model": entry["base_model"],
            "category": entry["category"],
            "strength_model": entry["strength_model"],
            "strength_clip": entry["strength_clip"],
            "nsfw": entry["nsfw"],
        }

        # Generate search aliases
        # 1. From canonical name
        aliases[canonical] = canonical

        # 2. From model name
        if entry["model_name"]:
            model_alias = normalize_name(entry["model_name"])
            if model_alias:
                aliases[model_alias] = canonical

        # 3. From raw filename-extracted name (case variants)
        raw_lower = raw_name.lower().replace(" ", "_")
        aliases[raw_lower] = canonical

        # 4. From filename without brackets
        clean_filename = re.sub(r"\[.*?\]_?", "", entry["filename"])
        clean_filename = clean_filename.replace(".safetensors", "").strip("_")
        if clean_filename:
            aliases[normalize_name(clean_filename)] = canonical

        # 5. From first trigger word if it looks like a character name
        if trigger_words and entry["category"] == "character":
            first_tw = trigger_words[0]
            tw_alias = normalize_name(first_tw)
            if tw_alias and len(tw_alias) > 2:
                aliases[tw_alias] = canonical

    return {
        "version": 1,
        "generated_at": datetime.now().isoformat(),
        "count": len(loras),
        "loras": loras,
        "search_aliases": aliases,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scan LoRA metadata and build lora_map.json")
    parser.add_argument("--lora-dir", default=None, help="Path to LoRA directory")
    parser.add_argument("--output", default=None, help="Output path for lora_map.json")
    args = parser.parse_args()

    # Load config for defaults
    config_path = SCRIPT_DIR / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    lora_dir = args.lora_dir or config.get("paths", {}).get("lora_dir")
    if not lora_dir:
        print("Error: No LoRA directory configured.", file=sys.stderr)
        print("  Set 'paths.lora_dir' in config.json or pass --lora-dir PATH", file=sys.stderr)
        print("  Run 'python setup_config.py' for interactive setup.", file=sys.stderr)
        sys.exit(1)
    output_path = args.output or config.get("paths", {}).get("lora_map", str(SCRIPT_DIR / "lora_map.json"))

    print(f"Scanning LoRA directory: {lora_dir}", file=sys.stderr)

    entries = scan_lora_directory(lora_dir)
    lora_map = build_lora_map(entries)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(lora_map, f, indent=2, ensure_ascii=False)

    print(f"lora_map.json saved to: {output_path}", file=sys.stderr)
    print(f"Total LoRAs indexed: {lora_map['count']}", file=sys.stderr)

    # Print some stats
    categories = {}
    for entry in lora_map["loras"].values():
        cat = entry.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()

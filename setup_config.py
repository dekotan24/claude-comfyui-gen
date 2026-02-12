#!/usr/bin/env python
"""Interactive setup wizard for claude-comfyui-gen configuration.

Auto-detects Stability Matrix installations and helps configure paths,
checkpoint selection, and Claude Code skill installation.
"""

import json
import os
import shutil
import sys
from pathlib import Path
from urllib import request

SCRIPT_DIR = Path(__file__).parent.resolve()


def find_stability_matrix():
    """Auto-detect Stability Matrix installations.

    Searches for StabilityMatrix.db or Data/Models/ as markers.
    Returns list of candidate paths.
    """
    candidates = []

    # Check %APPDATA% (Windows default)
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        sm_path = Path(appdata) / "StabilityMatrix"
        if (sm_path / "Data" / "Models").exists():
            candidates.append(sm_path)

    # Scan drive roots (Windows)
    if sys.platform == "win32":
        import string
        for drive in string.ascii_uppercase:
            drive_path = Path(f"{drive}:/")
            if not drive_path.exists():
                continue
            try:
                for item in drive_path.iterdir():
                    if not item.is_dir():
                        continue
                    try:
                        # Check for SM markers
                        if (item / "Data" / "StabilityMatrix.db").exists():
                            if item not in candidates:
                                candidates.append(item)
                        elif (item / "StabilityMatrix.exe").exists():
                            if item not in candidates:
                                candidates.append(item)
                        elif (item / "Data" / "Models" / "StableDiffusion").exists():
                            if item not in candidates:
                                candidates.append(item)
                    except PermissionError:
                        continue
            except PermissionError:
                continue

    # Linux/Mac: check common locations
    if sys.platform != "win32":
        home = Path.home()
        for candidate in [
            home / "StabilityMatrix",
            home / ".local" / "share" / "StabilityMatrix",
        ]:
            if candidate.exists() and (candidate / "Data" / "Models").exists():
                if candidate not in candidates:
                    candidates.append(candidate)

    return candidates


def list_checkpoints(checkpoint_dir):
    """List .safetensors files in checkpoint directory."""
    checkpoint_path = Path(checkpoint_dir)
    if not checkpoint_path.exists():
        return []
    return sorted([
        f.name for f in checkpoint_path.iterdir()
        if f.suffix == ".safetensors" and f.is_file()
    ])


def test_comfyui_connection(host, port):
    """Test if ComfyUI API is reachable."""
    url = f"http://{host}:{port}/system_stats"
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                vram = data.get("system", {}).get("vram", {})
                vram_total = vram.get("total", 0) / (1024**3) if vram else 0
                return True, f"Connected (VRAM: {vram_total:.1f} GB)"
            return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


def prompt_input(message, default=None):
    """Prompt user for input with optional default."""
    if default:
        value = input(f"{message} [{default}]: ").strip()
        return value if value else default
    return input(f"{message}: ").strip()


def prompt_choice(message, options, default=0):
    """Prompt user to choose from a list."""
    print(f"\n{message}")
    for i, option in enumerate(options):
        marker = " *" if i == default else ""
        print(f"  [{i + 1}] {option}{marker}")
    while True:
        value = input(f"Choice [1-{len(options)}] (default: {default + 1}): ").strip()
        if not value:
            return default
        try:
            idx = int(value) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print("Invalid choice, try again.")


def interactive_setup():
    """Run interactive configuration wizard."""
    print("=" * 60)
    print("  claude-comfyui-gen Setup")
    print("=" * 60)
    print()

    config = {
        "comfyui": {"host": "127.0.0.1", "port": 8188},
        "paths": {},
        "defaults": {
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "steps": 25,
            "cfg": 7.0,
            "clip_skip": 1,
            "width": 1024,
            "height": 1024,
            "batch_count": 4,
            "negative_prompt": "low quality, worst quality, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, artifacts, signature, watermark, username, blurry",
        },
        "face_detailer": {
            "enabled": True,
            "bbox_model": "bbox/face_yolov8m.pt",
            "denoise": 0.5,
            "guide_size": 512,
            "max_size": 768,
            "wildcard": "best quality, high quality face, detailed eyes",
            "steps": 20,
            "cfg": 7.0,
            "bbox_threshold": 0.5,
            "bbox_dilation": 10,
            "bbox_crop_factor": 3.0,
        },
        "hires_fix": {
            "scale": 1.5,
            "denoise": 0.55,
            "steps": None,
        },
        "resolutions": {
            "square": [1024, 1024],
            "portrait": [1024, 1536],
            "portrait_mid": [1152, 1536],
            "landscape": [1536, 1024],
        },
    }

    # --- Step 1: Auto-detect Stability Matrix ---
    print("[1/5] Detecting Stability Matrix...\n")
    sm_candidates = find_stability_matrix()
    sm_root = None

    if sm_candidates:
        if len(sm_candidates) == 1:
            print(f"  Found: {sm_candidates[0]}")
            use_it = prompt_input("  Use this installation? (y/n)", "y")
            if use_it.lower() in ("y", "yes"):
                sm_root = sm_candidates[0]
        else:
            options = [str(c) for c in sm_candidates] + ["Enter custom path"]
            idx = prompt_choice("Found multiple Stability Matrix installations:", options)
            if idx < len(sm_candidates):
                sm_root = sm_candidates[idx]

    if sm_root is None:
        custom = prompt_input("  Enter Stability Matrix root path (or press Enter to skip)")
        if custom and Path(custom).exists():
            sm_root = Path(custom)

    # --- Step 2: Configure paths ---
    print("\n[2/5] Configuring paths...\n")

    if sm_root:
        data_dir = sm_root / "Data"
        default_output = str(data_dir / "Images" / "Text2Img")
        default_lora = str(data_dir / "Models" / "Lora")
        default_checkpoint = str(data_dir / "Models" / "StableDiffusion")
    else:
        default_output = str(SCRIPT_DIR / "output")
        default_lora = ""
        default_checkpoint = ""

    output_dir = prompt_input("  Output directory", default_output)
    config["paths"]["output_dir"] = output_dir

    lora_dir = prompt_input("  LoRA directory", default_lora if default_lora else None)
    if lora_dir:
        config["paths"]["lora_dir"] = lora_dir

    checkpoint_dir = prompt_input("  Checkpoint directory", default_checkpoint if default_checkpoint else None)
    if checkpoint_dir:
        config["paths"]["checkpoint_dir"] = checkpoint_dir

    config["paths"]["lora_map"] = "./lora_map.json"

    # --- Step 3: Select checkpoint ---
    print("\n[3/5] Selecting default checkpoint...\n")

    if checkpoint_dir and Path(checkpoint_dir).exists():
        checkpoints = list_checkpoints(checkpoint_dir)
        if checkpoints:
            idx = prompt_choice("Available checkpoints:", checkpoints)
            config["defaults"]["checkpoint"] = checkpoints[idx]
            print(f"  Selected: {checkpoints[idx]}")
        else:
            print("  No .safetensors files found in checkpoint directory.")
            ckpt = prompt_input("  Enter checkpoint filename", "sd_xl_base_1.0.safetensors")
            config["defaults"]["checkpoint"] = ckpt
    else:
        ckpt = prompt_input("  Enter checkpoint filename", "sd_xl_base_1.0.safetensors")
        config["defaults"]["checkpoint"] = ckpt

    # --- Step 4: ComfyUI connection ---
    print("\n[4/5] ComfyUI connection...\n")

    host = prompt_input("  ComfyUI host", "127.0.0.1")
    port = prompt_input("  ComfyUI port", "8188")
    config["comfyui"]["host"] = host
    config["comfyui"]["port"] = int(port)

    print("  Testing connection...", end=" ")
    ok, msg = test_comfyui_connection(host, int(port))
    if ok:
        print(f"OK! {msg}")
    else:
        print(f"Failed: {msg}")
        print("  (You can start ComfyUI later. Configuration will be saved.)")

    # --- Step 5: Save config ---
    print("\n[5/5] Saving configuration...\n")

    config_path = SCRIPT_DIR / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  Config saved: {config_path}")

    # Offer to scan LoRAs
    if lora_dir and Path(lora_dir).exists():
        scan = prompt_input("\n  Scan LoRA directory now? (y/n)", "y")
        if scan.lower() in ("y", "yes"):
            print("  Scanning LoRAs...")
            scan_script = SCRIPT_DIR / "scan_loras.py"
            if scan_script.exists():
                os.system(f'"{sys.executable}" "{scan_script}"')
            else:
                print("  scan_loras.py not found, skipping.")

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print(f"\n  To generate images:")
    print(f'    python generate.py --prompt "1girl, smile" --count 1')
    print(f"\n  To install Claude Code skill:")
    print(f"    python setup_config.py --install-skill")
    print()


def install_skill():
    """Install SKILL.md to ~/.claude/skills/comfyui-gen/ with path substitution."""
    template_path = SCRIPT_DIR / "skill" / "SKILL.md"
    if not template_path.exists():
        print(f"Error: {template_path} not found.", file=sys.stderr)
        sys.exit(1)

    # Load config for path substitution
    config_path = SCRIPT_DIR / "config.json"
    if not config_path.exists():
        print("Error: config.json not found. Run setup first.", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Determine Python executable path
    python_exe = sys.executable

    # Read template
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Substitute placeholders
    replacements = {
        "{{PYTHON_EXE}}": python_exe,
        "{{SCRIPT_DIR}}": str(SCRIPT_DIR),
        "{{OUTPUT_DIR}}": config.get("paths", {}).get("output_dir", str(SCRIPT_DIR / "output")),
        "{{LORA_MAP_PATH}}": config.get("paths", {}).get("lora_map", str(SCRIPT_DIR / "lora_map.json")),
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    # Install to ~/.claude/skills/comfyui-gen/
    home = Path.home()
    skill_dir = home / ".claude" / "skills" / "comfyui-gen"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"

    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Skill installed: {skill_path}")
    print("Claude Code will now use this skill for image generation requests.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Setup claude-comfyui-gen configuration")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Copy config.example.json without prompts")
    parser.add_argument("--install-skill", action="store_true",
                        help="Install Claude Code skill to ~/.claude/skills/")
    args = parser.parse_args()

    if args.install_skill:
        install_skill()
        return

    if args.non_interactive:
        example = SCRIPT_DIR / "config.example.json"
        target = SCRIPT_DIR / "config.json"
        if not example.exists():
            print("Error: config.example.json not found.", file=sys.stderr)
            sys.exit(1)
        shutil.copy(example, target)
        print(f"Copied config.example.json -> config.json")
        print("Edit config.json with your paths before use.")
    else:
        interactive_setup()


if __name__ == "__main__":
    main()

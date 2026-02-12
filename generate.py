#!/usr/bin/env python
"""ComfyUI image generation script via API.

Builds SDXL workflows programmatically and submits them to ComfyUI's API.
Supports LoRA, FaceDetailer, sequential multi-image generation, and grid compositing.
"""

import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib import request, parse, error as urlerror

# Optional: websocket-client for real-time monitoring
try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

# Optional: PIL for grid compositing
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

SCRIPT_DIR = Path(__file__).parent.resolve()


# =============================================================================
# Configuration
# =============================================================================

def ensure_config():
    """Check for config.json and print guidance if missing."""
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        return
    example_path = SCRIPT_DIR / "config.example.json"
    print("Warning: config.json not found. Using built-in defaults.", file=sys.stderr)
    if example_path.exists():
        print("  Run 'python setup_config.py' for interactive setup, or", file=sys.stderr)
        print("  copy config.example.json to config.json and edit paths.", file=sys.stderr)
    else:
        print("  Run 'python setup_config.py' to create config.json.", file=sys.stderr)


def load_config():
    """Load config.json from script directory."""
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback defaults
    return {
        "comfyui": {"host": "127.0.0.1", "port": 8188},
        "paths": {"output_dir": str(SCRIPT_DIR / "output")},
        "defaults": {
            "checkpoint": "sd_xl_base_1.0.safetensors",
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "steps": 25,
            "cfg": 7.0,
            "clip_skip": 1,
            "width": 1024,
            "height": 1024,
            "batch_count": 4,
            "negative_prompt": "lowers, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, artifacts, signature, watermark, username, out of focus, censorship, Blurry faces, Blank faces, bad face, Ugly, extra ear, amputee, missing hands, missing arms, missing legs, Extra fingers, 6 fingers, Extra feet, Missing nipples, ghost, missing body, bad eyes, copyright, logo",
        },
        "face_detailer": {"enabled": True},
        "resolutions": {
            "square": [1024, 1024],
            "portrait": [896, 1152],
            "portrait_tall": [768, 1344],
            "landscape": [1152, 896],
            "landscape_wide": [1344, 768],
        },
    }


def load_lora_map():
    """Load lora_map.json if it exists."""
    config = load_config()
    lora_map_path = config.get("paths", {}).get("lora_map", str(SCRIPT_DIR / "lora_map.json"))
    path = Path(lora_map_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"loras": {}, "search_aliases": {}}


def resolve_lora_by_name(name, lora_map=None):
    """Look up a LoRA by character/concept name in lora_map.json.

    Returns dict with {filename, trigger_words, strength_model, strength_clip} or None.
    """
    if lora_map is None:
        lora_map = load_lora_map()

    name_lower = name.lower().replace(" ", "_").replace("-", "_")

    # Direct match in aliases
    aliases = lora_map.get("search_aliases", {})
    if name_lower in aliases:
        key = aliases[name_lower]
        entry = lora_map.get("loras", {}).get(key)
        if entry:
            return entry

    # Partial match in lora keys
    for key, entry in lora_map.get("loras", {}).items():
        if name_lower in key.lower():
            return entry

    # Partial match in trigger_words
    for key, entry in lora_map.get("loras", {}).items():
        for tw in entry.get("trigger_words", []):
            if name_lower in tw.lower():
                return entry

    return None


# =============================================================================
# Workflow Builder
# =============================================================================

def build_workflow(
    positive_prompt,
    negative_prompt,
    seed,
    steps=25,
    cfg=7.0,
    width=1024,
    height=1024,
    sampler_name="euler_ancestral",
    scheduler="normal",
    clip_skip=1,
    checkpoint="waiIllustriousSDXL_v150.safetensors",
    loras=None,
    face_detailer=True,
    face_detailer_config=None,
    filename_prefix="ComfyUI",
    hires_fix=False,
    hires_scale=1.5,
    hires_denoise=0.55,
    hires_steps=None,
):
    """Build a ComfyUI API-format workflow dict.

    Args:
        loras: list of dicts, each: {"filename": str, "strength_model": float, "strength_clip": float}
        face_detailer_config: dict with FaceDetailer parameters (from config.json)
    """
    workflow = {}

    # --- Node 1: CheckpointLoaderSimple ---
    workflow["1"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": checkpoint},
    }
    # Outputs: [0]=MODEL, [1]=CLIP, [2]=VAE

    # --- LoRA chain (nodes 20, 21, 22, ...) ---
    last_model_source = ["1", 0]  # MODEL from checkpoint
    last_clip_source = ["1", 1]   # CLIP from checkpoint

    if loras:
        for i, lora in enumerate(loras):
            node_id = str(20 + i)
            workflow[node_id] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": last_model_source,
                    "clip": last_clip_source,
                    "lora_name": lora["filename"],
                    "strength_model": lora.get("strength_model", 0.8),
                    "strength_clip": lora.get("strength_clip", 0.8),
                },
            }
            last_model_source = [node_id, 0]
            last_clip_source = [node_id, 1]

    # --- Node 2: CLIPSetLastLayer (clip skip) ---
    # Only add CLIPSetLastLayer if clip_skip > 1; clip_skip=1 is default behavior
    clip_output = last_clip_source
    if clip_skip > 1:
        workflow["2"] = {
            "class_type": "CLIPSetLastLayer",
            "inputs": {
                "clip": last_clip_source,
                "stop_at_clip_layer": -clip_skip,
            },
        }
        clip_output = ["2", 0]

    # --- Node 3: CLIPTextEncode (positive) ---
    workflow["3"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "clip": clip_output,
            "text": positive_prompt,
        },
    }

    # --- Node 4: CLIPTextEncode (negative) ---
    workflow["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "clip": clip_output,
            "text": negative_prompt,
        },
    }

    # --- Node 5: EmptyLatentImage ---
    workflow["5"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": width,
            "height": height,
            "batch_size": 1,
        },
    }

    # --- Node 6: KSampler ---
    workflow["6"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": last_model_source,
            "positive": ["3", 0],
            "negative": ["4", 0],
            "latent_image": ["5", 0],
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": 1.0,
        },
    }

    # --- Hires Fix (nodes 30, 31) ---
    vae_decode_input = ["6", 0]

    if hires_fix:
        # Node 30: LatentUpscaleBy
        workflow["30"] = {
            "class_type": "LatentUpscaleBy",
            "inputs": {
                "samples": ["6", 0],
                "upscale_method": "nearest-exact",
                "scale_by": hires_scale,
            },
        }

        # Node 31: KSampler (hires pass)
        workflow["31"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": last_model_source,
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["30", 0],
                "seed": seed,
                "steps": hires_steps or steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": hires_denoise,
            },
        }
        vae_decode_input = ["31", 0]

    # --- Node 7: VAEDecode ---
    workflow["7"] = {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": vae_decode_input,
            "vae": ["1", 2],
        },
    }

    # The image source for SaveImage (may be overridden by FaceDetailer)
    image_source = ["7", 0]

    # --- FaceDetailer (nodes 10, 11) ---
    if face_detailer:
        fd_cfg = face_detailer_config or {}

        workflow["10"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {
                "model_name": fd_cfg.get("bbox_model", "bbox/face_yolov8m.pt"),
            },
        }

        workflow["11"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": ["7", 0],
                "model": last_model_source,
                "clip": clip_output,
                "vae": ["1", 2],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "bbox_detector": ["10", 0],
                "seed": seed,
                "steps": fd_cfg.get("steps", 20),
                "cfg": fd_cfg.get("cfg", 7.0),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": fd_cfg.get("denoise", 0.5),
                "guide_size": fd_cfg.get("guide_size", 512),
                "guide_size_for": True,
                "max_size": fd_cfg.get("max_size", 768),
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": fd_cfg.get("bbox_threshold", 0.5),
                "bbox_dilation": fd_cfg.get("bbox_dilation", 10),
                "bbox_crop_factor": fd_cfg.get("bbox_crop_factor", 3.0),
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "wildcard": fd_cfg.get("wildcard", "best quality, high quality face, detailed eyes"),
                "cycle": 1,
            },
        }
        image_source = ["11", 0]

    # --- Node 8: SaveImage ---
    workflow["8"] = {
        "class_type": "SaveImage",
        "inputs": {
            "images": image_source,
            "filename_prefix": filename_prefix,
        },
    }

    return workflow


# =============================================================================
# ComfyUI API Client
# =============================================================================

def get_server_url(config):
    """Get the base server URL from config."""
    host = config.get("comfyui", {}).get("host", "127.0.0.1")
    port = config.get("comfyui", {}).get("port", 8188)
    return f"http://{host}:{port}"


def check_server(config):
    """Check if ComfyUI server is running."""
    url = f"{get_server_url(config)}/system_stats"
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def queue_prompt(workflow, config, client_id):
    """Submit a workflow to ComfyUI and return the prompt_id."""
    url = f"{get_server_url(config)}/prompt"
    payload = json.dumps({"client_id": client_id, "prompt": workflow}).encode("utf-8")
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body["prompt_id"]


def get_history(prompt_id, config):
    """Get history for a specific prompt_id."""
    url = f"{get_server_url(config)}/history/{prompt_id}"
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get(prompt_id, {})
    except Exception:
        return {}


def wait_for_completion_polling(prompt_id, config, timeout=300):
    """Poll /history until the prompt completes or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        history = get_history(prompt_id, config)
        if history and history.get("outputs"):
            return history
        time.sleep(2)
    raise TimeoutError(f"Generation timed out after {timeout}s for prompt {prompt_id}")


def wait_for_completion_ws(prompt_id, config, client_id, timeout=300):
    """Wait via WebSocket for prompt completion. Falls back to polling."""
    if not HAS_WEBSOCKET:
        return wait_for_completion_polling(prompt_id, config, timeout)

    host = config.get("comfyui", {}).get("host", "127.0.0.1")
    port = config.get("comfyui", {}).get("port", 8188)
    ws_url = f"ws://{host}:{port}/ws?clientId={client_id}"

    ws = None
    try:
        ws = websocket.create_connection(ws_url, timeout=timeout)
        ws.settimeout(timeout)

        while True:
            msg = ws.recv()
            if not msg:
                continue
            # Skip binary messages (preview images, etc.)
            if isinstance(msg, bytes):
                continue
            try:
                data = json.loads(msg)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            msg_type = data.get("type", "")

            if msg_type == "progress":
                d = data.get("data", {})
                if d.get("prompt_id") == prompt_id:
                    val = d.get("value", 0)
                    mx = d.get("max", 1)
                    print(f"\r  Progress: {val}/{mx}", end="", file=sys.stderr, flush=True)

            elif msg_type == "executing":
                d = data.get("data", {})
                if d.get("prompt_id") == prompt_id and d.get("node") is None:
                    # Execution complete
                    print("", file=sys.stderr)
                    break

            elif msg_type == "execution_error":
                d = data.get("data", {})
                if d.get("prompt_id") == prompt_id:
                    raise RuntimeError(f"ComfyUI execution error: {json.dumps(d, indent=2)}")

    except websocket.WebSocketTimeoutException:
        raise TimeoutError(f"WebSocket timed out after {timeout}s")
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    # Fetch history to get output filenames
    time.sleep(0.5)
    return get_history(prompt_id, config)


def get_output_filenames(history_entry):
    """Extract output image filenames from a history entry."""
    filenames = []
    outputs = history_entry.get("outputs", {})
    for node_id, node_output in outputs.items():
        images = node_output.get("images", [])
        for img in images:
            fn = img.get("filename")
            if fn:
                filenames.append(fn)
    return filenames


# =============================================================================
# Image Processing
# =============================================================================

def find_output_images(filenames, output_dir):
    """Map filenames to full paths in the output directory."""
    paths = []
    for fn in filenames:
        full_path = os.path.join(output_dir, fn)
        if os.path.exists(full_path):
            paths.append(full_path)
        else:
            # Try searching subdirectories
            for root, dirs, files in os.walk(output_dir):
                if fn in files:
                    paths.append(os.path.join(root, fn))
                    break
    return paths


def create_grid(image_paths, output_path, cols=None, padding=4, max_grid_size=3000):
    """Create a grid composite from multiple images.

    Args:
        max_grid_size: Maximum dimension of the grid image. Images are scaled down if needed.
    """
    if not HAS_PIL:
        print("Warning: PIL not available, skipping grid creation", file=sys.stderr)
        return None

    if not image_paths:
        return None

    import math
    images = [Image.open(p) for p in image_paths]
    n = len(images)
    if cols is None:
        cols = math.ceil(math.sqrt(n))
    rows = (n + cols - 1) // cols

    # Get max dimensions
    max_w = max(img.width for img in images)
    max_h = max(img.height for img in images)

    # Calculate grid size
    grid_w = cols * max_w + (cols - 1) * padding
    grid_h = rows * max_h + (rows - 1) * padding

    # Scale down if needed
    scale = 1.0
    if max(grid_w, grid_h) > max_grid_size:
        scale = max_grid_size / max(grid_w, grid_h)
        max_w = int(max_w * scale)
        max_h = int(max_h * scale)
        grid_w = cols * max_w + (cols - 1) * padding
        grid_h = rows * max_h + (rows - 1) * padding
        images = [img.resize((max_w, max_h), Image.LANCZOS) for img in images]

    grid = Image.new("RGB", (grid_w, grid_h), (0, 0, 0))

    for i, img in enumerate(images):
        row = i // cols
        col = i % cols
        x = col * (max_w + padding)
        y = row * (max_h + padding)
        # Center the image if it's smaller than the cell
        x_offset = (max_w - img.width) // 2
        y_offset = (max_h - img.height) // 2
        grid.paste(img, (x + x_offset, y + y_offset))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    grid.save(output_path, "PNG")
    return output_path


def open_image(path):
    """Open image in Windows default viewer."""
    if sys.platform == "win32":
        os.startfile(path)
    else:
        import subprocess
        subprocess.Popen(["xdg-open", path])


# =============================================================================
# Main Generation Flow
# =============================================================================

def generate_batch(
    positive_prompt,
    negative_prompt=None,
    seed=None,
    steps=None,
    cfg=None,
    width=None,
    height=None,
    sampler_name=None,
    scheduler=None,
    clip_skip=None,
    checkpoint=None,
    loras=None,
    face_detailer=None,
    batch_count=None,
    filename_prefix=None,
    open_grid=True,
    json_output=False,
    hires_fix=False,
    hires_scale=None,
    hires_denoise=None,
    hires_steps=None,
):
    """Generate a batch of images sequentially and create a grid composite."""
    config = load_config()
    defaults = config.get("defaults", {})

    # Apply defaults
    if negative_prompt is None:
        negative_prompt = defaults.get("negative_prompt", "")
    if steps is None:
        steps = defaults.get("steps", 25)
    if cfg is None:
        cfg = defaults.get("cfg", 7.0)
    if width is None:
        width = defaults.get("width", 1024)
    if height is None:
        height = defaults.get("height", 1024)
    if sampler_name is None:
        sampler_name = defaults.get("sampler", "euler_ancestral")
    if scheduler is None:
        scheduler = defaults.get("scheduler", "normal")
    if clip_skip is None:
        clip_skip = defaults.get("clip_skip", 1)
    if checkpoint is None:
        checkpoint = defaults.get("checkpoint", "waiIllustriousSDXL_v150.safetensors")
    if face_detailer is None:
        face_detailer = config.get("face_detailer", {}).get("enabled", True)
    if batch_count is None:
        batch_count = defaults.get("batch_count", 4)

    # Hires fix defaults
    hires_cfg = config.get("hires_fix", {})
    if hires_scale is None:
        hires_scale = hires_cfg.get("scale", 1.5)
    if hires_denoise is None:
        hires_denoise = hires_cfg.get("denoise", 0.55)
    if hires_steps is None and hires_fix:
        hires_steps = hires_cfg.get("steps", None)  # None = use same as base

    # Generate timestamp-based prefix
    if filename_prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_prefix = f"gen_{ts}"

    output_dir = config.get("paths", {}).get("output_dir", str(SCRIPT_DIR / "output"))
    os.makedirs(output_dir, exist_ok=True)
    fd_config = config.get("face_detailer", {})

    # Check server
    if not check_server(config):
        msg = "Error: ComfyUI is not running. Please start it via Stability Matrix."
        if json_output:
            print(json.dumps({"error": msg}))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    client_id = str(uuid.uuid4()).replace("-", "")
    all_filenames = []
    all_paths = []
    all_seeds = []
    seed_specified = seed is not None
    base_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    if not json_output:
        print(f"Generating {batch_count} images...", file=sys.stderr)
        print(f"  Model: {checkpoint}", file=sys.stderr)
        print(f"  Resolution: {width}x{height}", file=sys.stderr)
        print(f"  Steps: {steps}, CFG: {cfg}", file=sys.stderr)
        print(f"  Base seed: {base_seed}", file=sys.stderr)
        if hires_fix:
            final_w = int(width * hires_scale)
            final_h = int(height * hires_scale)
            print(f"  Hires Fix: {hires_scale}x (→{final_w}x{final_h}), denoise={hires_denoise}", file=sys.stderr)
        if loras:
            for l in loras:
                print(f"  LoRA: {l['filename']} (str={l.get('strength_model', 0.8)})", file=sys.stderr)

    for i in range(batch_count):
        if seed_specified:
            current_seed = base_seed + i
        else:
            current_seed = random.randint(0, 2**32 - 1) if i > 0 else base_seed
        all_seeds.append(current_seed)

        if not json_output:
            print(f"\n[{i+1}/{batch_count}] Generating with seed {current_seed}...", file=sys.stderr)

        workflow = build_workflow(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            seed=current_seed,
            steps=steps,
            cfg=cfg,
            width=width,
            height=height,
            sampler_name=sampler_name,
            scheduler=scheduler,
            clip_skip=clip_skip,
            checkpoint=checkpoint,
            loras=loras,
            face_detailer=face_detailer,
            face_detailer_config=fd_config,
            filename_prefix=filename_prefix,
            hires_fix=hires_fix,
            hires_scale=hires_scale,
            hires_denoise=hires_denoise,
            hires_steps=hires_steps,
        )

        try:
            prompt_id = queue_prompt(workflow, config, client_id)
        except Exception as e:
            msg = f"Failed to queue prompt: {e}"
            if json_output:
                print(json.dumps({"error": msg}))
            else:
                print(msg, file=sys.stderr)
            sys.exit(1)

        try:
            history = wait_for_completion_ws(prompt_id, config, client_id, timeout=300)
        except TimeoutError:
            print(f"Warning: Image {i+1} timed out, skipping", file=sys.stderr)
            continue
        except RuntimeError as e:
            print(f"Warning: Image {i+1} failed: {e}", file=sys.stderr)
            continue

        filenames = get_output_filenames(history)
        if filenames:
            all_filenames.extend(filenames)
            paths = find_output_images(filenames, output_dir)
            all_paths.extend(paths)
            if not json_output:
                print(f"[{i+1}/{batch_count}] Complete: {', '.join(filenames)}", file=sys.stderr)
        else:
            if not json_output:
                print(f"[{i+1}/{batch_count}] Warning: No output files found", file=sys.stderr)

    # Create grid
    grid_path = None
    if len(all_paths) > 1 and HAS_PIL:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        grid_filename = f"grid_{ts}_{base_seed}.png"
        grid_path = os.path.join(output_dir, grid_filename)
        grid_path = create_grid(all_paths, grid_path)
        if grid_path and not json_output:
            print(f"\nGrid saved: {grid_path}", file=sys.stderr)
    elif len(all_paths) == 1:
        grid_path = all_paths[0]

    # Open image
    if open_grid and grid_path and os.path.exists(grid_path):
        open_image(grid_path)

    # Build result
    result = {
        "images": all_paths,
        "grid": grid_path,
        "seed": base_seed,
        "seeds": all_seeds,
        "prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "params": {
            "steps": steps,
            "cfg": cfg,
            "width": width,
            "height": height,
            "sampler": sampler_name,
            "scheduler": scheduler,
            "checkpoint": checkpoint,
            "clip_skip": clip_skip,
            "face_detailer": face_detailer,
            "hires_fix": hires_fix,
            "hires_scale": hires_scale if hires_fix else None,
            "hires_denoise": hires_denoise if hires_fix else None,
            "loras": loras or [],
        },
    }

    if json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"\nDone! {len(all_paths)} images generated.", file=sys.stderr)

    return result


# =============================================================================
# CLI
# =============================================================================

def parse_lora_arg(lora_str):
    """Parse --lora argument: 'filename.safetensors:0.8' or 'filename.safetensors'."""
    parts = lora_str.rsplit(":", 1)
    filename = parts[0]
    strength = float(parts[1]) if len(parts) > 1 else 0.8
    return {"filename": filename, "strength_model": strength, "strength_clip": strength}


def main():
    ensure_config()
    parser = argparse.ArgumentParser(description="Generate images via ComfyUI API")
    parser.add_argument("--prompt", required=True, help="Positive prompt text")
    parser.add_argument("--negative", default=None, help="Negative prompt (uses default if omitted)")
    parser.add_argument("--seed", type=int, default=None, help="Base seed (random if omitted)")
    parser.add_argument("--steps", type=int, default=None, help="Sampling steps")
    parser.add_argument("--cfg", type=float, default=None, help="CFG scale")
    parser.add_argument("--width", type=int, default=None, help="Image width")
    parser.add_argument("--height", type=int, default=None, help="Image height")
    parser.add_argument("--resolution", default=None,
                        choices=["square", "portrait", "portrait_mid", "landscape"],
                        help="Named resolution preset")
    parser.add_argument("--sampler", default=None, help="Sampler name")
    parser.add_argument("--scheduler", default=None, help="Scheduler name")
    parser.add_argument("--checkpoint", default=None, help="Checkpoint model filename")
    parser.add_argument("--lora", action="append", default=None,
                        help="LoRA spec: 'filename.safetensors:strength' (repeatable)")
    parser.add_argument("--lora-name", action="append", default=None, dest="lora_names",
                        help="LoRA lookup by character name from lora_map.json (repeatable)")
    parser.add_argument("--no-face-detailer", action="store_true", help="Disable FaceDetailer")
    parser.add_argument("--hires", action="store_true", help="Enable Hires Fix (latent upscale + 2nd pass)")
    parser.add_argument("--hires-scale", type=float, default=None, help="Hires upscale factor (default: 1.5)")
    parser.add_argument("--hires-denoise", type=float, default=None, help="Hires denoise strength (default: 0.55)")
    parser.add_argument("--hires-steps", type=int, default=None, help="Hires sampling steps (default: same as base)")
    parser.add_argument("--count", type=int, default=None, help="Number of images (default: 4)")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open grid image")
    parser.add_argument("--prefix", default=None, help="Filename prefix")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")

    args = parser.parse_args()

    # Resolve resolution preset
    width = args.width
    height = args.height
    if args.resolution and not (args.width or args.height):
        config = load_config()
        res = config.get("resolutions", {}).get(args.resolution)
        if res:
            width, height = res

    # Resolve LoRAs
    loras = []
    if args.lora:
        for l in args.lora:
            loras.append(parse_lora_arg(l))

    if args.lora_names:
        lora_map = load_lora_map()
        for name in args.lora_names:
            entry = resolve_lora_by_name(name, lora_map)
            if entry:
                loras.append({
                    "filename": entry["filename"],
                    "strength_model": entry.get("strength_model", 0.8),
                    "strength_clip": entry.get("strength_clip", 0.8),
                })
                if not args.json:
                    print(f"LoRA found: {name} -> {entry['filename']}", file=sys.stderr)
                    if entry.get("trigger_words"):
                        print(f"  Trigger words: {entry['trigger_words'][:3]}", file=sys.stderr)
            else:
                print(f"Warning: LoRA not found for '{name}'", file=sys.stderr)

    generate_batch(
        positive_prompt=args.prompt,
        negative_prompt=args.negative,
        seed=args.seed,
        steps=args.steps,
        cfg=args.cfg,
        width=width,
        height=height,
        sampler_name=args.sampler,
        scheduler=args.scheduler,
        checkpoint=args.checkpoint,
        loras=loras if loras else None,
        face_detailer=False if args.no_face_detailer else None,
        batch_count=args.count,
        filename_prefix=args.prefix,
        open_grid=not args.no_open,
        json_output=args.json,
        hires_fix=args.hires,
        hires_scale=args.hires_scale,
        hires_denoise=args.hires_denoise,
        hires_steps=args.hires_steps,
    )


if __name__ == "__main__":
    main()

# Claude ComfyUI Gen

Generate SDXL images programmatically through ComfyUI's API — no workflow files needed. Builds node graphs dynamically in Python. Includes a [Claude Code](https://claude.com/claude-code) skill for natural language image generation (Japanese).

**[日本語 README](README.md)**

## Features

- **Programmatic Workflow Building** — constructs ComfyUI API workflows in pure Python, no JSON workflow files to manage
- **SDXL Optimized** — tuned defaults for Illustrious XL and similar SDXL checkpoints
- **LoRA Chains** — stack multiple LoRAs with per-LoRA strength control
- **Smart LoRA Lookup** — search LoRAs by character/concept name via auto-generated index
- **FaceDetailer Integration** — automatic face enhancement via UltralyticsDetectorProvider
- **Hires Fix** — 2-pass latent upscale for high-resolution output
- **Batch Generation** — generate N images with automatic seed management
- **Grid Compositing** — auto-creates comparison grids from batch runs
- **WebSocket Progress** — real-time generation progress with HTTP polling fallback
- **Claude Code Skill** — use natural language (Japanese) to generate images through Claude Code
- **Minimal Dependencies** — Pillow and websocket-client are optional with graceful fallbacks

## Prerequisites

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) running and accessible via API
- [Stability Matrix](https://github.com/LykosAI/StabilityMatrix) (recommended) or standalone ComfyUI
- Python 3.10+
- An SDXL-compatible checkpoint model (e.g., Illustrious XL, Pony Diffusion)
- (Optional) [ComfyUI Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) for FaceDetailer support

## Installation

### Option 1: Claude Code (fully automated)

```bash
git clone https://github.com/dekotan24/claude-comfyui-gen.git
cd claude-comfyui-gen
```

Copy the skill file:

```bash
# Windows
mkdir "%USERPROFILE%\.claude\skills\comfyui-gen" 2>nul
copy skill\SKILL.md "%USERPROFILE%\.claude\skills\comfyui-gen\SKILL.md"

# Linux/Mac
mkdir -p ~/.claude/skills/comfyui-gen
cp skill/SKILL.md ~/.claude/skills/comfyui-gen/SKILL.md
```

That's it. Ask Claude Code to generate an image (e.g., "generate a girl smiling"), and it will automatically:

1. Detect your Stability Matrix installation
2. Create a virtual environment and install dependencies
3. Configure paths and select your checkpoint model (interactive)
4. Scan LoRA metadata
5. Generate images

### Option 2: Manual Setup

```bash
git clone https://github.com/dekotan24/claude-comfyui-gen.git
cd claude-comfyui-gen
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
python setup_config.py
```

The setup wizard auto-detects Stability Matrix, configures paths, and walks you through model selection and connection testing.

## Usage

### Claude Code Skill

After installing the skill, just describe what you want in Japanese:

```
女の子を1人、笑顔で立ってる絵を生成して
海辺で水着の女の子を描いて
金髪ツインテールの女の子を高画質で
```

The skill parses Japanese descriptions, builds optimized SDXL prompts, and auto-selects resolution, steps, and LoRAs based on the content.

### CLI

```bash
# Basic generation (4 images)
python generate.py --prompt "masterpiece, best quality, 1girl, white dress, garden, sunlight"

# Portrait orientation, 1 image
python generate.py --prompt "masterpiece, best quality, 1girl, standing, full body" --resolution portrait --count 1

# LoRA by character name
python generate.py --prompt "masterpiece, best quality, 1girl, smile" --lora-name "character_name"

# LoRA by filename
python generate.py --prompt "masterpiece, best quality, 1girl" --lora "my_lora.safetensors:0.8"

# High-resolution with Hires Fix
python generate.py --prompt "masterpiece, best quality, 1girl, detailed" --resolution landscape --hires

# JSON output (for scripting)
python generate.py --prompt "masterpiece, best quality, 1girl" --json
```

### LoRA Scanning

Build a searchable LoRA index from Stability Matrix metadata:

```bash
python scan_loras.py
```

Reads `.cm-info.json` metadata files (created by Stability Matrix / CivitAI) and builds `lora_map.json` for fast character/concept lookup.

## CLI Reference

| Option | Description |
|--------|-------------|
| `--prompt "..."` | Positive prompt (required) |
| `--negative "..."` | Negative prompt (uses config default if omitted) |
| `--resolution NAME` | Resolution preset: `square`, `portrait`, `portrait_mid`, `landscape` |
| `--width N` | Custom width |
| `--height N` | Custom height |
| `--steps N` | Sampling steps (default: 25) |
| `--cfg N.N` | CFG scale (default: 7.0) |
| `--seed N` | Base seed (random if omitted) |
| `--checkpoint "..."` | Checkpoint model filename |
| `--lora "file:strength"` | LoRA by filename (repeatable) |
| `--lora-name "name"` | LoRA by character name lookup (repeatable) |
| `--no-face-detailer` | Disable FaceDetailer |
| `--hires` | Enable Hires Fix (2-pass latent upscale) |
| `--hires-scale N.N` | Upscale factor (default: 1.5) |
| `--hires-denoise N.N` | 2nd pass denoise (default: 0.55) |
| `--hires-steps N` | 2nd pass steps (default: same as base) |
| `--count N` | Number of images (default: 4) |
| `--no-open` | Don't auto-open result image |
| `--json` | Output result as JSON |

## Resolution Presets

| Preset | Size | Ratio | Use Case |
|--------|------|-------|----------|
| `portrait` | 1024x1536 | 2:3 | Single character, full body |
| `portrait_mid` | 1152x1536 | 3:4 | Two characters, low angle |
| `landscape` | 1536x1024 | 3:2 | Multiple characters, scenery |
| `square` | 1024x1024 | 1:1 | Face close-up, icons |

## Architecture

```
User input → generate.py → Build workflow JSON → ComfyUI API → Image output
                                    |
                            Checkpoint → LoRA chain → CLIP encode
                            → KSampler → [Hires Fix] → VAEDecode
                            → [FaceDetailer] → SaveImage
```

Workflows are built entirely in Python — no static JSON files. LoRA, FaceDetailer, and Hires Fix nodes are dynamically added or removed based on each request.

## Configuration

See `config.example.json` for the full structure:

| Section | Contents |
|---------|----------|
| `comfyui` | API server host and port |
| `paths` | Output directory, model directories, LoRA map path |
| `defaults` | Default checkpoint, sampler, steps, CFG, resolution, negative prompt |
| `face_detailer` | FaceDetailer parameters (bbox model, denoise, guide size) |
| `hires_fix` | Hires Fix defaults (scale, denoise, steps) |
| `resolutions` | Named resolution presets |

## License

MIT

# Claude ComfyUI Gen

claude codeからComfyUIのAPIを叩いて画像を生成するスキル。
「○○の画像を作って」等でComfyUI経由で画像の生成が可能です。

**[English README](README_en.md)**

## 特徴

- **ワークフロー自動構築** — JSON ワークフローファイル不要。Python で API ワークフローを動的に構築
- **SDXL 最適化** — Illustrious XL 等の SDXL チェックポイント向けにチューニング済み
- **LoRA チェーン** — 複数 LoRA の重ね掛けに対応、個別に強度設定可能
- **LoRA 名前検索** — キャラ名・コンセプト名から自動インデックスで LoRA を検索
- **FaceDetailer** — UltralyticsDetectorProvider による顔の自動補正
- **Hires Fix** — Latent アップスケール + 2パス生成で高解像度出力
- **バッチ生成** — 複数枚を順次生成、シード自動管理
- **グリッド合成** — バッチ生成結果を自動でグリッド画像に合成
- **WebSocket 進捗表示** — リアルタイム進捗表示（HTTP ポーリングフォールバック付き）
- **Claude Code スキル** — 日本語の指示から自動でプロンプトを構築し画像生成
- **最小依存** — Pillow と websocket-client はオプション、なくても動作

## 必要環境

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) が起動済みで API アクセス可能
- [Stability Matrix](https://github.com/LykosAI/StabilityMatrix)（推奨）または単体 ComfyUI
- Python 3.10+
- SDXL 対応チェックポイントモデル（Illustrious XL, Pony Diffusion 等）
- （任意）[ComfyUI Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) — FaceDetailer 使用時に必要

## インストール

### 方法 1: Claude Code で全自動セットアップ

```bash
git clone https://github.com/dekotan24/claude-comfyui-gen.git
cd claude-comfyui-gen
```

スキルファイルをコピー:

```bash
# Windows
mkdir "%USERPROFILE%\.claude\skills\comfyui-gen" 2>nul
copy skill\SKILL.md "%USERPROFILE%\.claude\skills\comfyui-gen\SKILL.md"

# Linux/Mac
mkdir -p ~/.claude/skills/comfyui-gen
cp skill/SKILL.md ~/.claude/skills/comfyui-gen/SKILL.md
```

これだけで準備完了。Claude Code に「女の子を生成して」と言うだけで、初回は自動で以下を実行します:

1. Stability Matrix のインストール先を自動検出
2. 仮想環境の作成と依存パッケージのインストール
3. パス設定とチェックポイントモデルの選択（対話式）
4. LoRA メタデータのスキャン
5. 画像生成

### 方法 2: 手動セットアップ

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

セットアップウィザードが Stability Matrix を自動検出し、パス設定・モデル選択・接続テストまで対話式で行います。

## 使い方

### Claude Code スキル（日本語で指示）

スキルインストール後は日本語で指示するだけ:

```
女の子を1人、笑顔で立ってる絵を生成して
海辺で水着の女の子を描いて
金髪ツインテールの女の子を高画質で
```

日本語の指示を解析し、SDXL 向けの英語プロンプトを自動構築して生成します。解像度・ステップ数・LoRA なども内容に応じて自動選択されます。

### コマンドライン

```bash
# 基本生成（4枚）
python generate.py --prompt "masterpiece, best quality, 1girl, white dress, garden, sunlight"

# 縦長、1枚だけ
python generate.py --prompt "masterpiece, best quality, 1girl, standing, full body" --resolution portrait --count 1

# キャラ名で LoRA 検索
python generate.py --prompt "masterpiece, best quality, 1girl, smile" --lora-name "character_name"

# LoRA ファイル直接指定
python generate.py --prompt "masterpiece, best quality, 1girl" --lora "my_lora.safetensors:0.8"

# Hires Fix で高解像度生成
python generate.py --prompt "masterpiece, best quality, 1girl, detailed" --resolution landscape --hires

# JSON出力（スクリプト連携用）
python generate.py --prompt "masterpiece, best quality, 1girl" --json
```

### LoRA スキャン

Stability Matrix のメタデータから検索可能なインデックスを構築:

```bash
python scan_loras.py
```

`.cm-info.json`（Stability Matrix / CivitAI が生成）を読み取り、`lora_map.json` を作成します。

## コマンドリファレンス

| オプション | 説明 |
|-----------|------|
| `--prompt "..."` | ポジティブプロンプト（必須） |
| `--negative "..."` | ネガティブプロンプト（省略でデフォルト使用） |
| `--resolution NAME` | 解像度プリセット: `square`, `portrait`, `portrait_mid`, `landscape` |
| `--width N` | 幅を直接指定 |
| `--height N` | 高さを直接指定 |
| `--steps N` | サンプリングステップ数（デフォルト: 25） |
| `--cfg N.N` | CFG スケール（デフォルト: 7.0） |
| `--seed N` | ベースシード（省略でランダム） |
| `--checkpoint "..."` | チェックポイントモデルのファイル名 |
| `--lora "file:strength"` | LoRA をファイル名で指定（複数回指定可） |
| `--lora-name "name"` | LoRA をキャラ名で検索（複数回指定可） |
| `--no-face-detailer` | FaceDetailer を無効化 |
| `--hires` | Hires Fix を有効化（Latent アップスケール + 2パス生成） |
| `--hires-scale N.N` | アップスケール倍率（デフォルト: 1.5） |
| `--hires-denoise N.N` | 2パス目の denoise 強度（デフォルト: 0.55） |
| `--hires-steps N` | 2パス目のステップ数（省略でベースと同じ） |
| `--count N` | 生成枚数（デフォルト: 4） |
| `--no-open` | 生成後に画像を自動で開かない |
| `--json` | 結果を JSON で出力 |

## 解像度プリセット

| プリセット | サイズ | 比率 | 用途 |
|-----------|--------|------|------|
| `portrait` | 1024x1536 | 2:3 | 1人の全身、立ち絵 |
| `portrait_mid` | 1152x1536 | 3:4 | 2人構図、ローアングル |
| `landscape` | 1536x1024 | 3:2 | 複数人、風景 |
| `square` | 1024x1024 | 1:1 | 顔アップ、アイコン |

## アーキテクチャ

```
ユーザー入力 → generate.py → ワークフロー JSON 構築 → ComfyUI API → 画像出力
                                       |
                               Checkpoint → LoRA chain → CLIP encode
                               → KSampler → [Hires Fix] → VAEDecode
                               → [FaceDetailer] → SaveImage
```

ワークフローは全て Python で動的に構築。リクエスト内容に応じて LoRA・FaceDetailer・Hires Fix ノードを自動で追加・除外します。

## 設定リファレンス

`config.example.json` に全設定項目のテンプレートがあります:

| セクション | 内容 |
|-----------|------|
| `comfyui` | API サーバーのホスト・ポート |
| `paths` | 出力先、モデルディレクトリ、LoRA マップパス |
| `defaults` | デフォルトのチェックポイント、サンプラー、ステップ数、CFG、解像度、ネガティブプロンプト |
| `face_detailer` | FaceDetailer パラメータ（bbox モデル、denoise、ガイドサイズ） |
| `hires_fix` | Hires Fix デフォルト（倍率、denoise、ステップ数） |
| `resolutions` | 名前付き解像度プリセット |

## ライセンス

MIT

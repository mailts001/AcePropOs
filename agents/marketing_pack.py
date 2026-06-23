"""
MarketingPackAgent — Property photo export pipeline.
Runs on Mac worker (local CPU/MPS). No AI calls — pure image processing.

Stages:
  1. Real-ESRGAN upscale (if available locally)
  2. Stable Diffusion img2img style transform (if diffusers available + MPS/CUDA)
  3. Pillow: crop/resize to 6 platform specs + watermark
  4. FFmpeg: Ken Burns 15-second social video

Falls back gracefully if GPU libs not installed (Pillow-only path always works).
"""

import os
import subprocess
import time
import json
import shutil
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

try:
    import torch
    TORCH_OK = True
    MPS_OK   = torch.backends.mps.is_available()
    CUDA_OK  = torch.cuda.is_available()
except ImportError:
    TORCH_OK = MPS_OK = CUDA_OK = False

try:
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    ESRGAN_OK = True
except ImportError:
    ESRGAN_OK = False

try:
    from diffusers import StableDiffusionImg2ImgPipeline
    DIFFUSERS_OK = True
except ImportError:
    DIFFUSERS_OK = False

FFMPEG_OK = shutil.which("ffmpeg") is not None

PLATFORM_SPECS = {
    "propertyguru": {"w": 1200, "h": 900,  "label": "PropertyGuru / 99.co"},
    "instagram_sq": {"w": 1080, "h": 1080, "label": "Instagram Square"},
    "instagram_st": {"w": 1080, "h": 1920, "label": "Instagram Story"},
    "facebook":     {"w": 1200, "h": 630,  "label": "Facebook / LinkedIn"},
    "whatsapp":     {"w": 800,  "h": 600,  "label": "WhatsApp Preview"},
    "print_hq":     {"w": 3840, "h": 2880, "label": "Print HQ 4K"},
}

WATERMARK_TEXT = "PropOS.sg"


def capabilities() -> dict:
    """Report what processing is available on this machine."""
    return {
        "pillow":    PILLOW_OK,
        "torch":     TORCH_OK,
        "mps":       MPS_OK,
        "cuda":      CUDA_OK,
        "esrgan":    ESRGAN_OK,
        "diffusers": DIFFUSERS_OK,
        "ffmpeg":    FFMPEG_OK,
    }


# ── Stage 1: Upscale with Real-ESRGAN ────────────────────────────────────────

def upscale_esrgan(img_path: str, out_path: str, scale: int = 2) -> str:
    """
    Upscale with Real-ESRGAN. Falls back to Pillow Lanczos if not available.
    Returns path to upscaled image.
    """
    if ESRGAN_OK and TORCH_OK:
        try:
            device = "mps" if MPS_OK else ("cuda" if CUDA_OK else "cpu")
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                            num_block=23, num_grow_ch=32, scale=scale)
            # Download model weights from HuggingFace on first run
            upsampler = RealESRGANer(
                scale=scale, model_path=None,
                dni_weight=None, model=model,
                tile=512, tile_pad=10, pre_pad=0,
                half=(device != "cpu"), device=device,
            )
            import cv2, numpy as np
            img = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
            out, _ = upsampler.enhance(img, outscale=scale)
            cv2.imwrite(out_path, out)
            return out_path
        except Exception as e:
            print(f"[ESRGAN] Error: {e} — falling back to Pillow")

    # Pillow fallback
    if PILLOW_OK:
        img = Image.open(img_path)
        w, h = img.size
        img_up = img.resize((w * scale, h * scale), Image.LANCZOS)
        img_up.save(out_path, quality=95)
        return out_path

    return img_path  # original if nothing works


# ── Stage 2: Stable Diffusion img2img ────────────────────────────────────────

_SD_PIPE = None  # cached pipeline — loaded once per worker session

def sd_img2img(
    img_path: str,
    out_path: str,
    prompt: str,
    negative_prompt: str = "blurry, low quality, distorted, people, text, watermark, cartoon, unrealistic",
    strength: float = 0.45,
    guidance_scale: float = 7.5,
    model_id: str = "runwayml/stable-diffusion-v1-5",
) -> str:
    """
    Style-transform with Stable Diffusion img2img.
    Loads model once, caches in _SD_PIPE.
    Falls back to enhanced Pillow filter if diffusers unavailable.
    """
    global _SD_PIPE

    if DIFFUSERS_OK and TORCH_OK:
        try:
            if _SD_PIPE is None:
                device = "mps" if MPS_OK else ("cuda" if CUDA_OK else "cpu")
                dtype  = torch.float16 if device != "cpu" else torch.float32
                print(f"[SD] Loading pipeline on {device} ({dtype})...")
                _SD_PIPE = StableDiffusionImg2ImgPipeline.from_pretrained(
                    model_id, torch_dtype=dtype, safety_checker=None
                ).to(device)
                if MPS_OK:
                    _SD_PIPE.enable_attention_slicing()

            init_img = Image.open(img_path).convert("RGB").resize((768, 512))
            result   = _SD_PIPE(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=init_img,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=30,
            ).images[0]
            result.save(out_path, quality=95)
            return out_path
        except Exception as e:
            print(f"[SD] Error: {e} — falling back to Pillow enhancement")

    # Pillow enhancement fallback (no AI — but still improves the image)
    return _pillow_enhance(img_path, out_path)


def _pillow_enhance(img_path: str, out_path: str) -> str:
    """Pillow-only enhancement: sharpen, brightness, contrast, colour boost."""
    if not PILLOW_OK:
        shutil.copy(img_path, out_path)
        return out_path
    img = Image.open(img_path).convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Color(img).enhance(1.15)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    img.save(out_path, quality=95)
    return out_path


# ── Stage 3: Platform exports with watermark ─────────────────────────────────

def _add_watermark(img: "Image.Image", text: str = WATERMARK_TEXT) -> "Image.Image":
    draw = ImageDraw.Draw(img)
    w, h = img.size
    font_size = max(16, h // 40)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()
    bbox   = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = font_size
    x, y   = w - tw - margin, h - th - margin
    # Drop shadow
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0, 100), font=font)
    draw.text((x, y),         text, fill=(255, 255, 255, 180), font=font)
    return img


def _smart_crop(img: "Image.Image", target_w: int, target_h: int) -> "Image.Image":
    """Centre-crop to target aspect ratio, then resize."""
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio    = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider — crop sides
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, src_h))
    else:
        # Source is taller — crop top/bottom, bias toward top (ceiling rooms look better)
        new_h = int(src_w / target_ratio)
        img = img.crop((0, 0, src_w, new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)


def export_platforms(
    enhanced_img_path: str,
    result_dir: str,
    watermark: bool = True,
    property_label: str = "",
) -> list[dict]:
    """
    Export to all 6 platform specs. Returns list of output dicts.
    """
    if not PILLOW_OK:
        return [{"error": "Pillow not installed"}]

    out_dir = Path(result_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_img = Image.open(enhanced_img_path).convert("RGB")
    outputs  = []

    for key, spec in PLATFORM_SPECS.items():
        try:
            cropped = _smart_crop(base_img.copy(), spec["w"], spec["h"])
            if watermark and key != "print_hq":
                cropped = _add_watermark(cropped)
            fname  = f"{key}_{spec['w']}x{spec['h']}.jpg"
            fpath  = out_dir / fname
            quality = 98 if key == "print_hq" else 92
            cropped.save(str(fpath), "JPEG", quality=quality, optimize=True)
            outputs.append({
                "platform": key,
                "label":    spec["label"],
                "filename": fname,
                "path":     str(fpath),
                "size_px":  f"{spec['w']}×{spec['h']}",
                "size_bytes": fpath.stat().st_size,
            })
        except Exception as e:
            outputs.append({"platform": key, "error": str(e)})

    return outputs


# ── Stage 4: Ken Burns 15-second video ───────────────────────────────────────

def make_ken_burns_video(
    img_path: str,
    out_path: str,
    duration: int = 15,
    fps: int = 30,
) -> str | None:
    """
    Ken Burns zoom-pan effect using FFmpeg zoompan filter.
    Returns output path or None if FFmpeg unavailable.
    """
    if not FFMPEG_OK:
        return None
    try:
        total_frames = duration * fps
        # Slow zoom from 1.0x to 1.08x, subtle pan upward
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", img_path,
            "-vf", (
                f"zoompan=z='min(zoom+0.0002,1.08)':x='iw/2-(iw/zoom/2)'"
                f":y='ih/2-(ih/zoom/2)-((ih/zoom/2)*on/{total_frames}*0.03)'"
                f":d={total_frames}:s=1080x1080:fps={fps},"
                "format=yuv420p"
            ),
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            out_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path
    except Exception as e:
        print(f"[FFmpeg] Ken Burns error: {e}")
        return None


# ── Full pipeline orchestrator ────────────────────────────────────────────────

def run_pipeline(
    job: dict,
    sd_prompt: str = "",
    negative_prompt: str = "blurry, low quality, distorted, people, text, watermark, cartoon",
    sd_strength: float = 0.45,
    make_video: bool = True,
) -> dict:
    """
    Run the full enhancement pipeline for a job.
    Returns updated outputs list + any errors.
    """
    job_id     = job["job_id"]
    img_path   = job["image_path"]
    result_dir = Path(job["result_dir"])
    result_dir.mkdir(parents=True, exist_ok=True)

    caps    = capabilities()
    outputs = []
    errors  = []
    log     = []

    # ── Step 1: Upscale ───────────────────────────────────────────────────────
    upscaled_path = str(result_dir / f"{job_id}_upscaled.jpg")
    log.append(f"Step 1: Upscaling (ESRGAN={caps['esrgan']}, Pillow fallback={caps['pillow']})")
    try:
        upscaled_path = upscale_esrgan(img_path, upscaled_path, scale=2)
    except Exception as e:
        errors.append(f"Upscale: {e}")
        upscaled_path = img_path

    # ── Step 2: Style transform ───────────────────────────────────────────────
    enhanced_path = str(result_dir / f"{job_id}_enhanced.jpg")
    log.append(f"Step 2: Style transform (SD={caps['diffusers']}, MPS={caps['mps']})")
    if sd_prompt:
        try:
            enhanced_path = sd_img2img(
                upscaled_path, enhanced_path,
                prompt=sd_prompt,
                negative_prompt=negative_prompt,
                strength=sd_strength,
            )
        except Exception as e:
            errors.append(f"SD img2img: {e}")
            enhanced_path = upscaled_path
    else:
        enhanced_path = _pillow_enhance(upscaled_path, enhanced_path)

    # ── Step 3: Platform exports ──────────────────────────────────────────────
    log.append("Step 3: Exporting 6 platform formats")
    try:
        platform_outputs = export_platforms(
            enhanced_path,
            str(result_dir),
            watermark=True,
            property_label=job.get("user_label", ""),
        )
        outputs.extend(platform_outputs)
    except Exception as e:
        errors.append(f"Export: {e}")

    # ── Step 4: Ken Burns video ───────────────────────────────────────────────
    if make_video and caps["ffmpeg"]:
        log.append("Step 4: Generating Ken Burns video")
        video_path = str(result_dir / f"{job_id}_social_video.mp4")
        try:
            vp = make_ken_burns_video(enhanced_path, video_path)
            if vp:
                outputs.append({
                    "platform": "video",
                    "label":    "Social Video (15s Ken Burns)",
                    "filename": Path(video_path).name,
                    "path":     video_path,
                    "size_px":  "1080×1080",
                    "size_bytes": Path(video_path).stat().st_size,
                })
        except Exception as e:
            errors.append(f"Video: {e}")

    # ── Write manifest ────────────────────────────────────────────────────────
    manifest = {
        "job_id":      job_id,
        "completed_at": time.time(),
        "capabilities": caps,
        "outputs":     outputs,
        "errors":      errors,
        "log":         log,
    }
    (result_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest

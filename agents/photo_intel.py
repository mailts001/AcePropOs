"""
PhotoIntelAgent — Claude Vision analysis for property marketing.
Single API call: analyzes interior photo → scene JSON + SD prompt + pipeline config.
Token-efficient: OpenCV pre-screen runs first (free), Claude only called if image passes.
"""

import os
import base64
import json
import time
from pathlib import Path

try:
    import cv2
    import numpy as np
    OPENCV_OK = True
except ImportError:
    OPENCV_OK = False

try:
    import anthropic
    ANTHROPIC_OK = True
except ImportError:
    ANTHROPIC_OK = False


STYLE_PRESETS = {
    "modern":       "modern minimalist interior, clean lines, neutral tones, smart lighting, contemporary furniture",
    "scandinavian": "Scandinavian hygge interior, warm natural wood tones, white walls, cosy textiles, diffused natural light",
    "luxury":       "luxury high-end interior, marble surfaces, statement lighting, designer furniture, rich warm tones, Architectural Digest style",
    "japandi":      "Japandi interior, wabi-sabi aesthetic, natural materials, muted earth palette, zen minimalism, artisanal accents",
    "airbnb":       "bright cheerful Airbnb-ready interior, neutral staging, welcoming warm light, clutter-free, Instagram-worthy composition",
}

PLATFORM_SPECS = {
    "propertyguru": {"w": 1200, "h": 900,  "label": "PropertyGuru / 99.co listing"},
    "instagram_sq": {"w": 1080, "h": 1080, "label": "Instagram Square"},
    "instagram_st": {"w": 1080, "h": 1920, "label": "Instagram Story (9:16)"},
    "facebook":     {"w": 1200, "h": 630,  "label": "Facebook / LinkedIn"},
    "whatsapp":     {"w": 800,  "h": 600,  "label": "WhatsApp Preview"},
    "print_hq":     {"w": 3840, "h": 2880, "label": "Print / HQ (4K)"},
}


def quick_image_check(img_path: str) -> dict:
    """
    OpenCV pre-screen — runs free, before any API call.
    Returns quality flags that inform Claude's prompt.
    """
    result = {
        "blur_score":   999,
        "brightness":   128,
        "is_blurry":    False,
        "is_dark":      False,
        "is_overexposed": False,
        "resolution":   (0, 0),
        "aspect_ratio": "unknown",
        "opencv_ok":    OPENCV_OK,
    }
    if not OPENCV_OK:
        return result
    try:
        img = cv2.imread(str(img_path))
        if img is None:
            return result
        h, w = img.shape[:2]
        result["resolution"] = (w, h)
        result["aspect_ratio"] = f"{round(w/h, 2)}:1"

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        result["blur_score"]   = round(cv2.Laplacian(gray, cv2.CV_64F).var(), 1)
        result["brightness"]   = round(float(np.mean(img)), 1)
        result["is_blurry"]    = result["blur_score"] < 80
        result["is_dark"]      = result["brightness"] < 60
        result["is_overexposed"] = result["brightness"] > 210
    except Exception as e:
        result["error"] = str(e)
    return result


def _encode_image(img_path: str) -> tuple[str, str]:
    """Base64-encode image for Claude vision. Returns (b64, media_type)."""
    ext  = Path(img_path).suffix.lower()
    mime = {"jpg": "image/jpeg", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp"}.get(ext, "image/jpeg")
    data = Path(img_path).read_bytes()
    return base64.standard_b64encode(data).decode("utf-8"), mime


_SYSTEM_PROMPT = """You are a Singapore real estate AI creative director.
You receive interior property photos and output a JSON marketing pipeline plan.
Singapore context: properties are HDB flats, condominiums, or landed houses.
You do NOT generate images. You ONLY analyse, plan and generate prompts.

Output ONLY valid JSON — no markdown fences, no commentary."""


def _build_user_prompt(style: str, property_type: str, qc: dict) -> str:
    style_desc = STYLE_PRESETS.get(style, STYLE_PRESETS["modern"])
    issues = []
    if qc.get("is_blurry"):   issues.append("image is blurry (blur score {:.0f})".format(qc["blur_score"]))
    if qc.get("is_dark"):     issues.append("image is underexposed (brightness {:.0f}/255)".format(qc["brightness"]))
    if qc.get("is_overexposed"): issues.append("image is overexposed (brightness {:.0f}/255)".format(qc["brightness"]))
    issue_str = "; ".join(issues) if issues else "none detected"

    return f"""Analyse this {property_type} interior photo and produce a JSON pipeline plan.

Target style: {style} — "{style_desc}"
Pre-screen issues: {issue_str}
Resolution: {qc.get("resolution", "unknown")}

Return this exact JSON structure:
{{
  "scene_analysis": {{
    "room_type": "living room | bedroom | kitchen | bathroom | dining | other",
    "estimated_property_type": "HDB | Condo | Landed",
    "current_style": "describe current style in 5 words",
    "lighting_quality": "poor | fair | good | excellent",
    "clutter_level": "none | minimal | moderate | heavy",
    "key_elements": ["list up to 5 notable furniture/features"],
    "issues_to_fix": ["list visual issues: clutter, stains, poor light, dated fixtures"],
    "strengths": ["list visual strengths to preserve"],
    "staging_readiness": 0
  }},
  "transformation_goal": "one sentence describing the target marketing look",
  "sd_prompts": {{
    "conservative": "img2img prompt, strength 0.35 — minimal change, clean up only",
    "moderate":     "img2img prompt, strength 0.50 — style upgrade, preserve layout",
    "bold":         "img2img prompt, strength 0.65 — strong restyle, keep structure"
  }},
  "negative_prompt": "blurry, low quality, distorted, people, text, watermark, cartoon",
  "controlnet_mode": "tile | depth | canny",
  "recommended_strength": 0.45,
  "pipeline": [
    {{"step": 1, "tool": "Real-ESRGAN",              "task": "upscale 2x + denoise",         "params": {{}}}},
    {{"step": 2, "tool": "Stable Diffusion img2img", "task": "style transform",              "params": {{"prompt": "use moderate", "strength": 0.45, "controlnet": "tile"}}}},
    {{"step": 3, "tool": "Pillow",                   "task": "crop + resize for 6 platforms","params": {{}}}},
    {{"step": 4, "tool": "FFmpeg",                   "task": "Ken Burns 15s video",          "params": {{"duration": 15, "fps": 30}}}}
  ],
  "social_captions": {{
    "propertyguru": "2-line listing description, professional tone, highlight top 2 features",
    "instagram":    "engaging caption with 5 hashtags, warm tone",
    "facebook":     "2-sentence post, include call-to-action"
  }},
  "estimated_quality_uplift": "low | medium | high"
}}"""


def analyse(
    img_path: str,
    property_type: str = "Condo",
    style: str = "modern",
    api_key: str | None = None,
) -> dict:
    """
    Run OpenCV pre-screen then 1 Claude vision call.
    Returns full pipeline plan dict.
    """
    if not Path(img_path).exists():
        return {"error": f"Image not found: {img_path}"}

    # Step 1: free OpenCV check
    qc = quick_image_check(img_path)

    # Step 2: single Claude vision call
    if not ANTHROPIC_OK:
        return {"error": "anthropic package not installed", "qc": qc}

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"error": "ANTHROPIC_API_KEY not set", "qc": qc}

    try:
        b64, mime = _encode_image(img_path)
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",  "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text",   "text": _build_user_prompt(style, property_type, qc)},
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        plan = json.loads(raw)
        plan["qc"]           = qc
        plan["style"]        = style
        plan["property_type"]= property_type
        plan["analysed_at"]  = time.time()
        plan["input_tokens"] = msg.usage.input_tokens
        plan["output_tokens"]= msg.usage.output_tokens
        return plan
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": raw, "qc": qc}
    except Exception as e:
        return {"error": str(e), "qc": qc}

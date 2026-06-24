#!/usr/bin/env python3
"""
PropOS Mac Worker — runs on your Mac, polls VPS for approved marketing jobs.
Executes full pipeline locally (free: Real-ESRGAN + SD on Apple Silicon MPS).
Pushes results back to VPS. Sends Telegram completion notice.

Usage:
  python3 scripts/mac_worker.py
  python3 scripts/mac_worker.py --vps root@5.223.72.120 --key ~/.ssh/id_ed25519 --once
  python3 scripts/mac_worker.py --dry-run   # analyse only, no image processing

Environment (or .env):
  VPS_HOST               root@5.223.72.120
  VPS_KEY                ~/.ssh/id_ed25519
  VPS_PROPOS_PATH        /root/propos
  ANTHROPIC_API_KEY      sk-ant-...
  TELEGRAM_BOT_TOKEN     ...
  TELEGRAM_ADMIN_CHAT_ID ...
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
VPS_HOST       = os.environ.get("VPS_HOST",         "root@5.223.72.120")
VPS_KEY        = os.environ.get("VPS_KEY",          os.path.expanduser("~/.ssh/id_ed25519"))
VPS_PATH       = os.environ.get("VPS_PROPOS_PATH",  "/root/propos")
POLL_INTERVAL  = int(os.environ.get("WORKER_POLL_SEC", "30"))
BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID  = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
LOCAL_WORK_DIR = Path(__file__).parent.parent / "cache" / "marketing" / "worker_tmp"
LOCAL_WORK_DIR.mkdir(parents=True, exist_ok=True)

WORKER_HOST = subprocess.getoutput("hostname")


def _ssh(cmd: str, debug: bool = False) -> tuple[str, int]:
    """Run command on VPS via SSH. Returns (stdout, returncode)."""
    ssh_cmd = ["ssh", "-i", VPS_KEY, "-o", "StrictHostKeyChecking=no",
               "-o", "ConnectTimeout=10", VPS_HOST, cmd]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True)
    if debug or (result.returncode != 0 and result.stderr):
        print(f"[SSH] rc={result.returncode} stderr={result.stderr.strip()[:200]}")
    return result.stdout.strip(), result.returncode


def _scp_get(remote_path: str, local_path: str) -> bool:
    """Download file from VPS."""
    cmd = ["scp", "-i", VPS_KEY, "-o", "StrictHostKeyChecking=no",
           f"{VPS_HOST}:{remote_path}", local_path]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _scp_put(local_path: str, remote_path: str) -> bool:
    """Upload file to VPS."""
    cmd = ["scp", "-i", VPS_KEY, "-o", "StrictHostKeyChecking=no",
           "-r", local_path, f"{VPS_HOST}:{remote_path}"]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _tg(text: str):
    """Send Telegram message to admin."""
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def heartbeat():
    """Write a heartbeat file to VPS so the dashboard knows worker is online."""
    # Avoid shell quoting issues with JSON — write via Python on the remote side
    ts   = int(time.time())
    host = WORKER_HOST.replace("'", "").replace('"', "")
    cmd  = (
        f"python3 -c \""
        f"import json; "
        f"open('{VPS_PATH}/cache/marketing/worker_heartbeat.json','w')"
        f".write(json.dumps({{'host':'{host}','ts':{ts},'status':'idle'}}))"
        f"\""
    )
    out, rc = _ssh(cmd)
    return rc == 0


def fetch_approved_jobs() -> list[dict]:
    """Fetch list of approved jobs from VPS."""
    out, rc = _ssh(f"ls {VPS_PATH}/cache/marketing/jobs/approved/*.json 2>/dev/null")
    if rc != 0 or not out.strip():
        return []
    jobs = []
    for fpath in out.strip().split("\n"):
        raw, rc2 = _ssh(f"cat {fpath}")
        if rc2 == 0:
            try:
                jobs.append(json.loads(raw))
            except Exception:
                pass
    return jobs


def process_job(job: dict, dry_run: bool = False) -> bool:
    """Download image, run pipeline, upload results, update job status."""
    job_id = job["job_id"]
    print(f"\n[Worker] Processing job {job_id} ({job.get('user_label', '')})")

    # ── 1. Mark as processing on VPS ─────────────────────────────────────────
    _ssh(
        f"cd {VPS_PATH} && .venv/bin/python3 -c \""
        f"import sys; sys.path.insert(0, '.'); "
        f"from data.marketing_pipeline import mark_processing; "
        f"mark_processing('{job_id}', '{WORKER_HOST}')\""
    )

    # ── 2. Download original image ────────────────────────────────────────────
    remote_img = job["image_path"]
    local_img  = str(LOCAL_WORK_DIR / f"{job_id}_original{Path(remote_img).suffix}")
    if not _scp_get(remote_img, local_img):
        print(f"[Worker] ERROR: Could not download image for {job_id}")
        _ssh(
            f"cd {VPS_PATH} && .venv/bin/python3 -c \""
            f"from data.marketing_pipeline import mark_failed; "
            f"mark_failed('{job_id}', 'SCP download failed')\""
        )
        return False

    if dry_run:
        print(f"[Worker] Dry run — skipping pipeline for {job_id}")
        print(f"[Worker] Image downloaded to: {local_img}")
        return True

    # ── 3. Run Claude vision analysis ────────────────────────────────────────
    print(f"[Worker] Analysing with Claude vision...")
    try:
        from agents.photo_intel import analyse
        plan = analyse(
            local_img,
            property_type=job.get("property_type", "Condo"),
            style=job.get("style", "modern"),
        )
        if plan.get("error"):
            print(f"[Worker] Analysis warning: {plan['error']} — using default prompt")
        sd_prompt     = plan.get("sd_prompts", {}).get("moderate", "")
        neg_prompt    = plan.get("negative_prompt", "blurry, low quality, distorted")
        sd_strength   = plan.get("recommended_strength", 0.45)
        scene_analysis = plan.get("scene_analysis", {})
        print(f"[Worker] Scene: {scene_analysis.get('room_type','?')} | "
              f"Style: {scene_analysis.get('current_style','?')} | "
              f"Tokens used: {plan.get('input_tokens',0)+plan.get('output_tokens',0)}")
    except Exception as e:
        print(f"[Worker] Analysis failed: {e} — using fallback prompt")
        from agents.photo_intel import STYLE_PRESETS
        sd_prompt   = STYLE_PRESETS.get(job.get("style", "modern"), "")
        neg_prompt  = "blurry, low quality, distorted, people, text, watermark"
        sd_strength = 0.45
        scene_analysis = {}
        plan = {}

    # ── 4. Run local image pipeline ──────────────────────────────────────────
    print(f"[Worker] Running pipeline (upscale → SD img2img → export → video)...")
    local_result_dir = str(LOCAL_WORK_DIR / job_id)
    local_job = {**job, "image_path": local_img, "result_dir": local_result_dir}
    try:
        from agents.marketing_pack import run_pipeline, capabilities
        caps = capabilities()
        print(f"[Worker] Capabilities: {caps}")
        manifest = run_pipeline(
            local_job,
            sd_prompt=sd_prompt,
            negative_prompt=neg_prompt,
            sd_strength=sd_strength,
            make_video=True,
        )
        print(f"[Worker] Pipeline done. Outputs: {len(manifest.get('outputs', []))}")
        if manifest.get("errors"):
            print(f"[Worker] Non-fatal errors: {manifest['errors']}")
    except Exception as e:
        print(f"[Worker] Pipeline FAILED: {e}")
        _ssh(
            f"cd {VPS_PATH} && .venv/bin/python3 -c \""
            f"from data.marketing_pipeline import mark_failed; "
            f"mark_failed('{job_id}', '{str(e)[:200]}')\""
        )
        _tg(f"❌ *Marketing job failed*\nJob: `{job_id}`\nError: {str(e)[:200]}")
        return False

    # ── 5. Upload results to VPS ──────────────────────────────────────────────
    remote_result_dir = f"{VPS_PATH}/cache/marketing/results/{job_id}"
    _ssh(f"mkdir -p {remote_result_dir}")
    if not _scp_put(local_result_dir, remote_result_dir + "/"):
        print(f"[Worker] WARNING: upload may be incomplete")

    # ── 6. Mark done on VPS ──────────────────────────────────────────────────
    outputs_json = json.dumps(manifest.get("outputs", [])).replace("'", "\\'").replace('"', '\\"')
    _ssh(
        f"cd {VPS_PATH} && .venv/bin/python3 -c \""
        f"import json; "
        f"from data.marketing_pipeline import mark_done; "
        f"mark_done('{job_id}', json.loads('{outputs_json}'))\""
    )

    # Sync the updated done-job JSON back to Mac so dashboard can see it
    mac_jobs_done = Path(__file__).parent.parent / "cache" / "marketing" / "jobs" / "done"
    mac_jobs_done.mkdir(parents=True, exist_ok=True)
    local_job_json = mac_jobs_done / f"{job_id}.json"
    _scp_get(
        f"{VPS_PATH}/cache/marketing/jobs/done/{job_id}.json",
        str(local_job_json),
    )
    # Patch result_dir to Mac-local path so dashboard's get_result_files() works
    if local_job_json.exists():
        _jdata = json.loads(local_job_json.read_text())
        mac_result_path = Path(__file__).parent.parent / "cache" / "marketing" / "results" / job_id
        _jdata["result_dir"] = str(mac_result_path)
        local_job_json.write_text(json.dumps(_jdata, indent=2))

    # ── 7. Notify via Telegram ────────────────────────────────────────────────
    n_files = len([o for o in manifest.get("outputs", []) if not o.get("error")])
    _tg(
        f"✅ *Marketing pack ready!*\n"
        f"Job: `{job_id}`\n"
        f"Label: {job.get('user_label', '')}\n"
        f"Files: {n_files} exports + video\n"
        f"Download from PropOS dashboard → Marketing Studio"
    )

    # ── 8. Copy results to Mac cache so dashboard can serve them ─────────────
    import shutil
    mac_result_dir = Path(__file__).parent.parent / "cache" / "marketing" / "results" / job_id
    mac_result_dir.mkdir(parents=True, exist_ok=True)
    for _f in Path(local_result_dir).glob("*.*"):
        shutil.copy2(str(_f), str(mac_result_dir / _f.name))
    print(f"[Worker] 📁 Results copied to {mac_result_dir}")

    # ── 9. Clean up temp working dir ─────────────────────────────────────────
    shutil.rmtree(local_result_dir, ignore_errors=True)
    Path(local_img).unlink(missing_ok=True)
    print(f"[Worker] ✅ Job {job_id} complete — {n_files} files uploaded")
    return True


def main():
    global VPS_HOST, VPS_KEY   # must be first — before any use of these names
    parser = argparse.ArgumentParser(description="PropOS Mac Worker")
    parser.add_argument("--vps",      default=VPS_HOST,  help="VPS SSH target")
    parser.add_argument("--key",      default=VPS_KEY,   help="SSH key path")
    parser.add_argument("--once",     action="store_true", help="Process one batch then exit")
    parser.add_argument("--dry-run",  action="store_true", help="Download+analyse only, no pipeline")
    args = parser.parse_args()

    VPS_HOST = args.vps
    VPS_KEY  = args.key

    print(f"[Worker] PropOS Mac Worker starting on {WORKER_HOST}")
    print(f"[Worker] VPS: {VPS_HOST} | Poll interval: {POLL_INTERVAL}s")
    print(f"[Worker] Dry run: {args.dry_run}")

    while True:
        try:
            # Heartbeat
            if heartbeat():
                print(f"[Worker] ❤️  Heartbeat OK — {time.strftime('%H:%M:%S')}")
            else:
                print(f"[Worker] ⚠️  Heartbeat failed — VPS unreachable")

            # Fetch and process approved jobs
            jobs = fetch_approved_jobs()
            if jobs:
                print(f"[Worker] 📋 {len(jobs)} approved job(s) found")
                for job in jobs:
                    process_job(job, dry_run=args.dry_run)
            else:
                print(f"[Worker] 💤 No pending jobs")

        except KeyboardInterrupt:
            print("\n[Worker] Stopped by user.")
            break
        except Exception as e:
            print(f"[Worker] Unhandled error: {e}")

        if args.once:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

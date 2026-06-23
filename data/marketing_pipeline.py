"""
Marketing Studio — Job Queue Manager
File-based job queue stored in cache/marketing/jobs/{status}/
Statuses: pending → approved → processing → done | rejected | failed

Job JSON schema:
{
  "job_id": str,
  "created_at": float,
  "status": str,
  "property_type": str,   # "HDB 4-room", "Condo", "Landed", etc.
  "style": str,           # "modern", "scandinavian", "luxury", "japandi", "airbnb"
  "user_label": str,      # user-supplied label, e.g. "Geylang 4-room listing"
  "image_path": str,      # abs path to original upload
  "result_dir": str,      # abs path to output folder (populated after done)
  "scene_analysis": dict, # populated by PhotoIntelAgent
  "sd_prompt": str,       # populated by PhotoIntelAgent
  "pipeline_config": dict,# tool list + params
  "approved_at": float | null,
  "completed_at": float | null,
  "outputs": list[dict],  # [{filename, format, platform, size_bytes}]
  "error": str | null,
  "worker_host": str | null,
}
"""

import json
import uuid
import time
import shutil
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent / "cache" / "marketing"
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"

for _d in (BASE_DIR / "jobs" / s for s in ("pending", "approved", "processing", "done", "rejected", "failed")):
    _d.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def _job_path(job_id: str, status: str) -> Path:
    return BASE_DIR / "jobs" / status / f"{job_id}.json"


def create_job(
    image_bytes: bytes,
    image_filename: str,
    property_type: str = "Condo",
    style: str = "modern",
    user_label: str = "",
) -> dict:
    """Save uploaded image + create pending job. Returns job dict."""
    job_id    = str(uuid.uuid4())[:12]
    ext       = Path(image_filename).suffix.lower() or ".jpg"
    img_path  = UPLOAD_DIR / f"{job_id}_original{ext}"
    img_path.write_bytes(image_bytes)

    job = {
        "job_id":        job_id,
        "created_at":    time.time(),
        "status":        "pending",
        "property_type": property_type,
        "style":         style,
        "user_label":    user_label or image_filename,
        "image_path":    str(img_path),
        "result_dir":    str(RESULT_DIR / job_id),
        "scene_analysis": {},
        "sd_prompt":     "",
        "pipeline_config": {},
        "approved_at":   None,
        "completed_at":  None,
        "outputs":       [],
        "error":         None,
        "worker_host":   None,
    }
    _job_path(job_id, "pending").write_text(json.dumps(job, indent=2))
    return job


def get_job(job_id: str) -> dict | None:
    """Find a job regardless of its current status folder."""
    for status in ("pending", "approved", "processing", "done", "rejected", "failed"):
        p = _job_path(job_id, status)
        if p.exists():
            return json.loads(p.read_text())
    return None


def list_jobs(status: str | None = None) -> list[dict]:
    """List all jobs, optionally filtered by status. Sorted newest first."""
    statuses = [status] if status else ("pending", "approved", "processing", "done", "rejected", "failed")
    jobs = []
    for s in statuses:
        for f in (BASE_DIR / "jobs" / s).glob("*.json"):
            try:
                jobs.append(json.loads(f.read_text()))
            except Exception:
                pass
    return sorted(jobs, key=lambda j: j.get("created_at", 0), reverse=True)


def update_job(job: dict, new_status: str | None = None) -> dict:
    """
    Update job fields and optionally move it to a new status folder.
    Pass the full modified job dict.
    """
    old_status = job["status"]
    if new_status and new_status != old_status:
        # Remove from old folder
        old_path = _job_path(job["job_id"], old_status)
        if old_path.exists():
            old_path.unlink()
        job["status"] = new_status

    _job_path(job["job_id"], job["status"]).write_text(json.dumps(job, indent=2))
    return job


def approve_job(job_id: str) -> dict | None:
    job = get_job(job_id)
    if not job or job["status"] != "pending":
        return None
    job["approved_at"] = time.time()
    return update_job(job, "approved")


def reject_job(job_id: str) -> dict | None:
    job = get_job(job_id)
    if not job:
        return None
    return update_job(job, "rejected")


def mark_processing(job_id: str, worker_host: str = "") -> dict | None:
    job = get_job(job_id)
    if not job or job["status"] != "approved":
        return None
    job["worker_host"] = worker_host
    return update_job(job, "processing")


def mark_done(job_id: str, outputs: list[dict], scene_analysis: dict = None,
              sd_prompt: str = "") -> dict | None:
    job = get_job(job_id)
    if not job:
        return None
    job["completed_at"] = time.time()
    job["outputs"] = outputs
    if scene_analysis:
        job["scene_analysis"] = scene_analysis
    if sd_prompt:
        job["sd_prompt"] = sd_prompt
    return update_job(job, "done")


def mark_failed(job_id: str, error: str) -> dict | None:
    job = get_job(job_id)
    if not job:
        return None
    job["error"] = error
    return update_job(job, "failed")


def get_result_files(job: dict) -> list[Path]:
    """Return all output files for a completed job."""
    result_dir = Path(job.get("result_dir", ""))
    if not result_dir.exists():
        return []
    return sorted(result_dir.glob("*.*"))


def cleanup_old_jobs(days: int = 7):
    """Remove jobs and their files older than `days` days."""
    cutoff = time.time() - days * 86400
    for status in ("done", "rejected", "failed"):
        for f in (BASE_DIR / "jobs" / status).glob("*.json"):
            try:
                job = json.loads(f.read_text())
                if job.get("created_at", 0) < cutoff:
                    # Remove result dir
                    rd = Path(job.get("result_dir", ""))
                    if rd.exists():
                        shutil.rmtree(rd, ignore_errors=True)
                    # Remove original upload
                    ip = Path(job.get("image_path", ""))
                    if ip.exists():
                        ip.unlink(missing_ok=True)
                    f.unlink()
            except Exception:
                pass

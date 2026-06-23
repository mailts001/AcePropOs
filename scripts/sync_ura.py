#!/usr/bin/env python3
"""
Sync all URA data: private sale transactions (4 batches) + rental medians.
Run once manually, then cron handles weekly refresh automatically.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
print(f"[URA Sync] Starting at {datetime.now().isoformat()}")

# ── 1. Private sale transactions (4 quarterly batches) ────────────────────────
from data.ura_pipeline import sync_all_batches
try:
    sync_all_batches()
    print("[URA Sync] Sale transactions ✓")
except Exception as e:
    print(f"[URA Sync] Sale transactions failed: {e}")

# ── 2. Rental median data (district × bedroom × quarter) ─────────────────────
from data.ura_rental_pipeline import fetch_rental_medians
try:
    medians = fetch_rental_medians(force=True)
    print(f"[URA Sync] Rental medians: {len(medians)} records ✓")
except Exception as e:
    print(f"[URA Sync] Rental medians failed: {e}")

print("[URA Sync] Done.")

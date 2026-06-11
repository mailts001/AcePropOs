#!/usr/bin/env python3
"""
Sync URA rental data: individual transactions (4 batches) + quarterly medians.
Run weekly via cron. Takes ~30 seconds.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from data.ura_rental_pipeline import fetch_rental_transactions, fetch_rental_medians
from datetime import datetime

print(f"[URA Rentals] Starting sync at {datetime.now().isoformat()}")

# Step 1: Quarterly median rents (free tier — works reliably)
try:
    medians = fetch_rental_medians(force=True)
    print(f"[URA Rentals] Median records: {len(medians)} ✓")
except Exception as e:
    print(f"[URA Rentals] Medians failed: {e}")

# Step 2: Individual rental transactions (may require higher URA access tier)
total = 0
for batch in range(1, 5):
    try:
        txns = fetch_rental_transactions(batch, force=True)
        total += len(txns)
        print(f"[URA Rentals] Batch {batch}: {len(txns)} rental transactions ✓")
    except Exception as e:
        print(f"[URA Rentals] Batch {batch} skipped ({e}) — median data is sufficient for yield display")

print(f"[URA Rentals] Done. Total rental transactions: {total}")

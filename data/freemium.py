"""
Freemium tier gating for PropOS.
Free tier:  3 watchlist alerts per week, basic features only.
Paid tier:  unlimited alerts, PDF reports, comparison tool, rental intel.
Stored in SQLite alongside user profile.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "propos.db"

TIERS = {
    "free": {
        "label": "Free",
        "price_sgd": 0,
        "watchlist_alerts_per_week": 3,
        "pdf_reports": False,
        "comparison_tool": True,   # visible but limited to 2 props
        "rental_intel": False,
        "en_bloc_scan": False,
    },
    "pro": {
        "label": "Pro — SGD 9.90/month",
        "price_sgd": 9.90,
        "watchlist_alerts_per_week": 999,
        "pdf_reports": True,
        "comparison_tool": True,
        "rental_intel": True,
        "en_bloc_scan": True,
    },
}

UPGRADE_CTA = (
    "🔒 **Free tier limit reached** — upgrade to **PropOS Pro (SGD 9.90/month)** "
    "for unlimited alerts, PDF reports, rental intelligence and en-bloc scanning. "
    "Contact [@AcePropOS_bot](https://t.me/AcePropOS_bot) to upgrade."
)


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tiers (
                telegram_id TEXT PRIMARY KEY,
                tier TEXT DEFAULT 'free',
                upgraded_at TEXT,
                expires_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT,
                alerted_at TEXT DEFAULT (datetime('now')),
                watch_id INTEGER
            )
        """)
        conn.commit()


def get_tier(telegram_id: str) -> str:
    """Return 'free' or 'pro' for a user."""
    ensure_schema()
    with _get_db() as conn:
        row = conn.execute(
            "SELECT tier, expires_at FROM user_tiers WHERE telegram_id=?",
            (str(telegram_id),)
        ).fetchone()
    if not row:
        return "free"
    if row["expires_at"]:
        try:
            if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return "free"  # expired
        except Exception:
            pass
    return row["tier"]


def set_tier(telegram_id: str, tier: str, months: int = 1):
    """Upgrade or downgrade a user's tier."""
    ensure_schema()
    expires = (datetime.utcnow() + timedelta(days=30 * months)).isoformat() if tier == "pro" else None
    with _get_db() as conn:
        conn.execute("""
            INSERT INTO user_tiers (telegram_id, tier, upgraded_at, expires_at)
            VALUES (?, ?, datetime('now'), ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                tier=excluded.tier,
                upgraded_at=excluded.upgraded_at,
                expires_at=excluded.expires_at
        """, (str(telegram_id), tier, expires))
        conn.commit()


def alerts_this_week(telegram_id: str) -> int:
    """Count alerts sent to a user in the last 7 days."""
    ensure_schema()
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM alert_usage WHERE telegram_id=? AND alerted_at > ?",
            (str(telegram_id), week_ago)
        ).fetchone()
    return row["cnt"] if row else 0


def can_send_alert(telegram_id: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Free users capped at 3 alerts/week.
    """
    tier = get_tier(telegram_id)
    limit = TIERS[tier]["watchlist_alerts_per_week"]
    used = alerts_this_week(telegram_id)
    if used >= limit:
        return False, UPGRADE_CTA
    return True, ""


def record_alert(telegram_id: str, watch_id: int):
    """Log that an alert was sent."""
    ensure_schema()
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO alert_usage (telegram_id, watch_id) VALUES (?, ?)",
            (str(telegram_id), watch_id)
        )
        conn.commit()


def tier_info(telegram_id: str) -> dict:
    """Full tier info for display."""
    tier = get_tier(telegram_id)
    info = dict(TIERS[tier])
    info["tier"] = tier
    info["alerts_used_this_week"] = alerts_this_week(telegram_id)
    info["telegram_id"] = telegram_id
    return info


def can_use_feature(telegram_id: str, feature: str) -> tuple[bool, str]:
    """
    Check if a user can use a gated feature.
    feature: 'pdf_reports' | 'rental_intel' | 'en_bloc_scan'
    """
    tier = get_tier(telegram_id)
    allowed = TIERS[tier].get(feature, False)
    if not allowed:
        return False, UPGRADE_CTA
    return True, ""

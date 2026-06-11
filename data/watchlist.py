"""
Watchlist — SQLite-backed property price alerts.
Users save town/flat-type/max-price. Checker fires email+Telegram when
new HDB transactions match criteria below the threshold.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "propos.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_watchlist_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                label TEXT,
                property_type TEXT NOT NULL DEFAULT 'HDB',
                town TEXT,
                flat_type TEXT,
                street_keyword TEXT,
                max_price_sgd REAL,
                min_floor_sqm REAL,
                alert_on_below_market BOOLEAN DEFAULT 1,
                alert_threshold_pct REAL DEFAULT 5.0,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                last_alerted_at TEXT,
                last_checked_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watchlist_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                transaction_key TEXT NOT NULL,
                town TEXT,
                street TEXT,
                flat_type TEXT,
                price_sgd REAL,
                psf REAL,
                market_psf REAL,
                discount_pct REAL,
                alert_sent_at TEXT DEFAULT (datetime('now')),
                channel TEXT DEFAULT 'telegram',
                UNIQUE(watchlist_id, transaction_key)
            )
        """)
        c.commit()


def add_watch(
    user_id: str,
    label: str,
    town: str | None = None,
    flat_type: str | None = None,
    street_keyword: str | None = None,
    max_price_sgd: float | None = None,
    min_floor_sqm: float | None = None,
    alert_threshold_pct: float = 5.0,
) -> int:
    """Add a watchlist entry. Returns new row id."""
    init_watchlist_db()
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO watchlist
              (user_id, label, town, flat_type, street_keyword, max_price_sgd,
               min_floor_sqm, alert_threshold_pct)
            VALUES (?,?,?,?,?,?,?,?)
        """, (user_id, label, town, flat_type, street_keyword,
              max_price_sgd, min_floor_sqm, alert_threshold_pct))
        c.commit()
        return cur.lastrowid


def list_watches(user_id: str) -> list[dict]:
    init_watchlist_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM watchlist WHERE user_id=? AND is_active=1 ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_watch(watch_id: int, user_id: str) -> bool:
    with _conn() as c:
        c.execute(
            "UPDATE watchlist SET is_active=0 WHERE id=? AND user_id=?",
            (watch_id, user_id)
        )
        c.commit()
        return c.execute("SELECT changes()").fetchone()[0] > 0


def check_watchlist() -> list[dict]:
    """
    Run against cached HDB data. Returns list of alert dicts to send.
    Designed to be called by cron or background thread.
    """
    init_watchlist_db()

    # Load HDB cache
    cache_path = Path(__file__).parent.parent / "cache" / "hdb" / "resale.json"
    if not cache_path.exists():
        return []

    with open(cache_path) as f:
        records = json.load(f)

    # Only look at last 30 days of transactions
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m")
    recent = [r for r in records if r.get("month", "") >= cutoff]
    if not recent:
        recent = records[:500]  # fallback: last 500 records

    # Build PSF lookup: town+flat_type → median PSF
    from collections import defaultdict
    import statistics
    psf_by_group: dict[tuple, list] = defaultdict(list)
    for r in records:
        try:
            area = float(r.get("floor_area_sqm", 0))
            price = float(r.get("resale_price", 0))
            if area > 0 and price > 0:
                psf = price / area * 10.764  # sqm → sqft
                psf_by_group[(r.get("town", ""), r.get("flat_type", ""))].append(psf)
        except Exception:
            pass

    median_psf: dict[tuple, float] = {
        k: statistics.median(v) for k, v in psf_by_group.items() if v
    }

    with _conn() as db:
        watches = db.execute(
            "SELECT * FROM watchlist WHERE is_active=1"
        ).fetchall()
        watches = [dict(w) for w in watches]

    alerts = []
    for watch in watches:
        for rec in recent:
            if not _matches(watch, rec):
                continue

            try:
                area = float(rec.get("floor_area_sqm", 0))
                price = float(rec.get("resale_price", 0))
                if area <= 0 or price <= 0:
                    continue
                psf = price / area * 10.764

                key = (rec.get("town", ""), rec.get("flat_type", ""))
                mkt_psf = median_psf.get(key, psf)
                discount_pct = (mkt_psf - psf) / mkt_psf * 100 if mkt_psf else 0

                # Only alert if it's a genuine below-market deal
                if watch["alert_on_below_market"] and discount_pct < watch["alert_threshold_pct"]:
                    continue

                # Also alert if price is under max_price threshold
                price_alert = watch["max_price_sgd"] and price <= watch["max_price_sgd"]
                if not (watch["alert_on_below_market"] and discount_pct >= watch["alert_threshold_pct"]) and not price_alert:
                    continue

                tx_key = f"{rec.get('month')}-{rec.get('block')}-{rec.get('street_name')}-{rec.get('flat_type')}-{price}"

                # Check not already alerted
                with _conn() as db:
                    exists = db.execute(
                        "SELECT 1 FROM watchlist_alerts WHERE watchlist_id=? AND transaction_key=?",
                        (watch["id"], tx_key)
                    ).fetchone()
                    if exists:
                        continue

                    db.execute("""
                        INSERT OR IGNORE INTO watchlist_alerts
                          (watchlist_id, user_id, transaction_key, town, street,
                           flat_type, price_sgd, psf, market_psf, discount_pct)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    """, (watch["id"], watch["user_id"], tx_key,
                          rec.get("town"), rec.get("street_name"),
                          rec.get("flat_type"), price,
                          round(psf, 0), round(mkt_psf, 0), round(discount_pct, 1)))
                    db.commit()

                alerts.append({
                    "watch_id": watch["id"],
                    "user_id": watch["user_id"],
                    "label": watch["label"],
                    "town": rec.get("town"),
                    "block": rec.get("block"),
                    "street": rec.get("street_name"),
                    "flat_type": rec.get("flat_type"),
                    "storey": rec.get("storey_range"),
                    "area_sqm": area,
                    "price_sgd": price,
                    "psf": round(psf, 0),
                    "market_psf": round(mkt_psf, 0),
                    "discount_pct": round(discount_pct, 1),
                    "month": rec.get("month"),
                    "price_alert": price_alert,
                })
            except Exception:
                continue

        # Update last_checked_at
        with _conn() as db:
            db.execute(
                "UPDATE watchlist SET last_checked_at=datetime('now') WHERE id=?",
                (watch["id"],)
            )
            db.commit()

    return alerts


def _matches(watch: dict, rec: dict) -> bool:
    if watch["town"] and watch["town"].upper() not in rec.get("town", "").upper():
        return False
    if watch["flat_type"] and watch["flat_type"].upper() not in rec.get("flat_type", "").upper():
        return False
    if watch["street_keyword"]:
        if watch["street_keyword"].upper() not in rec.get("street_name", "").upper():
            return False
    if watch["min_floor_sqm"]:
        try:
            if float(rec.get("floor_area_sqm", 0)) < watch["min_floor_sqm"]:
                return False
        except Exception:
            return False
    return True


def format_alert_message(alert: dict) -> str:
    """Format a single alert for Telegram/email."""
    lines = [
        f"🔔 *Watchlist Alert* — {alert['label']}",
        f"",
        f"🏠 {alert['block']} {alert['street']} ({alert['flat_type']})",
        f"📍 {alert['town']} · {alert['storey']} · {alert['area_sqm']:.0f} sqm",
        f"",
        f"💰 Price: *SGD {alert['price_sgd']:,.0f}*",
        f"📊 PSF: SGD {alert['psf']:,.0f} vs market SGD {alert['market_psf']:,.0f}",
    ]
    if alert["discount_pct"] >= 5:
        lines.append(f"🟢 *{alert['discount_pct']:.1f}% below market* — potential deal!")
    if alert["price_alert"]:
        lines.append(f"💡 Under your max price target")
    lines += ["", f"📅 Transacted: {alert['month']}"]
    return "\n".join(lines)

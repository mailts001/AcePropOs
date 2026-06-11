"""
PropOS Visitor Analytics — lightweight SQLite-based event tracking.
Tracks: page views, feature usage, session duration, broker leads.
IP-based deduplication for unique visitor counts.
No PII stored beyond Telegram ID (when user provides it) and IP hash.
"""

import sqlite3
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "propos.db"

# Known Singapore ISP/corporate IP ranges (rough detection)
# If first 2 octets match, flag as likely corporate
_CORP_PREFIXES = {
    "202.186", "202.188", "203.116", "203.127", "210.49",  # SG telcos
    "128.106", "137.132", "155.69", "175.176",              # SG universities/govt
}


def _ip_hash(ip: str) -> str:
    """One-way hash IP for privacy — can count uniques without storing raw IP."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _classify_visitor(ip: str) -> str:
    """Rough classification: 'consumer', 'corporate', or 'unknown'."""
    if not ip or ip in ("127.0.0.1", "localhost", "::1"):
        return "local"
    prefix = ".".join(ip.split(".")[:2])
    if prefix in _CORP_PREFIXES:
        return "corporate"
    # Private ranges = likely behind NAT/VPN
    if ip.startswith(("10.", "172.16.", "192.168.")):
        return "internal"
    return "consumer"


def ensure_schema():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS page_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                session_id TEXT,
                ip_hash TEXT,
                visitor_type TEXT,
                page TEXT,
                feature TEXT,
                duration_sec INTEGER DEFAULT 0,
                telegram_id TEXT,
                email TEXT,
                referrer TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pv_ts ON page_views(ts);
            CREATE INDEX IF NOT EXISTS idx_pv_page ON page_views(page);
            CREATE INDEX IF NOT EXISTS idx_pv_session ON page_views(session_id);

            CREATE TABLE IF NOT EXISTS broker_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                name TEXT, email TEXT, phone TEXT,
                loan_sgd REAL, prop_type TEXT,
                timeline TEXT, notes TEXT,
                ip_hash TEXT, session_id TEXT
            );

            CREATE TABLE IF NOT EXISTS feature_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                session_id TEXT,
                ip_hash TEXT,
                feature TEXT,
                action TEXT,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                subscribed_at TEXT DEFAULT (datetime('now')),
                welcome_sent INTEGER DEFAULT 0,
                source TEXT DEFAULT 'sidebar',
                active INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_sub_email ON subscribers(email);
        """)


def track_pageview(
    page: str,
    session_id: str = "",
    ip: str = "",
    telegram_id: str = "",
    email: str = "",
    referrer: str = "",
    duration_sec: int = 0,
    feature: str = "",
):
    """Log a page view / feature usage event."""
    ensure_schema()
    ip_h = _ip_hash(ip) if ip else ""
    vtype = _classify_visitor(ip)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO page_views (session_id,ip_hash,visitor_type,page,feature,duration_sec,telegram_id,email,referrer) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, ip_h, vtype, page, feature, duration_sec, telegram_id, email, referrer)
        )


def track_feature(session_id: str, feature: str, action: str, value: str = "", ip: str = ""):
    """Log a specific feature interaction (button click, form submit, etc.)."""
    ensure_schema()
    ip_h = _ip_hash(ip) if ip else ""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO feature_events (session_id,ip_hash,feature,action,value) VALUES (?,?,?,?,?)",
            (session_id, ip_h, feature, action, value)
        )


def log_broker_lead(name, email, phone, loan_sgd, prop_type, timeline, notes, session_id="", ip=""):
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO broker_leads (name,email,phone,loan_sgd,prop_type,timeline,notes,ip_hash,session_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, email, phone, loan_sgd, prop_type, timeline, notes, _ip_hash(ip) if ip else "", session_id)
        )


# ── Analytics queries ──────────────────────────────────────────────────────────

def get_summary(days: int = 30) -> dict:
    """High-level stats for admin dashboard."""
    ensure_schema()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        total_views = conn.execute("SELECT COUNT(*) FROM page_views WHERE ts > ?", (since,)).fetchone()[0]
        unique_sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM page_views WHERE ts > ? AND session_id != ''", (since,)).fetchone()[0]
        unique_ips = conn.execute("SELECT COUNT(DISTINCT ip_hash) FROM page_views WHERE ts > ? AND ip_hash != ''", (since,)).fetchone()[0]
        by_page = conn.execute(
            "SELECT page, COUNT(*) as cnt FROM page_views WHERE ts > ? GROUP BY page ORDER BY cnt DESC", (since,)
        ).fetchall()
        by_type = conn.execute(
            "SELECT visitor_type, COUNT(DISTINCT ip_hash) as cnt FROM page_views WHERE ts > ? GROUP BY visitor_type", (since,)
        ).fetchall()
        by_day = conn.execute(
            "SELECT substr(ts,1,10) as day, COUNT(*) as cnt FROM page_views WHERE ts > ? GROUP BY day ORDER BY day", (since,)
        ).fetchall()
        top_features = conn.execute(
            "SELECT feature, COUNT(*) as cnt FROM feature_events WHERE ts > ? AND feature != '' GROUP BY feature ORDER BY cnt DESC LIMIT 10", (since,)
        ).fetchall()
        broker_leads_count = conn.execute("SELECT COUNT(*) FROM broker_leads WHERE ts > ?", (since,)).fetchone()[0]
        emails_captured = conn.execute("SELECT COUNT(DISTINCT email) FROM page_views WHERE ts > ? AND email != ''", (since,)).fetchone()[0]
        telegram_users = conn.execute("SELECT COUNT(DISTINCT telegram_id) FROM page_views WHERE ts > ? AND telegram_id != ''", (since,)).fetchone()[0]
        returning = conn.execute(
            "SELECT COUNT(DISTINCT ip_hash) FROM page_views WHERE ip_hash IN "
            "(SELECT ip_hash FROM page_views WHERE ts < ? GROUP BY ip_hash) AND ts > ?", (since, since)
        ).fetchone()[0]
        avg_pages = conn.execute(
            "SELECT AVG(cnt) FROM (SELECT session_id, COUNT(*) as cnt FROM page_views WHERE ts > ? AND session_id != '' GROUP BY session_id)", (since,)
        ).fetchone()[0] or 0

    return {
        "days": days,
        "total_views": total_views,
        "unique_sessions": unique_sessions,
        "unique_visitors_ip": unique_ips,
        "returning_visitors": returning,
        "avg_pages_per_session": round(avg_pages, 1),
        "broker_leads": broker_leads_count,
        "emails_captured": emails_captured,
        "telegram_users": telegram_users,
        "by_page": [{"page": r["page"], "views": r["cnt"]} for r in by_page],
        "by_visitor_type": {r["visitor_type"]: r["cnt"] for r in by_type},
        "by_day": [{"date": r["day"], "views": r["cnt"]} for r in by_day],
        "top_features": [{"feature": r["feature"], "uses": r["cnt"]} for r in top_features],
    }


def get_engaged_sessions(days: int = 30, min_pages: int = 3) -> list[dict]:
    """Sessions that viewed 3+ pages — likely serious users."""
    ensure_schema()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                session_id,
                COUNT(*) as page_count,
                GROUP_CONCAT(DISTINCT page) as pages_visited,
                MAX(telegram_id) as telegram_id,
                MAX(email) as email,
                visitor_type,
                MIN(ts) as first_seen,
                MAX(ts) as last_seen
            FROM page_views
            WHERE ts > ? AND session_id != ''
            GROUP BY session_id
            HAVING page_count >= ?
            ORDER BY page_count DESC
            LIMIT 100
        """, (since, min_pages)).fetchall()
    return [dict(r) for r in rows]


def get_broker_leads(days: int = 90) -> list[dict]:
    """All broker referral leads."""
    ensure_schema()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM broker_leads WHERE ts > ? ORDER BY ts DESC", (since,)
        ).fetchall()
    return [dict(r) for r in rows]


def ai_visitor_summary(stats: dict, engaged: list[dict]) -> str:
    """
    Generate a plain-text AI summary of visitor patterns for admin.
    Rule-based (no API cost) — just interprets the data.
    """
    lines = []
    total = stats["unique_visitors_ip"] or 1
    corp_pct = round(stats["by_visitor_type"].get("corporate", 0) / total * 100)
    consumer_pct = round(stats["by_visitor_type"].get("consumer", 0) / total * 100)
    top_pages = [p["page"] for p in stats["by_page"][:3]]
    tg_users = stats["telegram_users"]
    leads = stats["broker_leads"]
    emails = stats["emails_captured"]
    avg_p = stats["avg_pages_per_session"]

    lines.append(f"**{stats['days']}-day summary: {total} unique visitors, {stats['total_views']} page views**")
    lines.append("")

    # Audience profile
    if corp_pct > 20:
        lines.append(f"🏢 **{corp_pct}% corporate IPs** — potential B2B leads (agents, developers, insurers). "
                     "Consider direct outreach for partnership.")
    if consumer_pct > 60:
        lines.append(f"👤 **{consumer_pct}% consumer traffic** — primarily individual buyers/investors.")

    # Engagement signals
    if avg_p >= 4:
        lines.append(f"🔥 **High engagement** — avg {avg_p} pages/session suggests serious intent.")
    elif avg_p >= 2:
        lines.append(f"📊 **Moderate engagement** — avg {avg_p} pages/session. "
                     "Consider onboarding nudge after 2nd page to capture email.")

    # Feature signals
    if top_pages:
        lines.append(f"📍 **Most visited:** {', '.join(top_pages)} — "
                     "focus product improvements here for maximum impact.")

    # Monetisation signals
    if leads > 0:
        lines.append(f"💰 **{leads} broker leads** — at SGD 500–2,000 referral each, "
                     f"estimated pipeline SGD {leads * 1000:,}–{leads * 2000:,}.")
    if tg_users > 0:
        lines.append(f"📱 **{tg_users} Telegram-identified users** — warm audience for broadcast campaigns.")
    if emails > 0:
        lines.append(f"📧 **{emails} emails captured** — eligible for email nurture sequence.")

    # Returning users
    ret = stats["returning_visitors"]
    if ret > 0:
        ret_pct = round(ret / total * 100)
        lines.append(f"🔁 **{ret_pct}% returning visitors** — "
                     + ("strong retention signal." if ret_pct > 20 else "room to improve retention via watchlist/alerts."))

    # Power users
    power = [s for s in engaged if s["page_count"] >= 6]
    if power:
        lines.append(f"\n**Power users ({len(power)} sessions, 6+ pages):**")
        for s in power[:5]:
            contact = s.get("telegram_id") or s.get("email") or "anonymous"
            lines.append(f"  • {contact} — visited: {s['pages_visited']} ({s['page_count']} pages)")

    return "\n".join(lines)


# ── Subscriber management ─────────────────────────────────────────────────────

def add_subscriber(email: str, source: str = "sidebar") -> dict:
    """
    Add email to subscribers table.
    Returns {"new": bool, "total": int}
    """
    ensure_schema()
    email = email.strip().lower()
    with sqlite3.connect(str(DB_PATH)) as conn:
        existing = conn.execute("SELECT id FROM subscribers WHERE email=?", (email,)).fetchone()
        if existing:
            return {"new": False, "total": get_subscriber_count()}
        conn.execute(
            "INSERT OR IGNORE INTO subscribers (email, source) VALUES (?,?)",
            (email, source)
        )
        conn.commit()
    return {"new": True, "total": get_subscriber_count()}


def get_subscriber_count(active_only: bool = True) -> int:
    """Return total subscriber count."""
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        if active_only:
            row = conn.execute("SELECT COUNT(*) FROM subscribers WHERE active=1").fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()
    return row[0] if row else 0


def get_unnotified_subscribers(limit: int = 100) -> list[dict]:
    """Return subscribers who haven't received the welcome email yet."""
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM subscribers WHERE welcome_sent=0 AND active=1 LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_welcome_sent(email: str):
    """Mark welcome email as sent for this subscriber."""
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("UPDATE subscribers SET welcome_sent=1 WHERE email=?", (email,))
        conn.commit()


def get_all_subscribers(active_only: bool = True) -> list[dict]:
    """Return full subscriber list for admin."""
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM subscribers WHERE active=1 ORDER BY subscribed_at DESC" if active_only \
            else "SELECT * FROM subscribers ORDER BY subscribed_at DESC"
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]

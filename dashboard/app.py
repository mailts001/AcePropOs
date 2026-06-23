"""
PropOS Streamlit Dashboard
Tabs: Deal Feed | Valuation | News | Admin (LLM mode + token costs)
Run: streamlit run dashboard/app.py --server.port 8502
"""

import streamlit as st
import json
import sys
import os
import uuid
from pathlib import Path
from datetime import date

# Add project root to path and load .env
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def _send_welcome_email(to_email: str) -> bool:
    """
    Send a welcome email to a new subscriber using SMTP.
    Reads SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS from environment.
    Falls back gracefully if SMTP not configured.
    Returns True if sent, False if skipped/failed.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not smtp_host or not smtp_user:
        return False  # SMTP not configured — silent skip

    subject = "Welcome to PropOS — Singapore's AI Property Intelligence"
    html_body = f"""
<html><body style="font-family:Inter,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;padding:32px">
  <h2 style="color:#1a1a2e;margin-bottom:4px">Welcome to PropOS 🏡</h2>
  <p style="color:#666;margin-top:0">Singapore AI Property Intelligence</p>
  <hr style="border:1px solid #eee">
  <p>Hi there,</p>
  <p>Thanks for subscribing! Here's what PropOS gives you <b>for free</b>:</p>
  <ul>
    <li>🔍 <b>Live HDB & private condo valuations</b> from 137,000+ URA transactions</li>
    <li>🗺️ <b>Full property research map</b> — MRT, hawkers, malls, schools + transaction heatmap</li>
    <li>💰 <b>CPF Housing Grants calculator</b> — find out if you qualify for up to $80,000</li>
    <li>🏠↔️ <b>Rent vs Buy analyser</b> — know your breakeven year instantly</li>
    <li>📊 <b>Deal Feed</b> — properties trading >10% below district median</li>
    <li>🏗️ <b>En-Bloc scanner</b> — early signals on collective sales</li>
    <li>📅 <b>MOP countdown tracker</b> — know when HDB flats become eligible to sell</li>
  </ul>
  <p>
    <a href="http://acepropos.duckdns.org"
       style="background:#c8a84b;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:700">
      Open PropOS Dashboard →
    </a>
  </p>
  <hr style="border:1px solid #eee">
  <p style="font-size:12px;color:#999">
    You're receiving this because you subscribed at acepropos.duckdns.org.<br>
    PropOS is free for personal use. No spam — we only email when there's something worth knowing.
  </p>
</div>
</body></html>
"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception:
        return False


def _gradient_html(df, col_cmaps: dict, fmt: dict | None = None) -> str:
    """
    Render a DataFrame as colour-coded HTML without requiring matplotlib.
    col_cmaps: {col_name: "RdYlGn" | "RdYlGn_r" | "YlGn" | "YlOrRd" | "Blues"}
    fmt: {col_name: format_string}  e.g. {"PSF": "${:,.0f}"}
    Returns raw HTML string safe for st.write(..., unsafe_allow_html=True).
    """
    import pandas as _pd

    # Colour palettes as (R,G,B) stops — low→high
    _PALETTES = {
        "RdYlGn":   [(215,25,28),(253,174,97),(255,255,191),(166,217,106),(26,150,65)],
        "RdYlGn_r": [(26,150,65),(166,217,106),(255,255,191),(253,174,97),(215,25,28)],
        "YlGn":     [(255,255,204),(194,230,153),(120,198,121),(49,163,84),(0,104,55)],
        "YlOrRd":   [(255,255,178),(254,204,92),(253,141,60),(240,59,32),(189,0,38)],
        "Blues":    [(247,251,255),(198,219,239),(107,174,214),(33,113,181),(8,48,107)],
    }

    def _interp(palette, t):
        t = max(0.0, min(1.0, t))
        n = len(palette) - 1
        lo = int(t * n)
        hi = min(lo + 1, n)
        f = t * n - lo
        r = int(palette[lo][0] + f * (palette[hi][0] - palette[lo][0]))
        g = int(palette[lo][1] + f * (palette[hi][1] - palette[lo][1]))
        b = int(palette[lo][2] + f * (palette[hi][2] - palette[lo][2]))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _text_color(hex_bg):
        r = int(hex_bg[1:3], 16)
        g = int(hex_bg[3:5], 16)
        b = int(hex_bg[5:7], 16)
        lum = 0.299*r + 0.587*g + 0.114*b
        return "#000" if lum > 140 else "#fff"

    # Pre-compute min/max per column
    col_ranges = {}
    for col, cmap in col_cmaps.items():
        if col in df.columns:
            vals = _pd.to_numeric(df[col], errors="coerce").dropna()
            lo, hi = (vals.min(), vals.max()) if len(vals) else (0, 1)
            col_ranges[col] = (lo, hi, _PALETTES.get(cmap, _PALETTES["Blues"]))

    rows_html = []
    for idx, row in df.iterrows():
        cells = [f"<td style='padding:4px 8px;font-weight:600;background:#e8eaf0;color:#1a1a2e'>{idx}</td>"]
        for col in df.columns:
            raw = row[col]
            cell_fmt = fmt.get(col, "{}") if fmt else "{}"
            try:
                display = cell_fmt.format(raw)
            except Exception:
                display = str(raw)
            if col in col_ranges:
                lo, hi, palette = col_ranges[col]
                try:
                    t = (float(raw) - lo) / (hi - lo) if hi != lo else 0.5
                except Exception:
                    t = 0.5
                bg = _interp(palette, t)
                fg = _text_color(bg)
                cells.append(f"<td style='padding:4px 8px;background:{bg};color:{fg};text-align:right'>{display}</td>")
            else:
                cells.append(f"<td style='padding:4px 8px;text-align:right'>{display}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    header = "<tr><th style='padding:4px 8px;background:#262730;color:#fff'>Town</th>" + \
             "".join(f"<th style='padding:4px 8px;background:#262730;color:#fff;text-align:right'>{c}</th>" for c in df.columns) + "</tr>"
    table = f"<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;font-size:13px'>{header}{''.join(rows_html)}</table></div>"
    return table


import requests as _requests_lib  # available globally throughout app

from agents.valuation_agent import ValuationAgent
from agents.deal_hunter_agent import DealHunterAgent
from agents.news_intel_agent import NewsIntelAgent
from agents.insurance_agent import InsuranceAgent
from agents.mortgage_agent import MortgageAgent, BANK_RATES, SORA_3M
from data.watchlist import (init_watchlist_db, add_watch, list_watches,
                             delete_watch, check_watchlist, format_alert_message)
from core.llm_router import save_mode, get_current_mode, get_token_summary
from data.news_pipeline import get_sentiment_index

st.set_page_config(
    page_title="PropOS — Singapore Property Intelligence",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "Get Help": "https://t.me/AcePropOS_bot",
        "Report a bug": "mailto:mailtsjp@gmail.com",
        "About": (
            "## PropOS — Singapore Property Intelligence\n\n"
            "AI-powered HDB & private property platform for Singapore.\n\n"
            "**Features:** Address lookup · Deal scanner · Valuation · "
            "News intelligence · Insurance advisor · Mortgage calculator · "
            "BTO tracker · Price alerts\n\n"
            "**Contact:** mailtsjp@gmail.com\n\n"
            "**Telegram channel:** https://t.me/AcePropOs_Ch\n\n"
            "**Telegram bot:** @AcePropOS_bot\n\n"
            "_Data sources: HDB Resale (data.gov.sg), URA (ura.gov.sg), "
            "RSS news feeds. Not financial advice._"
        ),
    },
)

# ── Cached data loaders — MUST be after set_page_config ──────────────────────
# Streamlit caches in memory for 1 hr: avoids re-parsing 10MB JSON on every rerender
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_hdb_records():
    from data.hdb_pipeline import fetch_hdb_resale
    return fetch_hdb_resale()

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_ura_transactions():
    from data.ura_pipeline import load_all_transactions
    return load_all_transactions()

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_districts_with_data():
    """Pre-compute all 28 district stats in one pass — avoids 112 file reads per render."""
    from data.ura_pipeline import get_district_stats
    result = []
    for d in range(1, 29):
        s = get_district_stats(d)
        if s.get("count", 0) >= 5:
            result.append((d, s["count"], s["median_psf"], s))
    return result

def _show_rental_intel(district: int, est_val_sgd: int = 0, area_sqft: int = 1000):
    """
    Render URA rental market stats from cache only — never blocks render thread.
    Uses project-level median rental PSF aggregated to district level.
    Cache seeded by sync_ura.py (daily cron).
    """
    st.divider()
    st.subheader(f"🏘️ Rental Market — District {district}")
    try:
        from data.ura_rental_pipeline import get_district_rental_stats
        _rs = get_district_rental_stats(district, area_sqft=area_sqft or 1000)
        if _rs.get("status") == "ok":
            _q   = _rs.get("latest_quarter", "")
            _med = _rs.get("med_rent_sgd", 0)
            _p25 = _rs.get("p25_rent_sgd", 0)
            _p75 = _rs.get("p75_rent_sgd", 0)
            _gy  = round(_med * 12 / est_val_sgd * 100, 2) if est_val_sgd and _med else 0
            _ny  = round(_gy - 1.5, 2) if _gy else 0

            st.caption(f"URA median rental PSF · {_q} · {_rs.get('project_count',0)} projects in D{district}")
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Median Rent/mo",   f"${_med:,.0f}",
                       help=f"{area_sqft:,} sqft × ${_rs.get('median_psf',0):.2f} PSF/mo")
            rc2.metric("Range (P25–P75)",  f"${_p25:,.0f} – ${_p75:,.0f}")
            rc3.metric("Est. Gross Yield", f"{_gy:.2f}%" if _gy else "—")
            rc4.metric("Est. Net Yield",   f"{_ny:.2f}%" if _ny else "—",
                       help="After ~1.5% p.a. for maintenance, vacancy, property tax")

            # Per-project rental records table
            _proj_rows = _rs.get("project_rows", [])
            if _proj_rows:
                import pandas as _rentpd
                st.caption(f"↓ Rental by project — {_q}, sorted highest PSF first")
                _rent_df = _rentpd.DataFrame([{
                    "Project":          r["project"],
                    "Street":           r["street"],
                    "Median PSF/mo":    f"${r['median_psf']:.2f}",
                    f"Est Rent ({area_sqft:,}sqft)": f"${r['med_rent']:,.0f}",
                    "P25 PSF":          f"${r['psf25']:.2f}",
                    "P75 PSF":          f"${r['psf75']:.2f}",
                } for r in _proj_rows])
                st.dataframe(_rent_df, hide_index=True, use_container_width=True)
            st.caption("Yield vs estimated/asking value. Actual yield varies by unit size, floor and furnishing.")
        else:
            st.info(
                "📋 **Rental data not yet cached.** Run once on the VPS "
                "(then auto-refreshes daily):\n"
                "```\ncd /root/propos && .venv/bin/python scripts/sync_ura.py\n```"
            )
    except Exception as _rle:
        st.caption(f"Rental data unavailable: {_rle}")

# ── Premium UI Theme ──────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Premium editorial: serif titles, sans body ── */
h1, h2, h3,
[data-testid="stHeading"] {
    font-family: 'Playfair Display', Georgia, 'Times New Roman', serif !important;
    letter-spacing: -0.3px;
}
h1 { font-size: 1.9rem !important; font-weight: 700 !important; }
h2 { font-size: 1.4rem !important; font-weight: 600 !important; }
h3 { font-size: 1.15rem !important; font-weight: 600 !important; }

/* ── Font only — let Streamlit handle all colors so dark/light mode works ── */
html, body, [class*="css"], button, input, select, textarea {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* ── Layout — top padding clears Streamlit's sticky header (~56px) ── */
.block-container {
    padding: 4rem 1.5rem 3rem !important;
    max-width: 1280px;
}

/* ── Sidebar: dark navy only inside sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1b2a 0%, #1a2f4a 100%) !important;
    border-right: 1px solid rgba(201,168,76,0.2) !important;
}
/* Only target direct text nodes in sidebar — not nested content panes */
[data-testid="stSidebar"] > div > div > div,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span:not([data-testid]),
[data-testid="stSidebar"] small {
    color: #c8d8e8 !important;
}
/* Category radio: larger, gold tint */
[data-testid="stSidebar"] .stRadio:first-of-type label { font-size: 0.95rem !important; font-weight: 600 !important; }
/* Page radio: slightly indented */
[data-testid="stSidebar"] .stRadio + .stRadio label { font-size: 0.84rem !important; padding-left: 0.5rem !important; }
[data-testid="stSidebar"] [data-baseweb="radio"] [aria-checked="true"] ~ span {
    color: #c9a84c !important;
    font-weight: 600;
}

/* ── Primary buttons: gold ── */
button[kind="primary"],
[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #c9a84c, #e8c96a) !important;
    color: #0d1b2a !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1.4rem !important;
    box-shadow: 0 2px 10px rgba(201,168,76,0.4) !important;
    transition: box-shadow 0.2s, transform 0.15s !important;
}
button[kind="primary"]:hover {
    box-shadow: 0 4px 18px rgba(201,168,76,0.6) !important;
    transform: translateY(-1px) !important;
}

/* ── Secondary buttons ── */
[data-testid="stButton"] > button:not([kind="primary"]) {
    border-radius: 8px !important;
    transition: border-color 0.15s !important;
}
[data-testid="stButton"] > button:not([kind="primary"]):hover {
    border-color: #c9a84c !important;
}

/* ── Active tab: gold underline, inherits text color ── */
[data-testid="stTabs"] button[aria-selected="true"] {
    font-weight: 700 !important;
    border-bottom: 3px solid #c9a84c !important;
}
[data-testid="stTabs"] > div:first-child {
    border-bottom: 1px solid rgba(128,128,128,0.2) !important;
}

/* ── Metric cards: subtle border + shadow, no background override ── */
[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,0.15) !important;
    border-radius: 12px !important;
    padding: 1rem 1.2rem !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05) !important;
    transition: box-shadow 0.2s;
}
[data-testid="stMetric"]:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.1) !important;
}
[data-testid="stMetricLabel"] > div {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
    opacity: 0.65;
}
[data-testid="stMetricValue"] {
    font-size: 1.45rem !important;
    font-weight: 700 !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid rgba(128,128,128,0.18) !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
    margin-bottom: 0.5rem;
}

/* ── Alerts ── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border-left-width: 4px !important;
}

/* ── Input focus: gold ring ── */
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: #c9a84c !important;
    box-shadow: 0 0 0 2px rgba(201,168,76,0.2) !important;
    outline: none !important;
}

/* ── Dataframes ── */
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06) !important;
}

/* ── Gradient HTML tables ── */
div[style*="overflow-x:auto"] {
    border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}

/* ── Divider ── */
hr { opacity: 0.2 !important; }

/* ══════════ MOBILE ══════════ */
@media (max-width: 768px) {
    /* Extra clearance on mobile — header bar + app bar can stack up to ~6rem */
    .block-container { padding: 5.5rem 0.75rem 5rem !important; }
    [data-testid="stMetric"] { padding: 0.75rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.15rem !important; }
    /* Stack columns */
    [data-testid="column"] { min-width: 100% !important; flex: 1 1 100% !important; }
    /* Scrollable tab row */
    [data-testid="stTabs"] > div:first-child {
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }
    [data-testid="stTabs"] > div:first-child::-webkit-scrollbar { display: none; }
    [data-testid="stTabs"] button { white-space: nowrap; font-size: 0.72rem; padding: 0.3rem 0.6rem; }
    /* Full-width buttons */
    [data-testid="stButton"] > button { width: 100%; margin-bottom: 0.4rem; }
    /* Compact HTML tables */
    div[style*="overflow-x:auto"] td, div[style*="overflow-x:auto"] th {
        padding: 3px 5px !important; font-size: 11px !important;
    }
    /* Keep Streamlit header — don't hide it (causes title clip) */
    footer { display: none; }
}

/* ══════════ TABLET ══════════ */
@media (min-width: 769px) and (max-width: 1024px) {
    .block-container { padding: 4rem 1.25rem !important; }
    [data-testid="stTabs"] button { font-size: 0.8rem; }
}

/* ── Wrap metric rows ── */
[data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.75rem; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p style="font-size:1.4rem;font-weight:700;color:#c9a84c;margin:0">🏠 PropOS</p>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:0.78rem;color:#8a9bac;margin-top:-4px;margin-bottom:1rem">Singapore Property Intelligence</p>', unsafe_allow_html=True)

    mode_info = get_current_mode()
    mode_colors = {"free": "🟢", "balanced": "🟡", "quality": "🔵", "premium": "🟣"}
    st.info(f"{mode_colors.get(mode_info['mode'], '⚪')} LLM: **{mode_info['mode'].upper()}** — {mode_info['model']}")

    st.divider()

    # ── Two-level navigation: category → page ─────────────────────────────────
    NAV = {
        "🔍 Research": [
            "🏠 Address Lookup",
            "📊 Deal Feed",
            "🔍 Valuation",
            "⚖️ Compare",
            "🏚️ En-Bloc",
            "🗺️ MRT Map",
        ],
        "📰 Intelligence": [
            "📰 News & Sentiment",
            "🏗️ BTO Pipeline",
            "📅 MOP Tracker",
        ],
        "💰 Finance": [
            "🏦 Mortgage",
            "💹 Stamp Duty & ROI",
            "🎁 CPF Grants",
            "🏠↔️ Rent vs Buy",
            "⬆️ HDB Upgrader",
            "🏛️ Property Tax",
            "🔄 Refi Alert",
            "🏘️ Rental Yield",
        ],
        "📈 Price History": [
            "📈 Price History",
        ],
        "🛡️ Protect": [
            "🛡️ Insurance",
            "🔔 Watchlist & Alerts",
            "⏳ SSD Timer",
        ],
        "💼 My Portfolio": ["💼 Portfolio"],
        "🤝 Partners": ["🤝 Partners"],
        "⚙️ Admin":    ["⚙️ Admin"],
    }

    # Flat map for legacy tab_select compatibility
    _NAV_ALIASES = {
        "📰 News & Sentiment": "📰 News Intel",
        "💹 Stamp Duty & ROI": "💹 Tools",
        "🔔 Watchlist & Alerts": "🔔 Watchlist",
        "🏗️ BTO Pipeline": "🏗️ BTO",
    }

    # ── Email capture — top of sidebar, before nav ───────────────────────────
    with st.expander("📬 Get market updates", expanded=False):
        _cap_email = st.text_input("Your email", placeholder="you@email.com", key="cap_email", label_visibility="collapsed")
        if st.button("Subscribe", key="cap_sub", use_container_width=True):
            if "@" in _cap_email and "." in _cap_email:
                try:
                    from data.analytics import add_subscriber, track_pageview as _tp_cap, resubscribe_email as _resub
                    _sub_result = add_subscriber(_cap_email.strip().lower(), source="sidebar")
                    _tp_cap("email_capture", session_id=st.session_state.get("session_id",""), email=_cap_email)
                    if _sub_result.get("new"):
                        st.success("✅ Subscribed! Sending welcome email…")
                        _sent = _send_welcome_email(_cap_email.strip().lower())
                        if _sent:
                            from data.analytics import mark_welcome_sent as _mws
                            _mws(_cap_email.strip().lower())
                    else:
                        # Already in DB — re-activate in case they unsubscribed
                        _resub(_cap_email.strip().lower())
                        st.info("✅ You're already on our list — re-activated! We'll keep you posted on Singapore property intelligence.")
                except Exception as _se:
                    st.success("✅ Subscribed!")
            else:
                st.warning("Enter a valid email address.")

    st.divider()

    # ── Page popularity counts (from analytics) ──────────────────────────────
    # Load counts into session state so labels are consistent within a rerun
    _page_counts: dict = st.session_state.get("_page_counts_cache", {})
    try:
        from data.analytics import get_summary as _get_summary
        _qs = _get_summary(7)
        _page_counts = {p["page"]: p["views"] for p in _qs.get("by_page", [])}
        st.session_state["_page_counts_cache"] = _page_counts
    except Exception:
        pass

    # Rank pages by views for relative popularity stars — more stable than raw counts
    _all_counts = list(_page_counts.values())
    _all_counts.sort(reverse=True)

    def _popularity_badge(cnt: int) -> str:
        """Convert view count to a relative star badge. Empty string if low traffic."""
        if not _all_counts or _all_counts[0] == 0:
            return ""
        rank_pct = cnt / _all_counts[0]  # fraction of max-viewed page
        if rank_pct >= 1.0:  return " 🔥"      # most popular
        if rank_pct >= 0.6:  return " ⭐⭐"
        if rank_pct >= 0.3:  return " ⭐"
        return ""

    def _label(pg: str) -> str:
        """Popularity badge via format_func — clean page name is still stored value."""
        alias_key = _NAV_ALIASES.get(pg, pg)
        cnt = _page_counts.get(alias_key, _page_counts.get(pg, 0))
        badge = _popularity_badge(cnt)
        return f"{pg}{badge}"

    st.markdown("<p style='font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;opacity:0.5;margin-bottom:2px'>Main Categories</p>", unsafe_allow_html=True)
    # NO on_change — on_change callbacks interact badly with bidirectional
    # custom components (streamlit-folium) which trigger their own reruns.
    # Tracking is handled below via per-page session state flags instead.
    nav_cat = st.radio(
        "Section",
        list(NAV.keys()),
        label_visibility="collapsed",
        key="nav_cat",
    )

    pages = NAV[nav_cat]

    if len(pages) == 1:
        nav_page = pages[0]
    else:
        st.markdown("<p style='font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;opacity:0.5;margin:6px 0 2px 0'>Sub Menus</p>", unsafe_allow_html=True)
        nav_page = st.radio(
            "Page",
            pages,
            format_func=_label,
            label_visibility="collapsed",
            key=f"nav_page_{nav_cat}",
            # NO on_change here — see comment on nav_cat above
        )

    # Resolve alias so existing elif chain keeps working unchanged
    tab_select = _NAV_ALIASES.get(nav_page, nav_page)

    st.divider()
    with st.expander("📖 Terms Explained"):
        st.markdown("""
**Property**
- **PSF** — Price per square foot. Lower = cheaper relative to size.
- **HDB** — Housing Development Board. Singapore public housing.
- **MOP** — Minimum Occupation Period. HDB owners must live in their flat for 5 years before selling or renting the whole unit.
- **BTO** — Build-to-Order. New HDB flats balloted directly from HDB, usually 20–30% cheaper than resale.
- **En-bloc** — Collective sale where all owners sell to a developer at a premium.
- **Leasehold / Freehold** — Leasehold = 99-yr lease from government. Freehold = no expiry.

**Finance**
- **BSD** — Buyer's Stamp Duty. Paid by all buyers on every property purchase.
- **ABSD** — Additional BSD. Extra tax for 2nd+ properties or foreigners.
- **SSD** — Seller's Stamp Duty. Applies if you sell within 3 years of buying.
- **TDSR** — Total Debt Servicing Ratio. MAS rule: all loan repayments ≤ 55% of gross income.
- **MSR** — Mortgage Servicing Ratio. For HDB/EC only: mortgage ≤ 30% of gross income.
- **SORA** — Singapore Overnight Rate Average. Benchmark rate that bank mortgage packages are pegged to.
- **LTV** — Loan-to-Value. Max % of property price you can borrow (75% private, 80% HDB first loan).

**Insurance**
- **Mortgage Protection (MRTA)** — Mortgage Reducing Term Assurance. Pays off your remaining loan if you pass away or become critically ill. Coverage reduces as loan is paid down. One-time premium ~SGD 2,000–5,000.
- **Life & Mortgage Insurance (MLTA)** — Mortgage Level Term Assurance. Fixed payout regardless of remaining loan. More flexible — family keeps the difference. Higher premium than MRTA.
- **Term Life** — Pays a lump sum if you pass away within the policy term.
- **Critical Illness (CI)** — Pays lump sum on diagnosis of major illnesses (cancer, stroke, heart attack).
- **Total & Permanent Disability (TPD)** — Pays if you cannot work permanently.
- **Fire Insurance** — Covers the structure of your property (required for HDB).
- **Home Contents** — Covers furniture, appliances, and belongings inside your home.
        """)

    # ── Live visitor stats ────────────────────────────────────────────────────
    try:
        from data.analytics import get_summary as _vs, get_subscriber_count as _sub_cnt
        _today_stats = _vs(1)
        _total_stats = _vs(365)
        _d  = _today_stats["unique_visitors_ip"]
        _t  = _total_stats["unique_visitors_ip"]
        _sc = _sub_cnt()
        st.markdown(
            f"<div style='background:rgba(255,255,255,0.06);border-radius:8px;"
            f"padding:8px 10px;margin:8px 0 4px 0'>"
            f"<span style='font-size:0.85rem;font-weight:700;color:#c8a84b'>👁 Today: {_d}</span>"
            f"&nbsp;&nbsp;"
            f"<span style='font-size:0.85rem;font-weight:700;opacity:0.85'>Total: {_t}</span>"
            f"<br>"
            f"<span style='font-size:0.8rem;color:#5cb8a8'>📬 Subscribers: {_sc}</span>"
            f"</div>",
            unsafe_allow_html=True
        )
    except Exception as _ve:
        st.caption(f"Stats: {_ve}")

    st.caption("v1.0 · acepropos.duckdns.org")

# ── Session init & page tracking ─────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())[:12]
_session_id = st.session_state["session_id"]

try:
    from data.analytics import ensure_schema
    ensure_schema()
    # Resolve real visitor IP once per session (nginx proxy headers)
    if "_visitor_ip" not in st.session_state:
        _headers = st.context.headers if hasattr(st, "context") else {}
        _visitor_ip = (
            _headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or _headers.get("X-Real-Ip", "")
            or ""
        )
        st.session_state["_visitor_ip"] = _visitor_ip
    else:
        _visitor_ip = st.session_state["_visitor_ip"]

    # Track page views using a per-page flag in session state.
    # Key = session_id + page name → fires ONCE per page per session.
    # Immune to folium reruns, widget rerenders, or any other reruns because
    # the flag is already set after the first genuine navigation.
    _track_key = f"_pv_{_session_id}_{tab_select}"
    if not st.session_state.get(_track_key):
        st.session_state[_track_key] = True
        from data.analytics import track_pageview as _tpv
        _tpv(page=tab_select, session_id=_session_id, ip=_visitor_ip)
except Exception:
    _visitor_ip = ""

# ── Address Lookup ────────────────────────────────────────────────────────────
if tab_select == "🏠 Address Lookup":
    st.header("🏠 Property Address Lookup")
    st.caption("Get real transaction history and market valuation for any Singapore property address")

    prop_category = st.radio("Property type", ["HDB Flat", "Private Condo/Apt (Project Name)"], horizontal=True)

    if prop_category == "HDB Flat":
        st.subheader("HDB Address Lookup")

        # ── Input method: postal code OR block+street ─────────────────────────
        _addr_mode = st.radio("Enter by", ["🏠 Block & Street", "📮 Postal Code"], horizontal=True, key="addr_input_mode")

        if _addr_mode == "📮 Postal Code":
            _addr_postal = st.text_input("Postal Code (6 digits)", max_chars=6, placeholder="e.g. 520320", key="addr_postal")
            block, street = "", ""
            if _addr_postal and len(_addr_postal) == 6 and _addr_postal.isdigit():
                try:
                    _om_a = _requests_lib.get(
                        "https://www.onemap.gov.sg/api/common/elastic/search"
                        f"?searchVal={_addr_postal}&returnGeom=N&getAddrDetails=Y&pageNum=1",
                        timeout=6
                    ).json()
                    _om_ar = (_om_a.get("results") or [{}])[0]
                    block  = (_om_ar.get("BLK_NO","") or "").strip()
                    street = (_om_ar.get("ROAD_NAME","") or "").strip()
                    if block and street:
                        st.success(f"📍 Resolved: **Block {block}, {street}**")
                    else:
                        st.warning("Could not resolve postal code. Enter block & street manually.")
                except Exception as _ae:
                    st.warning(f"Postal lookup error: {_ae}")
        else:
            st.info("Enter block number and street name as shown on your flat's address.")
            col1, col2 = st.columns([1, 3])
            with col1:
                block = st.text_input("Block No.", placeholder="e.g. 123A")
            with col2:
                street = st.text_input("Street Name", placeholder="e.g. TAMPINES ST 11")

        col_ft, col_ask = st.columns(2)
        with col_ft:
            flat_type_filter = st.selectbox("Flat Type", ["4 ROOM", "3 ROOM", "5 ROOM", "EXECUTIVE", "2 ROOM", "Any"],
                                            help="Filter transactions to this flat type only")
        with col_ask:
            asking = st.number_input("Asking Price (SGD, 0 = history only)", 0, 2000000, 0, step=5000)
        explain_toggle = st.checkbox("Generate AI analysis", value=True)

        if st.button("🔍 Look Up Address", type="primary"):
            if not block or not street:
                st.warning("Please enter both block number and street name.")
            else:
                agent = ValuationAgent()
                ftype = "" if flat_type_filter == "Any" else flat_type_filter
                with st.spinner(f"Looking up Block {block} {street}..."):
                    result = agent.value_by_address(block.strip(), street.strip(), asking, ftype, explain_toggle)

                if result["status"] == "not_found":
                    st.error(result["message"])
                    if result.get("suggestions"):
                        st.write("**Did you mean one of these?**")
                        for s in result["suggestions"]:
                            st.write(f"  • {s}")
                else:
                    # Header metrics
                    st.success(f"✅ Found {result['transaction_count']} transactions for Block {block} {street}")
                    st.caption(f"🏘️ Town: {result['town']} | Type: {result['flat_type']} | Lease remaining: {result['remaining_lease']}")

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Latest Transaction", f"${result['latest_transacted_price']:,.0f}", result['latest_transaction_month'])
                    col2.metric("Latest PSF", f"${result['latest_transacted_psf']:,.0f}")
                    col3.metric("Address Median", f"${result['address_median_price']:,.0f}")
                    col4.metric("Town Median", f"${result['town_median_price']:,.0f}")

                    col5, col6 = st.columns(2)
                    col5.metric("Floor Area", f"{result['floor_area_sqft']:.0f} sqft")
                    col6.metric("Avg PSF (this block)", f"${result['avg_psf']:,.0f}")

                    if asking > 0:
                        st.divider()
                        vs = result.get("vs_address_history_pct", 0)
                        vs_town = result.get("vs_town_median_pct")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Asking vs Address History", f"{vs:+.1f}%")
                        if vs_town is not None:
                            c2.metric("Asking vs Town Median", f"{vs_town:+.1f}%")
                        c3.metric("Deal Score", f"{result.get('deal_score', 0)}/100")
                        st.info(f"**Verdict:** {result.get('verdict', '')}")
                        if result.get("negotiation_hint"):
                            st.write(f"💬 {result['negotiation_hint']}")
                        if result.get("explanation"):
                            st.write(f"🤖 **AI Analysis:** {result['explanation']}")

                    # Transaction history table
                    st.divider()
                    _ftype_label = flat_type_filter if flat_type_filter != "Any" else "All Types"
                    st.subheader(f"📋 Transaction History — Block {block} {street} ({_ftype_label})")
                    txns = result.get("recent_transactions", [])
                    if txns:
                        import pandas as _txn_pd
                        _txn_rows = []
                        for t in txns:
                            _txn_rows.append({
                                "Month":       t.get("month",""),
                                "Flat Type":   t.get("flat_type",""),
                                "Storey":      t.get("storey_range",""),
                                "Area (sqft)": int(t.get("floor_area_sqft", 0) or 0),
                                "Price (SGD)": f"${t.get('resale_price',0):,.0f}",
                                "PSF":         f"${t.get('psf_sgd',0):,.0f}",
                                "Lease Rem.":  t.get("remaining_lease",""),
                            })
                        st.dataframe(_txn_pd.DataFrame(_txn_rows), hide_index=True, use_container_width=True)
                        if flat_type_filter != "Any":
                            st.caption(f"✅ All {len(txns)} transactions above are filtered to **{flat_type_filter}** only at Block {block} {street}.")

                    # Rental yield estimate
                    st.divider()
                    st.subheader("📈 Estimated Rental Yield")
                    # Full benchmark table: 2 ROOM through EXECUTIVE for all towns
                    _HDB_TOWN_RENT_FULL = {
                        "ANG MO KIO":     {"2 ROOM":1400,"3 ROOM":2300,"4 ROOM":2800,"5 ROOM":3200,"EXECUTIVE":3500},
                        "BEDOK":          {"2 ROOM":1350,"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                        "BISHAN":         {"2 ROOM":1500,"3 ROOM":2400,"4 ROOM":3000,"5 ROOM":3400,"EXECUTIVE":3700},
                        "BUKIT BATOK":    {"2 ROOM":1300,"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "BUKIT MERAH":    {"2 ROOM":1700,"3 ROOM":2600,"4 ROOM":3200,"5 ROOM":3700,"EXECUTIVE":4000},
                        "BUKIT PANJANG":  {"2 ROOM":1250,"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                        "CENTRAL AREA":   {"2 ROOM":2200,"3 ROOM":3200,"4 ROOM":4200,"5 ROOM":5000,"EXECUTIVE":5500},
                        "CHOA CHU KANG":  {"2 ROOM":1250,"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                        "CLEMENTI":       {"2 ROOM":1500,"3 ROOM":2400,"4 ROOM":2900,"5 ROOM":3400,"EXECUTIVE":3700},
                        "GEYLANG":        {"2 ROOM":1500,"3 ROOM":2200,"4 ROOM":2800,"5 ROOM":3200,"EXECUTIVE":3500},
                        "HOUGANG":        {"2 ROOM":1300,"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "JURONG EAST":    {"2 ROOM":1350,"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                        "JURONG WEST":    {"2 ROOM":1300,"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "KALLANG/WHAMPOA":{"2 ROOM":1600,"3 ROOM":2500,"4 ROOM":3100,"5 ROOM":3600,"EXECUTIVE":3900},
                        "MARINE PARADE":  {"2 ROOM":1700,"3 ROOM":2600,"4 ROOM":3200,"5 ROOM":3700,"EXECUTIVE":4000},
                        "PASIR RIS":      {"2 ROOM":1300,"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "PUNGGOL":        {"2 ROOM":1300,"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "QUEENSTOWN":     {"2 ROOM":1800,"3 ROOM":2700,"4 ROOM":3400,"5 ROOM":3900,"EXECUTIVE":4200},
                        "SEMBAWANG":      {"2 ROOM":1200,"3 ROOM":1900,"4 ROOM":2400,"5 ROOM":2800,"EXECUTIVE":3100},
                        "SENGKANG":       {"2 ROOM":1300,"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "SERANGOON":      {"2 ROOM":1450,"3 ROOM":2300,"4 ROOM":2900,"5 ROOM":3300,"EXECUTIVE":3600},
                        "TAMPINES":       {"2 ROOM":1350,"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                        "TOA PAYOH":      {"2 ROOM":1600,"3 ROOM":2400,"4 ROOM":3000,"5 ROOM":3500,"EXECUTIVE":3800},
                        "WOODLANDS":      {"2 ROOM":1200,"3 ROOM":1900,"4 ROOM":2400,"5 ROOM":2800,"EXECUTIVE":3100},
                        "YISHUN":         {"2 ROOM":1250,"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                    }
                    _res_town = result.get("town","")
                    _town_rents_full = _HDB_TOWN_RENT_FULL.get(_res_town, {})
                    _ref_price = result.get("address_median_price") or result.get("latest_transacted_price", 0)

                    # What flat types actually exist in this block?
                    _block_txns = result.get("recent_transactions", [])
                    _block_ftypes = sorted(set(
                        t.get("flat_type","").strip().upper()
                        for t in _block_txns if t.get("flat_type","").strip()
                    ))

                    # User-selected flat type takes priority; else derive from block records
                    _sel_ft = flat_type_filter if flat_type_filter != "Any" else (
                        result.get("flat_type","4 ROOM") or "4 ROOM"
                    )
                    # Normalise to our benchmark key
                    _ft_upper = _sel_ft.upper()
                    if "EXEC" in _ft_upper:
                        _rent_key = "EXECUTIVE"
                    elif "5" in _ft_upper:
                        _rent_key = "5 ROOM"
                    elif "4" in _ft_upper:
                        _rent_key = "4 ROOM"
                    elif "3" in _ft_upper:
                        _rent_key = "3 ROOM"
                    elif "2" in _ft_upper:
                        _rent_key = "2 ROOM"
                    else:
                        _rent_key = "4 ROOM"

                    _est_rent = _town_rents_full.get(_rent_key, 0)

                    # Flat-type mismatch warning: if block has different types, flag it
                    if _block_ftypes and _rent_key not in _block_ftypes:
                        _ftype_note = f"⚠️ Block records show **{', '.join(_block_ftypes)}** — you selected **{_rent_key}**. Showing benchmark for your selection."
                        st.warning(_ftype_note)
                    elif _block_ftypes:
                        st.caption(f"✅ Block has **{', '.join(_block_ftypes)}** transactions — rental estimate is for **{_rent_key}**.")

                    if _est_rent and _ref_price:
                        # Rental range: ±12% around benchmark (low floor / high premium)
                        _rent_low  = round(_est_rent * 0.88 / 100) * 100
                        _rent_high = round(_est_rent * 1.12 / 100) * 100
                        _gross_yield     = round(_est_rent * 12 / _ref_price * 100, 2)
                        _gross_yield_low = round(_rent_low  * 12 / _ref_price * 100, 2)
                        _gross_yield_hi  = round(_rent_high * 12 / _ref_price * 100, 2)
                        _net_yield  = round(_gross_yield - 1.2, 2)

                        ra, rb, rc, rd = st.columns(4)
                        ra.metric(f"Est. Rent ({_rent_key})",  f"${_est_rent:,}/mo",
                                  help=f"SRX 2024–25 median for {_rent_key} in {_res_town}")
                        rb.metric("Rental Range",              f"${_rent_low:,}–${_rent_high:,}/mo",
                                  help="±12% around median (low floor vs high premium/renovated)")
                        rc.metric("Gross Yield",               f"{_gross_yield}%",
                                  help=f"Range: {_gross_yield_low}%–{_gross_yield_hi}%")
                        rd.metric("Net Yield (est.)",          f"{_net_yield}%",
                                  help="After ~1.2% for tax, maintenance, vacancy, agent")

                        # Breakdown table: all flat types in this town
                        if _town_rents_full:
                            import pandas as _ry_pd
                            _ry_rows = []
                            for _k, _r in sorted(_town_rents_full.items(),
                                                  key=lambda x: ["2 ROOM","3 ROOM","4 ROOM","5 ROOM","EXECUTIVE"].index(x[0]) if x[0] in ["2 ROOM","3 ROOM","4 ROOM","5 ROOM","EXECUTIVE"] else 99):
                                _gy = round(_r * 12 / _ref_price * 100, 2) if _ref_price else 0
                                _is_sel = "← your type" if _k == _rent_key else ""
                                _ry_rows.append({"Flat Type": f"{_k} {_is_sel}",
                                                 "Benchmark Rent/mo": f"${_r:,}",
                                                 "Rent Range": f"${round(_r*.88/100)*100:,}–${round(_r*1.12/100)*100:,}",
                                                 "Gross Yield": f"{_gy:.2f}%"})
                            with st.expander(f"📊 All flat type rents in {_res_town}"):
                                st.dataframe(_ry_pd.DataFrame(_ry_rows), hide_index=True, use_container_width=True)
                        st.caption(
                            f"**Source:** SRX 2024–25 town-level median for **{_rent_key}** in **{_res_town}**. "
                            f"Range (${_rent_low:,}–${_rent_high:,}) reflects ±12% variance by floor, condition & MRT proximity. "
                            f"Yield calculated on address median price SGD {_ref_price:,.0f}. "
                            f"⚠️ HDB MOP (5 years) must be satisfied before entire flat can be rented."
                        )
                    else:
                        st.caption(f"No rental benchmark available for {_rent_key} in {_res_town}.")

                    # Price + implied yield trend chart
                    st.divider()
                    st.subheader(f"📊 {result['town']} {result['flat_type']} — Price & Implied Yield Trend")
                    st.caption("Price trend uses actual HDB resale transactions. Yield is implied: benchmark rent ÷ monthly median price.")
                    from collections import defaultdict as _dd
                    import pandas as _pd
                    _all_records = _cached_hdb_records()
                    _trend_records = [
                        r for r in _all_records
                        if r["town"] == result["town"]
                        and result["flat_type"].lower() in r["flat_type"].lower()
                        and r.get("psf_sgd", 0) > 0
                    ]
                    if _trend_records:
                        _monthly_p: dict = _dd(list)
                        for r in _trend_records:
                            _monthly_p[r["month"]].append(r["resale_price"])
                        _months = sorted(_monthly_p.keys())[-18:]
                        _med_prices = [sorted(_monthly_p[m])[len(_monthly_p[m]) // 2] for m in _months]
                        _annual_rent = (_est_rent or 0) * 12
                        _impl_yields = [
                            round(_annual_rent / p * 100, 2) if _annual_rent and p else 0
                            for p in _med_prices
                        ]
                        _price_tab, _yield_tab = st.tabs(["💰 Median Price Trend", "📈 Implied Gross Yield Trend"])
                        with _price_tab:
                            _pdf = _pd.DataFrame({"Median Resale Price (SGD)": _med_prices}, index=_months)
                            st.line_chart(_pdf)
                            st.caption(f"Median resale price for {result['flat_type']} in {result['town']} — last {len(_months)} months")
                        with _yield_tab:
                            if _annual_rent:
                                _ydf = _pd.DataFrame({"Implied Gross Yield (%)": _impl_yields}, index=_months)
                                st.line_chart(_ydf)
                                st.caption(f"Implied yield = ${_est_rent:,}/mo benchmark rent ÷ monthly median price. Yield rises when prices fall.")
                            else:
                                st.info("Rental benchmark not available for this flat type — cannot compute yield trend.")
                    else:
                        st.caption("Not enough data for trend chart.")

                    # Insurance trigger
                    if result.get("insurance_suggestions"):
                        with st.expander("🛡️ Insurance check for this property"):
                            for ins in result["insurance_suggestions"][:2]:
                                st.write(f"**{ins['call_to_action']}** — [{ins['partner']}]({ins['website']})")
                                st.caption(ins["disclaimer"])

        # Address search helper
        st.divider()
        st.subheader("🔎 Don't know the exact street name?")
        search_hint = st.text_input("Search by keyword (e.g. 'TAMPINES ST', 'ANG MO KIO AVE')", placeholder="Type street keyword...")
        if search_hint and len(search_hint) >= 4:
            from data.hdb_pipeline import search_by_street
            suggestions = search_by_street(search_hint, limit=8)
            if suggestions:
                st.write(f"Found {len(suggestions)} matching addresses:")
                for s in suggestions:
                    st.write(f"• Block **{s['block']}** {s['street_name']} — {s['flat_type']} — ${s['resale_price']:,.0f} ({s['month']})")
            else:
                st.write("No matches found. Try a different keyword.")

    else:
        st.subheader("🏢 Private Condo / Apartment Lookup")

        # ── Input: Postal Code OR Project Name ───────────────────────────────
        _priv_mode = st.radio("Search by", ["📮 Postal Code", "🏢 Project Name"], horizontal=True, key="priv_addr_mode")

        _priv_project = ""
        _priv_district = 15

        if _priv_mode == "📮 Postal Code":
            _priv_postal = st.text_input("Postal Code (6 digits)", max_chars=6, placeholder="e.g. 018956", key="priv_postal")
            if _priv_postal and len(_priv_postal) == 6 and _priv_postal.isdigit():
                try:
                    _om_p = _requests_lib.get(
                        "https://www.onemap.gov.sg/api/common/elastic/search"
                        f"?searchVal={_priv_postal}&returnGeom=N&getAddrDetails=Y&pageNum=1",
                        timeout=6
                    ).json()
                    _om_pr = (_om_p.get("results") or [{}])[0]
                    _priv_bldg = (_om_pr.get("BUILDING","") or "").strip()
                    _priv_road = (_om_pr.get("ROAD_NAME","") or "").strip()
                    _priv_blk  = (_om_pr.get("BLK_NO","")   or "").strip()
                    # Prefer building name; fall back to road name
                    if _priv_bldg and _priv_bldg.upper() not in ("NIL",""):
                        _priv_project = _priv_bldg
                        st.success(f"📍 Resolved: **{_priv_bldg}** ({_priv_road})")
                    elif _priv_road:
                        _priv_project = _priv_road
                        st.info(f"📍 No building name found — searching by road: **{_priv_road}**")
                    else:
                        st.warning("Could not resolve this postal code. Try Project Name search.")
                    # Estimate district from postal sector
                    _ps = int(_priv_postal[:2])
                    _PS_DIST = {1:1,2:1,3:1,4:4,5:5,6:6,7:7,8:8,9:9,10:10,11:11,12:12,
                                13:14,14:14,15:15,16:16,17:17,18:18,19:19,20:20,21:21,
                                22:22,23:23,24:24,25:25,26:26,27:27,28:28}
                    _priv_district = _PS_DIST.get(_ps, 15)
                except Exception as _pe:
                    st.warning(f"Postal lookup failed: {_pe}")
        else:
            _priv_project  = st.text_input("Project / Condo Name", placeholder="e.g. The Sail, Parc Clematis, Marina Bay Sands Residences", key="priv_project_name")

        col1, col2, col3 = st.columns(3)
        with col1:
            district  = st.number_input("District (for benchmark)", 1, 28, _priv_district, key="priv_dist_num")
        with col2:
            area_sqft = st.number_input("Area (sqft)", 300, 5000, 1000, key="priv_area_num")
        with col3:
            priv_floor = st.number_input("Floor / Storey", 1, 80, 10, key="priv_floor_addr",
                                         help="Used to filter results to similar floors (±5 floors)")
        asking = st.number_input("Asking Price (SGD)", 0, 20000000, 0, step=10000, key="priv_ask")

        if st.button("🔍 Look Up Property", type="primary", key="priv_lookup_btn"):
            agent = ValuationAgent()
            # ── Search URA transaction cache by project name ──────────────────
            if _priv_project:
                with st.spinner(f"Searching URA transactions for '{_priv_project}'..."):
                    try:
                        from agents.price_history import get_project_history as _priv_ph
                        _all_ura = _cached_ura_transactions()
                        _ph_data = _priv_ph(_priv_project, _all_ura)
                    except Exception as _ue:
                        _ph_data = None
                        st.error(f"URA search error: {_ue}")

                if _ph_data and _ph_data.get("match_count", 0) > 0:
                    q_list      = _ph_data.get("quarters", [])
                    earliest_q  = q_list[0] if q_list else {}
                    latest_q    = q_list[-1] if q_list else {}
                    _med_psf_al = _ph_data.get("latest_median_psf", 0)

                    # ── Filter to nearby floors (±5 of selected floor) ────────
                    import re as _re2
                    _all_ura2b = _cached_ura_transactions()
                    _proj_all_txns = [t for t in _all_ura2b
                                      if _priv_project.lower() in str(t.get("project","")).lower()]
                    _floor_txns = []
                    for _ft in _proj_all_txns:
                        _fr = str(_ft.get("floor_range","") or "")
                        _nums = _re2.findall(r'\d+', _fr)
                        if _nums:
                            _f_mid = (int(_nums[0]) + int(_nums[-1])) // 2
                            if abs(_f_mid - priv_floor) <= 5:
                                _floor_txns.append(_ft)

                    _floor_psfs = [float(t.get("psf_sgd",0)) for t in _floor_txns if t.get("psf_sgd",0) > 0]
                    _floor_med_psf = round(sum(_floor_psfs)/len(_floor_psfs)) if _floor_psfs else _med_psf_al

                    # Floor premium vs overall median
                    _floor_prem = round((_floor_med_psf - _med_psf_al) / _med_psf_al * 100, 1) if _med_psf_al else 0

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Transactions",     f"{_ph_data['match_count']:,}",
                              help=f"From {earliest_q.get('quarter','')} to {latest_q.get('quarter','')}")
                    c2.metric("Overall Median PSF",     f"SGD {_med_psf_al:,}",
                              delta=f"{_ph_data['psf_change_pct']:+.1f}% all-time")
                    c3.metric(f"Floor ~{priv_floor} Median PSF",
                              f"SGD {_floor_med_psf:,}" if _floor_psfs else "—",
                              delta=f"{_floor_prem:+.1f}% vs overall" if _floor_psfs else "No floor data",
                              help=f"{len(_floor_txns)} transactions within ±5 floors of floor {priv_floor}")
                    _est_val = round(_floor_med_psf * area_sqft)
                    c4.metric("Est. Value (your unit)", f"SGD {_est_val:,.0f}",
                              help=f"Floor-adjusted PSF × {area_sqft:,} sqft")

                    if asking > 0 and _med_psf_al:
                        _ask_psf = round(asking / area_sqft)
                        _vs_ask  = round((asking - _est_val) / _est_val * 100, 1) if _est_val else 0
                        st.divider()
                        va, vb, vc = st.columns(3)
                        va.metric("Asking PSF",          f"SGD {_ask_psf:,}")
                        vb.metric("Asking vs Est. Value", f"{_vs_ask:+.1f}%")
                        vc.metric("Verdict", "Above market 🔴" if _vs_ask > 5 else ("Fair value 🟡" if abs(_vs_ask)<=5 else "Below market 🟢"))

                    # ── PSF trend chart ───────────────────────────────────────
                    if q_list and _med_psf_al > 0:
                        import pandas as _upd
                        _udf = _upd.DataFrame(q_list).set_index("quarter")
                        st.divider()
                        st.subheader(f"📈 PSF Trend — {_priv_project.title()}")
                        if not _udf.empty and _udf["median_psf"].max() > 0:
                            st.line_chart(_udf["median_psf"], height=240, use_container_width=True)
                        else:
                            st.info("PSF trend chart unavailable — check URA data sync.")
                        st.dataframe(_udf[["median_psf","min_psf","max_psf","count","median_price"]].rename(columns={
                            "median_psf":"Median PSF","min_psf":"Min PSF","max_psf":"Max PSF",
                            "count":"# Txns","median_price":"Median Price (SGD)"
                        }), use_container_width=True)

                    # ── Recent transactions (similar floors) ──────────────────
                    if _floor_txns or _proj_all_txns:
                        st.divider()
                        _show_txns = (_floor_txns if _floor_txns else _proj_all_txns)[:30]
                        _show_txns = sorted(_show_txns, key=lambda t: t.get("contract_date",""), reverse=True)
                        st.subheader(f"📋 Recent Transactions{' (Floor ±5)' if _floor_txns else ''} — {_priv_project.title()}")
                        import pandas as _txpd2
                        st.dataframe(_txpd2.DataFrame([{
                            "Date":       t.get("contract_date",""),
                            "Floor Range":t.get("floor_range",""),
                            "Area (sqft)":int(t.get("area_sqft",0) or 0),
                            "Price (SGD)":f"${t.get('price_sgd',0):,.0f}",
                            "PSF":        f"${t.get('psf_sgd',0):,.0f}",
                            "Type":       t.get("property_type",""),
                            "Tenure":     t.get("tenure",""),
                        } for t in _show_txns]), hide_index=True, use_container_width=True)
                        st.caption(f"Showing {len(_show_txns)} of {len(_proj_all_txns)} total transactions"
                                   + (f" ({len(_floor_txns)} near floor {priv_floor})" if _floor_txns else ""))

                    # ── Rental intel for this project's district ──────────────
                    _show_rental_intel(district, _est_val, area_sqft=area_sqft)
                else:
                    st.warning(f"No URA transactions found for **{_priv_project}**. Showing district benchmark instead.")
                    # Fall through to district benchmark
                    with st.spinner("Loading district benchmark..."):
                        _bench = agent.value_private_property(district, area_sqft, asking_price=asking, explain=bool(asking))
                    if _bench.get("status") == "ok":
                        c1, c2, c3 = st.columns(3)
                        c1.metric("District Estimated Value", f"${_bench['estimated_value_sgd']:,.0f}")
                        c2.metric("Median PSF",               f"${_bench['median_psf']:,.0f}")
                        c3.metric("PSF Range",                f"${_bench['p25_psf']:,.0f}–${_bench['p75_psf']:,.0f}")
                    _show_rental_intel(district, _bench.get("estimated_value_sgd",0) if _bench.get("status")=="ok" else 0, area_sqft=area_sqft)

            else:
                # No project name — show district benchmark only
                with st.spinner("Calculating district benchmark..."):
                    _bench2 = agent.value_private_property(district, area_sqft, asking_price=asking, explain=bool(asking))
                if _bench2.get("status") == "ok":
                    st.info(f"📊 District {district} benchmark")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Estimated Value", f"${_bench2['estimated_value_sgd']:,.0f}")
                    c2.metric("Median PSF",      f"${_bench2['median_psf']:,.0f}")
                    c3.metric("PSF Range",       f"${_bench2['p25_psf']:,.0f}–${_bench2['p75_psf']:,.0f}")
                    if asking > 0:
                        st.metric("vs District Median", f"{_bench2.get('vs_median_pct',0):+.1f}%", _bench2.get("verdict",""))
                    _show_rental_intel(district, _bench2.get("estimated_value_sgd",0), area_sqft=area_sqft)
                else:
                    st.warning(_bench2.get("message", "Insufficient data"))

# ── Deal Feed ─────────────────────────────────────────────────────────────────
elif tab_select == "📊 Deal Feed":
    st.header("📊 Deal Feed")
    st.caption("Properties trading below district/town median")

    deal_tab1, deal_tab2, deal_tab3 = st.tabs(["🏠 HDB Below Market", "📈 Rental Yield by Town", "🏢 Private Condo"])

    with deal_tab1:
        col1, col2 = st.columns(2)
        threshold = col1.slider("Min % below town median", 5, 30, 8, key="hdb_thresh")
        limit = col2.slider("Max results", 5, 20, 10, key="hdb_limit")
        if st.button("🔍 Scan HDB Deals", type="primary", key="scan_hdb"):
            agent = DealHunterAgent()
            with st.spinner("Scanning 10,000 recent HDB transactions..."):
                result = agent.scan_hdb_deals(threshold_pct=threshold, limit=limit)
            deals = result.get("top_deals", [])
            if not deals:
                st.info(f"No deals found {threshold}%+ below town median. Try lowering the threshold to 5%.")
            else:
                st.success(f"Found **{result['opportunities_found']}** qualifying deals — showing top {len(deals)}")
                for deal in deals:
                    label = f"🏠 {deal.get('town','')} {deal.get('flat_type','')} — {deal.get('discount_pct',0):.1f}% below median — ${deal.get('resale_price',0):,.0f} ({deal.get('month','')})"
                    with st.expander(label):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Resale Price", f"${deal.get('resale_price',0):,.0f}")
                        c2.metric("Town Median PSF", f"${deal.get('median_psf',0):,.0f}")
                        c3.metric("Potential Gain", f"${deal.get('potential_gain_sgd',0):,.0f}")
                        st.caption(f"📍 {deal.get('street_name','')} | {deal.get('storey_range','')} | {deal.get('floor_area_sqft',0):.0f} sqft")

    with deal_tab2:
        st.caption("Gross yield = estimated annual rent / median resale price × 100")
        target_yield = st.slider("Min gross yield %", 2.0, 8.0, 3.5, step=0.5, key="yield_slider")
        if st.button("Calculate Yields by Town", type="primary", key="scan_yield"):
            agent = DealHunterAgent()
            with st.spinner("Computing yields across all HDB towns..."):
                arb = agent.scan_hdb_rental_yield(target_gross_yield_pct=target_yield)
            opps = arb.get("opportunities", [])
            if not opps:
                st.info(f"No towns found with gross yield above {target_yield}%. Try lowering to 2.5%.")
            else:
                st.success(f"**{len(opps)} towns** meet the {target_yield}% yield target")
                for opp in opps:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Town", opp['town'])
                    c2.metric("Gross Yield", f"{opp['gross_yield_pct']}%")
                    c3.metric("Net Yield (est.)", f"{opp['net_yield_pct']}%")
                    c4.metric("Median Resale", f"${opp['median_price_sgd']:,.0f}")

    with deal_tab3:
        st.subheader("🏢 Private Condo Deal Scanner")

        # Check if URA cache exists
        _ura_cache = ROOT / "cache" / "ura" / "transactions_batch1.json"
        if _ura_cache.exists():
            try:
                import json as _json
                _ura_data = _json.loads(_ura_cache.read_text())
                _txns = _ura_data.get("transactions", [])
                if _txns:
                    # Show real deals from cache
                    import pandas as _pd, statistics as _stats
                    from collections import defaultdict as _dd
                    _by_district: dict = _dd(list)
                    for t in _txns:
                        d = str(t.get("district", ""))
                        psf = t.get("psf_sgd", 0)
                        if d and psf and psf > 0:
                            _by_district[d].append(t)

                    _threshold = st.slider("Deal threshold: % below district median PSF", 5, 20, 8, key="ura_thresh")
                    _deals = []
                    for dist, txns in _by_district.items():
                        psfs = [t["psf_sgd"] for t in txns if t.get("psf_sgd", 0) > 0]
                        if len(psfs) < 5:
                            continue
                        med = _stats.median(psfs)
                        for t in txns:
                            disc = (med - t["psf_sgd"]) / med * 100
                            if disc >= _threshold:
                                t["median_psf"] = round(med, 0)
                                t["discount_pct"] = round(disc, 1)
                                t["upside_sgd"] = round((med - t["psf_sgd"]) * t.get("area_sqft", 0), 0)
                                _deals.append(t)

                    _deals.sort(key=lambda x: x["discount_pct"], reverse=True)
                    st.success(f"**{len(_deals)} private condo deals** found {_threshold}%+ below district median PSF")
                    for d in _deals[:10]:
                        with st.expander(f"🟢 {d['project']} — D{d['district']} · {d['discount_pct']}% below median"):
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Price", f"SGD {d['price_sgd']:,.0f}")
                            c2.metric("PSF", f"SGD {d['psf_sgd']:,.0f}")
                            c3.metric("Median PSF", f"SGD {d['median_psf']:,.0f}")
                            c4.metric("Potential upside", f"SGD {d['upside_sgd']:,.0f}")
                            st.caption(f"{d.get('street','')} · {d.get('area_sqft',0):.0f} sqft · {d.get('property_type','')} · {d.get('tenure','')} · {d.get('contract_date','')}")
                else:
                    st.warning("URA cache is empty. Run: `python scripts/sync_ura.py` on the VPS to fetch data.")
            except Exception as _e:
                st.error(f"Error reading URA cache: {_e}")
        else:
            st.info(
                "Private condo data not yet synced. On the VPS, run:\n\n"
                "```\ncd /root/propos && .venv/bin/python scripts/sync_ura.py\n```\n\n"
                "This fetches all 28 districts from URA. Takes ~2 minutes. "
                "After that, deals will appear here automatically."
            )

# ── Valuation ─────────────────────────────────────────────────────────────────
elif tab_select == "🔍 Valuation":
    st.header("🔍 Property Valuation")

    val_type = st.radio("Property type", ["🏠 HDB Resale", "🏢 Private Condo/Apt", "📊 Market Heatmap"], horizontal=True)

    # ── Session state init — Private Condo results ────────────────────────────
    for _sk in ("val_priv_result", "val_priv_proj_hist", "val_priv_district",
                "val_priv_floor", "val_priv_area", "val_priv_project_name",
                "val_priv_path"):
        if _sk not in st.session_state:
            st.session_state[_sk] = None

    # Clear Private Condo results when switching away from that tab
    if val_type != "🏢 Private Condo/Apt":
        for _sk in ("val_priv_result", "val_priv_proj_hist", "val_priv_path"):
            st.session_state[_sk] = None

    if val_type == "🏠 HDB Resale":
        records = _cached_hdb_records()
        towns_available = sorted(set(r['town'] for r in records))

        # ── Input method: postal code OR town picker ──────────────────────────
        _val_input_method = st.radio("Enter by", ["🏘️ Town / Flat Type", "📮 Postal Code"], horizontal=True, key="val_hdb_input_method")

        # ── session state for resolved postal address ─────────────────────────
        if "val_postal_block"  not in st.session_state: st.session_state["val_postal_block"]  = ""
        if "val_postal_street" not in st.session_state: st.session_state["val_postal_street"] = ""
        if "val_postal_town"   not in st.session_state: st.session_state["val_postal_town"]   = ""

        if _val_input_method == "📮 Postal Code":
            _val_postal = st.text_input("Postal Code (6 digits)", max_chars=6, placeholder="e.g. 400320", key="val_postal_code")
            col1, col2 = st.columns(2)
            with col1:
                flat_type  = st.selectbox("Flat Type", ["4 ROOM", "3 ROOM", "5 ROOM", "EXECUTIVE"], key="val_ft_postal")
            with col2:
                area_sqft  = st.number_input("Floor Area (sqft)", 500, 2000, 1000, key="val_area_postal")
            asking_price   = st.number_input("Asking Price (SGD, 0 = estimate only)", 0, 2000000, 0, step=5000, key="val_ask_postal")

            # Resolve postal → block + street via OneMap (fires on each keystroke, stores in state)
            if _val_postal and len(_val_postal) == 6 and _val_postal.isdigit():
                try:
                    _om_val   = _requests_lib.get(
                        "https://www.onemap.gov.sg/api/common/elastic/search"
                        f"?searchVal={_val_postal}&returnGeom=N&getAddrDetails=Y&pageNum=1",
                        timeout=6
                    ).json()
                    _om_val_r = (_om_val.get("results") or [{}])[0]
                    _resolved_blk  = (_om_val_r.get("BLK_NO","")    or "").strip()
                    _resolved_road = (_om_val_r.get("ROAD_NAME","")  or "").strip()
                    _resolved_bldg = (_om_val_r.get("BUILDING","")   or "").strip()
                    if _resolved_blk and _resolved_road:
                        st.session_state["val_postal_block"]  = _resolved_blk
                        st.session_state["val_postal_street"] = _resolved_road
                        # Confirm address from HDB records
                        _addr_match = next(
                            (r for r in records
                             if _resolved_blk.lower() == r.get("block","").lower()
                             and _resolved_road.lower() in r.get("street_name","").lower()),
                            None
                        )
                        _resolved_town = _addr_match["town"] if _addr_match else "Unknown"
                        st.session_state["val_postal_town"] = _resolved_town
                        _bldg_note = f" ({_resolved_bldg})" if _resolved_bldg and _resolved_bldg.upper() not in ("NIL","") else ""
                        st.success(f"📍 **Block {_resolved_blk} {_resolved_road}**{_bldg_note} · Town: **{_resolved_town}**")
                        if not _addr_match:
                            st.caption("⚠️ No HDB resale records found for this exact block — valuation will use town-level data.")
                    else:
                        st.warning("OneMap could not resolve this postal code. Check the number or use Town picker.")
                except Exception as _ve:
                    st.warning(f"Postal lookup error: {_ve}")
            elif _val_postal:
                st.caption("Enter all 6 digits.")

            # Use resolved values from state
            town = st.session_state.get("val_postal_town") or (towns_available[0] if towns_available else "TAMPINES")
            _postal_block  = st.session_state.get("val_postal_block","")
            _postal_street = st.session_state.get("val_postal_street","")

        else:
            col1, col2 = st.columns(2)
            with col1:
                town = st.selectbox("Town", towns_available, index=towns_available.index("TAMPINES") if "TAMPINES" in towns_available else 0)
                flat_type = st.selectbox("Flat Type", ["3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"])
            with col2:
                area_sqft    = st.number_input("Floor Area (sqft)", 500, 2000, 1000)
                asking_price = st.number_input("Asking Price (SGD, 0 = estimate only)", 0, 2000000, 0, step=5000)
            _postal_block  = ""
            _postal_street = ""

        if st.button("Value HDB", type="primary", key="val_hdb"):
            agent = ValuationAgent()
            # ── Postal mode with resolved block → address-specific lookup ─────
            if _val_input_method == "📮 Postal Code" and _postal_block and _postal_street:
                st.session_state["val_hdb_show_trend"] = False  # postal shows block-specific, not town trend
                with st.spinner(f"Looking up Block {_postal_block} {_postal_street}..."):
                    result = agent.value_by_address(_postal_block, _postal_street, asking_price, flat_type, explain=bool(asking_price))
                if result.get("status") == "ok":
                    st.success(f"✅ Found **{result.get('transaction_count',0)} transactions** for Block {_postal_block} {_postal_street}")
                    st.caption(f"🏘️ Town: {result.get('town','')} | Type: {result.get('flat_type','')} | Lease remaining: {result.get('remaining_lease','')}")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Latest Price",    f"${result.get('latest_transacted_price',0):,.0f}", result.get('latest_transaction_month',''))
                    c2.metric("Latest PSF",      f"${result.get('latest_transacted_psf',0):,.0f}")
                    c3.metric("Address Median",  f"${result.get('address_median_price',0):,.0f}")
                    c4.metric("Town Median",     f"${result.get('town_median_price',0):,.0f}")
                    if asking_price > 0:
                        st.divider()
                        _vs_addr  = result.get("vs_address_history_pct", 0)
                        _vs_town  = result.get("vs_town_median_pct")
                        ca, cb, cc = st.columns(3)
                        ca.metric("Asking vs This Block",  f"{_vs_addr:+.1f}%")
                        if _vs_town is not None:
                            cb.metric("Asking vs Town Median", f"{_vs_town:+.1f}%")
                        cc.metric("Deal Score", f"{result.get('deal_score',0)}/100")
                        st.info(f"**Verdict:** {result.get('verdict','')}")
                    # Recent transactions table
                    _addr_txns = result.get("recent_transactions",[])
                    if _addr_txns:
                        st.divider()
                        st.subheader(f"📋 Transaction History — Block {_postal_block} {_postal_street}")
                        import pandas as _ap
                        st.dataframe(_ap.DataFrame([{
                            "Month":       t.get("month",""),
                            "Flat Type":   t.get("flat_type",""),
                            "Storey":      t.get("storey_range",""),
                            "Area (sqft)": int(t.get("floor_area_sqft",0) or 0),
                            "Price (SGD)": f"${t.get('resale_price',0):,.0f}",
                            "PSF":         f"${t.get('psf_sgd',0):,.0f}",
                        } for t in _addr_txns]), hide_index=True, use_container_width=True)
                    # ── Rental Benchmark (postal path) ──────────────────────────
                    _post_town = result.get("town","").upper()
                    _post_ft   = result.get("flat_type","4 ROOM")
                    _pft_key   = _post_ft if _post_ft in ("3 ROOM","4 ROOM","5 ROOM","EXECUTIVE") else "4 ROOM"
                    _post_rent_map = {
                        "ANG MO KIO":     {"3 ROOM":2300,"4 ROOM":2800,"5 ROOM":3200,"EXECUTIVE":3500},
                        "BEDOK":          {"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                        "BISHAN":         {"3 ROOM":2400,"4 ROOM":3000,"5 ROOM":3400,"EXECUTIVE":3700},
                        "BUKIT BATOK":    {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "BUKIT MERAH":    {"3 ROOM":2600,"4 ROOM":3200,"5 ROOM":3700,"EXECUTIVE":4000},
                        "BUKIT PANJANG":  {"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                        "BUKIT TIMAH":    {"3 ROOM":2800,"4 ROOM":3500,"5 ROOM":4000,"EXECUTIVE":4500},
                        "CENTRAL AREA":   {"3 ROOM":3200,"4 ROOM":4200,"5 ROOM":5000,"EXECUTIVE":5500},
                        "CHOA CHU KANG":  {"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                        "CLEMENTI":       {"3 ROOM":2400,"4 ROOM":2900,"5 ROOM":3400,"EXECUTIVE":3700},
                        "GEYLANG":        {"3 ROOM":2200,"4 ROOM":2800,"5 ROOM":3200,"EXECUTIVE":3500},
                        "HOUGANG":        {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "JURONG EAST":    {"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                        "JURONG WEST":    {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "KALLANG/WHAMPOA":{"3 ROOM":2500,"4 ROOM":3100,"5 ROOM":3600,"EXECUTIVE":3900},
                        "MARINE PARADE":  {"3 ROOM":2600,"4 ROOM":3200,"5 ROOM":3700,"EXECUTIVE":4000},
                        "PASIR RIS":      {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "PUNGGOL":        {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "QUEENSTOWN":     {"3 ROOM":2700,"4 ROOM":3400,"5 ROOM":3900,"EXECUTIVE":4200},
                        "SEMBAWANG":      {"3 ROOM":1900,"4 ROOM":2400,"5 ROOM":2800,"EXECUTIVE":3100},
                        "SENGKANG":       {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                        "SERANGOON":      {"3 ROOM":2300,"4 ROOM":2900,"5 ROOM":3300,"EXECUTIVE":3600},
                        "TAMPINES":       {"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                        "TOA PAYOH":      {"3 ROOM":2400,"4 ROOM":3000,"5 ROOM":3500,"EXECUTIVE":3800},
                        "WOODLANDS":      {"3 ROOM":1900,"4 ROOM":2400,"5 ROOM":2800,"EXECUTIVE":3100},
                        "YISHUN":         {"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                    }
                    _post_rent_val = _post_rent_map.get(_post_town, {}).get(_pft_key, 0)
                    _post_val      = result.get("address_median_price", 0) or result.get("latest_transacted_price", 0)
                    st.divider()
                    st.subheader(f"🏘️ Rental Market — {_post_town} {_post_ft}")
                    if _post_rent_val:
                        _pg  = round(_post_rent_val * 12 / _post_val * 100, 2) if _post_val else 0
                        _pn  = round(_pg - 0.8, 2) if _pg else 0
                        hpa, hpb, hpc, hpd = st.columns(4)
                        hpa.metric("Est. Monthly Rent",  f"${_post_rent_val:,}",
                                   help="SRX 2024–25 median for this flat type and town")
                        hpb.metric("Rent Range",         f"${round(_post_rent_val*0.88/100)*100:,} – ${round(_post_rent_val*1.12/100)*100:,}")
                        hpc.metric("Est. Gross Yield",   f"{_pg:.2f}%" if _pg else "—",
                                   help="Annual rent ÷ address median price")
                        hpd.metric("Est. Net Yield",     f"{_pn:.2f}%" if _pn else "—",
                                   help="After ~0.8% p.a. for maintenance and vacancy")
                        st.caption(
                            "HDB rental: MOP (5 years) must be met before renting entire flat. "
                            "Sub-letting requires HDB approval. Benchmark from SRX — actual rent "
                            "varies by floor, renovation and proximity to MRT."
                        )
                    else:
                        st.info(f"No rental benchmark available for {_post_town}.")
                else:
                    st.warning(result.get("message","Address not found — try Address Lookup tab or use Town picker."))
                    if result.get("suggestions"):
                        st.write("**Nearby addresses:**")
                        for _s in result["suggestions"][:5]:
                            st.write(f"  • {_s}")

            # ── Town-level lookup (default / fallback) ─────────────────────────
            else:
                st.session_state["val_hdb_show_trend"]  = True
                st.session_state["val_hdb_trend_town"]  = town
                st.session_state["val_hdb_trend_ft"]    = flat_type
                with st.spinner("Analysing transactions..."):
                    result = agent.value_hdb(town.upper(), flat_type, area_sqft, asking_price, explain=bool(asking_price))
                if result.get("status") == "ok":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Estimated Value",   f"${result['estimated_value_sgd']:,.0f}")
                    c2.metric("Town Median",       f"${result['median_price_sgd']:,.0f}")
                    c3.metric("Transactions Used", result['transactions_used'])
                    if asking_price > 0:
                        st.metric("vs Town Median", f"{result.get('vs_median_pct',0):+.1f}%", delta=result.get('verdict',''))
                        st.info(f"Deal Score: **{result.get('deal_score',0)}/100**")
                    if result.get("explanation"):
                        st.write("**AI Analysis:**", result["explanation"])
                    st.divider()
                    if st.button("📄 Download Valuation Report (PDF)", key="pdf_hdb"):
                        try:
                            from agents.pdf_report import generate_valuation_report
                            _ft_key2  = flat_type if flat_type in ("3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE") else "4 ROOM"
                            _rent_est = _VAL_TOWN_RENT.get(town.upper(), {}).get(_ft_key2, 0) if '_VAL_TOWN_RENT' in dir() else 0
                            pdf_bytes = generate_valuation_report(
                                property_address=f"{town} — {flat_type}",
                                property_type="HDB Resale",
                                area_sqft=area_sqft,
                                estimated_value=result.get("estimated_value_sgd", 0),
                                median_price=result.get("median_price_sgd", 0),
                                transactions_used=result.get("transactions_used", 0),
                                asking_price=asking_price,
                                vs_median_pct=result.get("vs_median_pct", 0),
                                verdict=result.get("verdict", ""),
                                ai_analysis=result.get("explanation", ""),
                                rental_monthly=_rent_est,
                                gross_yield_pct=round(_rent_est * 12 / result["estimated_value_sgd"] * 100, 2) if _rent_est and result.get("estimated_value_sgd") else 0,
                            )
                            st.download_button("💾 Save PDF", pdf_bytes,
                                file_name=f"PropOS_{town}_{flat_type.replace(' ','_')}_{date.today()}.pdf",
                                mime="application/pdf", key="dl_pdf_hdb")
                        except ImportError:
                            st.warning("PDF export requires `fpdf2`.")
                        except Exception as _pe:
                            st.error(f"PDF error: {_pe}")
                else:
                    st.warning(result.get("message", "Insufficient data for this town/flat type"))

        # ── Trend + recent transactions: only render after button click ─────────
        # Stored in session_state so charts don't render on page load (avoids
        # Vega 'Infinite extent' WebSocket crash when data not yet loaded)
        if st.session_state.get("val_hdb_show_trend"):
            _trend_town = st.session_state.get("val_hdb_trend_town", town)
            _trend_ft   = st.session_state.get("val_hdb_trend_ft",   flat_type)
            st.divider()
            st.subheader(f"📈 {_trend_town} — Price & Rental Yield Trend ({_trend_ft})")
            _VAL_TOWN_RENT = {
                "ANG MO KIO":     {"3 ROOM":2300,"4 ROOM":2800,"5 ROOM":3200,"EXECUTIVE":3500},
                "BEDOK":          {"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                "BISHAN":         {"3 ROOM":2400,"4 ROOM":3000,"5 ROOM":3400,"EXECUTIVE":3700},
                "BUKIT BATOK":    {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                "BUKIT MERAH":    {"3 ROOM":2600,"4 ROOM":3200,"5 ROOM":3700,"EXECUTIVE":4000},
                "BUKIT PANJANG":  {"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                "CENTRAL AREA":   {"3 ROOM":3200,"4 ROOM":4200,"5 ROOM":5000,"EXECUTIVE":5500},
                "CHOA CHU KANG":  {"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                "CLEMENTI":       {"3 ROOM":2400,"4 ROOM":2900,"5 ROOM":3400,"EXECUTIVE":3700},
                "GEYLANG":        {"3 ROOM":2200,"4 ROOM":2800,"5 ROOM":3200,"EXECUTIVE":3500},
                "HOUGANG":        {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                "JURONG EAST":    {"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                "JURONG WEST":    {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                "KALLANG/WHAMPOA":{"3 ROOM":2500,"4 ROOM":3100,"5 ROOM":3600,"EXECUTIVE":3900},
                "MARINE PARADE":  {"3 ROOM":2600,"4 ROOM":3200,"5 ROOM":3700,"EXECUTIVE":4000},
                "PASIR RIS":      {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                "PUNGGOL":        {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                "QUEENSTOWN":     {"3 ROOM":2700,"4 ROOM":3400,"5 ROOM":3900,"EXECUTIVE":4200},
                "SEMBAWANG":      {"3 ROOM":1900,"4 ROOM":2400,"5 ROOM":2800,"EXECUTIVE":3100},
                "SENGKANG":       {"3 ROOM":2100,"4 ROOM":2600,"5 ROOM":3000,"EXECUTIVE":3300},
                "SERANGOON":      {"3 ROOM":2300,"4 ROOM":2900,"5 ROOM":3300,"EXECUTIVE":3600},
                "TAMPINES":       {"3 ROOM":2200,"4 ROOM":2700,"5 ROOM":3100,"EXECUTIVE":3400},
                "TOA PAYOH":      {"3 ROOM":2400,"4 ROOM":3000,"5 ROOM":3500,"EXECUTIVE":3800},
                "WOODLANDS":      {"3 ROOM":1900,"4 ROOM":2400,"5 ROOM":2800,"EXECUTIVE":3100},
                "YISHUN":         {"3 ROOM":2000,"4 ROOM":2500,"5 ROOM":2900,"EXECUTIVE":3200},
                "BUKIT TIMAH":    {"3 ROOM":2800,"4 ROOM":3500,"5 ROOM":4000,"EXECUTIVE":4500},
            }
            from collections import defaultdict as _defdict
            import pandas as _tpd
            _ft_key2  = _trend_ft if _trend_ft in ("3 ROOM","4 ROOM","5 ROOM","EXECUTIVE") else "4 ROOM"
            _brent    = _VAL_TOWN_RENT.get(_trend_town.upper(), {}).get(_ft_key2, 0)
            _trecs    = [r for r in records
                         if r.get("town","") == _trend_town
                         and _ft_key2.lower() in r.get("flat_type","").lower()
                         and r.get("resale_price", 0) > 0]
            if _trecs:
                _tmonthly: dict = _defdict(list)
                for r in _trecs:
                    _tmonthly[r["month"]].append(r["resale_price"])
                _tmonths = sorted(_tmonthly.keys())[-18:]
                _tprices = [sorted(_tmonthly[m])[len(_tmonthly[m])//2] for m in _tmonths]
                _tyields = [round(_brent * 12 / p * 100, 2) if _brent and p else 0 for p in _tprices]

                vt1, vt2, vt3 = st.tabs(["💰 Median Price", "🏘️ Est. Monthly Rent", "📈 Implied Gross Yield"])
                with vt1:
                    if _tprices and any(p > 0 for p in _tprices):
                        st.line_chart(_tpd.DataFrame({"Median Price (SGD)": _tprices}, index=_tmonths))
                        st.caption(f"Median resale prices — {_trend_ft} in {_trend_town}, last {len(_tmonths)} months")
                    else:
                        st.info("No price trend data available.")
                with vt2:
                    if _brent:
                        st.metric("Benchmark Monthly Rent", f"${_brent:,}/mo")
                        st.metric("Estimated Annual Income", f"${_brent*12:,}")
                        st.info(f"SRX 2024–25 median for **{_ft_key2}** in **{_trend_town}**. Actual rent varies by floor, condition and MRT proximity.")
                    else:
                        st.info("No rental benchmark available.")
                with vt3:
                    _valid_yields = [y for y in _tyields if y > 0]
                    if _brent and _valid_yields:
                        st.line_chart(_tpd.DataFrame({"Gross Yield (%)": _tyields}, index=_tmonths))
                        st.caption(f"Implied gross yield — current: **{_tyields[-1]:.2f}%** / net ~**{round(_tyields[-1]-1.2,2):.2f}%**")
                    else:
                        st.info("No yield trend available.")

                # Recent transactions
                st.divider()
                st.subheader(f"🧾 Recent Transactions — {_trend_town} {_trend_ft}")
                _rrecs = sorted(
                    [r for r in records
                     if r.get("town","").upper() == _trend_town.upper()
                     and _ft_key2.lower() in r.get("flat_type","").lower()
                     and r.get("resale_price", 0) > 0],
                    key=lambda r: r.get("month",""), reverse=True
                )[:25]
                if _rrecs:
                    st.dataframe(_tpd.DataFrame([{
                        "Month":       r.get("month",""),
                        "Block":       r.get("block",""),
                        "Street":      r.get("street_name",""),
                        "Type":        r.get("flat_type",""),
                        "Storey":      r.get("storey_range",""),
                        "Area (sqft)": int(r.get("floor_area_sqft",0)),
                        "Price (SGD)": f"${r.get('resale_price',0):,.0f}",
                        "PSF":         f"${r.get('psf_sgd',0):,.0f}",
                        "Lease Rem.":  r.get("remaining_lease",""),
                    } for r in _rrecs]), hide_index=True, use_container_width=True)
                    st.caption(f"{len(_rrecs)} most recent {_trend_ft} transactions in {_trend_town}, newest first.")
                else:
                    st.info(f"No recent transactions found for {_trend_ft} in {_trend_town}.")

                # ── HDB Rental Benchmark ──────────────────────────────────────
                st.divider()
                st.subheader(f"🏘️ Rental Market — {_trend_town} {_trend_ft}")
                _hdb_rent = _VAL_TOWN_RENT.get(_trend_town.upper(), {})
                _hdb_rent_val = _hdb_rent.get(_ft_key2, 0)
                if _hdb_rent_val:
                    _latest_price = _tprices[-1] if _tprices else 0
                    _hdb_gross_y  = round(_hdb_rent_val * 12 / _latest_price * 100, 2) if _latest_price else 0
                    _hdb_net_y    = round(_hdb_gross_y - 0.8, 2) if _hdb_gross_y else 0
                    hrc1, hrc2, hrc3, hrc4 = st.columns(4)
                    hrc1.metric("Est. Monthly Rent",  f"${_hdb_rent_val:,}",
                                help="SRX 2024–25 median benchmark for this flat type and town")
                    hrc2.metric("Rent Range",         f"${round(_hdb_rent_val*0.88/100)*100:,} – ${round(_hdb_rent_val*1.12/100)*100:,}",
                                help="±12% for floor, condition and MRT proximity")
                    hrc3.metric("Est. Gross Yield",   f"{_hdb_gross_y:.2f}%" if _hdb_gross_y else "—",
                                help="vs latest median resale price in this town")
                    hrc4.metric("Est. Net Yield",     f"{_hdb_net_y:.2f}%" if _hdb_net_y else "—",
                                help="After ~0.8% p.a. for maintenance and vacancy (HDB lower costs than private)")
                    st.caption(
                        f"HDB rental: MOP (5 years) must be met before renting entire flat. "
                        f"Sub-letting requires HDB approval. Benchmark is SRX median — actual "
                        f"rent varies by floor, renovation, proximity to MRT."
                    )
                    # All flat types for this town for comparison
                    _all_ft_rents = _hdb_rent
                    if len(_all_ft_rents) > 1:
                        import pandas as _hdbrentpd
                        _hdb_rent_rows = []
                        for _ft_r, _rent_r in sorted(_all_ft_rents.items()):
                            _gy_r = round(_rent_r * 12 / _latest_price * 100, 2) if _latest_price else 0
                            _hdb_rent_rows.append({
                                "Flat Type": _ft_r,
                                "Est. Monthly Rent": f"${_rent_r:,}",
                                "Annual Income": f"${_rent_r*12:,}",
                                "Est. Gross Yield": f"{_gy_r:.2f}%" if _gy_r else "—",
                            })
                        st.caption("Rental benchmarks by flat type in this town:")
                        st.dataframe(_hdbrentpd.DataFrame(_hdb_rent_rows), hide_index=True, use_container_width=True)
                else:
                    st.info(f"No rental benchmark available for {_trend_town}.")
            else:
                st.info(f"No transaction records for **{_trend_ft}** in **{_trend_town}**.")

    elif val_type == "🏢 Private Condo/Apt":
        from data.ura_pipeline import get_district_stats
        st.caption("Enter your project name for a property-specific valuation, or just select the district for a benchmark.")

        # ── Input mode: postal code OR project name ──────────────────────────
        _val_priv_mode = st.radio("Search by", ["🏢 Project / Development Name", "📮 Postal Code"],
                                   horizontal=True, key="val_priv_mode")
        priv_project_input = ""

        if _val_priv_mode == "📮 Postal Code":
            _vp_postal = st.text_input("Postal Code (6 digits)", max_chars=6,
                                        placeholder="e.g. 439970", key="val_priv_postal")
            if _vp_postal and len(_vp_postal) == 6 and _vp_postal.isdigit():
                try:
                    _vp_om = _requests_lib.get(
                        "https://www.onemap.gov.sg/api/common/elastic/search"
                        f"?searchVal={_vp_postal}&returnGeom=N&getAddrDetails=Y&pageNum=1",
                        timeout=6
                    ).json()
                    _vp_r = (_vp_om.get("results") or [{}])[0]
                    _vp_bldg = (_vp_r.get("BUILDING","") or "").strip()
                    _vp_road = (_vp_r.get("ROAD_NAME","") or "").strip()
                    _vp_ps   = int(_vp_postal[:2])
                    _VP_DIST = {1:1,2:1,3:1,4:4,5:5,6:6,7:7,8:8,9:9,10:10,11:11,12:12,
                                13:14,14:14,15:15,16:16,17:17,18:18,19:19,20:20,21:21,
                                22:22,23:23,24:24,25:25,26:26,27:27,28:28}
                    _vp_dist_default = _VP_DIST.get(_vp_ps, 15)
                    if _vp_bldg and _vp_bldg.upper() not in ("NIL",""):
                        priv_project_input = _vp_bldg
                        st.success(f"📍 Resolved: **{_vp_bldg}** ({_vp_road}) — will search as project name")
                    elif _vp_road:
                        priv_project_input = _vp_road
                        st.info(f"📍 No development name — searching by road: **{_vp_road}**")
                    else:
                        st.warning("Could not resolve postal code. Switch to Project Name search.")
                except Exception as _vpe:
                    st.warning(f"Postal lookup error: {_vpe}")
                    _vp_dist_default = 15
            else:
                _vp_dist_default = 15
        else:
            priv_project_input = st.text_input(
                "Project / Development Name (optional — leave blank for district benchmark)",
                placeholder="e.g. The Interlace, Parc Clematis, One Holland Village",
                key="val_priv_proj"
            )
            _vp_dist_default = 15

        # ── District + property details (use cached stats — fast) ────────────
        _dist_cache = _cached_districts_with_data()
        districts_with_data = [(d, cnt, psf) for d, cnt, psf, _ in _dist_cache]

        if not districts_with_data:
            st.info(
                "Private transaction data not yet synced.\n\n"
                "Run once on the VPS:\n"
                "```\ncd /root/propos && .venv/bin/python scripts/sync_ura.py\n```"
            )
        else:
            district_options = {f"D{d} — {cnt} txns, median ${psf:,.0f} PSF": d for d, cnt, psf in districts_with_data}
            # Pre-select district from postal code if resolved
            _dist_keys = list(district_options.keys())
            _dist_default_idx = next((i for i,k in enumerate(_dist_keys) if district_options[k] == _vp_dist_default), 0)
            col1, col2, col3 = st.columns(3)
            with col1:
                selected    = st.selectbox("District", _dist_keys, index=_dist_default_idx)
                district    = district_options[selected]
            with col2:
                property_type = st.selectbox("Type", ["Condominium", "Apartment", "Executive Condominium"])
                area_sqft     = st.number_input("Area (sqft)", 300, 5000, 1000, key="priv_area")
            with col3:
                priv_floor  = st.number_input("Floor / Storey", 1, 80, 10, key="priv_floor",
                                              help="Higher floors typically command a 0.3–0.8% PSF premium per floor")
                asking_price = st.number_input("Asking Price (SGD)", 0, 10000000, 0, step=10000, key="priv_ask2")

            if st.button("Value Property", type="primary", key="val_priv"):
                agent = ValuationAgent()
                # Store inputs for the results renderer below
                st.session_state["val_priv_district"]     = district
                st.session_state["val_priv_floor"]        = priv_floor
                st.session_state["val_priv_area"]         = area_sqft
                st.session_state["val_priv_project_name"] = priv_project_input.strip()

                # ── Path A: Project name given → URA transaction lookup ───────
                _used_project = priv_project_input.strip()
                if _used_project:
                    with st.spinner(f"Searching URA transactions for '{_used_project}'..."):
                        try:
                            from agents.price_history import get_project_history as _priv_ph2
                            _proj_hist = _priv_ph2(_used_project, _cached_ura_transactions())
                        except Exception as _ue2:
                            _proj_hist = None
                            st.error(f"URA lookup error: {_ue2}")

                    if _proj_hist and _proj_hist.get("match_count", 0) > 0:
                        st.session_state["val_priv_proj_hist"] = _proj_hist
                        st.session_state["val_priv_result"]    = None
                        st.session_state["val_priv_path"]      = "A"
                    else:
                        st.warning(f"No transactions found for **'{_used_project}'** — using district benchmark.")
                        _used_project = ""

                # ── Path B: District benchmark ────────────────────────────────
                if not _used_project:
                    with st.spinner("Analysing URA transactions..."):
                        _res = agent.value_private_property(district, area_sqft, property_type, asking_price, explain=bool(asking_price))
                    st.session_state["val_priv_result"]    = _res
                    st.session_state["val_priv_proj_hist"] = None
                    st.session_state["val_priv_path"]      = "B"

            # ── Render results from session state (safe — no chart on page load) ──
            _vp_path     = st.session_state.get("val_priv_path")
            _vp_district = st.session_state.get("val_priv_district") or district
            _vp_floor    = st.session_state.get("val_priv_floor")    or priv_floor
            _vp_area     = st.session_state.get("val_priv_area")     or area_sqft
            _vp_projname = st.session_state.get("val_priv_project_name") or ""

            if _vp_path == "A":
                _proj_hist = st.session_state["val_priv_proj_hist"]
                _pq        = _proj_hist.get("quarters", [])
                _latest_q  = _pq[-1] if _pq else {}
                _med_psf   = _proj_hist.get("latest_median_psf", 0)
                _floor_adj = 1 + max(0, _vp_floor - 5) * 0.005
                _adj_psf   = round(_med_psf * _floor_adj)
                _est_val   = round(_adj_psf * _vp_area)

                st.success(f"✅ Found **{_proj_hist['match_count']:,} transactions** for '{_vp_projname}'")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Est. Value",           f"${_est_val:,.0f}",
                          help=f"Latest median PSF × {_vp_area:,} sqft × floor adj")
                c2.metric("Project Median PSF",   f"${_med_psf:,.0f}")
                c3.metric("PSF Range (latest Q)", f"${_latest_q.get('min_psf',0):,}–${_latest_q.get('max_psf',0):,}")
                c4.metric("Floor-adj PSF",        f"${_adj_psf:,.0f}",
                          help=f"Floor {_vp_floor}: +{round((_floor_adj-1)*100,1):.1f}% vs median")
                if asking_price > 0 and _est_val:
                    _ask_psf = round(asking_price / _vp_area)
                    _vs_proj = round((asking_price - _est_val) / _est_val * 100, 1)
                    st.divider()
                    va, vb, vc = st.columns(3)
                    va.metric("Asking PSF",        f"${_ask_psf:,.0f}")
                    vb.metric("Asking vs Project", f"{_vs_proj:+.1f}%",
                              delta="Above market" if _vs_proj>5 else ("Fair" if abs(_vs_proj)<=5 else "Below market"))
                    vc.metric("Deal Score",        f"{max(0,min(100,round(50-_vs_proj*2)))}/100",
                              help="100 = deeply below market")
                if _pq and _med_psf > 0:
                    import pandas as _pvpd
                    st.divider()
                    st.subheader(f"📈 PSF Trend — {_vp_projname.title()}")
                    _pvdf = _pvpd.DataFrame(_pq).set_index("quarter")
                    if not _pvdf.empty and _pvdf["median_psf"].max() > 0:
                        st.line_chart(_pvdf["median_psf"], height=240)
                    st.dataframe(_pvdf[["median_psf","min_psf","max_psf","count","median_price"]].rename(columns={
                        "median_psf":"Median PSF","min_psf":"Min PSF","max_psf":"Max PSF",
                        "count":"# Txns","median_price":"Median Price (SGD)"
                    }), use_container_width=True)
                    if len(_pq) >= 2:
                        st.caption(f"Change: **{_proj_hist['psf_change_pct']:+.1f}%** from {_pq[0]['quarter']} to {_pq[-1]['quarter']}.")
                _show_rental_intel(_vp_district, round(_adj_psf * _vp_area) if _adj_psf else 0, area_sqft=_vp_area)

            elif _vp_path == "B":
                result = st.session_state["val_priv_result"] or {}
                if result.get("status") == "ok":
                    _floor_adj2  = 1 + max(0, _vp_floor - 5) * 0.005
                    _adj_med_psf = round(result["median_psf"] * _floor_adj2)
                    _adj_est_val = round(_adj_med_psf * _vp_area)
                    st.info(f"📊 **District {_vp_district}** benchmark — enter a project name for property-specific valuation")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Est. Value (floor adj)", f"${_adj_est_val:,.0f}")
                    c2.metric("District Median PSF",    f"${result['median_psf']:,.0f}")
                    c3.metric("Floor-adj PSF",          f"${_adj_med_psf:,.0f}")
                    c4.metric("PSF Range (P25–P75)",    f"${result['p25_psf']:,.0f}–${result['p75_psf']:,.0f}")
                    if asking_price > 0:
                        st.metric("Asking vs District Median", f"{result.get('vs_median_pct',0):+.1f}%",
                                  delta=result.get("verdict",""))
                    if result.get("explanation"):
                        st.write("**AI Analysis:**", result["explanation"])
                    _show_rental_intel(_vp_district, _adj_est_val, area_sqft=_vp_area)
                    st.divider()
                    if st.button("📄 Download Valuation Report (PDF)", key="pdf_priv"):
                        try:
                            from agents.pdf_report import generate_valuation_report
                            pdf_bytes = generate_valuation_report(
                                property_address=f"District {_vp_district}",
                                property_type=property_type,
                                area_sqft=_vp_area,
                                estimated_value=result.get("estimated_value_sgd", 0),
                                median_price=result.get("median_psf", 0) * _vp_area,
                                transactions_used=result.get("transactions_used", 0),
                                asking_price=asking_price,
                                vs_median_pct=result.get("vs_median_pct", 0),
                                verdict=result.get("verdict", ""),
                                ai_analysis=result.get("explanation", ""),
                                district=_vp_district,
                            )
                            st.download_button("💾 Save PDF", pdf_bytes,
                                file_name=f"PropOS_Valuation_D{_vp_district}_{date.today()}.pdf",
                                mime="application/pdf", key="dl_pdf_priv")
                        except ImportError:
                            st.warning("PDF export requires `fpdf2`.")
                        except Exception as _pe:
                            st.error(f"PDF error: {_pe}")
                else:
                    st.warning(result.get("message", "Insufficient data for this district."))

    else:  # Heatmap
        heatmap_type = st.radio("Heatmap type", ["🏠 HDB — All Towns", "🏢 Private — All Districts"], horizontal=True)

        # Clear heatmap chart state when leaving heatmap tab entirely
        if val_type != "📊 Market Heatmap":
            st.session_state.pop("val_heatmap_loaded", None)

        if heatmap_type == "🏢 Private — All Districts":
            st.subheader("🗺️ Private Property Intelligence — All Districts")
            from data.ura_pipeline import get_district_stats
            import pandas as pd
            # District name map
            _DIST_NAMES = {
                1:"Boat Quay/Raffles Place",2:"Chinatown/Tanjong Pagar",3:"Alexandra/Commonwealth",
                4:"Harbourfront/Telok Blangah",5:"Buona Vista/West Coast",6:"City Hall/Clarke Quay",
                7:"Middle Road/Golden Mile",8:"Farrer Park/Serangoon Rd",9:"Orchard/River Valley",
                10:"Tanglin/Holland/Bukit Timah",11:"Newton/Novena",12:"Balestier/Toa Payoh",
                13:"Macpherson/Braddell",14:"Geylang/Eunos",15:"Katong/Joo Chiat/Marine Parade",
                16:"Bedok/Upper East Coast",17:"Loyang/Changi",18:"Tampines/Pasir Ris",
                19:"Serangoon/Hougang",20:"Ang Mo Kio/Bishan",21:"Clementi/Upper Bukit Timah",
                22:"Jurong",23:"Hillview/Bukit Batok",24:"Lim Chu Kang/Tengah",
                25:"Admiralty/Woodlands",26:"Mandai/Upper Thomson",27:"Sembawang/Yishun",
                28:"Seletar/Punggol",
            }
            # Gross yield benchmarks by district
            _D_YIELD = {1:3.0,2:3.2,3:3.1,4:3.3,5:3.0,6:2.8,7:3.2,8:3.3,
                        9:2.9,10:2.8,11:2.9,12:3.3,13:3.4,14:3.4,15:3.3,16:3.2,
                        17:3.5,18:3.5,19:3.4,20:3.2,21:3.1,22:3.5,23:3.3,
                        24:3.3,25:3.4,26:3.3,27:3.3,28:3.4}

            hm_priv_data = []
            for d, cnt, med_psf, s in _cached_districts_with_data():
                yield_b = _D_YIELD.get(d, 3.2)
                est_rent = round(med_psf * 1000 * yield_b / 12 / 100, -1) if med_psf > 0 else 0
                hm_priv_data.append({
                    "District": f"D{d}",
                    "Name": _DIST_NAMES.get(d, ""),
                    "Median PSF": med_psf,
                    "P25 PSF": s.get("p25_psf", 0),
                    "P75 PSF": s.get("p75_psf", 0),
                    "Transactions": cnt,
                    "Est Rent 1000sqft": int(est_rent),
                    "Gross Yield %": yield_b,
                    "Net Yield %": round(yield_b - 1.5, 1),
                })

            if not hm_priv_data:
                st.info("No private transaction data cached yet. Run `sync_ura.py` on the VPS.")
                st.session_state["val_heatmap_loaded"] = False
            else:
                st.session_state["val_heatmap_loaded"] = True
                df_priv = pd.DataFrame(hm_priv_data)
                ph_tab1, ph_tab2, ph_tab3 = st.tabs(["💰 PSF by District", "📈 Yield & Rent", "📊 Full Table"])
                with ph_tab1:
                    st.caption("Median PSF across all private residential transactions. Sorted highest to lowest.")
                    _psf_col = df_priv.set_index("District")["Median PSF"]
                    if st.session_state.get("val_heatmap_loaded") and _psf_col.max() > 0:
                        st.bar_chart(_psf_col)
                    else:
                        st.info("PSF data not yet loaded — run `sync_ura.py` on the VPS to sync transactions.")
                    st.caption("Higher PSF = more expensive district. CCR (D1–D11) typically commands premium over OCR (D17–D28).")
                with ph_tab2:
                    pc1, pc2 = st.columns(2)
                    with pc1:
                        st.subheader("Est. Monthly Rent — 1,000 sqft unit")
                        _rent_col = df_priv.set_index("District")["Est Rent 1000sqft"]
                        if _rent_col.max() > 0:
                            st.bar_chart(_rent_col)
                        else:
                            st.info("No rental data — PSF sync required.")
                        st.caption("Estimate: median PSF × 1,000 sqft × gross yield ÷ 12")
                    with pc2:
                        st.subheader("Gross Rental Yield (%)")
                        _yield_col = df_priv.set_index("District")["Gross Yield %"]
                        if _yield_col.max() > 0:
                            st.bar_chart(_yield_col)
                        st.caption("OCR districts (D17–D28) typically yield more than prime CCR.")
                with ph_tab3:
                    st.dataframe(
                        df_priv[["District","Name","Median PSF","P25 PSF","P75 PSF","Transactions","Est Rent 1000sqft","Gross Yield %","Net Yield %"]],
                        hide_index=True, use_container_width=True
                    )
                    st.caption("Net yield estimated after ~1.5% annual holding costs (maintenance, vacancy, property tax). Not financial advice.")

        if heatmap_type == "🏠 HDB — All Towns":
            st.subheader("🗺️ HDB Market Intelligence — All Towns")
        else:
            st.stop()  # Private mode ends here — prevents HDB controls below from rendering
        from data.hdb_pipeline import get_town_stats
        from collections import defaultdict, Counter
        import pandas as pd

        _HM_RENT = {
            "ANG MO KIO": 2800, "BEDOK": 2700, "BISHAN": 3000, "BUKIT BATOK": 2600,
            "BUKIT MERAH": 3200, "BUKIT PANJANG": 2500, "BUKIT TIMAH": 3100,
            "CENTRAL AREA": 4200, "CHOA CHU KANG": 2500, "CLEMENTI": 2900,
            "GEYLANG": 2800, "HOUGANG": 2600, "JURONG EAST": 2700,
            "JURONG WEST": 2600, "KALLANG/WHAMPOA": 3100, "MARINE PARADE": 3200,
            "PASIR RIS": 2600, "PUNGGOL": 2600, "QUEENSTOWN": 3400,
            "SEMBAWANG": 2400, "SENGKANG": 2600, "SERANGOON": 2900,
            "TAMPINES": 2700, "TOA PAYOH": 3000, "WOODLANDS": 2400, "YISHUN": 2500,
        }

        # Global controls
        hm_flat = st.selectbox("Flat Type", ["4 ROOM", "3 ROOM", "5 ROOM", "EXECUTIVE"], key="hm_flat")
        # Adjust rent map for flat type
        _RENT_SCALE = {"3 ROOM": 0.82, "4 ROOM": 1.0, "5 ROOM": 1.16, "EXECUTIVE": 1.27}
        _scale = _RENT_SCALE.get(hm_flat, 1.0)
        _adj_rent = {t: round(r * _scale / 100) * 100 for t, r in _HM_RENT.items()}

        records = _cached_hdb_records()
        all_months = sorted(set(r['month'] for r in records))

        # Time window control
        _window_opts = {"Last 3 months": 3, "Last 6 months": 6, "Last 12 months": 12, "All data": len(all_months)}
        _window_label = st.select_slider("Time window", options=list(_window_opts.keys()), value="Last 12 months", key="hm_window")
        _n_months = _window_opts[_window_label]
        _months_in_window = all_months[-_n_months:]
        records_windowed = [r for r in records if r.get("month", "") in set(_months_in_window)]

        towns = sorted(set(r['town'] for r in records_windowed))

        # Build snapshot stats from the windowed records (so time control affects all tabs)
        _win_by_town: dict = defaultdict(list)
        for r in records_windowed:
            if hm_flat.lower() in r.get("flat_type", "").lower() and r.get("resale_price", 0) > 0 and r.get("floor_area_sqft", 0) > 0:
                _win_by_town[r["town"]].append(r)

        town_data = []
        for t, recs in _win_by_town.items():
            if len(recs) < 3:
                continue
            prices = sorted(r["resale_price"] for r in recs)
            psfs = sorted(r["psf_sgd"] for r in recs if r.get("psf_sgd", 0) > 0)
            if not psfs:
                continue
            n = len(prices)
            median_price = prices[n // 2]
            median_psf = psfs[len(psfs) // 2]
            rent = _adj_rent.get(t, 0)
            gross_yield = round(rent * 12 / median_price * 100, 2) if rent and median_price else 0
            net_yield = round(gross_yield - 1.2, 2) if gross_yield else 0
            town_data.append({
                "Town": t, "Median PSF": median_psf, "Median Price": median_price,
                "Est Monthly Rent": rent, "Gross Yield %": gross_yield,
                "Net Yield %": net_yield, "Txns": len(recs),
            })

        hm_tab1, hm_tab2, hm_tab3, hm_tab4, hm_tab5 = st.tabs([
            "💰 Price PSF", "📈 Rental Yield & Rent",
            "🌡️ Heatmap Over Time", "📊 Full Table", "🔁 Volume Trend"
        ])

        if not town_data:
            st.warning("No data for this flat type / window. Try '4 ROOM' with 'All data'.")
        else:
            df = pd.DataFrame(town_data).sort_values("Median PSF", ascending=False)

            with hm_tab1:
                st.caption(f"{hm_flat} — {_window_label}. Sorted highest to lowest PSF.")
                _hm_psf_col = df.set_index("Town")["Median PSF"]
                if not _hm_psf_col.empty and _hm_psf_col.max() > 0:
                    st.bar_chart(_hm_psf_col)
                else:
                    st.info("No PSF data for this filter. Try 'All data' or '4 ROOM'.")

            with hm_tab2:
                yield_df = df.sort_values("Gross Yield %", ascending=False)
                rc1, rc2 = st.columns(2)
                with rc1:
                    st.subheader("Est. Monthly Rent (SGD)")
                    _hm_rent_col = yield_df.set_index("Town")["Est Monthly Rent"]
                    if not _hm_rent_col.empty and _hm_rent_col.max() > 0:
                        st.bar_chart(_hm_rent_col)
                    else:
                        st.info("No rental data for this filter.")
                    st.caption(f"Scaled from 4-room SRX benchmarks × {_scale:.2f} for {hm_flat}.")
                with rc2:
                    st.subheader("Gross Rental Yield (%)")
                    _hm_yield_col = yield_df.set_index("Town")["Gross Yield %"]
                    if not _hm_yield_col.empty and _hm_yield_col.max() > 0:
                        st.bar_chart(_hm_yield_col)
                    st.caption("Higher = better yield. Affordable towns typically yield more.")
                st.divider()
                st.write(f"**Top 5 yield towns ({hm_flat}):**")
                for _, row in yield_df.head(5).iterrows():
                    st.write(
                        f"**{row['Town']}** — "
                        f"Rent ~SGD {row['Est Monthly Rent']:,}/mo, "
                        f"Gross yield {row['Gross Yield %']}%, "
                        f"Net {row['Net Yield %']}%, "
                        f"Median price SGD {row['Median Price']:,.0f}"
                    )
                st.write(f"**Bottom 5 yield towns ({hm_flat}):**")
                for _, row in yield_df.tail(5).iterrows():
                    st.write(
                        f"**{row['Town']}** — "
                        f"Rent ~SGD {row['Est Monthly Rent']:,}/mo, "
                        f"Gross yield {row['Gross Yield %']}%, "
                        f"Net {row['Net Yield %']}%, "
                        f"Median price SGD {row['Median Price']:,.0f}"
                    )

            with hm_tab3:
                st.caption("Each row = town. Each column = month. Colour = median PSF or implied yield — darker green = higher value. Use time window above to zoom in.")
                hm_metric = st.radio("Show", ["Median PSF", "Implied Gross Yield %"], horizontal=True, key="hm_metric")

                # Build town × month pivot
                monthly_town: dict = defaultdict(lambda: defaultdict(list))
                for r in records:
                    if r.get("month") in set(_months_in_window) and hm_flat.lower() in r.get("flat_type", "").lower() and r.get("resale_price", 0) > 0:
                        monthly_town[r["town"]][r["month"]].append(r["resale_price"])

                pivot_rows = {}
                for t, months_dict in monthly_town.items():
                    row = {}
                    for m in _months_in_window:
                        prices = months_dict.get(m, [])
                        if prices:
                            med_p = sorted(prices)[len(prices) // 2]
                            if hm_metric == "Median PSF":
                                # Need area — approximate from town stats
                                area_recs = [r for r in records if r["town"] == t and hm_flat.lower() in r.get("flat_type","").lower() and r.get("floor_area_sqft", 0) > 0]
                                avg_area = sum(r["floor_area_sqft"] for r in area_recs) / len(area_recs) if area_recs else 1000
                                row[m] = round(med_p / avg_area, 0)
                            else:
                                rent = _adj_rent.get(t, 0)
                                row[m] = round(rent * 12 / med_p * 100, 2) if rent and med_p else None
                        else:
                            row[m] = None
                    if any(v is not None for v in row.values()):
                        pivot_rows[t] = row

                if pivot_rows:
                    pivot_df = pd.DataFrame(pivot_rows).T
                    pivot_df = pivot_df[[c for c in _months_in_window if c in pivot_df.columns]]
                    pivot_df = pivot_df.dropna(how="all").sort_index().astype(float)
                    _pivot_cmap = "YlOrRd" if hm_metric == "Median PSF" else "YlGn"
                    _pivot_fmt_str = "${:,.0f}" if hm_metric == "Median PSF" else "{:.2f}%"
                    # Use pure-Python gradient (no matplotlib dependency)
                    _pivot_col_cmaps = {c: _pivot_cmap for c in pivot_df.columns}
                    _pivot_col_fmt = {c: _pivot_fmt_str for c in pivot_df.columns}
                    st.write(_gradient_html(pivot_df, _pivot_col_cmaps, _pivot_col_fmt), unsafe_allow_html=True)
                    legend = "🟡 Yellow = low → 🔴 Red = high PSF" if hm_metric == "Median PSF" else "🟡 Yellow = low → 🟢 Green = high yield"
                    st.caption(f"{legend}. Blank = no transactions that month.")
                else:
                    st.info("Not enough data in this time window. Try 'All data'.")

            with hm_tab4:
                st.subheader(f"All Towns — {hm_flat} Snapshot ({_window_label})")
                st.caption("🔴 Red PSF = expensive. 🟢 Green yield = high rental return. Click column headers to re-sort.")
                num_df = df[["Town", "Median PSF", "Median Price", "Est Monthly Rent", "Gross Yield %", "Net Yield %", "Txns"]].set_index("Town")
                _tbl_cmaps = {
                    "Median PSF": "RdYlGn_r", "Median Price": "RdYlGn_r",
                    "Gross Yield %": "RdYlGn", "Net Yield %": "RdYlGn",
                    "Est Monthly Rent": "Blues",
                }
                _tbl_fmt = {
                    "Median PSF": "${:,.0f}", "Median Price": "${:,.0f}",
                    "Est Monthly Rent": "${:,}", "Gross Yield %": "{:.2f}%",
                    "Net Yield %": "{:.2f}%", "Txns": "{:.0f}",
                }
                st.write(_gradient_html(num_df, _tbl_cmaps, _tbl_fmt), unsafe_allow_html=True)
                st.caption("PSF/Price: 🔴 red = expensive, 🟢 green = affordable. Yield: 🟢 green = high return. Net yield = gross − 1.2%.")

            with hm_tab5:
                st.subheader("Transaction Volume")
                # Overall volume trend
                month_counts = Counter(r['month'] for r in records)
                months_all = sorted(month_counts.keys())
                vol_df = pd.DataFrame({"All Towns": [month_counts[m] for m in months_all]}, index=months_all)
                st.line_chart(vol_df)
                st.caption("Total monthly HDB resale transactions. Dips around Jan–Feb = Chinese New Year.")

                st.divider()
                # Top/bottom towns by volume in selected window
                town_vol = Counter(r['town'] for r in records_windowed)
                if town_vol:
                    vol_towns = sorted(town_vol.items(), key=lambda x: x[1], reverse=True)
                    t5c, b5c = st.columns(2)
                    with t5c:
                        st.write(f"**Top 5 towns by volume ({_window_label})**")
                        for t, cnt in vol_towns[:5]:
                            st.write(f"• **{t}** — {cnt:,} txns")
                    with b5c:
                        st.write(f"**Bottom 5 towns by volume ({_window_label})**")
                        for t, cnt in vol_towns[-5:]:
                            st.write(f"• **{t}** — {cnt:,} txns")

                    st.divider()
                    st.subheader("Volume by Town (selected window)")
                    town_vol_df = pd.DataFrame(
                        {"Transactions": [v for _, v in vol_towns]},
                        index=[t for t, _ in vol_towns]
                    )
                    st.bar_chart(town_vol_df)

# ── News Intel ────────────────────────────────────────────────────────────────
elif tab_select == "📰 News Intel":
    st.header("📰 Market Intelligence")
    from data.news_pipeline import get_sector_breakdown, get_trending_topics
    from data.market_indicators import get_all_indicators, sg_property_macro_summary
    import pandas as pd

    # Refresh button — re-syncs RSS feeds and rebuilds sectors
    _sync_col, _info_col = st.columns([1, 4])
    with _sync_col:
        if st.button("🔄 Refresh News", key="news_sync"):
            from data.news_pipeline import sync_news
            with st.spinner("Fetching RSS feeds..."):
                _synced = sync_news()
            st.success(f"Synced {len(_synced)} articles")
            st.rerun()
    with _info_col:
        st.caption("News syncs automatically every hour via cron. Click Refresh to fetch latest now.")

    sentiment = get_sentiment_index()
    score = sentiment.get("score", 0)
    score_color = "🟢" if score > 0.1 else "🔴" if score < -0.1 else "⚪"

    # Top-level sentiment bar
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric(f"{score_color} Overall Sentiment", sentiment.get("label", "Neutral"), f"{score:+.3f}")
    sc2.metric("Articles Tracked", sentiment.get("article_count", 0))
    sc3.metric("Policy Alerts", sentiment.get("policy_alerts", 0))
    sc4.metric("Opportunity Signals", sentiment.get("opportunity_alerts", 0))

    ni_tab1, ni_tab2, ni_tab3, ni_tab4, ni_tab5 = st.tabs([
        "📊 Sector Breakdown", "📈 Trending", "⚠️ Policy Alerts", "💡 Opportunities", "🌐 Macro Indicators"
    ])

    with ni_tab1:
        st.subheader("Sentiment by Property Sector")
        st.caption("Score: +1.0 = very bullish, -1.0 = very bearish. Based on keyword analysis of recent articles.")
        with st.spinner("Analysing sectors..."):
            breakdown = get_sector_breakdown()

        _sector_icons = {"HDB": "🏘️", "Private Condo": "🏢", "Landed": "🏡", "Commercial": "🏪", "Rental": "🔑", "Policy": "📋"}
        for sector, data in breakdown.items():
            if data["count"] == 0:
                continue
            icon = _sector_icons.get(sector, "📰")
            sent_color = "🟢" if data["sentiment"] > 0.1 else ("🔴" if data["sentiment"] < -0.1 else "⚪")
            with st.expander(f"{icon} **{sector}** — {sent_color} {data['label']} ({data['sentiment']:+.3f}) | {data['count']} articles"):
                for art in data["top_articles"]:
                    art_sign = "🟢" if art["sentiment_score"] > 0.1 else ("🔴" if art["sentiment_score"] < -0.1 else "⚪")
                    st.write(f"{art_sign} [{art['title']}]({art['link']}) *({art['pub_date'][:16]})*")
                    if art.get("description"):
                        st.caption(art["description"])

    with ni_tab2:
        st.subheader("Market Pulse")
        with st.spinner("Loading trends..."):
            trends = get_trending_topics()

        # Sector activity bar — more useful than raw keyword dump
        from data.news_pipeline import get_sector_breakdown as _get_bd
        _bd = get_sector_breakdown() if "breakdown" not in dir() else breakdown
        _active = {s: d for s, d in _bd.items() if d["count"] > 0}
        if _active:
            import pandas as pd
            _bd_df = pd.DataFrame([
                {"Sector": s, "Articles": d["count"], "Sentiment": d["sentiment"]}
                for s, d in sorted(_active.items(), key=lambda x: x[1]["count"], reverse=True)
            ]).set_index("Sector")
            pulse_c1, pulse_c2 = st.columns(2)
            with pulse_c1:
                st.caption("Article volume by sector (last sync)")
                st.bar_chart(_bd_df["Articles"])
            with pulse_c2:
                st.caption("Sentiment by sector (+1=bullish, −1=bearish)")
                st.bar_chart(_bd_df["Sentiment"])

        st.divider()
        up_col, down_col = st.columns(2)
        with up_col:
            st.write("**📈 Bullish Headlines**")
            if trends["trending_up"]:
                for art in trends["trending_up"]:
                    sectors_str = ", ".join(art.get("sectors", [])) or "General"
                    st.markdown(f"🟢 **[{art['title']}]({art['link']})**")
                    st.caption(f"{sectors_str} — sentiment score {art['score']:+.2f}")
            else:
                st.caption("No strongly bullish headlines in current cache.")
        with down_col:
            st.write("**📉 Bearish Headlines**")
            if trends["trending_down"]:
                for art in trends["trending_down"]:
                    sectors_str = ", ".join(art.get("sectors", [])) or "General"
                    st.markdown(f"🔴 **[{art['title']}]({art['link']})**")
                    st.caption(f"{sectors_str} — sentiment score {art['score']:+.2f}")
            else:
                st.caption("No strongly bearish headlines in current cache.")

        st.divider()
        st.caption(f"Most-mentioned terms: " + ", ".join(f"**{kw}** ×{cnt}" for kw, cnt in trends["hot_keywords"][:6]))
        if st.button("📝 Get AI Daily Briefing", key="ni_briefing"):
            agent = NewsIntelAgent()
            with st.spinner("Generating briefing (uses LLM)..."):
                briefing = agent.get_market_briefing()
            if briefing.get("narrative"):
                st.info(briefing["narrative"])

    with ni_tab3:
        st.subheader("⚠️ Policy Alerts")
        st.caption("Articles mentioning government policy, MAS, URA, ABSD, cooling measures, stamp duties.")
        with st.spinner("Loading..."):
            trends = get_trending_topics() if "trends" not in dir() else trends
            policy_arts = trends.get("policy_articles", [])

        if not policy_arts:
            st.info("No policy articles in current cache. Run a news sync to refresh.")
        else:
            for art in policy_arts:
                with st.expander(f"📋 {art['title']} *({art['pub_date'][:16]})*"):
                    if art.get("description"):
                        st.write(art["description"])
                    st.write(f"[Read full article →]({art['link']})")
                    if st.button(f"🤖 AI deep dive", key=f"policy_{hash(art['title']) % 99999}"):
                        agent = NewsIntelAgent()
                        with st.spinner("Generating policy analysis..."):
                            prompt = f"""Analyse this Singapore property policy news for a property investor.
Title: {art['title']}
Summary: {art.get('description', '')}

Provide:
1. What policy change is being discussed (2 sentences)
2. Impact on HDB resale buyers (1 sentence)
3. Impact on private condo buyers (1 sentence)
4. Impact on property investors / landlords (1 sentence)
5. Prediction: likely market reaction over next 3-6 months (2 sentences)

Be specific, use numbers where possible. Plain text, no markdown."""
                            resp = agent._llm(prompt, max_tokens=300, use_cache=True)
                        st.info(resp.content.strip())

    with ni_tab4:
        st.subheader("💡 Opportunity Signals")

        with st.expander("ℹ️ How this works — what qualifies as an opportunity signal?"):
            st.write("""
**Opportunity signals** are news articles that mention keywords associated with motivated sellers or below-market purchases:

- **Mortgagee sale / foreclosure** — bank seizes and sells a property after loan default. Typical discount: 10–20% below market. Risk: sold as-is, may have outstanding charges.
- **Auction sale** — owner or mortgagee lists at public auction. Buyers can bid below asking. Discount range: 5–15%.
- **Distressed sale / urgent sale** — owner needs quick exit (divorce, emigration, financial difficulty). Often 5–12% below market if you move fast.
- **Price cut / reduced** — active listing with a recorded price reduction. Signals overpriced stock or motivated seller.
- **Fire sale / below valuation** — explicit under-market listing. Least common but highest discount potential (15–25%).

**How to use this:**
1. Click any signal to read the article context
2. Use "Analyse opportunity" for AI breakdown of risk/reward
3. Cross-reference with the Deal Feed (HDB scanner) for actual transaction data
4. Act quickly — distressed listings are typically snapped up in 1–2 weeks

**Limitations:** This is news-based detection, not live listing data. For actual listings, check PropertyGuru/99.co directly.
""")

        with st.spinner("Loading..."):
            opp_arts = trends.get("opportunity_articles", []) if "trends" in dir() else get_trending_topics().get("opportunity_articles", [])

        if opp_arts:
            # Filter controls
            _opp_types = ["All types", "Auction", "Mortgagee", "Price cut", "Distressed", "Fire sale"]
            _opp_sources = ["All sources"] + sorted(set(a.get("source", "unknown") for a in opp_arts))
            fc1, fc2 = st.columns(2)
            _opp_type_filter = fc1.selectbox("Filter by type", _opp_types, key="opp_type")
            _opp_src_filter = fc2.selectbox("Filter by source", _opp_sources, key="opp_src")

            _type_kws = {
                "Auction": ["auction"], "Mortgagee": ["mortgagee"],
                "Price cut": ["price cut", "reduced"], "Distressed": ["distressed", "urgent"],
                "Fire sale": ["fire sale", "below valuation"],
            }
            _filtered_opp = opp_arts
            if _opp_type_filter != "All types":
                _kws = _type_kws.get(_opp_type_filter, [])
                _filtered_opp = [a for a in opp_arts if any(kw in (a.get("title","") + a.get("description","")).lower() for kw in _kws)]
            if _opp_src_filter != "All sources":
                _filtered_opp = [a for a in _filtered_opp if a.get("source") == _opp_src_filter]

        if not opp_arts:
            st.info("No opportunity signals detected in current cache. This is actually a good sign — it means the market is in normal conditions with few distressed sellers. Refresh news or check back during market stress periods.")
        elif not _filtered_opp:
            st.warning(f"No results for filter: {_opp_type_filter} / {_opp_src_filter}. Try 'All types'.")
        else:
            st.success(f"**{len(_filtered_opp)} opportunity signals** ({_opp_type_filter}, {_opp_src_filter})")
            for art in _filtered_opp:
                with st.expander(f"💡 {art['title']} — *{art.get('pub_date','')[:16]}*"):
                    if art.get("description"):
                        st.write(art["description"])
                    st.write(f"[Read full article →]({art['link']})")
                    if st.button("🤖 Analyse opportunity", key=f"opp_{hash(art['title']) % 99999}"):
                        agent = NewsIntelAgent()
                        with st.spinner("Analysing..."):
                            prompt = f"""Analyse this Singapore property opportunity for an investor.
Title: {art['title']}
Summary: {art.get('description', '')}

Provide:
1. What type of opportunity (mortgagee sale, auction, price cut, distressed, etc.)
2. Typical discount range for this scenario in Singapore (e.g. 10-20% below market)
3. Key risks (legal encumbrances, hidden costs, timeline)
4. Action steps for a buyer (3 specific steps)

Be direct. Singapore context. Plain text."""
                            resp = agent._llm(prompt, max_tokens=250, use_cache=True)
                        st.info(resp.content.strip())

    with ni_tab5:
        st.subheader("🌐 Macro Market Indicators")
        st.caption("Live data from Yahoo Finance (cached 4 hours). Shows global factors influencing Singapore property.")
        with st.spinner("Fetching market data..."):
            indicators = get_all_indicators()
            macro_summary = sg_property_macro_summary(indicators)

        # Macro signal header
        macro_color = "🟢" if "Bullish" in macro_summary["signal"] else ("🔴" if "Bearish" in macro_summary["signal"] else "⚪")
        st.info(f"**{macro_color} {macro_summary['signal']}** for Singapore property\n\n{macro_summary['sg_property_impact']}")

        # Individual indicators
        ind_cols = st.columns(len(indicators))
        for col, (key, ind) in zip(ind_cols, indicators.items()):
            if "error" in ind:
                col.metric(ind["label"], "—", "fetch failed")
            else:
                delta_str = f"{ind['change_1d_pct']:+.2f}% today" if ind.get("change_1d_pct") is not None else None
                col.metric(ind["label"], f"{ind['current']:,.4g} {ind['unit']}", delta_str)

        st.divider()
        # Bullish/bearish breakdown
        b_col, r_col = st.columns(2)
        with b_col:
            st.write("**🟢 Bullish macro factors:**")
            for f in macro_summary["bullish_factors"]:
                st.write(f"• {f}")
            if not macro_summary["bullish_factors"]:
                st.write("• None at current levels")
        with r_col:
            st.write("**🔴 Bearish macro factors:**")
            for f in macro_summary["bearish_factors"]:
                st.write(f"• {f}")
            if not macro_summary["bearish_factors"]:
                st.write("• None at current levels")
        if macro_summary["neutral_factors"]:
            st.write("**⚪ Neutral:**")
            for f in macro_summary["neutral_factors"]:
                st.write(f"• {f}")

        st.divider()
        st.caption(
            "**How to read this:** VIX measures global fear — above 25 signals risk-off and buyers pause big purchases. "
            "US 10Y Treasury drives global mortgage rates; Singapore's SORA roughly tracks Fed Funds with a 6-month lag. "
            "SGD strength affects foreign buyer appetite. STI reflects local equity wealth effect on property demand."
        )

# ── Insurance ─────────────────────────────────────────────────────────────────
elif tab_select == "🛡️ Insurance":
    import sqlite3
    import hashlib

    st.header("🛡️ Insurance Portfolio Analyser")
    st.caption("Save your property portfolio for personalised gap analysis. For referral purposes only — not financial advice.")

    # ── SQLite profile storage ─────────────────────────────────────────────────
    DB_PATH = ROOT / "propos.db"
    def _ins_db():
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""CREATE TABLE IF NOT EXISTS insurance_profiles (
            id TEXT PRIMARY KEY,
            name TEXT, email TEXT, telegram_id TEXT,
            properties_json TEXT, created_at TEXT, updated_at TEXT
        )""")
        conn.commit()
        return conn

    ins_tab1, ins_tab2 = st.tabs(["📋 My Portfolio", "📊 Saved Profiles"])

    with ins_tab1:
        st.subheader("Your Profile")
        pc1, pc2, pc3 = st.columns(3)
        user_name = pc1.text_input("Your Name", placeholder="e.g. John Tan", key="ins_name")
        user_email = pc2.text_input("Email (for report)", placeholder="john@email.com", key="ins_email")
        user_tg = pc3.text_input("Telegram @username (optional)", placeholder="@johnt", key="ins_tg")

        st.subheader("Your Properties")
        n_props = st.number_input("Number of properties", 1, 5, 1, key="ins_nprops")
        properties = []
        for i in range(n_props):
            with st.expander(f"Property {i+1}", expanded=(i==0)):
                c1, c2, c3 = st.columns(3)
                name = c1.text_input("Address / Name", f"Property {i+1}", key=f"ins_name_{i}")
                value = c2.number_input("Est. Value (SGD)", 300000, 10000000, 1000000, step=50000, key=f"ins_val_{i}")
                prop_type = c3.selectbox("Type", ["hdb", "condo", "landed", "commercial"], key=f"ins_type_{i}")

                c4, c5 = st.columns(2)
                has_mortgage = c4.checkbox("Has Mortgage?", key=f"ins_mort_{i}")
                outstanding_loan = c4.number_input("Outstanding Loan (SGD)", 0, 5000000, 0, step=10000, key=f"ins_loan_{i}") if has_mortgage else 0
                monthly_repayment = c5.number_input("Monthly Repayment (SGD)", 0, 20000, 0, step=100, key=f"ins_repay_{i}") if has_mortgage else 0
                loan_tenure_left = c5.number_input("Loan Tenure Remaining (years)", 0, 35, 20, key=f"ins_tenure_{i}") if has_mortgage else 0

                c6, c7, c8, c9 = st.columns(4)
                has_fire = c6.checkbox("Fire Insurance?", value=True, key=f"ins_fire_{i}")
                has_contents = c7.checkbox("Contents Insured?", key=f"ins_cont_{i}")
                is_rented = c8.checkbox("Rented Out?", key=f"ins_rent_{i}")
                has_mrta = c9.checkbox("Mortgage Protection?", help="MRTA/MLTA — covers your loan if you pass away or become critically ill", key=f"ins_mrta_{i}") if has_mortgage else False

                mrta_coverage = 0
                if has_mrta and has_mortgage:
                    mrta_coverage = st.number_input("Mortgage Protection Coverage (SGD)", 0, 5000000, outstanding_loan, step=10000, key=f"ins_mrta_cov_{i}")

                properties.append({
                    "name": name, "value_sgd": value, "type": prop_type,
                    "has_fire_insurance": has_fire, "has_contents_insurance": has_contents,
                    "is_rented_out": is_rented, "has_mortgage": has_mortgage,
                    "has_mortgage_insurance": has_mrta, "outstanding_loan": outstanding_loan,
                    "monthly_repayment": monthly_repayment, "loan_tenure_left": loan_tenure_left,
                    "mrta_coverage": mrta_coverage,
                })

        acol1, acol2, acol3 = st.columns(3)
        run_analysis = acol1.button("🔍 Analyse Gaps", type="primary", key="ins_analyse")
        save_profile = acol2.button("💾 Save Profile", key="ins_save")
        send_report = acol3.button("📧 Email Report", key="ins_email_btn")

        if save_profile:
            if not user_name or not user_email:
                st.warning("Enter your name and email to save a profile.")
            else:
                import json as _json
                from datetime import datetime as _dt
                conn = _ins_db()
                pid = hashlib.md5(user_email.lower().encode()).hexdigest()[:12]
                now = _dt.now().isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO insurance_profiles VALUES (?,?,?,?,?,?,?)",
                    (pid, user_name, user_email, user_tg, _json.dumps(properties), now, now)
                )
                conn.commit()
                conn.close()
                st.success(f"✅ Profile saved for **{user_name}** ({user_email}). ID: `{pid}`")

        if run_analysis or send_report:
            agent = InsuranceAgent()
            result = agent.analyse_portfolio_gaps({"properties": properties})
            gaps = result.get("gaps", [])

            # Build report text
            report_lines = [
                f"PropertyOS Insurance Gap Report — {user_name or 'Guest'}",
                f"Properties: {len(properties)} | Total portfolio value: SGD {sum(p['value_sgd'] for p in properties):,}",
                "",
            ]
            if not gaps:
                st.success("✅ No major gaps detected based on the information provided.")
                report_lines.append("No major gaps detected.")
            else:
                total_ref = result.get('total_referral_value_sgd', 0)
                st.warning(f"**{len(gaps)} potential gap(s) found.** Estimated premium exposure: SGD {total_ref:,}/year")
                for gap in gaps:
                    with st.expander(f"⚠️ {gap['gap']} — Priority: {gap['priority']}"):
                        st.write(gap["reason"])
                        c_gap1, c_gap2 = st.columns(2)
                        c_gap1.metric("Est. Annual Premium", f"SGD {gap.get('est_annual_premium_sgd', 0):,}")
                        c_gap2.metric("Priority", gap["priority"])
                        st.caption(gap.get("disclaimer", ""))
                    report_lines.append(f"GAP: {gap['gap']} (Priority: {gap['priority']})")
                    report_lines.append(f"  Reason: {gap['reason']}")
                    report_lines.append(f"  Est. premium: SGD {gap.get('est_annual_premium_sgd', 0):,}/year")
                    report_lines.append("")

            st.caption(result.get("next_step", ""))
            report_text = "\n".join(report_lines)

            if send_report:
                if not user_email:
                    st.warning("Enter your email address to receive the report.")
                else:
                    # Email via smtplib (uses Gmail SMTP if configured) or show report inline
                    smtp_host = os.environ.get("SMTP_HOST", "")
                    if smtp_host:
                        import smtplib
                        from email.mime.text import MIMEText
                        try:
                            msg = MIMEText(report_text)
                            msg["Subject"] = "Your PropertyOS Insurance Gap Report"
                            msg["From"] = os.environ.get("SMTP_FROM", "noreply@propertyos.sg")
                            msg["To"] = user_email
                            with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587))) as s:
                                s.starttls()
                                s.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", ""))
                                s.send_message(msg)
                            st.success(f"📧 Report sent to **{user_email}**")
                        except Exception as e:
                            st.error(f"Email failed: {e}. Configure SMTP_HOST in .env to enable email delivery.")
                    else:
                        st.info("Email delivery requires SMTP configuration in .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS). For now, copy the report below:")
                        st.text_area("Your Report (copy to save)", report_text, height=200)

    with ins_tab2:
        st.subheader("Saved Profiles")
        try:
            conn = _ins_db()
            rows = conn.execute("SELECT id, name, email, updated_at FROM insurance_profiles ORDER BY updated_at DESC").fetchall()
            conn.close()
            if not rows:
                st.info("No saved profiles yet. Fill in your portfolio and click 'Save Profile'.")
            else:
                for pid, pname, pemail, pupdated in rows:
                    with st.expander(f"👤 {pname} — {pemail} (saved {pupdated[:10]})"):
                        if st.button("Load & Re-analyse", key=f"load_{pid}"):
                            import json as _json
                            conn2 = _ins_db()
                            row = conn2.execute("SELECT properties_json FROM insurance_profiles WHERE id=?", (pid,)).fetchone()
                            conn2.close()
                            if row:
                                _props = _json.loads(row[0])
                                agent = InsuranceAgent()
                                result = agent.analyse_portfolio_gaps({"properties": _props})
                                gaps = result.get("gaps", [])
                                if not gaps:
                                    st.success("No gaps detected for this profile.")
                                else:
                                    for gap in gaps:
                                        st.write(f"⚠️ **{gap['gap']}** ({gap['priority']}) — {gap['reason']}")
        except Exception as e:
            st.warning(f"Could not load profiles: {e}")

# ── Mortgage ──────────────────────────────────────────────────────────────────
elif tab_select == "🏦 Mortgage":
    st.header("🏦 Mortgage Calculator & Refi Advisor")
    st.caption(f"Current SORA 3M: **{SORA_3M}%** · Rates updated June 2026")

    agent = MortgageAgent()

    mort_tab1, mort_tab2, mort_tab3, mort_tab4 = st.tabs([
        "📐 Loan Calculator", "🏦 Bank Comparison", "♻️ Refi Analysis", "🏛️ Affordability Check"
    ])

    # ── Tab 1: Loan Calculator ─────────────────────────────────────────────────
    with mort_tab1:
        st.subheader("Monthly Repayment Calculator")
        c1, c2 = st.columns(2)
        prop_price = c1.number_input("Property Price (SGD)", value=650000, step=10000, min_value=100000)
        ltv_pct = c1.slider("Loan-to-Value %", 50, 80, 75, help="HDB: up to 80% (bank loan), Private: up to 75%")
        tenure = c2.slider("Loan Tenure (years)", 5, 30, 25)
        rate = c2.number_input("Interest Rate (% p.a.)", value=3.68, step=0.05, min_value=1.0, max_value=8.0)
        cpf_monthly = c2.number_input("Monthly CPF OA contribution (SGD)", value=800, step=100, min_value=0)

        loan = prop_price * ltv_pct / 100
        cash_down = prop_price - loan

        if st.button("Calculate", type="primary", key="mort_calc"):
            result = agent.calculate(prop_price, loan, tenure, rate, cpf_monthly)
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Monthly Repayment", f"SGD {result['monthly_repayment']:,.0f}")
            m2.metric("Cash Down Payment", f"SGD {cash_down:,.0f}")
            m3.metric("Total Interest Paid", f"SGD {result['total_interest']:,.0f}")
            m4.metric("Interest / Loan", f"{result['interest_to_loan_ratio']}%")

            st.divider()
            c3, c4 = st.columns(2)
            c3.metric("CPF covers", f"{result['cpf_covers_pct']}%")
            c4.metric("Monthly cash top-up needed", f"SGD {result['monthly_cash_top_up']:,.0f}")

            # Amortisation highlights
            with st.expander("Amortisation breakdown"):
                import pandas as _pd
                r = rate / 100 / 12
                rows = []
                bal = loan
                for yr in [1, 3, 5, 10, 15, 20, int(tenure)]:
                    n = yr * 12
                    if n > tenure * 12:
                        break
                    # Principal paid by year n
                    if r > 0:
                        bal_remaining = loan * (1 + r)**n - result['monthly_repayment'] * ((1 + r)**n - 1) / r
                    else:
                        bal_remaining = loan - result['monthly_repayment'] * n
                    bal_remaining = max(0, bal_remaining)
                    principal_paid = loan - bal_remaining
                    rows.append({"Year": yr, "Balance Remaining (SGD)": f"{bal_remaining:,.0f}",
                                 "Principal Paid (SGD)": f"{principal_paid:,.0f}",
                                 "% Paid Off": f"{principal_paid/loan*100:.1f}%"})
                st.dataframe(_pd.DataFrame(rows).set_index("Year"), use_container_width=True)

    # ── Tab 2: Bank Comparison ─────────────────────────────────────────────────
    with mort_tab2:
        st.subheader("Bank Rate Comparison")
        import pandas as _pd

        bc1, bc2, bc3 = st.columns(3)
        bc_loan = bc1.number_input("Loan Amount (SGD)", value=487500, step=10000, min_value=100000, key="bc_loan")
        bc_tenure = bc2.slider("Tenure (years)", 5, 30, 25, key="bc_ten")
        bc_hdb = bc3.checkbox("HDB flat? (includes HDB loan option)", value=True, key="bc_hdb")
        bc_type = bc3.radio("Rate type", ["fixed", "floating"], key="bc_rtype", horizontal=True)

        results = agent.compare_banks(bc_loan, bc_tenure, bc_type, bc_hdb)

        rows = []
        for r in results:
            rows.append({
                "Bank": r["bank"],
                "Package": r["rate_name"],
                "Rate %": r["annual_rate_pct"],
                "Monthly (SGD)": f"{r['monthly_repayment']:,.0f}",
                "Total Interest (SGD)": f"{r['total_interest_sgd']:,.0f}",
                "Lock-in (yrs)": r["lock_in_years"],
                "Cashback (SGD)": r["cashback_sgd"],
                "Legal Subsidy": r["legal_subsidy_sgd"],
                "Net 1st-Yr Cost": f"{r['net_first_year_cost']:,.0f}",
            })

        df_banks = _pd.DataFrame(rows)
        if not df_banks.empty:
            st.dataframe(df_banks.set_index("Bank"), use_container_width=True)
            st.caption("Net 1st-Year Cost = (monthly × 12) − cashback − legal subsidy. Lower = cheaper to switch to.")

            best = results[0]
            st.success(f"**Best deal:** {best['bank']} — {best['rate_name']} at **{best['annual_rate_pct']}%** "
                       f"(SGD {best['monthly_repayment']:,.0f}/mo). Net first-year cost after incentives: SGD {best['net_first_year_cost']:,.0f}.")

        # Detailed rate schedules
        with st.expander("All rate schedules"):
            for r in results:
                st.markdown(f"**{r['bank']}**")
                for pkg in r["all_rates"]:
                    st.markdown(f"  · Year {pkg['year']}: {pkg['name']} — **{pkg['rate']:.2f}%**")
                if r["note"]:
                    st.info(r["note"])

    # ── Tab 3: Refi Analysis ───────────────────────────────────────────────────
    with mort_tab3:
        st.subheader("Refinancing Savings Calculator")
        st.info("Find out if switching banks saves money — and by how much.")

        rc1, rc2, rc3 = st.columns(3)
        cur_rate = rc1.number_input("Your current rate (% p.a.)", value=4.20, step=0.05, min_value=1.0, max_value=8.0, key="cur_rate")
        cur_outstanding = rc2.number_input("Outstanding loan (SGD)", value=450000, step=10000, min_value=50000, key="cur_out")
        rem_tenure = rc3.slider("Remaining tenure (years)", 1, 30, 20, key="rem_ten")
        cur_bank = rc1.text_input("Current bank", value="DBS", key="cur_bank")

        if st.button("Analyse Refi Savings", type="primary", key="refi_btn"):
            with st.spinner("Comparing rates..."):
                refi = agent.refi_analysis(cur_rate, cur_outstanding, rem_tenure, cur_bank)

            best = refi["best_refi"]
            if best:
                verdict_color = "success" if best["worth_refi"] else "warning"
                getattr(st, verdict_color)(f"**{refi['recommendation']}**")

                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Current Monthly", f"SGD {refi['current_monthly']:,.0f}")
                r2.metric("Best New Monthly", f"SGD {best['new_monthly']:,.0f}", delta=f"-SGD {best['monthly_saving']:,.0f}/mo")
                r3.metric("Annual Saving", f"SGD {best['annual_saving']:,.0f}")
                r4.metric("Breakeven Period", f"{best['breakeven_months']} months")

                import pandas as _pd
                rows = []
                for opt in refi["all_options"]:
                    rows.append({
                        "Bank": opt["bank"],
                        "New Rate %": opt["new_rate_pct"],
                        "Monthly (SGD)": f"{opt['new_monthly']:,.0f}",
                        "Monthly Saving": f"{opt['monthly_saving']:,.0f}",
                        "Annual Saving": f"{opt['annual_saving']:,.0f}",
                        "Switching Cost": f"{opt['switching_cost_sgd']:,.0f}",
                        "Breakeven (mo)": opt["breakeven_months"],
                        "Net Saving": f"{opt['net_saving_over_tenure']:,.0f}",
                        "Worth It?": "✅" if opt["worth_refi"] else "⏳",
                    })
                if rows:
                    st.dataframe(_pd.DataFrame(rows).set_index("Bank"), use_container_width=True)

                # MRTA alert
                if "insurance_alert" in refi:
                    alert = refi["insurance_alert"]
                    st.warning(f"🛡️ **Mortgage Protection Review**\n\n{alert['message']}")
                    if st.button("💬 Get Mortgage Protection Quote", key="mrta_from_refi"):
                        st.switch_page = None  # navigation placeholder
                        st.info("Head to the 🛡️ Insurance tab to run a full MRTA analysis for your new loan.")

                # AI narrative
                if "narrative" in refi:
                    with st.expander("🤖 AI Refi Commentary"):
                        st.write(refi["narrative"])
            else:
                st.info("Your current rate is already competitive — no significant savings from refinancing now.")
                st.caption(refi["recommendation"])

    # ── Tab 4: Affordability Check ─────────────────────────────────────────────
    with mort_tab4:
        st.subheader("TDSR / MSR Affordability Check")
        st.caption("MAS guidelines: TDSR ≤ 55% (all loans), MSR ≤ 30% for HDB/EC loans.")

        ac1, ac2 = st.columns(2)
        gross_income = ac1.number_input("Gross monthly income (SGD)", value=8000, step=500, min_value=1000, key="gross_inc")
        aff_loan = ac1.number_input("Loan amount (SGD)", value=487500, step=10000, min_value=50000, key="aff_loan")
        aff_tenure = ac1.slider("Tenure (years)", 5, 30, 25, key="aff_ten")
        aff_rate = ac1.number_input("Interest rate (% p.a.)", value=3.68, step=0.05, min_value=1.0, key="aff_rate")
        other_debts = ac2.number_input("Other monthly debt payments (car loan, study loan, etc.) SGD", value=0, step=100, min_value=0, key="other_debts")
        aff_hdb = ac2.checkbox("HDB flat? (applies MSR limit)", value=True, key="aff_hdb")
        aff_age = ac2.slider("Your age", 21, 65, 35, key="aff_age")
        cpf_oa = ac2.number_input("Monthly CPF OA contribution (SGD)", value=800, step=100, min_value=0, key="cpf_oa")

        if st.button("Check Affordability", type="primary", key="aff_btn"):
            aff = agent.affordability_check(gross_income, aff_loan, aff_tenure, aff_rate, other_debts, aff_hdb)

            # Verdict
            if "✅" in aff["verdict"]:
                st.success(aff["verdict"])
            else:
                st.error(aff["verdict"])

            a1, a2, a3 = st.columns(3)
            a1.metric("Monthly Repayment", f"SGD {aff['monthly_repayment']:,.0f}")
            a2.metric("TDSR", f"{aff['tdsr_pct']}%", delta=f"Limit: {aff['tdsr_limit_pct']}%",
                      delta_color="off" if aff["tdsr_pass"] else "inverse")
            if aff_hdb:
                a3.metric("MSR", f"{aff['msr_pct']}%", delta=f"Limit: {aff['msr_limit_pct']}%",
                          delta_color="off" if aff["msr_pass"] else "inverse")

            st.info(f"💡 {aff['tip']}")

            # CPF projection
            st.divider()
            st.markdown("**CPF OA Projection**")
            cpf = agent.cpf_projection(aff_loan / 0.75, aff_loan, aff_tenure, aff_rate, cpf_oa, aff_age)
            cp1, cp2, cp3 = st.columns(3)
            cp1.metric("Monthly CPF used", f"SGD {cpf['monthly_cpf_used']:,.0f}")
            cp2.metric("Monthly cash needed", f"SGD {cpf['monthly_cash_needed']:,.0f}")
            cp3.metric("Total CPF over tenure", f"SGD {cpf['total_cpf_used']:,.0f}")
            if cpf["warning"]:
                st.warning(f"⚠️ {cpf['warning']}")
            elif cpf["within_cpf_limit"]:
                st.success("✅ CPF usage within valuation limit for entire tenure.")

            # MRTA nudge for new buyers
            st.divider()
            st.markdown("### 🛡️ Protect Your Mortgage")
            st.markdown(
                f"On a SGD {aff_loan:,.0f} loan over {aff_tenure} years, "
                f"a Mortgage Protection policy typically costs **SGD 2,000–5,000** as a one-time premium "
                f"and pays off your outstanding mortgage if you pass away or become critically ill. "
                f"Your family keeps the home — not just the debt."
            )
            if st.button("💬 Check My Mortgage Protection", key="mrta_from_aff"):
                st.info("Head to the 🛡️ Insurance tab → Analyse to build your full insurance portfolio including MRTA/MLTA coverage.")

    # ── Mortgage Broker Referral ──────────────────────────────────────────────
    st.divider()
    with st.expander("🏦 Get matched with a licensed mortgage broker — free, no obligation", expanded=False):
        st.markdown("""
**Why use a broker instead of going direct to a bank?**
- Brokers compare **all major banks simultaneously** (DBS, OCBC, UOB, Maybank, SCB and more)
- They negotiate on your behalf — often securing rates 0.1–0.3% lower than walk-in
- **No cost to you** — brokers are paid by the bank when your loan is approved
- Pre-qualify before committing to an OTP, avoiding last-minute loan rejections
        """)
        st.subheader("Request a Free Mortgage Consultation")
        br_col1, br_col2 = st.columns(2)
        with br_col1:
            br_name = st.text_input("Your name", key="br_name", placeholder="Lee Wei Ming")
            br_email = st.text_input("Email address", key="br_email", placeholder="you@email.com")
            br_phone = st.text_input("Mobile (optional)", key="br_phone", placeholder="+65 9xxx xxxx")
        with br_col2:
            br_loan = st.number_input("Loan amount needed (SGD)", 100000, 5000000, 500000, step=50000, key="br_loan")
            br_prop_type = st.selectbox("Property type", ["HDB", "Private Condo/Apt", "EC", "Landed"], key="br_ptype")
            br_timeline = st.selectbox("Timeline", ["Within 1 month", "1–3 months", "3–6 months", "Just exploring"], key="br_timeline")
        br_notes = st.text_area("Any other details (optional)", key="br_notes", placeholder="e.g. currently on OCBC package expiring Oct 2026, looking to refinance...")

        if st.button("📩 Submit Referral Request", type="primary", key="broker_submit"):
            if not br_name or not br_email:
                st.warning("Please enter at least your name and email.")
            else:
                import asyncio
                async def _send_broker_lead():
                    try:
                        from telegram import Bot
                        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                        admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
                        if bot_token and admin_id:
                            bot = Bot(token=bot_token)
                            msg = (
                                f"🏦 *New Broker Referral Lead*\n\n"
                                f"👤 Name: {br_name}\n"
                                f"📧 Email: {br_email}\n"
                                f"📱 Phone: {br_phone or '—'}\n"
                                f"💰 Loan: SGD {br_loan:,.0f}\n"
                                f"🏠 Type: {br_prop_type}\n"
                                f"⏱ Timeline: {br_timeline}\n"
                                f"📝 Notes: {br_notes or '—'}"
                            )
                            await bot.send_message(chat_id=admin_id, text=msg, parse_mode="Markdown")
                    except Exception:
                        pass
                try:
                    asyncio.run(_send_broker_lead())
                except Exception:
                    pass
                try:
                    from data.analytics import log_broker_lead
                    log_broker_lead(br_name, br_email, br_phone, br_loan, br_prop_type, br_timeline, br_notes, session_id=_session_id, ip=_visitor_ip)
                except Exception:
                    pass
                st.success(
                    f"✅ Thank you {br_name}! Your request has been received. "
                    "A licensed mortgage broker will contact you within 1 business day. "
                    "This service is completely free — no obligation to proceed."
                )
                st.balloons()

# ── Tools (Stamp Duty + ROI + Affordability) ──────────────────────────────────
elif tab_select == "💹 Tools":
    from data.stamp_duty import full_stamp_duty, calc_ssd, ABSD_RATES
    from data.roi_projector import project_roi, affordability_planner, GROSS_YIELD_BENCHMARKS
    import pandas as _pd

    st.header("💹 Property Calculators")

    tool_tab1, tool_tab2, tool_tab3 = st.tabs([
        "🏷️ Stamp Duty (ABSD/BSD)", "📈 Investment ROI", "🧮 Affordability Planner"
    ])

    # ── Stamp Duty ─────────────────────────────────────────────────────────────
    with tool_tab1:
        st.subheader("Stamp Duty Calculator")
        from data.stamp_duty import RATES_EFFECTIVE_DATE
        st.caption(f"Rates effective {RATES_EFFECTIVE_DATE} (IRAS). BSD applies to all buyers. ABSD is additional based on profile and property count. Verify at iras.gov.sg before transacting.")

        sd1, sd2 = st.columns(2)
        sd_price = sd1.number_input("Purchase Price (SGD)", value=1_000_000, step=50_000, min_value=100_000, key="sd_price")
        sd_profile = sd1.selectbox("Buyer Profile", ["SC", "SPR", "Foreigner", "Entity"],
            format_func=lambda x: {"SC":"🇸🇬 Singapore Citizen","SPR":"🟢 PR","Foreigner":"🌍 Foreigner","Entity":"🏢 Company/Trust"}[x], key="sd_prof")
        sd_count = sd2.selectbox("Property count after this purchase",
            [1, 2, 3], format_func=lambda x: {1:"1st property",2:"2nd property",3:"3rd or more"}[x], key="sd_count")
        sd_hdb = sd2.checkbox("HDB flat?", value=False, key="sd_hdb")
        sd_sell = sd2.checkbox("Planning to sell within 3 years? (SSD)", value=False, key="sd_sell")
        sd_hold = None
        if sd_sell:
            sd_hold = sd2.slider("Expected hold period (months)", 1, 36, 24, key="sd_hold")

        sd_result = full_stamp_duty(sd_price, sd_profile, sd_count, sd_hdb)

        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("BSD", f"SGD {sd_result['bsd']['total_bsd_sgd']:,.0f}", f"{sd_result['bsd']['effective_rate_pct']}%")
        m2.metric("ABSD", f"SGD {sd_result['absd']['total_absd_sgd']:,.0f}", f"{sd_result['absd']['absd_rate_pct']:.0f}%")
        m3.metric("Total Stamp Duty", f"SGD {sd_result['total_stamp_duty_sgd']:,.0f}", f"{sd_result['effective_total_rate_pct']}%")
        m4.metric("Total Cash Upfront", f"SGD {sd_result['total_upfront_cash_sgd']:,.0f}",
                  help="Downpayment + stamp duties. All in cash (no CPF for stamp duties).")

        if sd_sell and sd_hold:
            ssd = calc_ssd(sd_price, sd_hold)
            if ssd["total_ssd_sgd"] > 0:
                st.warning(f"⚠️ **SSD applies:** SGD {ssd['total_ssd_sgd']:,.0f} ({ssd['rate_pct']:.0f}%) — {ssd['note']}")
            else:
                st.success("✅ No SSD — held more than 3 years.")

        for note in sd_result["absd"]["notes"]:
            st.info(f"ℹ️ {note}")

        with st.expander("BSD breakdown by band"):
            bsd_rows = [{
                "Band": b["band"], "Rate": f"{b['rate_pct']:.0f}%",
                "Taxable (SGD)": f"{b['taxable_sgd']:,.0f}",
                "Duty (SGD)": f"{b['duty_sgd']:,.0f}",
            } for b in sd_result["bsd"]["breakdown"]]
            st.dataframe(_pd.DataFrame(bsd_rows), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Quick ABSD Reference**")
        absd_rows = []
        for profile, rates in ABSD_RATES.items():
            absd_rows.append({
                "Profile": {"SC":"🇸🇬 SC","SPR":"🟢 SPR","Foreigner":"🌍 Foreigner","Entity":"🏢 Entity"}.get(profile, profile),
                "1st Property": f"{rates[1]*100:.0f}%",
                "2nd Property": f"{rates[2]*100:.0f}%",
                "3rd+ Property": f"{rates[3]*100:.0f}%",
            })
        st.dataframe(_pd.DataFrame(absd_rows), use_container_width=True, hide_index=True)
        st.caption("Source: IRAS. Rates as of Feb 2023 cooling measures.")

    # ── Investment ROI ─────────────────────────────────────────────────────────
    with tool_tab2:
        st.subheader("Investment ROI Projector")
        st.caption("Model rental income, holding costs, mortgage, and capital gain scenarios to see your real return.")

        r1, r2 = st.columns(2)
        roi_price = r1.number_input("Purchase Price (SGD)", value=1_200_000, step=50_000, min_value=200_000, key="roi_price")
        roi_ltv = r1.slider("Loan-to-Value %", 0, 75, 75, key="roi_ltv")
        roi_rate = r1.number_input("Mortgage Rate (% p.a.)", value=3.68, step=0.05, key="roi_rate")
        roi_tenure = r1.slider("Loan Tenure (years)", 5, 30, 25, key="roi_ten")
        roi_rent = r2.number_input("Expected Monthly Rent (SGD)", value=4_500, step=100, key="roi_rent")
        roi_type = r2.selectbox("Property Type", list(GROSS_YIELD_BENCHMARKS.keys()), key="roi_type")
        roi_hold = r2.slider("Planned Hold Period (years)", 2, 20, 5, key="roi_hold")
        roi_absd = r2.number_input("ABSD paid (SGD, 0 if none)", value=0, step=10_000, key="roi_absd")
        roi_bsd = r2.number_input("BSD paid (SGD)", value=0, step=1_000, key="roi_bsd")

        if st.button("Project Returns", type="primary", key="roi_btn"):
            loan = roi_price * roi_ltv / 100
            res = project_roi(roi_price, loan, roi_rate, roi_tenure, roi_rent,
                              roi_type, roi_hold, roi_absd, roi_bsd)

            st.divider()
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Gross Yield", f"{res['gross_yield_pct']:.2f}%")
            p2.metric("Net Yield", f"{res['net_yield_pct']:.2f}%")
            p3.metric("Monthly Cash Flow", f"SGD {res['monthly_cashflow_sgd']:,.0f}",
                      delta="positive" if res["cashflow_positive"] else "negative",
                      delta_color="normal" if res["cashflow_positive"] else "inverse")
            p4.metric("Equity Invested", f"SGD {res['equity_invested']:,.0f}")

            bench = res["yield_benchmark"]
            if res["gross_yield_pct"] >= bench["market_mid_pct"]:
                st.success(f"✅ Yield is **{res['gross_yield_pct']:.2f}%** — above market median of {bench['market_mid_pct']}% for {roi_type}.")
            else:
                st.warning(f"⚠️ Yield is **{res['gross_yield_pct']:.2f}%** — below market median of {bench['market_mid_pct']}% for {roi_type}. Consider negotiating price or raising rent.")

            st.divider()
            st.markdown(f"#### Capital Gain Scenarios over {roi_hold} years")
            scen_rows = []
            for k, s in res["capital_scenarios"].items():
                scen_rows.append({
                    "Scenario": s["label"],
                    "Appreciation": f"{s['annual_appreciation_pct']}%/yr",
                    "Future Value": f"SGD {s['future_value_sgd']:,.0f}",
                    "Capital Gain": f"SGD {s['capital_gain_sgd']:,.0f}",
                    "Rental Income": f"SGD {s['total_rental_income_sgd']:,.0f}",
                    "Total Return": f"SGD {s['total_return_sgd']:,.0f}",
                    "ROI (leveraged)": f"{s['roi_leveraged_pct']:.1f}%",
                    "Annualised": f"{s['annualised_roi_pct']:.1f}%/yr",
                })
            st.dataframe(_pd.DataFrame(scen_rows), use_container_width=True, hide_index=True)

            with st.expander("Annual cost breakdown"):
                costs = res["annual_costs_breakdown"]
                cost_rows = [
                    {"Cost item": "Property tax (investment)", "Annual SGD": f"{costs['property_tax_sgd']:,.0f}"},
                    {"Cost item": "Maintenance / S&CC", "Annual SGD": f"{costs['maintenance_sgd']:,.0f}"},
                    {"Cost item": "Insurance", "Annual SGD": f"{costs['insurance_sgd']:,.0f}"},
                    {"Cost item": "Vacancy allowance (1 mo/yr)", "Annual SGD": f"{costs['vacancy_allowance_sgd']:,.0f}"},
                    {"Cost item": "Agent fees", "Annual SGD": f"{costs['agent_fees_sgd']:,.0f}"},
                    {"Cost item": "Repairs & maintenance", "Annual SGD": f"{costs['repairs_sgd']:,.0f}"},
                    {"Cost item": "**Total costs**", "Annual SGD": f"**{costs['total_sgd']:,.0f}**"},
                ]
                st.dataframe(_pd.DataFrame(cost_rows), use_container_width=True, hide_index=True)

            if res["payback_years"]:
                st.info(f"💡 Estimated full payback (equity recovered via cashflow + capital gain): **{res['payback_years']} years** under base scenario.")

            # MRTA nudge
            st.divider()
            st.markdown("### 🛡️ Protect this investment")
            st.markdown(
                f"With SGD {loan:,.0f} in mortgage financing, a Mortgage Protection policy ensures "
                f"your family keeps this investment property — not just the liability — if you're unable to service the loan. "
                f"Typical cost: SGD 2,000–5,000 one-time premium."
            )

    # ── Affordability Planner ──────────────────────────────────────────────────
    with tool_tab3:
        st.subheader("Affordability Planner")
        st.caption("Enter your income, CPF, and savings to find your maximum purchase price.")

        a1, a2 = st.columns(2)
        aff_income = a1.number_input("Gross monthly income (SGD)", value=8_000, step=500, key="aff2_inc")
        aff_cpf = a1.number_input("Monthly CPF OA contribution (SGD)", value=800, step=100, key="aff2_cpf")
        aff_cash = a1.number_input("Cash savings available (SGD)", value=150_000, step=10_000, key="aff2_cash")
        aff_profile = a2.selectbox("Buyer profile", ["SC", "SPR", "Foreigner"],
            format_func=lambda x: {"SC":"🇸🇬 Singapore Citizen","SPR":"🟢 PR","Foreigner":"🌍 Foreigner"}[x], key="aff2_prof")
        aff_count = a2.selectbox("This will be my...", [1, 2, 3],
            format_func=lambda x: {1:"1st property",2:"2nd property",3:"3rd+ property"}[x], key="aff2_cnt")
        aff_hdb2 = a2.checkbox("Looking at HDB?", value=True, key="aff2_hdb")
        aff_tenure2 = a2.slider("Preferred loan tenure", 10, 30, 25, key="aff2_ten")
        aff_rate2 = a2.number_input("Expected rate (% p.a.)", value=3.68 if not aff_hdb2 else 2.60, step=0.05, key="aff2_rate")

        if st.button("Calculate Max Budget", type="primary", key="aff2_btn"):
            res = affordability_planner(aff_income, aff_cpf, aff_cash,
                                        aff_hdb2, aff_profile, aff_count,
                                        aff_tenure2, aff_rate2)
            st.divider()
            b1, b2, b3 = st.columns(3)
            b1.metric("Max Purchase Price", f"SGD {res['max_purchase_price_sgd']:,.0f}")
            b2.metric("Monthly Repayment", f"SGD {res['monthly_repayment_sgd']:,.0f}")
            b3.metric("Total Cash Needed", f"SGD {res['total_cash_outlay_sgd']:,.0f}")

            st.divider()
            st.markdown("**How your money is used:**")
            d1, d2, d3 = st.columns(3)
            d1.metric("5% Cash Downpayment", f"SGD {res['cash_needed_for_downpayment_sgd']:,.0f}")
            d2.metric("CPF for Downpayment", f"SGD {res['cpf_for_downpayment_sgd']:,.0f}")
            d3.metric("Stamp Duties (cash)", f"SGD {res['stamp_duty_cash_sgd']:,.0f}")

            st.info(f"💡 Limit used: **{res['income_limit_used']}**. This is the maximum — staying 10–15% below gives you buffer for rate rises.")

            # Surface deals at this budget
            st.divider()
            st.markdown(f"**Looking for HDB deals under SGD {res['max_purchase_price_sgd']:,.0f}?**")
            try:
                from data.hdb_pipeline import find_below_market_hdb
                _budget_deals = find_below_market_hdb(
                    max_price=res["max_purchase_price_sgd"] * 1.05,
                    threshold_pct=3.0, limit=3
                )
                if _budget_deals:
                    for d in _budget_deals:
                        st.markdown(
                            f"🟢 **{d['town']} {d['flat_type']}** — "
                            f"SGD {d['resale_price']:,.0f} · {d['discount_pct']:.1f}% below market · "
                            f"{d['floor_area_sqm']:.0f} sqm"
                        )
                    st.caption("From 📊 Deal Feed. Go to Deal Feed tab for full details.")
            except Exception:
                st.caption("Head to 📊 Deal Feed to browse properties in your budget.")

# ── Watchlist ─────────────────────────────────────────────────────────────────
elif tab_select == "🔔 Watchlist":
    st.header("🔔 Property Watchlist & Price Alerts")

    with st.expander("ℹ️ How Watchlist alerts work — read this first", expanded=False):
        st.markdown("""
**What PropOS Watchlist monitors**

PropOS tracks **confirmed resale transactions** from official government data — not live listings on PropertyGuru or 99.co. This means:

| What it IS | What it is NOT |
|---|---|
| ✅ Real sold prices (what buyers actually paid) | ❌ Live asking prices from agents |
| ✅ Alerts when a unit matching your criteria has SOLD below your target | ❌ "This unit is for sale now" notifications |
| ✅ Useful for knowing the real market clearing price | ❌ Direct link to available listings |

**Why confirmed transactions are more valuable than listings:**
Asking prices on portals are often inflated by 5–15%. Knowing what similar units *actually sold for* tells you your real negotiation anchor.

**Step-by-step:**
1. **Enter your Telegram ID** below (message @userinfobot on Telegram to get it)
2. Go to **➕ Add Watch** → set your town, flat type, max price, and threshold
3. PropOS checks automatically on your chosen frequency
4. Alert via **@AcePropOS_bot** when a matching sold transaction appears

**Alert threshold**
- **0%** → any transaction in your price range
- **5%** → only when sold price is 5%+ below town median (genuine deals)
- **10%+** → only the sharpest below-market transactions

> 📊 **HDB resale** data updates daily from data.gov.sg. **Private condo** alerts use URA transaction data (updated weekly).
        """)

    init_watchlist_db()

    _user_id = st.text_input(
        "Your Telegram ID (for alerts) — message @userinfobot to find yours",
        value=str(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")),
        placeholder="e.g. 1245366658",
        key="wl_user_id",
    )

    # ── Freemium tier status banner ──────────────────────────────────────────────
    if _user_id:
        try:
            from data.freemium import tier_info, UPGRADE_CTA
            _tier = tier_info(_user_id)
            _used = _tier["alerts_used_this_week"]
            _limit = _tier["watchlist_alerts_per_week"]
            if _tier["tier"] == "pro":
                st.success(f"✅ **PropOS Pro** — unlimited alerts active")
            else:
                _pct = min(100, int(_used / max(_limit, 1) * 100))
                if _used >= _limit:
                    st.error(f"🔒 **Free tier limit reached** ({_used}/{_limit} alerts this week). {UPGRADE_CTA}")
                elif _used >= _limit - 1:
                    st.warning(f"⚠️ **{_used}/{_limit} alerts used this week** — 1 remaining. Upgrade to Pro for unlimited.")
                else:
                    st.info(f"🆓 **Free tier** — {_used}/{_limit} alerts used this week · [Upgrade to Pro →](https://t.me/AcePropOS_bot)")
        except Exception:
            pass

    wl_tab1, wl_tab2, wl_tab3 = st.tabs(["➕ Add Watch", "📋 My Watches", "🔍 Run Check Now"])

    # ── Add Watch ──────────────────────────────────────────────────────────────
    with wl_tab1:
        st.subheader("Add a new property alert")
        import pandas as _pd
        # Load town options from HDB cache
        cache_path = Path(__file__).parent.parent / "cache" / "hdb" / "resale.json"
        town_options = ["Any"]
        flat_type_options = ["Any", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"]
        if cache_path.exists():
            try:
                _recs = json.load(open(cache_path))
                town_options = ["Any"] + sorted(set(r.get("town","") for r in _recs if r.get("town")))
                flat_type_options = ["Any"] + sorted(set(r.get("flat_type","") for r in _recs if r.get("flat_type")))
            except Exception:
                pass

        w1, w2 = st.columns(2)
        wl_label = w1.text_input("Alert name", placeholder="e.g. Tampines 4-room under 600K")
        wl_town = w1.selectbox("Town", town_options, key="wl_town")
        wl_flat = w1.selectbox("Flat type", flat_type_options, key="wl_flat")
        wl_street = w1.text_input("Street keyword (optional)", placeholder="e.g. TAMPINES ST")

        wl_max_price = w2.number_input("Max price (SGD, 0 = no limit)", value=0, step=10000, min_value=0, key="wl_max")
        wl_min_area = w2.number_input("Min floor area (sqm, 0 = no limit)", value=0, step=5, min_value=0, key="wl_min_area")
        wl_threshold = w2.slider("Alert when below market by (%)", 0, 20, 5, key="wl_thresh",
                                  help="0 = alert on any match; 5 = only if 5%+ below median PSF")
        wl_frequency = w2.selectbox(
            "Alert frequency",
            ["daily", "weekly", "monthly", "hourly"],
            index=0,
            key="wl_freq",
            help="How often you want to receive alerts. Daily is recommended — avoids notification overload.",
        )
        _freq_labels = {"hourly": "every hour", "daily": "once per day at most",
                        "weekly": "once per week at most", "monthly": "once per month at most"}
        w2.caption(f"ℹ️ You'll be alerted {_freq_labels.get(wl_frequency, 'daily')}.")

        if st.button("➕ Save Alert", type="primary", key="wl_add"):
            if not wl_label:
                st.warning("Please enter an alert name.")
            else:
                wid = add_watch(
                    user_id=_user_id,
                    label=wl_label,
                    town=None if wl_town == "Any" else wl_town,
                    flat_type=None if wl_flat == "Any" else wl_flat,
                    street_keyword=wl_street or None,
                    max_price_sgd=wl_max_price or None,
                    min_floor_sqm=wl_min_area or None,
                    alert_threshold_pct=float(wl_threshold),
                    alert_frequency=wl_frequency,
                )
                st.success(f"✅ Alert #{wid} saved: **{wl_label}** · alerts {_freq_labels[wl_frequency]}")
                st.rerun()

    # ── My Watches ─────────────────────────────────────────────────────────────
    with wl_tab2:
        watches = list_watches(_user_id)
        if not watches:
            st.info("No active alerts yet. Add one in the ➕ Add Watch tab.")
        else:
            st.markdown(f"**{len(watches)} active alert(s)**")
            for w in watches:
                criteria = []
                if w["town"]: criteria.append(f"Town: {w['town']}")
                if w["flat_type"]: criteria.append(f"Type: {w['flat_type']}")
                if w["street_keyword"]: criteria.append(f"Street: {w['street_keyword']}")
                if w["max_price_sgd"]: criteria.append(f"Max: SGD {w['max_price_sgd']:,.0f}")
                if w["min_floor_sqm"]: criteria.append(f"Min area: {w['min_floor_sqm']} sqm")
                criteria.append(f"Alert when ≥{w['alert_threshold_pct']}% below market")
                criteria.append(f"Frequency: {w.get('alert_frequency','daily')}")

                with st.expander(f"🔔 {w['label']}  (#{w['id']})"):
                    st.markdown(" · ".join(criteria))
                    st.caption(f"Created: {w['created_at'][:10]}  |  Last checked: {w.get('last_checked_at','never')[:10] if w.get('last_checked_at') else 'never'}  |  Last alerted: {w.get('last_alerted_at','never')}")
                    if st.button(f"🗑️ Delete alert #{w['id']}", key=f"wl_del_{w['id']}"):
                        delete_watch(w["id"], _user_id)
                        st.success("Alert deleted.")
                        st.rerun()

    # ── Run Check ──────────────────────────────────────────────────────────────
    with wl_tab3:
        st.subheader("Scan HDB transactions against your alerts")
        st.caption("This normally runs automatically every hour via cron. Run manually here to test.")

        if st.button("🔍 Check All My Alerts Now", type="primary", key="wl_run"):
            with st.spinner("Scanning last 30 days of HDB transactions..."):
                fired = check_watchlist()
                my_alerts = [a for a in fired if a["user_id"] == _user_id]

            if not my_alerts:
                st.info("No matches found. Either no qualifying transactions in the last 30 days, or alerts already sent.")
            else:
                st.success(f"🎯 {len(my_alerts)} match(es) found!")
                for alert in my_alerts:
                    with st.expander(f"🟢 {alert['town']} — {alert['flat_type']} · SGD {alert['price_sgd']:,.0f}"):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Price", f"SGD {alert['price_sgd']:,.0f}")
                        c2.metric("PSF", f"SGD {alert['psf']:,.0f}")
                        c3.metric("vs Market PSF", f"SGD {alert['market_psf']:,.0f}",
                                  delta=f"-{alert['discount_pct']}%" if alert['discount_pct'] > 0 else None,
                                  delta_color="inverse")
                        st.markdown(f"**{alert['block']} {alert['street']}** · {alert['storey']} · {alert['area_sqm']:.0f} sqm")
                        st.caption(f"Transacted: {alert['month']}  |  Alert: {alert['label']}")

                        with st.expander("Telegram message preview"):
                            st.code(format_alert_message(alert), language=None)

# ── BTO ───────────────────────────────────────────────────────────────────────
elif tab_select == "🏗️ BTO":
    from data.bto_pipeline import get_bto_summary, estimate_bto_price
    import pandas as _pd

    st.header("🏗️ BTO Launch Tracker")
    st.caption("HDB Build-to-Order launch calendar, price guide, and savings vs resale.")

    bto_tab1, bto_tab2, bto_tab3 = st.tabs(["📅 Upcoming Launches", "💰 Price Estimator", "📊 Launch History"])

    # ── Upcoming ────────────────────────────────────────────────────────────────
    with bto_tab1:
        summary = get_bto_summary()
        st.subheader("Upcoming BTO Launches")
        for launch in summary["upcoming"]:
            with st.expander(f"📅 {launch['launch_date']} — {', '.join(launch['estates'][:2])} {'+ more' if len(launch['estates']) > 2 else ''}"):
                st.markdown(f"**Estates:** {', '.join(launch['estates'])}")
                st.markdown(f"**Note:** {launch['note']}")
                st.caption(f"Source: {launch['source']}")

        st.divider()
        st.subheader("BTO vs Resale Price Guide")
        st.info("BTO flats are typically **30–50% cheaper** than resale market prices in the same area. The trade-off: 5-year Minimum Occupancy Period (MOP) before selling.")

        cols = st.columns(2)
        for i, (estate_type, prices) in enumerate(summary["price_guide"].items()):
            with cols[i % 2]:
                st.markdown(f"**{estate_type.title()} Estates**")
                rows = []
                for flat, (lo, hi) in prices.items():
                    rows.append({"Flat Type": flat, "From (SGD)": f"{lo:,}", "To (SGD)": f"{hi:,}"})
                st.dataframe(_pd.DataFrame(rows).set_index("Flat Type"), use_container_width=True)

    # ── Price Estimator ─────────────────────────────────────────────────────────
    with bto_tab2:
        st.subheader("BTO Price Estimator")

        cache_path = Path(__file__).parent.parent / "cache" / "hdb" / "resale.json"
        town_opts = ["TAMPINES", "WOODLANDS", "YISHUN", "QUEENSTOWN", "KALLANG/WHAMPOA",
                     "ANG MO KIO", "BUKIT MERAH", "JURONG WEST", "TENGAH", "SENGKANG"]
        if cache_path.exists():
            try:
                _recs = json.load(open(cache_path))
                town_opts = sorted(set(r.get("town","") for r in _recs if r.get("town")))
            except Exception:
                pass

        pe1, pe2 = st.columns(2)
        bto_town = pe1.selectbox("Select Estate", town_opts, key="bto_town")
        bto_flat = pe2.selectbox("Flat Type", ["4 ROOM", "3 ROOM", "5 ROOM", "2 ROOM FLEXI", "EXECUTIVE"], key="bto_flat")

        if st.button("Estimate BTO Price", type="primary", key="bto_est"):
            est = estimate_bto_price(bto_town, bto_flat)
            resale_data = None

            # Get current resale price for comparison
            try:
                from data.hdb_pipeline import get_town_stats
                stats = get_town_stats(bto_town, bto_flat)
                resale_median = stats.get("median_price")
            except Exception:
                resale_median = None

            st.divider()
            b1, b2, b3 = st.columns(3)
            b1.metric("BTO Price From", f"SGD {est['price_from_sgd']:,}")
            b2.metric("BTO Price To", f"SGD {est['price_to_sgd']:,}")
            if resale_median:
                bto_mid = (est['price_from_sgd'] + est['price_to_sgd']) / 2
                savings_pct = (resale_median - bto_mid) / resale_median * 100
                b3.metric("vs Resale Savings", f"~{savings_pct:.0f}%",
                          help=f"Resale median: SGD {resale_median:,.0f}")

            st.info(f"**{est['estate_type'].title()} Estate** — {est['note']}")

            if resale_median:
                st.markdown(
                    f"Current resale median for {bto_town} {bto_flat}: **SGD {resale_median:,.0f}**\n\n"
                    f"BTO midpoint estimate: **SGD {(est['price_from_sgd']+est['price_to_sgd'])//2:,}**\n\n"
                    f"Estimated instant equity on MOP: **SGD {resale_median - (est['price_from_sgd']+est['price_to_sgd'])//2:,}**"
                )

            # MRTA nudge for new flat buyers
            st.divider()
            st.markdown("### 🛡️ New BTO buyers: protect your mortgage")
            st.markdown(
                "If you're taking an HDB or bank loan for your BTO, a Mortgage Protection policy ensures your family "
                "won't lose the flat if you pass away before the loan is paid off. "
                "One-time premium typically SGD 2,000–5,000."
            )

    # ── Launch History ──────────────────────────────────────────────────────────
    with bto_tab3:
        st.subheader("Recent BTO Launch History")
        summary = get_bto_summary()
        if summary["recent_launches"]:
            df_bto = _pd.DataFrame(summary["recent_launches"])
            df_bto = df_bto[df_bto["town"].str.len() > 0] if "town" in df_bto.columns else df_bto
            st.dataframe(df_bto, use_container_width=True)
        else:
            st.info("Launch history is loading — check back shortly.")
            if st.button("🔄 Refresh", key="bto_refresh"):
                from data.bto_pipeline import fetch_bto_launches
                try:
                    records = fetch_bto_launches(force=True)
                    st.success(f"Loaded {len(records)} BTO records.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

# ── MOP Tracker ───────────────────────────────────────────────────────────────
elif tab_select == "📅 MOP Tracker":
    from data.mop_tracker import calculate_mop, mop_financial_snapshot
    from datetime import date
    import pandas as _pd

    st.header("📅 MOP Tracker")
    st.caption("Minimum Occupation Period — HDB owners must stay 5 years before selling the whole flat or buying another subsidised property.")

    mop_tab1, mop_tab2 = st.tabs(["⏱️ MOP Status", "💰 Sell or Hold?"])

    with mop_tab1:
        st.subheader("When does my MOP end?")
        st.info("The MOP clock starts from the **date you collect your keys** (Vacant Possession date shown on your HDB letter), not the purchase or signing date.")

        m1, m2 = st.columns(2)
        mop_date_input = m1.date_input(
            "Key collection date (Vacant Possession date)",
            value=date(2020, 6, 15),
            min_value=date(2000, 1, 1),
            max_value=date.today(),
            key="mop_date",
        )
        mop_flat_type = m2.selectbox("Flat type", ["BTO", "Resale HDB", "DBSS", "EC (Executive Condo)"], key="mop_flat")

        mop = calculate_mop(mop_date_input, mop_flat_type)

        st.divider()
        if mop["status"] == "completed":
            st.success(f"✅ **MOP Completed** — You are free to sell on the open market!")
            st.balloons()
        elif mop["approaching_mop"]:
            st.warning(f"⏳ **Approaching MOP** — {mop['months_remaining']} months remaining ({mop['mop_end_date']})")
            st.info("💡 Start preparing now: engage a property agent 3 months before, get a valuation, and check resale levy rules if you plan to buy another HDB.")
        else:
            st.info(f"🔒 MOP in progress — ends **{mop['mop_end_date']}**")

        # Progress bar
        st.markdown(f"**Progress: {mop['pct_complete']}%**")
        st.progress(mop["pct_complete"] / 100)

        p1, p2, p3 = st.columns(3)
        p1.metric("MOP End Date", mop["mop_end_date"])
        p2.metric("Months Remaining", mop["months_remaining"] if mop["status"] != "completed" else "Done")
        p3.metric("Time Elapsed", f"{mop['years_elapsed']}y {mop['months_elapsed']}m")

        if mop["status"] == "completed":
            st.divider()
            st.markdown("**What you can do now:**")
            for opt in mop["post_mop_options"]:
                st.markdown(f"✅ {opt}")

        st.divider()
        with st.expander("📖 MOP Rules & Common Questions"):
            for note in mop["notes"]:
                st.markdown(f"• {note}")

    with mop_tab2:
        st.subheader("Should I sell now or wait?")
        st.caption("Model your net proceeds after CPF refund, outstanding loan, and compare to holding.")

        f1, f2 = st.columns(2)
        snap_purchase = f1.number_input("Original purchase price (SGD)", value=350_000, step=10_000, key="snap_purchase")
        snap_cpf = f1.number_input("Total CPF used to date (SGD)", value=120_000, step=5_000, key="snap_cpf",
                                    help="Principal + all monthly deductions. Check via CPF website → My Statements.")
        snap_loan = f1.number_input("Outstanding loan (SGD)", value=180_000, step=5_000, key="snap_loan")
        snap_mkt = f2.number_input("Estimated current market value (SGD)", value=520_000, step=10_000, key="snap_mkt",
                                    help="Use Address Lookup tab to get a valuation estimate.")
        snap_key_date = f2.date_input("Key collection date", value=date(2020, 6, 15),
                                       min_value=date(2000, 1, 1), max_value=date.today(), key="snap_key")

        if st.button("Calculate Net Proceeds", type="primary", key="snap_btn"):
            snap = mop_financial_snapshot(snap_purchase, snap_cpf, snap_mkt, snap_loan, snap_key_date)

            st.divider()
            if snap["warning"]:
                st.error(f"🔒 {snap['warning']}")
            else:
                st.success("✅ MOP completed — legally able to sell.")

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Market Value", f"SGD {snap_mkt:,.0f}")
            s2.metric("Capital Gain", f"SGD {snap['capital_gain_sgd']:,.0f}", f"{snap['gain_pct']:+.1f}%")
            s3.metric("Annual Appreciation", f"{snap['annual_appreciation_pct']}%/yr")
            s4.metric("Net Cash in Hand", f"SGD {snap['net_cash_in_hand_sgd']:,.0f}",
                      help="After repaying loan + CPF with accrued interest")

            st.divider()
            st.markdown("**How net cash is calculated:**")
            flow_rows = [
                {"Item": "Sale proceeds", "SGD": f"{snap_mkt:,.0f}"},
                {"Item": "Less: Outstanding loan", "SGD": f"({snap['outstanding_loan_sgd']:,.0f})"},
                {"Item": "Less: CPF principal to refund", "SGD": f"({snap['cpf_used_sgd']:,.0f})"},
                {"Item": "Less: CPF accrued interest (2.5%/yr)", "SGD": f"({snap['cpf_accrued_interest_sgd']:,.0f})"},
                {"Item": "Less: Agent commission (~1–2%)", "SGD": f"({snap_mkt*0.015:,.0f})"},
                {"Item": "**Net cash proceeds**", "SGD": f"**{snap['net_cash_in_hand_sgd'] - snap_mkt*0.015:,.0f}**"},
            ]
            st.dataframe(_pd.DataFrame(flow_rows), use_container_width=True, hide_index=True)

            st.info(f"💡 {snap['tip']}")

            st.divider()
            st.markdown("### 🏠 Next steps if selling")
            st.markdown(
                "After selling your HDB, you have **6 months** to purchase a replacement property "
                "before ABSD kicks in on a private purchase. If buying another HDB, you may be subject to "
                "a **Resale Levy** (SGD 15,000–55,000 depending on flat type). Use the 💹 Tools tab to "
                "compute ABSD for your next purchase."
            )
            if st.button("📊 Calculate ABSD for Next Purchase", key="mop_to_absd"):
                st.info("Head to 💹 Tools → Stamp Duty Calculator. Set property count to 2 if you own another property.")

# ── En-Bloc Scanner ───────────────────────────────────────────────────────────
elif tab_select == "🏚️ En-Bloc":
    st.header("🏚️ En-Bloc Potential Scanner")
    st.markdown(
        "*Identify private condominiums and apartments that may be ripe for collective sale. "
        "Score is based on age, plot ratio headroom, tenure, unit count and district demand.*"
    )

    from data.enbloc_scanner import score_enbloc_potential, scan_from_ura_cache, get_district_enbloc_history, ENBLOC_HISTORY

    enbloc_tab1, enbloc_tab2, enbloc_tab3 = st.tabs(["🔍 Score a Property", "📋 District Scan", "📜 Historical En-Blocs"])

    with enbloc_tab1:
        st.subheader("Score En-Bloc Potential")
        st.caption("Enter details of a development to estimate its collective sale attractiveness.")

        col1, col2 = st.columns(2)
        with col1:
            eb_project = st.text_input("Development Name", placeholder="e.g. LUCKY TOWERS")
            eb_district = st.number_input("District (D1–D28)", min_value=1, max_value=28, value=9)
            eb_year = st.number_input("Completion Year (approx)", min_value=1970, max_value=2020, value=1995)
            eb_tenure = st.selectbox("Tenure", ["Freehold", "999-year leasehold", "99-year leasehold"])
        with col2:
            eb_units = st.number_input("Number of Units", min_value=5, max_value=2000, value=120)
            eb_site_area = st.number_input("Site Area (sqm)", min_value=500, max_value=50000, value=5000)
            eb_current_pr = st.number_input("Current Plot Ratio", min_value=0.5, max_value=5.0, value=1.4, step=0.1)
            eb_allow_pr = st.number_input("Allowable Plot Ratio (URA Master Plan)", min_value=0.5, max_value=5.0, value=2.8, step=0.1)

        if st.button("Calculate En-Bloc Score", type="primary"):
            if not eb_project:
                st.warning("Please enter a development name.")
            else:
                result = score_enbloc_potential(
                    project_name=eb_project,
                    district=eb_district,
                    completion_year=eb_year,
                    tenure=eb_tenure,
                    units=eb_units,
                    current_plot_ratio=eb_current_pr,
                    allowable_plot_ratio=eb_allow_pr,
                    site_area_sqm=eb_site_area,
                )
                st.divider()
                score_col, rating_col = st.columns([1, 2])
                with score_col:
                    st.metric("En-Bloc Score", f"{result['score']}/100")
                    st.metric("Rating", result["rating"])
                    if result["eligible"]:
                        st.success(f"✅ Eligible — {result['age_years']} years old (≥20 required)")
                    else:
                        st.error(f"❌ Not yet eligible — {result['age_years']} years old (need 20+)")
                with rating_col:
                    if result["potential_payout_per_unit_sgd"]:
                        st.metric(
                            "Est. Payout Per Unit",
                            f"SGD {result['potential_payout_per_unit_sgd']:,.0f}",
                            help="Indicative only. Based on residual land value model with conservative 60% developer margin."
                        )
                    st.caption(f"🏢 {result['units']} units · D{result['district']} · {result['tenure']}")

                st.subheader("Scoring Breakdown")
                for factor, desc, pts in result["factors"]:
                    icon = "🟢" if pts >= 15 else "🟡" if pts >= 5 else "🔴"
                    st.markdown(f"{icon} **{factor}** (+{pts} pts) — {desc}")

                st.info(result["note"])

                # District en-bloc history
                dist_hist = get_district_enbloc_history(eb_district)
                if dist_hist:
                    st.subheader(f"Past En-Blocs in D{eb_district}")
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(dist_hist)[["project", "year", "price_m", "units"]].rename(columns={
                            "project": "Development", "year": "Year", "price_m": "Sale Price (SGD M)", "units": "Units"
                        }),
                        hide_index=True, use_container_width=True
                    )

    with enbloc_tab2:
        st.subheader("District-Wide En-Bloc Scan")
        st.caption("Scans URA transaction cache to surface developments most likely to be en-bloc candidates.")

        col1, col2 = st.columns(2)
        with col1:
            scan_min_age = st.slider("Minimum Age (years)", 15, 40, 20)
        with col2:
            scan_min_score = st.slider("Minimum Score", 20, 80, 40)

        if st.button("Run Scan", type="primary"):
            with st.spinner("Scanning URA transaction cache..."):
                candidates = scan_from_ura_cache(min_age=scan_min_age, min_score=scan_min_score)

            if not candidates:
                st.info("No URA transaction data cached yet. Run `python scripts/sync_ura.py` on the VPS first to enable this scan.")
            else:
                st.success(f"Found {len(candidates)} potential en-bloc candidates")
                import pandas as pd
                rows = []
                for c in candidates:
                    rows.append({
                        "Development": c["project"],
                        "District": f"D{c['district']}",
                        "Age (yrs)": c["age_years"],
                        "Tenure": c["tenure"],
                        "Score": c["score"],
                        "Rating": c["rating"],
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, hide_index=True, use_container_width=True)
                st.caption("⚠️ Age and unit count are estimated from transaction data. Verify against URA REALIS for accuracy.")

    with enbloc_tab3:
        st.subheader("Notable Singapore En-Bloc Sales")
        st.caption("Reference database of completed collective sales used in scoring model.")
        import pandas as pd
        df_hist = pd.DataFrame(ENBLOC_HISTORY)
        df_hist = df_hist.rename(columns={
            "project": "Development", "district": "District",
            "year": "Sale Year", "price_m": "Price (SGD M)", "units": "Units"
        })
        df_hist["District"] = df_hist["District"].apply(lambda x: f"D{x}")
        df_hist["Price (SGD M)"] = df_hist["Price (SGD M)"].apply(lambda x: f"${x}M")
        st.dataframe(df_hist, hide_index=True, use_container_width=True)
        st.markdown("""
**How en-bloc works:**
1. A Collective Sale Committee (CSC) is formed by owners
2. **80% consent** (by share value and strata area) needed to proceed
3. A reserve price is set and a tender launched
4. Developer bids; Sale Committee votes to accept
5. Strata Titles Board approves if 80% threshold met
6. Completion typically 12–24 months after CSC formation

**Key risk:** Minority owners (the 20%) can object but cannot block once 80% threshold is met — subject to STB review.
""")

# ── Property Comparison Tool ──────────────────────────────────────────────────
elif tab_select == "⚖️ Compare":
    st.header("⚖️ Property Comparison")
    st.markdown(
        "*Compare up to 3 HDB or private properties side-by-side — valuation, yield, stamp duty and mortgage cost.*"
    )

    from data.hdb_pipeline import get_town_stats
    from data.stamp_duty import full_stamp_duty
    _mort_agent = MortgageAgent()
    def calc_mortgage(price, loan, tenure, rate, cpf): return _mort_agent.calculate(price, loan, tenure, rate, cpf)

    n_props = st.radio("Number of properties to compare", [2, 3], horizontal=True)

    # ── Input columns ──────────────────────────────────────────────────────────
    cols = st.columns(n_props)
    props = []
    for i, col in enumerate(cols):
        with col:
            st.subheader(f"Property {i+1}")
            p_type = st.selectbox("Type", ["HDB Resale", "Private Condo/Apt"], key=f"cmp_type_{i}")
            if p_type == "HDB Resale":
                towns_cmp = sorted(set(r['town'] for r in _cached_hdb_records()))
                p_town = st.selectbox("Town", towns_cmp, key=f"cmp_town_{i}",
                    index=towns_cmp.index("TAMPINES") if "TAMPINES" in towns_cmp else 0)
                p_flat = st.selectbox("Flat Type", ["3 ROOM","4 ROOM","5 ROOM","EXECUTIVE"], key=f"cmp_flat_{i}")
                p_area = st.number_input("Area (sqft)", 400, 2000, 1000, key=f"cmp_area_{i}")
                p_price = st.number_input("Asking Price (SGD)", 100000, 2000000, 550000, step=5000, key=f"cmp_price_{i}")
                p_district = 0
            else:
                p_town = ""
                p_flat = ""
                p_district = st.number_input("District", 1, 28, 9, key=f"cmp_dist_{i}")
                p_area = st.number_input("Area (sqft)", 300, 5000, 1000, key=f"cmp_area_{i}")
                p_price = st.number_input("Asking Price (SGD)", 300000, 10000000, 1500000, step=10000, key=f"cmp_price_{i}")
                p_flat = ""
            p_profile = st.selectbox("Buyer Profile", ["SC", "SPR", "Foreigner"], key=f"cmp_profile_{i}")
            p_prop_count = st.number_input("Nth property (1=first)", 1, 3, 1, key=f"cmp_cnt_{i}")
            p_income = st.number_input("Gross Monthly Income (SGD)", 0, 50000, 8000, step=500, key=f"cmp_inc_{i}")
            props.append({
                "type": p_type, "town": p_town, "flat": p_flat,
                "district": p_district, "area": p_area, "price": p_price,
                "profile": p_profile, "prop_count": p_prop_count, "income": p_income,
                "label": f"{'D'+str(p_district) if p_district else p_town} {p_flat or 'Condo'} #{i+1}",
            })

    if st.button("Compare Properties", type="primary"):
        import pandas as pd
        st.divider()

        # Build comparison rows
        metrics = {
            "Asking Price (SGD)": [],
            "PSF (SGD)": [],
            "Estimated Market Value (SGD)": [],
            "vs Market (%)": [],
            "BSD (SGD)": [],
            "ABSD (SGD)": [],
            "Total Stamp Duty (SGD)": [],
            "Min Cash Down (SGD)": [],
            "Monthly Mortgage @3.5% 25yr (SGD)": [],
            "TDSR (%)": [],
            "Est. Gross Rental Yield (%)": [],
        }

        # Benchmark rents by town (HDB)
        _COMP_RENT = {
            "ANG MO KIO": {"3 ROOM": 2300,"4 ROOM": 2800,"5 ROOM": 3200,"EXECUTIVE": 3500},
            "BEDOK": {"3 ROOM": 2200,"4 ROOM": 2700,"5 ROOM": 3100,"EXECUTIVE": 3400},
            "BISHAN": {"3 ROOM": 2400,"4 ROOM": 3000,"5 ROOM": 3400,"EXECUTIVE": 3700},
            "BUKIT BATOK": {"3 ROOM": 2100,"4 ROOM": 2600,"5 ROOM": 3000,"EXECUTIVE": 3300},
            "BUKIT MERAH": {"3 ROOM": 2600,"4 ROOM": 3200,"5 ROOM": 3700,"EXECUTIVE": 4000},
            "BUKIT PANJANG": {"3 ROOM": 2000,"4 ROOM": 2500,"5 ROOM": 2900,"EXECUTIVE": 3200},
            "CENTRAL AREA": {"3 ROOM": 3200,"4 ROOM": 4200,"5 ROOM": 5000,"EXECUTIVE": 5500},
            "CHOA CHU KANG": {"3 ROOM": 2000,"4 ROOM": 2500,"5 ROOM": 2900,"EXECUTIVE": 3200},
            "CLEMENTI": {"3 ROOM": 2400,"4 ROOM": 2900,"5 ROOM": 3400,"EXECUTIVE": 3700},
            "GEYLANG": {"3 ROOM": 2200,"4 ROOM": 2800,"5 ROOM": 3200,"EXECUTIVE": 3500},
            "HOUGANG": {"3 ROOM": 2100,"4 ROOM": 2600,"5 ROOM": 3000,"EXECUTIVE": 3300},
            "JURONG EAST": {"3 ROOM": 2200,"4 ROOM": 2700,"5 ROOM": 3100,"EXECUTIVE": 3400},
            "JURONG WEST": {"3 ROOM": 2100,"4 ROOM": 2600,"5 ROOM": 3000,"EXECUTIVE": 3300},
            "KALLANG/WHAMPOA": {"3 ROOM": 2500,"4 ROOM": 3100,"5 ROOM": 3600,"EXECUTIVE": 3900},
            "MARINE PARADE": {"3 ROOM": 2600,"4 ROOM": 3200,"5 ROOM": 3700,"EXECUTIVE": 4000},
            "PASIR RIS": {"3 ROOM": 2100,"4 ROOM": 2600,"5 ROOM": 3000,"EXECUTIVE": 3300},
            "PUNGGOL": {"3 ROOM": 2100,"4 ROOM": 2600,"5 ROOM": 3000,"EXECUTIVE": 3300},
            "QUEENSTOWN": {"3 ROOM": 2700,"4 ROOM": 3400,"5 ROOM": 3900,"EXECUTIVE": 4200},
            "SEMBAWANG": {"3 ROOM": 1900,"4 ROOM": 2400,"5 ROOM": 2800,"EXECUTIVE": 3100},
            "SENGKANG": {"3 ROOM": 2100,"4 ROOM": 2600,"5 ROOM": 3000,"EXECUTIVE": 3300},
            "SERANGOON": {"3 ROOM": 2300,"4 ROOM": 2900,"5 ROOM": 3300,"EXECUTIVE": 3600},
            "TAMPINES": {"3 ROOM": 2200,"4 ROOM": 2700,"5 ROOM": 3100,"EXECUTIVE": 3400},
            "TOA PAYOH": {"3 ROOM": 2400,"4 ROOM": 3000,"5 ROOM": 3500,"EXECUTIVE": 3800},
            "WOODLANDS": {"3 ROOM": 1900,"4 ROOM": 2400,"5 ROOM": 2800,"EXECUTIVE": 3100},
            "YISHUN": {"3 ROOM": 2000,"4 ROOM": 2500,"5 ROOM": 2900,"EXECUTIVE": 3200},
        }
        # Private condo yield benchmarks by district (gross %)
        _PRIV_YIELD = {1:3.0,2:3.2,3:3.1,4:3.3,5:3.0,6:2.8,7:3.2,8:3.3,
                       9:2.9,10:2.8,11:2.9,12:3.3,13:3.4,14:3.4,15:3.3,16:3.2,
                       17:3.5,18:3.5,19:3.4,20:3.2,21:3.1,22:3.5,23:3.3,
                       24:3.3,25:3.4,26:3.3,27:3.3,28:3.4}

        prop_labels = []
        for p in props:
            prop_labels.append(p["label"])
            price = p["price"]
            area = p["area"]
            psf = round(price / area, 0) if area else 0

            # Stamp duty
            sd = full_stamp_duty(price, p["profile"], p["prop_count"], p["type"] == "HDB Resale")
            loan = sd["max_loan_sgd"]
            cash_down = sd["min_cash_downpayment_sgd"]

            # Mortgage
            mort = calc_mortgage(price, loan, 25, 3.5, 0)
            monthly = mort.get("monthly_repayment_sgd", 0)
            tdsr = round(monthly / p["income"] * 100, 1) if p["income"] else 0

            # Market value estimate (simple)
            if p["type"] == "HDB Resale" and p["town"]:
                stats = get_town_stats(p["town"], p["flat"])
                est_val = stats.get("median_price", price)
                rent_est = _COMP_RENT.get(p["town"].upper(), {}).get(p["flat"], 0)
                gross_y = round(rent_est * 12 / price * 100, 2) if rent_est and price else 0
            else:
                est_val = price  # use asking price as proxy when no URA data
                gross_y = _PRIV_YIELD.get(p["district"], 3.2)

            vs_mkt = round((price - est_val) / est_val * 100, 1) if est_val else 0

            metrics["Asking Price (SGD)"].append(f"${price:,.0f}")
            metrics["PSF (SGD)"].append(f"${psf:,.0f}")
            metrics["Estimated Market Value (SGD)"].append(f"${est_val:,.0f}")
            metrics["vs Market (%)"].append(f"{vs_mkt:+.1f}%")
            metrics["BSD (SGD)"].append(f"${sd['bsd']['total_bsd_sgd']:,.0f}")
            metrics["ABSD (SGD)"].append(f"${sd['absd']['total_absd_sgd']:,.0f}")
            metrics["Total Stamp Duty (SGD)"].append(f"${sd['total_stamp_duty_sgd']:,.0f}")
            metrics["Min Cash Down (SGD)"].append(f"${cash_down:,.0f}")
            metrics["Monthly Mortgage @3.5% 25yr (SGD)"].append(f"${monthly:,.0f}")
            metrics["TDSR (%)"].append(f"{tdsr:.1f}%" + (" ⚠️" if tdsr > 55 else ""))
            metrics["Est. Gross Rental Yield (%)"].append(f"{gross_y:.2f}%")

        # Render as table
        df_cmp = pd.DataFrame(metrics, index=prop_labels).T
        df_cmp.index.name = "Metric"
        st.dataframe(df_cmp, use_container_width=True)

        # Visual: total upfront cost bar chart
        upfront_costs = []
        for p in props:
            sd2 = full_stamp_duty(p["price"], p["profile"], p["prop_count"], p["type"] == "HDB Resale")
            upfront_costs.append(sd2["total_upfront_cash_sgd"])
        st.subheader("Total Upfront Cash Required (Down Payment + Stamp Duties)")
        st.bar_chart(pd.DataFrame({"Upfront Cash (SGD)": upfront_costs}, index=prop_labels))

        # Winner highlights
        st.subheader("Quick Summary")
        best_yield_idx = max(range(len(props)), key=lambda i: _PRIV_YIELD.get(props[i]["district"], 3.2) if props[i]["type"] != "HDB Resale" else (_COMP_RENT.get(props[i]["town"].upper(), {}).get(props[i]["flat"], 0) * 12 / props[i]["price"] * 100 if props[i]["price"] else 0))
        cheapest_idx = min(range(len(props)), key=lambda i: upfront_costs[i])
        st.success(f"**Lowest upfront cash:** Property {cheapest_idx + 1} ({props[cheapest_idx]['label']}) — SGD {upfront_costs[cheapest_idx]:,.0f}")
        st.info(f"**Best estimated yield:** Property {best_yield_idx + 1} ({props[best_yield_idx]['label']})")
        st.caption("TDSR limit is 55%. Red ⚠️ = exceeds limit. Yields are indicative benchmarks, not guaranteed.")

# ── MRT Proximity Map ─────────────────────────────────────────────────────────
elif tab_select == "🗺️ MRT Map":
    st.header("🗺️ Full Property Research Map")
    st.markdown("*Search by project name, HDB address, town or postal code. Overlay MRT lines, hawker centres, malls, schools, parks and live transaction hotspots — all on one map.*")

    from data.mrt_proximity import mrt_score, nearest_mrt, DISTRICT_CENTROIDS, TOWN_CENTROIDS
    from data.amenities import nearest_amenities, HAWKER_CENTRES, SHOPPING_MALLS, PRIMARY_SCHOOLS, PARKS
    import pandas as pd

    # ── Search mode ─────────────────────────────────────────────────────────
    mrt_type = st.radio(
        "Search by", ["🏠 HDB Town", "🏢 Private District", "🔍 Project / Address Search"],
        horizontal=True, key="mrt_search_mode"
    )

    coords = None
    loc_label = ""
    search_project_name = None

    if mrt_type == "🏠 HDB Town":
        town_sel = st.selectbox("Select HDB town", sorted(TOWN_CENTROIDS.keys()), key="mrt_town")
        coords = TOWN_CENTROIDS.get(town_sel)
        loc_label = town_sel

    elif mrt_type == "🏢 Private District":
        dist_sel = st.number_input("District (1–28)", 1, 28, 9, key="mrt_dist")
        coords = DISTRICT_CENTROIDS.get(int(dist_sel))
        loc_label = f"District {dist_sel}"

    else:
        # Project/Address search — OneMap API for postal codes, URA cache for project names
        st.caption("Type a condo/HDB project name (e.g. 'The Interlace', 'Parc Clematis') or exact 6-digit postal code.")
        addr_query = st.text_input("Project name or postal code", placeholder="e.g. Katong Regency or 439970", key="mrt_addr_q")

        _found_coords = None

        if addr_query and len(addr_query) >= 3:
            _q = addr_query.strip()

            # ── Path A: 6-digit postal code → OneMap API (exact geocode) ──────
            if _q.isdigit() and len(_q) == 6:
                try:
                    import requests as _req
                    _om_url = (
                        f"https://www.onemap.gov.sg/api/common/elastic/search"
                        f"?searchVal={_q}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
                    )
                    _om_resp = _req.get(_om_url, timeout=5)
                    _om_data = _om_resp.json()
                    _om_results = _om_data.get("results", [])
                    if _om_results:
                        _r0 = _om_results[0]
                        _found_coords = (float(_r0["LATITUDE"]), float(_r0["LONGITUDE"]))
                        _addr_str = _r0.get("ADDRESS", _q)
                        _bld_name = _r0.get("BLK_NO", "") + " " + _r0.get("ROAD_NAME", "")
                        loc_label = _r0.get("BUILDING","").title() or _bld_name.title() or _addr_str
                        st.success(f"📍 **{loc_label}** · {_addr_str}")
                    else:
                        st.warning(f"Postal code {_q} not found on OneMap. Try the project name instead.")
                except Exception as _oe:
                    st.warning(f"Postal lookup failed: {_oe}")

            # ── Path B: project name → URA transaction cache ──────────────────
            if not _found_coords:
                try:
                    from data.svy21 import svy21_to_wgs84
                    _all_txns = _cached_ura_transactions()
                    _q_lower = _q.lower()
                    _matched = [t for t in _all_txns if _q_lower in t.get("project", "").lower()]
                    if _matched:
                        _m = _matched[0]
                        _x = float(_m.get("x", "0") or 0)
                        _y = float(_m.get("y", "0") or 0)
                        if _x > 0 and _y > 0:
                            _found_coords = svy21_to_wgs84(_x, _y)
                        else:
                            _d = int(_m.get("district", 9) or 9)
                            _found_coords = DISTRICT_CENTROIDS.get(_d, (1.3521, 103.8198))
                        loc_label = _m.get("project", _q).title()
                        search_project_name = _m.get("project", "")
                        st.success(f"📍 **{loc_label}** (from URA transactions cache)")

                        # Show matching projects if multiple
                        _uniq_projects = sorted({t.get("project","") for t in _matched if t.get("project")})
                        if len(_uniq_projects) > 1:
                            with st.expander(f"🔎 {len(_uniq_projects)} matching projects — click to refine"):
                                _sel_proj = st.selectbox("Select project", _uniq_projects, key="mrt_proj_sel")
                                _proj_txns = [t for t in _all_txns if t.get("project","") == _sel_proj]
                                if _proj_txns:
                                    _pt = _proj_txns[0]
                                    _px, _py = float(_pt.get("x","0") or 0), float(_pt.get("y","0") or 0)
                                    if _px > 0 and _py > 0:
                                        _found_coords = svy21_to_wgs84(_px, _py)
                                    loc_label = _sel_proj.title()
                    else:
                        if not (_q.isdigit() and len(_q) == 6):
                            st.warning(f"No URA transactions found for '{_q}'. Try a shorter keyword or exact postal code.")
                except Exception as _ue:
                    if not _found_coords:
                        st.caption(f"Project search: {_ue}")

        if _found_coords:
            coords = _found_coords
        elif addr_query:
            coords = (1.3521, 103.8198)
            loc_label = "Singapore (default)"

    if coords is None:
        coords = (1.3521, 103.8198)
        loc_label = "Singapore"

    # ── Overlay toggles ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("**🗂️ Map Overlays**")
    ov_cols = st.columns(6)
    show_mrt      = ov_cols[0].checkbox("🚇 MRT", value=True,  key="ov_mrt")
    show_hawker   = ov_cols[1].checkbox("🍜 Hawker", value=False, key="ov_hawker")
    show_mall     = ov_cols[2].checkbox("🛍️ Mall", value=False, key="ov_mall")
    show_school   = ov_cols[3].checkbox("🏫 School", value=False, key="ov_school")
    show_park     = ov_cols[4].checkbox("🌳 Park", value=False, key="ov_park")
    show_txn      = ov_cols[5].checkbox("💰 Transactions", value=False, key="ov_txn")

    # Radius filter for amenities
    radius_km = st.slider("Show amenities within (km)", 0.5, 5.0, 2.0, 0.5, key="ov_radius")

    # ── Transaction filters (shown only when Transactions overlay is on) ──────
    if show_txn:
        with st.expander("🔧 Transaction Filters & Display", expanded=True):
            _tf_c1, _tf_c2, _tf_c3, _tf_c4 = st.columns(4)
            with _tf_c1:
                _txn_psf_min, _txn_psf_max = st.slider(
                    "PSF Range (SGD)", 200, 5000, (500, 3000), step=100, key="txn_psf_range"
                )
            with _tf_c2:
                _txn_type = st.selectbox(
                    "Property Type", ["All", "Condominium", "Apartment", "Executive Condominium", "HDB Resale"],
                    key="txn_type_filter"
                )
            with _tf_c3:
                _txn_date_from = st.selectbox(
                    "From Year", list(range(2015, date.today().year + 1)),
                    index=5, key="txn_year_from"
                )
            with _tf_c4:
                _txn_colour_by = st.radio(
                    "Colour dots by",
                    ["PSF", "Price", "Age (year)"],
                    horizontal=True, key="txn_colour_by"
                )
    else:
        _txn_psf_min, _txn_psf_max = 0, 99999
        _txn_type = "All"
        _txn_date_from = 2015
        _txn_colour_by = "PSF"

    # ── MRT connectivity stats ───────────────────────────────────────────────
    stations = nearest_mrt(coords[0], coords[1], top_n=8)
    if stations:
        score = mrt_score(stations)
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Nearest MRT", stations[0]["station"])
        sc2.metric("Distance", f"{stations[0]['distance_m']:,} m")
        sc3.metric("Connectivity Score", f"{score}/100",
                   delta="Excellent" if score >= 80 else "Good" if score >= 60 else "Fair" if score >= 40 else "Poor",
                   delta_color="normal")

    # ── Nearest amenities table ───────────────────────────────────────────────
    _active_layers = []
    if show_mrt:     _active_layers.append("mrt")
    if show_hawker:  _active_layers.append("hawker")
    if show_mall:    _active_layers.append("mall")
    if show_school:  _active_layers.append("school")
    if show_park:    _active_layers.append("park")

    if len(_active_layers) > 1 or (len(_active_layers) == 1 and _active_layers[0] != "mrt"):
        _label_map = {"hawker":"🍜 Hawker Centre","mall":"🛍️ Shopping Mall","school":"🏫 Primary School","park":"🌳 Park"}
        for _layer in [l for l in _active_layers if l != "mrt"]:
            _nearby = [a for a in nearest_amenities(coords[0], coords[1], _layer, top_n=20)
                       if a["distance_m"] <= radius_km * 1000]
            if _nearby:
                with st.expander(f"{_label_map[_layer]}s within {radius_km:.0f} km — {len(_nearby)} found"):
                    _df_am = pd.DataFrame([
                        {"Name": a["name"], "Distance": f"{a['distance_m']:,} m", "Walk": f"{a['walk_min']} min"}
                        for a in _nearby
                    ])
                    st.dataframe(_df_am, hide_index=True, use_container_width=True)

    # ── Folium interactive map ─────────────────────────────────────────────
    st.subheader(f"📍 {loc_label}")
    try:
        import folium
        from folium.plugins import HeatMap, MarkerCluster
        from streamlit_folium import st_folium

        _zoom = 15 if mrt_type == "🔍 Project / Address Search" else 14
        m = folium.Map(location=list(coords), zoom_start=_zoom, tiles="CartoDB positron")

        # — Centre pin -------------------------------------------------------
        folium.Marker(
            list(coords), popup=f"<b>{loc_label}</b>",
            tooltip=loc_label,
            icon=folium.Icon(color="red", icon="home", prefix="fa")
        ).add_to(m)

        # — MRT overlay -------------------------------------------------------
        if show_mrt:
            from data.mrt_data import MRT_STATIONS, LINE_COLORS
            _mrt_cluster = MarkerCluster(name="MRT Stations", show=True).add_to(m)
            for stn_name, stn_line, stn_lat, stn_lon, stn_dist in MRT_STATIONS:
                _dist = ((stn_lat - coords[0])**2 + (stn_lon - coords[1])**2) ** 0.5 * 111320
                _color_key = stn_line.split("/")[0][:2]
                _hex = LINE_COLORS.get(_color_key, "#888888")
                folium.CircleMarker(
                    [stn_lat, stn_lon], radius=7,
                    color=_hex, fill=True, fill_color=_hex, fill_opacity=0.9,
                    popup=f"<b>{stn_name}</b><br>{stn_line}",
                    tooltip=f"{stn_name} ({stn_line})"
                ).add_to(_mrt_cluster)
            # Lines from centre to nearby MRTs
            for s in stations[:5]:
                if s["distance_m"] <= radius_km * 1000:
                    folium.PolyLine(
                        [list(coords), [s["lat"], s["lon"]]],
                        color=s["color"], weight=2, opacity=0.7, dash_array="6"
                    ).add_to(m)

        # — Hawker overlay ---------------------------------------------------
        if show_hawker:
            _h_cluster = MarkerCluster(name="Hawker Centres", show=True).add_to(m)
            for name, lat, lon in HAWKER_CENTRES:
                _d = ((lat - coords[0])**2 + (lon - coords[1])**2)**0.5 * 111320
                if _d <= radius_km * 1000:
                    folium.Marker(
                        [lat, lon],
                        popup=f"<b>🍜 {name}</b><br>{_d/1000:.2f} km away",
                        tooltip=name,
                        icon=folium.Icon(color="orange", icon="cutlery", prefix="fa")
                    ).add_to(_h_cluster)

        # — Mall overlay -----------------------------------------------------
        if show_mall:
            _m_cluster = MarkerCluster(name="Shopping Malls", show=True).add_to(m)
            for name, lat, lon in SHOPPING_MALLS:
                _d = ((lat - coords[0])**2 + (lon - coords[1])**2)**0.5 * 111320
                if _d <= radius_km * 1000:
                    folium.Marker(
                        [lat, lon],
                        popup=f"<b>🛍️ {name}</b><br>{_d/1000:.2f} km away",
                        tooltip=name,
                        icon=folium.Icon(color="purple", icon="shopping-bag", prefix="fa")
                    ).add_to(_m_cluster)

        # — School overlay ---------------------------------------------------
        if show_school:
            _s_cluster = MarkerCluster(name="Primary Schools", show=True).add_to(m)
            for name, lat, lon in PRIMARY_SCHOOLS:
                _d = ((lat - coords[0])**2 + (lon - coords[1])**2)**0.5 * 111320
                if _d <= radius_km * 1000:
                    folium.Marker(
                        [lat, lon],
                        popup=f"<b>🏫 {name}</b><br>{_d/1000:.2f} km away",
                        tooltip=name,
                        icon=folium.Icon(color="green", icon="graduation-cap", prefix="fa")
                    ).add_to(_s_cluster)

        # — Park overlay -----------------------------------------------------
        if show_park:
            for name, lat, lon in PARKS:
                _d = ((lat - coords[0])**2 + (lon - coords[1])**2)**0.5 * 111320
                if _d <= radius_km * 1000:
                    folium.Marker(
                        [lat, lon],
                        popup=f"<b>🌳 {name}</b>",
                        tooltip=name,
                        icon=folium.Icon(color="darkgreen", icon="tree", prefix="fa")
                    ).add_to(m)

        # — Transaction heatmap overlay (with filters) -----------------------
        if show_txn:
            try:
                from data.svy21 import svy21_to_wgs84
                _all_txns = _cached_ura_transactions()
                _heat_pts  = []
                _txn_markers = []
                _rad_m = radius_km * 1000
                _filtered_count = 0

                # Colour helper based on selected mode
                def _txn_dot_color(t, mode):
                    if mode == "PSF":
                        p = float(t.get("psf","0") or t.get("unitPrice","0") or 0)
                        return ("darkred" if p >= 2500 else "red" if p >= 2000 else
                                "orange" if p >= 1500 else "blue" if p >= 1000 else "lightblue")
                    elif mode == "Price":
                        p = float(t.get("price","0") or t.get("transactionPrice","0") or 0)
                        return ("darkred" if p >= 3_000_000 else "red" if p >= 1_500_000 else
                                "orange" if p >= 800_000 else "blue" if p >= 400_000 else "lightblue")
                    else:  # Age (year)
                        d = str(t.get("contractDate","") or t.get("saleDate",""))
                        yr = int(d[-4:]) if len(d) >= 4 and d[-4:].isdigit() else \
                             int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else 2020
                        return ("darkred" if yr >= 2023 else "orange" if yr >= 2020 else
                                "blue" if yr >= 2017 else "lightblue")

                for _t in _all_txns:
                    try:
                        _x = float(_t.get("x","0") or 0)
                        _y = float(_t.get("y","0") or 0)
                        if _x > 0 and _y > 0:
                            _tlat, _tlon = svy21_to_wgs84(_x, _y)
                        else:
                            continue
                        _d = ((_tlat - coords[0])**2 + (_tlon - coords[1])**2)**0.5 * 111320
                        if _d > _rad_m:
                            continue

                        # ── Apply filters ──────────────────────────────────
                        _psf   = float(_t.get("psf","0") or _t.get("unitPrice","0") or 0)
                        _price = float(_t.get("price","0") or _t.get("transactionPrice","0") or 0)
                        _ptype = str(_t.get("propertyType","") or _t.get("property_type","")).lower()

                        if _psf < _txn_psf_min or (_psf > _txn_psf_max and _psf > 0):
                            continue
                        if _txn_type != "All" and _txn_type.lower() not in _ptype:
                            continue
                        # Date filter
                        _date_str = str(_t.get("contractDate","") or _t.get("saleDate",""))
                        _yr = 0
                        if "/" in _date_str and len(_date_str) >= 7:
                            try: _yr = int(_date_str[-4:])
                            except: pass
                        elif len(_date_str) >= 4 and _date_str[:4].isdigit():
                            _yr = int(_date_str[:4])
                        if _yr > 0 and _yr < _txn_date_from:
                            continue

                        # Estimate rental yield: PSF × area × 4.5% / 12 → monthly rent
                        _area  = float(_t.get("area","0") or _t.get("floorArea","0") or 0)
                        _est_rent = round(_psf * _area * 0.045 / 12) if _psf and _area else 0
                        _est_yield = round(_psf * _area * 0.045 / _price * 100, 1) if _price and _psf and _area else 0

                        _heat_pts.append([_tlat, _tlon, min(_psf / 3000, 1.0)])
                        _filtered_count += 1
                        if len(_txn_markers) < 80:
                            _txn_markers.append((_tlat, _tlon, _t, _psf, _price, _est_rent, _est_yield))
                    except Exception:
                        continue

                if _heat_pts:
                    HeatMap(_heat_pts, radius=18, blur=14, min_opacity=0.3).add_to(m)

                _txn_cluster = MarkerCluster(name="Transactions", show=True).add_to(m)
                for _tlat, _tlon, _t, _psf, _price, _est_rent, _est_yield in _txn_markers[:80]:
                    _proj  = (_t.get("project","") or "").title()
                    _area  = _t.get("area","") or _t.get("floorArea","")
                    _ptype_str = (_t.get("propertyType","") or "").title()
                    _date_str  = _t.get("contractDate","") or _t.get("saleDate","")
                    _popup_html = (
                        f"<div style='min-width:180px'>"
                        f"<b style='font-size:13px'>{_proj or _ptype_str}</b><br>"
                        f"<span style='color:#c0392b;font-weight:700'>PSF: ${_psf:,.0f}</span><br>"
                        f"Price: SGD {_price:,.0f}<br>"
                        + (f"Area: {_area} sqft<br>" if _area else "")
                        + (f"<span style='color:#27ae60'>Est. rent: ~${_est_rent:,}/mo · yield ~{_est_yield}%</span><br>" if _est_rent else "")
                        + f"Date: {_date_str}<br>"
                        f"Type: {_ptype_str}"
                        f"</div>"
                    )
                    _dot_color = _txn_dot_color(_t, _txn_colour_by)
                    folium.CircleMarker(
                        [_tlat, _tlon], radius=5,
                        color=_dot_color, fill=True, fill_color=_dot_color, fill_opacity=0.75,
                        popup=folium.Popup(_popup_html, max_width=240),
                        tooltip=f"{_proj or _ptype_str} — ${_psf:,.0f} psf"
                    ).add_to(_txn_cluster)

                if _heat_pts:
                    st.caption(f"💰 {_filtered_count:,} transactions in range match your filters.")
                else:
                    st.caption("No transactions found in range — try widening the radius or adjusting PSF filters.")
            except Exception as _te:
                st.caption(f"Transaction overlay error: {_te}")

        folium.LayerControl().add_to(m)
        # returned_objects=[] → map sends NO data back to Streamlit on load/interaction.
        # This prevents st_folium from triggering reruns that reset the nav radio state.
        # key= stabilises the component identity so Streamlit doesn't re-mount it.
        st_folium(m, height=520, use_container_width=True,
                  returned_objects=[], key="propos_main_map")

        # Legend
        _legend_items = []
        if show_mrt:      _legend_items.append("🔵 MRT station · dashed line = walking distance")
        if show_hawker:   _legend_items.append("🟠 Hawker centre")
        if show_mall:     _legend_items.append("🟣 Shopping mall")
        if show_school:   _legend_items.append("🟢 Primary school")
        if show_park:     _legend_items.append("🌿 Park / nature reserve")
        if show_txn:
            if _txn_colour_by == "PSF":
                _legend_items.append("💰 Dot colour by PSF: 🔴 ≥$2.5k · 🟠 ≥$2k · 🟡 ≥$1.5k · 🔵 ≥$1k · 💠 <$1k | heatmap = density")
            elif _txn_colour_by == "Price":
                _legend_items.append("💰 Dot colour by Price: 🔴 ≥$3M · 🟠 ≥$1.5M · 🟡 ≥$800k · 🔵 ≥$400k · 💠 <$400k")
            else:
                _legend_items.append("💰 Dot colour by Year: 🔴 ≥2023 · 🟠 ≥2020 · 🔵 ≥2017 · 💠 earlier | popup shows est. yield")
        if _legend_items:
            st.caption("  ·  ".join(_legend_items))

    except ImportError:
        st.info("Interactive map requires `folium` and `streamlit-folium`. Install on VPS: `pip install folium streamlit-folium`")
        # Fallback: MRT table
        if stations:
            rows = []
            for s in stations:
                rows.append({
                    "Station": s["station"],
                    "Line": s["line"],
                    "Distance": f"{s['distance_m']:,} m",
                    "Walk Time": s["walk_label"],
                    "Walkable": "✅" if s["distance_m"] <= 800 else "🚌" if s["distance_m"] <= 1500 else "🚗",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.caption("Walk speed: 80 m/min (~4.8 km/h). Straight-line distance — actual walk may be longer.")

    # MRT scoring context
    with st.expander("📖 What does the Connectivity Score mean?"):
        st.markdown("""
| Score | Rating | Meaning |
|---|---|---|
| 80–100 | 🟢 Excellent | ≤400m walk to MRT — premium connectivity, commands higher resale/rental |
| 60–79 | 🟡 Good | ≤800m walk — comfortable, most buyers/tenants accept this |
| 40–59 | 🟠 Fair | ≤1,200m walk — bus/bicycle often needed |
| <40 | 🔴 Poor | >1,200m — car-dependent, negative impact on yield and resale |

**Rule of thumb:** Each additional 100m from MRT reduces rental yield by ~0.05–0.1% and resale premium by ~1–2%.
**School proximity** adds 5–15% premium to resale prices in primary school P1 registration zones.
**Hawker centre within 500m** correlates with higher HDB rental demand (+3–7% yield).
        """)

# ── Portfolio Tracker ──────────────────────────────────────────────────────────
elif tab_select == "💼 Portfolio":
    st.header("💼 My Property Portfolio")
    st.markdown("*Track your owned properties, monitor unrealised gains, CPF accrued interest and net equity in one place.*")

    from data.portfolio_tracker import (
        ensure_schema as pt_schema, add_property, get_portfolio,
        delete_property, update_valuation, analyse_property, portfolio_summary
    )
    pt_schema()
    import pandas as pd

    _pt_user = st.text_input(
        "Your Telegram ID (to save your portfolio)",
        value=str(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")),
        placeholder="e.g. 1245366658", key="pt_user"
    )

    pt_tab1, pt_tab2 = st.tabs(["📋 My Properties", "➕ Add Property"])

    with pt_tab2:
        st.subheader("Add a property to your portfolio")
        pc1, pc2 = st.columns(2)
        with pc1:
            pt_name = st.text_input("Property name / address", key="pt_name", placeholder="Tampines St 45 Blk 123 #08-12")
            pt_ptype = st.selectbox("Type", ["HDB Resale", "BTO", "Private Condo/Apt", "EC", "Landed"], key="pt_ptype")
            pt_town = st.text_input("Town / District", key="pt_town", placeholder="TAMPINES or D15")
            pt_flat = st.selectbox("Flat Type (HDB)", ["", "3 ROOM","4 ROOM","5 ROOM","EXECUTIVE","N/A"], key="pt_flat")
        with pc2:
            pt_price = st.number_input("Purchase Price (SGD)", 100000, 10000000, 500000, step=10000, key="pt_price")
            pt_date = st.date_input("Purchase / Key Collection Date", key="pt_date")
            pt_loan = st.number_input("Loan Amount (SGD)", 0, 8000000, 400000, step=10000, key="pt_loan")
            pt_rate = st.number_input("Interest Rate (%)", 0.5, 8.0, 3.5, step=0.1, key="pt_rate")
        pc3, pc4 = st.columns(2)
        with pc3:
            pt_tenure = st.number_input("Loan Tenure (years)", 5, 30, 25, key="pt_tenure")
            pt_cpf = st.number_input("CPF Used (SGD)", 0, 3000000, 0, step=5000, key="pt_cpf")
        with pc4:
            pt_cur_val = st.number_input("Current Est. Value (SGD)", 100000, 10000000, 550000, step=10000, key="pt_curval",
                                          help="Your best estimate or latest valuation. You can update this anytime.")
            pt_rent = st.number_input("Monthly Rent Received (0 if owner-occupied)", 0, 20000, 0, step=100, key="pt_rent")
        pt_notes = st.text_area("Notes (optional)", key="pt_notes")

        if st.button("Save to Portfolio", type="primary", key="pt_save"):
            if not _pt_user:
                st.warning("Enter your Telegram ID above to save.")
            elif not pt_name:
                st.warning("Enter a property name.")
            else:
                add_property(
                    telegram_id=_pt_user, property_name=pt_name,
                    property_type=pt_ptype, town_or_district=pt_town,
                    flat_type=pt_flat, purchase_price=pt_price,
                    purchase_date=str(pt_date), loan_amount=pt_loan,
                    annual_rate_pct=pt_rate, tenure_years=pt_tenure,
                    cpf_used=pt_cpf, current_est_value=pt_cur_val,
                    monthly_rent_sgd=pt_rent, notes=pt_notes
                )
                st.success(f"✅ {pt_name} added to your portfolio!")
                st.rerun()

    with pt_tab1:
        if not _pt_user:
            st.info("Enter your Telegram ID above to view your portfolio.")
        else:
            summary = portfolio_summary(_pt_user)
            if summary["count"] == 0:
                st.info("No properties yet. Go to **➕ Add Property** to track your first property.")
            else:
                # Portfolio KPIs
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Properties", summary["count"])
                k2.metric("Total Value", f"SGD {summary['total_current_value']:,.0f}")
                k3.metric("Total Gain", f"SGD {summary['total_capital_gain']:,.0f}",
                          delta=f"{summary['total_gain_pct']:+.1f}%")
                k4.metric("Net Equity", f"SGD {summary['total_net_equity']:,.0f}")
                k5.metric("Outstanding Loans", f"SGD {summary['total_outstanding_loans']:,.0f}")

                if summary.get("total_rental_income", 0) > 0:
                    st.metric("Total Rental Income (all time)", f"SGD {summary['total_rental_income']:,.0f}")
                    st.metric("Total Return (capital + rent)", f"SGD {summary['total_return']:,.0f}")

                st.divider()

                # Per-property cards
                for prop in summary["properties"]:
                    with st.expander(f"🏠 {prop['property_name']} — {prop['property_type']}", expanded=True):
                        p1, p2, p3, p4 = st.columns(4)
                        p1.metric("Purchase Price", f"SGD {prop['purchase_price']:,.0f}")
                        p2.metric("Current Value", f"SGD {prop['current_value']:,.0f}")
                        p3.metric("Capital Gain", f"SGD {prop['capital_gain_sgd']:,.0f}",
                                  delta=f"{prop['gain_pct']:+.1f}% · {prop['annual_appreciation_pct']:+.1f}%/yr")
                        p4.metric("Net Equity", f"SGD {prop['net_equity']:,.0f}")

                        p5, p6, p7, p8 = st.columns(4)
                        p5.metric("Outstanding Loan", f"SGD {prop['outstanding_loan']:,.0f}")
                        p6.metric("Monthly Payment", f"SGD {prop['monthly_payment']:,.0f}")
                        if prop["cpf_used"] > 0:
                            p7.metric("CPF to Refund on Sale", f"SGD {prop['cpf_to_refund']:,.0f}",
                                      help="CPF principal + 2.5% p.a. accrued interest — must be refunded to CPF OA when you sell")
                        if prop["monthly_rent"] > 0:
                            p8.metric("Gross Yield", f"{prop['gross_yield_pct']:.2f}%",
                                      delta=f"Net {prop['net_yield_pct']:.2f}%")

                        # Update valuation + delete
                        uc1, uc2, uc3 = st.columns(3)
                        with uc1:
                            new_val = st.number_input("Update current value (SGD)", 100000, 10000000,
                                                       int(prop["current_value"]), step=10000,
                                                       key=f"upd_val_{prop['id']}")
                        with uc2:
                            if st.button("💾 Update Value", key=f"upd_btn_{prop['id']}"):
                                update_valuation(prop["id"], new_val)
                                st.success("Updated!")
                                st.rerun()
                        with uc3:
                            if st.button("🗑️ Remove", key=f"del_{prop['id']}"):
                                delete_property(prop["id"], _pt_user)
                                st.rerun()

                # Portfolio chart
                if summary["count"] > 1:
                    st.divider()
                    st.subheader("Portfolio Breakdown")
                    chart_data = pd.DataFrame({
                        "Current Value": [p["current_value"] for p in summary["properties"]],
                        "Purchase Price": [p["purchase_price"] for p in summary["properties"]],
                    }, index=[p["property_name"][:25] for p in summary["properties"]])
                    st.bar_chart(chart_data, height=250)

# ── CPF Housing Grants Calculator ─────────────────────────────────────────────
elif tab_select == "🎁 CPF Grants":
    st.header("🎁 CPF Housing Grants Calculator")
    st.markdown("*Find out which CPF housing grants you qualify for. Covers EHG, Family Grant, PHG and Step-Up Grant (2024 rules). Zero cost — fully rule-based.*")

    from agents.cpf_grants import calculate_grants_dict
    import pandas as pd

    g1, g2 = st.columns(2)
    with g1:
        cg_applicant = st.selectbox("Applicant type", ["couple", "family", "single"], key="cg_app")
        cg_first_main = st.checkbox("I am a first-timer (never bought subsidised flat)", value=True, key="cg_f1")
        cg_first_partner = st.checkbox("Partner is also a first-timer", value=True, key="cg_f2",
                                        help="Uncheck if partner previously bought HDB / received grant")
        cg_citizenship = st.selectbox("Citizenship status", ["SC+SC","SC+PR","SC_only"], key="cg_cit",
                                       help="SC = Singapore Citizen, PR = Permanent Resident")
    with g2:
        cg_income = st.number_input("Combined monthly household income (SGD)", 0, 30000, 6000, step=500, key="cg_income",
                                     help="Gross monthly salary of all buyers")
        cg_flat_type = st.selectbox("Flat type", ["resale","BTO"], key="cg_ftype")
        cg_flat_size = st.selectbox("Flat size", ["2-room","3-room","4-room","5-room","executive"], key="cg_fsize")
        cg_near = st.checkbox("Buying near / with parents (within 4 km)", key="cg_near")
        cg_same_town = st.checkbox("Same town as parents (live together)", key="cg_town") if cg_near else False

    if st.button("Calculate Grants 🎁", type="primary", key="cg_calc"):
        _gr = calculate_grants_dict(
            applicant_type=cg_applicant,
            first_timer_main=cg_first_main,
            first_timer_partner=cg_first_partner,
            citizenship=cg_citizenship,
            monthly_income=float(cg_income),
            flat_type=cg_flat_type,
            flat_size=cg_flat_size,
            near_parents=cg_near,
            same_town=cg_same_town,
        )
        st.divider()
        ga, gb, gc, gd = st.columns(4)
        ga.metric("EHG", f"${_gr['ehg']:,}" if _gr['ehg'] else "—")
        gb.metric("Family Grant", f"${_gr['family_grant']:,}" if _gr['family_grant'] else "—")
        gc.metric("PHG", f"${_gr['phg']:,}" if _gr['phg'] else "—")
        gd.metric("Step-Up", f"${_gr['step_up']:,}" if _gr['step_up'] else "—")

        if _gr['total'] > 0:
            st.success(f"## 🎉 Total Grants: **SGD {_gr['total']:,}**")
        else:
            st.warning("No grants applicable based on the inputs provided.")

        for _line in _gr['breakdown']:
            st.markdown(_line)

        if _gr['notes']:
            with st.expander("ℹ️ Eligibility notes"):
                for _n in _gr['notes']:
                    st.markdown(f"- {_n}")

        with st.expander("📖 Grant details & conditions"):
            st.markdown("""
**Enhanced CPF Housing Grant (EHG)**
- For first-timer singles (income ≤$4,500) or couples/families (income ≤$9,000)
- Applies to BTO and resale flats
- Up to **$80,000** for couples, **$40,000** for singles
- Grant tapers by $5,000 per $500 income band

**CPF Housing Grant / Family Grant** (resale only)
- Income ceiling: $14,000 (couples/families)
- SC+SC: up to **$50,000** for 3/4-room, $40,000 for 2/5-room
- SC+PR: up to **$40,000** for 3/4-room
- Half-grant for first-timer + second-timer couples

**Proximity Housing Grant (PHG)** (resale only)
- **$30,000** if buying to live with/near parents (same town)
- **$20,000** if buying within 4 km of parents

**Step-Up CPF Housing Grant** (resale, second-timers upgrading from 2-room)
- **$15,000** for 2-room flat residents upgrading, income ≤$7,000
""")

        # Insurance nudge
        st.divider()
        st.info("🛡️ Buying with a grant often means higher ownership pride — protect your investment with MRTA. Head to **🛡️ Insurance** to calculate your coverage needs.")

# ── Rent vs Buy Calculator ─────────────────────────────────────────────────────
elif tab_select == "🏠↔️ Rent vs Buy":
    st.header("🏠↔️ Rent vs Buy Analysis")
    st.markdown("*Should you rent or buy now? Compare the true total cost and net position over your chosen horizon, accounting for mortgage interest, CPF accrued costs, property tax, investment opportunity cost, and appreciation.*")

    from agents.rent_vs_buy import analyse_dict
    import pandas as pd

    rvb1, rvb2 = st.columns(2)
    with rvb1:
        st.subheader("🏠 Property (Buy)")
        rvb_price = st.number_input("Purchase Price (SGD)", 200000, 10000000, 600000, step=10000, key="rvb_price")
        rvb_ftype = st.selectbox("Property type", ["HDB","Condo","EC","Landed"], key="rvb_ftype")
        rvb_first = st.checkbox("First property purchase", value=True, key="rvb_first")
        rvb_sc = st.checkbox("Singapore Citizen (main buyer)", value=True, key="rvb_sc")
        rvb_pr = st.checkbox("Permanent Resident (if not SC)", value=False, key="rvb_pr")
        rvb_down = st.slider("Down payment (%)", 10, 50, 25, 5, key="rvb_down") / 100
        rvb_cpf_frac = st.slider("CPF portion of down payment (%)", 0, 100, 40, 5, key="rvb_cpf") / 100
        rvb_rate = st.number_input("Loan interest rate (%)", 1.0, 6.0, 3.5, 0.1, key="rvb_rate")
        rvb_tenure = st.number_input("Loan tenure (years)", 5, 30, 25, key="rvb_tenure")
        rvb_maint = st.number_input("Monthly maintenance / S&CC (SGD)", 0, 2000, 300, 50, key="rvb_maint")
    with rvb2:
        st.subheader("🏢 Rental Alternative")
        rvb_rent = st.number_input("Comparable monthly rent (SGD, 0 = auto-estimate)", 0, 20000, 0, 100, key="rvb_rent",
                                    help="Leave 0 to auto-estimate at 3.5% gross yield of purchase price")
        st.subheader("📈 Assumptions")
        rvb_years = st.slider("Analysis horizon (years)", 1, 20, 5, key="rvb_years")
        rvb_appr = st.slider("Property appreciation p.a. (%)", 0.0, 8.0, 3.5, 0.5, key="rvb_appr")
        rvb_invest = st.slider("Investment return if renting (%)", 0.0, 10.0, 5.0, 0.5, key="rvb_invest",
                                help="Expected annual return if you invest the down payment + monthly savings instead of buying")

    if st.button("Analyse Now 📊", type="primary", key="rvb_run"):
        _r = analyse_dict(
            purchase_price=float(rvb_price),
            flat_type=rvb_ftype,
            is_first_property=rvb_first,
            is_sc=rvb_sc,
            is_pr=rvb_pr and not rvb_sc,
            down_pmt_pct=float(rvb_down),
            loan_rate_pct=float(rvb_rate),
            loan_tenure_years=int(rvb_tenure),
            cpf_used_pct=float(rvb_cpf_frac),
            monthly_rent=float(rvb_rent),
            years_horizon=int(rvb_years),
            property_appreciation_pct=float(rvb_appr),
            investment_return_pct=float(rvb_invest),
            monthly_maintenance=float(rvb_maint),
        )
        st.divider()

        # Verdict banner
        if _r["buy_wins"]:
            st.success(f"### 🏆 Buy wins  —  ahead by **SGD {abs(_r['delta_sgd']):,.0f}** over {rvb_years} years")
        else:
            st.warning(f"### 📈 Renting ahead  —  by **SGD {abs(_r['delta_sgd']):,.0f}** over {rvb_years} years  (buy breaks even year {_r['breakeven_year']} if appreciation holds)")

        st.markdown(_r["verdict"])

        # Side-by-side metrics
        rvb_c1, rvb_c2 = st.columns(2)
        bd = _r["buy_details"]
        rd = _r["rent_details"]

        with rvb_c1:
            st.subheader("🏠 Buy scenario")
            st.metric("Upfront cash needed", f"SGD {bd.get('upfront_cash_required',0):,.0f}")
            st.metric("Monthly cost (loan+maint+tax)", f"SGD {bd.get('monthly_total',0):,.0f}")
            st.metric("Total interest paid", f"SGD {bd.get('total_interest_paid',0):,.0f}")
            st.metric("Stamp duty (BSD+ABSD)", f"SGD {bd.get('stamp_duty_bsd',0)+bd.get('stamp_duty_absd',0):,.0f}")
            st.metric(f"Property value in {rvb_years}yr", f"SGD {bd.get('future_property_value',0):,.0f}")
            st.metric("Net equity after sale", f"SGD {_r['buy_net_position']:,.0f}")

        with rvb_c2:
            st.subheader("🏢 Rent scenario")
            st.metric("Monthly rent", f"SGD {rd.get('monthly_rent',0):,.0f}")
            st.metric("Total rent paid", f"SGD {rd.get('total_rent_paid',0):,.0f}")
            st.metric("Capital invested (alt)", f"SGD {rd.get('capital_deployed_to_investments',0):,.0f}")
            st.metric("Monthly savings invested", f"SGD {rd.get('monthly_savings_vs_buying',0):,.0f}")
            st.metric(f"Portfolio value in {rvb_years}yr", f"SGD {_r['rent_net_position']:,.0f}")

        # Breakeven chart
        with st.expander("📈 Year-by-year comparison"):
            _chart_rows = []
            for _yr in range(1, min(rvb_years + 5, 21)):
                _yr_r = analyse_dict(
                    purchase_price=float(rvb_price), flat_type=rvb_ftype,
                    is_first_property=rvb_first, is_sc=rvb_sc, is_pr=rvb_pr and not rvb_sc,
                    down_pmt_pct=float(rvb_down), loan_rate_pct=float(rvb_rate),
                    loan_tenure_years=int(rvb_tenure), cpf_used_pct=float(rvb_cpf_frac),
                    monthly_rent=float(rvb_rent), years_horizon=_yr,
                    property_appreciation_pct=float(rvb_appr),
                    investment_return_pct=float(rvb_invest),
                    monthly_maintenance=float(rvb_maint),
                )
                _chart_rows.append({
                    "Year": _yr,
                    "Buy net position (SGD)": _yr_r["buy_net_position"],
                    "Rent portfolio value (SGD)": _yr_r["rent_net_position"],
                })
            _chart_df = pd.DataFrame(_chart_rows).set_index("Year")
            st.line_chart(_chart_df, height=300)
            st.caption("Buy net position = property value − outstanding loan − CPF refund − selling cost. Rent portfolio = invested down payment + monthly savings, compounded.")

        with st.expander("ℹ️ Assumptions"):
            for _a in _r["assumptions"]:
                st.markdown(f"- {_a}")

        # Insurance nudge
        st.divider()
        if _r["buy_wins"] or _r["breakeven_year"] <= 7:
            st.info("🛡️ If buying makes sense, protect your mortgage with MRTA. Head to **🛡️ Insurance** to get a quote.")

# ── Partners ──────────────────────────────────────────────────────────────────
elif tab_select == "🤝 Partners":
    st.header("🤝 Partner with PropOS")
    st.markdown(
        "*PropOS is Singapore's AI-powered property intelligence platform — "
        "reaching buyers, sellers, investors and upgraders at their highest-intent moments.*"
    )

    st.divider()

    # Value proposition cards
    p1, p2, p3 = st.columns(3)
    p1.metric("Monthly Active Users", "Growing", "Early access")
    p2.metric("Coverage", "HDB + Private", "All 28 districts")
    p3.metric("Data Sources", "HDB · URA · News", "Real-time")

    st.divider()
    st.subheader("Partnership Opportunities")

    partner_types = {
        "🏦 Mortgage Brokers & Banks": {
            "pitch": "Users actively compare mortgage rates on our platform at the exact moment they decide to buy or refinance. Your packages appear when intent is highest.",
            "value": "Qualified mortgage leads with property type, loan quantum, and buyer profile already known.",
            "model": "Lead referral fee or CPC placement.",
        },
        "🛡️ Insurance Companies": {
            "pitch": "Every new mortgage, BTO purchase, and property upgrade triggers an insurance review. Our platform surfaces MRTA/MLTA, term life, and home protection gaps to buyers in real time.",
            "value": "Pre-qualified leads with loan amount, tenure, and coverage gap already identified.",
            "model": "Policy referral commission (SGD 500–5,000 per placed policy).",
        },
        "🏠 Property Agents & Agencies": {
            "pitch": "PropOS users are active buyers and sellers in the research phase. Surface your listings and expertise to motivated prospects.",
            "value": "Seller leads approaching MOP, buyer leads with budget and district preferences known.",
            "model": "Featured agent listing, lead subscription, or co-marketing.",
        },
        "💼 Portfolio & Fund Managers": {
            "pitch": "Access aggregated Singapore property market intelligence — district-level yield trends, transaction velocity, sentiment index, and macro indicators — for investment and fund reporting.",
            "value": "Data API access, custom research reports, or white-label intelligence dashboard.",
            "model": "Data licensing or research retainer.",
        },
        "🏗️ Developers & Project Marketing": {
            "pitch": "Reach buyers actively comparing new launches against resale and BTO alternatives. Feature your project at the decision point.",
            "value": "Pre-launch interest capture, BTO vs new launch comparison placement.",
            "model": "Project feature placement or lead generation.",
        },
        "⚖️ Legal & Conveyancing Firms": {
            "pitch": "Every property transaction requires a conveyancing lawyer. Surface your firm at the moment a deal is confirmed.",
            "value": "Transaction-ready leads with property type and deal value known.",
            "model": "Lead referral or directory listing.",
        },
    }

    for ptype, details in partner_types.items():
        with st.expander(ptype):
            st.markdown(f"**Why partner:** {details['pitch']}")
            st.markdown(f"**What you get:** {details['value']}")
            st.markdown(f"**Commercial model:** {details['model']}")

    st.divider()
    st.subheader("📩 Get in Touch")
    st.markdown("""
We are selectively onboarding early partners who want to reach Singapore property buyers and investors at high-intent moments.

**Contact:** [mailtsjp@gmail.com](mailto:mailtsjp@gmail.com?subject=PropOS%20Partnership%20Enquiry)

Please include:
- Your company name and role
- Which partnership type interests you
- Rough volume / scale you're working with

We'll respond within 2 business days.
    """)

    st.info(
        "💡 **Telegram:** For quick questions, message **@AcePropOS_bot** with your partnership interest "
        "and we'll connect you with the team."
    )

    st.divider()
    st.caption(
        "PropOS is built on Singapore government open data (HDB Resale data.gov.sg, URA transaction data) "
        "and AI analysis. All partnership arrangements are subject to MAS and CEA guidelines where applicable."
    )

# ── SSD Timer ────────────────────────────────────────────────────────────────
elif tab_select == "⏳ SSD Timer":
    st.header("⏳ Seller's Stamp Duty (SSD) Timer")
    st.caption("Know exactly how long before you can sell penalty-free — and how much you'd save by waiting")

    from agents.ssd_calculator import analyse as _ssd_analyse

    col1, col2, col3 = st.columns(3)
    with col1:
        _ssd_purchase_price = st.number_input("Purchase Price (SGD)", 200_000, 10_000_000, 800_000, step=10_000, key="ssd_pp")
    with col2:
        _ssd_purchase_date  = st.date_input("Purchase Date", value=date(2024, 1, 15), key="ssd_pd")
    with col3:
        _ssd_sale_price     = st.number_input("Estimated Sale Price (SGD, 0 = same as purchase)", 0, 10_000_000, 0, step=10_000, key="ssd_sp")

    if st.button("Calculate SSD", type="primary", key="ssd_calc"):
        _ssd_sp = _ssd_sale_price if _ssd_sale_price > 0 else None
        _ssd_res = _ssd_analyse(_ssd_purchase_price, _ssd_purchase_date, _ssd_sp)

        if _ssd_res.is_ssd_free:
            st.success(f"✅ **SSD-free!** You held for {_ssd_res.months_held} months — no stamp duty on sale.")
        else:
            st.warning(
                f"⚠️ **SSD applies.** You've held for **{_ssd_res.months_held} months** — "
                f"currently in the **{_ssd_res.ssd_rate_pct:.0f}% SSD bracket**."
            )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Months Held", _ssd_res.months_held)
        col2.metric("SSD Rate", f"{_ssd_res.ssd_rate_pct:.0f}%")
        col3.metric("SSD Payable", f"SGD {_ssd_res.ssd_amount:,.0f}")
        col4.metric("Days to SSD-Free", f"{_ssd_res.days_to_ssd_free:,}" if not _ssd_res.is_ssd_free else "0")

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("💰 Net Proceeds")
            st.metric("If you sell NOW", f"SGD {_ssd_res.net_proceeds_now:,.0f}")
            st.metric(f"If you wait until {_ssd_res.ssd_free_date.strftime('%b %Y')}", f"SGD {_ssd_res.net_proceeds_after_ssd:,.0f}")
            if _ssd_res.savings_if_wait > 0:
                st.info(f"💡 Waiting saves you **SGD {_ssd_res.savings_if_wait:,.0f}** in SSD.")

        with col_b:
            st.subheader("📅 SSD Rate Schedule")
            import pandas as _pd
            _ssd_df = _pd.DataFrame(_ssd_res.year_brackets)
            _ssd_df["You are here"] = _ssd_df["current"].apply(lambda x: "← HERE" if x else "")
            _ssd_df = _ssd_df[["period","rate_pct","ssd_on_price","You are here"]].rename(columns={
                "period": "Holding Period", "rate_pct": "SSD Rate (%)",
                "ssd_on_price": "SSD on Est. Price (SGD)"
            })
            st.dataframe(_ssd_df, use_container_width=True, hide_index=True)

# ── Refi Alert ────────────────────────────────────────────────────────────────
elif tab_select == "🔄 Refi Alert":
    st.header("🔄 Mortgage Refinancing Analyser")
    st.caption("Find out if switching your home loan saves money — accounting for legal fees, clawback, and break-even")

    from agents.refi_alert import analyse_refi as _refi_analyse, MARKET_RATES as _MR

    st.info(f"📊 Current market rates (updated Jun 2026): Best fixed 2Y **{_MR['best_fixed_2y']}%** | "
            f"SORA 3M **{_MR['sora_3m']}%** | HDB loan **{_MR['hdb_loan']}%**")

    col1, col2 = st.columns(2)
    with col1:
        _refi_loan = st.number_input("Outstanding Loan Balance (SGD)", 100_000, 5_000_000, 600_000, step=10_000)
        _refi_rate = st.number_input("Current Interest Rate (%)", 1.0, 8.0, 4.5, step=0.05, format="%.2f")
        _refi_tenure = st.number_input("Remaining Tenure (months)", 12, 360, 240)
    with col2:
        _refi_lockin = st.number_input("Remaining Lock-In Period (years, 0 = none)", 0.0, 3.0, 0.0, step=0.5)
        _refi_clawback = st.number_input("Clawback Penalty (% of loan, 0 = none)", 0.0, 3.0, 0.0, step=0.25, format="%.2f")
        _refi_proptype = st.selectbox("Property Type", ["private", "hdb"])

    if st.button("Analyse Refinancing", type="primary", key="refi_calc"):
        _refi_res = _refi_analyse(
            outstanding_loan=_refi_loan,
            current_rate_pct=_refi_rate,
            remaining_tenure_months=_refi_tenure,
            lock_in_years=_refi_lockin,
            clawback_pct=_refi_clawback,
            property_type=_refi_proptype,
        )

        if _refi_res.recommended:
            st.success(f"✅ **Recommended to refinance!**")
        else:
            st.warning(f"⏸️ **Not recommended right now.**")

        st.markdown(_refi_res.verdict)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Monthly Savings", f"SGD {_refi_res.monthly_savings:,}")
        col2.metric("Annual Savings", f"SGD {_refi_res.annual_savings:,}")
        col3.metric("Break-Even", f"{_refi_res.breakeven_months} months")
        col4.metric("Net Savings (5Y)", f"SGD {_refi_res.savings_over_5y:,}")

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("💸 Refinancing Costs")
            st.metric("Legal + Valuation Fees", f"SGD {3100:,}")
            st.metric("Clawback Penalty", f"SGD {_refi_res.clawback_sgd:,}")
            st.metric("Total Cost", f"SGD {_refi_res.total_refi_cost:,}")
        with col_b:
            st.subheader("📊 Rate Comparison")
            import pandas as _pd
            _refi_df = _pd.DataFrame(_refi_res.rate_comparison)
            st.dataframe(_refi_df, use_container_width=True, hide_index=True)

        if _refi_res.recommended:
            with st.expander("📞 Get a free mortgage consultation"):
                st.markdown("""
Our partner mortgage brokers can help you compare packages across all major Singapore banks —
**DBS, OCBC, UOB, Standard Chartered, HSBC, Maybank** — at no cost to you.

**What they handle:**
- Rate comparisons across 15+ bank packages
- Lock-in vs floating analysis for your situation
- Processing refinancing paperwork end-to-end
- MRTA/MLTA insurance bundling (saves additional ~SGD 2,000–5,000)
                """)
                _refi_name  = st.text_input("Name", key="refi_broker_name")
                _refi_email = st.text_input("Email", key="refi_broker_email")
                _refi_phone = st.text_input("Phone (optional)", key="refi_broker_phone")
                if st.button("Request Free Consultation", type="primary", key="refi_broker_submit"):
                    if _refi_email:
                        try:
                            from data.analytics import log_broker_lead as _lbl
                            _lbl(_refi_name, _refi_email, _refi_phone, _refi_loan, "refi", "asap",
                                 f"Current rate: {_refi_rate}%, savings: SGD {_refi_res.monthly_savings}/mo")
                        except Exception:
                            pass
                        st.success("✅ We'll connect you with a mortgage specialist within 24 hours!")

# ── HDB Upgrader ──────────────────────────────────────────────────────────────
elif tab_select == "⬆️ HDB Upgrader":
    st.header("⬆️ HDB Upgrader Path Calculator")
    st.caption("Calculate your private condo budget after selling your HDB — including CPF refund, ABSD timing, and TDSR check")

    from agents.hdb_upgrader import calculate_upgrade as _hdb_upg

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Your HDB Details")
        _upg_val       = st.number_input("Estimated HDB Value (SGD)", 300_000, 2_000_000, 550_000, step=5_000)
        _upg_pd        = st.date_input("HDB Purchase Date", value=date(2018, 6, 1), key="upg_pd")
        _upg_loan      = st.number_input("Outstanding HDB Loan (SGD)", 0, 2_000_000, 200_000, step=5_000)
        _upg_cpf       = st.number_input("CPF Used for HDB (SGD, principal only)", 0, 1_000_000, 80_000, step=5_000)
        _upg_loan_rate = st.number_input("HDB Loan Rate (%)", 1.0, 5.0, 2.6, step=0.1, format="%.1f")
        _upg_tenure    = st.number_input("Original HDB Loan Tenure (years)", 5, 30, 25)
    with col2:
        st.subheader("Your Profile")
        _upg_income    = st.number_input("Gross Monthly Income (SGD, household)", 3_000, 50_000, 12_000, step=500)
        _upg_cpf_oa    = st.number_input("Current CPF OA Balance (SGD)", 0, 1_000_000, 60_000, step=5_000)
        _upg_other_debt= st.number_input("Other Monthly Debt Obligations (SGD)", 0, 10_000, 0, step=100)
        _upg_condo_rate= st.number_input("Private Condo Loan Rate (%)", 2.0, 6.0, 3.5, step=0.1, format="%.1f")
        _upg_condo_ten = st.number_input("Condo Loan Tenure (years)", 5, 30, 25)
        _upg_buy_first = st.checkbox("Buying condo BEFORE selling HDB? (ABSD applies)", value=False)

    if st.button("Calculate Upgrade Path", type="primary", key="upg_calc"):
        _upg_res = _hdb_upg(
            hdb_current_value=_upg_val,
            hdb_purchase_date=_upg_pd,
            hdb_outstanding_loan=_upg_loan,
            hdb_cpf_used=_upg_cpf,
            hdb_loan_rate_pct=_upg_loan_rate,
            hdb_tenure_years=_upg_tenure,
            gross_monthly_income=_upg_income,
            cpf_oa_balance=_upg_cpf_oa,
            other_monthly_debt=_upg_other_debt,
            condo_loan_rate_pct=_upg_condo_rate,
            condo_loan_tenure_years=_upg_condo_ten,
            buy_before_selling_hdb=_upg_buy_first,
        )

        st.markdown(_upg_res.verdict)

        for w in _upg_res.warnings:
            st.warning(w)

        st.divider()
        st.subheader("🏦 HDB Sale Proceeds Breakdown")
        col1, col2, col3 = st.columns(3)
        col1.metric("Estimated Value",     f"SGD {_upg_res.hdb_estimated_value:,}")
        col1.metric("Outstanding Loan",    f"- SGD {_upg_res.hdb_outstanding_loan:,}")
        col2.metric("CPF to Refund (OA)",  f"- SGD {_upg_res.hdb_cpf_to_refund:,}")
        col2.metric("Agent Commission",    f"- SGD {_upg_res.hdb_agent_commission:,}")
        col3.metric("SSD (if applicable)", f"- SGD {_upg_res.hdb_ssd:,}")
        col3.metric("Net Cash Proceeds",   f"SGD {_upg_res.hdb_net_cash:,}")

        st.divider()
        st.subheader("🏠 Private Condo Budget")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Conservative",  f"SGD {_upg_res.budget_range['conservative']:,}")
        col_b.metric("Mid Budget",    f"SGD {_upg_res.budget_range['mid']:,}",       delta="Recommended")
        col_c.metric("Stretch",       f"SGD {_upg_res.budget_range['stretch']:,}")

        st.divider()
        col1, col2, col3 = st.columns(3)
        col1.metric("Max Loan (TDSR)", f"SGD {_upg_res.max_loan_by_tdsr:,}")
        col2.metric("Est. Monthly Instalment", f"SGD {_upg_res.monthly_instalment_estimate:,}/mo")
        col3.metric("TDSR Used", f"{_upg_res.tdsr_used_pct}%",
                    delta="✅ OK" if _upg_res.tdsr_used_pct <= 55 else "⚠️ Over limit",
                    delta_color="normal" if _upg_res.tdsr_used_pct <= 55 else "inverse")

        st.divider()
        st.subheader("⚠️ ABSD Considerations")
        col_a, col_b = st.columns(2)
        col_a.metric("ABSD if buy BEFORE selling HDB", f"SGD {_upg_res.absd_if_buy_before_sell:,}", delta="20% penalty")
        col_b.metric("ABSD if buy AFTER selling HDB",  f"SGD 0", delta="No ABSD ✅")
        st.info("💡 **Sell your HDB first**, then buy the condo — you reset to first-property status (0% ABSD). "
                "If you must buy first, apply for **ABSD Remission** (must sell HDB within 6 months of condo purchase).")

        with st.expander("📞 Connect with a Property Specialist"):
            st.markdown("Our partner CEA-licensed property agents specialise in HDB-to-condo upgrades. Free consultation.")
            _upg_name  = st.text_input("Name", key="upg_name")
            _upg_email = st.text_input("Email", key="upg_email")
            if st.button("Request Agent", type="primary", key="upg_agent"):
                if _upg_email:
                    try:
                        from data.analytics import log_broker_lead as _lbl
                        _lbl(_upg_name, _upg_email, "", _upg_val, "hdb_upgrade", "3-6 months",
                             f"Budget SGD {_upg_res.budget_range['mid']:,}, income SGD {_upg_income:,}/mo")
                    except Exception:
                        pass
                    st.success("✅ A property specialist will contact you within 1 business day!")

# ── Property Tax ──────────────────────────────────────────────────────────────
elif tab_select == "🏛️ Property Tax":
    st.header("🏛️ Singapore Property Tax Calculator")
    st.caption("Calculate your annual property tax and find the best investment strategy to offset it — T-bill laddering, CPF, SSBs and more")

    from agents.property_tax import analyse as _ptax_analyse, INVESTMENT_RATES as _PTAX_RATES
    from datetime import date as _ddate

    # ── AV input: postal-code lookup OR manual entry ──────────────────────────
    _ptax_input_tab1, _ptax_input_tab2 = st.tabs(["📮 Lookup by Postal Code", "✏️ Enter AV Manually"])

    # Initialise AV in session state so both tabs can share it
    if "ptax_av_val" not in st.session_state:
        st.session_state["ptax_av_val"] = 24_000

    with _ptax_input_tab1:
        st.caption("Enter your postal code to estimate your property's Annual Value from recent rental transactions.")
        _ptax_pc_col1, _ptax_pc_col2 = st.columns([2, 1])
        with _ptax_pc_col1:
            _ptax_postal = st.text_input("Singapore Postal Code", placeholder="e.g. 560123", max_chars=6, key="ptax_postal")
        with _ptax_pc_col2:
            _ptax_flat_type = st.selectbox("Flat / Unit Type", ["4 ROOM", "3 ROOM", "5 ROOM", "EXECUTIVE", "2 ROOM", "Private"], key="ptax_flat_type")

        if st.button("🔍 Look Up AV", key="ptax_lookup"):
            if len(_ptax_postal) == 6 and _ptax_postal.isdigit():
                with st.spinner("Looking up address and estimating AV..."):
                    try:
                        import requests as _rq
                        # Step 1: geocode via OneMap
                        _om = _rq.get(
                            f"https://www.onemap.gov.sg/api/common/elastic/search"
                            f"?searchVal={_ptax_postal}&returnGeom=N&getAddrDetails=Y&pageNum=1",
                            timeout=5
                        ).json()
                        _om_results = _om.get("results", [])
                        if not _om_results:
                            st.error("Postal code not found. Please check and try again.")
                        else:
                            _om_r = _om_results[0]
                            _om_addr = f"{_om_r.get('BLK_NO','')} {_om_r.get('ROAD_NAME','')}, Singapore {_ptax_postal}".strip()
                            _om_building = _om_r.get("BUILDING", "") or _om_r.get("SEARCHVAL", "")

                            st.success(f"📍 **{_om_addr}**" + (f" ({_om_building})" if _om_building else ""))

                            # Step 2: estimate AV from HDB rental data or URA transactions
                            # AV ≈ estimated annual rental value
                            # HDB: use known average monthly rents by flat type
                            # Private: use URA PSF × floor area × ~4.5% yield
                            _AV_HDB_EST = {
                                "2 ROOM":    10_800,   # ~$900/mo
                                "3 ROOM":    15_600,   # ~$1,300/mo
                                "4 ROOM":    21_600,   # ~$1,800/mo
                                "5 ROOM":    27_600,   # ~$2,300/mo
                                "EXECUTIVE": 33_600,   # ~$2,800/mo
                                "Private":   36_000,   # ~$3,000/mo — rough mid-market estimate
                            }
                            # Adjust by postal sector (rough zone premium)
                            _sector = int(_ptax_postal[:2])
                            _zone_mult = 1.0
                            if _sector in range(1, 9):    _zone_mult = 1.8   # CBD/Marina
                            elif _sector in range(9, 12): _zone_mult = 1.5   # Orchard/River Valley
                            elif _sector in range(15,17): _zone_mult = 1.3   # East Coast/Katong
                            elif _sector in range(10,12): _zone_mult = 1.4   # Bukit Timah
                            elif _sector in range(22,24): _zone_mult = 0.9   # Jurong/West
                            elif _sector in range(70,74): _zone_mult = 0.85  # Woodlands/Yishun
                            elif _sector in range(76,82): _zone_mult = 0.85  # Tampines/Pasir Ris
                            elif _sector >= 60 and _sector < 70: _zone_mult = 0.90  # North

                            _base_av = _AV_HDB_EST.get(_ptax_flat_type, 21_600)
                            _est_av  = int(round(_base_av * _zone_mult / 1_000) * 1_000)

                            # Try to refine from URA/HDB cache
                            try:
                                from data.ura_pipeline import load_all_transactions as _lut
                                _txns = _lut()
                                _proj_psfs = []
                                for _t in _txns:
                                    _tpost = str(_t.get("postalCode","") or _t.get("postal","") or "")
                                    if _tpost == _ptax_postal:
                                        _psf = _t.get("unitPrice") or _t.get("psf")
                                        _area = _t.get("area") or _t.get("floorArea")
                                        if _psf and _area:
                                            try:
                                                # AV ≈ PSF × sqft × 4.5% annual yield
                                                _proj_psfs.append(float(_psf) * float(_area) * 0.045)
                                            except Exception:
                                                pass
                                if _proj_psfs:
                                    import statistics as _stat
                                    _ura_av = int(round(_stat.median(_proj_psfs) / 1_000) * 1_000)
                                    _est_av = _ura_av
                                    st.caption(f"📊 AV estimated from {len(_proj_psfs)} recent URA transactions at this postal code.")
                                else:
                                    st.caption(f"📊 AV estimated from rental benchmarks for {_ptax_flat_type} in this area (no exact postal match in URA cache).")
                            except Exception:
                                st.caption(f"📊 AV estimated from rental benchmarks for {_ptax_flat_type} in this area.")

                            st.info(
                                f"**Estimated Annual Value: SGD {_est_av:,}**  \n"
                                f"This is an *estimate* based on prevailing rental rates. "
                                f"Your actual IRAS-assessed AV may differ. "
                                f"Check your exact AV at [myTax Portal](https://mytax.iras.gov.sg) → "
                                f"Property → View Property Tax."
                            )
                            st.session_state["ptax_av_val"] = _est_av

                    except Exception as _ptax_err:
                        st.error(f"Lookup failed: {_ptax_err}. Please enter AV manually.")
            else:
                st.warning("Enter a valid 6-digit Singapore postal code.")

    with _ptax_input_tab2:
        st.caption("Find your exact AV on your IRAS property tax notice or at myTax Portal → Property → View Property Tax.")
        _ptax_av_manual = st.number_input(
            "Annual Value (AV) of Property (SGD)",
            help="IRAS assesses AV as the estimated annual rental value of your property.",
            min_value=5_000, max_value=500_000,
            value=st.session_state["ptax_av_val"],
            step=1_000, key="ptax_av_manual"
        )
        st.session_state["ptax_av_val"] = _ptax_av_manual

    # Use whichever AV was last set (postal lookup or manual)
    _ptax_av = st.session_state["ptax_av_val"]

    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("AV to Use", f"SGD {_ptax_av:,}", help="From postal lookup or manual entry above")
    with col2:
        _ptax_oo = st.radio("Owner-Occupier Status", ["Owner-Occupied (live in it)", "Non-Owner-Occupier (renting out / investment)"], horizontal=False)
        _ptax_oo_bool = "Owner-Occupied" in _ptax_oo
    with col3:
        st.markdown("**Tax Due Date**")
        st.markdown("IRAS issues assessment in Dec/Jan.")
        st.markdown("**Payment deadline: 31 January** each year.")
        st.markdown("Late payment: 5% penalty, then 2%/month.")

    if st.button("Calculate Property Tax", type="primary", key="ptax_calc"):
        _ptax_res = _ptax_analyse(_ptax_av, _ptax_oo_bool)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Annual Value", f"SGD {_ptax_res.annual_value:,}")
        col2.metric("Property Tax", f"SGD {_ptax_res.tax_amount:,}", delta="/year")
        col3.metric("Effective Rate", f"{_ptax_res.effective_rate_pct:.2f}%")
        col4.metric("Days to Jan 31", f"{_ptax_res.days_to_jan31} days")

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("📊 Tax Breakdown by Band")
            import pandas as _pd
            _ptax_df = _pd.DataFrame(_ptax_res.band_breakdown)
            _ptax_df = _ptax_df[["band","rate_pct","av_in_band","tax"]].rename(columns={
                "band": "AV Band", "rate_pct": "Rate (%)", "av_in_band": "AV in Band (SGD)", "tax": "Tax (SGD)"
            })
            st.dataframe(_ptax_df, use_container_width=True, hide_index=True)

            st.caption(f"Rates: {'Owner-Occupier progressive 0–32%' if _ptax_oo_bool else 'Non-Owner-Occupier 11–27%'}")
            if not _ptax_oo_bool:
                st.info("💡 **Tip:** If this is your primary residence, you may qualify for owner-occupier rates (much lower). Apply via myTax Portal.")

        with col_b:
            st.subheader("✅ Best Way to Pay")
            st.success(f"**Recommended: {_ptax_res.recommended_instrument}**")
            st.markdown(_ptax_res.recommended_notes)

        st.divider()
        st.subheader("💹 Investment Options to Offset Your Property Tax")
        st.caption(
            f"Invest now so returns cover SGD {_ptax_res.tax_amount:,} by {_ptax_res.next_jan31.strftime('%d %b %Y')} "
            f"({_ptax_res.days_to_jan31} days away)"
        )

        for opt in _ptax_res.investment_options:
            risk_color = {"Very Low": "🟢", "Zero": "✅", "Medium (price fluctuation)": "🟡"}.get(opt["risk"], "⚪")
            with st.expander(
                f"{risk_color} **{opt['instrument']}** — {opt['rate_pa']}% p.a. | "
                f"Need: SGD {opt['principal_needed']:,} → Returns SGD {opt['return_generated']:,}"
            ):
                col1, col2, col3 = st.columns(3)
                col1.metric("Principal Needed", f"SGD {opt['principal_needed']:,}")
                col2.metric("Return Generated", f"SGD {opt['return_generated']:,}")
                col3.metric("Risk Level", opt["risk"])
                st.markdown(f"**Liquidity:** {opt['liquidity']}")
                st.markdown(f"**Notes:** {opt['notes']}")
                if opt.get("cpf_eligible"):
                    st.info("🏦 **CPF Path:** Login to CPF Board portal → My Requests → Property → Pay property tax using CPF savings. Or set up GIRO from CPF OA via IRAS.")

        st.divider()
        st.subheader("📅 T-Bill Laddering Strategy")
        st.caption("Stagger T-bill purchases so they mature just before Jan 31 — maximise yield while ensuring liquidity")
        for step in _ptax_res.tbill_ladder:
            st.markdown(f"**Tranche {step['tranche']}:** {step['action']}")

        with st.expander("ℹ️ How to buy Singapore T-bills"):
            st.markdown("""
**Via Internet Banking (DBS/OCBC/UOB):**
1. Login → Invest → Singapore Government Securities (SGS)
2. Select T-bill auction (6M or 1Y)
3. Enter bid amount and yield (or apply for non-competitive bid to guarantee allocation)
4. Settlement: 2 business days after auction

**Via CDP Account:**
- Open CDP account at SGX before bidding
- Link to your bank account

**Auction schedule:** T-bill auctions held roughly every 4 weeks.
Check: [MAS T-bill auctions](https://www.mas.gov.sg/bonds-and-bills/singapore-government-t-bills-information-for-individuals)

**Minimum bid:** SGD 1,000 per application, multiples of SGD 1,000
**Maximum individual:** No cap (CPF investments capped at SGD 20,000 per T-bill)
            """)

        st.divider()
        st.subheader("📌 Current Indicative Yields")
        import pandas as _pd
        _yield_data = [
            {"Instrument": "T-Bill (6M)",       "Rate (% p.a.)": _PTAX_RATES["tbill_6m"],  "Risk": "Very Low", "Min Amount": "SGD 1,000"},
            {"Instrument": "T-Bill (1Y)",        "Rate (% p.a.)": _PTAX_RATES["tbill_1y"],  "Risk": "Very Low", "Min Amount": "SGD 1,000"},
            {"Instrument": "Singapore Savings Bond", "Rate (% p.a.)": _PTAX_RATES["ssb_1y"], "Risk": "Very Low", "Min Amount": "SGD 500"},
            {"Instrument": "Fixed Deposit (6M)", "Rate (% p.a.)": _PTAX_RATES["fd_6m"],     "Risk": "Very Low", "Min Amount": "SGD 10,000"},
            {"Instrument": "CPF OA",             "Rate (% p.a.)": _PTAX_RATES["cpf_oa"],    "Risk": "Zero",     "Min Amount": "Own CPF OA"},
            {"Instrument": "S-REITs (div yield)","Rate (% p.a.)": _PTAX_RATES["reits_div"], "Risk": "Medium",   "Min Amount": "~SGD 200+"},
        ]
        st.dataframe(_pd.DataFrame(_yield_data), use_container_width=True, hide_index=True)

# ── Price History ─────────────────────────────────────────────────────────────
elif tab_select == "📈 Price History":
    st.header("📈 Project Price History")
    st.caption("Track PSF trends by project, district, or property type — powered by 137,584+ URA transactions")

    from agents.price_history import get_project_history as _ph_get, top_trending_projects as _ph_top, district_psf_trend as _ph_dist

    _ph_tab1, _ph_tab2, _ph_tab3 = st.tabs(["🔍 Project Lookup", "🏆 Top Trending", "🗺️ By District"])

    with _ph_tab1:
        col1, col2 = st.columns([3, 1])
        with col1:
            _ph_project = st.text_input("Project / Development Name or Postal Code",
                                         placeholder="e.g. The Pinnacle @ Duxton  OR  6-digit postal code",
                                         key="ph_project_name")
        with col2:
            _ph_proptype = st.selectbox("Filter by Type", ["All", "Condominium", "Apartment", "Executive Condominium", "Landed"],
                                         key="ph_proptype")
        st.caption("💡 Tip: enter a project name (partial is fine) or a 6-digit postal code — we'll resolve it to the development name automatically.")

        if st.button("Load Price History", type="primary", key="ph_search") and _ph_project:
            with st.spinner("Loading transaction history from URA cache..."):
                try:
                    from data.ura_pipeline import load_all_transactions as _load_ura
                    _all_txns = _load_ura()
                    _ph_ptype = None if _ph_proptype == "All" else _ph_proptype

                    # ── Postal code → building name via OneMap ───────────────
                    _ph_search_term = _ph_project.strip()
                    _ph_search_term_orig = _ph_search_term
                    if _ph_search_term.isdigit() and len(_ph_search_term) == 6:
                        try:
                            _om = _requests_lib.get(
                                "https://www.onemap.gov.sg/api/common/elastic/search"
                                f"?searchVal={_ph_search_term}&returnGeom=N&getAddrDetails=Y&pageNum=1",
                                timeout=6
                            ).json()
                            _om_results = _om.get("results", [])
                            if _om_results:
                                _om_r = _om_results[0]
                                _bldg = (_om_r.get("BUILDING","") or "").strip()
                                _road = (_om_r.get("ROAD_NAME","") or "").strip()
                                _blk  = (_om_r.get("BLK_NO","") or "").strip()
                                # Use building name if available, else block+street
                                _ph_search_term = _bldg if _bldg and _bldg.upper() not in ("NIL","") else f"{_blk} {_road}".strip()
                                st.info(f"📍 Postal {_ph_search_term_orig} → searching for: **{_ph_search_term}**")
                            else:
                                st.warning(f"Postal code {_ph_search_term_orig} not found on OneMap. Searching as-is.")
                        except Exception as _om_err:
                            st.caption(f"OneMap lookup failed: {_om_err}. Searching postal code as-is.")

                    _ph_res = _ph_get(_ph_search_term, _all_txns, _ph_ptype)
                    # Store original query for display
                    if _ph_res and _ph_res["match_count"] == 0 and _ph_search_term != _ph_search_term_orig:
                        # Fallback: try original postal as literal search
                        _ph_res_fallback = _ph_get(_ph_search_term_orig, _all_txns, _ph_ptype)
                        if _ph_res_fallback and _ph_res_fallback["match_count"] > 0:
                            _ph_res = _ph_res_fallback
                except Exception as _phe:
                    st.error(f"Error loading data: {_phe}")
                    _ph_res = None

            if _ph_res and _ph_res["match_count"] > 0:
                col1, col2, col3 = st.columns(3)
                col1.metric("Matching Transactions", f"{_ph_res['match_count']:,}")
                col2.metric("Latest Median PSF", f"SGD {_ph_res['latest_median_psf']:,}")
                col3.metric("PSF Change (all time)", f"{_ph_res['psf_change_pct']:+.1f}%",
                            delta_color="normal" if _ph_res['psf_change_pct'] >= 0 else "inverse")

                if _ph_res["quarters"]:
                    import pandas as _pd
                    _ph_df = _pd.DataFrame(_ph_res["quarters"])
                    _ph_df = _ph_df.set_index("quarter")

                    st.subheader("📈 Median PSF by Quarter")
                    st.line_chart(_ph_df["median_psf"], height=300, use_container_width=True)

                    st.subheader("📊 Quarterly Summary Table")
                    _ph_show = _ph_df[["median_psf","min_psf","max_psf","count","median_price"]].rename(columns={
                        "median_psf": "Median PSF", "min_psf": "Min PSF", "max_psf": "Max PSF",
                        "count": "# Txns", "median_price": "Median Price"
                    })
                    st.dataframe(_ph_show, use_container_width=True)
                else:
                    st.warning("No quarterly data found — try a broader project name.")
            elif _ph_res:
                st.warning(f"No transactions found for **{_ph_project}**. Try a partial name or check spelling.")

    with _ph_tab2:
        st.subheader("🏆 Top Trending Projects (Biggest PSF Appreciation)")
        st.caption("Projects with highest PSF appreciation across all URA transactions — min 10 transactions")
        if st.button("Load Top 10 Trending Projects", key="ph_top_btn"):
            with st.spinner("Scanning 137k+ transactions... (may take 15–30 sec)"):
                try:
                    from data.ura_pipeline import load_all_transactions as _load_ura
                    _all_txns = _load_ura()
                    _ph_trending = _ph_top(_all_txns, min_txns=10, top_n=10)
                except Exception as _te:
                    st.error(f"Error: {_te}")
                    _ph_trending = []

            if _ph_trending:
                import pandas as _pd
                _trend_rows = []
                for p in _ph_trending:
                    _trend_rows.append({
                        "Project": p["project"],
                        "PSF Change": f"{p['psf_change_pct']:+.1f}%",
                        "Earliest PSF": f"SGD {p['earliest_median_psf']:,}",
                        "Latest PSF": f"SGD {p['latest_median_psf']:,}",
                        "Txns": p["total_txns"],
                        "Quarters": len(p["quarters"]),
                    })
                st.dataframe(_pd.DataFrame(_trend_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No data loaded yet.")

    with _ph_tab3:
        st.subheader("🗺️ District PSF Trend")
        _ph_district = st.selectbox("Select District", list(range(1, 29)), format_func=lambda d: f"D{d:02d}", key="ph_district")
        if st.button("Load District Trend", key="ph_dist_btn"):
            with st.spinner("Loading district transactions..."):
                try:
                    from data.ura_pipeline import load_all_transactions as _load_ura
                    _all_txns = _load_ura()
                    _ph_dist_data = _ph_dist(_all_txns, str(_ph_district))
                except Exception as _de:
                    st.error(f"Error: {_de}")
                    _ph_dist_data = []

            if _ph_dist_data:
                import pandas as _pd
                _dist_df = _pd.DataFrame(_ph_dist_data).set_index("quarter")
                st.line_chart(_dist_df["median_psf"], height=280, use_container_width=True)
                st.dataframe(_dist_df, use_container_width=True)
            else:
                st.info(f"No data found for District {_ph_district}.")

# ── Rental Yield ─────────────────────────────────────────────────────────────
elif tab_select == "🏘️ Rental Yield":
    st.header("🏘️ Rental Yield Calculator")
    st.caption("Full buy-to-let analysis — gross & net yield, monthly cashflow, breakeven rent, vs T-bills and REITs")

    from agents.rental_yield import analyse as _ry_analyse, BENCHMARKS as _RY_BENCH

    # ── Try to pre-fill rent from URA rental cache ────────────────────────────
    _ry_rent_hint = None
    with st.expander("🔍 Look up market rent by postal code (optional)", expanded=False):
        _ry_pc = st.text_input("Postal code", max_chars=6, placeholder="e.g. 520123", key="ry_postal")
        _ry_ft = st.selectbox("Flat / unit type", ["4 ROOM","3 ROOM","5 ROOM","EXECUTIVE","2 ROOM","Private (≤700sqft)","Private (700–1200sqft)","Private (>1200sqft)"], key="ry_flat")
        if st.button("Get Market Rent", key="ry_rent_lookup"):
            # Use URA rental data if available, else benchmark table
            _RENT_BENCH = {
                "2 ROOM": {"central": 1800, "mid": 1400, "outer": 1100},
                "3 ROOM": {"central": 2800, "mid": 2200, "outer": 1800},
                "4 ROOM": {"central": 3500, "mid": 2800, "outer": 2300},
                "5 ROOM": {"central": 4200, "mid": 3400, "outer": 2800},
                "EXECUTIVE": {"central": 5000, "mid": 4000, "outer": 3200},
                "Private (≤700sqft)": {"central": 3500, "mid": 2800, "outer": 2200},
                "Private (700–1200sqft)": {"central": 5500, "mid": 4200, "outer": 3200},
                "Private (>1200sqft)": {"central": 9000, "mid": 6500, "outer": 4500},
            }
            _sector = int(_ry_pc[:2]) if _ry_pc and len(_ry_pc) >= 2 and _ry_pc[:2].isdigit() else 0
            _zone = "outer"
            if _sector in range(1, 12):   _zone = "central"
            elif _sector in range(12,22): _zone = "mid"
            elif _sector in range(22,30): _zone = "outer"
            elif _sector in range(30,40): _zone = "mid"
            elif _sector in range(40,60): _zone = "mid"
            else:                          _zone = "outer"
            _est = _RENT_BENCH.get(_ry_ft, {}).get(_zone, 2500)
            st.info(f"📊 Market rent estimate for **{_ry_ft}** in zone **{_zone.title()}**: ~**SGD {_est:,}/month**  \nAdjust based on actual condition, floor level, and furnishing.")
            st.session_state["ry_rent_prefill"] = _est

    st.divider()

    # ── Main inputs ───────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🏠 Property Details")
        _ry_price    = st.number_input("Purchase Price (SGD)", 200_000, 10_000_000, 800_000, step=10_000, key="ry_price")
        _ry_area     = st.number_input("Floor Area (sqft, 0 = unknown)", 0, 5000, 1000, step=50, key="ry_area")
        _ry_ptype    = st.selectbox("Property Type", ["condo","hdb","landed"], key="ry_ptype")
        _ry_absd     = st.number_input("ABSD Paid (SGD, 0 if none)", 0, 2_000_000, 0, step=5_000, key="ry_absd")
        _ry_hold_yrs = st.number_input("Expected Holding Period (years)", 1, 30, 10, key="ry_hold")

    with col2:
        st.subheader("💰 Rental & Financing")
        _prefill_rent = st.session_state.get("ry_rent_prefill", 2800)
        _ry_rent     = st.number_input("Expected Monthly Rent (SGD)", 500, 50_000, _prefill_rent, step=100, key="ry_rent")
        _ry_vacancy  = st.slider("Vacancy Allowance (months/year)", 0.0, 3.0, 1.0, 0.5, key="ry_vacancy")
        _ry_mortgaged = st.checkbox("Property is mortgaged", value=True, key="ry_mortgaged")
        if _ry_mortgaged:
            _ry_loan     = st.number_input("Outstanding Loan (SGD)", 0, 8_000_000, 600_000, step=10_000, key="ry_loan")
            _ry_lrate    = st.number_input("Loan Rate (%)", 1.0, 8.0, 3.5, step=0.1, format="%.1f", key="ry_lrate")
            _ry_ltenure  = st.number_input("Remaining Tenure (years)", 1, 35, 25, key="ry_ltenure")
        else:
            _ry_loan = _ry_lrate = _ry_ltenure = 0

    if st.button("Calculate Rental Yield", type="primary", key="ry_calc"):
        _ry_res = _ry_analyse(
            purchase_price=_ry_price,
            monthly_rent=_ry_rent,
            floor_area_sqft=_ry_area,
            property_type=_ry_ptype,
            loan_amount=_ry_loan,
            loan_rate_pct=_ry_lrate,
            loan_tenure_years=int(_ry_ltenure) if _ry_ltenure else 25,
            vacancy_months_per_year=_ry_vacancy,
            absd_paid=_ry_absd,
            holding_years=int(_ry_hold_yrs),
        )

        # ── Top metrics ──────────────────────────────────────────────────────
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Gross Yield",     f"{_ry_res.gross_yield_pct:.1f}%")
        m2.metric("Net Yield",       f"{_ry_res.net_yield_pct:.1f}%",
                  delta="✅ Above T-bill" if _ry_res.net_yield_pct >= _RY_BENCH["tbill_6m"] else "⚠️ Below T-bill")
        m3.metric("Yield on Equity", f"{_ry_res.net_yield_on_equity_pct:.1f}%")
        m4.metric("Monthly Cashflow",
                  f"SGD {_ry_res.monthly_net_cashflow:+,.0f}",
                  delta_color="normal" if _ry_res.monthly_net_cashflow >= 0 else "inverse")
        m5.metric("Years to Payback", f"{_ry_res.years_to_payback:.0f} yrs" if _ry_res.years_to_payback < 999 else "∞")

        # ── Verdict ──────────────────────────────────────────────────────────
        if _ry_res.net_yield_pct >= 4.0:
            st.success(_ry_res.verdict)
        elif _ry_res.net_yield_pct >= 2.5:
            st.warning(_ry_res.verdict)
        else:
            st.error(_ry_res.verdict)

        st.divider()

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("📊 Monthly Cashflow Breakdown")
            import pandas as _pd
            _cf_data = {
                "Item": ["Rental Income", "Mortgage Instalment", "Running Expenses", "Net Cashflow"],
                "SGD/month": [
                    f"+ {_ry_res.monthly_rent_income:,}",
                    f"- {_ry_res.monthly_mortgage:,}" if _ry_res.monthly_mortgage else "—",
                    f"- {_ry_res.monthly_expenses:,}",
                    f"{_ry_res.monthly_net_cashflow:+,}",
                ]
            }
            st.dataframe(_pd.DataFrame(_cf_data), use_container_width=True, hide_index=True)

            st.subheader("📋 Annual Expense Breakdown")
            _exp_rows = [{"Cost Item": k, "SGD/year": f"{v:,}"} for k, v in _ry_res.annual_expenses.items()]
            _exp_rows.append({"Cost Item": "**TOTAL EXPENSES**", "SGD/year": f"**{sum(_ry_res.annual_expenses.values()):,}**"})
            st.dataframe(_pd.DataFrame(_exp_rows), use_container_width=True, hide_index=True)

        with col_b:
            st.subheader("⚖️ Breakeven Analysis")
            _be_delta = _ry_res.monthly_rent - _ry_res.breakeven_rent
            st.metric("Breakeven Rent",  f"SGD {_ry_res.breakeven_rent:,}/month")
            st.metric("Your Rent",       f"SGD {_ry_res.monthly_rent:,}/month",
                      delta=f"SGD {_be_delta:+,.0f} {'buffer' if _be_delta >= 0 else 'shortfall'}",
                      delta_color="normal" if _be_delta >= 0 else "inverse")
            if _ry_res.is_mortgaged:
                st.metric("Mortgage Coverage", f"{_ry_res.mortgage_coverage_ratio:.1f}×",
                          delta="Healthy ✅" if _ry_res.mortgage_coverage_ratio >= 1.3 else "Tight ⚠️",
                          delta_color="normal" if _ry_res.mortgage_coverage_ratio >= 1.3 else "inverse")

            st.subheader("📈 vs Alternative Investments")
            st.caption(f"What if you invested SGD {_ry_res.purchase_price:,} elsewhere?")
            _bench_df = _pd.DataFrame(_ry_res.benchmarks)
            _bench_df["Better than property?"] = _bench_df["vs Your Net Yield"].apply(
                lambda x: "✅ Yes" if x < 0 else "❌ No"
            )
            st.dataframe(_bench_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("💡 Key Insights")
        for tip in _ry_res.tips:
            st.markdown(f"- {tip}")

        # ── Insurance CTA ────────────────────────────────────────────────────
        st.divider()
        with st.expander("🛡️ Protect Your Rental Investment — Insurance Checklist"):
            st.markdown(f"""
As a landlord, you need more than just fire insurance. Here's what PropOS recommends:

| Cover | Why | Est. Premium |
|---|---|---|
| **Fire Insurance** | Covers structure damage (mandatory for HDB) | SGD 200/year |
| **Home Contents** | Protects fixtures and fittings you provide | SGD 300–600/year |
| **Landlord Liability** | If tenant is injured in your property | Bundled with above |
| **Loss of Rent** | Pays if property is uninhabitable due to covered event | Add-on ~SGD 100/year |
| **Mortgage Protection (MRTA)** | Clears SGD {_ry_res.monthly_mortgage * _ry_ltenure * 12:,.0f} loan if you pass away | SGD 2,000–5,000 one-time |

**Your mortgage at SGD {_ry_res.monthly_mortgage:,}/month over {int(_ry_ltenure) if _ry_ltenure else 25} years = SGD {int(_ry_res.monthly_mortgage * (int(_ry_ltenure) if _ry_ltenure else 25) * 12):,} total exposure.**
An MRTA policy ensures your family inherits the property debt-free — not the mortgage.
            """)
            _ins_name  = st.text_input("Name", key="ry_ins_name")
            _ins_email = st.text_input("Email", key="ry_ins_email")
            if st.button("Get Free Insurance Quote", type="primary", key="ry_ins_cta"):
                if _ins_email:
                    try:
                        from data.analytics import log_broker_lead as _lbl
                        _lbl(_ins_name, _ins_email, "", _ry_loan, "landlord_insurance", "asap",
                             f"Rental property SGD {_ry_price:,}, rent SGD {_ry_rent:,}/mo, "
                             f"net yield {_ry_res.net_yield_pct}%")
                    except Exception:
                        pass
                    st.success("✅ An insurance specialist will contact you within 1 business day with landlord cover options!")

# ── Admin ─────────────────────────────────────────────────────────────────────
elif tab_select == "⚙️ Admin":
    st.header("⚙️ Admin Panel")
    admin_pw = st.text_input("Admin Password", type="password")

    if admin_pw == os.environ.get("ADMIN_PASSWORD", "changeme"):
        st.success("✅ Authenticated")

        st.subheader("🤖 LLM Mode")
        current = get_current_mode()
        st.info(f"Current: **{current['mode'].upper()}** → {current['model']} | Cost: ${current['cost_per_1k_tokens_input']}/1K input tokens")

        new_mode = st.selectbox(
            "Switch Mode",
            ["free", "balanced", "quality", "premium"],
            index=["free", "balanced", "quality", "premium"].index(current["mode"]),
            help="free=Gemini(free) | balanced=Groq(near-free) | quality=Haiku(default) | premium=Sonnet(VC demo)"
        )
        mode_descriptions = {
            "free": "🟢 Gemini 2.0 Flash — Free tier, 15 RPM. Use for bulk/cron jobs.",
            "balanced": "🟡 Groq Llama 3.1 8B — Near-free, very fast structured outputs.",
            "quality": "🔵 Claude Haiku 4.5 — Default production. Good quality, low cost.",
            "premium": "🟣 Claude Sonnet 4.6 — Full quality. Use for demos and complex reasoning.",
        }
        st.caption(mode_descriptions[new_mode])

        if st.button("Apply Mode", type="primary"):
            save_mode(new_mode)
            st.success(f"Mode switched to **{new_mode}**")
            st.rerun()

        st.divider()
        st.subheader("👥 User Tier Management")
        from data.freemium import set_tier, tier_info, ensure_schema
        ensure_schema()
        ut_col1, ut_col2, ut_col3 = st.columns(3)
        with ut_col1:
            ut_id = st.text_input("Telegram ID", key="ut_id", placeholder="1234567890")
        with ut_col2:
            ut_tier = st.selectbox("Tier", ["pro", "free"], key="ut_tier")
        with ut_col3:
            ut_months = st.number_input("Months (Pro)", 1, 24, 1, key="ut_months")
        if st.button("Update Tier", key="ut_save"):
            if ut_id:
                set_tier(ut_id, ut_tier, ut_months if ut_tier == "pro" else 0)
                st.success(f"✅ {ut_id} → {ut_tier} ({ut_months} months)")
        if ut_id:
            try:
                _ti = tier_info(ut_id)
                st.caption(f"Current: **{_ti['tier'].upper()}** · {_ti['alerts_used_this_week']} alerts this week · expires {_ti.get('expires_at','—')}")
            except Exception:
                pass

        st.divider()
        # ── Weekly Digest ──────────────────────────────────────────────────────
        st.subheader("📧 Weekly Digest")
        _dg_c1, _dg_c2 = st.columns(2)
        with _dg_c1:
            if st.button("🔍 Preview Digest HTML", key="digest_preview"):
                with st.spinner("Building digest..."):
                    try:
                        from agents.weekly_digest import build_digest_html as _build_dg
                        _dg_html = _build_dg()
                        st.markdown("**Digest preview (raw HTML length):**")
                        st.code(f"{len(_dg_html):,} characters", language=None)
                        with st.expander("Show raw HTML"):
                            st.code(_dg_html[:3000] + "...", language="html")
                    except Exception as _dge:
                        st.error(f"Preview error: {_dge}")
        with _dg_c2:
            if st.button("🚀 Send Weekly Digest Now", type="primary", key="digest_send"):
                with st.spinner("Sending to all subscribers..."):
                    try:
                        from agents.weekly_digest import send_weekly_digest as _send_dg
                        _dg_result = _send_dg(dry_run=False)
                        st.success(
                            f"✅ Digest sent: **{_dg_result['sent']} delivered**, "
                            f"{_dg_result.get('failed',0)} failed"
                        )
                    except Exception as _dge:
                        st.error(f"Send error: {_dge}")
        st.caption("Cron: Sunday 8 AM SGT — `python3 /root/propos/agents/weekly_digest.py`")

        st.divider()
        # ── Subscriber Management ──────────────────────────────────────────────
        st.subheader("📬 Subscriber Management")
        from data.analytics import (
            get_all_subscribers as _get_subs, get_subscriber_count as _sub_cnt,
            unsubscribe_email as _unsub_email, delete_subscriber as _del_sub,
            resubscribe_email as _resub_email, add_subscriber as _add_sub_admin
        )
        import pandas as _spd

        _subs = _get_subs(active_only=False)
        _active_cnt   = sum(1 for s in _subs if s["active"])
        _inactive_cnt = sum(1 for s in _subs if not s["active"])

        _sc1, _sc2, _sc3 = st.columns(3)
        _sc1.metric("Active Subscribers", _active_cnt)
        _sc2.metric("Unsubscribed", _inactive_cnt)
        _sc3.metric("Total (all time)", len(_subs))

        if _subs:
            _sub_rows = []
            for _s in _subs:
                _sub_rows.append({
                    "Email": _s["email"],
                    "Subscribed": _s["subscribed_at"][:10],
                    "Source": _s.get("source","sidebar"),
                    "Welcome Sent": "✅" if _s["welcome_sent"] else "❌",
                    "Status": "Active" if _s["active"] else "Unsubscribed",
                })
            _sub_df = _spd.DataFrame(_sub_rows)
            st.dataframe(_sub_df, hide_index=True, use_container_width=True)

            # CSV export
            _csv = _sub_df.to_csv(index=False)
            st.download_button(
                "📥 Export CSV",
                data=_csv,
                file_name="propos_subscribers.csv",
                mime="text/csv",
                key="sub_csv_dl"
            )

        # Actions on individual subscriber
        with st.expander("🔧 Manage a subscriber"):
            _mgmt_email = st.text_input("Email address", key="sub_mgmt_email", placeholder="user@example.com")
            _mg1, _mg2, _mg3, _mg4 = st.columns(4)
            if _mg1.button("🔴 Unsubscribe", key="sub_do_unsub"):
                if _mgmt_email and "@" in _mgmt_email:
                    if _unsub_email(_mgmt_email):
                        st.success(f"Unsubscribed: {_mgmt_email}")
                    else:
                        st.warning(f"Not found: {_mgmt_email}")
                else:
                    st.warning("Enter email first")

            if _mg2.button("🟢 Re-activate", key="sub_do_resub"):
                if _mgmt_email and "@" in _mgmt_email:
                    if _resub_email(_mgmt_email):
                        st.success(f"Re-activated: {_mgmt_email}")
                    else:
                        st.warning(f"Not found: {_mgmt_email}")

            if _mg3.button("🗑️ Delete", key="sub_do_del"):
                if _mgmt_email and "@" in _mgmt_email:
                    if _del_sub(_mgmt_email):
                        st.success(f"Deleted: {_mgmt_email}")
                    else:
                        st.warning(f"Not found: {_mgmt_email}")

            if _mg4.button("📧 Resend Welcome", key="sub_do_welcome"):
                if _mgmt_email and "@" in _mgmt_email:
                    _sent = _send_welcome_email(_mgmt_email)
                    if _sent:
                        from data.analytics import mark_welcome_sent as _mwsm
                        _mwsm(_mgmt_email)
                        st.success(f"Welcome email resent to {_mgmt_email}")
                    else:
                        st.warning("SMTP not configured — set SMTP_HOST, SMTP_USER, SMTP_PASS in .env")

            # Debug: check if email exists
            if st.button("🔍 Check email in DB", key="sub_check"):
                if _mgmt_email:
                    _found = next((s for s in _subs if s["email"] == _mgmt_email.strip().lower()), None)
                    if _found:
                        st.json(_found)
                    else:
                        st.info(f"'{_mgmt_email}' not found in subscribers table.")

        st.divider()
        st.subheader("📊 Visitor Analytics")
        from data.analytics import get_summary, get_engaged_sessions, get_broker_leads, ai_visitor_summary
        import pandas as _apd

        _an_days = st.radio("Period", [7, 30, 90], index=1, horizontal=True, key="an_days")
        stats = get_summary(_an_days)
        engaged = get_engaged_sessions(_an_days)
        leads = get_broker_leads(_an_days)

        # KPI row
        ak1, ak2, ak3, ak4, ak5, ak6 = st.columns(6)
        ak1.metric("Unique Visitors", stats["unique_visitors_ip"])
        ak2.metric("Sessions", stats["unique_sessions"])
        ak3.metric("Page Views", stats["total_views"])
        ak4.metric("Avg Pages/Session", stats["avg_pages_per_session"])
        ak5.metric("Broker Leads", stats["broker_leads"])
        ak6.metric("Telegram Users", stats["telegram_users"])

        # Visitor type breakdown
        vt = stats["by_visitor_type"]
        if vt:
            av1, av2 = st.columns(2)
            with av1:
                st.markdown("**Visitor Type Breakdown**")
                for vtype, cnt in sorted(vt.items(), key=lambda x: -x[1]):
                    icon = {"consumer":"👤","corporate":"🏢","internal":"🔒","local":"💻"}.get(vtype,"❓")
                    st.write(f"{icon} **{vtype.title()}**: {cnt} unique IPs")
            with av2:
                st.markdown("**Top Pages**")
                for p in stats["by_page"][:6]:
                    st.write(f"• {p['page']} — {p['views']} views")

        # Daily trend
        if stats["by_day"]:
            trend_df = _apd.DataFrame(stats["by_day"]).set_index("date")
            st.markdown("**Daily Traffic**")
            st.line_chart(trend_df["views"], height=180)

        # Top features
        if stats["top_features"]:
            st.markdown("**Most Used Features**")
            feat_df = _apd.DataFrame(stats["top_features"])
            st.dataframe(feat_df, hide_index=True, use_container_width=True)

        # Engaged sessions
        if engaged:
            st.markdown(f"**Power Users — {len(engaged)} sessions with 3+ pages**")
            eng_rows = []
            for s in engaged[:20]:
                contact = s.get("telegram_id") or s.get("email") or "anonymous"
                eng_rows.append({
                    "Session": s["session_id"][:8],
                    "Pages": s["page_count"],
                    "Visited": s["pages_visited"][:60] + "…" if len(s.get("pages_visited","")) > 60 else s.get("pages_visited",""),
                    "Contact": contact,
                    "Type": s.get("visitor_type",""),
                    "First Seen": s.get("first_seen","")[:16],
                })
            st.dataframe(_apd.DataFrame(eng_rows), hide_index=True, use_container_width=True)

        # Broker leads table
        if leads:
            st.markdown(f"**Broker Referral Leads — {len(leads)} total**")
            lead_rows = [{"Date": l["ts"][:10], "Name": l["name"], "Email": l["email"],
                          "Phone": l.get("phone",""), "Loan": f"SGD {l['loan_sgd']:,.0f}",
                          "Type": l["prop_type"], "Timeline": l["timeline"]} for l in leads]
            st.dataframe(_apd.DataFrame(lead_rows), hide_index=True, use_container_width=True)

        # AI summary
        st.divider()
        st.markdown("**🤖 AI Business Intelligence Summary**")
        _ai_sum = ai_visitor_summary(stats, engaged)
        st.markdown(_ai_sum)
        st.caption("Rule-based analysis — no API cost. Pattern interpretation from traffic data.")

        st.divider()
        st.subheader("💰 Token Cost Tracker")
        costs = get_token_summary()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Cost (USD)", f"${costs['total_cost_usd']:.4f}")
        c2.metric("Total Cost (SGD)", f"${costs['est_sgd']:.4f}")
        c3.metric("Total Tokens Used", f"{costs['total_tokens']:,}")
        st.metric("API Calls Made", costs["call_count"])

        st.divider()
        st.subheader("📋 Regulatory Data — Last Verified")
        st.caption("These rates are hardcoded from official sources. Verify after each Singapore Budget (usually February) and update the corresponding file if rates change.")

        from data.stamp_duty import RATES_EFFECTIVE_DATE
        _REG_SOURCES = [
            {"name": "BSD / ABSD / SSD rates", "file": "data/stamp_duty.py",
             "verified": RATES_EFFECTIVE_DATE, "url": "https://www.iras.gov.sg/taxes/stamp-duty/for-property/buying-or-acquiring-property/additional-buyer's-stamp-duty-(absd)"},
            {"name": "TDSR / MSR limits (55% / 30%)", "file": "data/mortgage_agent.py → TDSR_LIMIT",
             "verified": "Jun 2023 (MAS)", "url": "https://www.mas.gov.sg/regulation/explainers/tdsr-framework"},
            {"name": "HDB Concessionary Rate (2.60%)", "file": "agents/mortgage_agent.py → HDB (CPF Board)",
             "verified": "Jan 2024", "url": "https://www.hdb.gov.sg/residential/buying-a-flat/financing-your-flat-purchase/housing-loan-from-hdb"},
            {"name": "CPF OA rate + property withdrawal rules", "file": "agents/mortgage_agent.py → CPF_VALUATION_LIMIT_PCT",
             "verified": "Jan 2024", "url": "https://www.cpf.gov.sg/member/home-ownership/using-your-cpf-to-buy-a-home"},
            {"name": "MOP rules (5 years)", "file": "data/mop_tracker.py → MOP_YEARS",
             "verified": "2021 (HDB)", "url": "https://www.hdb.gov.sg/residential/selling-a-flat/eligibility"},
        ]
        import pandas as _pd
        _reg_df = _pd.DataFrame(_REG_SOURCES)
        from datetime import date
        _verified_cache = ROOT / "cache" / "admin_verified.json"
        _verified_log = {}
        if _verified_cache.exists():
            try:
                _verified_log = json.load(open(_verified_cache))
            except Exception:
                pass

        for _, row in _reg_df.iterrows():
            _col1, _col2, _col3, _col4 = st.columns([3, 2, 1, 1])
            _col1.markdown(f"**{row['name']}**  \n`{row['file']}`")
            _last_check = _verified_log.get(row["name"], row["verified"])
            _col2.markdown(f"✅ Verified: {_last_check}")
            _col3.markdown(f"[Open source ↗]({row['url']})")
            if _col4.button("Mark verified ✓", key=f"verify_{row['name'][:15]}"):
                _verified_log[row["name"]] = str(date.today())
                import json as _json2
                _verified_cache.parent.mkdir(parents=True, exist_ok=True)
                _verified_cache.write_text(_json2.dumps(_verified_log))
                st.success(f"Marked '{row['name']}' verified today.")
                st.rerun()
        st.caption("Click 'Open source' to check the official page, then 'Mark verified ✓' to log today's date. Update the code file if rates changed.")

        st.divider()
        st.subheader("🔄 Data Sync")
        col1, col2, col3 = st.columns(3)
        if col1.button("Sync URA Data"):
            from data.ura_pipeline import sync_all_batches
            with st.spinner("Syncing URA..."):
                n = sync_all_batches()
            st.success(f"Synced {n} URA transactions")
        if col2.button("Sync HDB Data"):
            from data.hdb_pipeline import sync_all
            with st.spinner("Syncing HDB..."):
                sync_all()
            st.success("HDB data synced")
        if col3.button("Sync News"):
            from data.news_pipeline import sync_news
            with st.spinner("Fetching news..."):
                articles = sync_news()
            st.success(f"Synced {len(articles)} articles")
    elif admin_pw:
        st.error("Invalid password")

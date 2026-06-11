"""
PropOS Streamlit Dashboard
Tabs: Deal Feed | Valuation | News | Admin (LLM mode + token costs)
Run: streamlit run dashboard/app.py --server.port 8502
"""

import streamlit as st
import json
import sys
import os
from pathlib import Path

# Add project root to path and load .env
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

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

# ── Premium UI Theme ──────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Font only — let Streamlit handle all colors so dark/light mode works ── */
html, body, [class*="css"], button, input, select, textarea {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* ── Layout ── */
.block-container {
    padding: 1.25rem 1.5rem 3rem !important;
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
[data-testid="stSidebar"] .stRadio label { font-size: 0.88rem; }
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
    /* Give room below Streamlit's fixed top bar (~3.5rem) */
    .block-container { padding: 4rem 0.75rem 5rem !important; }
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
    .block-container { padding: 1rem 1.25rem !important; }
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
    tab_select = st.radio(
        "Navigate",
        ["🏠 Address Lookup", "📊 Deal Feed", "🔍 Valuation", "📰 News Intel", "🛡️ Insurance", "🏦 Mortgage", "💹 Tools", "🔔 Watchlist", "🏗️ BTO", "⚙️ Admin"],
    )

# ── Address Lookup ────────────────────────────────────────────────────────────
if tab_select == "🏠 Address Lookup":
    st.header("🏠 Property Address Lookup")
    st.caption("Get real transaction history and market valuation for any Singapore property address")

    prop_category = st.radio("Property type", ["HDB Flat", "Private Condo/Apt (Project Name)"], horizontal=True)

    if prop_category == "HDB Flat":
        st.subheader("HDB Address Lookup")
        st.info("Enter the block number and street name as shown on your flat's address. Example: Block **123A**, Street **TAMPINES ST 11**")

        col1, col2, col3 = st.columns([1, 3, 2])
        with col1:
            block = st.text_input("Block No.", placeholder="e.g. 123A")
        with col2:
            street = st.text_input("Street Name", placeholder="e.g. TAMPINES ST 11")
        with col3:
            flat_type_filter = st.selectbox("Flat Type (optional)", ["Any", "2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"])

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
                    st.subheader("Transaction History (this block)")
                    txns = result.get("recent_transactions", [])
                    if txns:
                        for t in txns:
                            st.write(f"**{t['month']}** — ${t['resale_price']:,.0f} | PSF ${t['psf_sgd']:,.0f} | {t['storey_range']} | {t['floor_area_sqft']:.0f} sqft")

                    # Rental yield estimate
                    st.divider()
                    st.subheader("📈 Estimated Rental Yield")
                    _HDB_TOWN_RENT = {
                        "ANG MO KIO": {"3 ROOM": 2300, "4 ROOM": 2800, "5 ROOM": 3200},
                        "BEDOK": {"3 ROOM": 2200, "4 ROOM": 2700, "5 ROOM": 3100},
                        "BISHAN": {"3 ROOM": 2400, "4 ROOM": 3000, "5 ROOM": 3400},
                        "BUKIT BATOK": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000},
                        "BUKIT MERAH": {"3 ROOM": 2600, "4 ROOM": 3200, "5 ROOM": 3700},
                        "BUKIT PANJANG": {"3 ROOM": 2000, "4 ROOM": 2500, "5 ROOM": 2900},
                        "CENTRAL AREA": {"3 ROOM": 3200, "4 ROOM": 4200, "5 ROOM": 5000},
                        "CHOA CHU KANG": {"3 ROOM": 2000, "4 ROOM": 2500, "5 ROOM": 2900},
                        "CLEMENTI": {"3 ROOM": 2400, "4 ROOM": 2900, "5 ROOM": 3400},
                        "GEYLANG": {"3 ROOM": 2200, "4 ROOM": 2800, "5 ROOM": 3200},
                        "HOUGANG": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000},
                        "JURONG EAST": {"3 ROOM": 2200, "4 ROOM": 2700, "5 ROOM": 3100},
                        "JURONG WEST": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000},
                        "KALLANG/WHAMPOA": {"3 ROOM": 2500, "4 ROOM": 3100, "5 ROOM": 3600},
                        "MARINE PARADE": {"3 ROOM": 2600, "4 ROOM": 3200, "5 ROOM": 3700},
                        "PASIR RIS": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000},
                        "PUNGGOL": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000},
                        "QUEENSTOWN": {"3 ROOM": 2700, "4 ROOM": 3400, "5 ROOM": 3900},
                        "SEMBAWANG": {"3 ROOM": 1900, "4 ROOM": 2400, "5 ROOM": 2800},
                        "SENGKANG": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000},
                        "SERANGOON": {"3 ROOM": 2300, "4 ROOM": 2900, "5 ROOM": 3300},
                        "TAMPINES": {"3 ROOM": 2200, "4 ROOM": 2700, "5 ROOM": 3100},
                        "TOA PAYOH": {"3 ROOM": 2400, "4 ROOM": 3000, "5 ROOM": 3500},
                        "WOODLANDS": {"3 ROOM": 1900, "4 ROOM": 2400, "5 ROOM": 2800},
                        "YISHUN": {"3 ROOM": 2000, "4 ROOM": 2500, "5 ROOM": 2900},
                    }
                    _town_rents = _HDB_TOWN_RENT.get(result["town"], {})
                    # Determine flat type key
                    _ft = result["flat_type"].upper()
                    _rent_key = "5 ROOM" if "EXEC" in _ft or "5" in _ft else ("3 ROOM" if "3" in _ft or "2" in _ft else "4 ROOM")
                    _est_rent = _town_rents.get(_rent_key, _town_rents.get("4 ROOM", 0))
                    _ref_price = result["address_median_price"] or result["latest_transacted_price"]
                    if _est_rent and _ref_price:
                        _gross_yield = round(_est_rent * 12 / _ref_price * 100, 2)
                        _net_yield = round(_gross_yield - 1.2, 2)
                        rc1, rc2, rc3, rc4 = st.columns(4)
                        rc1.metric("Est. Monthly Rent", f"${_est_rent:,}/mo", help=f"Town benchmark for {_rent_key} in {result['town']}")
                        rc2.metric("Annual Rental Income", f"${_est_rent*12:,}")
                        rc3.metric("Gross Yield", f"{_gross_yield}%")
                        rc4.metric("Net Yield (est.)", f"{_net_yield}%", help="After ~1.2% for maintenance, tax, vacancy")
                        st.caption(f"Based on {result['town']} town median rent for {_rent_key}. Actual rental depends on floor, condition, and MRT proximity. HDB Minimum Occupation Period (MOP) must be satisfied before renting.")
                    else:
                        st.caption("Rental benchmark not available for this town/flat type.")

                    # Price + implied yield trend chart
                    st.divider()
                    st.subheader(f"📊 {result['town']} {result['flat_type']} — Price & Implied Yield Trend")
                    st.caption("Price trend uses actual HDB resale transactions. Yield is implied: benchmark rent ÷ monthly median price.")
                    from data.hdb_pipeline import fetch_hdb_resale as _fetch_resale
                    from collections import defaultdict as _dd
                    import pandas as _pd
                    _all_records = _fetch_resale()
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
        st.subheader("Private Property — Project Name Lookup")
        st.info("URA private transaction API endpoint is being updated. While we await the new URL from URA, enter the district and area for a benchmark valuation.")

        col1, col2, col3 = st.columns(3)
        with col1:
            project_hint = st.text_input("Project/Condo Name", placeholder="e.g. The Sail, Bishan 8")
        with col2:
            district = st.number_input("District", 1, 28, 15)
        with col3:
            area_sqft = st.number_input("Area (sqft)", 300, 5000, 1000)

        asking = st.number_input("Asking Price (SGD)", 0, 20000000, 0, step=10000, key="priv_ask")

        if st.button("Get Benchmark Valuation", type="primary"):
            agent = ValuationAgent()
            with st.spinner("Calculating district benchmark..."):
                result = agent.value_private_property(district, area_sqft, asking_price=asking, explain=bool(asking))
            if result.get("status") == "ok":
                st.info(f"📊 Showing District {district} benchmark (project-level data available once URA API is restored)")
                c1, c2, c3 = st.columns(3)
                c1.metric("Estimated Value", f"${result['estimated_value_sgd']:,.0f}")
                c2.metric("Median PSF", f"${result['median_psf']:,.0f}")
                c3.metric("PSF Range", f"${result['p25_psf']:,.0f}–${result['p75_psf']:,.0f}")
                if asking > 0:
                    st.metric("vs District Median", f"{result.get('vs_median_pct',0):+.1f}%", result.get("verdict",""))
                if result.get("explanation"):
                    st.write("**AI Analysis:**", result["explanation"])
            else:
                st.warning(result.get("message", "Insufficient data"))

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

    if val_type == "🏠 HDB Resale":
        from data.hdb_pipeline import fetch_hdb_resale
        records = fetch_hdb_resale()
        towns_available = sorted(set(r['town'] for r in records))
        col1, col2 = st.columns(2)
        with col1:
            town = st.selectbox("Town", towns_available, index=towns_available.index("TAMPINES") if "TAMPINES" in towns_available else 0)
            flat_type = st.selectbox("Flat Type", ["3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"])
        with col2:
            area_sqft = st.number_input("Floor Area (sqft)", 500, 2000, 1000)
            asking_price = st.number_input("Asking Price (SGD, 0 = estimate only)", 0, 2000000, 0, step=5000)

        if st.button("Value HDB", type="primary", key="val_hdb"):
            agent = ValuationAgent()
            with st.spinner("Analysing transactions..."):
                result = agent.value_hdb(town.upper(), flat_type, area_sqft, asking_price, explain=bool(asking_price))
            if result.get("status") == "ok":
                c1, c2, c3 = st.columns(3)
                c1.metric("Estimated Value", f"${result['estimated_value_sgd']:,.0f}")
                c2.metric("Town Median", f"${result['median_price_sgd']:,.0f}")
                c3.metric("Transactions Used", result['transactions_used'])
                if asking_price > 0:
                    st.metric("vs Town Median", f"{result.get('vs_median_pct',0):+.1f}%", delta=result.get('verdict',''))
                    st.info(f"Deal Score: **{result.get('deal_score',0)}/100**")
                if result.get("explanation"):
                    st.write("**AI Analysis:**", result["explanation"])
            else:
                st.warning(result.get("message", "Insufficient data for this town/flat type"))

        # Town price + yield trend
        st.divider()
        st.subheader(f"📈 {town} — Price & Rental Yield Trend ({flat_type})")
        from collections import defaultdict
        import pandas as pd
        _VAL_TOWN_RENT = {
            "ANG MO KIO": {"3 ROOM": 2300, "4 ROOM": 2800, "5 ROOM": 3200, "EXECUTIVE": 3500},
            "BEDOK": {"3 ROOM": 2200, "4 ROOM": 2700, "5 ROOM": 3100, "EXECUTIVE": 3400},
            "BISHAN": {"3 ROOM": 2400, "4 ROOM": 3000, "5 ROOM": 3400, "EXECUTIVE": 3700},
            "BUKIT BATOK": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000, "EXECUTIVE": 3300},
            "BUKIT MERAH": {"3 ROOM": 2600, "4 ROOM": 3200, "5 ROOM": 3700, "EXECUTIVE": 4000},
            "BUKIT PANJANG": {"3 ROOM": 2000, "4 ROOM": 2500, "5 ROOM": 2900, "EXECUTIVE": 3200},
            "CENTRAL AREA": {"3 ROOM": 3200, "4 ROOM": 4200, "5 ROOM": 5000, "EXECUTIVE": 5500},
            "CHOA CHU KANG": {"3 ROOM": 2000, "4 ROOM": 2500, "5 ROOM": 2900, "EXECUTIVE": 3200},
            "CLEMENTI": {"3 ROOM": 2400, "4 ROOM": 2900, "5 ROOM": 3400, "EXECUTIVE": 3700},
            "GEYLANG": {"3 ROOM": 2200, "4 ROOM": 2800, "5 ROOM": 3200, "EXECUTIVE": 3500},
            "HOUGANG": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000, "EXECUTIVE": 3300},
            "JURONG EAST": {"3 ROOM": 2200, "4 ROOM": 2700, "5 ROOM": 3100, "EXECUTIVE": 3400},
            "JURONG WEST": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000, "EXECUTIVE": 3300},
            "KALLANG/WHAMPOA": {"3 ROOM": 2500, "4 ROOM": 3100, "5 ROOM": 3600, "EXECUTIVE": 3900},
            "MARINE PARADE": {"3 ROOM": 2600, "4 ROOM": 3200, "5 ROOM": 3700, "EXECUTIVE": 4000},
            "PASIR RIS": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000, "EXECUTIVE": 3300},
            "PUNGGOL": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000, "EXECUTIVE": 3300},
            "QUEENSTOWN": {"3 ROOM": 2700, "4 ROOM": 3400, "5 ROOM": 3900, "EXECUTIVE": 4200},
            "SEMBAWANG": {"3 ROOM": 1900, "4 ROOM": 2400, "5 ROOM": 2800, "EXECUTIVE": 3100},
            "SENGKANG": {"3 ROOM": 2100, "4 ROOM": 2600, "5 ROOM": 3000, "EXECUTIVE": 3300},
            "SERANGOON": {"3 ROOM": 2300, "4 ROOM": 2900, "5 ROOM": 3300, "EXECUTIVE": 3600},
            "TAMPINES": {"3 ROOM": 2200, "4 ROOM": 2700, "5 ROOM": 3100, "EXECUTIVE": 3400},
            "TOA PAYOH": {"3 ROOM": 2400, "4 ROOM": 3000, "5 ROOM": 3500, "EXECUTIVE": 3800},
            "WOODLANDS": {"3 ROOM": 1900, "4 ROOM": 2400, "5 ROOM": 2800, "EXECUTIVE": 3100},
            "YISHUN": {"3 ROOM": 2000, "4 ROOM": 2500, "5 ROOM": 2900, "EXECUTIVE": 3200},
        }
        _ft_key = flat_type if flat_type in ("3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE") else "4 ROOM"
        _bench_rent = _VAL_TOWN_RENT.get(town.upper(), {}).get(_ft_key, 0)
        town_records = [r for r in records if r['town'] == town and _ft_key.lower() in r['flat_type'].lower() and r.get('resale_price', 0) > 0]
        if town_records:
            monthly: dict = defaultdict(list)
            for r in town_records:
                monthly[r['month']].append(r['resale_price'])
            months_sorted = sorted(monthly.keys())[-18:]
            med_prices = [sorted(monthly[m])[len(monthly[m]) // 2] for m in months_sorted]
            impl_yields = [round(_bench_rent * 12 / p * 100, 2) if _bench_rent and p else 0 for p in med_prices]

            vt1, vt2, vt3 = st.tabs(["💰 Median Price", "🏘️ Est. Monthly Rent", "📈 Implied Gross Yield"])
            with vt1:
                st.line_chart(pd.DataFrame({"Median Price (SGD)": med_prices}, index=months_sorted))
                st.caption(f"Median resale prices for {flat_type} in {town} — last {len(months_sorted)} months")
            with vt2:
                if _bench_rent:
                    # Benchmark rent is static — show as flat reference line alongside price context
                    st.metric("Benchmark Monthly Rent", f"${_bench_rent:,}/mo", help=f"SRX 2024–25 median for {_ft_key} in {town}")
                    st.metric("Estimated Annual Rental Income", f"${_bench_rent * 12:,}")
                    st.info(f"Rental benchmark for **{_ft_key}** in **{town}**: **${_bench_rent:,}/month**. "
                            f"This is a town-level median from SRX 2024–25 data. "
                            f"Actual rent varies by floor, condition, and MRT proximity. "
                            f"Once deployed to Singapore VPS, URA rental transaction data will replace this estimate.")
                else:
                    st.info("No rental benchmark for this town/flat type.")
            with vt3:
                if _bench_rent:
                    st.line_chart(pd.DataFrame({"Gross Yield (%)": impl_yields}, index=months_sorted))
                    st.caption(f"Implied yield = ${_bench_rent:,}/mo benchmark ÷ monthly median price. "
                               f"Current implied yield: **{impl_yields[-1]:.2f}%** gross / **{round(impl_yields[-1]-1.2, 2):.2f}%** net.")
                else:
                    st.info("No rental benchmark for this town/flat type.")

    elif val_type == "🏢 Private Condo/Apt":
        from data.ura_pipeline import get_district_stats
        # Show which districts have data
        districts_with_data = []
        for d in range(1, 29):
            s = get_district_stats(d)
            if s.get("count", 0) >= 5:
                districts_with_data.append((d, s["count"], s["median_psf"]))

        if not districts_with_data:
            st.warning("No URA private transaction data cached yet. URA API is blocked from non-Singapore IPs. Deploy to Singapore VPS to sync data.")
            st.info("**Workaround:** Use HDB Resale tab or Address Lookup for now. URA private data will be available after VPS deployment.")
        else:
            district_options = {f"D{d} — {cnt} txns, median ${psf:,.0f} PSF": d for d, cnt, psf in districts_with_data}
            col1, col2 = st.columns(2)
            with col1:
                selected = st.selectbox("District (with data)", list(district_options.keys()))
                district = district_options[selected]
                area_sqft = st.number_input("Area (sqft)", 300, 5000, 1000, key="priv_area")
            with col2:
                property_type = st.selectbox("Type", ["Condominium", "Apartment", "Executive Condominium"])
                asking_price = st.number_input("Asking Price (SGD)", 0, 10000000, 0, step=10000, key="priv_ask2")

            if st.button("Value Property", type="primary", key="val_priv"):
                agent = ValuationAgent()
                with st.spinner("Analysing URA transactions..."):
                    result = agent.value_private_property(district, area_sqft, property_type, asking_price, explain=bool(asking_price))
                if result.get("status") == "ok":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Estimated Value", f"${result['estimated_value_sgd']:,.0f}")
                    c2.metric("Median PSF", f"${result['median_psf']:,.0f}")
                    c3.metric("PSF Range", f"${result['p25_psf']:,.0f}–${result['p75_psf']:,.0f}")
                    if asking_price > 0:
                        st.metric("vs District Median", f"{result.get('vs_median_pct',0):+.1f}%", delta=result.get('verdict',''))
                    if result.get("explanation"):
                        st.write("**AI Analysis:**", result["explanation"])
                else:
                    st.warning(result.get("message", "Insufficient data"))

    else:  # Heatmap
        st.subheader("🗺️ HDB Market Intelligence — All Towns")
        from data.hdb_pipeline import fetch_hdb_resale, get_town_stats
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

        records = fetch_hdb_resale()
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
                st.bar_chart(df.set_index("Town")["Median PSF"])

            with hm_tab2:
                yield_df = df.sort_values("Gross Yield %", ascending=False)
                rc1, rc2 = st.columns(2)
                with rc1:
                    st.subheader("Est. Monthly Rent (SGD)")
                    st.bar_chart(yield_df.set_index("Town")["Est Monthly Rent"])
                    st.caption(f"Scaled from 4-room SRX benchmarks × {_scale:.2f} for {hm_flat}.")
                with rc2:
                    st.subheader("Gross Rental Yield (%)")
                    st.bar_chart(yield_df.set_index("Town")["Gross Yield %"])
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
                has_mrta = c9.checkbox("MRTA/MLTA?", key=f"ins_mrta_{i}") if has_mortgage else False

                mrta_coverage = 0
                if has_mrta and has_mortgage:
                    mrta_coverage = st.number_input("MRTA/MLTA Coverage (SGD)", 0, 5000000, outstanding_loan, step=10000, key=f"ins_mrta_cov_{i}")

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
                    st.warning(f"🛡️ **MRTA Review Recommended**\n\n{alert['message']}")
                    if st.button("💬 Get MRTA Quote", key="mrta_from_refi"):
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
                f"an MRTA policy typically costs **SGD 2,000–5,000** as a one-time premium "
                f"and pays off your outstanding mortgage if you pass away or become critically ill. "
                f"Your family keeps the home — not just the debt."
            )
            if st.button("💬 Run MRTA Analysis", key="mrta_from_aff"):
                st.info("Head to the 🛡️ Insurance tab → Analyse to build your full insurance portfolio including MRTA/MLTA coverage.")

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
                f"With SGD {loan:,.0f} in mortgage financing, an MRTA policy ensures "
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

    with st.expander("ℹ️ How to use Watchlist alerts", expanded=False):
        st.markdown("""
**What it does**

Set up a saved search (e.g. *Tampines 4-room under SGD 600,000*). Every hour, PropOS automatically scans the latest HDB resale transactions and alerts you when a matching deal appears — especially ones priced below the market median.

**Step-by-step:**
1. **Enter your Telegram ID** below (get it by messaging @userinfobot on Telegram)
2. Go to **➕ Add Watch** → set your town, flat type, max price, and alert threshold
3. Save it — PropOS checks automatically every hour
4. You'll receive a Telegram message via **@askAceBot** when a match is found

**Alert threshold explained**

- Set to **0%** → alert on any transaction matching your criteria
- Set to **5%** → only alert when PSF is 5% or more below the town median (deals only)
- Set to **10%+** → only the sharpest deals

**Your Telegram ID**

Open Telegram → message **@userinfobot** → it replies with your numeric ID (e.g. `1245366658`). Enter that below to receive alerts.

> ⚠️ Currently covers **HDB resale transactions** only. Private condo watchlist coming soon.
        """)

    init_watchlist_db()

    _user_id = st.text_input(
        "Your Telegram ID (for alerts) — message @userinfobot to find yours",
        value=str(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")),
        placeholder="e.g. 1245366658",
        key="wl_user_id",
    )

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
            st.markdown("### 🛡️ New BTO buyers: don't forget MRTA")
            st.markdown(
                "If you're taking an HDB or bank loan for your BTO, an MRTA policy ensures your family "
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
        st.subheader("💰 Token Cost Tracker")
        costs = get_token_summary()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Cost (USD)", f"${costs['total_cost_usd']:.4f}")
        c2.metric("Total Cost (SGD)", f"${costs['est_sgd']:.4f}")
        c3.metric("Total Tokens Used", f"{costs['total_tokens']:,}")
        st.metric("API Calls Made", costs["call_count"])

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

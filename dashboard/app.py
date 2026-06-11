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
from core.llm_router import save_mode, get_current_mode, get_token_summary
from data.news_pipeline import get_sentiment_index

st.set_page_config(
    page_title="PropertyOS",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🏠 PropertyOS")
    st.caption("Singapore Property Intelligence")

    mode_info = get_current_mode()
    mode_colors = {"free": "🟢", "balanced": "🟡", "quality": "🔵", "premium": "🟣"}
    st.info(f"{mode_colors.get(mode_info['mode'], '⚪')} LLM: **{mode_info['mode'].upper()}** — {mode_info['model']}")

    st.divider()
    tab_select = st.radio(
        "Navigate",
        ["🏠 Address Lookup", "📊 Deal Feed", "🔍 Valuation", "📰 News Intel", "🛡️ Insurance", "⚙️ Admin"],
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
        st.info(
            "**Requires Singapore VPS deployment.**\n\n"
            "URA's private transaction API (PMI_Resi_Transaction) is blocked from non-Singapore IPs. "
            "Once PropOS is deployed to a Hetzner CPX12 Singapore VPS, this scanner will:\n\n"
            "• Scan all 28 districts for condos/apartments trading below district median PSF\n"
            "• Flag deals ≥8% below median as opportunities\n"
            "• Show project name, street, discount %, potential upside SGD, and AI deal summary\n"
            "• Cover new launches, subsale, and resale across freehold and leasehold\n\n"
            "**To unlock:** Order Hetzner CPX12 Singapore → `python scripts/sync_ura.py` → restart dashboard."
        )
        st.caption("HDB deals above are fully functional now — private condo data needs Singapore IP for URA API access.")

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

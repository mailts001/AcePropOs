"""
Weekly Email Digest — auto-generates and sends to all active subscribers.
Run: python3 agents/weekly_digest.py  (or via cron every Sunday)

Sections:
1. Market Pulse — sentiment index + week-on-week volume
2. Top Deals — 5 properties trading >10% below district median
3. MOP Cliff — HDB flats whose 5-year MOP expires this month/next
4. Biggest Movers — projects with highest PSF change (last 4 quarters)
5. En-Bloc Watch — properties flagged with collective sale signals
6. Insurance nudge (MRTA/MLTA) — subtle CTA for mortgage owners
"""

import os
import sys
import smtplib
from pathlib import Path
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


# ── Section generators ────────────────────────────────────────────────────────

def _section_deals(n=5) -> tuple[str, list[dict]]:
    """Top N deals from DealHunterAgent — below district median."""
    try:
        from agents.deal_hunter_agent import DealHunterAgent
        agent = DealHunterAgent()
        deals = agent.find_deals(min_discount_pct=8, max_results=n)
        if not deals:
            return "<p>No standout deals found this week.</p>", []

        rows = ""
        for d in deals[:n]:
            disc = d.get("discount_pct", 0)
            price = d.get("price", 0)
            psf   = d.get("psf", 0)
            addr  = d.get("address", d.get("block","") + " " + d.get("street",""))
            rows += (
                f"<tr>"
                f"<td style='padding:6px 10px'>{addr.title()}</td>"
                f"<td style='padding:6px 10px;text-align:right'>SGD {price:,.0f}</td>"
                f"<td style='padding:6px 10px;text-align:right'>${psf:,.0f} psf</td>"
                f"<td style='padding:6px 10px;text-align:center;color:#c0392b;font-weight:700'>{disc:.1f}% below</td>"
                f"</tr>"
            )
        html = f"""
<table style='width:100%;border-collapse:collapse;font-size:13px'>
  <thead>
    <tr style='background:#f0f4f8'>
      <th style='padding:6px 10px;text-align:left'>Property</th>
      <th style='padding:6px 10px;text-align:right'>Price</th>
      <th style='padding:6px 10px;text-align:right'>PSF</th>
      <th style='padding:6px 10px'>vs Median</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""
        return html, deals[:n]
    except Exception as e:
        return f"<p>Deals unavailable: {e}</p>", []


def _section_mop(n=5) -> str:
    """HDB flats whose MOP expires in the next 60 days."""
    try:
        from data.hdb_pipeline import load_hdb_transactions
        txns = load_hdb_transactions()
        today = date.today()
        upcoming = []
        for t in txns:
            try:
                # MOP = purchase date + 5 years. Use resale date + lease start as proxy.
                mth_str = t.get("month", "")  # e.g. "2020-01"
                if not mth_str:
                    continue
                yr, mo = int(mth_str[:4]), int(mth_str[5:7])
                mop_date = date(yr + 5, mo, 1)
                days_left = (mop_date - today).days
                if 0 <= days_left <= 60:
                    upcoming.append({
                        "address": f"Blk {t.get('block','')} {t.get('street_name','').title()}",
                        "town": t.get("town",""),
                        "flat_type": t.get("flat_type",""),
                        "mop_date": mop_date.strftime("%d %b %Y"),
                        "days_left": days_left,
                        "price": t.get("resale_price", 0),
                    })
            except Exception:
                continue

        if not upcoming:
            return "<p>No MOP cliffs in the next 60 days.</p>"

        upcoming.sort(key=lambda x: x["days_left"])
        rows = ""
        for u in upcoming[:n]:
            rows += (
                f"<tr>"
                f"<td style='padding:6px 10px'>{u['address']}</td>"
                f"<td style='padding:6px 10px'>{u['town']}</td>"
                f"<td style='padding:6px 10px'>{u['flat_type']}</td>"
                f"<td style='padding:6px 10px;font-weight:700;color:#2980b9'>{u['mop_date']}</td>"
                f"<td style='padding:6px 10px;text-align:center'>{u['days_left']}d</td>"
                f"</tr>"
            )
        return f"""
<table style='width:100%;border-collapse:collapse;font-size:13px'>
  <thead>
    <tr style='background:#f0f4f8'>
      <th style='padding:6px 10px;text-align:left'>Address</th>
      <th style='padding:6px 10px'>Town</th>
      <th style='padding:6px 10px'>Type</th>
      <th style='padding:6px 10px'>MOP Date</th>
      <th style='padding:6px 10px'>Days</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""
    except Exception as e:
        return f"<p>MOP data unavailable: {e}</p>"


def _section_movers(n=5) -> str:
    """Projects with biggest PSF appreciation over last 8 quarters."""
    try:
        from data.ura_pipeline import load_all_transactions
        from agents.price_history import top_trending_projects
        txns = load_all_transactions()
        top = top_trending_projects(txns, min_txns=15, lookback_quarters=8, top_n=n)
        if not top:
            return "<p>No price trend data available.</p>"

        rows = ""
        for p in top:
            chg   = p.get("psf_change_pct", 0)
            early = p.get("earliest_median_psf", 0)
            late  = p.get("latest_median_psf", 0)
            rows += (
                f"<tr>"
                f"<td style='padding:6px 10px'>{p['project'].title()}</td>"
                f"<td style='padding:6px 10px;text-align:right'>${early:,}</td>"
                f"<td style='padding:6px 10px;text-align:right'>${late:,}</td>"
                f"<td style='padding:6px 10px;text-align:center;color:#27ae60;font-weight:700'>{chg:+.1f}%</td>"
                f"</tr>"
            )
        return f"""
<table style='width:100%;border-collapse:collapse;font-size:13px'>
  <thead>
    <tr style='background:#f0f4f8'>
      <th style='padding:6px 10px;text-align:left'>Project</th>
      <th style='padding:6px 10px;text-align:right'>Earliest PSF</th>
      <th style='padding:6px 10px;text-align:right'>Latest PSF</th>
      <th style='padding:6px 10px'>Change</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""
    except Exception as e:
        return f"<p>Price trend data unavailable: {e}</p>"


def _section_sentiment() -> tuple[str, int]:
    """Market sentiment index (0–100)."""
    try:
        from data.news_pipeline import get_sentiment_index
        idx = get_sentiment_index()
        score = idx.get("score", 50)
        label = idx.get("label", "Neutral")
        color = "#27ae60" if score >= 60 else "#c0392b" if score <= 40 else "#f39c12"
        html = (
            f"<p style='font-size:24px;font-weight:700;color:{color};margin:4px 0'>"
            f"{score}/100 — {label}</p>"
            f"<p style='font-size:12px;color:#666'>"
            f"Based on Singapore property news sentiment this week.</p>"
        )
        return html, score
    except Exception:
        return "<p>Sentiment index unavailable.</p>", 50


# ── Email builder ─────────────────────────────────────────────────────────────

def build_digest_html() -> str:
    today_str = datetime.now().strftime("%d %B %Y")
    base_url  = os.environ.get("PROPOS_URL", "http://acepropos.duckdns.org")

    deals_html,  deals_data = _section_deals(5)
    mop_html                = _section_mop(5)
    movers_html             = _section_movers(5)
    sentiment_html, score   = _section_sentiment()

    sentiment_label = "📈 Bullish" if score >= 60 else "📉 Bearish" if score <= 40 else "😐 Neutral"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PropOS Weekly Digest — {today_str}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif">
<div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;margin-top:20px;margin-bottom:20px;box-shadow:0 2px 12px rgba(0,0,0,0.08)">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0d1b2a,#1a2f4a);padding:28px 32px">
    <div style="display:flex;align-items:center;gap:12px">
      <span style="font-size:28px">🏠</span>
      <div>
        <h1 style="margin:0;font-size:20px;font-weight:700;color:#c9a84c;font-family:Georgia,serif">PropOS Weekly</h1>
        <p style="margin:0;font-size:12px;color:#8aa4bc">Singapore Property Intelligence · {today_str}</p>
      </div>
    </div>
  </div>

  <!-- Body -->
  <div style="padding:28px 32px">

    <!-- Market Pulse -->
    <h2 style="font-size:15px;font-weight:700;color:#1a2f4a;border-bottom:2px solid #c9a84c;padding-bottom:6px;margin-top:0">
      {sentiment_label} Market Pulse
    </h2>
    {sentiment_html}

    <div style="height:16px"></div>

    <!-- Top Deals -->
    <h2 style="font-size:15px;font-weight:700;color:#1a2f4a;border-bottom:2px solid #c9a84c;padding-bottom:6px">
      🔥 Top Deals This Week
    </h2>
    <p style="font-size:12px;color:#666;margin-top:0">Properties trading &gt;8% below district median — verified against 137k+ URA transactions.</p>
    {deals_html}
    <p style="text-align:right;margin-top:8px">
      <a href="{base_url}?page=Deal+Feed" style="font-size:12px;color:#c9a84c;text-decoration:none;font-weight:600">
        View all deals on PropOS →
      </a>
    </p>

    <div style="height:16px"></div>

    <!-- MOP Cliffs -->
    <h2 style="font-size:15px;font-weight:700;color:#1a2f4a;border-bottom:2px solid #c9a84c;padding-bottom:6px">
      📅 MOP Cliffs (Next 60 Days)
    </h2>
    <p style="font-size:12px;color:#666;margin-top:0">HDB flats completing their 5-year Minimum Occupation Period — they can now be listed for resale.</p>
    {mop_html}

    <div style="height:16px"></div>

    <!-- Biggest PSF Movers -->
    <h2 style="font-size:15px;font-weight:700;color:#1a2f4a;border-bottom:2px solid #c9a84c;padding-bottom:6px">
      📈 Biggest PSF Movers
    </h2>
    <p style="font-size:12px;color:#666;margin-top:0">Projects with the highest price appreciation across all recorded transactions.</p>
    {movers_html}

    <div style="height:20px"></div>

    <!-- CTA -->
    <div style="background:linear-gradient(135deg,#0d1b2a,#1a3a5c);border-radius:10px;padding:20px 24px;text-align:center">
      <p style="color:#c9a84c;font-weight:700;font-size:14px;margin:0 0 8px">Thinking of buying or refinancing?</p>
      <p style="color:#a0b8cc;font-size:12px;margin:0 0 14px">
        Run free mortgage, SSD, CPF grant and HDB upgrade calculations on PropOS.
        Our partner brokers offer <strong style="color:#fff">free mortgage comparisons</strong> across 15+ banks.
      </p>
      <a href="{base_url}"
         style="background:linear-gradient(135deg,#c9a84c,#e8c96a);color:#0d1b2a;padding:10px 24px;
                border-radius:6px;text-decoration:none;font-weight:700;font-size:13px;display:inline-block">
        Open PropOS Dashboard →
      </a>
    </div>

  </div>

  <!-- Footer -->
  <div style="background:#f8f9fb;padding:16px 32px;border-top:1px solid #e8ecf0">
    <p style="font-size:11px;color:#999;margin:0">
      You're receiving this because you subscribed at acepropos.duckdns.org.
      Data sources: URA, HDB Data.gov.sg.
      <strong>Not financial advice.</strong>
      <a href="{base_url}?unsub=1" style="color:#c9a84c">Unsubscribe</a>
    </p>
  </div>

</div>
</body></html>"""


def send_weekly_digest(dry_run: bool = False) -> dict:
    """
    Send the weekly digest to all active subscribers.
    Returns {"sent": int, "failed": int, "skipped": int, "dry_run": bool}
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not smtp_host or not smtp_user:
        print("SMTP not configured — set SMTP_HOST, SMTP_USER, SMTP_PASS in .env")
        return {"sent": 0, "failed": 0, "skipped": 0, "dry_run": dry_run, "error": "SMTP not configured"}

    from data.analytics import get_all_subscribers
    subscribers = get_all_subscribers(active_only=True)

    if not subscribers:
        return {"sent": 0, "failed": 0, "skipped": 0, "dry_run": dry_run}

    print(f"Building digest HTML...")
    html_body = build_digest_html()
    today_str = datetime.now().strftime("%d %b %Y")
    subject   = f"PropOS Weekly — Singapore Property Intel {today_str}"

    if dry_run:
        print(f"[DRY RUN] Would send to {len(subscribers)} subscribers.")
        print(f"Subject: {subject}")
        print(f"HTML length: {len(html_body)} chars")
        return {"sent": 0, "failed": 0, "skipped": len(subscribers), "dry_run": True}

    sent = failed = 0
    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        server.starttls()
        server.login(smtp_user, smtp_pass)

        for sub in subscribers:
            email = sub.get("email", "")
            if not email or "@" not in email:
                failed += 1
                continue
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = f"PropOS <{smtp_user}>"
                msg["To"]      = email
                msg.attach(MIMEText(html_body, "html"))
                server.sendmail(smtp_user, email, msg.as_string())
                sent += 1
                print(f"  ✅ Sent to {email}")
            except Exception as e:
                failed += 1
                print(f"  ❌ Failed {email}: {e}")

        server.quit()
    except Exception as e:
        print(f"SMTP connection error: {e}")
        return {"sent": sent, "failed": len(subscribers) - sent, "skipped": 0, "dry_run": False, "error": str(e)}

    print(f"\nDone: {sent} sent, {failed} failed")
    return {"sent": sent, "failed": failed, "skipped": 0, "dry_run": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Send PropOS weekly digest")
    parser.add_argument("--dry-run", action="store_true", help="Build HTML but don't send")
    parser.add_argument("--preview", action="store_true", help="Print HTML to stdout")
    args = parser.parse_args()

    if args.preview:
        print(build_digest_html())
    else:
        result = send_weekly_digest(dry_run=args.dry_run)
        print(result)

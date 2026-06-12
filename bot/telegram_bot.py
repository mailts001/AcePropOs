"""
PropOS Telegram Bot — Acquisition Funnel
=========================================
Onboarding flow:
  /start → rich welcome + inline keyboard
  → "Subscribe for alerts" → bot asks for email → saves to DB → welcome email

Commands:
  /start       — onboarding with inline buttons
  /deals       — top 3 private deals below median
  /hdb [town] [type] — HDB below-market deals
  /news        — market sentiment + headlines
  /value D15 1000 1500000 — quick district valuation
  /alert add 521234 800000 — set price watchlist
  /alert list  — show my alerts
  /alert del 1 — remove alert by ID
  /mop 521234  — MOP countdown for an address
  /ssd 800000 2024-03-01 — SSD timer
  /calc        — calculator menu (mortgage/tax/refi/yield)
  /subscribe   — subscribe to email digest
  /status      — system health
  /admin       — admin menu (admin only)
"""

import os
import sys
import logging
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from telegram import (
    Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
)
from telegram.constants import ParseMode

from agents.deal_hunter_agent import DealHunterAgent
from agents.valuation_agent import ValuationAgent
from agents.news_intel_agent import NewsIntelAgent
from data.news_pipeline import get_sentiment_index
from data.hdb_pipeline import find_below_market_hdb

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("propos_bot")

BOT_TOKEN        = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID    = int(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "1245366658"))
DEALS_CHANNEL_ID = os.environ.get("TELEGRAM_DEALS_CHANNEL_ID", "-1004221326153")
DASHBOARD_URL    = os.environ.get("PROPOS_URL", "https://acepropos.duckdns.org")

# ConversationHandler states
ASK_EMAIL = 1


def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_CHAT_ID


def _dashboard_link(page: str = "", tg_id: int = 0) -> str:
    """Build dashboard URL with optional page + Telegram attribution."""
    url = DASHBOARD_URL
    if tg_id:
        url += f"?tg={tg_id}"
    return url


# ── /start — rich onboarding ──────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    name  = user.first_name or "there"
    tg_id = user.id

    keyboard = [
        [InlineKeyboardButton("🔥 Today's Deals",       callback_data="quick_deals"),
         InlineKeyboardButton("📊 Market Pulse",        callback_data="quick_news")],
        [InlineKeyboardButton("🏠 HDB Deals",           callback_data="quick_hdb"),
         InlineKeyboardButton("💰 Quick Valuation",     callback_data="quick_value_help")],
        [InlineKeyboardButton("⏳ SSD Timer",            callback_data="quick_ssd_help"),
         InlineKeyboardButton("📅 MOP Check",           callback_data="quick_mop_help")],
        [InlineKeyboardButton("🧮 Calculators",         callback_data="quick_calc"),
         InlineKeyboardButton("🔔 Set Price Alert",     callback_data="quick_alert_help")],
        [InlineKeyboardButton("📬 Subscribe to Digest", callback_data="subscribe_start")],
        [InlineKeyboardButton("📊 Open Full Dashboard →", url=_dashboard_link(tg_id=tg_id))],
    ]

    await update.message.reply_text(
        f"🏠 *Welcome to PropOS, {name}!*\n"
        f"_Singapore's AI Property Intelligence_\n\n"
        f"*What I can do for you:*\n"
        f"• 🔥 Scan for deals trading below district median\n"
        f"• 📊 Daily market sentiment + news headlines\n"
        f"• 💰 Instant property valuations\n"
        f"• 🔔 Price alerts — I'll notify you when a match appears\n"
        f"• ⏳ SSD timer — know when to sell penalty-free\n"
        f"• 📅 MOP countdown — track your resale eligibility date\n"
        f"• 🧮 Mortgage, tax, refi & rental yield calculators\n\n"
        f"*Choose an action below or type a command:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )


# ── Email subscription conversation ──────────────────────────────────────────

async def subscribe_ask_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point for email subscription — triggered by /subscribe or inline button."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text(
            "📬 *Subscribe to PropOS Weekly Digest*\n\n"
            "You'll get:\n"
            "• Top deals below district median\n"
            "• MOP cliffs this month\n"
            "• Biggest PSF movers\n"
            "• Market pulse summary\n\n"
            "Please reply with your *email address* to subscribe:",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "📬 Please reply with your *email address* to subscribe to the weekly digest:",
            parse_mode=ParseMode.MARKDOWN,
        )
    return ASK_EMAIL


async def subscribe_save_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Save email to subscribers DB and send welcome email."""
    email = update.message.text.strip().lower()
    user  = update.effective_user
    tg_id = user.id

    if "@" not in email or "." not in email:
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid email. Please try again or /cancel to stop."
        )
        return ASK_EMAIL

    try:
        from data.analytics import add_subscriber, resubscribe_email, mark_welcome_sent
        result = add_subscriber(email, source=f"telegram_{tg_id}")
        if not result["new"]:
            resubscribe_email(email)
            await update.message.reply_text(
                f"✅ You're already subscribed! Re-activated.\n"
                f"Total subscribers: {result['total']}"
            )
        else:
            # Try to send welcome email
            sent = _send_welcome_email_sync(email)
            if sent:
                mark_welcome_sent(email)
            await update.message.reply_text(
                f"🎉 *Subscribed!* Welcome to PropOS Weekly.\n\n"
                f"You'll receive your first digest this Sunday.\n"
                f"Your Telegram ID `{tg_id}` is linked — set price alerts with:\n"
                f"`/alert add <postal_code> <max_price>`\n\n"
                f"📊 {_dashboard_link(tg_id=tg_id)}",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            # Notify admin
            try:
                await ctx.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"🆕 New subscriber via Telegram: `{email}` (@{user.username or 'no-username'}, ID {tg_id})",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
    except Exception as e:
        log.error(f"Subscribe save error: {e}")
        await update.message.reply_text(f"❌ Error saving subscription: {e}")

    return ConversationHandler.END


async def subscribe_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /subscribe anytime.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def _send_welcome_email_sync(email: str) -> bool:
    """Synchronous welcome email sender for use inside async handlers."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    if not smtp_host or not smtp_user:
        return False
    try:
        html = f"""<html><body style="font-family:Inter,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;padding:32px">
  <h2 style="color:#1a1a2e">Welcome to PropOS 🏡</h2>
  <p>You subscribed via the PropOS Telegram bot — great choice!</p>
  <p>Every Sunday you'll get the Singapore property digest: deals, MOP cliffs, price movers.</p>
  <p>Meanwhile, explore the full free dashboard:</p>
  <a href="{DASHBOARD_URL}" style="background:#c8a84b;color:#fff;padding:10px 20px;border-radius:6px;
     text-decoration:none;font-weight:700;display:inline-block">Open PropOS →</a>
  <p style="font-size:12px;color:#999;margin-top:24px">Not financial advice. Unsubscribe anytime.</p>
</div></body></html>"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Welcome to PropOS — Singapore Property Intelligence"
        msg["From"]    = smtp_user
        msg["To"]      = email
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, email, msg.as_string())
        return True
    except Exception:
        return False


# ── /deals ────────────────────────────────────────────────────────────────────

async def cmd_deals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Scanning transactions… (10–20s)")
    try:
        agent  = DealHunterAgent()
        result = agent.scan_private_deals(threshold_pct=8.0, limit=5, summarise=True)
        deals  = result.get("top_deals", [])
        if not deals:
            await update.message.reply_text("No deals above threshold found today. Check back tomorrow!")
            return
        lines = ["🏠 *Today's Top Private Property Deals*\n"]
        for i, d in enumerate(deals[:3], 1):
            lines.append(
                f"*{i}. {d['project']} — D{d['district']}*\n"
                f"  📉 {d['discount_pct']}% below district median\n"
                f"  💰 PSF: ${d['psf_sgd']:,.0f} vs median ${d['median_psf']:,.0f}\n"
                f"  📐 {d['area_sqft']:.0f} sqft | {d['property_type']}\n"
                f"  ⭐ Score: {d['deal_score']}/100\n"
            )
        if result.get("summary"):
            lines.append(f"\n📝 _{result['summary']}_")
        lines.append(f"\n🔓 [Full deal feed + set alerts →]({DASHBOARD_URL})")
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(f"Error scanning deals: {e}")


# ── /hdb ─────────────────────────────────────────────────────────────────────

async def cmd_hdb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args      = ctx.args
    town      = args[0].upper().replace("-", " ") if args else None
    flat_type = " ".join(args[1:]).upper() if len(args) > 1 else None
    await update.message.reply_text("🔍 Scanning HDB resale transactions…")
    try:
        deals = find_below_market_hdb(town=town, flat_type=flat_type, threshold_pct=5.0, limit=5)
        if not deals:
            await update.message.reply_text(
                "No below-market HDB deals found" + (f" in {town}" if town else "") +
                " right now.\nTry: `/hdb TAMPINES` or `/hdb WOODLANDS 4 ROOM`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        lines = [f"🏠 *HDB Below-Market Deals*" + (f" — {town}" if town else "") + "\n"]
        for i, d in enumerate(deals[:3], 1):
            lines.append(
                f"*{i}. {d['town']} {d['flat_type']}*\n"
                f"  📍 {d['block']} {d['street_name']}, {d.get('storey_range','')}\n"
                f"  💰 SGD {d['resale_price']:,.0f} — {d['discount_pct']:.1f}% below median PSF\n"
                f"  📐 {d['floor_area_sqm']:.0f} sqm | PSF {d['psf']:,.0f} vs {d['median_psf']:,.0f}\n"
            )
        lines.append(f"🔓 [Set price alerts →]({DASHBOARD_URL})")
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ── /news ─────────────────────────────────────────────────────────────────────

async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        agent = NewsIntelAgent()
        msg   = agent.format_telegram_daily()
        await update.message.reply_text(
            msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ── /value ────────────────────────────────────────────────────────────────────

async def cmd_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/value [district] [sqft] [asking_price]`\nExample: `/value 15 1000 1500000`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        district     = int(str(args[0]).replace("D","").replace("d",""))
        area_sqft    = float(args[1])
        asking_price = float(args[2]) if len(args) >= 3 else 0
        agent  = ValuationAgent()
        result = agent.value_private_property(district, area_sqft, asking_price=asking_price, explain=False)
        if result.get("status") != "ok":
            await update.message.reply_text(result.get("message", "Insufficient data."))
            return
        lines = [
            f"🏠 *Valuation — District {district}*\n",
            f"📐 Area: {area_sqft:.0f} sqft",
            f"💰 Estimated Value: *SGD {result['estimated_value_sgd']:,.0f}*",
            f"📊 Median PSF: ${result['median_psf']:,.0f} | Range: ${result['p25_psf']:,.0f}–${result['p75_psf']:,.0f}",
            f"🔢 Based on {result['transactions_used']} transactions | Confidence: {result['confidence']}",
        ]
        if asking_price > 0:
            lines += [
                f"\n💬 Asking: SGD {asking_price:,.0f}",
                f"📈 vs Median: {result['vs_median_pct']:+.1f}%",
                f"⭐ Deal Score: {result['deal_score']}/100",
                f"📝 {result['verdict']}",
            ]
        lines.append(f"\n🔓 [Full analysis →]({DASHBOARD_URL})")
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    except (ValueError, IndexError) as e:
        await update.message.reply_text(f"Invalid input. Try: `/value 15 1000 1500000`", parse_mode=ParseMode.MARKDOWN)


# ── /alert ────────────────────────────────────────────────────────────────────

async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /alert add 521234 800000   — watch postal code, alert when price ≤ 800k
    /alert add TAMPINES 4ROOM 500000 — HDB town+type alert
    /alert list                — show all my alerts
    /alert del 3               — delete alert by ID
    """
    args    = ctx.args
    tg_id   = str(update.effective_user.id)
    chat_id = update.effective_chat.id

    if not args:
        await update.message.reply_text(
            "🔔 *Price Alert Commands*\n\n"
            "Add alert:  `/alert add 521234 800000`\n"
            "Add HDB:    `/alert add TAMPINES 4ROOM 500000`\n"
            "List alerts: `/alert list`\n"
            "Delete:     `/alert del 1`\n\n"
            "I'll message you when a matching property appears in the deal feed.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    action = args[0].lower()

    if action == "add":
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: `/alert add <postal_or_town> <max_price>`\nExample: `/alert add 521234 800000`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            from data.watchlist import add_watch
            target   = args[1]
            max_price = float(args[-1].replace(",",""))
            flat_type = args[2].upper() if len(args) == 4 else ""
            watch_id = add_watch(
                telegram_id=tg_id,
                chat_id=str(chat_id),
                address=target,
                flat_type=flat_type,
                max_price=max_price,
                source="telegram",
            )
            await update.message.reply_text(
                f"✅ *Alert set!*\n"
                f"📍 Location: {target}" + (f" {flat_type}" if flat_type else "") + "\n"
                f"💰 Max price: SGD {max_price:,.0f}\n"
                f"🔔 I'll notify you here when a match appears.\n\n"
                f"Manage alerts: `/alert list` | Remove: `/alert del {watch_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await update.message.reply_text(f"Error setting alert: {e}")

    elif action == "list":
        try:
            from data.watchlist import list_watches
            alerts = list_watches(telegram_id=tg_id)
            if not alerts:
                await update.message.reply_text(
                    "You have no active alerts.\nAdd one: `/alert add 521234 800000`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            lines = ["🔔 *Your Active Price Alerts*\n"]
            for a in alerts:
                lines.append(
                    f"*{a['id']}.* {a.get('address','')} {a.get('flat_type','')} "
                    f"≤ SGD {float(a.get('max_price',0)):,.0f}"
                )
            lines.append("\nRemove with `/alert del <ID>`")
            await update.message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    elif action == "del":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/alert del <ID>`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            from data.watchlist import delete_watch
            alert_id = int(args[1])
            ok = delete_watch(alert_id, telegram_id=tg_id)
            if ok:
                await update.message.reply_text(f"✅ Alert #{alert_id} deleted.")
            else:
                await update.message.reply_text(f"Alert #{alert_id} not found or not yours.")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
    else:
        await update.message.reply_text(
            "Unknown subcommand. Try `/alert add`, `/alert list`, or `/alert del`.",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── /mop ─────────────────────────────────────────────────────────────────────

async def cmd_mop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /mop 521234         — MOP check by postal code
    /mop 2020-06        — MOP from purchase month (YYYY-MM)
    """
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "`/mop 521234` — by postal code\n"
            "`/mop 2020-06` — by purchase month (YYYY-MM)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    arg = args[0].strip()
    try:
        # If YYYY-MM format
        if "-" in arg and len(arg) == 7:
            yr, mo = int(arg[:4]), int(arg[5:7])
            purchase_date = date(yr, mo, 1)
        elif arg.isdigit() and len(arg) == 6:
            # Postal code — try to find in HDB data
            from data.hdb_pipeline import load_hdb_transactions
            txns = load_hdb_transactions()
            # Filter by postal-derived town (rough) — use latest transaction for that postal
            # We can't directly match postal in HDB data, so use month input fallback
            await update.message.reply_text(
                "⚠️ Postal code lookup for MOP requires block + street.\n"
                "Try: `/mop 2020-06` (your purchase month in YYYY-MM format)\n"
                "Or use the MOP Tracker on the dashboard for address search.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        else:
            await update.message.reply_text("Invalid format. Use `YYYY-MM` e.g. `/mop 2020-06`", parse_mode=ParseMode.MARKDOWN)
            return

        mop_date  = date(purchase_date.year + 5, purchase_date.month, 1)
        today     = date.today()
        days_left = (mop_date - today).days

        if days_left <= 0:
            msg = (
                f"✅ *MOP has passed!*\n\n"
                f"Purchase month: {purchase_date.strftime('%b %Y')}\n"
                f"MOP date: {mop_date.strftime('%d %b %Y')}\n"
                f"Status: *Eligible to sell / rent whole unit*"
            )
        else:
            yrs = days_left // 365
            mos = (days_left % 365) // 30
            msg = (
                f"📅 *MOP Countdown*\n\n"
                f"Purchase month: {purchase_date.strftime('%b %Y')}\n"
                f"MOP date: *{mop_date.strftime('%d %b %Y')}*\n"
                f"Time remaining: *{yrs}y {mos}m* ({days_left:,} days)\n\n"
                f"⚠️ Cannot sell or rent whole unit until MOP is met."
            )
        msg += f"\n\n📊 [Full MOP Tracker →]({DASHBOARD_URL})"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ── /ssd ─────────────────────────────────────────────────────────────────────

async def cmd_ssd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /ssd 800000 2024-03-01    — SSD on a property purchased at 800k on 1 Mar 2024
    """
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/ssd <purchase_price> <purchase_date>`\n"
            "Example: `/ssd 800000 2024-03-01`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        price = float(args[0].replace(",",""))
        pd    = datetime.strptime(args[1], "%Y-%m-%d").date()
        from agents.ssd_calculator import analyse as ssd_analyse
        r = ssd_analyse(price, pd)
        if r.is_ssd_free:
            msg = (
                f"✅ *SSD-Free!*\n"
                f"You've held for {r.months_held} months — no Seller's Stamp Duty applies."
            )
        else:
            msg = (
                f"⏳ *SSD Timer*\n\n"
                f"Purchase: SGD {price:,.0f} on {pd.strftime('%d %b %Y')}\n"
                f"Held: *{r.months_held} months* → Rate: *{r.ssd_rate_pct:.0f}%*\n"
                f"SSD payable NOW: *SGD {r.ssd_amount:,.0f}*\n\n"
                f"SSD-free from: *{r.ssd_free_date.strftime('%d %b %Y')}* ({r.days_to_ssd_free} days)\n"
                f"💡 Waiting saves: *SGD {r.savings_if_wait:,.0f}*"
            )
        msg += f"\n\n📊 [Full SSD analysis →]({DASHBOARD_URL})"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except ValueError:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD e.g. `/ssd 800000 2024-03-01`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ── /calc — calculator menu ────────────────────────────────────────────────────

async def cmd_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏦 Mortgage Calculator",  url=f"{DASHBOARD_URL}"),
         InlineKeyboardButton("🏛️ Property Tax",        url=f"{DASHBOARD_URL}")],
        [InlineKeyboardButton("🔄 Refi Alert",           url=f"{DASHBOARD_URL}"),
         InlineKeyboardButton("🏘️ Rental Yield",        url=f"{DASHBOARD_URL}")],
        [InlineKeyboardButton("⬆️ HDB Upgrader",        url=f"{DASHBOARD_URL}"),
         InlineKeyboardButton("🎁 CPF Grants",           url=f"{DASHBOARD_URL}")],
        [InlineKeyboardButton("⏳ SSD: /ssd 800000 2024-03-01", callback_data="calc_ssd_hint")],
    ]
    await update.message.reply_text(
        "🧮 *PropOS Calculators*\n\n"
        "Quick calc via bot: `/ssd`, `/mop`, `/value`\n"
        "Full calculators on the dashboard (tap below):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from core.llm_router import get_current_mode, get_token_summary
    mode      = get_current_mode()
    costs     = get_token_summary()
    sentiment = get_sentiment_index()
    try:
        from data.analytics import get_subscriber_count
        subs = get_subscriber_count()
    except Exception:
        subs = "?"
    msg = (
        f"⚙️ *PropOS Status*\n\n"
        f"🤖 LLM: {mode['mode'].upper()} ({mode['model']})\n"
        f"💰 API Cost: SGD ${costs['est_sgd']:.4f} ({costs['call_count']} calls)\n"
        f"📊 Market: {sentiment.get('label','N/A')}\n"
        f"📬 Subscribers: {subs}\n"
        f"📡 {DASHBOARD_URL}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# ── /admin ────────────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 System Status",       callback_data="admin_status"),
         InlineKeyboardButton("💰 Token Costs",         callback_data="admin_costs")],
        [InlineKeyboardButton("📰 Sync News",           callback_data="admin_sync_news"),
         InlineKeyboardButton("🏠 Sync HDB",            callback_data="admin_sync_hdb")],
        [InlineKeyboardButton("📢 Post Daily Digest",   callback_data="admin_post_digest"),
         InlineKeyboardButton("🔍 Check Watchlist",     callback_data="admin_watchlist")],
        [InlineKeyboardButton("📧 Send Weekly Digest",  callback_data="admin_send_digest"),
         InlineKeyboardButton("🔄 Bot Health",          callback_data="admin_health")],
    ]
    await update.message.reply_text(
        "🔐 *Admin Menu*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )


# ── Inline button callbacks ────────────────────────────────────────────────────

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    # ── Quick action shortcuts from /start ────────────────────────────────────
    if data == "quick_deals":
        ctx.args = []
        update._effective_message = query.message
        await cmd_deals(update, ctx)
        return
    if data == "quick_news":
        update._effective_message = query.message
        await cmd_news(update, ctx)
        return
    if data == "quick_hdb":
        ctx.args = []
        update._effective_message = query.message
        await cmd_hdb(update, ctx)
        return
    if data == "quick_value_help":
        await query.message.reply_text(
            "💰 *Quick Valuation*\n\nSend: `/value <district> <sqft> <asking_price>`\nExample: `/value 15 1000 1500000`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if data == "quick_ssd_help":
        await query.message.reply_text(
            "⏳ *SSD Timer*\n\nSend: `/ssd <price> <purchase_date>`\nExample: `/ssd 800000 2024-03-01`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if data == "quick_mop_help":
        await query.message.reply_text(
            "📅 *MOP Check*\n\nSend: `/mop <purchase_month>`\nExample: `/mop 2020-06`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if data == "quick_alert_help":
        await query.message.reply_text(
            "🔔 *Set Price Alert*\n\nSend: `/alert add <postal_or_town> <max_price>`\nExample: `/alert add 521234 800000`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if data == "quick_calc":
        update._effective_message = query.message
        await cmd_calc(update, ctx)
        return
    if data == "subscribe_start":
        await subscribe_ask_email(update, ctx)
        return
    if data == "calc_ssd_hint":
        await query.message.reply_text("Send: `/ssd 800000 2024-03-01`", parse_mode=ParseMode.MARKDOWN)
        return

    # ── Admin callbacks ────────────────────────────────────────────────────────
    if not is_admin(update):
        await query.answer("⛔ Admin only.")
        return

    if data == "admin_status":
        from core.llm_router import get_current_mode, get_token_summary
        mode  = get_current_mode()
        costs = get_token_summary()
        sentiment = get_sentiment_index()
        await query.edit_message_text(
            f"⚙️ *System Status*\n\n"
            f"🤖 LLM: `{mode['mode'].upper()}` ({mode['model']})\n"
            f"💰 Cost: SGD ${costs['est_sgd']:.4f} ({costs['call_count']} calls)\n"
            f"📊 Sentiment: {sentiment.get('label','N/A')}\n"
            f"📡 {DASHBOARD_URL}",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "admin_costs":
        from core.llm_router import get_token_summary
        costs = get_token_summary()
        lines = ["💰 *Token Usage*\n"]
        for model, stats in costs.get("by_model", {}).items():
            lines.append(f"• `{model}`: {stats.get('calls',0)} calls, SGD ${stats.get('cost_sgd',0):.4f}")
        lines.append(f"\n**Total: SGD ${costs['est_sgd']:.4f}**")
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_sync_news":
        await query.edit_message_text("🔄 Syncing news…")
        try:
            from data.news_pipeline import sync_news
            sync_news()
            await ctx.bot.send_message(ADMIN_CHAT_ID, "✅ News sync complete.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ News sync failed: {e}")

    elif data == "admin_sync_hdb":
        await query.edit_message_text("🔄 Syncing HDB data… (30s)")
        try:
            from data.hdb_pipeline import fetch_hdb_resale
            records = fetch_hdb_resale(force=True)
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"✅ HDB sync — {len(records)} records.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ HDB sync failed: {e}")

    elif data == "admin_post_digest":
        await query.edit_message_text("📢 Posting digest to channel…")
        try:
            await post_daily_briefing(ctx.bot)
            await ctx.bot.send_message(ADMIN_CHAT_ID, "✅ Digest posted.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ Post failed: {e}")

    elif data == "admin_send_digest":
        await query.edit_message_text("📧 Sending weekly email digest…")
        try:
            from agents.weekly_digest import send_weekly_digest
            result = send_weekly_digest()
            await ctx.bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ Weekly digest: {result['sent']} sent, {result.get('failed',0)} failed."
            )
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ Digest failed: {e}")

    elif data == "admin_watchlist":
        await query.edit_message_text("🔍 Running watchlist check…")
        try:
            from data.watchlist import check_watchlist, format_alert_message
            alerts = check_watchlist()
            if alerts:
                await ctx.bot.send_message(ADMIN_CHAT_ID, f"✅ {len(alerts)} watchlist match(es) found.")
                for alert in alerts[:3]:
                    await ctx.bot.send_message(
                        ADMIN_CHAT_ID, format_alert_message(alert), parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await ctx.bot.send_message(ADMIN_CHAT_ID, "✅ Watchlist checked — no new matches.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ Watchlist failed: {e}")

    elif data == "admin_health":
        import time
        from pathlib import Path as _P
        cache = _P(__file__).parent.parent / "cache"
        def _age(p):
            return f"{(time.time()-p.stat().st_mtime)/3600:.0f}h ago" if p.exists() else "missing"
        try:
            from data.analytics import get_subscriber_count
            subs = get_subscriber_count()
        except Exception:
            subs = "?"
        await query.edit_message_text(
            f"🔄 *Health Check*\n\n"
            f"🏠 HDB cache: {_age(cache/'hdb'/'resale.json')}\n"
            f"📰 News cache: {_age(cache/'news'/'articles.json')}\n"
            f"📬 Subscribers: {subs}\n"
            f"🤖 Bot: ✅ Online",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Free-text: email auto-detect + enquiry forward ────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id
    text    = (update.message.text or "").strip()

    # Auto-detect email address — subscribe them silently
    if "@" in text and "." in text and " " not in text and len(text) < 80:
        email = text.lower()
        try:
            from data.analytics import add_subscriber, resubscribe_email, mark_welcome_sent
            result = add_subscriber(email, source=f"telegram_autosub_{user.id}")
            if result["new"]:
                sent = _send_welcome_email_sync(email)
                if sent:
                    mark_welcome_sent(email)
                await update.message.reply_text(
                    f"📬 *Subscribed!* `{email}` added to PropOS Weekly Digest.\n"
                    f"You'll get the next digest on Sunday.\n\n"
                    f"📊 {DASHBOARD_URL}",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
                try:
                    await ctx.bot.send_message(
                        ADMIN_CHAT_ID,
                        f"🆕 Auto-subscribed via Telegram: `{email}` (@{user.username or '?'}, ID {user.id})",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
            else:
                await update.message.reply_text(f"✅ `{email}` is already subscribed!", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"Couldn't save email: {e}")
        return

    # Admin messages ignored (don't forward to self)
    if chat_id == ADMIN_CHAT_ID:
        return

    # Forward enquiry to admin
    fwd = (
        f"📩 *Enquiry*\n"
        f"From: {user.first_name or ''} {user.last_name or ''} (@{user.username or '?'})\n"
        f"ID: `{chat_id}`\n\n{text}"
    )
    try:
        await ctx.bot.send_message(ADMIN_CHAT_ID, fwd, parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(
            "✅ Message forwarded to the PropOS team. We'll reply within 1 business day.\n\n"
            f"Try /start for quick actions or visit {DASHBOARD_URL}"
        )
    except Exception as e:
        await update.message.reply_text("Thanks! Email us: mailtsjp@gmail.com")


# ── Scheduled posts ────────────────────────────────────────────────────────────

async def post_daily_briefing(bot: Bot):
    if not DEALS_CHANNEL_ID:
        return
    try:
        agent   = NewsIntelAgent()
        msg     = agent.format_telegram_daily()
        await bot.send_message(DEALS_CHANNEL_ID, msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        deals = find_below_market_hdb(threshold_pct=5.0, limit=3)
        if deals:
            lines = ["🏠 *Today's Top HDB Deals*\n"]
            for d in deals:
                lines.append(
                    f"• *{d['town']} {d['flat_type']}* — {d['discount_pct']:.1f}% below median\n"
                    f"  SGD {d['resale_price']:,.0f} | {d['floor_area_sqm']:.0f} sqm"
                )
            lines.append(f"\n🔓 [Full feed + alerts →]({DASHBOARD_URL})")
            await bot.send_message(DEALS_CHANNEL_ID, "\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        log.info("Daily briefing posted")
    except Exception as e:
        log.error(f"Daily briefing failed: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(BOT_TOKEN).build()

    # Email subscription conversation
    sub_conv = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", subscribe_ask_email),
        ],
        states={
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_save_email)],
        },
        fallbacks=[CommandHandler("cancel", subscribe_cancel)],
        per_chat=True,
    )

    app.add_handler(sub_conv)
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("deals",   cmd_deals))
    app.add_handler(CommandHandler("hdb",     cmd_hdb))
    app.add_handler(CommandHandler("news",    cmd_news))
    app.add_handler(CommandHandler("value",   cmd_value))
    app.add_handler(CommandHandler("alert",   cmd_alert))
    app.add_handler(CommandHandler("mop",     cmd_mop))
    app.add_handler(CommandHandler("ssd",     cmd_ssd))
    app.add_handler(CommandHandler("calc",    cmd_calc))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("admin",   cmd_admin))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("PropOS Telegram bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

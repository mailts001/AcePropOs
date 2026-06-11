"""
PropOS Telegram Bot
- Free public channel: Daily sentiment index + top 3 deals (acquisition funnel)
- Private alerts: DealHunter alerts for paying subscribers
- Commands: /deals /value /news /status
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from agents.deal_hunter_agent import DealHunterAgent
from agents.valuation_agent import ValuationAgent
from agents.news_intel_agent import NewsIntelAgent
from data.news_pipeline import get_sentiment_index
from data.hdb_pipeline import find_below_market_hdb

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("propos_bot")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "1245366658"))
DEALS_CHANNEL_ID = os.environ.get("TELEGRAM_DEALS_CHANNEL_ID", "-1004221326153")

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_CHAT_ID


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 *Welcome to PropOS — Singapore Property Intelligence*\n\n"
        "*Free commands:*\n"
        "/subscribe — Subscribe to daily digest\n"
        "/hdb [town] [type] — HDB below-market deals\n"
        "/deals — Private condo deals\n"
        "/news — Market sentiment + top stories\n"
        "/value [district] [sqft] [price] — Quick valuation\n"
        "/status — System status\n\n"
        "Examples:\n"
        "`/hdb TAMPINES 4 ROOM`\n"
        "`/value 15 1000 1500000`\n\n"
        "📊 Full dashboard (free): https://acepropos.duckdns.org\n"
        "🔔 Set price alerts in the Watchlist tab",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_deals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show top 3 deals. Free command — drives subscription."""
    await update.message.reply_text("🔍 Scanning transactions... (may take 10-20s)")
    try:
        agent = DealHunterAgent()
        result = agent.scan_private_deals(threshold_pct=8.0, limit=5, summarise=True)
        deals = result.get("top_deals", [])

        if not deals:
            await update.message.reply_text("No deals above threshold found today.")
            return

        lines = ["🏠 *Today's Top Property Deals*\n"]
        for i, deal in enumerate(deals[:3], 1):
            lines.append(
                f"*{i}. {deal['project']} — D{deal['district']}*\n"
                f"  📉 {deal['discount_pct']}% below district median\n"
                f"  💰 PSF: ${deal['psf_sgd']:,.0f} vs median ${deal['median_psf']:,.0f}\n"
                f"  📐 {deal['area_sqft']:.0f} sqft | {deal['property_type']}\n"
                f"  ⭐ Deal Score: {deal['deal_score']}/100\n"
            )

        if result.get("summary"):
            lines.append(f"\n📝 _{result['summary']}_")

        lines.append("\n🔓 [Unlock full deal feed + alerts →](https://propertyos.sg)")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        log.error(f"cmd_deals error: {e}")
        await update.message.reply_text(f"Error scanning deals: {e}")


async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Market sentiment + top stories."""
    try:
        agent = NewsIntelAgent()
        msg = agent.format_telegram_daily()
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /value D15 1000 1500000
    Quick valuation: district area_sqft asking_price
    """
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /value [district] [sqft] [asking_price optional]\n"
            "Example: /value 15 1000 1500000"
        )
        return

    try:
        district = int(str(args[0]).replace("D", "").replace("d", ""))
        area_sqft = float(args[1])
        asking_price = float(args[2]) if len(args) >= 3 else 0

        agent = ValuationAgent()
        result = agent.value_private_property(district, area_sqft, asking_price=asking_price, explain=False)

        if result.get("status") != "ok":
            await update.message.reply_text(result.get("message", "Insufficient data for this district."))
            return

        lines = [
            f"🏠 *Valuation — District {district}*\n",
            f"📐 Area: {area_sqft:.0f} sqft",
            f"💰 Estimated Value: *${result['estimated_value_sgd']:,.0f}*",
            f"📊 Median PSF: ${result['median_psf']:,.0f} | Range: ${result['p25_psf']:,.0f}–${result['p75_psf']:,.0f}",
            f"🔢 Based on {result['transactions_used']} transactions | Confidence: {result['confidence']}",
        ]
        if asking_price > 0:
            lines += [
                f"\n💬 Asking: ${asking_price:,.0f}",
                f"📈 vs Median: {result['vs_median_pct']:+.1f}%",
                f"⭐ Deal Score: {result['deal_score']}/100",
                f"📝 {result['verdict']}",
            ]

        lines.append("\n🔓 [Full analysis + PDF report →](https://propertyos.sg)")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except (ValueError, IndexError) as e:
        await update.message.reply_text(f"Invalid input. Try: /value 15 1000 1500000\nError: {e}")


async def cmd_hdb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /hdb [town] [flat_type]
    Show top 3 below-market HDB deals. Free command — acquisition funnel.
    """
    args = ctx.args
    town = args[0].upper().replace("-", " ") if args else None
    flat_type = " ".join(args[1:]).upper() if len(args) > 1 else None

    await update.message.reply_text("🔍 Scanning HDB resale transactions...")
    try:
        deals = find_below_market_hdb(town=town, flat_type=flat_type, threshold_pct=5.0, limit=5)
        if not deals:
            await update.message.reply_text(
                "No below-market HDB deals found" +
                (f" in {town}" if town else "") + " right now. Try /hdb TAMPINES or /hdb WOODLANDS 4-ROOM"
            )
            return

        lines = [f"🏠 *HDB Below-Market Deals*" + (f" — {town}" if town else "") + "\n"]
        for i, d in enumerate(deals[:3], 1):
            lines.append(
                f"*{i}. {d['town']} — {d['flat_type']}*\n"
                f"  📍 {d['block']} {d['street_name']}, {d.get('storey_range','')}\n"
                f"  💰 SGD {d['resale_price']:,.0f} ({d['discount_pct']:.1f}% below median PSF)\n"
                f"  📐 {d['floor_area_sqm']:.0f} sqm | PSF: SGD {d['psf']:,.0f} vs SGD {d['median_psf']:,.0f}\n"
            )
        lines.append("🔓 [Full deal feed + alerts →](https://acepropos.duckdns.org)")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        log.error(f"cmd_hdb error: {e}")
        await update.message.reply_text(f"Error: {e}")


async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Public subscribe command — captures user into funnel."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "unknown"
    name = update.effective_user.first_name or "there"

    # Log subscriber (in production, write to DB)
    log.info(f"New subscriber: {chat_id} (@{username})")

    await update.message.reply_text(
        f"👋 Hi {name}! You're now subscribed to *PropOS Daily*.\n\n"
        f"*What you'll get (free):*\n"
        f"• 📊 Daily market sentiment at 8 AM SGT\n"
        f"• 🏠 Top 3 HDB below-market deals daily\n"
        f"• 🚨 Policy change alerts\n\n"
        f"*Available commands:*\n"
        f"/hdb [town] — HDB deal scanner\n"
        f"/deals — Private condo deals\n"
        f"/news — Market sentiment\n"
        f"/value [district] [sqft] [price] — Quick valuation\n\n"
        f"📊 Full dashboard (free): https://acepropos.duckdns.org\n"
        f"💡 Your Telegram ID: `{chat_id}` — use this in the Watchlist tab for personalised alerts.",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from core.llm_router import get_current_mode, get_token_summary
    mode = get_current_mode()
    costs = get_token_summary()
    sentiment = get_sentiment_index()

    msg = (
        f"⚙️ *PropertyOS Status*\n\n"
        f"🤖 LLM Mode: {mode['mode'].upper()} ({mode['model']})\n"
        f"💰 Total Cost: USD ${costs['total_cost_usd']:.4f} / SGD ${costs['est_sgd']:.4f}\n"
        f"🔢 API Calls: {costs['call_count']}\n"
        f"📊 Market Sentiment: {sentiment.get('label', 'N/A')}\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ── Admin commands ────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin-only menu. Only responds to ADMIN_CHAT_ID."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    keyboard = [
        [InlineKeyboardButton("📊 System Status", callback_data="admin_status"),
         InlineKeyboardButton("💰 Token Costs", callback_data="admin_costs")],
        [InlineKeyboardButton("📰 Sync News Now", callback_data="admin_sync_news"),
         InlineKeyboardButton("🏠 Sync HDB Now", callback_data="admin_sync_hdb")],
        [InlineKeyboardButton("📢 Post Daily Digest", callback_data="admin_post_digest"),
         InlineKeyboardButton("🔍 Run Watchlist Check", callback_data="admin_watchlist")],
        [InlineKeyboardButton("🔄 Check Bot Health", callback_data="admin_health")],
    ]
    await update.message.reply_text(
        "🔐 *Admin Menu* — @askAceBot",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks from admin menu."""
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("⛔ Admin only.")
        return
    await query.answer()

    data = query.data

    if data == "admin_status":
        from core.llm_router import get_current_mode, get_token_summary
        mode = get_current_mode()
        costs = get_token_summary()
        sentiment = get_sentiment_index()
        msg = (
            f"⚙️ *System Status*\n\n"
            f"🤖 LLM Mode: `{mode['mode'].upper()}` ({mode['model']})\n"
            f"💰 API Cost: SGD ${costs['est_sgd']:.4f} ({costs['call_count']} calls)\n"
            f"📊 Market Sentiment: {sentiment.get('label', 'N/A')} ({sentiment.get('score', 0):.2f})\n"
            f"📡 Dashboard: https://acepropos.duckdns.org"
        )
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_costs":
        from core.llm_router import get_token_summary
        costs = get_token_summary()
        lines = [f"💰 *Token Usage Summary*\n"]
        for model, stats in costs.get("by_model", {}).items():
            lines.append(f"• `{model}`: {stats.get('calls',0)} calls, SGD ${stats.get('cost_sgd',0):.4f}")
        lines.append(f"\n**Total: SGD ${costs['est_sgd']:.4f}**")
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_sync_news":
        await query.edit_message_text("🔄 Syncing news... (check logs)")
        try:
            from data.news_pipeline import sync_news
            sync_news()
            await ctx.bot.send_message(ADMIN_CHAT_ID, "✅ News sync complete.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ News sync failed: {e}")

    elif data == "admin_sync_hdb":
        await query.edit_message_text("🔄 Syncing HDB data... (this may take 30s)")
        try:
            from data.hdb_pipeline import fetch_hdb_resale
            records = fetch_hdb_resale(force=True)
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"✅ HDB sync done — {len(records)} records.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ HDB sync failed: {e}")

    elif data == "admin_post_digest":
        await query.edit_message_text("📢 Posting digest to channel...")
        try:
            await post_daily_briefing(ctx.bot)
            await ctx.bot.send_message(ADMIN_CHAT_ID, "✅ Digest posted to Ace PropOs_Ch.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ Post failed: {e}")

    elif data == "admin_watchlist":
        await query.edit_message_text("🔍 Running watchlist check...")
        try:
            from data.watchlist import check_watchlist, format_alert_message
            alerts = check_watchlist()
            if alerts:
                await ctx.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"✅ {len(alerts)} watchlist alert(s) found and queued for sending."
                )
                for alert in alerts[:3]:
                    await ctx.bot.send_message(
                        ADMIN_CHAT_ID,
                        format_alert_message(alert),
                        parse_mode=ParseMode.MARKDOWN,
                    )
            else:
                await ctx.bot.send_message(ADMIN_CHAT_ID, "✅ Watchlist checked — no new matches.")
        except Exception as e:
            await ctx.bot.send_message(ADMIN_CHAT_ID, f"❌ Watchlist check failed: {e}")

    elif data == "admin_health":
        import os
        from pathlib import Path
        cache_dir = Path(__file__).parent.parent / "cache"
        hdb_cache = cache_dir / "hdb" / "resale.json"
        news_cache = cache_dir / "news" / "articles.json"

        hdb_age = "missing"
        if hdb_cache.exists():
            import time
            age_h = (time.time() - hdb_cache.stat().st_mtime) / 3600
            hdb_age = f"{age_h:.0f}h ago"

        news_age = "missing"
        if news_cache.exists():
            import time
            age_h = (time.time() - news_cache.stat().st_mtime) / 3600
            news_age = f"{age_h:.0f}h ago"

        msg = (
            f"🔄 *Bot Health Check*\n\n"
            f"🏠 HDB cache: {hdb_age}\n"
            f"📰 News cache: {news_age}\n"
            f"🤖 Bot: ✅ Online\n"
            f"📡 Dashboard: https://acepropos.duckdns.org"
        )
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)


async def handle_enquiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Forward non-command messages to admin as enquiries.
    Public users can text the bot; admin sees it and can reply.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text or ""

    # If admin is replying in their own chat, echo for confirmation
    if chat_id == ADMIN_CHAT_ID:
        return

    # Forward to admin
    fwd = (
        f"📩 *New Enquiry*\n\n"
        f"From: {user.first_name or ''} {user.last_name or ''} (@{user.username or 'no username'})\n"
        f"Chat ID: `{chat_id}`\n\n"
        f"Message:\n{text}\n\n"
        f"_Reply in the bot chat to respond._"
    )
    try:
        await ctx.bot.send_message(ADMIN_CHAT_ID, fwd, parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(
            "✅ Your message has been forwarded to our team. "
            "We'll get back to you within 1 business day.\n\n"
            "Meanwhile, try:\n/hdb — HDB deals\n/news — Market sentiment\n"
            "📊 https://acepropos.duckdns.org"
        )
    except Exception as e:
        log.error(f"Enquiry forward failed: {e}")
        await update.message.reply_text("Thanks for reaching out! Email us: mailtsjp@gmail.com")


# ── Scheduled: Daily public channel post ──────────────────────────────────────

async def post_daily_briefing(bot: Bot):
    """Post daily market briefing + top HDB deals to public channel. Called by cron at 8 AM SGT."""
    if not DEALS_CHANNEL_ID:
        log.warning("TELEGRAM_DEALS_CHANNEL_ID not set — skipping channel post")
        return
    try:
        # Part 1: news sentiment
        agent = NewsIntelAgent()
        news_msg = agent.format_telegram_daily()
        await bot.send_message(
            chat_id=DEALS_CHANNEL_ID,
            text=news_msg,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )

        # Part 2: top 3 HDB deals
        try:
            deals = find_below_market_hdb(threshold_pct=5.0, limit=3)
            if deals:
                lines = ["🏠 *Today's Top HDB Deals*\n"]
                for d in deals:
                    lines.append(
                        f"• *{d['town']} {d['flat_type']}* — {d['discount_pct']:.1f}% below median\n"
                        f"  SGD {d['resale_price']:,.0f} | PSF {d['psf']:,.0f} vs {d['median_psf']:,.0f} | {d['floor_area_sqm']:.0f} sqm"
                    )
                lines.append("\n🔓 [Set up price alerts →](https://acepropos.duckdns.org)")
                await bot.send_message(
                    chat_id=DEALS_CHANNEL_ID,
                    text="\n".join(lines),
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
        except Exception as e:
            log.warning(f"HDB deals section skipped: {e}")

        log.info("Daily briefing posted to channel")
    except Exception as e:
        log.error(f"Daily briefing failed: {e}")


async def post_top_deals(bot: Bot):
    """Post top 3 deals to public channel. Called by cron at 9 PM SGT."""
    if not DEALS_CHANNEL_ID:
        return
    try:
        agent = DealHunterAgent()
        result = agent.scan_private_deals(threshold_pct=8.0, limit=3, summarise=False)
        deals = result.get("top_deals", [])
        if not deals:
            return

        lines = ["🏠 *PropertyOS Evening Deal Scan*\n"]
        for deal in deals:
            lines.append(
                f"• *{deal['project']}* D{deal['district']} — "
                f"*{deal['discount_pct']}% below median* | "
                f"PSF ${deal['psf_sgd']:,.0f} | Score {deal['deal_score']}/100"
            )
        lines.append("\n🔓 [Full analysis →](https://propertyos.sg)")

        await bot.send_message(
            chat_id=DEALS_CHANNEL_ID,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Deal post failed: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("hdb", cmd_hdb))
    app.add_handler(CommandHandler("deals", cmd_deals))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("value", cmd_value))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    # Forward non-command messages to admin as enquiries
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_enquiry))

    log.info("PropertyOS Telegram bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

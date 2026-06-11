"""
Cron script — sends daily 8AM SGT digest to Telegram channel.
Schedule: 0 0 * * 1-5 (Mon–Fri midnight UTC = 8AM SGT)
"""
import sys, os, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from telegram import Bot
from telegram.constants import ParseMode

from agents.news_intel_agent import NewsIntelAgent
from data.hdb_pipeline import find_below_market_hdb
from data.news_pipeline import get_sentiment_index

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DEALS_CHANNEL_ID = os.environ.get("TELEGRAM_DEALS_CHANNEL_ID", "")


async def send():
    if not BOT_TOKEN or not DEALS_CHANNEL_ID:
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_DEALS_CHANNEL_ID not set — dry run")
        dry = True
    else:
        dry = False
        bot = Bot(BOT_TOKEN)

    # Part 1: market sentiment + news
    try:
        agent = NewsIntelAgent()
        news_msg = agent.format_telegram_daily()
        if dry:
            print("=== NEWS DIGEST ===")
            print(news_msg)
        else:
            await bot.send_message(chat_id=DEALS_CHANNEL_ID, text=news_msg,
                                   parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        print("News digest sent.")
    except Exception as e:
        print(f"News digest failed: {e}")

    # Part 2: top 3 HDB below-market
    try:
        deals = find_below_market_hdb(threshold_pct=5.0, limit=3)
        if deals:
            lines = ["🏠 *Today's Top HDB Deals*\n"]
            for d in deals:
                lines.append(
                    f"• *{d['town']} {d['flat_type']}* — {d['discount_pct']:.1f}% below median\n"
                    f"  SGD {d['resale_price']:,.0f} | {d['floor_area_sqm']:.0f} sqm | PSF {d['psf']:,.0f}"
                )
            lines.append("\n🔓 [Set up price alerts →](https://acepropos.duckdns.org)")
            msg = "\n".join(lines)
            if dry:
                print("\n=== HDB DEALS ===")
                print(msg)
            else:
                await bot.send_message(chat_id=DEALS_CHANNEL_ID, text=msg,
                                       parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            print(f"HDB deals sent ({len(deals)} deals).")
        else:
            print("No qualifying HDB deals today.")
    except Exception as e:
        print(f"HDB deals section failed: {e}")


if __name__ == "__main__":
    asyncio.run(send())

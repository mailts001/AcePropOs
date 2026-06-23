# PropOS — AI Property Intelligence Platform
> **For Claude Code**: Read this file first. It has everything needed to resume development cold.

## Infrastructure
- Local dev: `~/Documents/PropOS/`
- VPS: Hetzner CX22, IP: `5.223.72.120`, Singapore
- SSH: `ssh root@5.223.72.120` (key: `~/.ssh/id_ed25519` — check which key works)
- GitHub: `https://github.com/mailts001/AcePropOs.git`
- Dashboard: `http://5.223.72.120:8501` (Streamlit, service: `propos-dashboard`)
- Telegram bots: `@acepropos_bot` (main), `@AceMarketScannerBot` (scanner)

## VPS Key Commands
```bash
ssh root@5.223.72.120 "cd /root/propos && git pull && systemctl restart propos-dashboard propos-bot"
ssh root@5.223.72.120 "journalctl -u propos-bot -n 30"
ssh root@5.223.72.120 "journalctl -u propos-dashboard -n 20"
ssh root@5.223.72.120 "sqlite3 /root/propos/propos.db '.tables'"
# Python venv on VPS:
ssh root@5.223.72.120 "cd /root/propos && .venv/bin/python agents/weekly_digest.py --dry-run"
```

## Deploy Flow
```bash
# Local → GitHub → VPS
git add -A && git commit -m "msg" && git push
ssh root@5.223.72.120 "cd /root/propos && git pull && systemctl restart propos-dashboard propos-bot"
```

## LLM Modes (admin switchable in dashboard ⚙️ Admin)
- `free`     → Gemini 2.0 Flash (free tier, rate limited)
- `balanced` → Groq Llama 3.1 8B (near-free, fast)
- `quality`  → Claude Haiku (paid, default production)
- `premium`  → Claude Sonnet (full quality, demos)

## File Structure
```
dashboard/app.py             — Main Streamlit UI (ALL pages in one file, ~4500 lines)
bot/telegram_bot.py          — Telegram bot (python-telegram-bot v20+)
agents/
  valuation_agent.py         — HDB/private valuation, address lookup
  deal_hunter_agent.py       — Below-market deal detection
  mortgage_agent.py          — Bank rate comparison, TDSR calc
  news_intel_agent.py        — Sentiment scoring
  insurance_agent.py         — Insurance referral triggers
  ssd_calculator.py          — Seller's Stamp Duty calculator
  refi_alert.py              — Mortgage refinancing alert engine
  hdb_upgrader.py            — HDB → private upgrade feasibility
  property_tax.py            — NOO/OO property tax + T-bill laddering
  price_history.py           — URA PSF trend by project/district
  rental_yield.py            — Buy-to-let net yield analyser
  weekly_digest.py           — Weekly HTML email digest (cron Sunday)
  pdf_report.py              — PDF valuation report export
data/
  hdb_pipeline.py            — HDB resale from data.gov.sg (7-day file cache)
  ura_pipeline.py            — URA private transactions (137k+ cached)
  ura_rental_pipeline.py     — URA rental data by district
  news_pipeline.py           — RSS news + sentiment
  onemap_client.py           — SVY21↔WGS84, MRT distance, amenities
  watchlist.py               — SQLite watchlist + price alerts
core/
  llm_router.py              — Multi-LLM routing with mode switching
  token_tracker.py           — Per-query cost tracking
config/
  settings.json              — LLM mode, feature flags
  insurance_partners.json    — Insurance referral partners
cache/
  hdb/                       — Cached HDB resale JSON (7-day TTL)
  ura/                       — Cached URA transactions JSON
propos.db                    — SQLite: page_views, broker_leads, subscribers, feature_events
```

## Dashboard Navigation (NAV dict in app.py ~line 390)
```
🔍 Research:   🔍 Property Search, 🏠 Address Lookup, 🔍 Property Valuation
               📊 Deals & Opportunities, 🗺️ MRT Map
📰 Intelligence: 📰 Market Intelligence, 📈 Price History
💰 Finance:    🏦 Mortgage, 💹 Stamp Duty & ROI, 🎁 CPF Grants
               🏠↔️ Rent vs Buy, ⬆️ HDB Upgrader, 🏛️ Property Tax
               🔄 Refi Alert, 🏘️ Rental Yield
🛡️ Protect:   🛡️ Insurance, 🔔 Watchlist & Alerts, ⏳ SSD Timer
💼 My Portfolio, 📈 Price History, 🤝 Partners, ⚙️ Admin
```

## Key Architecture Patterns

### Streamlit caching (CRITICAL for speed)
```python
# app.py top — use these cached loaders everywhere instead of calling pipelines directly
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_hdb_records():      # replaces fetch_hdb_resale() calls
def _cached_ura_transactions(): # replaces load_all_transactions() calls
```

### Telegram bot (python-telegram-bot v20+)
- Logic extracted to helper functions: `_msg_deals()`, `_msg_hdb()`, `_msg_ssd()` etc. → return strings
- Commands: use `update.message.reply_text(text)`
- Callbacks (inline buttons): `update.message` is None → use `ctx.bot.send_message(chat_id, text)`
- HDB pipeline returns `psf_sgd` not `psf` — always use `d.get("psf_sgd", d.get("psf", 0))`

### OneMap API (postal code → address)
```python
_requests_lib.get(
    f"https://www.onemap.gov.sg/api/common/elastic/search"
    f"?searchVal={postal}&returnGeom=N&getAddrDetails=Y&pageNum=1", timeout=6
).json()["results"][0]  # keys: BLK_NO, ROAD_NAME, BUILDING, POSTAL
```

## Data Sources
- URA API: `https://www.ura.gov.sg/maps/api/` (free, need URA_ACCESS_KEY)
- HDB: `https://data.gov.sg/collections/189/view` (free, resource ID: `d_8b84c4ee58e3cfc0ece0d773c8ca6abc`)
- OneMap: `https://www.onemap.gov.sg/apidocs/` (free, no token needed for search)
- News RSS: The Edge SG, Business Times, CNA, PropertyGuru

## .env on VPS (at `/root/propos/.env`)
```
TELEGRAM_BOT_TOKEN=...          # @acepropos_bot
SCANNER_BOT_TOKEN=...           # @AceMarketScannerBot
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=mailtcb2150@gmail.com
SMTP_PASS=...                   # Gmail App Password
ADMIN_PASSWORD=...
```
⚠️ If SMTP not working: check .env has no duplicate SMTP block above real credentials.

## SQLite DB (`propos.db`)
```sql
-- Add test subscriber:
sqlite3 /root/propos/propos.db "INSERT OR IGNORE INTO subscribers (email,source,active) VALUES ('mailtcb2150@gmail.com','admin',1);"
```

## Cron Jobs (VPS)
```
# Run: crontab -l on VPS
0 9 * * 1-5  cd /root/propos && .venv/bin/python scripts/sync_hdb.py
0 8 * * 0    cd /root/propos && .venv/bin/python agents/weekly_digest.py  # Sunday digest
```

## Singapore Property Rules (hardcoded in agents)
- SSD: 12%/8%/4% if sold within 1/2/3 years of purchase
- ABSD: 20% on 2nd property (SC), 65% foreigners
- TDSR: 55% of gross monthly income
- LTV: 75% private (bank), 80% HDB (HDB loan)
- MOP: 5 years for BTO/resale HDB before can sell/rent entire flat
- NOO property tax: 11%/16%/21%/27% progressive on AV
- AV ≈ annual rental value (what IRAS estimates property would fetch if rented)

## Known Issues / Gotchas
- HDB pipeline `psf_sgd` vs `psf` — always use `.get("psf_sgd", .get("psf", 0))`
- URA transactions take 15-30s to scan — always use `_cached_ura_transactions()`
- Ghost positions in IBKR unrelated to PropOS (different project)
- `_requests_lib` is the global alias for `requests` in app.py (imported at top as `import requests as _requests_lib`)
- Telegram inline button callbacks: `update.message` is always None — use `ctx.bot.send_message()`

## Monetisation Streams
1. SaaS: Investor SGD99, Professional SGD299, Enterprise SGD999+/month
2. Mortgage referrals: SGD1,200–3,000 per closed loan
3. Insurance referrals: SGD100–5,000 per policy (MRTA highest)
4. Legal: SGD300–500 per conveyancing referral
5. Renovation: 5–8% referral fee

## Critical Rules
- NEVER give personalised financial advice — output data/information only
- NEVER act as unlicensed mortgage broker — compare rates, refer to banks
- NEVER act as unlicensed estate agent — no transaction facilitation
- Always show data sources + confidence ranges on valuations
- Insurance = referral only, never advice

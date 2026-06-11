# PropOS — AI Property Intelligence Platform

## Infrastructure
- Local dev: ~/Documents/PropOS/
- VPS: New Hetzner CX32 (4 vCPU, 8GB RAM) — separate from trading VPS
- GitHub: github.com/[user]/propos (private repo)
- Dashboard: http://[vps-ip]:8502 (Streamlit)
- API: http://[vps-ip]:8000 (FastAPI)

## Key Commands
```bash
# Local dev
cd ~/Documents/PropOS
python -m uvicorn api.main:app --reload --port 8000
streamlit run dashboard/app.py --server.port 8502
python scripts/sync_ura.py          # Manual URA data sync
python scripts/sync_hdb.py          # Manual HDB data sync
python bot/telegram_bot.py          # Start Telegram bot

# DB
python scripts/setup_db.py          # Initialise PostgreSQL schema

# LLM mode (admin)
curl -X POST http://localhost:8000/admin/llm-mode -d '{"mode":"quality"}'
```

## LLM Modes (admin switchable)
- free      → Gemini 2.0 Flash (free tier, rate limited)
- balanced  → Groq Llama 3.1 8B (near-free, fast)
- quality   → Claude Haiku 4.5 (paid, default production)
- premium   → Claude Sonnet 4.6 (full quality, demos/VC)

## File Structure
```
config/
  settings.json          — LLM mode, feature flags, API keys refs
  insurance_partners.json — Insurance referral partners + commission rates
core/
  llm_router.py          — Multi-LLM routing with mode switching
  token_tracker.py       — Per-query cost tracking
  cache.py               — File-based cache (avoid redundant API calls)
data/
  ura_pipeline.py        — URA private residential transactions
  hdb_pipeline.py        — HDB resale + rental data
  news_pipeline.py       — RSS: The Edge SG, BT, CNA, PropertyGuru
  onemap_client.py       — Singapore geospatial (MRT distance, amenities)
agents/
  base_agent.py          — Base class: token tracking, mode awareness, caching
  valuation_agent.py     — Fair value vs transacted price
  deal_hunter_agent.py   — Below-market, distressed, arbitrage detection
  mortgage_agent.py      — Bank rate comparison, refi alerts
  news_intel_agent.py    — Sentiment scoring, policy change detection
  wealth_agent.py        — Portfolio NW, CPF projection
  insurance_agent.py     — Gap analysis, referral triggers
api/
  main.py                — FastAPI app, CORS, auth
  routes/portfolio.py    — Portfolio CRUD + NW calculation
  routes/deals.py        — Deal feed + alerts
  routes/mortgage.py     — Mortgage comparison
  routes/insurance.py    — Insurance referral triggers
  routes/admin.py        — LLM mode + token cost dashboard
  models.py              — Pydantic schemas
bot/
  telegram_bot.py        — Deal alerts, portfolio queries via Telegram
dashboard/
  app.py                 — Streamlit UI (portfolio, deals, admin)
scripts/
  setup_db.py            — PostgreSQL schema init
  sync_ura.py            — Cron: daily URA sync
  sync_hdb.py            — Cron: weekly HDB sync
  sync_news.py           — Cron: hourly news sync
```

## Data Sources
- URA API: https://www.ura.gov.sg/maps/api/ (free, need token)
- HDB: https://data.gov.sg/collections/189/view (free)
- data.gov.sg: https://data.gov.sg (free API)
- OneMap: https://www.onemap.gov.sg/apidocs/ (free, SLA login)
- MAS: https://eservices.mas.gov.sg/api/action/ (free)
- News RSS: The Edge SG, Business Times, CNA, PropertyGuru, OrangeTee

## API Keys Needed (store in .env)
- URA_ACCESS_KEY       — ura.gov.sg/maps/api (free registration)
- ONEMAP_TOKEN         — onemap.gov.sg (free, renews monthly)
- ANTHROPIC_API_KEY    — console.anthropic.com
- GEMINI_API_KEY       — aistudio.google.com (free tier)
- GROQ_API_KEY         — console.groq.com (free tier)
- TELEGRAM_BOT_TOKEN   — @BotFather on Telegram
- DATABASE_URL         — postgresql://user:pass@localhost/propos
- NEWSAPI_KEY          — newsapi.org (free 100 req/day)

## Insurance Partners (referral only — not advice)
- NTUC Income: home, fire, landlord insurance
- FWD Singapore: home, mortgage insurance
- AIG Singapore: property insurance
- Tokio Marine: landlord, commercial property
- Great Eastern: MRTA/MLTA (mortgage life)
- Manulife SG: MRTA/MLTA
Contact each directly for referral partnership agreements.

## Critical Rules
- NEVER give personalised financial advice — output data/information only
- NEVER act as unlicensed mortgage broker — compare rates, refer to banks
- NEVER act as unlicensed estate agent — no transaction facilitation
- Always show data sources and confidence ranges on valuations
- Insurance = referral only, never advice

## Monetisation Streams
1. SaaS: Investor SGD99, Professional SGD299, Enterprise SGD999+/month
2. Mortgage referrals: SGD1,200-3,000 per closed loan
3. Insurance referrals: SGD100-5,000 per policy (MRTA highest)
4. Legal referrals: SGD300-500 per conveyancing
5. Renovation contractor: 5-8% referral fee
6. Agent CMA tool: SGD299/month (Professional tier)

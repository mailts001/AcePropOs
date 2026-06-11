"""
PropOS FastAPI backend.
Endpoints: portfolio, deals, mortgage, insurance, admin (LLM mode + token costs).
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

# Import agents
from agents.valuation_agent import ValuationAgent
from agents.deal_hunter_agent import DealHunterAgent
from agents.news_intel_agent import NewsIntelAgent
from agents.insurance_agent import InsuranceAgent
from core.llm_router import save_mode, get_current_mode, get_token_summary

app = FastAPI(title="PropertyOS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


def get_admin_password():
    return os.environ.get("ADMIN_PASSWORD", "changeme")


def require_admin(x_admin_key: str = Header(default="")):
    if x_admin_key != get_admin_password():
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


# ── Pydantic Models ───────────────────────────────────────────────────────────

class ValuationRequest(BaseModel):
    district: int
    area_sqft: float
    property_type: str = "Condominium"
    asking_price: float = 0
    explain: bool = True


class HDBValuationRequest(BaseModel):
    town: str
    flat_type: str
    floor_area_sqft: float
    asking_price: float = 0
    explain: bool = True


class DealScanRequest(BaseModel):
    districts: Optional[list[int]] = None
    threshold_pct: float = 8.0
    limit: int = 10
    summarise: bool = True


class LLMModeRequest(BaseModel):
    mode: str  # free | balanced | quality | premium


class PortfolioInsuranceRequest(BaseModel):
    properties: list[dict]


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "app": "PropertyOS", "version": "0.1.0"}


@app.get("/health")
def health():
    mode = get_current_mode()
    return {"status": "ok", "llm_mode": mode["mode"], "model": mode["model"]}


# ── Valuation ──────────────────────────────────────────────────────────────────

@app.post("/valuation/private")
def value_private(req: ValuationRequest):
    agent = ValuationAgent()
    return agent.value_private_property(
        district=req.district,
        area_sqft=req.area_sqft,
        property_type=req.property_type,
        asking_price=req.asking_price,
        explain=req.explain,
    )


@app.post("/valuation/hdb")
def value_hdb(req: HDBValuationRequest):
    agent = ValuationAgent()
    return agent.value_hdb(
        town=req.town,
        flat_type=req.flat_type,
        floor_area_sqft=req.floor_area_sqft,
        asking_price=req.asking_price,
        explain=req.explain,
    )


# ── Deal Hunter ────────────────────────────────────────────────────────────────

@app.post("/deals/private")
def scan_private_deals(req: DealScanRequest):
    agent = DealHunterAgent()
    return agent.scan_private_deals(
        districts=req.districts,
        threshold_pct=req.threshold_pct,
        limit=req.limit,
        summarise=req.summarise,
    )


@app.post("/deals/hdb")
def scan_hdb_deals(req: DealScanRequest):
    agent = DealHunterAgent()
    return agent.scan_hdb_deals(threshold_pct=req.threshold_pct, limit=req.limit)


@app.get("/deals/rental-arbitrage")
def rental_arbitrage(target_yield: float = 4.0):
    agent = DealHunterAgent()
    return agent.scan_rental_arbitrage(target_gross_yield_pct=target_yield)


@app.get("/deals/news")
def news_deal_alerts():
    agent = DealHunterAgent()
    return agent.news_deal_alerts()


# ── News Intelligence ──────────────────────────────────────────────────────────

@app.get("/news/briefing")
def market_briefing():
    agent = NewsIntelAgent()
    return agent.get_market_briefing()


@app.get("/news/sentiment")
def sentiment_index():
    from data.news_pipeline import get_sentiment_index
    return get_sentiment_index()


@app.get("/news/policy-alerts")
def policy_alerts():
    agent = NewsIntelAgent()
    return agent.detect_policy_changes()


@app.get("/news/district/{district_id}")
def district_news_sentiment(district_id: int):
    agent = NewsIntelAgent()
    return agent.get_district_news_sentiment(district_id)


# ── Insurance ──────────────────────────────────────────────────────────────────

@app.post("/insurance/portfolio-gaps")
def insurance_portfolio_gaps(req: PortfolioInsuranceRequest):
    agent = InsuranceAgent()
    return agent.analyse_portfolio_gaps({"properties": req.properties})


@app.get("/insurance/mortgage-prompt")
def mortgage_insurance_prompt(loan_amount: float, tenure_years: int = 25):
    agent = InsuranceAgent()
    return agent.mortgage_insurance_prompt(loan_amount, tenure_years)


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin/status", dependencies=[Depends(require_admin)])
def admin_status():
    return {
        "llm": get_current_mode(),
        "tokens": get_token_summary(),
    }


@app.post("/admin/llm-mode", dependencies=[Depends(require_admin)])
def set_llm_mode(req: LLMModeRequest):
    """Switch LLM mode live. free/balanced/quality/premium."""
    try:
        save_mode(req.mode)
        return {"status": "ok", "mode": req.mode, "config": get_current_mode()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/admin/token-costs", dependencies=[Depends(require_admin)])
def token_costs():
    return get_token_summary()


@app.post("/admin/sync/ura", dependencies=[Depends(require_admin)])
def trigger_ura_sync():
    from data.ura_pipeline import sync_all_batches
    total = sync_all_batches()
    return {"status": "ok", "transactions_synced": total}


@app.post("/admin/sync/hdb", dependencies=[Depends(require_admin)])
def trigger_hdb_sync():
    from data.hdb_pipeline import sync_all
    sync_all()
    return {"status": "ok"}


@app.post("/admin/sync/news", dependencies=[Depends(require_admin)])
def trigger_news_sync():
    from data.news_pipeline import sync_news
    articles = sync_news()
    return {"status": "ok", "articles_fetched": len(articles)}

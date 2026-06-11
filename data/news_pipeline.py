"""
Singapore Property News Pipeline
Sources: RSS feeds from The Edge SG, Business Times, CNA, PropertyGuru, 99.co
No API keys needed for RSS. NewsAPI key optional for broader coverage.
Runs hourly via cron to detect policy changes, sentiment shifts.
"""

import json
import time
import os
import re
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from collections import Counter

CACHE_DIR = Path(__file__).parent.parent / "cache" / "news"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RSS_FEEDS = {
    "business_times_property": "https://www.businesstimes.com.sg/rss/property",
    "cna_business": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511",
    "propertyguru_news": "https://www.propertyguru.com.sg/property-news/feed",
    "99co_blog": "https://www.99.co/singapore/insider/feed/",
    "edgeprop_sg": "https://www.edgeprop.sg/rss.xml",
}

# Keyword weights for property relevance + sentiment scoring
BULLISH_KEYWORDS = [
    "surge", "growth", "increase", "rise", "strong demand",
    "new high", "outperform", "upgrade", "boom", "rally",
    "en bloc", "collective sale", "new launch", "oversubscribed",
    "record high", "record price", "record psf", "highest ever",
    "most expensive", "sold above", "beat valuation", "profit",
]
BEARISH_KEYWORDS = [
    "cooling measure", "absd", "tdsr", "ltvr", "restrict", "curb",
    "decline", "fall", "drop", "weak", "oversupply", "vacancy",
    "interest rate hike", "recession", "caution", "slow",
    # Loss / negative return signals
    "loss", "capital loss", "at a loss", "sold at a loss", "record loss",
    "negative return", "losing", "lost money", "underwater",
    "price cut", "price drop", "reduced asking", "below purchase price",
    "unsold", "developer cut", "foreclos", "mortgagee",
]
# Contextual overrides: these phrases negate a bullish keyword nearby
_LOSS_PHRASES = [
    "at a loss", "sold at a loss", "capital loss", "record loss",
    "highest loss", "largest loss", "loss of s$", "loss of $",
]
POLICY_KEYWORDS = [
    "mas ", "ura ", "hdb ", "cooling measure", "absd", "bsd", "tdsr",
    "stamp duty", "property tax", "urban redevelopment", "master plan",
    "budget 2", "finance minister", "government policy",
]
OPPORTUNITY_KEYWORDS = [
    "below valuation", "distressed", "mortgagee sale", "auction",
    "fire sale", "urgent sale", "motivated seller", "price cut",
    "reduced", "negotiable",
]

SECTOR_KEYWORDS = {
    "HDB": ["hdb", "bto", "resale flat", "public housing", "hdb resale", "hdb rental", "mop", "built-to-order"],
    "Private Condo": ["condo", "condominium", "private residential", "new launch", "en bloc", "collective sale", "econdo", "executive condo"],
    "Landed": ["landed", "bungalow", "semi-detached", "terrace house", "good class bungalow", "gcb"],
    "Commercial": ["office", "retail", "shophouse", "industrial", "reit", "commercial property"],
    "Rental": ["rental", "tenant", "landlord", "lease", "tenancy", "rent"],
    "Policy": ["mas ", "ura ", "cooling measure", "absd", "stamp duty", "tdsr", "ltvr", "budget", "property tax"],
}

HDB_BULLISH = ["bto popular", "oversubscribed", "record resale", "resale prices rise", "hdb grant"]
HDB_BEARISH = ["hdb vacancy", "hdb oversupply", "bto delay", "hdb rental drop"]
PRIVATE_BULLISH = ["new launch sells", "en bloc", "psf record", "luxury demand", "foreign buyer"]
PRIVATE_BEARISH = ["absd", "cooling", "unsold units", "developer discount", "luxury cooling"]


def fetch_rss(url: str, source: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of article dicts."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "PropertyOS/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        articles = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            description = item.findtext("description", "") or ""
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            text = f"{title} {description}".lower()
            articles.append({
                "source": source,
                "title": title,
                "description": _clean_html(description)[:300],
                "link": link,
                "pub_date": pub_date,
                "fetched_at": time.time(),
                "sentiment_score": _score_sentiment(text),
                "is_policy": _has_keywords(text, POLICY_KEYWORDS),
                "is_opportunity": _has_keywords(text, OPPORTUNITY_KEYWORDS),
                "relevance": _score_relevance(text),
                "sectors": _tag_sectors(text),
            })
        return articles
    except Exception as e:
        print(f"[News] RSS fetch failed for {source}: {e}")
        return []


def _clean_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _has_keywords(text: str, keywords: list) -> bool:
    return any(kw in text for kw in keywords)


def _score_sentiment(text: str) -> float:
    """Returns -1.0 (bearish) to +1.0 (bullish)."""
    # Loss phrases hard-override any bullish signals — a loss story is always bearish
    if any(phrase in text for phrase in _LOSS_PHRASES):
        return -0.8
    bull = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bear = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
    total = bull + bear
    if total == 0:
        return 0.0
    return round((bull - bear) / total, 2)


def _tag_sectors(text: str) -> list[str]:
    return [sector for sector, keywords in SECTOR_KEYWORDS.items() if any(kw in text for kw in keywords)]


def _score_relevance(text: str) -> float:
    """0.0-1.0 score for how property-relevant this article is."""
    property_terms = [
        "condo", "hdb", "property", "real estate", "apartment", "bto",
        "resale", "rental", "tenant", "landlord", "mortgage", "loan",
        "developer", "launch", "district", "psf", "sqft",
    ]
    hits = sum(1 for t in property_terms if t in text)
    return min(1.0, hits / 5)


def sync_news() -> list[dict]:
    """Fetch all RSS feeds and cache results. Run hourly."""
    all_articles = []
    for source, url in RSS_FEEDS.items():
        articles = fetch_rss(url, source)
        all_articles.extend(articles)
        time.sleep(0.5)

    # Filter to property-relevant articles
    relevant = [a for a in all_articles if a["relevance"] >= 0.4]
    relevant.sort(key=lambda x: x.get("pub_date", ""), reverse=True)

    cache_path = CACHE_DIR / "latest_articles.json"
    cache_path.write_text(json.dumps(relevant[:200]))  # Keep top 200
    print(f"[News] Synced {len(all_articles)} articles, {len(relevant)} property-relevant")
    return relevant


def get_latest_articles(limit: int = 20, policy_only: bool = False) -> list[dict]:
    cache_path = CACHE_DIR / "latest_articles.json"
    if not cache_path.exists():
        return []
    articles = json.loads(cache_path.read_text())
    if policy_only:
        articles = [a for a in articles if a["is_policy"]]
    return articles[:limit]


def get_sentiment_index() -> dict:
    """
    Compute a rolling property sentiment score from recent articles.
    Returns index from -1.0 (very bearish) to +1.0 (very bullish).
    Published daily to Telegram channel as a moat signal.
    """
    articles = get_latest_articles(limit=50)
    if not articles:
        return {"score": 0.0, "label": "Neutral", "count": 0}

    scores = [a["sentiment_score"] for a in articles]
    avg = sum(scores) / len(scores)

    if avg >= 0.3:
        label = "Bullish"
    elif avg >= 0.1:
        label = "Mildly Bullish"
    elif avg <= -0.3:
        label = "Bearish"
    elif avg <= -0.1:
        label = "Mildly Bearish"
    else:
        label = "Neutral"

    policy_alerts = [a for a in articles if a["is_policy"]]
    opportunity_alerts = [a for a in articles if a["is_opportunity"]]

    return {
        "score": round(avg, 3),
        "label": label,
        "article_count": len(articles),
        "policy_alerts": len(policy_alerts),
        "opportunity_alerts": len(opportunity_alerts),
        "top_policy": policy_alerts[0]["title"] if policy_alerts else None,
        "computed_at": datetime.now().isoformat(),
    }


def get_opportunity_articles() -> list[dict]:
    """Articles flagging distressed sales, auctions, price cuts — feeds DealHunterAgent."""
    return [a for a in get_latest_articles(limit=100) if a["is_opportunity"]]


def get_sector_breakdown() -> dict:
    """
    Returns per-sector article counts + sentiment scores.
    Sectors: HDB, Private Condo, Landed, Commercial, Rental, Policy.
    """
    articles = get_latest_articles(limit=100)
    breakdown = {}
    for sector in SECTOR_KEYWORDS:
        sector_articles = [a for a in articles if sector in a.get("sectors", [])]
        if not sector_articles:
            breakdown[sector] = {"count": 0, "sentiment": 0.0, "label": "No data", "top_articles": []}
            continue
        scores = [a["sentiment_score"] for a in sector_articles]
        avg = round(sum(scores) / len(scores), 3)
        label = "Bullish" if avg >= 0.2 else ("Bearish" if avg <= -0.2 else "Neutral")
        breakdown[sector] = {
            "count": len(sector_articles),
            "sentiment": avg,
            "label": label,
            "top_articles": [
                {"title": a["title"], "link": a["link"], "pub_date": a["pub_date"],
                 "sentiment_score": a["sentiment_score"], "is_policy": a["is_policy"],
                 "description": a["description"]}
                for a in sorted(sector_articles, key=lambda x: abs(x["sentiment_score"]), reverse=True)[:5]
            ],
        }
    return breakdown


def get_trending_topics() -> dict:
    """Extract trending bullish and bearish topics from recent headlines."""
    articles = get_latest_articles(limit=100)
    bullish_arts = sorted([a for a in articles if a["sentiment_score"] > 0.2], key=lambda x: x["sentiment_score"], reverse=True)
    bearish_arts = sorted([a for a in articles if a["sentiment_score"] < -0.2], key=lambda x: x["sentiment_score"])

    # Count keyword hits across all articles for trending terms
    all_text = " ".join(a["title"].lower() + " " + a.get("description", "").lower() for a in articles)
    trending_kws = [
        "en bloc", "bto", "resale", "cooling", "absd", "rental", "interest rate",
        "hdb", "condo", "new launch", "psf", "vacancy", "demand", "supply",
    ]
    kw_counts = {kw: all_text.count(kw) for kw in trending_kws if all_text.count(kw) > 0}
    top_keywords = sorted(kw_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "trending_up": [{"title": a["title"], "link": a["link"], "sectors": a.get("sectors", []), "score": a["sentiment_score"]} for a in bullish_arts[:5]],
        "trending_down": [{"title": a["title"], "link": a["link"], "sectors": a.get("sectors", []), "score": a["sentiment_score"]} for a in bearish_arts[:5]],
        "hot_keywords": top_keywords,
        "policy_articles": [
            {"title": a["title"], "link": a["link"], "description": a["description"], "pub_date": a["pub_date"]}
            for a in articles if a["is_policy"]
        ][:8],
        "opportunity_articles": [
            {"title": a["title"], "link": a["link"], "description": a["description"], "pub_date": a["pub_date"]}
            for a in articles if a["is_opportunity"]
        ][:8],
    }


if __name__ == "__main__":
    sync_news()
    print(json.dumps(get_sentiment_index(), indent=2))

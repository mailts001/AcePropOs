"""
DealHunterAgent — scans for below-market properties, rental arbitrage,
Master Plan opportunities, and distressed sales.
Core detection is rule-based (free). LLM used only for deal summaries.
"""

import json
from agents.base_agent import BaseAgent
from data.ura_pipeline import get_district_stats, search_transactions
from data.hdb_pipeline import find_below_market_hdb
from data.news_pipeline import get_opportunity_articles, get_sentiment_index


class DealHunterAgent(BaseAgent):
    name = "DealHunterAgent"
    preferred_mode = "balanced"

    def scan_private_deals(
        self,
        districts: list[int] = None,
        threshold_pct: float = 8.0,
        limit: int = 10,
        summarise: bool = True,
    ) -> dict:
        """
        Scan URA transactions for private properties trading below district median.
        threshold_pct: minimum % below median to flag as opportunity.
        summarise=True uses LLM for deal summary narrative.
        """
        target_districts = districts or list(range(1, 29))
        opportunities = []

        for district in target_districts:
            stats = get_district_stats(district)
            if stats.get("count", 0) < 10:
                continue

            median_psf = stats["median_psf"]
            # Look for recent transactions below threshold
            txns = search_transactions(district=district, limit=200)

            for txn in txns[:50]:  # Check most recent 50 per district
                if txn["psf_sgd"] <= 0:
                    continue
                discount_pct = (median_psf - txn["psf_sgd"]) / median_psf * 100
                if discount_pct >= threshold_pct:
                    opportunities.append({
                        "type": "private",
                        "project": txn["project"],
                        "street": txn["street"],
                        "district": district,
                        "psf_sgd": txn["psf_sgd"],
                        "median_psf": median_psf,
                        "discount_pct": round(discount_pct, 1),
                        "price_sgd": txn["price_sgd"],
                        "area_sqft": txn["area_sqft"],
                        "property_type": txn["property_type"],
                        "contract_date": txn["contract_date"],
                        "deal_score": self._deal_score(discount_pct),
                        "potential_upside_sgd": round(
                            (median_psf - txn["psf_sgd"]) * txn["area_sqft"], 0
                        ),
                    })

        opportunities.sort(key=lambda x: x["deal_score"], reverse=True)
        top = opportunities[:limit]

        result = {
            "scan_type": "private_below_market",
            "threshold_pct": threshold_pct,
            "opportunities_found": len(opportunities),
            "top_deals": top,
            "sentiment": get_sentiment_index(),
        }

        if summarise and top:
            result["summary"] = self._summarise_deals(top[:3])

        # Insurance trigger: deal hunter users are likely buyers
        result["insurance_suggestions"] = self.check_insurance_triggers("new_property_added")

        return result

    def scan_hdb_deals(self, threshold_pct: float = 8.0, limit: int = 10) -> dict:
        """Scan HDB resale transactions for below-market opportunities."""
        opportunities = find_below_market_hdb(threshold_pct=threshold_pct, limit=limit * 2)
        top = opportunities[:limit]

        return {
            "scan_type": "hdb_below_market",
            "threshold_pct": threshold_pct,
            "opportunities_found": len(opportunities),
            "top_deals": top,
        }

    def scan_rental_arbitrage(
        self,
        target_gross_yield_pct: float = 4.0,
        districts: list[int] = None,
    ) -> dict:
        """
        Find properties where estimated rental yield exceeds target.
        Rental yield = (annual rent / purchase price) * 100
        Uses district-level rental benchmarks from HDB data.
        """
        # Rough Singapore rental benchmarks by district (SGD/month for 1000 sqft condo)
        # These are manually maintained estimates — replace with live data when available
        RENTAL_BENCHMARKS = {
            1: 5500, 2: 5200, 3: 4800, 4: 5000, 5: 4500,
            7: 4800, 8: 4200, 9: 6500, 10: 7000, 11: 6000,
            12: 4000, 13: 3800, 14: 3600, 15: 4500, 16: 3800,
            17: 3500, 18: 3400, 19: 3800, 20: 3700, 21: 4200,
            22: 3600, 23: 3800, 25: 3400, 26: 3600, 27: 3500,
            28: 3600,
        }

        target_districts = districts or list(range(1, 29))
        opportunities = []

        for district in target_districts:
            monthly_rent = RENTAL_BENCHMARKS.get(district, 0)
            if not monthly_rent:
                continue

            stats = get_district_stats(district)
            if stats.get("count", 0) < 5:
                continue

            median_price = stats["median_price"]
            if median_price <= 0:
                continue

            annual_rent = monthly_rent * 12
            gross_yield = (annual_rent / median_price) * 100
            # Net yield estimate: -1.5% for maintenance, tax, vacancy
            net_yield = gross_yield - 1.5

            if gross_yield >= target_gross_yield_pct:
                opportunities.append({
                    "district": district,
                    "estimated_monthly_rent": monthly_rent,
                    "median_price_sgd": median_price,
                    "gross_yield_pct": round(gross_yield, 2),
                    "net_yield_pct": round(net_yield, 2),
                    "annual_rental_income": annual_rent,
                    "transactions_used": stats["count"],
                })

        opportunities.sort(key=lambda x: x["gross_yield_pct"], reverse=True)

        return {
            "scan_type": "rental_arbitrage",
            "target_yield_pct": target_gross_yield_pct,
            "qualifying_districts": len(opportunities),
            "opportunities": opportunities[:10],
        }

    def scan_hdb_rental_yield(self, target_gross_yield_pct: float = 3.5) -> dict:
        """
        Compute rental yield for all HDB towns using median resale prices
        vs SRX/HDB benchmark rental rates.
        Returns towns meeting the yield target, sorted by yield desc.
        """
        # HDB town rental benchmarks (SGD/month for a 4-room flat, ~1,000 sqft)
        # Based on SRX median rental data 2024-2025
        HDB_TOWN_RENT = {
            "ANG MO KIO": 2800, "BEDOK": 2700, "BISHAN": 3000, "BUKIT BATOK": 2600,
            "BUKIT MERAH": 3200, "BUKIT PANJANG": 2500, "BUKIT TIMAH": 3100,
            "CENTRAL AREA": 4200, "CHOA CHU KANG": 2500, "CLEMENTI": 2900,
            "GEYLANG": 2800, "HOUGANG": 2600, "JURONG EAST": 2700,
            "JURONG WEST": 2600, "KALLANG/WHAMPOA": 3100, "MARINE PARADE": 3200,
            "PASIR RIS": 2600, "PUNGGOL": 2600, "QUEENSTOWN": 3400,
            "SEMBAWANG": 2400, "SENGKANG": 2600, "SERANGOON": 2900,
            "TAMPINES": 2700, "TOA PAYOH": 3000, "WOODLANDS": 2400,
            "YISHUN": 2500,
        }
        from data.hdb_pipeline import get_town_stats
        opportunities = []
        for town, monthly_rent in HDB_TOWN_RENT.items():
            stats = get_town_stats(town, "4 ROOM")
            if stats.get("count", 0) < 3:
                continue
            median_price = stats.get("median_price", 0)
            if not median_price:
                continue
            annual_rent = monthly_rent * 12
            gross_yield = round(annual_rent / median_price * 100, 2)
            net_yield = round(gross_yield - 1.2, 2)  # ~1.2% for maintenance + tax + vacancy
            if gross_yield >= target_gross_yield_pct:
                opportunities.append({
                    "town": town,
                    "gross_yield_pct": gross_yield,
                    "net_yield_pct": net_yield,
                    "median_price_sgd": median_price,
                    "est_monthly_rent_sgd": monthly_rent,
                    "annual_rental_income": annual_rent,
                    "transactions_used": stats["count"],
                })
        opportunities.sort(key=lambda x: x["gross_yield_pct"], reverse=True)
        return {
            "scan_type": "hdb_rental_yield",
            "target_yield_pct": target_gross_yield_pct,
            "towns_qualifying": len(opportunities),
            "opportunities": opportunities,
        }

    def news_deal_alerts(self) -> list[dict]:
        """Fetch distressed sale / auction opportunities from news pipeline."""
        articles = get_opportunity_articles()
        return [
            {
                "source": a["source"],
                "title": a["title"],
                "description": a["description"],
                "link": a["link"],
                "pub_date": a["pub_date"],
                "opportunity_type": "news_flagged",
            }
            for a in articles[:10]
        ]

    def _deal_score(self, discount_pct: float) -> int:
        if discount_pct >= 20:
            return 95
        if discount_pct >= 15:
            return 85
        if discount_pct >= 10:
            return 75
        if discount_pct >= 8:
            return 65
        return 50

    def _summarise_deals(self, deals: list[dict]) -> str:
        """LLM narrative for top deals. Intentionally short to save tokens."""
        prompt = f"""
In 2-3 sentences, summarise these Singapore property deals for an investor.
Focus on: location, discount vs market, and why each is interesting.
Be specific with numbers. No markdown.

Deals:
{json.dumps(deals, indent=2)}
"""
        resp = self._llm(prompt, max_tokens=200, use_cache=True)
        return resp.content.strip()

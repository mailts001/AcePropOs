"""
ValuationAgent — estimates fair value of Singapore properties.
Uses URA/HDB transaction data as baseline (no LLM needed for core calc).
LLM used only for narrative explanation — routes to 'balanced' mode to save tokens.
"""

import json
from agents.base_agent import BaseAgent
from data.ura_pipeline import get_district_stats, search_transactions
from data.hdb_pipeline import get_town_stats, lookup_by_address, search_by_street


class ValuationAgent(BaseAgent):
    name = "ValuationAgent"
    preferred_mode = "balanced"  # Structured output — no need for premium LLM

    def value_private_property(
        self,
        district: int,
        area_sqft: float,
        property_type: str = "Condominium",
        asking_price: float = 0,
        explain: bool = True,
    ) -> dict:
        """
        Estimate fair value for a private property.
        Returns: value estimate, confidence band, vs-market comparison.
        explain=True adds LLM narrative (uses tokens). explain=False is free.
        """
        stats = get_district_stats(district, property_type)

        if stats.get("count", 0) < 5:
            return {
                "status": "insufficient_data",
                "district": district,
                "message": f"Only {stats.get('count', 0)} transactions in District {district}. Need 5+ for reliable estimate.",
            }

        median_psf = stats["median_psf"]
        p25_psf = stats["p25_psf"]
        p75_psf = stats["p75_psf"]

        estimated_value = round(median_psf * area_sqft, 0)
        low_estimate = round(p25_psf * area_sqft, 0)
        high_estimate = round(p75_psf * area_sqft, 0)

        result = {
            "status": "ok",
            "district": district,
            "property_type": property_type,
            "area_sqft": area_sqft,
            "estimated_value_sgd": estimated_value,
            "low_estimate_sgd": low_estimate,
            "high_estimate_sgd": high_estimate,
            "median_psf": median_psf,
            "p25_psf": p25_psf,
            "p75_psf": p75_psf,
            "transactions_used": stats["count"],
            "confidence": self._confidence_label(stats["count"]),
        }

        if asking_price > 0:
            vs_median = round((asking_price - estimated_value) / estimated_value * 100, 1)
            result["asking_price_sgd"] = asking_price
            result["asking_psf"] = round(asking_price / area_sqft, 0)
            result["vs_median_pct"] = vs_median
            result["deal_score"] = self._deal_score(vs_median)
            result["verdict"] = self._verdict(vs_median)

        if explain and asking_price > 0:
            result["explanation"] = self._explain(result)

        # Insurance trigger: when user values a property they likely own or are buying
        result["insurance_suggestions"] = self.check_insurance_triggers(
            "new_property_added", {"district": district}
        )

        return result

    def value_hdb(
        self,
        town: str,
        flat_type: str,
        floor_area_sqft: float,
        asking_price: float = 0,
        explain: bool = True,
    ) -> dict:
        stats = get_town_stats(town, flat_type)

        if stats.get("count", 0) < 5:
            return {
                "status": "insufficient_data",
                "town": town,
                "message": f"Insufficient data for {flat_type} in {town}",
            }

        median_price = stats["median_price"]
        median_psf = stats["median_psf"]
        estimated_value = round(median_psf * floor_area_sqft, 0)

        result = {
            "status": "ok",
            "town": town,
            "flat_type": flat_type,
            "floor_area_sqft": floor_area_sqft,
            "estimated_value_sgd": estimated_value,
            "median_price_sgd": median_price,
            "p25_price": stats.get("p25_price", 0),
            "p75_price": stats.get("p75_price", 0),
            "median_psf": median_psf,
            "transactions_used": stats["count"],
            "confidence": self._confidence_label(stats["count"]),
        }

        if asking_price > 0:
            vs_median = round((asking_price - median_price) / median_price * 100, 1)
            result["asking_price_sgd"] = asking_price
            result["vs_median_pct"] = vs_median
            result["deal_score"] = self._deal_score(vs_median)
            result["verdict"] = self._verdict(vs_median)

        if explain and asking_price > 0:
            result["explanation"] = self._explain(result)

        return result

    def value_by_address(
        self,
        block: str,
        street: str,
        asking_price: float = 0,
        flat_type: str = "",
        explain: bool = True,
    ) -> dict:
        """
        Value an HDB flat by its actual block + street address.
        Example: value_by_address("123A", "TAMPINES ST 11", asking_price=580000)
        Uses real transaction history for that exact address.
        """
        lookup = lookup_by_address(block, street, flat_type)

        if not lookup.get("found"):
            # Try to suggest similar addresses
            suggestions = search_by_street(street, limit=5)
            return {
                "status": "not_found",
                "message": lookup.get("message", "Address not found"),
                "suggestions": [
                    f"Block {s['block']} {s['street_name']} ({s['flat_type']})"
                    for s in suggestions[:5]
                ],
            }

        latest = lookup["latest_transaction"]
        median_price = lookup["price_range"]["median"]
        town_median = lookup["town_median_price"]

        result = {
            "status": "ok",
            "source": "address_lookup",
            "address": f"Block {block} {street}",
            "town": lookup["town"],
            "flat_type": lookup["flat_type"],
            "transaction_count": lookup["transaction_count"],
            "latest_transacted_price": latest["price"],
            "latest_transacted_psf": latest["psf"],
            "latest_transaction_month": latest["month"],
            "storey": latest["storey"],
            "floor_area_sqft": latest["area_sqft"],
            "remaining_lease": latest["remaining_lease"],
            "address_median_price": median_price,
            "town_median_price": town_median,
            "avg_psf": lookup["avg_psf"],
            "price_range": lookup["price_range"],
            "confidence": self._confidence_label(lookup["transaction_count"]),
        }

        # Compare asking vs address-specific history
        if asking_price > 0:
            vs_address = round((asking_price - median_price) / median_price * 100, 1)
            vs_town = round((asking_price - town_median) / town_median * 100, 1) if town_median else None
            result["asking_price_sgd"] = asking_price
            result["vs_address_history_pct"] = vs_address
            result["vs_town_median_pct"] = vs_town
            result["deal_score"] = self._deal_score(vs_address)
            result["verdict"] = self._verdict(vs_address)
            result["negotiation_hint"] = self._negotiation_hint(asking_price, median_price, lookup)

        if explain and asking_price > 0:
            result["explanation"] = self._explain_address(result)

        result["insurance_suggestions"] = self.check_insurance_triggers("new_property_added")
        result["recent_transactions"] = lookup.get("all_transactions", [])[:5]

        return result

    def search_address_suggestions(self, street_keyword: str) -> list[str]:
        """Return address suggestions for autocomplete. No LLM needed."""
        matches = search_by_street(street_keyword, limit=10)
        return list({f"Block {m['block']} {m['street_name']}" for m in matches})

    def _negotiation_hint(self, asking: float, address_median: float, lookup: dict) -> str:
        """Suggest a counter-offer range based on address transaction history."""
        low = lookup["price_range"]["min"]
        high = lookup["price_range"]["max"]
        spread = high - low
        counter = round(address_median * 0.97 / 1000) * 1000  # 3% below address median, rounded
        return (
            f"Address transaction range: ${low:,.0f}–${high:,.0f}. "
            f"Suggested counter-offer: ~${counter:,.0f} (3% below address median)."
        )

    def _explain_address(self, result: dict) -> str:
        """LLM explanation for address-based valuation."""
        prompt = f"""
In 2 sentences, tell a Singapore HDB buyer whether this is a good deal based on actual transaction history at this block.
Be specific: mention the address, asking price vs address history, and one actionable recommendation.

Data: {json.dumps({k: v for k, v in result.items() if k not in ['insurance_suggestions', 'explanation', 'recent_transactions']}, indent=2)}

Plain text only. 2 sentences max.
"""
        resp = self._llm(prompt, max_tokens=120, use_cache=True)
        return resp.content.strip()

    def _confidence_label(self, count: int) -> str:
        if count >= 100:
            return "High"
        if count >= 30:
            return "Medium"
        return "Low"

    def _deal_score(self, vs_median_pct: float) -> int:
        """0-100 score. Higher = better deal (more below market)."""
        if vs_median_pct <= -20:
            return 95
        if vs_median_pct <= -10:
            return 80
        if vs_median_pct <= -5:
            return 65
        if vs_median_pct <= 0:
            return 50
        if vs_median_pct <= 5:
            return 35
        if vs_median_pct <= 10:
            return 20
        return 10

    def _verdict(self, vs_median_pct: float) -> str:
        if vs_median_pct <= -15:
            return "Significantly below market — strong buying opportunity"
        if vs_median_pct <= -8:
            return "Below market — good value"
        if vs_median_pct <= -3:
            return "Slightly below market"
        if vs_median_pct <= 3:
            return "Fairly priced"
        if vs_median_pct <= 8:
            return "Slightly above market"
        if vs_median_pct <= 15:
            return "Above market — negotiate down"
        return "Significantly overpriced"

    def _explain(self, result: dict) -> str:
        """LLM-generated narrative explanation. Uses tokens — only call when needed."""
        prompt = f"""
Provide a 2-3 sentence plain English explanation of this Singapore property valuation for an investor.
Be direct and concise. Mention the key number (vs_median_pct) and what action the investor should consider.

Data:
{json.dumps({k: v for k, v in result.items() if k not in ['insurance_suggestions', 'explanation']}, indent=2)}

Format: Plain text, no markdown, no bullet points. 2-3 sentences maximum.
"""
        resp = self._llm(prompt, max_tokens=150, use_cache=True)
        return resp.content.strip()

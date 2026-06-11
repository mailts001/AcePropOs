"""
InsuranceAgent — identifies insurance gaps and generates referral suggestions.
IMPORTANT: This agent surfaces information only. Never gives insurance advice.
Revenue: SGD 100-5,000 per referred policy (MRTA highest at SGD 2,000-5,000).
"""

import json
from agents.base_agent import BaseAgent


class InsuranceAgent(BaseAgent):
    name = "InsuranceAgent"
    preferred_mode = "balanced"  # Structured JSON output

    def analyse_portfolio_gaps(self, portfolio: dict) -> dict:
        """
        Given a user's property portfolio, identify potential insurance gaps.
        portfolio: {properties: [{type, value, has_fire, has_contents, has_landlord, has_mrta}]}
        Returns list of gap suggestions + estimated referral value.
        """
        properties = portfolio.get("properties", [])
        if not properties:
            return {"gaps": [], "total_referral_value_sgd": 0}

        gaps = []
        total_commission = 0

        for prop in properties:
            prop_type = prop.get("type", "condo")
            value = prop.get("value_sgd", 0)
            is_rented = prop.get("is_rented_out", False)
            has_mortgage = prop.get("has_mortgage", False)

            # Fire/building insurance — every property should have it
            if not prop.get("has_fire_insurance"):
                gaps.append({
                    "property": prop.get("name", "Property"),
                    "gap": "Fire/Building Insurance",
                    "priority": "High",
                    "reason": "Required for most mortgage agreements. Covers structural damage.",
                    "suggested_products": ["fire_insurance"],
                    "est_annual_premium_sgd": self._estimate_premium("fire_insurance", value),
                    "referral_commission_sgd": 120,
                })
                total_commission += 120

            # Contents insurance
            if not prop.get("has_contents_insurance") and not is_rented:
                gaps.append({
                    "property": prop.get("name", "Property"),
                    "gap": "Home Contents Insurance",
                    "priority": "Medium",
                    "reason": "Covers furniture, electronics, personal belongings from theft/damage.",
                    "suggested_products": ["home_contents"],
                    "est_annual_premium_sgd": self._estimate_premium("home_contents", value),
                    "referral_commission_sgd": 150,
                })
                total_commission += 150

            # Landlord insurance — critical if rented
            if is_rented and not prop.get("has_landlord_insurance"):
                gaps.append({
                    "property": prop.get("name", "Property"),
                    "gap": "Landlord Insurance",
                    "priority": "High",
                    "reason": "Covers rental income loss, tenant damage, public liability. Essential for landlords.",
                    "suggested_products": ["landlord_insurance"],
                    "est_annual_premium_sgd": self._estimate_premium("landlord_insurance", value),
                    "referral_commission_sgd": 300,
                })
                total_commission += 300

            # MRTA/MLTA — highest commission, tied to mortgage
            if has_mortgage and not prop.get("has_mortgage_insurance"):
                gaps.append({
                    "property": prop.get("name", "Property"),
                    "gap": "Mortgage Insurance (MRTA/MLTA)",
                    "priority": "High",
                    "reason": "Pays off your mortgage if you die or become critically ill. Protects your family.",
                    "suggested_products": ["mrta", "mlta"],
                    "est_annual_premium_sgd": self._estimate_premium("mrta", value),
                    "referral_commission_sgd": 2500,
                    "note": "MRTA (reducing) vs MLTA (level) — discuss with a licensed adviser.",
                })
                total_commission += 2500

        gaps.sort(key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["priority"]])

        return {
            "gaps": gaps,
            "gap_count": len(gaps),
            "total_referral_value_sgd": total_commission,
            "disclaimer": self._insurance["disclaimer"],
            "next_step": "Review these gaps with a licensed financial adviser. PropertyOS earns a referral fee if you proceed — this does not affect the products available to you.",
        }

    def mortgage_insurance_prompt(self, loan_amount_sgd: float, loan_tenure_years: int) -> dict:
        """
        When user initiates mortgage comparison, surface MRTA/MLTA options.
        Called by MortgageAgent as a hook.
        """
        # Rough MRTA annual premium estimate: 0.15-0.3% of loan amount
        est_annual_mrta = round(loan_amount_sgd * 0.002, 0)  # ~0.2% rough estimate

        return {
            "trigger": "mortgage_initiated",
            "loan_amount_sgd": loan_amount_sgd,
            "loan_tenure_years": loan_tenure_years,
            "insurance_products": [
                {
                    "type": "MRTA (Mortgage Reducing Term Assurance)",
                    "description": "Coverage reduces as loan reduces. Lower cost.",
                    "est_annual_premium_sgd": est_annual_mrta,
                    "referral_partners": ["great_eastern", "manulife_sg"],
                    "referral_commission_sgd": 2000,
                },
                {
                    "type": "MLTA (Mortgage Level Term Assurance)",
                    "description": "Coverage stays level throughout loan tenure. Higher payout.",
                    "est_annual_premium_sgd": round(est_annual_mrta * 1.4, 0),
                    "referral_partners": ["great_eastern", "manulife_sg"],
                    "referral_commission_sgd": 3000,
                },
            ],
            "disclaimer": self._insurance["disclaimer"],
        }

    def _estimate_premium(self, product: str, property_value: float) -> int:
        """Very rough annual premium estimates for display purposes only."""
        estimates = {
            "fire_insurance": max(200, int(property_value * 0.00015)),
            "home_contents": 300,
            "landlord_insurance": max(400, int(property_value * 0.0003)),
            "mrta": max(800, int(property_value * 0.002)),
            "mlta": max(1200, int(property_value * 0.003)),
        }
        return estimates.get(product, 500)

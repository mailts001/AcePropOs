"""
Base agent class. All PropertyOS agents inherit from this.
Provides: LLM routing, token tracking, caching, insurance trigger hooks.
"""

import json
from pathlib import Path
from typing import Optional
from core.llm_router import call as llm_call, LLMResponse, get_current_mode


INSURANCE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "insurance_partners.json"


class BaseAgent:
    """
    All agents inherit this. Handles:
    - LLM call routing with mode awareness
    - Automatic insurance referral trigger checks
    - Structured output helpers
    """

    name: str = "BaseAgent"
    # Agents can declare which LLM mode they prefer (overridable by admin)
    preferred_mode: Optional[str] = None

    def __init__(self):
        with open(INSURANCE_CONFIG_PATH) as f:
            self._insurance = json.load(f)

    def _llm(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        use_cache: bool = True,
        force_mode: Optional[str] = None,
    ) -> LLMResponse:
        """Call LLM with this agent's mode preference (or admin override)."""
        mode = force_mode or self.preferred_mode
        return llm_call(
            prompt=prompt,
            system=system or self._default_system(),
            mode_override=mode,
            use_cache=use_cache,
            max_tokens=max_tokens,
        )

    def _default_system(self) -> str:
        return (
            "You are PropertyOS, a Singapore property intelligence assistant. "
            "Provide data-driven analysis. Always cite data sources. "
            "Never give personalised financial, legal, or insurance advice. "
            "Present information for users to make their own informed decisions."
        )

    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text, "parse_error": True}

    def check_insurance_triggers(self, event: str, context: dict = {}) -> list[dict]:
        """
        Check if an event should trigger insurance referral suggestions.
        Events: new_property_added, mortgage_initiated, property_rented_out,
                annual_renewal_check, refi_triggered
        Returns list of insurance products to surface to user (not advice).
        """
        rules = self._insurance.get("trigger_rules", {})
        triggered_products = rules.get(event, [])
        if not triggered_products:
            return []

        partners = self._insurance["partners"]
        suggestions = []

        for product in triggered_products:
            if product == "all":
                # Annual renewal — surface all products
                for partner_id, partner in partners.items():
                    for p in partner["products"]:
                        suggestions.append(self._build_insurance_suggestion(partner_id, partner, p))
                break
            else:
                for partner_id, partner in partners.items():
                    if product in partner["products"]:
                        suggestions.append(self._build_insurance_suggestion(partner_id, partner, product))
                        break  # One partner per product type

        return suggestions

    def _build_insurance_suggestion(self, partner_id: str, partner: dict, product: str) -> dict:
        commission = partner.get("est_commission_sgd", {}).get(product, 0)
        return {
            "partner": partner["name"],
            "partner_id": partner_id,
            "product": product,
            "website": partner["website"],
            "referral_contact": partner["referral_contact"],
            "est_commission_sgd": commission,
            "disclaimer": self._insurance["disclaimer"],
            "call_to_action": f"Review your {product.replace('_', ' ')} coverage with {partner['name']}",
        }

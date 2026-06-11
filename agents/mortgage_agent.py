"""
MortgageAgent — Singapore mortgage calculator and refinancing advisor.
Core calculations are rule-based (free). LLM used only for refi narrative.
Drives MRTA/MLTA referrals — highest commission product (SGD 2,000–5,000/policy).
"""

import json
from agents.base_agent import BaseAgent

# ── Live-ish rate table (update monthly or scrape) ────────────────────────────
# Source: DBS/OCBC/UOB published rates, June 2026
# SORA 3M compounded: ~3.2% (approximate)
SORA_3M = 3.20  # Update when SORA changes

BANK_RATES = {
    "DBS": {
        "floating": [
            {"name": "SORA 3M + 0.80%", "year": "1-2", "rate": SORA_3M + 0.80, "lock_in": 2},
            {"name": "SORA 3M + 0.90%", "year": "3+", "rate": SORA_3M + 0.90, "lock_in": 0},
        ],
        "fixed": [
            {"name": "2-yr fixed", "year": "1-2", "rate": 3.75, "lock_in": 2},
            {"name": "3-yr fixed", "year": "1-3", "rate": 3.85, "lock_in": 3},
        ],
        "cashback": 0,
        "legal_subsidy": 2000,
    },
    "OCBC": {
        "floating": [
            {"name": "SORA 3M + 0.75%", "year": "1-2", "rate": SORA_3M + 0.75, "lock_in": 2},
            {"name": "SORA 3M + 0.85%", "year": "3+", "rate": SORA_3M + 0.85, "lock_in": 0},
        ],
        "fixed": [
            {"name": "2-yr fixed", "year": "1-2", "rate": 3.68, "lock_in": 2},
            {"name": "3-yr fixed", "year": "1-3", "rate": 3.78, "lock_in": 3},
        ],
        "cashback": 2000,
        "legal_subsidy": 2000,
    },
    "UOB": {
        "floating": [
            {"name": "SORA 3M + 0.78%", "year": "1-2", "rate": SORA_3M + 0.78, "lock_in": 2},
            {"name": "SORA 3M + 0.88%", "year": "3+", "rate": SORA_3M + 0.88, "lock_in": 0},
        ],
        "fixed": [
            {"name": "2-yr fixed", "year": "1-2", "rate": 3.70, "lock_in": 2},
            {"name": "3-yr fixed", "year": "1-3", "rate": 3.80, "lock_in": 3},
        ],
        "cashback": 1500,
        "legal_subsidy": 1800,
    },
    "Maybank": {
        "floating": [
            {"name": "SORA 3M + 0.72%", "year": "1-2", "rate": SORA_3M + 0.72, "lock_in": 2},
        ],
        "fixed": [
            {"name": "2-yr fixed", "year": "1-2", "rate": 3.65, "lock_in": 2},
        ],
        "cashback": 0,
        "legal_subsidy": 1500,
    },
    "HDB (CPF Board)": {
        "floating": [],
        "fixed": [
            {"name": "HDB Concessionary Rate", "year": "all", "rate": 2.60, "lock_in": 0},
        ],
        "cashback": 0,
        "legal_subsidy": 0,
        "note": "Only for HDB flats. Rate = CPF OA rate + 0.10%. No lock-in.",
    },
}

# CPF OA ceiling for property (as of 2026)
CPF_VALUATION_LIMIT_PCT = 1.0   # Can use CPF up to purchase price or valuation, whichever lower
CPF_WITHDRAWAL_LIMIT_PCT = 1.2  # Lifetime limit = 120% of valuation

# TDSR / MSR limits
TDSR_LIMIT = 0.55    # Total Debt Servicing Ratio: all loans ≤ 55% gross income
MSR_LIMIT = 0.30     # Mortgage Servicing Ratio: HDB/EC loan ≤ 30% gross income


class MortgageAgent(BaseAgent):
    name = "MortgageAgent"
    preferred_mode = "balanced"

    def calculate(
        self,
        property_price: float,
        loan_amount: float,
        tenure_years: int,
        annual_rate_pct: float,
        monthly_cpf_contribution: float = 0,
    ) -> dict:
        """Monthly repayment, total interest, CPF coverage breakdown."""
        r = annual_rate_pct / 100 / 12
        n = tenure_years * 12
        if r == 0:
            monthly = loan_amount / n
        else:
            monthly = loan_amount * r * (1 + r) ** n / ((1 + r) ** n - 1)

        total_paid = monthly * n
        total_interest = total_paid - loan_amount
        cpf_covers_pct = min(100, round(monthly_cpf_contribution / monthly * 100, 1)) if monthly > 0 else 0
        cash_top_up = max(0, monthly - monthly_cpf_contribution)

        return {
            "monthly_repayment": round(monthly, 2),
            "total_interest": round(total_interest, 2),
            "total_paid": round(total_paid, 2),
            "interest_to_loan_ratio": round(total_interest / loan_amount * 100, 1),
            "cpf_covers_pct": cpf_covers_pct,
            "monthly_cash_top_up": round(cash_top_up, 2),
            "loan_amount": loan_amount,
            "tenure_years": tenure_years,
            "annual_rate_pct": annual_rate_pct,
        }

    def compare_banks(
        self,
        loan_amount: float,
        tenure_years: int,
        rate_type: str = "fixed",
        is_hdb: bool = False,
    ) -> list[dict]:
        """Compare all banks for the given loan. Returns list sorted by effective cost."""
        results = []
        banks = BANK_RATES.copy()
        if not is_hdb:
            del banks["HDB (CPF Board)"]

        for bank, data in banks.items():
            rates = data.get(rate_type, data.get("fixed", []))
            if not rates:
                continue
            # Use first-year rate for initial comparison
            rate = rates[0]["rate"]
            calc = self.calculate(loan_amount, loan_amount, tenure_years, rate)
            lock_in = rates[0].get("lock_in", 0)
            cashback = data.get("cashback", 0)
            legal = data.get("legal_subsidy", 0)
            net_first_year_cost = calc["monthly_repayment"] * 12 - cashback - legal

            results.append({
                "bank": bank,
                "rate_name": rates[0]["name"],
                "annual_rate_pct": rate,
                "monthly_repayment": calc["monthly_repayment"],
                "total_interest_sgd": calc["total_interest"],
                "lock_in_years": lock_in,
                "cashback_sgd": cashback,
                "legal_subsidy_sgd": legal,
                "net_first_year_cost": round(net_first_year_cost, 0),
                "note": data.get("note", ""),
                "all_rates": rates,
            })

        results.sort(key=lambda x: x["net_first_year_cost"])
        return results

    def affordability_check(
        self,
        gross_monthly_income: float,
        loan_amount: float,
        tenure_years: int,
        annual_rate_pct: float,
        other_monthly_debts: float = 0,
        is_hdb: bool = False,
    ) -> dict:
        """Check TDSR and MSR compliance."""
        calc = self.calculate(loan_amount, loan_amount, tenure_years, annual_rate_pct)
        mortgage = calc["monthly_repayment"]
        total_debt = mortgage + other_monthly_debts
        tdsr = total_debt / gross_monthly_income
        msr = mortgage / gross_monthly_income

        tdsr_ok = tdsr <= TDSR_LIMIT
        msr_ok = (msr <= MSR_LIMIT) if is_hdb else True

        max_loan_tdsr = (gross_monthly_income * TDSR_LIMIT - other_monthly_debts)
        max_loan_msr = gross_monthly_income * MSR_LIMIT if is_hdb else None

        return {
            "monthly_repayment": mortgage,
            "tdsr_pct": round(tdsr * 100, 1),
            "tdsr_limit_pct": TDSR_LIMIT * 100,
            "tdsr_pass": tdsr_ok,
            "msr_pct": round(msr * 100, 1) if is_hdb else None,
            "msr_limit_pct": MSR_LIMIT * 100 if is_hdb else None,
            "msr_pass": msr_ok if is_hdb else None,
            "max_affordable_monthly": round(gross_monthly_income * (MSR_LIMIT if is_hdb else TDSR_LIMIT), 0),
            "verdict": "✅ Affordable" if (tdsr_ok and msr_ok) else "❌ Exceeds limits — reduce loan or extend tenure",
            "tip": self._affordability_tip(tdsr, msr, is_hdb, gross_monthly_income, loan_amount, tenure_years),
        }

    def refi_analysis(
        self,
        current_rate_pct: float,
        current_outstanding: float,
        remaining_tenure_years: int,
        current_bank: str = "existing",
        monthly_cpf: float = 0,
    ) -> dict:
        """
        Analyse refinancing savings vs switching costs.
        Returns best refi option, breakeven period, net savings.
        Triggers MRTA review recommendation.
        """
        current_calc = self.calculate(current_outstanding, current_outstanding, remaining_tenure_years, current_rate_pct)
        current_monthly = current_calc["monthly_repayment"]
        current_total = current_calc["total_paid"]

        comparisons = self.compare_banks(current_outstanding, remaining_tenure_years, "fixed")
        refi_options = []

        for option in comparisons:
            new_monthly = option["monthly_repayment"]
            monthly_saving = current_monthly - new_monthly
            if monthly_saving <= 0:
                continue

            # Switching costs: legal (~SGD 2,500-3,500), valuation (~SGD 500), misc (~SGD 200)
            legal_cost = 3000 - option["legal_subsidy_sgd"]
            valuation_cost = 500
            total_switching_cost = max(0, legal_cost + valuation_cost - option["cashback_sgd"])

            breakeven_months = round(total_switching_cost / monthly_saving, 0) if monthly_saving > 0 else 999
            net_savings_over_tenure = monthly_saving * remaining_tenure_years * 12 - total_switching_cost

            refi_options.append({
                "bank": option["bank"],
                "new_rate_pct": option["annual_rate_pct"],
                "new_monthly": new_monthly,
                "monthly_saving": round(monthly_saving, 2),
                "annual_saving": round(monthly_saving * 12, 0),
                "switching_cost_sgd": total_switching_cost,
                "breakeven_months": int(breakeven_months),
                "net_saving_over_tenure": round(net_savings_over_tenure, 0),
                "worth_refi": breakeven_months <= 18 and net_savings_over_tenure > 5000,
            })

        refi_options.sort(key=lambda x: x["net_saving_over_tenure"], reverse=True)
        best = refi_options[0] if refi_options else None

        result = {
            "current_rate_pct": current_rate_pct,
            "current_monthly": current_monthly,
            "current_total_remaining": current_total,
            "best_refi": best,
            "all_options": refi_options[:3],
            "recommendation": self._refi_recommendation(best, current_rate_pct),
        }

        # MRTA trigger — refinancing = new loan = new MRTA opportunity
        if best and best["worth_refi"]:
            result["insurance_alert"] = {
                "type": "MRTA_review",
                "message": f"When refinancing, review your Mortgage Reducing Term Assurance (MRTA). "
                           f"A new policy on SGD {current_outstanding:,.0f} over {remaining_tenure_years} years "
                           f"typically costs SGD 2,000–5,000 and covers your family if you pass away.",
                "referral_value_sgd": 3500,
                "urgency": "high",
            }

        # LLM narrative only if refi is worth it
        if best and best["worth_refi"]:
            result["narrative"] = self._refi_narrative(result)

        return result

    def cpf_projection(
        self,
        property_price: float,
        loan_amount: float,
        tenure_years: int,
        annual_rate_pct: float,
        monthly_cpf_oa: float,
        age: int = 35,
    ) -> dict:
        """How much CPF OA will be used over the loan tenure."""
        monthly = self.calculate(loan_amount, loan_amount, tenure_years, annual_rate_pct)["monthly_repayment"]
        monthly_cpf_used = min(monthly_cpf_oa, monthly)
        total_cpf_used = monthly_cpf_used * tenure_years * 12
        cpf_limit = property_price * CPF_VALUATION_LIMIT_PCT

        # At 55, CPF OA above Basic Retirement Sum can still be used
        years_to_55 = max(0, 55 - age)
        cpf_pre55 = monthly_cpf_used * min(years_to_55 * 12, tenure_years * 12)

        return {
            "monthly_cpf_used": round(monthly_cpf_used, 0),
            "monthly_cash_needed": round(monthly - monthly_cpf_used, 0),
            "total_cpf_used": round(total_cpf_used, 0),
            "cpf_valuation_limit": round(cpf_limit, 0),
            "within_cpf_limit": total_cpf_used <= cpf_limit,
            "cpf_pre_55": round(cpf_pre55, 0),
            "warning": "CPF usage will exceed valuation limit — cash top-up required for remaining tenure" if total_cpf_used > cpf_limit else None,
        }

    def _affordability_tip(self, tdsr, msr, is_hdb, income, loan, tenure):
        if is_hdb and msr > MSR_LIMIT:
            max_loan_msr = income * MSR_LIMIT
            r = BANK_RATES["HDB (CPF Board)"]["fixed"][0]["rate"] / 100 / 12
            n = tenure * 12
            max_loan = max_loan_msr * ((1 + r) ** n - 1) / (r * (1 + r) ** n)
            return f"MSR exceeded. With SGD {income:,.0f}/mo income, max HDB loan ≈ SGD {max_loan:,.0f}. Consider longer tenure or lower price."
        if tdsr > TDSR_LIMIT:
            return f"TDSR exceeded. Reduce other debts or increase tenure to lower monthly repayment."
        return "Loan is within MAS guidelines."

    def _refi_recommendation(self, best, current_rate):
        if not best:
            return "Current rate appears competitive. No clear refi benefit at this time."
        if best["worth_refi"]:
            return (f"Refinancing to {best['bank']} at {best['new_rate_pct']}% saves "
                    f"SGD {best['annual_saving']:,.0f}/year. Breakeven in {best['breakeven_months']} months. "
                    f"Recommended to act before lock-in expires.")
        return f"Savings exist but switching costs mean breakeven takes {best['breakeven_months']} months. Monitor rates."

    def _refi_narrative(self, result: dict) -> str:
        best = result["best_refi"]
        prompt = f"""In 2 sentences, advise a Singapore homeowner on refinancing their mortgage.
Current rate: {result['current_rate_pct']}%, monthly: SGD {result['current_monthly']:,.0f}.
Best option: {best['bank']} at {best['new_rate_pct']}%, saves SGD {best['annual_saving']:,.0f}/year, breakeven {best['breakeven_months']} months.
Be specific with numbers. No markdown."""
        resp = self._llm(prompt, max_tokens=100, use_cache=True)
        return resp.content.strip()

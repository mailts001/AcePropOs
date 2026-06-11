"""
CPF Housing Grant Calculator — Singapore 2024 rules.
All rule-based (zero LLM cost).

Grant types:
1. Enhanced CPF Housing Grant (EHG) — income-linked, BTO + resale
2. CPF Housing Grant / Family Grant — resale HDB
3. Proximity Housing Grant (PHG) — buy near parents/children
4. Step-Up CPF Housing Grant — 2-room flat upgraders
5. Half-Housing Grant — first-timer + second-timer couples

References:
- HDB: https://www.hdb.gov.sg/residential/buying-a-flat/flat-and-grant-eligibility
- CPF Board guidelines (Feb 2024)
"""

from dataclasses import dataclass


@dataclass
class GrantInput:
    # Buyer profile
    applicant_type: str          # "single" | "couple" | "family"
    first_timer_main: bool       # main applicant first-timer?
    first_timer_partner: bool    # partner first-timer? (if couple/family)
    citizenship: str             # "SC+SC" | "SC+PR" | "SC+foreigner" | "SC_only"
    monthly_income: float        # combined gross monthly household income (SGD)

    # Property
    flat_type: str               # "BTO" | "resale"
    flat_size: str               # "2-room" | "3-room" | "4-room" | "5-room" | "EC"
    near_parents: bool = False   # within 4 km (PHG-live with / near)
    same_town: bool = False      # same town as parents (PHG)


@dataclass
class GrantResult:
    ehg: int = 0                 # Enhanced CPF Housing Grant
    family_grant: int = 0        # CPF Housing Grant / Family Grant
    phg: int = 0                 # Proximity Housing Grant
    step_up: int = 0             # Step-Up Grant
    total: int = 0
    breakdown: list = None
    eligibility_notes: list = None

    def __post_init__(self):
        if self.breakdown is None:
            self.breakdown = []
        if self.eligibility_notes is None:
            self.eligibility_notes = []


# ── EHG income brackets (2024) ───────────────────────────────────────────────
# Couples/families — up to $9,000/month, grant tapers $5k per bracket
EHG_BRACKETS_COUPLE = [
    (1500,  80_000),
    (2000,  75_000),
    (2500,  70_000),
    (3000,  65_000),
    (3500,  60_000),
    (4000,  55_000),
    (4500,  50_000),
    (5000,  45_000),
    (5500,  40_000),
    (6000,  35_000),
    (6500,  30_000),
    (7000,  25_000),
    (7500,  20_000),
    (8000,  15_000),
    (8500,  10_000),
    (9000,   5_000),
]

# Singles — up to $4,500/month
EHG_BRACKETS_SINGLE = [
    (1500,  40_000),
    (2000,  37_500),
    (2500,  35_000),
    (3000,  32_500),
    (3500,  30_000),
    (4000,  27_500),
    (4500,  25_000),
]

# ── Family Grant (resale only) ────────────────────────────────────────────────
# SC+SC couple/family ≤$14k, SC+PR ≤$14k
FAMILY_GRANT = {
    # (flat_size, SC+SC, SC+PR)
    "2-room":  (40_000, 30_000),
    "3-room":  (50_000, 40_000),
    "4-room":  (50_000, 40_000),
    "5-room":  (40_000, 30_000),
    "executive": (40_000, 30_000),
}

# ── PHG ──────────────────────────────────────────────────────────────────────
PHG_LIVE_WITH  = 30_000   # buy to live with parents
PHG_NEAR       = 20_000   # buy within 4 km of parents

# ── Step-Up Grant ─────────────────────────────────────────────────────────────
STEP_UP_GRANT  = 15_000   # 2-room → higher flat, income ≤$7k


def calculate_grants(inp: GrantInput) -> GrantResult:
    result = GrantResult()
    notes = result.eligibility_notes
    breakdown = result.breakdown

    is_single = inp.applicant_type == "single"
    income = inp.monthly_income

    # ── 1. EHG ───────────────────────────────────────────────────────────────
    if inp.first_timer_main:
        if is_single:
            # Singles: only for BTO 5-room and below or resale ≤5-room, income ≤$4,500
            if income <= 4500:
                for cap, grant in EHG_BRACKETS_SINGLE:
                    if income <= cap:
                        result.ehg = grant
                        breakdown.append(f"Enhanced CPF Housing Grant (EHG): **${grant:,}**")
                        break
            else:
                notes.append("EHG: Income >$4,500 — singles not eligible.")
        else:
            # Couples / family: income ≤$9,000
            if income <= 9000 and inp.first_timer_main and inp.first_timer_partner:
                for cap, grant in EHG_BRACKETS_COUPLE:
                    if income <= cap:
                        result.ehg = grant
                        breakdown.append(f"Enhanced CPF Housing Grant (EHG): **${grant:,}**")
                        break
            elif income <= 9000 and (inp.first_timer_main != inp.first_timer_partner):
                # Half-EHG for first-timer + second-timer
                for cap, grant in EHG_BRACKETS_COUPLE:
                    if income <= cap:
                        half = grant // 2
                        result.ehg = half
                        breakdown.append(f"Enhanced CPF Housing Grant – Half (EHG): **${half:,}** (first-timer + second-timer)")
                        break
            else:
                notes.append("EHG: Income >$9,000 — not eligible.")
    else:
        notes.append("EHG: Only for first-timer applicants.")

    # ── 2. Family Grant (resale only) ────────────────────────────────────────
    if inp.flat_type == "resale" and not is_single and income <= 14_000:
        size_key = inp.flat_size.lower().replace("-room", "-room").replace("room ", "room")
        if size_key not in FAMILY_GRANT:
            size_key = "4-room"  # default
        sc_sc, sc_pr = FAMILY_GRANT[size_key]

        if inp.first_timer_main and inp.first_timer_partner:
            grant = sc_sc if inp.citizenship == "SC+SC" else sc_pr if inp.citizenship == "SC+PR" else 0
            result.family_grant = grant
            breakdown.append(f"CPF Housing Grant (Family): **${grant:,}**")
        elif inp.first_timer_main != inp.first_timer_partner:
            half = (sc_sc if inp.citizenship == "SC+SC" else sc_pr) // 2
            result.family_grant = half
            breakdown.append(f"CPF Housing Grant – Half (Family): **${half:,}** (first-timer + second-timer)")
        else:
            notes.append("Family Grant: Both applicants are second-timers — not eligible.")
    elif inp.flat_type == "resale" and income > 14_000:
        notes.append("Family Grant: Income >$14,000 — not eligible.")

    # ── 3. Proximity Housing Grant ───────────────────────────────────────────
    if inp.flat_type == "resale" and not is_single:
        if inp.near_parents and inp.same_town:
            result.phg = PHG_LIVE_WITH
            breakdown.append(f"Proximity Housing Grant (live with parents): **${PHG_LIVE_WITH:,}**")
        elif inp.near_parents:
            result.phg = PHG_NEAR
            breakdown.append(f"Proximity Housing Grant (within 4 km of parents): **${PHG_NEAR:,}**")
    elif inp.flat_type == "BTO" and inp.near_parents:
        notes.append("PHG is for resale flats only.")

    # ── 4. Step-Up Grant ─────────────────────────────────────────────────────
    if (inp.flat_type == "resale"
            and not inp.first_timer_main
            and inp.flat_size not in ("2-room",)
            and income <= 7000):
        result.step_up = STEP_UP_GRANT
        breakdown.append(f"Step-Up CPF Housing Grant: **${STEP_UP_GRANT:,}**")

    # ── Total ─────────────────────────────────────────────────────────────────
    result.total = result.ehg + result.family_grant + result.phg + result.step_up

    if result.total == 0 and not breakdown:
        notes.append("No grants applicable based on the inputs provided.")
    else:
        breakdown.append(f"─────────────────────────────")
        breakdown.append(f"**Total Grants: ${result.total:,}**")

    return result


# ── Convenience wrapper returning dict ────────────────────────────────────────
def calculate_grants_dict(
    applicant_type: str,
    first_timer_main: bool,
    first_timer_partner: bool,
    citizenship: str,
    monthly_income: float,
    flat_type: str,
    flat_size: str,
    near_parents: bool = False,
    same_town: bool = False,
) -> dict:
    inp = GrantInput(
        applicant_type=applicant_type,
        first_timer_main=first_timer_main,
        first_timer_partner=first_timer_partner,
        citizenship=citizenship,
        monthly_income=monthly_income,
        flat_type=flat_type,
        flat_size=flat_size,
        near_parents=near_parents,
        same_town=same_town,
    )
    r = calculate_grants(inp)
    return {
        "ehg": r.ehg,
        "family_grant": r.family_grant,
        "phg": r.phg,
        "step_up": r.step_up,
        "total": r.total,
        "breakdown": r.breakdown,
        "notes": r.eligibility_notes,
    }

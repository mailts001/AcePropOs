"""
PDF Report Generator — PropOS property valuation and mortgage summary reports.
Uses fpdf2 (pure Python, no system deps). Install: pip install fpdf2
"""

from __future__ import annotations
from datetime import date
from pathlib import Path
import io

try:
    from fpdf import FPDF
    _FPDF_AVAILABLE = True
except ImportError:
    _FPDF_AVAILABLE = False


LOGO_TEXT = "PropOS"
BRAND_COLOR = (13, 27, 42)       # dark navy
GOLD_COLOR  = (201, 168, 76)     # gold
LIGHT_BG    = (245, 247, 250)
SEPARATOR   = (220, 220, 220)


class PropReport(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self.set_auto_page_break(auto=True, margin=18)
        self.add_page()

    def header(self):
        self.set_fill_color(*BRAND_COLOR)
        self.rect(0, 0, 210, 22, "F")
        self.set_text_color(201, 168, 76)
        self.set_font("Helvetica", "B", 13)
        self.set_xy(8, 5)
        self.cell(40, 12, LOGO_TEXT, ln=0)
        self.set_text_color(200, 216, 230)
        self.set_font("Helvetica", "", 9)
        self.set_xy(50, 7)
        self.cell(100, 8, "Singapore Property Intelligence", ln=0)
        self.set_text_color(160, 180, 200)
        self.set_xy(140, 7)
        self.cell(60, 8, f"Generated {date.today().strftime('%d %b %Y')}", align="R", ln=0)
        self.ln(20)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*SEPARATOR)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, "Not financial advice. Data from HDB/data.gov.sg and URA. Verify all figures independently.", align="C")

    def section_title(self, text: str):
        self.ln(4)
        self.set_fill_color(*GOLD_COLOR)
        self.rect(10, self.get_y(), 3, 7, "F")
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*BRAND_COLOR)
        self.set_xy(16, self.get_y())
        self.cell(0, 7, text, ln=True)
        self.ln(2)

    def kv_row(self, label: str, value: str, shade: bool = False):
        if shade:
            self.set_fill_color(*LIGHT_BG)
            self.rect(10, self.get_y(), 190, 7, "F")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(80, 80, 80)
        self.set_x(12)
        self.cell(85, 7, label, ln=False)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*BRAND_COLOR)
        self.cell(0, 7, str(value), ln=True)

    def note_box(self, text: str):
        self.ln(2)
        self.set_fill_color(255, 251, 235)
        self.set_draw_color(*GOLD_COLOR)
        self.set_line_width(0.4)
        x, y = self.get_x(), self.get_y()
        self.rect(10, y, 190, 14, "FD")
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 80, 0)
        self.set_xy(14, y + 2)
        self.multi_cell(182, 5, text)
        self.ln(4)
        self.set_line_width(0.2)


def generate_valuation_report(
    property_address: str,
    property_type: str,
    area_sqft: float,
    estimated_value: float,
    median_price: float,
    transactions_used: int,
    asking_price: float = 0,
    vs_median_pct: float = 0,
    verdict: str = "",
    ai_analysis: str = "",
    rental_monthly: float = 0,
    gross_yield_pct: float = 0,
    district: int = 0,
) -> bytes:
    """Generate a valuation report PDF. Returns bytes."""
    if not _FPDF_AVAILABLE:
        raise ImportError("fpdf2 not installed. Run: pip install fpdf2")

    pdf = PropReport("Property Valuation Report")

    # Title block
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*BRAND_COLOR)
    pdf.cell(0, 10, "Property Valuation Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, property_address or f"District {district} — {property_type}", ln=True, align="C")
    pdf.ln(6)

    # Valuation summary
    pdf.section_title("Valuation Summary")
    pdf.kv_row("Estimated Market Value", f"SGD {estimated_value:,.0f}", shade=False)
    pdf.kv_row("District / Town Median", f"SGD {median_price:,.0f}", shade=True)
    pdf.kv_row("Floor Area", f"{area_sqft:,.0f} sqft", shade=False)
    if estimated_value > 0 and area_sqft > 0:
        pdf.kv_row("Price Per Square Foot", f"SGD {estimated_value / area_sqft:,.0f} PSF", shade=True)
    pdf.kv_row("Transactions Analysed", str(transactions_used), shade=False)

    if asking_price > 0:
        pdf.ln(3)
        pdf.section_title("Deal Assessment")
        pdf.kv_row("Asking Price", f"SGD {asking_price:,.0f}", shade=False)
        pdf.kv_row("vs Market Median", f"{vs_median_pct:+.1f}%  →  {verdict}", shade=True)
        if asking_price > estimated_value:
            pdf.note_box(f"Asking price is {((asking_price/estimated_value)-1)*100:.1f}% above estimated value. "
                         "Negotiate or seek independent valuation before committing.")
        elif asking_price < estimated_value * 0.95:
            pdf.note_box(f"Asking price is {((1 - asking_price/estimated_value))*100:.1f}% below estimated value — "
                         "potential value buy. Verify condition and any outstanding issues.")

    if rental_monthly > 0:
        pdf.ln(3)
        pdf.section_title("Rental & Yield Snapshot")
        pdf.kv_row("Estimated Monthly Rent", f"SGD {rental_monthly:,.0f}", shade=False)
        pdf.kv_row("Est. Annual Rental Income", f"SGD {rental_monthly * 12:,.0f}", shade=True)
        if gross_yield_pct > 0:
            pdf.kv_row("Gross Rental Yield", f"{gross_yield_pct:.2f}%", shade=False)
            pdf.kv_row("Est. Net Yield (after costs)", f"{max(0, gross_yield_pct - 1.5):.2f}%", shade=True)

    if ai_analysis:
        pdf.ln(3)
        pdf.section_title("AI Analysis")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(50, 50, 50)
        pdf.set_x(12)
        pdf.multi_cell(186, 5, ai_analysis)

    # Insurance nudge
    pdf.ln(3)
    pdf.section_title("Protect Your Investment")
    pdf.note_box(
        "Consider Mortgage Reducing Term Assurance (MRTA) or Mortgage Level Term Assurance (MLTA) "
        "to protect your family if you are unable to service the loan. "
        "Speak to a licensed financial adviser. Contact PropOS for an insurance referral."
    )

    pdf.section_title("Disclaimer")
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.set_x(12)
    pdf.multi_cell(186, 4.5,
        "This report is for informational purposes only and does not constitute financial, legal, or investment advice. "
        "Estimated values are derived from recent transaction data and statistical models — actual sale prices may differ. "
        "Always engage a licensed valuer and conveyancing lawyer before transacting property."
    )

    return bytes(pdf.output())


def generate_mortgage_report(
    property_price: float,
    loan_amount: float,
    tenure_years: int,
    annual_rate_pct: float,
    monthly_repayment: float,
    bank_name: str = "",
    total_interest: float = 0,
    tdsr_pct: float = 0,
    msr_pct: float = 0,
    gross_monthly_income: float = 0,
    refi_saving: float = 0,
) -> bytes:
    """Generate a mortgage summary PDF. Returns bytes."""
    if not _FPDF_AVAILABLE:
        raise ImportError("fpdf2 not installed. Run: pip install fpdf2")

    pdf = PropReport("Mortgage Summary Report")

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*BRAND_COLOR)
    pdf.cell(0, 10, "Mortgage Summary Report", ln=True, align="C")
    pdf.ln(6)

    pdf.section_title("Loan Details")
    pdf.kv_row("Property Price", f"SGD {property_price:,.0f}", shade=False)
    pdf.kv_row("Loan Amount", f"SGD {loan_amount:,.0f}", shade=True)
    pdf.kv_row("Down Payment", f"SGD {property_price - loan_amount:,.0f}  ({(1 - loan_amount/property_price)*100:.0f}%)", shade=False)
    pdf.kv_row("Loan Tenure", f"{tenure_years} years", shade=True)
    pdf.kv_row("Interest Rate", f"{annual_rate_pct:.2f}% p.a.", shade=False)
    if bank_name:
        pdf.kv_row("Bank / Package", bank_name, shade=True)

    pdf.ln(3)
    pdf.section_title("Repayment Summary")
    pdf.kv_row("Monthly Repayment", f"SGD {monthly_repayment:,.0f}", shade=False)
    pdf.kv_row("Total Amount Repayable", f"SGD {loan_amount + total_interest:,.0f}", shade=True)
    pdf.kv_row("Total Interest Paid", f"SGD {total_interest:,.0f}", shade=False)

    if gross_monthly_income > 0:
        pdf.ln(3)
        pdf.section_title("Affordability Check")
        pdf.kv_row("Gross Monthly Income", f"SGD {gross_monthly_income:,.0f}", shade=False)
        if tdsr_pct > 0:
            status = "✓ Pass" if tdsr_pct <= 55 else "✗ Fail"
            pdf.kv_row("TDSR", f"{tdsr_pct:.1f}%  (limit 55%)  {status}", shade=True)
        if msr_pct > 0:
            status = "✓ Pass" if msr_pct <= 30 else "✗ Fail"
            pdf.kv_row("MSR (HDB)", f"{msr_pct:.1f}%  (limit 30%)  {status}", shade=False)

    if refi_saving > 0:
        pdf.ln(3)
        pdf.note_box(f"Refinancing opportunity: estimated savings of SGD {refi_saving:,.0f} over remaining tenure. "
                     "Consider reviewing your mortgage package annually.")

    # Insurance nudge
    pdf.ln(3)
    pdf.section_title("Mortgage Protection")
    pdf.note_box(
        f"For a loan of SGD {loan_amount:,.0f}, an MRTA or MLTA policy can protect your family "
        "from SGD 2,000–5,000 in annual premiums. Contact PropOS for a no-obligation insurance referral."
    )

    return bytes(pdf.output())

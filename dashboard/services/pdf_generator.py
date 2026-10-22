from io import BytesIO
from datetime import date
from decimal import Decimal
from fpdf import FPDF


class APWRSPDFReport(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, "APWRS — Drought Early Warning Report", align="C")
            self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def _pdf_str(s):
    if not s:
        return ''
    try:
        s.encode('latin-1')
        return s
    except UnicodeEncodeError:
        import unicodedata
        return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')


def generate_drought_pdf(region_name, year_label, risk_scores, drivers, explanation, snapshots):
    """Generate a PDF drought analysis report buffer."""
    pdf = APWRSPDFReport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    w = pdf.w - pdf.l_margin - pdf.r_margin
    today_str = date.today().isoformat()

    # Title
    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(w, 12, 'Drought Analysis Report', border=0, align='C')
    pdf.ln(14)

    # 1. Summary
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '1. Report Summary', border=0, fill=True)
    pdf.ln(10)

    summary_rows = [
        ('Region', region_name),
        ('Year', year_label),
        ('Export Date', today_str),
        ('Overall Risk', f"{risk_scores.get('today', '-')}/100"),
        ('7-Day Forecast', f"{risk_scores.get('day_7', '-')}/100"),
        ('30-Day Forecast', f"{risk_scores.get('day_30', '-')}/100"),
    ]
    for label, value in summary_rows:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(50, 7, label, border=0)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(w - 50, 7, _pdf_str(str(value)), border=0)
        pdf.ln(7)

    pdf.ln(4)

    # 2. Key Drought Drivers
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '2. Key Drought Drivers', border=0, fill=True)
    pdf.ln(10)

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(200, 215, 240)
    col_w = [w * 0.45, w * 0.25, w * 0.30]
    headers = ['Driver', 'Contribution (%)', 'Score (0-100)']
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, fill=True, align='C')
    pdf.ln()

    driver_keys = [
        ('rainfall_deficit', 'Rainfall Deficit'),
        ('high_temperature', 'High Temperature'),
        ('soil_moisture_decline', 'Soil Moisture Decline'),
        ('vegetation_stress', 'Vegetation Stress'),
        ('high_evapotranspiration', 'High Evapotranspiration'),
    ]
    abs_drivers = drivers.get('absolute', {}) if isinstance(drivers, dict) else {}
    pdf.set_font('Helvetica', '', 9)
    for i, (key, label) in enumerate(driver_keys):
        contrib = drivers.get(key, '-') if isinstance(drivers, dict) else '-'
        abs_val = abs_drivers.get(key, '-') if isinstance(abs_drivers, dict) else '-'
        fill = (i % 2 == 0)
        if fill:
            pdf.set_fill_color(245, 248, 252)
        pdf.cell(col_w[0], 6, f'  {label}', border=1, fill=fill)
        pdf.cell(col_w[1], 6, str(contrib), border=1, fill=fill, align='C')
        pdf.cell(col_w[2], 6, str(abs_val), border=1, fill=fill, align='C')
        pdf.ln()

    pdf.ln(6)

    # 3. Drought Insight
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '3. Drought Insight', border=0, fill=True)
    pdf.ln(10)

    pdf.set_font('Helvetica', '', 10)
    pdf.set_fill_color(252, 252, 252)
    pdf.multi_cell(w, 6, _pdf_str(explanation) if explanation else 'No insight available.', border=0, fill=True)
    pdf.ln(6)

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer

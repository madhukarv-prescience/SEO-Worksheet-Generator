"""
Renders an approved worksheet to a branded, printable HTML page, and
optionally to a real PDF file.

Why HTML rather than drawing a PDF directly: the page must be reviewable
in the browser and printable to PDF from the same source, and HTML/CSS
gives far better typographic control over question layout than drawing
boxes by hand.

Why headless Chrome for the PDF rather than weasyprint: Chrome runs
JavaScript and honours modern CSS, so what you see in the review screen is
exactly what lands in the PDF. Converters that skip JS silently drop
things.
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from jinja2 import Template

from app.config import DIAGRAM_DIR, EXPORT_DIR

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _b64(path: Path) -> str:
    try:
        return base64.b64encode(path.read_bytes()).decode()
    except Exception:
        return ""


TEMPLATE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --orange:#f15d22; --navy:#212638; --yellow:#fab82b;
    --blue:#5e91ff; --grey:#45474a; --paper:#ffffff;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; background:#eceef2; color:var(--navy);
    font-family:'Poppins',-apple-system,BlinkMacSystemFont,sans-serif;
  }
  .sheet{
    width:210mm; min-height:297mm; margin:12mm auto; padding:14mm 16mm 18mm;
    background:var(--paper); position:relative;
    box-shadow:0 2px 18px rgba(33,38,56,.14);
  }
  .brandbar{
    display:flex; align-items:center; justify-content:space-between;
    border-bottom:3px solid var(--orange); padding-bottom:8mm; margin-bottom:8mm;
  }
  .brandbar img{height:13mm;}
  .meta{text-align:right; font-size:9pt; color:var(--grey); line-height:1.5;}
  .meta b{color:var(--navy);}
  h1{font-size:19pt; margin:0 0 2mm; font-weight:700; letter-spacing:-.2px;}
  .skill{font-size:10.5pt; color:var(--grey); margin:0 0 7mm;}
  .namerow{
    display:flex; gap:8mm; margin-bottom:9mm; font-size:10pt; color:var(--grey);
  }
  .namerow span{flex:1; border-bottom:1.4px dotted #b9bdc7; padding-bottom:2.5mm;}
  .section{
    font-size:9.5pt; font-weight:600; letter-spacing:.9px; text-transform:uppercase;
    color:var(--orange); margin:6mm 0 3mm; padding-bottom:1.5mm;
    border-bottom:1.2px solid #f3d9cc;
    /* Without this a heading strands itself at the foot of a page while
       its questions start the next one. */
    page-break-after:avoid; break-after:avoid;
  }
  .q{display:flex; gap:4mm; margin-bottom:5mm; page-break-inside:avoid; break-inside:avoid;}
  .qnum{
    flex:0 0 8mm; height:8mm; border-radius:50%; background:var(--navy);
    color:#fff; font-size:10.5pt; font-weight:600;
    display:flex; align-items:center; justify-content:center;
  }
  .qbody{flex:1;}
  .qtext{font-size:11.5pt; line-height:1.6; margin:0 0 3mm;}
  .qfig{margin:2.5mm 0 3mm;}
  .qfig img{max-width:112mm; max-height:42mm; display:block;}
  .answerbox{
    border:1.4px solid #c9ccd3; border-radius:3px; height:10mm;
    max-width:62mm; background:#fafbfc;
  }
  .closing{
    margin-top:8mm; padding:5mm 7mm; border-radius:5px;
    background:#fff6e8; border-left:4px solid var(--yellow); font-size:11pt;
    line-height:1.6; page-break-inside:avoid;
  }
  .closing b{display:block; margin-bottom:2mm; color:var(--orange);
             font-size:9.5pt; letter-spacing:.8px; text-transform:uppercase;}
  .foot{
    position:absolute; left:16mm; right:16mm; bottom:9mm;
    display:flex; align-items:center; justify-content:space-between;
    border-top:1.2px solid #e4e6ec; padding-top:3mm;
    font-size:8.5pt; color:var(--grey); page-break-before:avoid;
  }
  .foot img{height:7.5mm; opacity:.9;}
  .answerkey{page-break-before:always;}
  .answerkey .section{color:var(--blue); border-bottom-color:#d5e2ff;}
  .akrow{
    display:flex; gap:4mm; padding:2.2mm 0; border-bottom:1px dotted #dfe2e8;
    font-size:10.5pt;
  }
  .akrow .n{flex:0 0 9mm; font-weight:600; color:var(--blue);}

  .pdfbar{
    position:fixed; right:22px; bottom:22px; background:var(--orange);
    color:#fff; border:none; border-radius:40px; padding:13px 24px;
    font-family:inherit; font-size:14px; font-weight:600; cursor:pointer;
    box-shadow:0 5px 18px rgba(241,93,34,.4);
  }
  @media print{
    body{background:#fff;}
    .sheet{margin:0; box-shadow:none; width:auto; min-height:auto;}
    .pdfbar{display:none !important;}
    @page{size:A4; margin:0;}
  }
</style>
</head>
<body>
<div class="sheet">
  <div class="brandbar">
    {% if logo %}<img src="data:image/png;base64,{{ logo }}" alt="Bhanzu">{% endif %}
    <div class="meta"><b>{{ grade_label }}</b><br>{{ difficulty_label }} level</div>
  </div>

  <h1>{{ title }}</h1>
  {% if skill %}<p class="skill">{{ skill }}</p>{% endif %}

  <div class="namerow"><span>Name</span><span>Class</span><span>Date</span></div>

  {% for group in grouped %}
    <div class="section">{{ group.section }}</div>
    {% for q in group.questions %}
      <div class="q">
        <div class="qnum">{{ q.number }}</div>
        <div class="qbody">
          <p class="qtext">{{ q.text }}</p>
          {% if q.diagram_b64 %}
            <div class="qfig"><img src="data:image/png;base64,{{ q.diagram_b64 }}" alt=""></div>
          {% endif %}
          <div class="answerbox"></div>
        </div>
      </div>
    {% endfor %}
  {% endfor %}

  {% if closing_note %}
    <div class="closing"><b>Before you go</b>{{ closing_note }}</div>
  {% endif %}

  <div class="foot">
    <span>{{ title }}</span>
    {% if logo %}<img src="data:image/png;base64,{{ logo }}" alt="">{% endif %}
  </div>
</div>

<div class="sheet answerkey">
  <div class="brandbar">
    {% if logo %}<img src="data:image/png;base64,{{ logo }}" alt="Bhanzu">{% endif %}
    <div class="meta"><b>Answer key</b><br>{{ grade_label }}</div>
  </div>
  <h1>{{ title }}</h1>
  <div class="section">Answers</div>
  {% for q in questions %}
    <div class="akrow"><span class="n">{{ q.number }}</span><span>{{ q.answer or '—' }}</span></div>
  {% endfor %}
  <div class="foot">
    <span>Answer key</span>
    {% if logo %}<img src="data:image/png;base64,{{ logo }}" alt="">{% endif %}
  </div>
</div>

<button class="pdfbar" onclick="window.print()">Download PDF</button>
</body>
</html>""")

SECTION_ORDER = ["Warm up", "Practice", "Stretch", "Reflect"]


def render_export(worksheet: dict, grade_label: str, difficulty_label: str) -> Path:
    questions = worksheet["questions"]
    for q in questions:
        q["diagram_b64"] = (_b64(DIAGRAM_DIR / f"{q['diagram_id']}.png")
                             if q.get("diagram_id") else "")

    grouped, seen = [], {}
    for q in questions:
        sec = q.get("section") or "Practice"
        if sec not in seen:
            seen[sec] = {"section": sec, "questions": []}
            grouped.append(seen[sec])
        seen[sec]["questions"].append(q)
    grouped.sort(key=lambda g: SECTION_ORDER.index(g["section"])
                  if g["section"] in SECTION_ORDER else 99)

    html = TEMPLATE.render(
        title=worksheet["title"],
        skill=worksheet.get("skill") or "",
        grade_label=grade_label,
        difficulty_label=difficulty_label,
        grouped=grouped,
        questions=questions,
        closing_note=worksheet.get("closing_note") or "",
        logo=_b64(STATIC_DIR / "bhanzu_logo.png"),
    )
    out = EXPORT_DIR / f"{worksheet['id']}.html"
    out.write_text(html, encoding="utf-8")
    return out


def render_pdf(html_path: Path) -> Path | None:
    """Print the export page to a real PDF with headless Chrome.

    Returns None if Chrome isn't present — the HTML export still works and
    the reviewer can print from their browser, so this is a degradation,
    not a failure.
    """
    if not Path(CHROME).exists():
        return None
    pdf_path = html_path.with_suffix(".pdf")
    try:
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=10000", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf_path}", html_path.as_uri()],
            check=True, capture_output=True, timeout=120,
        )
        return pdf_path if pdf_path.exists() else None
    except Exception:
        return None

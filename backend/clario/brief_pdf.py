"""The clinician brief as a one-page PDF, rendered on the clinic server with fpdf2.

Two states: the AI draft (watermarked "AI draft, not reviewed") and the signed brief (clinician name, date and
"Reviewed and signed by"). Both carry the provenance: which model drafted it, where it ran (AMD Token Factory), and
whether the model input was sent pseudonymised. The patient copy is the third state: "Clario" over "Summary from
your visit", the patient's pseudonym and the date, the clinician who signed, plain-words sections and the reminder that
Clario does not diagnose (no model provenance: the patient reads what the clinician reviewed). The font is DejaVu Sans (shipped in data/fonts), so Italian and any
other Latin text prints as written. The body shrinks until the brief fits one A4 page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from fpdf import FPDF

FONTS = Path(__file__).parent / "data" / "fonts"
TOKEN_FACTORY = "amd-token-factory"
OFFLINE = "offline-fixtures"
SIZES = (10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5)
PATIENT_SIZES = (12.0, 11.5, 11.0, 10.5) + SIZES  # the patient copy starts larger: it is read at home, not at a desk

WORDS = {
    "en": {"title": "Clinician brief: {alias}", "period": "Period {a} to {b}", "focus": "Focus: {sp}",
           "draft": "AI draft, not reviewed", "draft_banner": "AI DRAFT, NOT REVIEWED. Edit and sign before it is used.",
           "signed": "Reviewed and signed by {name}, {date}", "drafted_by": "Drafted by {model}.",
           "pseudo": "Model input sent pseudonymised (names, contacts, ids and dates replaced).",
           "plain_remote": "Model input sent without pseudonymisation.",
           "local": "Model input stayed on this server.",
           "offline": "Offline demo: drafted from fixtures, no model call.",
           "footer": "Prepared with Clario. Patterns are not a diagnosis.",
           "tf": "{model} on AMD Token Factory", "demo_model": "offline demo fixtures",
           "p_title": "Summary from your visit", "p_signed": "Reviewed and signed by {name}",
           "p_footer": ["Clario organises information; it does not diagnose or give treatment advice.",
                        "Ask your doctor about anything here."],
           "p_empty": "Nothing to show yet."},
    "it": {"title": "Riepilogo clinico: {alias}", "period": "Periodo dal {a} al {b}", "focus": "Specialità: {sp}",
           "draft": "Bozza IA, non rivista", "draft_banner": "BOZZA IA, NON RIVISTA. Modificala e firmala prima di usarla.",
           "signed": "Rivisto e firmato da {name}, {date}", "drafted_by": "Bozza scritta da {model}.",
           "pseudo": "Dati inviati al modello pseudonimizzati (nomi, contatti, codici e date sostituiti).",
           "plain_remote": "Dati inviati al modello senza pseudonimizzazione.",
           "local": "I dati per il modello sono rimasti su questo server.",
           "offline": "Demo offline: bozza dalle fixture, nessuna chiamata al modello.",
           "footer": "Preparato con Clario. Gli schemi non sono una diagnosi.",
           "tf": "{model} su AMD Token Factory", "demo_model": "fixture demo offline",
           "p_title": "Riepilogo della tua visita", "p_signed": "Rivisto e firmato da {name}",
           "p_footer": ["Clario organizza le informazioni; non fa diagnosi e non dà consigli sulle cure.",
                        "Chiedi al tuo medico qualsiasi cosa trovi qui."],
           "p_empty": "Ancora niente da mostrare."},
}


def model_name(model: str | None) -> str:
    """"Gemma-4-31B-IT" -> "Gemma 4 31B" (as the clinic UI writes it); any other id as is."""
    m = re.search(r"gemma[-_ ]?4[-_ :]?(e?\d+b)", model or "", re.I)
    return f"Gemma 4 {m.group(1).upper()}" if m else (model or "")


def provenance(backend: str | None, model: str | None, pseudonymized: bool | None, remote: bool | None, lang: str) -> list[str]:
    w = WORDS[lang]
    if backend == OFFLINE:
        return [w["drafted_by"].format(model=w["demo_model"]), w["offline"]]
    who = w["tf"].format(model=model_name(model) or "Gemma 4") if backend == TOKEN_FACTORY else \
        " · ".join(x for x in (model_name(model), backend) if x)
    privacy = w["pseudo"] if pseudonymized else (w["plain_remote"] if remote else w["local"])
    return [w["drafted_by"].format(model=who or "?"), privacy]


@dataclass
class PdfBrief:
    lang: str
    title: str
    subtitle: str
    sections: list[tuple[str, list[str]]]
    provenance: list[str]
    signed: str | None = None  # "Reviewed and signed by ..." line; None = AI draft
    notes: list[str] = field(default_factory=list)
    kicker: str | None = None  # small line over the title ("Clario" on the patient copy)
    footer: list[str] | None = None  # replaces provenance + the clinician footer (the patient copy)
    sizes: tuple[float, ...] = SIZES


class _Doc(FPDF):
    def __init__(self, b: PdfBrief):
        super().__init__(format="A4", unit="mm")
        self.b = b
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_margins(16, 14, 16)
        self.footer_lines = b.footer if b.footer is not None else b.provenance + [WORDS[b.lang]["footer"]]
        self.set_auto_page_break(True, margin=10 + 3.6 * len(self.footer_lines))
        self.set_title(b.title)
        self.set_creator("Clario")

    def header(self) -> None:
        if self.b.signed is not None:
            return
        with self.local_context(fill_opacity=0.14, text_color=(190, 20, 20)):  # under the text, every page
            self.set_font("DejaVu", "B", 46)
            with self.rotation(52, x=self.w / 2, y=self.h / 2):
                text = WORDS[self.b.lang]["draft"]
                self.text(self.w / 2 - self.get_string_width(text) / 2, self.h / 2 + 6, text)
        self.set_y(self.t_margin)

    def footer(self) -> None:
        self.set_y(-(8 + 3.6 * len(self.footer_lines)))
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.2)
        self.set_font("DejaVu", "", 7.5)
        self.set_text_color(90, 90, 90)
        for line in self.footer_lines:
            self.cell(0, 3.6, line, new_x="LMARGIN", new_y="NEXT")


def _render(b: PdfBrief, size: float) -> FPDF:
    pdf = _Doc(b)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    if b.kicker:
        pdf.set_text_color(31, 92, 153)
        pdf.set_font("DejaVu", "B", 11)
        pdf.cell(0, 5.5, b.kicker, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("DejaVu", "B", 15)
    pdf.cell(0, 7.5, b.title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 4.8, b.subtitle, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    if b.signed is None:
        pdf.set_fill_color(253, 236, 234)
        pdf.set_text_color(160, 20, 20)
        pdf.set_font("DejaVu", "B", 9)
        pdf.cell(0, 6.5, "  " + WORDS[b.lang]["draft_banner"], fill=True, new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_fill_color(232, 244, 236)
        pdf.set_text_color(20, 90, 50)
        pdf.set_font("DejaVu", "B", 9.5)
        pdf.cell(0, 6.5, "  " + b.signed, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    lh = size * 0.47
    for title, lines in b.sections:
        if not lines:
            continue
        pdf.ln(size * 0.18)
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("DejaVu", "B", size + 1)
        pdf.cell(0, lh + 1, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", size)
        for line in lines:
            pdf.set_x(pdf.l_margin + 1.5)
            pdf.cell(3.5, lh, "•")
            pdf.multi_cell(width - 5, lh, line, new_x="LMARGIN", new_y="NEXT")
    for note in b.notes:
        pdf.ln(1)
        pdf.set_font("DejaVu", "", size - 1)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(0, lh, note, new_x="LMARGIN", new_y="NEXT")
    return pdf


def render(b: PdfBrief) -> bytes:
    """The brief as PDF bytes: the largest body size that fits one page (the smallest size if nothing does)."""
    pdf = None
    for size in b.sizes:
        pdf = _render(b, size)
        if pdf.pages_count == 1:
            break
    return bytes(pdf.output())


def page_count(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))

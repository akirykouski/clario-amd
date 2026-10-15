"""Pseudonymization before text leaves the device, and a tamper-evident log of every model call.

Three parts:
  * `pseudonymize(text)`: rule-based removal of direct identifiers. Returns the redacted text and a list of
    replacements (type and positions only, never the original value).
  * `PrivacyLLM`: wraps any LLM. In patient mode with a remote backend it redacts user messages before the call,
    then maps returned quotes back to the ORIGINAL text so grounding still works. Every call is logged.
  * `CallLog`: hash chain of calls. hash = sha256(prev_hash + payload_sha256 + ts + backend + model + purpose),
    so changing, removing or reordering a record is detectable with `verify()`.

Medical content (terms, doses, lab values, scores) is deliberately left alone: the cloud model needs it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .llm import extract_json
from .vault import Locked, Vault

GENESIS = "0" * 64
PURPOSES = ("extract", "rationale", "brief", "next_question", "document", "other")
PLACEHOLDER = {"email": "[EMAIL]", "iban": "[IBAN]", "codice_fiscale": "[CODICE_FISCALE]", "address": "[ADDRESS]",
               "date": "[DATE]", "phone": "[PHONE]", "name": "[NAME]", "health_id": "[HEALTH_ID]", "record": "[RECORD_NO]"}
# The kind a replacement reports (models.PrivacyReplacement / the Cloud-saw panel know seven kinds). The tessera
# sanitaria and hospital record numbers are national and hospital identifiers and share the codice_fiscale kind.
KIND = {"health_id": "codice_fiscale", "record": "codice_fiscale"}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


# ====================================================================== pseudonymize
def _ci(word: str) -> str:
    return "".join(f"[{c.upper()}{c.lower()}]" if c.isalpha() else re.escape(c) for c in word)


_MONTHS_FULL = ["january", "february", "march", "april", "june", "july", "august", "september", "october",
                "november", "december", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
                "Gen", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Dic"]
_MONTH = "(?:" + "|".join([_ci(m) for m in _MONTHS_FULL] + ["May"] + [m + r"\.?" for m in _MONTHS_ABBR]) + ")"
_DAY = r"\d{1,2}(?:st|nd|rd|th|°)?"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# "name [at] host.it" and "name (at) host.it": written that way to dodge scrapers, still an address
_EMAIL_OBFUSCATED = re.compile(r"[A-Za-z0-9._%+-]+\s*[\[(]\s*(?i:at)\s*[\])]\s*[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?:\s?[A-Za-z0-9]{4}){3,7}(?:\s?[A-Za-z0-9]{1,4})?\b")
_CF = re.compile(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b")
_CF_SPACED = re.compile(r"\b[A-Za-z]{3}[ .]?[A-Za-z]{3}[ .]?\d{2}[A-Za-z]\d{2}[ .]?[A-Za-z]\d{3}[A-Za-z]\b")
# Tessera sanitaria: 20 digits that start with 80380, written solid or in groups.
_TS = re.compile(r"(?<!\d)80380(?:[ \t-]?\d){15}(?!\d)")
_TS_LABELLED = re.compile(
    r"\b(?i:tessera\s+sanitaria|health\s+card|codice\s+tessera|tessera|T\.?E\.?A\.?M\.?|TS)(?:[ \t]+(?i:n\.?|n°|nr\.?|no\.?|numero|number))?"
    r"[ \t]*[:#-]?[ \t]*(?P<v>\d(?:[\d \t-]){8,26}\d)(?!\d)")
# Hospital and record numbers: the value after a label such as MRN, "cartella clinica n.", "patient ID", "NHS number".
_REC_LABEL = (r"(?:\bMRN|\bM\.R\.N\.?|\bNHS\s+(?i:no\.?|number)|\b(?i:(?:hospital|medical|patient|case|record|file|chart|admission|clinical|clinic)"
              r"\s+(?:record\s+|file\s+)?(?:no\.?|nr\.?|number|num\.?|id|#)|record\s+(?:no\.?|number)|"
              r"cartella(?:\s+clinica)?(?:\s+(?:n\.?|n°|nr\.?|numero))?|nosologico|"
              r"(?:n\.?|n°|numero|codice|id)\s+(?:di\s+)?(?:ricovero|cartella|paziente|pratica|accettazione|nosologico|referto)|"
              r"codice\s+paziente|id\s+paziente|pratica(?:\s+n\.?)?|accettazione(?:\s+n\.?)?))")
_REC = re.compile(_REC_LABEL + r"[ \t]*[:#]?[ \t]*(?P<v>(?:[A-Za-z]{1,3}[-/]?)?\d[\d/-]*(?:[ ]\d{3,4}){0,3})(?!\w)")
_REF = re.compile(r"\b(?:Ref|Rif|Reference|Riferimento)\b\.?[ \t]*[:#]?[ \t]*(?P<v>(?:[A-Za-z]{1,3}[-/]?)?\d[\d/-]*)(?!\w)")
# A long digit run with no label is an identifier too (record, card or account number); doses, lab values and
# dates are shorter or carry separators.
_LONG_DIGITS = re.compile(r"(?<![\d.,:/-])\d{7,}(?![\d]|[.,]\d)")
_DIGITS_SLASH = re.compile(r"(?<![\d/.])\d{2,4}/\d{5,8}(?![\d/])")
_CODE_SLASH = re.compile(r"\b[A-Z]{1,3}-\d{3,6}/\d{2}\b")  # C-2291/24
# Codice fiscale read off a scan or retyped: 16 characters in the 6 letters, 2 digits, letter, 2 digits, letter,
# 3 digits, letter layout, where up to 2 characters may be a look-alike (O/0, I/1, S/5, B/8, Z/2).
_CF_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{16}(?![A-Za-z0-9])")
_CF_LETTER_POS = (0, 1, 2, 3, 4, 5, 8, 11, 15)
_CF_DIGIT_POS = (6, 7, 9, 10, 12, 13, 14)
_CF_AS_DIGIT, _CF_AS_LETTER = set("OILSZB"), set("015825")


def _cf_like(tok: str) -> bool:
    errors = 0
    for k in _CF_LETTER_POS:
        if tok[k].isdigit():
            if tok[k] not in _CF_AS_LETTER:
                return False
            errors += 1
    for k in _CF_DIGIT_POS:
        if not tok[k].isdigit():
            if tok[k].upper() not in _CF_AS_DIGIT:
                return False
            errors += 1
    return errors <= 2
_NAME_WORD = r"[A-ZÀ-Ý][\w'’]+"
_STREET_IT = (r"via|viale|piazza|piazzale|corso|vicolo|largo|lungarno|lungotevere|lungomare|strada|contrada|borgo|salita|"
              r"vico|stradone|traversa|localit[àa]|frazione")
_STREET_EN = r"street|st|road|rd|avenue|ave|lane|drive|close|way|court|gardens|place|crescent|terrace|square|mews|grove"
# words after "via" that make it the preposition ("via WhatsApp", "via email")
_NOT_STREET = r"(?i:email|e-mail|mail|phone|whatsapp|sms|app|skype|zoom|telefono|posta|web|the|a|an|telegram|portal|portale|video|call)"
_ADDRESS = [
    re.compile(rf"\b(?i:{_STREET_IT})\s+(?!{_NOT_STREET}\b)(?:(?i:di|del|della|dei|degli|delle|dell['’])\s*)?"
               rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}"
               rf"(?:,?\s*(?:(?i:n\.?|civico|n°)\s*)?\d{{1,4}}(?:[A-Za-z]\b|/[A-Za-z0-9]{{1,3}})?(?:,?\s*(?i:int\.?|interno|scala|sc\.?)\s*\w{{1,3}})?)?"),
    # named residences and localities: "Condominio Le Rose, scala B, int. 4", "loc. Fontana 12"
    re.compile(rf"\b(?i:condominio|loc\.|localit[àa]|frazione|c\.da)\s+{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}"
               rf"(?:,?\s*(?i:scala|sc\.)\s*\w{{1,3}})?(?:,?\s*(?i:int\.?|interno)\s*\w{{1,3}})?(?:,?\s*\d{{1,4}}\b)?"),
    # typed in lower case: only with a house number, and never "via email 2 times"
    re.compile(rf"\b(?i:via|viale|piazza|piazzale|vicolo|lungarno)\s+(?!{_NOT_STREET}\b)"
               rf"(?:(?i:di|del|della|dei|degli|delle|dell['’])\s*)?[A-Za-zÀ-ÿ'’]{{2,}}(?:\s+[A-Za-zÀ-ÿ'’]{{2,}}){{0,2}}?,?\s*(?:(?i:n\.?|civico|n°)\s*)?"
               rf"\d{{1,4}}(?:[A-Za-z]\b|/[A-Za-z0-9]{{1,3}})?"),
    re.compile(rf"\b(?:(?i:flat|apartment|apt|unit)\s+\d{{1,3}}[A-Za-z]?,\s*)?\d{{1,4}}\s+{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}\s+(?i:{_STREET_EN})\b\.?"),
    re.compile(rf"\b{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}\s+(?:Street|Road|Avenue|Lane|Drive|Close|Gardens|Crescent|Terrace)\b(?:,?\s*\d{{1,4}})?"),
]
_DATE = [
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}([/.-])\d{1,2}\1(?:\d{4}|\d{2})\b"),
    re.compile(r"\b\d{1,2}-[A-Za-z]{3}-(?:\d{4}|\d{2})\b"),
    re.compile(rf"\b{_DAY}\s+(?:(?i:of)\s+)?{_MONTH}(?:,?\s+(?:\d{{4}}|['’]\d{{2}}))?\b"),
    re.compile(rf"\b{_MONTH}\s+{_DAY}\b(?:,?\s+(?:\d{{4}}|['’]\d{{2}}))?"),
]
_PHONE = [
    re.compile(r"(?<![\w+])(?<!\d[\s.-])\(?(?:\+|00)\d{1,3}\)?[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)"),
    re.compile(r"(?<![\d.])3\d{2}(?:[\s./-]?\d){6,7}(?!\d)"),  # Italian mobile in any grouping (3-3-4, 3-2-2-3, solid)
    re.compile(r"(?<![\d.])0\d{1,3}[\s./-]\d{5,8}(?!\d)"),
    re.compile(r"(?<![\d.])0\d{1,3}(?:[\s./-]\d{2}){3,4}(?!\d)"),  # landline in pairs: 02 12 34 56 78
    re.compile(r"(?<![\d.])\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
]
_TITLE_NAME = re.compile(
    r"\b(?:(?:Dr|DR|Dott|DOTT|Prof|PROF|Mr|MR|Mrs|MRS|Ms|MS|Miss|Mx|Sig|SIG|Primario)(?:\.ssa|\.ra|\.na|\.|ssa)?"
    r"|[Dd]ottor(?:e|essa)?|[Pp]rofessor(?:e|essa)?|dott\.(?:ssa)?|dr\.|prof\.(?:ssa)?)\s+" + _NAME_WORD)

# A surname that follows a first name or a title: one or two capitalised words, optionally behind a particle
# ("De Luca", "Della Valle"). Medical terms and sentence words are never taken.
_PARTICLES = {"de", "di", "da", "del", "della", "dei", "degli", "dal", "dalla", "lo", "la", "le", "van", "von", "mc", "mac"}
# Medical eponyms: never a surname, and never redacted when a name rule fires on them.
_EPONYMS = {
    "lupus", "raynaud", "sjogren", "sjögren", "crohn", "hashimoto", "graves", "behcet", "behçet", "addison", "cushing",
    "parkinson", "alzheimer", "asperger", "down", "hodgkin", "kawasaki", "meniere", "ménière", "marfan", "wilson",
    "huntington", "gilbert", "paget", "takayasu", "hughes", "still", "bell", "reiter", "felty", "gaucher", "duchenne",
    "becker", "charcot", "osler", "wegener", "horton", "kaposi", "peyronie", "dupuytren", "ehlers", "danlos", "tourette",
    "bechterew", "waldenstrom", "waldenström", "hirschsprung", "whipple", "burkitt", "hansen", "kikuchi", "sneddon",
    "guillain", "barre", "barré", "bright", "hurler", "tay", "sachs", "lyme", "turner", "klinefelter", "sturge", "weber",
    "wolff", "parkinson-white", "conn", "zollinger", "ellison", "lambert", "eaton", "castleman", "schnitzler", "sweet",
    "basedow", "pott", "meckel", "crouzon", "apert", "noonan", "williams", "prader", "willi", "angelman", "rett",
}
_NOT_SURNAME = _EPONYMS | {
    "syndrome", "sindrome", "disease", "malattia", "morbo", "fenomeno", "phenomenon", "test", "the", "a", "an", "and",
    "or", "but", "i", "my", "in", "on", "at", "it", "he", "she", "we", "is", "was", "il", "un", "una", "e", "ma", "ho",
    "mi", "ha", "ed", "se", "che", "per", "con", "oggi", "ieri", "domani", "today", "yesterday", "tomorrow",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "lunedì", "martedì", "mercoledì",
    "giovedì", "venerdì", "sabato", "domenica", "may", "dr", "dott", "dottor", "dottore", "dottoressa", "prof",
    "professor", "professore", "mr", "mrs", "ms", "miss", "sig", "italian", "english", "german", "french", "covid",
    "christmas", "easter", "natale", "pasqua", "internet", "nhs", "asl", "usl", "gp",
} | {m.lower() for m in _MONTHS_FULL} | {m.lower().rstrip(".") for m in _MONTHS_ABBR}
_SURNAME_WORD = re.compile(r"[ \t]+([A-ZÀ-Ý][\w'’]*)")
# A word that names a disease right after / before a candidate: "Graves disease", "morbo di Crohn", "Sjogren's syndrome".
_EPONYM_AFTER = re.compile(r"(?:['’]s)?[ \t]+(?i:disease|syndrome|sindrome|malattia|morbo|phenomenon|fenomeno|palsy|paralisi|test|"
                           r"thyroiditis|tiroidite|lymphoma|linfoma|arteritis|arterite|anaemia|anemia|sign|segno|ulcer|ulcera)\b")
_EPONYM_BEFORE = re.compile(r"(?i:malattia|morbo|sindrome|disease|syndrome|fenomeno|phenomenon|tiroidite|thyroiditis)[ \t]+(?:(?i:di|del|of)[ \t]+)?$")
# Saints and places of care: "Ospedale San Raffaele", "St Thomas' Hospital", "in Siena".
_PLACE_BEFORE = re.compile(r"(?i:\b(?:san|santa|santo|sant['’]|st\.?|saint|ospedale|hospital|policlinico|clinica|clinic|presso|in|at|near)[ \t]*)$")
_FIELD_WORDS = {
    "id", "mrn", "dob", "cf", "ts", "tel", "sesso", "nato", "nata", "data", "date", "born", "codice", "via", "nome", "cognome",
    "name", "surname", "paziente", "patient", "esame", "visita", "referto", "report", "motivo", "diagnosi", "note", "note:",
    "information", "info", "portal", "details", "history", "number", "numero", "reparto", "ward", "email", "mail",
}


def _surname_end(text: str, pos: int) -> int:
    """End of the personal-name span that continues after `pos` (a first name or a title), or `pos`."""
    end, taken = pos, 0
    while taken < 2:
        m = _SURNAME_WORD.match(text, end)
        if not m or m.group(1).lower() in _NOT_SURNAME:
            break
        if m.group(1).lower() in _PARTICLES:  # a particle only counts when a capitalised word follows it
            nxt = _SURNAME_WORD.match(text, m.end())
            if not nxt or nxt.group(1).lower() in _NOT_SURNAME or nxt.group(1).lower() in _PARTICLES:
                break
            end, taken = nxt.end(), taken + 2
            continue
        end, taken = m.end(), taken + 1
    return end


_NAMES_FILE = Path(__file__).parent / "data" / "first_names.txt"
_name_re: re.Pattern | None = None
_name_caps_re: re.Pattern | None = None
_name_set: set[str] | None = None


def _names() -> re.Pattern:
    global _name_re, _name_set
    if _name_re is None:
        names = [n.strip() for n in _NAMES_FILE.read_text(encoding="utf-8").splitlines() if n.strip()]
        _name_set = {n.lower() for n in names}
        alts = "|".join(sorted({a for n in names for a in (n, n.upper())}, key=len, reverse=True))
        _name_re = re.compile(rf"\b(?:{alts})\b")
    return _name_re


def _is_first_name(word: str) -> bool:
    _names()
    return word.lower() in (_name_set or ())


# Labels that introduce the patient or a clinician in a referto header or a form: "Paziente: Rossi Mario".
_LABEL_NAME = re.compile(
    r"\b(?:Paziente|PAZIENTE|Patient|PATIENT|Nome|NOME|Cognome|COGNOME|Name|NAME|Surname|Intestatario|INTESTATARIO|"
    r"Intestato\s+a|Referto\s+per|Referral\s+for|Firmato\s+da|Signed\s+by|Medico\s+curante|Medico|Doctor|Referente)"
    r"\b(?P<sep>[ \t]*[:\-–][ \t]*|[ \t]+)(?=[A-ZÀ-Ý])")
# People named through a relation or a verb of contact: "my friend Harry", "mia cugina Ilaria", "called Harry",
# "lunch with Isabelle", "parlato con Elena". Eponyms, dates and titles are never taken.
_KIN = (r"friend|sister|brother|cousin|neighbou?r|mother|father|mom|mum|dad|husband|wife|partner|colleague|boss|aunt|uncle|"
        r"daughter|son|nurse|physio|therapist|doctor|GP|girlfriend|boyfriend|amica|amico|sorella|fratello|cugina|cugino|vicina|"
        r"vicino|madre|padre|mamma|pap[àa]|marito|moglie|compagna|compagno|collega|zia|zio|figlia|figlio|infermiera|"
        r"infermiere|dottoressa|medico|nonna|nonno|nipote|suocera|suocero|cognata|cognato|fidanzata|fidanzato")
_CUE_VERB = (r"called|told|asked|texted|thanked|emailed|messaged|phoned|met|visited|"
             r"(?:spoke|speak|spoken|talked|talk|chatted|chat)\s+(?:to|with)|"
             r"(?:lunch|dinner|coffee|breakfast|supper|walk|drinks|pranzo|cena|colazione|caff[eè]|passeggiata|aperitivo)\s+(?:with|con)|"
             r"chiamato|chiamata|chiamare|chiamo|ringraziato|ringraziata|incontrato|incontrata|visto|"
             r"(?:parlato|parlare|parlo|uscito|uscita|uscire|sentito|sentita)\s+con|"
             r"(?:telefonato|scritto|risposto|detto)\s+a|accompagnat[oa]\s+da|(?:driven|brought|taken|helped)\s+by|"
             r"portat[oa]\s+da|aiutat[oa]\s+da|"
             r"(?:firmato|firmata|refertato|refertata|redatto|compilato|visitato|visitata|seguito|seguita|in\s+cura)(?:\s+da)?|"
             r"(?:signed|seen|treated|followed|referred)\s+by|signed")
_CUE = re.compile(rf"(?:\b(?i:my|mia|mio|la\s+mia|il\s+mio|his|her|our|nostra|nostro|sua|suo)\s+(?i:{_KIN})|"
                  rf"\b(?i:{_CUE_VERB}))[ \t]+(?P<n>{_NAME_WORD})")


def _word_ok(w: str) -> bool:
    return w.lower() not in _NOT_SURNAME and w.lower() not in _FIELD_WORDS


def _name_suppressed(text: str, s: int, e: int) -> bool:
    """A name rule fired on [s, e): is it really a disease, a saint or a place of care?"""
    word = text[s:e].split()[0] if text[s:e].split() else ""
    if word.lower() in _EPONYMS:
        return True
    if _EPONYM_AFTER.match(text, e) or _EPONYM_BEFORE.search(text, max(0, s - 24), s):
        return True
    return bool(_PLACE_BEFORE.search(text, max(0, s - 16), s))


def _label_names(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _LABEL_NAME.finditer(text):
        pos, words = m.end(), []
        while len(words) < 3:
            w = re.compile(r"([A-ZÀ-Ý][\w'’]*)").match(text, pos)
            if not w or not _word_ok(w.group(1)):
                break
            words.append(w)
            sp = re.compile(r"[ \t]+").match(text, w.end())
            if not sp:
                pos = w.end()
                break
            pos = sp.end()
        if not words:
            continue
        end = words[-1].end()
        colon = re.search(r"[:\-–]", m.group("sep")) is not None
        tokens = [w.group(1) for w in words]
        # Without a colon the label is also an ordinary word ("Patient Portal"): then only an upper-case pair
        # or a known first name counts.
        if not colon and not (any(_is_first_name(t) for t in tokens) or (len(tokens) >= 2 and all(t.isupper() for t in tokens))):
            continue
        out.append((words[0].start(), end, "name"))
    return out


def _lexicon_names(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _names().finditer(text):
        if _name_suppressed(text, m.start(), m.end()):
            continue
        start = m.start()
        # surname first: "Moretti Tommaso", "MORETTI TOMMASO", "Della Valle Sara" (not at a sentence start)
        prev = re.search(r"([A-ZÀ-Ý][\w'’]+)[ \t]+$", text[max(0, start - 40):start])
        if prev and _word_ok(prev.group(1)) and prev.group(1).lower() not in _PARTICLES:
            ps = max(0, start - 40) + prev.start(1)
            before = text[:ps].rstrip(" \t")
            if before and before[-1] not in ".!?:;\n" and not _is_first_name(prev.group(1)):
                start = ps
                while True:  # particles in front of the surname
                    pm = re.search(r"\b([A-Za-zÀ-ÿ]+)[ \t]+$", text[max(0, start - 20):start])
                    if pm and pm.group(1).lower() in _PARTICLES:
                        start = max(0, start - 20) + pm.start(1)
                    else:
                        break
        out.append((start, _surname_end(text, m.end()), "name"))
    return out


# A capitalised name before a verb of speech or contact: "Esposito said ...", "Giuli mi ha scritto".
_SAYS = re.compile(rf"(?<![\w'’])(?P<n>{_NAME_WORD}(?:[ \t]+{_NAME_WORD})?)[ \t]+"
                   r"(?i:said|says|called|rang|texted|wrote|told|asked|replied|answered|thinks|agreed|confirmed|suggested|"
                   r"insisted|mentioned|reminded|ha\s+(?:detto|chiamato|scritto|risposto|confermato|telefonato)|dice|"
                   r"mi\s+(?:ha\s+)?(?:detto|dice|chiama|chiamato|scrive|scritto|telefona|telefonato|manda|mandato))\b")
_SUBJECT_WORDS = {"he", "she", "they", "we", "it", "who", "mom", "mum", "dad", "mother", "father", "doctor", "nurse",
                  "everyone", "nobody", "somebody", "lui", "lei", "loro", "noi", "mamma", "papà", "medico", "dottore",
                  "dottoressa", "infermiera", "everybody", "someone", "anyone", "gp", "surgeon", "consultant", "registrar",
                  "midwife", "carer", "secretary", "segretaria", "ostetrica", "chirurgo", "radiologo"}
_ROLE_SUFFIX = re.compile(r"(?i)(?:ologist|ologo|ologa|iatra|iatrist|ician|apist|apista|macist|macista|dentista|dentist|specialist|receptionist)$")


def _is_role(word: str) -> bool:
    """Job titles that open a sentence ("Rheumatologist said ...") are not a person's name."""
    return word.lower() in _SUBJECT_WORDS or bool(_ROLE_SUFFIX.search(word))


def _says_names(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _SAYS.finditer(text):
        words = m.group("n").split()
        if len(words) == 2 and (words[0].lower() in _NOT_SURNAME or _is_role(words[0]) or not _word_ok(words[0])):
            words = words[1:]  # "Then Esposito said": only the last word is the name
        if not words or any(not _word_ok(w) or _is_role(w) for w in words):
            continue
        s = m.end("n") - len(" ".join(words))
        if _name_suppressed(text, s, m.end("n")):
            continue
        out.append((s, m.end("n"), "name"))
    return out


def _cue_names(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _CUE.finditer(text):
        s, e = m.start("n"), m.end("n")
        if not _word_ok(m.group("n")) or _name_suppressed(text, s, e):
            continue
        out.append((s, _surname_end(text, e), "name"))
    return out


def _candidates(text: str) -> list[tuple[int, int, str]]:
    """(start, end, type) in priority order (earlier = wins an overlap)."""
    out: list[tuple[int, int, str]] = []

    def add(rx: re.Pattern, typ: str, group: str | None = None) -> None:
        for m in rx.finditer(text):
            if group is None:
                out.append((m.start(), m.end(), typ))
            elif sum(c.isdigit() for c in m.group(group)) >= 5:
                out.append((m.start(group), m.end(group), typ))

    add(_EMAIL, "email")
    add(_EMAIL_OBFUSCATED, "email")
    add(_IBAN, "iban")
    add(_CF, "codice_fiscale")
    add(_CF_SPACED, "codice_fiscale")
    add(_TS, "health_id")
    add(_TS_LABELLED, "health_id", "v")
    add(_REC, "record", "v")
    for rx in _ADDRESS:
        add(rx, "address")
    for rx in _DATE:
        add(rx, "date")
    for rx in _PHONE:
        add(rx, "phone")
    out.extend((m.start(), _surname_end(text, m.end()), "name") for m in _TITLE_NAME.finditer(text))
    out.extend(_label_names(text))
    out.extend(_cue_names(text))
    out.extend(_says_names(text))
    out.extend(_lexicon_names(text))
    out.extend((m.start(), m.end(), "codice_fiscale") for m in _CF_TOKEN.finditer(text) if _cf_like(m.group()))
    add(_REF, "record", "v")
    add(_DIGITS_SLASH, "record")
    add(_LONG_DIGITS, "record")
    add(_CODE_SLASH, "record")
    return out


def pseudonymize(text: str) -> tuple[str, list[dict]]:
    """Replace direct identifiers with placeholders.

    Returns (redacted, replacements). Each replacement is {type, start, end, out_start, out_end}: `start/end` index
    the original text, `out_start/out_end` the redacted text. The original values are not stored anywhere.
    """
    taken: list[tuple[int, int, str]] = []
    for s, e, typ in _candidates(text):
        if e > s and all(e <= ts or s >= te for ts, te, _ in taken):
            taken.append((s, e, typ))
    taken.sort()
    parts: list[str] = []
    reps: list[dict] = []
    pos = 0
    out_len = 0
    for s, e, typ in taken:
        chunk = text[pos:s]
        parts.append(chunk)
        out_len += len(chunk)
        ph = PLACEHOLDER[typ]
        parts.append(ph)
        reps.append({"type": KIND.get(typ, typ), "start": s, "end": e, "out_start": out_len, "out_end": out_len + len(ph)})
        out_len += len(ph)
        pos = e
    parts.append(text[pos:])
    return "".join(parts), reps


# ---------------------------------------------------------------------- mapping quotes back
def _to_original(pos: int, reps: list[dict], *, end: bool) -> int:
    """Index in the redacted text -> index in the original. Inside a placeholder, snap to the whole value."""
    delta = 0
    for r in reps:
        if pos <= r["out_start"]:
            break
        if pos < r["out_end"]:
            return r["end"] if end else r["start"]
        delta = r["end"] - r["out_end"]
    return pos + delta


def restore_quote(quote: str, redacted: str, original: str, reps: list[dict]) -> str | None:
    """Map a quote the model copied from the redacted text onto the original text. None if it is not in it."""
    q = re.sub(r"\s+", " ", (quote or "").strip(" .,;:\"'"))
    if len(q) < 2:
        return None
    m = re.search(re.escape(q).replace(r"\ ", r"\s+"), redacted, flags=re.I)
    if not m:
        return None
    s, e = _to_original(m.start(), reps, end=False), _to_original(m.end(), reps, end=True)
    return original[s:e] if e > s else None


class Redaction:
    """What was redacted in one call. Lives only in memory for the duration of the call."""

    def __init__(self) -> None:
        self.pairs: list[tuple[str, str, list[dict]]] = []

    def add(self, original: str, redacted: str, reps: list[dict]) -> None:
        if reps:
            self.pairs.append((original, redacted, reps))

    @property
    def count(self) -> int:
        return sum(len(r) for _, _, r in self.pairs)

    def restore(self, quote: str) -> str:
        for original, redacted, reps in self.pairs:
            got = restore_quote(quote, redacted, original, reps)
            if got:
                return got
        return quote

    def restore_in(self, obj: Any) -> Any:
        """Walk a model output and restore every field called `quote`."""
        if isinstance(obj, BaseModel):
            for name in type(obj).model_fields:
                v = getattr(obj, name)
                if name == "quote" and isinstance(v, str):
                    setattr(obj, name, self.restore(v))
                else:
                    self.restore_in(v)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k == "quote" and isinstance(v, str):
                    obj[k] = self.restore(v)
                else:
                    self.restore_in(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self.restore_in(v)
        return obj


# ====================================================================== call log
def now_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def chain_hash(prev_hash: str, payload_sha256: str, ts: str, backend: str, model: str, purpose: str) -> str:
    return sha256(prev_hash + payload_sha256 + ts + backend + model + purpose)


def call_id(seq: int) -> str:
    return f"call_{seq:06d}"


class VaultStore:
    """Calls live in the encrypted vault as kind 'ai_call'."""

    def __init__(self, vault: Vault):
        self.v = vault

    HEAD = "ai_call_head"

    def records(self) -> list[dict]:
        return sorted(self.v.all("ai_call"), key=lambda r: r.get("seq", 0))

    def recent(self, limit: int) -> list[dict]:
        """Newest first."""
        return sorted(self.v.recent("ai_call", limit), key=lambda r: r.get("seq", 0), reverse=True)

    def head(self) -> tuple[int, str] | None:
        """(seq, hash) of the last record, from vault meta; a log written before the head was kept falls back to its newest row."""
        raw = self.v.sealed_meta(self.HEAD)
        if raw is not None:
            h = json.loads(raw)
            return h["seq"], h["hash"]
        last = self.recent(1)
        return (last[0].get("seq", 1), last[0].get("hash", GENESIS)) if last else None

    def add(self, rec: dict) -> None:
        self.v.put("ai_call", rec["id"], rec, meta={self.HEAD: json.dumps({"seq": rec["seq"], "hash": rec["hash"]}).encode()})


class FileStore:
    """Clinic mode: its own append-only JSONL file next to the clinic keys. Holds redacted previews only."""

    def __init__(self, path: Path, keys=None):
        self.path = path
        self.keys = keys  # ClinicKeys: the diary preview text is encrypted at rest when given
        path.parent.mkdir(parents=True, exist_ok=True)

    def _enc(self, rec: dict) -> dict:
        if self.keys and rec.get("redacted_preview"):
            rec = {**rec, "redacted_preview": "enc:" + base64.b64encode(self.keys.seal_data(rec["redacted_preview"].encode())).decode()}
        return rec

    def _dec(self, rec: dict) -> dict:
        pv = rec.get("redacted_preview")
        if self.keys and isinstance(pv, str) and pv.startswith("enc:"):
            try:
                rec = {**rec, "redacted_preview": self.keys.open_data(base64.b64decode(pv[4:])).decode()}
            except Exception:  # noqa: BLE001 - wrong key or damaged: show nothing rather than the cipher text
                rec = {**rec, "redacted_preview": ""}
        return rec

    def recent(self, limit: int) -> list[dict]:
        """Newest first."""
        return self.records()[::-1][:limit]

    def head(self) -> tuple[int, str] | None:
        """(seq, hash) from the last line only; None when the file is empty or its last line is damaged."""
        if not self.path.exists():
            return None
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        try:
            last = json.loads(lines[-1]) if lines else None
        except json.JSONDecodeError:
            last = None
        return (last["seq"], last["hash"]) if last and "seq" in last and "hash" in last else None

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        recs = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    recs.append(self._dec(json.loads(line)))
                except json.JSONDecodeError:
                    recs.append({"id": "corrupt", "seq": 10 ** 9})
        return sorted(recs, key=lambda r: r.get("seq", 0))

    def add(self, rec: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self._enc(rec), ensure_ascii=False) + "\n")


class CallLog:
    def __init__(self, store: VaultStore | FileStore):
        self.store = store
        self._lock = threading.Lock()
        self._head: tuple[int, str] | None = None  # (seq, hash) of the last record
        self._pending: list[dict] = []  # calls made while the vault was locked, chained on the next write

    @classmethod
    def for_settings(cls, s, vault: Vault | None, keys=None) -> "CallLog":
        return cls(VaultStore(vault) if vault is not None else FileStore(s.data_dir / "ai_calls.jsonl", keys))

    def _load_head(self) -> tuple[int, str]:
        head = self.store.head()
        if head is not None:
            return head
        recs = self.store.records()  # empty log, or a last line that cannot be read: walk it
        return (recs[-1].get("seq", len(recs)), recs[-1].get("hash", GENESIS)) if recs else (0, GENESIS)

    def append(self, *, backend: str, model: str, purpose: str, preview: str, sent_text: str,
               redacted: bool = False, replacements: int = 0, images: int = 0) -> dict | None:
        purpose = purpose if purpose in PURPOSES else "other"
        entry = {"ts": now_iso_ms(), "backend": backend, "model": model, "purpose": purpose,
                 "redacted_preview": preview[:200], "payload_sha256": sha256(sent_text),
                 "redacted": redacted, "replacements": replacements, "images": images}
        with self._lock:
            self._pending.append(entry)
            try:
                if self._head is None:
                    self._head = self._load_head()
                last = None
                while self._pending:
                    p = self._pending[0]
                    seq, prev = self._head
                    rec = {"id": call_id(seq + 1), "seq": seq + 1, **p, "prev_hash": prev,
                           "hash": chain_hash(prev, p["payload_sha256"], p["ts"], p["backend"], p["model"], p["purpose"])}
                    self.store.add(rec)
                    self._head = (rec["seq"], rec["hash"])
                    self._pending.pop(0)
                    last = rec
                return last
            except Locked:
                self._head = None
                return None

    def calls(self, limit: int = 50) -> list[dict]:
        return self.store.recent(max(1, min(limit, 500)))

    def verify(self) -> dict:
        prev, expect = GENESIS, 1
        recs = self.store.records()
        for r in recs:
            try:
                ok = (r.get("seq") == expect and r.get("id") == call_id(expect) and r.get("prev_hash") == prev
                      and r.get("hash") == chain_hash(prev, r["payload_sha256"], r["ts"], r["backend"], r["model"], r["purpose"]))
            except (KeyError, TypeError):
                ok = False
            if not ok:
                return {"ok": False, "broken_at": r.get("id") or call_id(expect), "count": len(recs)}
            prev, expect = r["hash"], expect + 1
        return {"ok": True, "broken_at": None, "count": len(recs)}


# ====================================================================== LLM wrapper
def should_pseudonymize(s) -> bool:
    """CLARIO_PSEUDONYMIZE=1|0 wins. Default: on for patient mode when the model is remote."""
    if s.pseudonymize is not None:
        return s.pseudonymize
    if s.mode != "patient" or s.offline:
        return False
    return (s.llm_host or "") not in LOCAL_HOSTS


class PrivacyLLM:
    """Delegates to the inner LLM. Redacts user messages when `pseudonymize` is on. Logs every call."""

    def __init__(self, inner, log: CallLog, pseudonymize: bool):
        self._inner, self.log, self.pseudonymize = inner, log, pseudonymize

    def __getattr__(self, name: str):
        """Plain attributes of the inner client (backend, model, is_amd) pass through. A method never does: every
        way to call the model is defined below, so a method added to LLM later cannot skip redaction and the log."""
        value = getattr(self._inner, name)
        if callable(value):
            raise AttributeError(f"{type(self).__name__} does not forward {name}(); define it so the call is redacted and logged")
        return value

    # -- internals
    def _prepare(self, task: str, messages: list[dict], payload: dict | None, purpose: str | None):
        red = Redaction()
        out: list[dict] = []
        last_user = ""
        for m in messages:
            c = m.get("content")
            if m.get("role") == "user" and isinstance(c, str):
                r, reps = pseudonymize(c)
                last_user = r  # the preview always shows redacted text, even when the backend is local
                if self.pseudonymize:
                    red.add(c, r, reps)
                    m = {**m, "content": r}
            elif isinstance(c, list):  # multimodal parts: text is redacted, images pass through
                parts = []
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                        r, reps = pseudonymize(p["text"])
                        last_user = r
                        if self.pseudonymize:
                            red.add(p["text"], r, reps)
                            p = {**p, "text": r}
                    parts.append(p)
                m = {**m, "content": parts}
            out.append(m)
        pl = payload
        if self.pseudonymize and payload and isinstance(payload.get("text"), str):
            pl = {**payload, "text": pseudonymize(payload["text"])[0]}  # the local hint must match what is sent
        return out, pl, red, (task, out, last_user, purpose, red)

    async def _record(self, args: tuple) -> None:
        """Write the log record off the event loop: it touches sqlite or a file."""
        await asyncio.to_thread(self._log, *args)

    def _log(self, task: str, sent: list[dict], preview: str, purpose: str | None, red: Redaction) -> None:
        images = sum(1 for m in sent if isinstance(m.get("content"), list)
                     for p in m["content"] if isinstance(p, dict) and p.get("type") != "text")
        p = purpose or (task if task in PURPOSES else "other")
        self.log.append(backend=self._inner.backend, model=self._inner.model, purpose=p, preview=preview,
                        sent_text=json.dumps(sent, ensure_ascii=False, sort_keys=True), redacted=self.pseudonymize,
                        replacements=red.count, images=images)

    # -- LLM surface
    async def complete(self, task, messages, *, purpose=None, payload=None, **kw):
        msgs, pl, _red, rec = self._prepare(task, messages, payload, purpose)
        await self._record(rec)
        return await self._inner.complete(task, msgs, payload=pl, **kw)

    async def stream(self, task, messages, *, purpose=None, payload=None, **kw):
        msgs, pl, _red, rec = self._prepare(task, messages, payload, purpose)
        await self._record(rec)
        async for item in self._inner.stream(task, msgs, payload=pl, **kw):
            yield item

    async def json(self, task, messages, cls, *, purpose=None, payload=None, **kw):
        msgs, pl, red, rec = self._prepare(task, messages, payload, purpose)
        await self._record(rec)
        res, st = await self._inner.json(task, msgs, cls, payload=pl, **kw)
        return red.restore_in(res), st

    async def samples(self, task, messages, *args, purpose=None, payload=None, **kw):
        msgs, pl, red, rec = self._prepare(task, messages, payload, purpose)
        await self._record(rec)
        texts, st = await self._inner.samples(task, msgs, *args, payload=pl, **kw)
        return [self._restore_text(t, red) for t in texts], st

    @staticmethod
    def _restore_text(text: str, red: Redaction) -> str:
        """Raw JSON text from samples(): restore placeholders inside `quote` fields, leave the rest as sent."""
        if not red.count:
            return text
        try:
            obj = extract_json(text)
        except ValueError:
            return text
        return json.dumps(red.restore_in(obj), ensure_ascii=False)


def wrap(inner, s, log: CallLog) -> PrivacyLLM:
    return PrivacyLLM(inner, log, should_pseudonymize(s))


# ====================================================================== HTTP routes
def routes(app: FastAPI, s, log: CallLog, get_entry: Callable[[str], Any] | None = None) -> None:
    @app.get("/api/privacy/calls")
    def privacy_calls(limit: int = 50) -> list[dict]:
        return log.calls(limit)

    @app.get("/api/privacy/verify")
    def privacy_verify() -> dict:
        return log.verify()

    if get_entry is not None:
        @app.get("/api/privacy/preview")
        def privacy_preview(entry_id: str) -> dict:
            e = get_entry(entry_id)
            if e is None:
                raise HTTPException(404, "entry not found")
            redacted, reps = pseudonymize(e.text)
            return {"original": e.text, "redacted": redacted, "replacements": reps,
                    "applied": should_pseudonymize(s), "backend": s.llm_backend}

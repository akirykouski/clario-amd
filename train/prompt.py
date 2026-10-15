"""Clario extraction prompt, extraction_v3 contract. Single source of truth; dependency-free (stdlib only).

Contract: backend/clario/schemas/extraction_v3.json (frozen 2026-10-15). Each entity carries
quote, canonical, hpo_id, type, negated, family_history, onset_hint, severity, confidence.
Older outputs (no family_history / onset_hint / severity / confidence, hpo_id "" , `span` or
`name` keys) still parse; missing fields take the neutral value.
"""
import json
import re

TYPES = ("symptom", "finding", "lab", "medication", "trigger", "body_site")
_TYPE_MAP = {"bodypart": "body_site", "body_part": "body_site", "bodysite": "body_site",
             "med": "medication", "drug": "medication", "lab_marker": "lab", "labmarker": "lab"}
FIELDS = ("quote", "canonical", "hpo_id", "type", "negated", "family_history", "onset_hint", "severity",
          "confidence")

_CORE = """You extract clinical entities from a patient's colloquial diary entry (English or Italian) and map each to a Human Phenotype Ontology (HPO) term.

Return ONLY one JSON object, no prose, no markdown fences:
{"entities":[{"quote":"...","canonical":"...","hpo_id":"HP:0000000","type":"symptom","negated":false,"family_history":false,"onset_hint":null,"severity":null,"confidence":null}]}

Rules:
- quote: an exact, verbatim span copied from the diary (same characters, same case), covering the symptom words and not the negation word. Never paraphrase.
- canonical: the standard clinical English term for the concept, for example "Malar rash".
- hpo_id: the HPO identifier, format HP:#######, or null if you are not confident of the ID.
- type: one of symptom, finding, lab, medication, trigger, body_site.
- negated: true only when the diary says the entity is absent ("no fever", "niente febbre").
- family_history: true when the entity belongs to a relative ("my mother has lupus", "mia madre ha il lupus"), not to the writer. Such entities are still listed.
- onset_hint: the time phrase from the diary for when it started ("since Tuesday", "da tre giorni"), or null.
- severity: an integer 0 to 10 only when the diary gives a rating ("6/10"), else null.
- confidence: %s
- Extract only what the diary states. Do not infer diseases or diagnoses. Do not add advice.
- Ignore unrelated life events. One entity per distinct concept; no duplicates. If nothing clinical is present, return {"entities":[]}."""

SYSTEM_PROMPT = _CORE % "always null."
SYSTEM_PROMPT_CONF = _CORE % ("your probability from 0 to 1 that this entity is correct "
                              "(right span, right HPO ID, right negation and family flags).")

_ID = re.compile(r"^HP:\d{7}$")


def build_messages(diary: str, confidence: bool = False) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT_CONF if confidence else SYSTEM_PROMPT},
        {"role": "user", "content": diary.strip()},
    ]


def _type(v) -> str:
    t = str(v or "symptom").lower()
    t = _TYPE_MAP.get(t, t)
    return t if t in TYPES else "symptom"


def _hpo(v):
    h = str(v or "").strip().upper()
    return h if _ID.match(h) else None


def _severity(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        s = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return s if 0 <= s <= 10 else None


def _confidence(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    return c if 0.0 <= c <= 1.0 else None


def _onset(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("null", "none") else None


def normalise(e: dict) -> dict:
    """Any entity-like dict (v3, v2, or dataset row) -> the full v3 entity."""
    quote = e.get("quote", e.get("span", e.get("name_colloquial", "")))
    canonical = e.get("canonical", e.get("name_canonical", e.get("name", "")))
    return {
        "quote": str(quote or ""),
        "canonical": str(canonical or ""),
        "hpo_id": _hpo(e.get("hpo_id")),
        "type": _type(e.get("type")),
        "negated": bool(e.get("negated", False)),
        "family_history": bool(e.get("family_history", False)),
        "onset_hint": _onset(e.get("onset_hint")),
        "severity": _severity(e.get("severity")),
        "confidence": _confidence(e.get("confidence")),
    }


def from_dataset_entities(entities: list) -> list:
    """Map dataset rows (name_colloquial/name_canonical/... or already v3) to the target schema.
    Training and gold targets never carry a confidence: it is null here."""
    out = []
    for e in entities:
        n = normalise(e)
        n["confidence"] = None
        out.append(n)
    return out


def target_json(entities: list) -> str:
    return json.dumps({"entities": [normalise(e) for e in entities]}, ensure_ascii=False, separators=(",", ":"))


def _extract_json(text: str):
    text = text.strip()
    # strip thinking blocks / fences
    text = re.sub(r"<\|channel>.*?<channel\|>", "", text, flags=re.S)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except Exception:
        pass
    s = text.find("{")
    while s != -1:
        depth = 0
        for i in range(s, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[s:i + 1])
                    except Exception:
                        break
        s = text.find("{", s + 1)
    return None


def parse(output: str):
    """Parse model output to a list of normalised v3 entity dicts.
    Returns None if the output is not valid JSON of the expected shape."""
    obj = _extract_json(output or "")
    if not isinstance(obj, dict) or not isinstance(obj.get("entities"), list):
        return None
    return [normalise(e) for e in obj["entities"] if isinstance(e, dict)]


def strict_valid(output: str) -> bool:
    """True only if the output is exactly the v3 shape: a JSON object whose entities carry every
    required key with the right types. Stricter than parse(), which fills defaults."""
    obj = _extract_json(output or "")
    if not isinstance(obj, dict) or set(obj) != {"entities"} or not isinstance(obj["entities"], list):
        return False
    for e in obj["entities"]:
        if not isinstance(e, dict) or set(e) != set(FIELDS):
            return False
        if not isinstance(e["quote"], str) or not isinstance(e["canonical"], str):
            return False
        if e["hpo_id"] is not None and not (isinstance(e["hpo_id"], str) and _ID.match(e["hpo_id"])):
            return False
        if e["type"] not in TYPES or not isinstance(e["negated"], bool) or not isinstance(e["family_history"], bool):
            return False
        if e["onset_hint"] is not None and not isinstance(e["onset_hint"], str):
            return False
        if e["severity"] is not None and (isinstance(e["severity"], bool) or not isinstance(e["severity"], int)
                                          or not 0 <= e["severity"] <= 10):
            return False
        c = e["confidence"]
        if c is not None and (isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1):
            return False
    return True

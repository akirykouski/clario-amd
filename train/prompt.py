"""Clario extraction prompt. Single source of truth; dependency-free (stdlib only)."""
import json
import re

TYPES = ("symptom", "finding", "lab", "medication", "trigger", "body_site")
_TYPE_MAP = {"bodypart": "body_site", "body_part": "body_site", "bodysite": "body_site"}

SYSTEM_PROMPT = """You extract clinical entities from a patient's colloquial diary entry and map each to a Human Phenotype Ontology (HPO) term.

Return ONLY one JSON object, no prose, no markdown fences:
{"entities":[{"quote":"...","canonical":"...","hpo_id":"HP:0000000","type":"symptom","negated":false}]}

Rules:
- quote: an exact, verbatim span copied from the diary (same characters, same case). Never paraphrase.
- canonical: the HPO preferred label for the concept.
- hpo_id: the HPO identifier, format HP:#######. Use an empty string if you are not confident of the ID.
- type: one of symptom, finding, lab, medication, trigger, body_site.
- negated: true only when the diary explicitly says the entity is absent (for example "no fever").
- Extract only what the diary states. Do not infer diseases or diagnoses. Do not add advice.
- One entity per distinct concept; no duplicates. If nothing clinical is present, return {"entities":[]}."""

_ID = re.compile(r"^HP:\d{7}$")


def build_messages(diary: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": diary.strip()},
    ]


def from_dataset_entities(entities: list) -> list:
    """Map dataset rows (name_colloquial/name_canonical/...) to the target schema."""
    out = []
    for e in entities:
        t = str(e.get("type", "symptom")).lower()
        t = _TYPE_MAP.get(t, t)
        if t not in TYPES:
            t = "symptom"
        out.append({
            "quote": e["name_colloquial"],
            "canonical": e["name_canonical"],
            "hpo_id": e.get("hpo_id", ""),
            "type": t,
            "negated": bool(e.get("negated", False)),
        })
    return out


def target_json(entities: list) -> str:
    return json.dumps({"entities": entities}, ensure_ascii=False, separators=(",", ":"))


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
    """Parse model output to a list of normalised entity dicts.
    Returns None if the output is not valid JSON of the expected shape."""
    obj = _extract_json(output or "")
    if not isinstance(obj, dict) or not isinstance(obj.get("entities"), list):
        return None
    res = []
    for e in obj["entities"]:
        if not isinstance(e, dict):
            continue
        hpo = str(e.get("hpo_id", "")).strip().upper()
        t = str(e.get("type", "symptom")).lower()
        t = _TYPE_MAP.get(t, t)
        res.append({
            "quote": str(e.get("quote", "")),
            "canonical": str(e.get("canonical", "")),
            "hpo_id": hpo if _ID.match(hpo) else hpo,
            "type": t if t in TYPES else "symptom",
            "negated": bool(e.get("negated", False)),
        })
    return res

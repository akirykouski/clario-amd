"""Diary entry -> grounded clinical entities (extraction v3, schemas/extraction_v3.json).

The model proposes; code decides:
  * every entity must quote a span that exists in the entry (case-insensitive), else dropped
  * an HPO ID is picked by the model from ontology candidates only (second call, enum schema); an id
    outside the candidate list becomes null. The existing ontology check (label/synonym agrees with
    the words) stays as the final gate
  * negations ("no fever", "non ho febbre") and relatives ("my mother has lupus", "mia madre ha il lupus")
    are also detected in code from the quote's left context, so a model miss cannot leak them into patterns
  * confidence is the share of n sampled answers that contain the same (term, negated) pair
    (self-consistency), or the model's own field when CLARIO_TRUST_MODEL_CONFIDENCE=1
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import Settings
from .knowledge import Ontology
from .llm import LLM, LLMError, Stats, extract_json, merge_stats
from .models import Entity
from .review import route_review

_SCHEMA_FILE = Path(__file__).parent / "schemas" / "extraction_v3.json"
EXTRACTION_SCHEMA: dict = {k: v for k, v in json.loads(_SCHEMA_FILE.read_text()).items() if k not in ("$schema", "$id")}

SYSTEM = """You read one diary entry written by a patient in everyday words (English or Italian) and list the \
clinically relevant things in it. Return JSON only:
{"entities": [{"quote": "<exact words copied from the entry>", "canonical": "<standard clinical English term>", \
"hpo_id": "<HP:0000000 code if you are sure, else null>", "type": "symptom|finding|lab|medication|trigger|body_site", \
"negated": <true if the entry says it is absent>, "family_history": <true if it belongs to a relative>, \
"onset_hint": "<date or phrase from the entry such as since Tuesday, else null>", \
"severity": <0-10 if the patient rates it, else null>, "confidence": <0-1 how sure you are, else null>}]}
Rules: quote must be copied exactly from the entry. One entity per distinct thing. Do not add anything the entry does \
not say. Do not interpret causes. Moods and weather are triggers only if the patient links them to a symptom. \
Something a mother, father, sibling or other relative has is family_history true; it is not the patient's own."""

FEW_SHOT_USER = ("Woke up with that butterfly rash on my cheeks again after gardening. Knees ache, maybe 6/10. No fever. "
                 "My mother has lupus. Tired since Tuesday.")
FEW_SHOT_ASSISTANT = ('{"entities": ['
                      '{"quote": "butterfly rash on my cheeks", "canonical": "Malar rash", "hpo_id": "HP:0025300", '
                      '"type": "symptom", "negated": false, "family_history": false, "onset_hint": null, '
                      '"severity": null, "confidence": 0.9},'
                      '{"quote": "after gardening", "canonical": "Sun exposure", "hpo_id": null, "type": "trigger", '
                      '"negated": false, "family_history": false, "onset_hint": null, "severity": null, "confidence": 0.7},'
                      '{"quote": "Knees ache", "canonical": "Knee pain", "hpo_id": "HP:0030839", "type": "symptom", '
                      '"negated": false, "family_history": false, "onset_hint": null, "severity": 6, "confidence": 0.9},'
                      '{"quote": "No fever", "canonical": "Fever", "hpo_id": "HP:0001945", "type": "symptom", '
                      '"negated": true, "family_history": false, "onset_hint": null, "severity": null, "confidence": 0.95},'
                      '{"quote": "My mother has lupus", "canonical": "Systemic lupus erythematosus", "hpo_id": null, '
                      '"type": "finding", "negated": false, "family_history": true, "onset_hint": null, '
                      '"severity": null, "confidence": 0.9},'
                      '{"quote": "Tired since Tuesday", "canonical": "Fatigue", "hpo_id": "HP:0012378", '
                      '"type": "symptom", "negated": false, "family_history": false, "onset_hint": "since Tuesday", '
                      '"severity": null, "confidence": 0.9}]}')

PICK_SYSTEM = """You map a patient's words to one term of a clinical vocabulary. You get the patient's quote, a \
clinical name, and a list of candidate terms with ids. Answer with the id of the candidate that means the same \
thing. If no candidate is a good match, answer NONE. Return JSON only: {"hpo_id": "<id or NONE>"}"""

MATCH_THRESHOLD = 0.6
PICK_K = 20
_TYPES = {"symptom", "finding", "lab", "medication", "trigger", "body_site", "bodypart"}
_NEG = re.compile(r"\b(no|not|without|never|denies|nessun[ao]?|non|senza|niente)\b[^.;,]{0,25}$", re.I)
_REL_EN = r"(?:my|his|her|their)\s+(?:mother|mom|mum|father|dad|sister|brother|grandmother|grandfather|grandma|grandpa|aunt|uncle|cousin|parents?|family)"
_REL_IT = r"(?:mia|mio|mie|miei|sua|suo)\s+(?:madre|mamma|padre|papa|papà|sorella|fratello|nonna|nonno|zia|zio|cugin[ao]|genitori|famiglia)"
_FAMILY = re.compile(rf"\b(?:{_REL_EN}|{_REL_IT})\b([^.;!?\n]{{0,30}})$", re.I)
_FAMILY_IN_QUOTE = re.compile(rf"\b(?:{_REL_EN}|{_REL_IT})\b", re.I)
_FIRST_PERSON = re.compile(r"\b(i|me|io|mi|ho)\b", re.I)


class RawEntity(BaseModel):
    quote: str = ""
    canonical: str = ""
    hpo_id: str | None = None
    type: str = "symptom"
    negated: bool = False
    family_history: bool = False
    onset_hint: str | None = None
    severity: int | float | None = None
    confidence: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _older_outputs(cls, d):
        """Outputs from before v3: `span`/`name` instead of quote/canonical, and no new fields."""
        if isinstance(d, dict):
            d = dict(d)
            if not d.get("quote") and d.get("span"):
                d["quote"] = d["span"]
            if not d.get("canonical") and d.get("name"):
                d["canonical"] = d["name"]
            if not d.get("quote") and d.get("canonical"):
                d["quote"] = d["canonical"]
            for k in ("negated", "family_history"):
                if d.get(k) is None:
                    d.pop(k, None)
            if d.get("type") is None:
                d.pop("type", None)
        return d

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if 0 <= f <= 1 else None

    @field_validator("onset_hint", mode="before")
    @classmethod
    def _onset(cls, v):
        return v.strip()[:60] or None if isinstance(v, str) else None


class RawOut(BaseModel):
    entities: list[RawEntity] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractOpts:
    sc_n: int = 5
    trust_model_confidence: bool = False
    hpo_pick: bool = True
    review_threshold: float = 0.7

    @classmethod
    def from_settings(cls, s: Settings) -> "ExtractOpts":
        return cls(s.sc_n, s.trust_model_confidence, s.hpo_pick, s.review_threshold)


def messages_for(text: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": FEW_SHOT_USER},
            {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
            {"role": "user", "content": text}]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Locate quote in text ignoring case, accents and whitespace runs. Returns (start, end) in text."""
    q = re.sub(r"\s+", " ", _fold(quote).strip(" .,;:\"'"))
    if len(q) < 2:
        return None
    folded = _fold(text)
    pattern = re.escape(q).replace(r"\ ", r"\s+")
    m = re.search(pattern, folded)
    return (m.start(), m.end()) if m else None


def is_family_history(text: str, span: tuple[int, int]) -> bool:
    """A relative is named just before the span in the same sentence ('my mother has lupus'), or inside the quote."""
    if _FAMILY_IN_QUOTE.search(text[span[0]:span[1]]):
        return True
    left = text[max(0, span[0] - 70):span[0]]
    left = re.split(r"[.;!?\n]", left)[-1]
    m = _FAMILY.search(left)
    return bool(m) and not _FIRST_PERSON.search(m.group(1))


def parse_raw(text: str | None) -> RawOut:
    return RawOut.model_validate(extract_json(text))


# ---------------------------------------------------------------- confidence
def _same(a: RawEntity, b: RawEntity) -> bool:
    if bool(a.negated) != bool(b.negated):
        return False
    if a.canonical.strip().lower() == b.canonical.strip().lower():
        return True
    return bool(a.hpo_id) and a.hpo_id == b.hpo_id


def self_consistency(primary: list[RawEntity], samples: list[RawOut], text: str) -> list[float | None]:
    """Per primary entity: share of samples that contain the same (term, negated) pair, grounded in the text."""
    if not samples:
        return [None] * len(primary)
    out: list[float | None] = []
    for p in primary:
        hits = sum(1 for s in samples
                   if any(find_quote(text, q.quote) and _same(p, q) for q in s.entities))
        out.append(round(hits / len(samples), 4))
    return out


# ---------------------------------------------------------------- grounding
def ground(entry_id: str, text: str, raw: RawOut, onto: Ontology, model: str | None, *,
           picks: dict[int, str | None] | None = None, confidences: list[float | None] | None = None,
           review_threshold: float = 0.7, trust_model_confidence: bool = False) -> list[Entity]:
    """`picks[i]`: id the model chose from the ontology candidates for raw entity i (None = NONE).
    Entities with a pick skip the free-form HPO proposal entirely."""
    out: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    for i, r in enumerate(raw.entities):
        span = find_quote(text, r.quote)
        if not span or not r.canonical.strip():
            continue
        quote = text[span[0]:span[1]]
        etype = "body_site" if r.type == "bodypart" else (r.type if r.type in _TYPES else "symptom")
        flags: list[str] = []
        hpo_id, hpo_label = None, None
        if picks is not None and i in picks:
            hpo_id, hpo_label, flags = checked_pick(picks[i], quote, r.canonical, onto)
        elif etype in ("symptom", "finding", "lab", "body_site"):
            hpo_id, hpo_label, flags = resolve_hpo(r.hpo_id, quote, r.canonical, onto)
        negated = bool(r.negated) or bool(_NEG.search(text[max(0, span[0] - 30):span[0]]))
        if bool(r.negated) != negated:
            flags.append("negation_from_text")
        family = bool(r.family_history) or is_family_history(text, span)
        if bool(r.family_history) != family:
            flags.append("family_history_from_text")
        sev = r.severity
        sev = int(round(sev)) if isinstance(sev, (int, float)) and 0 <= sev <= 10 else None
        conf = r.confidence if trust_model_confidence and r.confidence is not None else (
            confidences[i] if confidences and i < len(confidences) else None)
        key = (hpo_id or r.canonical.lower(), quote.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(Entity(id=f"ent_{uuid.uuid4().hex[:10]}", entry_id=entry_id, type=etype, quote=quote,
                          canonical=r.canonical.strip()[:120], hpo_id=hpo_id, hpo_label=hpo_label,
                          negated=negated, family_history=family, onset_hint=r.onset_hint, severity=sev,
                          confidence=conf, review=route_review(conf, review_threshold),
                          flags=flags, model=model))
    return out


def checked_pick(picked: str | None, quote: str, canonical: str, onto: Ontology) -> tuple[str | None, str | None, list[str]]:
    """A pick from the candidate list still has to agree with the words (final ontology check); no fallback match."""
    if not picked:
        return None, None, ["no_hpo"]
    hid, label, flags = resolve_hpo(picked, quote, canonical, onto)
    if hid != picked:
        return None, None, ["hpo_dropped"]
    return hid, label, flags


def resolve_hpo(proposed: str | None, quote: str, canonical: str, onto: Ontology) -> tuple[str | None, str | None, list[str]]:
    """Keep the model's HPO id only if the ontology agrees with the words; else try our own match."""
    flags: list[str] = []
    pid = (proposed or "").strip().upper()
    if pid and re.fullmatch(r"HP:\d{7}", pid) and onto.exists(pid):
        names = [_fold(n) for n in [onto.label(pid) or "", *onto.synonyms(pid)]]
        for phrase in (canonical, quote):
            m = onto.best_match(phrase)
            if m and (m[0].hpo_id == pid or pid in onto.ancestors(m[0].hpo_id) or m[0].hpo_id in onto.ancestors(pid)):
                return pid, onto.label(pid), flags
            if _fold(phrase).strip() in names:
                return pid, onto.label(pid), flags
        flags.append("hpo_dropped")
    elif pid:
        flags.append("hpo_invalid")
    m = onto.best_match(canonical) or onto.best_match(quote)
    if m and m[1] >= MATCH_THRESHOLD:
        flags.append("hpo_from_ontology")
        return m[0].hpo_id, m[0].label, flags
    flags.append("no_hpo")
    return None, None, flags


# ---------------------------------------------------------------- model calls
def pick_schema(ids: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["hpo_id"],
            "properties": {"hpo_id": {"enum": [*ids, "NONE"]}}}


async def pick_hpo(llm: LLM, onto: Ontology, quote: str, canonical: str, proposed: str | None) -> tuple[str | None, Stats]:
    """Ask the model to choose among ontology candidates. The answer must be one of them, else None."""
    cands = onto.search(f"{canonical} {quote}", PICK_K)
    ids = [c.hpo_id for c in cands]
    payload = {"quote": quote, "canonical": canonical, "proposed": proposed,
               "candidates": [{"id": c.hpo_id, "label": c.label} for c in cands]}
    msgs = [{"role": "system", "content": PICK_SYSTEM},
            {"role": "user", "content": json.dumps({"quote": quote, "canonical": canonical,
                                                    "candidates": payload["candidates"]}, ensure_ascii=False)}]
    texts, st = await llm.samples("hpo_pick", msgs, 1, temperature=0.0, schema=pick_schema(ids), payload=payload)
    try:
        got = str(extract_json(texts[0]).get("hpo_id", "")).strip().upper()
    except (ValueError, AttributeError):
        got = ""
    return (got if got in ids else None), st


async def _primary(llm: LLM, msgs: list[dict], text: str) -> tuple[RawOut, Stats]:
    err: Exception | None = None
    for _ in range(2):
        texts, st = await llm.samples("extract", msgs, 1, temperature=0.1, schema=EXTRACTION_SCHEMA, payload={"text": text})
        try:
            return parse_raw(texts[0]), st
        except Exception as e:  # noqa: BLE001 - ValueError or pydantic ValidationError
            err = e
            msgs = msgs + [{"role": "assistant", "content": (texts[0] or "")[:2000]},
                           {"role": "user", "content": "Reply again with ONLY the JSON object for the schema. No prose."}]
    raise LLMError(f"invalid JSON after retry: {err}")


async def extract(llm: LLM, entry_id: str, text: str, onto: Ontology,
                  opts: ExtractOpts | None = None) -> tuple[list[Entity], Stats]:
    opts = opts or ExtractOpts()
    msgs = messages_for(text)
    raw, st = await _primary(llm, msgs, text)
    # drop ungrounded entities up front so the later calls only spend tokens on real ones
    raw = RawOut(entities=[r for r in raw.entities if find_quote(text, r.quote) and r.canonical.strip()])

    confidences: list[float | None] = [None] * len(raw.entities)
    need_sc = opts.sc_n > 1 and raw.entities and not (
        opts.trust_model_confidence and all(r.confidence is not None for r in raw.entities))
    if need_sc:
        texts, st2 = await llm.samples("extract", msgs, opts.sc_n, temperature=0.7, schema=EXTRACTION_SCHEMA,
                                       payload={"text": text})
        st = merge_stats(st, st2)
        parsed: list[RawOut] = []
        for t in texts:
            try:
                parsed.append(parse_raw(t))
            except Exception:  # noqa: BLE001 - an unparsable sample counts as a miss
                parsed.append(RawOut())
        confidences = self_consistency(raw.entities, parsed, text)

    picks: dict[int, str | None] | None = None
    if opts.hpo_pick:
        idx = [i for i, r in enumerate(raw.entities) if (r.type if r.type in _TYPES else "symptom") in ("symptom", "finding")]
        results = await asyncio.gather(*[pick_hpo(llm, onto, raw.entities[i].quote, raw.entities[i].canonical,
                                                  raw.entities[i].hpo_id) for i in idx])
        picks = {}
        for i, (hid, st3) in zip(idx, results):
            picks[i] = hid
            st = merge_stats(st, st3)
    ents = ground(entry_id, text, raw, onto, st.model, picks=picks, confidences=confidences,
                  review_threshold=opts.review_threshold, trust_model_confidence=opts.trust_model_confidence)
    return ents, st

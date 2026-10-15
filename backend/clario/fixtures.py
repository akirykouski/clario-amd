"""Deterministic offline model (CLARIO_OFFLINE=1). Used by tests and offline demos only.

Follows simple, inspectable rules so the guardrails around it can be tested.
"""

from __future__ import annotations

import json
import re

from .llm import LLM, Stats

PHRASES = [
    ("tired", "Fatigue", "HP:0012378"), ("exhausted", "Fatigue", "HP:0012378"),
    ("joints in my fingers ache", "Arthralgia", "HP:0002829"), ("knees ache", "Arthralgia", "HP:0002829"),
    ("knees and wrists ache", "Arthralgia", "HP:0002829"),
    ("stiff for about an hour", "Morning stiffness", "HP:0005197"),
    ("butterfly shape", "Malar rash", "HP:0025300"), ("rash on my cheeks", "Malar rash", "HP:0025300"),
    ("sore in my mouth", "Oral ulcer", "HP:0000155"), ("mouth sore", "Oral ulcer", "HP:0000155"),
    ("turned white and then blue in the cold", "Raynaud phenomenon", "HP:0030880"),
    ("fingers went white", "Raynaud phenomenon", "HP:0030880"),
    ("hair than usual in the shower", "Alopecia", "HP:0001596"), ("hair still falling out", "Alopecia", "HP:0001596"),
    ("chest hurts when i take a deep breath", "Pleuritic chest pain", "HP:0033771"),
    ("low fever", "Fever", "HP:0001945"), ("no fever", "Fever", "HP:0001945"),
    ("wrists swollen", "Joint swelling", "HP:0001386"), ("stiff and swollen", "Joint swelling", "HP:0001386"),
    ("protein in my urine", "Proteinuria", "HP:0000093"), ("white cells are a bit low", "Leukopenia", "HP:0001882"),
    ("ankles a little puffy", "Edema of the lower limbs", "HP:0010741"), ("headache", "Headache", "HP:0002315"),
    ("after a sunny afternoon", "Sun exposure", None),
]


HEDGE = re.compile(r"\b(maybe|perhaps|i think|not sure|forse|mi sembra)\b")


def _stats(tokens: int = 60) -> Stats:
    return Stats("offline-fixtures", "offline-fixture-v1", 5.0, tokens, None)


class OfflineLLM(LLM):
    backend = "offline-fixtures"
    model = "offline-fixture-v1"

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        payload = payload or {}
        if task == "extract":
            return json.dumps(self._extract(payload["text"])), _stats()
        if task == "hpo_pick":
            ids = {c["id"] for c in payload.get("candidates", [])}
            return json.dumps({"hpo_id": payload.get("proposed") if payload.get("proposed") in ids else "NONE"}), _stats(8)
        if task == "rationale":
            feats = ", ".join(payload.get("overlapping_features", [])[:3]).lower()
            return json.dumps({"rationale": f"What you recorded ({feats}) resembles some typical features of "
                                            f"{payload.get('condition')}. It may be worth discussing with your doctor."}), _stats()
        if task == "document":
            return json.dumps(self._document(payload)), _stats(200)
        if task == "next_question":
            lay = payload.get("plain_description", "")
            return json.dumps({"question": f"Le capita di avere: {lay}?" if payload.get("lang") == "it"
                               else f"Do you sometimes have: {lay}?"}), _stats(20)
        if task == "brief":
            return json.dumps(self._brief(payload)), _stats(300)
        return "{}", _stats()

    async def samples(self, task, messages, n, *, temperature=0.7, schema=None, payload=None):
        """n deterministic samples. In extraction, a phrase in a hedged sentence ("maybe", "forse") shows up only in
        every other sample, so self-consistency confidence is below 1 and the review queue can be exercised offline."""
        if task != "extract":
            return await super().samples(task, messages, n, temperature=temperature, schema=schema, payload=payload)
        outs = [json.dumps(self._extract(payload["text"], i)) for i in range(max(1, n))]
        return outs, _stats(60 * len(outs))

    @staticmethod
    def _extract(text: str, sample: int = 0) -> dict:
        low = text.lower()
        ents = []
        for phrase, canonical, hpo in PHRASES:
            i = low.find(phrase)
            if i < 0:
                continue
            if sample % 2 and HEDGE.search(re.split(r"[.!?\n]", low[:i])[-1] + low[i:].split(".")[0]):
                continue
            quote = text[i:i + len(phrase)]
            sev = re.search(r"(\d+)/10", text)
            ents.append({"quote": quote, "canonical": canonical, "hpo_id": hpo,
                         "type": "trigger" if hpo is None else "symptom", "negated": phrase.startswith("no "),
                         "severity": int(sev.group(1)) if sev and canonical == "Arthralgia" else None})
        return {"entities": ents}

    @staticmethod
    def _document(payload: dict) -> dict:
        """Offline "reading" of a page: replays the truth sidecar embedded in generated PDFs (no OCR, no model).

        Fixed confidences: every 6th row is 0.55 (below the default review threshold), the rest 0.93.
        """
        off = payload.get("offline")
        if not off:
            return {"date": None, "rows": []}
        rows = []
        for i, t in enumerate(off["rows"]):
            rows.append({"test_name": t["test_name"], "value_numeric": t["value_numeric"], "value_text": t["value_text"],
                         "unit": t["unit"], "ref_low": t["ref_low"], "ref_high": t["ref_high"], "flag": t["flag"],
                         "confidence": 0.55 if i % 6 == 5 else 0.93})
        return {"date": off["date"], "rows": rows}

    @staticmethod
    def _brief(payload: dict) -> dict:
        entries = payload["entries"]
        ids = [e["id"] for e in entries]
        first, last = entries[0], entries[-1]
        return {"items": [
            {"section": "summary", "text": f"{len(entries)} diary entries from {first['date']} to {last['date']}; "
                                           "recurring joint pain, fatigue and a facial rash after sun.", "cites": ids[:3]},
            {"section": "timeline", "text": f"{first['date']}: fatigue first noted.", "cites": [ids[0]]},
            {"section": "patterns", "text": "The recorded features may resemble an autoimmune pattern worth considering.",
             "cites": ids[:2]},
            {"section": "patterns", "text": "You have lupus. Start 200 mg hydroxychloroquine.", "cites": ids[:1]},
            {"section": "timeline", "text": "Uncited claim that must be dropped.", "cites": ["not-an-entry"]},
            {"section": "questions", "text": "Ask whether the rash appears only after sun exposure.", "cites": []},
        ]}

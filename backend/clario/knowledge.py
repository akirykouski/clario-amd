"""HPO ontology + rare-disease annotations: lookup, lexical search, Resnik-style similarity."""
from __future__ import annotations

import bisect
import gzip
import heapq
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from clario.models import Term

DEFAULT_PATH = Path(__file__).parent / "data" / "knowledge.json.gz"
# Optional: verified everyday English phrasings per term (train/lay_expand.py). Search only, never shown as synonyms.
LAY_LEXICON_PATH = Path(__file__).parent / "data" / "lay_lexicon_en.json"
ROOT = "HP:0000118"
CAND_IC = 1.2  # ancestors below this IC carry no signal and are skipped when pruning
STOP = {"a", "an", "the", "of", "and", "or", "in", "on", "my", "i", "is", "are", "to", "with",
        "have", "has", "been", "very", "really", "some", "it", "me", "feel", "feeling", "got"}


@dataclass
class Disease:
    id: str
    name: str
    phenotypes: dict[str, float] = field(default_factory=dict)
    n_freq: int | None = None  # annotations backed by a real frequency (None: older knowledge files do not say)


def fold(s: str) -> str:
    """Lower-case and strip accents ("Perché" -> "perche")."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(s)).strip()


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _tokens(s: str) -> list[str]:
    return [_stem(w) for w in _norm(s).split() if w not in STOP]


def _hid(n: int) -> str:
    return f"HP:{n:07d}"


class Ontology:
    n_terms: int
    n_diseases: int

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Ontology":
        return _load(str(Path(path) if path else DEFAULT_PATH))

    def __init__(self, raw: dict, search_extra: dict[str, list[str]] | None = None) -> None:
        self._search_extra = search_extra or {}
        self._label: dict[str, str] = {}
        self._syn: dict[str, list[str]] = {}
        self._parents: dict[str, list[str]] = {}
        self._ic: dict[str, float] = {}
        for n, label, syn, par, ic in raw["terms"]:
            i = _hid(n)
            self._label[i] = label
            self._syn[i] = syn
            self._parents[i] = [_hid(p) for p in par]
            self._ic[i] = ic
        self._diseases: dict[str, Disease] = {}
        self._direct: dict[str, list[tuple[Disease, float]]] = defaultdict(list)
        for did, name, ph, *rest in raw["diseases"]:
            d = Disease(did, name, {_hid(t): w for t, w in ph}, rest[0] if rest else None)
            self._diseases[did] = d
            for t, w in d.phenotypes.items():
                self._direct[t].append((d, w))
        self.n_terms = len(self._label)
        self.n_diseases = len(self._diseases)
        self._anc: dict[str, frozenset[str]] = {}
        self._children: dict[str, list[str]] = defaultdict(list)
        for t, ps in self._parents.items():
            for p in ps:
                self._children[p].append(t)
        self._desc: dict[str, frozenset[str]] = {}
        self._top = frozenset(self._children.get(ROOT, ()))
        self._build_search()

    # ---- lookup -------------------------------------------------------
    def term(self, hpo_id: str) -> Term | None:
        l = self._label.get(hpo_id)
        return Term(hpo_id=hpo_id, label=l) if l is not None else None

    def exists(self, hpo_id: str) -> bool:
        return hpo_id in self._label

    def label(self, hpo_id: str) -> str | None:
        return self._label.get(hpo_id)

    def synonyms(self, hpo_id: str) -> list[str]:
        return list(self._syn.get(hpo_id, []))

    def ic(self, hpo_id: str) -> float:
        return self._ic.get(hpo_id, 0.0)

    def ancestors(self, hpo_id: str) -> frozenset[str]:
        """Shared and cached, never copied: safe in hot loops, immutable for callers."""
        return self._ancestors(hpo_id)

    def descendants(self, hpo_id: str) -> frozenset[str]:
        """The term itself and everything below it (shared, cached)."""
        return self._descendants(hpo_id)

    def systems(self, hpo_id: str) -> frozenset[str]:
        """Top-level organ systems (direct children of Phenotypic abnormality) a term belongs to."""
        return ({hpo_id} | self._ancestors(hpo_id)) & self._top

    def _ancestors(self, t: str) -> frozenset[str]:
        a = self._anc.get(t)
        if a is None:
            s: set[str] = set()
            for p in self._parents.get(t, ()):
                s.add(p)
                s |= self._ancestors(p)
            a = self._anc[t] = frozenset(s)
        return a

    def _descendants(self, t: str) -> frozenset[str]:
        d = self._desc.get(t)
        if d is None:
            s = {t}
            for c in self._children.get(t, ()):
                s |= self._descendants(c)
            d = self._desc[t] = frozenset(s)
        return d

    # ---- search -------------------------------------------------------
    def _build_search(self) -> None:
        self._exact: dict[str, list[tuple[str, bool]]] = defaultdict(list)  # phrase -> (id, is_label)
        self._tok: dict[str, set[int]] = defaultdict(set)
        self._phr: list[tuple[str, str, bool, frozenset[str]]] = []
        for t, label in self._label.items():
            for k, ph in enumerate([label, *self._syn[t], *self._search_extra.get(t, ())]):
                n = _norm(ph)
                if not n:
                    continue
                toks = frozenset(_tokens(ph))
                idx = len(self._phr)
                self._phr.append((n, t, k == 0, toks))
                self._exact[n].append((t, k == 0))
                for w in toks:
                    self._tok[w].add(idx)
        self._sorted = sorted(range(len(self._phr)), key=lambda i: self._phr[i][0])
        self._sorted_keys = [self._phr[i][0] for i in self._sorted]
        n = len(self._phr)
        self._idf = {w: math.log(1 + n / len(s)) for w, s in self._tok.items()}

    def _score_candidates(self, text: str) -> dict[str, float]:
        """term id -> score 0..1 (best phrase)."""
        q = _norm(text)
        qt = frozenset(_tokens(text))
        best: dict[str, float] = {}

        def put(t: str, s: float) -> None:
            if s > best.get(t, 0.0):
                best[t] = s

        for t, is_label in self._exact.get(q, ()):
            put(t, 1.0 if is_label else 0.98)
        if q:
            lo = bisect.bisect_left(self._sorted_keys, q)
            for j in range(lo, min(lo + 400, len(self._sorted))):
                ph = self._phr[self._sorted[j]]
                if not ph[0].startswith(q):
                    break
                put(ph[1], 0.85 * (0.5 + 0.5 * len(q) / len(ph[0])))
        if qt:
            cand: dict[int, float] = defaultdict(float)
            for w in qt:
                for i in self._tok.get(w, ()):
                    cand[i] += self._idf[w]
            qw = sum(self._idf.get(w, 1.0) for w in qt)
            for i, ov in cand.items():
                ph = self._phr[i]
                pw = sum(self._idf[w] for w in ph[3]) or 1.0
                prec, rec = ov / pw, ov / qw
                f = 2 * prec * rec / (prec + rec)
                put(ph[1], 0.8 * f + (0.02 if ph[2] else 0.0))
        return best

    def search(self, q: str, k: int = 10) -> list[Term]:
        best = self._score_candidates(q)
        top = heapq.nlargest(k, best.items(), key=lambda kv: (kv[1], self._ic.get(kv[0], 0)))
        return [Term(hpo_id=t, label=self._label[t]) for t, _ in top]

    def search_scored(self, q: str, k: int = 10) -> list[tuple[Term, float]]:
        """Like `search`, with the match score (1.0 exact label, lower for partial word overlap)."""
        best = self._score_candidates(q)
        top = heapq.nlargest(k, best.items(), key=lambda kv: (kv[1], self._ic.get(kv[0], 0)))
        return [(Term(hpo_id=t, label=self._label[t]), round(s, 4)) for t, s in top]

    def best_match(self, text: str) -> tuple[Term, float] | None:
        best = self._score_candidates(text)
        if not best:
            return None
        t, s = max(best.items(), key=lambda kv: (kv[1], self._ic.get(kv[0], 0)))
        return Term(hpo_id=t, label=self._label[t]), round(min(1.0, s), 4)

    # ---- diseases / similarity ---------------------------------------
    def diseases(self) -> Iterable[Disease]:
        return self._diseases.values()

    def disease(self, disease_id: str) -> Disease | None:
        return self._diseases.get(disease_id)

    def similarity(self, patient_hpo: set[str], disease: Disease) -> tuple[float, list[tuple[str, str, float]]]:
        pts = [p for p in patient_hpo if p in self._label]
        denom = sum(self._ic[p] for p in pts)
        if not pts or denom <= 0:
            return 0.0, []
        tot, out = 0.0, []
        for p in pts:
            ap = self._ancestors(p) | {p}
            bv, bq = 0.0, None
            for q, w in disease.phenotypes.items():
                common = ap & (self._ancestors(q) | {q})
                if not common:
                    continue
                v = max(self._ic[c] for c in common) * w
                if v > bv:
                    bv, bq = v, q
            if bq:
                tot += bv
                out.append((p, bq, bv))
        return min(1.0, tot / denom), out

    @lru_cache(maxsize=2048)  # noqa: B019 - the Ontology is a process-wide singleton (see _load)
    def _mica_map(self, p: str) -> dict[str, float]:
        """disease-term q (descendant-or-self of an informative ancestor of p) -> IC of MICA(p, q)."""
        m: dict[str, float] = {}
        for a in sorted(self._ancestors(p) | {p}, key=lambda x: (self._ic[x], x)):
            ia = self._ic[a]
            if ia < CAND_IC and a != p:
                continue
            for q in self._descendants(a):
                m[q] = ia  # ascending IC order, later (higher) overwrites
        return m

    def top_diseases(self, patient_hpo: set[str], k: int = 10) -> list[tuple[Disease, float, list]]:
        pts = sorted(p for p in patient_hpo if p in self._label)  # sorted: float sums and ties must not follow set order
        denom = sum(self._ic[p] for p in pts)
        if not pts or denom <= 0:
            return []
        best: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)  # disease -> p -> (v, q)
        for p in pts:
            mica = self._mica_map(p)
            for q in sorted(mica):
                ia = mica[q]
                for d, w in self._direct.get(q, ()):
                    v = ia * w
                    cur = best[d.id].get(p)
                    if cur is None or v > cur[0]:
                        best[d.id][p] = (v, q)
        scored = []
        for did, pm in best.items():
            s = sum(v for _, (v, _q) in sorted(pm.items())) / denom
            scored.append((s, did))
        top = heapq.nlargest(k, scored)
        res = []
        for s, did in top:
            matches = [(p, q, v) for p, (v, q) in sorted(best[did].items())]
            matches.sort(key=lambda x: (-x[2], x[0]))
            res.append((self._diseases[did], min(1.0, s), matches))
        return res


@lru_cache(maxsize=4)
def _load(path: str) -> Ontology:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    extra = json.loads(LAY_LEXICON_PATH.read_text(encoding="utf-8")) if LAY_LEXICON_PATH.exists() else None
    return Ontology(raw, extra)

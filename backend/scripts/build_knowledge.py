"""Build clario/data/knowledge.json.gz from hp.json and phenotype.hpoa."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
from collections import defaultdict

ROOT = "HP:0000118"
FREQ = {"HP:0040280": 1.0, "HP:0040281": 0.9, "HP:0040282": 0.55,
        "HP:0040283": 0.17, "HP:0040284": 0.03}
EXCLUDED = "HP:0040285"


def hid(iri: str) -> str | None:
    m = re.search(r"HP_(\d{7})$", iri)
    return f"HP:{m.group(1)}" if m else None


DEFAULT_FREQ = 0.5  # annotation without any frequency: "occasional-like" prior, never certainty


def freq_weight(f: str) -> float | None:
    """P(feature | disease) from one phenotype.hpoa frequency cell, or None for an excluded feature.

    Only an explicit "Obligate" term (HP:0040280) or "100%" means 1.0. A case-report ratio n/d is evidence about d
    patients, so it is shrunk toward the 0.5 prior with a Laplace estimate (n+1)/(d+2): 1/1 -> 0.67, 4/4 -> 0.83,
    20/20 -> 0.95, 0/3 -> 0.2. Before this, every 1/1 case report (about 20,000 annotations, e.g. 51 of 58 features of
    OMIM:621369) was stored as 1.0 and read as "every patient has it", which inflated scores, the next-question
    pick and the strength of a "no" answer. A blank cell is the DEFAULT_FREQ prior.
    """
    f = f.strip()
    if not f:
        return DEFAULT_FREQ
    if f == EXCLUDED:
        return None
    if f in FREQ:
        return FREQ[f]
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", f)
    if m:
        n, d = int(m.group(1)), int(m.group(2))
        return (min(n, d) + 1) / (d + 2) if d else DEFAULT_FREQ
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", f)
    if m:
        return min(1.0, float(m.group(1)) / 100)
    return DEFAULT_FREQ


INFORMATIVE_MIN_D = 10  # a n/d ratio from fewer patients is a case report, not a frequency


def freq_informative(f: str) -> bool:
    """True when the cell really measures how often a feature occurs (a frequency term, a percentage, a cohort ratio)."""
    f = f.strip()
    if not f or f == EXCLUDED:
        return False
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", f)
    return int(m.group(2)) >= INFORMATIVE_MIN_D if m else True


def load_hpo(path: str):
    g = json.load(open(path))["graphs"][0]
    nodes, parents = {}, defaultdict(set)
    for n in g["nodes"]:
        i = hid(n["id"])
        if not i or n.get("type") != "CLASS" or "lbl" not in n:
            continue
        meta = n.get("meta", {})
        if meta.get("deprecated"):
            continue
        syns = []
        for s in meta.get("synonyms", []):
            if s.get("pred") in ("hasExactSynonym", "hasRelatedSynonym"):
                v = s["val"]
                if v not in syns and v != n["lbl"]:
                    syns.append(v)
        nodes[i] = {"label": n["lbl"], "syn": syns}
    for e in g["edges"]:
        if e["pred"] != "is_a":
            continue
        s, o = hid(e["sub"]), hid(e["obj"])
        if s in nodes and o in nodes:
            parents[s].add(o)
    # keep subtree of ROOT
    children = defaultdict(set)
    for s, ps in parents.items():
        for p in ps:
            children[p].add(s)
    keep, stack = {ROOT}, [ROOT]
    while stack:
        for c in children[stack.pop()]:
            if c not in keep:
                keep.add(c)
                stack.append(c)
    return {i: nodes[i] for i in keep}, {i: sorted(p for p in parents[i] if p in keep) for i in keep}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hpo", required=True)
    ap.add_argument("--hpoa", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    nodes, parents = load_hpo(a.hpo)
    anc_cache: dict[str, frozenset] = {}

    def anc(t: str) -> frozenset:
        if t in anc_cache:
            return anc_cache[t]
        s = set()
        for p in parents[t]:
            s.add(p)
            s |= anc(p)
        anc_cache[t] = frozenset(s)
        return anc_cache[t]

    import sys
    sys.setrecursionlimit(10000)

    dis: dict[str, dict] = {}
    with open(a.hpoa, newline="") as fh:
        lines = (l for l in fh if not l.startswith("#"))
        for r in csv.DictReader(lines, delimiter="\t"):
            d = r["database_id"]
            if not (d.startswith("ORPHA:") or d.startswith("OMIM:")):
                continue
            if r["aspect"] != "P" or r["qualifier"].strip() == "NOT":
                continue
            t = r["hpo_id"]
            if t not in nodes:
                continue
            w = freq_weight(r["frequency"])
            if w is None:
                continue
            e = dis.setdefault(d, {"id": d, "name": r["disease_name"], "p": {}, "fi": set()})
            if freq_informative(r["frequency"]):
                e["fi"].add(t)
            if w > e["p"].get(t, -1):
                e["p"][t] = w

    n_dis = len(dis)
    count: dict[str, int] = defaultdict(int)
    for e in dis.values():
        cl = set(e["p"])
        for t in list(cl):
            cl |= anc(t)
        for t in cl:
            count[t] += 1
    ic = {t: -math.log(count[t] / n_dis) for t in nodes if count.get(t)}
    mx = max(ic.values())
    for t in nodes:
        ic.setdefault(t, mx)

    n = lambda i: int(i[3:])
    out = {
        "terms": [[n(t), v["label"], v["syn"], [n(p) for p in parents[t]], round(ic[t], 3)]
                  for t, v in sorted(nodes.items())],
        "diseases": [[e["id"], e["name"], [[n(t), round(w, 3)] for t, w in sorted(e["p"].items())],
                     len(e["fi"])]  # 4th field: annotations with a real frequency behind the weight
                     for e in dis.values() if e["p"]],
    }
    with gzip.open(a.out, "wt", compresslevel=9) as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"terms={len(out['terms'])} diseases={len(out['diseases'])}")


if __name__ == "__main__":
    main()

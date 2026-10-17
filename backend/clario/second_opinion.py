"""Second opinion: the patient takes the diary to another doctor.

Every package is split in code into facts and conclusions:
- facts (every view): the diary, quotes, timeline, labs, `tried` (treatment, duration, effect) and `tested` (test, result);
- conclusions (`SharePackage.previous`): the previous doctor's diagnosis, accepted and rejected lines, conditions to
  consider and notes. They leave the device only in a second-opinion package, and the clinic server strips them from
  every view, the brief model's input and the differential (`facts_only`) until the new doctor has finalized the brief.
  Then `compare` lays both opinions side by side and marks where they differ. Nothing here calls a model.
"""

from __future__ import annotations

from .knowledge import Ontology, fold
from .models import Brief, Condition, PriorCondition, PriorOpinion, SharePackage
from .patterns import base_name
from .share import patient_mentions
from .i18n import term_label


def facts_only(pkg: SharePackage) -> SharePackage:
    """The package without the previous doctor's conclusions: what every clinic view, model call and ranking reads."""
    return pkg.model_copy(update={"previous": None}) if pkg.previous is not None else pkg


def _same(a_name: str, a_id: str | None, b_name: str, b_id: str | None) -> bool:
    if a_id and b_id:
        return a_id == b_id
    return fold(base_name(a_name)).strip() == fold(base_name(b_name)).strip()


def since_previous(pkg: SharePackage, prev_date: str | None, onto: Ontology, lang: str) -> list[str]:
    """Terms first recorded after the previous opinion was given (the previous doctor could not have seen them), plus
    tests done after it with an abnormal result. Oldest first."""
    if not prev_date:
        return []
    first: dict[str, tuple[str, str]] = {}
    for x in patient_mentions(pkg.entities):
        k = x.hpo_id or x.canonical.lower()
        if k not in first or x.occurred_on < first[k][0]:
            label = term_label(x.hpo_id, onto.label(x.hpo_id) or x.canonical, lang) if x.hpo_id else term_label(None, x.canonical, lang)
            first[k] = (x.occurred_on, label)
    out = sorted(v for v in first.values() if v[0] > prev_date)
    out += sorted((t.date or "", f"{t.test}: {t.result}") for t in pkg.tested if t.abnormal and (t.date or "") > prev_date)
    return [label for _, label in out]


def compare(previous: PriorOpinion, conditions: list[Condition], brief: Brief, since: list[str]) -> dict:
    """Both opinions side by side. `rows` has one line per condition named on either side: `previous` is `diagnosis`,
    `considered` or null, `current_rank` the rank in this doctor's conditions to consider (computed in code from the
    facts) or null; `agree` is true when both sides name it. The second doctor's lines are the signed brief's AI lines as
    they kept, edited or removed them, plus the lines they wrote themselves."""
    prev: list[tuple[PriorCondition, str]] = [(c, "diagnosis") for c in previous.diagnosis]
    prev += [(c, "considered") for c in previous.conditions
             if not any(_same(c.name, c.disease_id, d.name, d.disease_id) for d in previous.diagnosis)]
    rows, used = [], set()
    for c, role in prev:
        hit = next((x for x in conditions if _same(c.name, c.disease_id, x.name, x.disease_id)), None)
        if hit:
            used.add(hit.disease_id)
        rows.append({"name": c.name, "disease_id": c.disease_id or (hit.disease_id if hit else None), "previous": role,
                     "current_rank": hit.rank if hit else None, "agree": hit is not None})
    for x in conditions:
        if x.disease_id not in used:
            rows.append({"name": x.name, "disease_id": x.disease_id, "previous": None, "current_rank": x.rank, "agree": False})
    ai = [i for i in brief.items if i.origin in ("ai", "clinician")]
    return {
        "previous": previous.model_dump(),
        "current": {"conditions": [{"disease_id": c.disease_id, "name": c.name, "rank": c.rank, "signal": c.signal}
                                   for c in conditions],
                    "accepted": [i.text for i in ai if i.review in ("accepted", "edited")],
                    "rejected": [i.text for i in ai if i.review == "rejected"],
                    "finalized_at": brief.finalized_at},
        "rows": rows,
        "disagreements": sum(1 for r in rows if not r["agree"]),
        "since_previous": since,
    }

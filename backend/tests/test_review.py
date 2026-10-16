from conftest import confirm_all, wait_extracted
from clario.brief import LOW_CONFIDENCE, patient_items
from clario.models import Entry, SharedEntity, SharePackage
from clario.review import register_review_kind
from clario.share import build_package


def queue(c):
    return c.get("/api/review").json()


def add_hedged_entry(c):
    c.post("/api/entries", json={"text": "Maybe my knees ache a bit. So tired. Mouth sore again.", "occurred_on": "2026-09-01"})
    return wait_extracted(c)[0]["entities"]


def test_threshold_routes_unsure_entities_to_the_queue(unlocked):
    ents = {e["canonical"]: e for e in add_hedged_entry(unlocked)}
    assert ents["Arthralgia"]["review"] == "needs_review" and ents["Arthralgia"]["confidence"] == 0.6
    assert ents["Fatigue"]["review"] == "auto" and ents["Fatigue"]["confidence"] == 1.0
    q = queue(unlocked)
    assert q["count"] == 1
    item = q["items"][0]
    assert item["kind"] == "entity" and item["id"] == ents["Arthralgia"]["id"] and item["confidence"] == 0.6
    assert item["display"] == "Arthralgia" and item["value"] == "HP:0002829"
    assert "knees ache" in item["source_excerpt"].lower() and item["entry_id"]


def test_needs_review_counts_and_stays_flagged_until_a_person_decides(unlocked):
    add_hedged_entry(unlocked)
    labels = {t["clinical"] for t in unlocked.get("/api/timeline").json()["terms"]}
    assert "Arthralgia" in labels and "Fatigue" in labels  # nobody has to confirm anything for terms to count
    item = queue(unlocked)["items"][0]
    r = unlocked.post(f"/api/review/entity/{item['id']}", json={"action": "confirm"}).json()
    assert r == {"ok": True, "count": 0}
    assert "Arthralgia" in {t["clinical"] for t in unlocked.get("/api/timeline").json()["terms"]}
    assert queue(unlocked)["count"] == 0


def test_reject_removes_the_term_from_patterns(unlocked):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    before = unlocked.get("/api/patterns").json()
    ents = [x for e in unlocked.get("/api/entries").json() for x in e["entities"] if x["canonical"] == "Malar rash"]
    assert ents
    for x in ents:
        assert unlocked.post(f"/api/review/entity/{x['id']}", json={"action": "reject"}).status_code == 200
    after = unlocked.get("/api/patterns").json()
    assert after["confirmed_terms"] == before["confirmed_terms"] - 1
    assert "Malar rash" not in {t["clinical"] for t in unlocked.get("/api/timeline").json()["terms"]}


def test_correct_writes_correction_log_and_updates_the_term(unlocked):
    add_hedged_entry(unlocked)
    item = queue(unlocked)["items"][0]
    bad = unlocked.post(f"/api/review/entity/{item['id']}", json={"action": "correct", "value": "HP:9999999"})
    assert bad.status_code == 422
    assert unlocked.post(f"/api/review/entity/{item['id']}", json={"action": "correct"}).status_code == 422
    assert unlocked.post(f"/api/review/entity/{item['id']}", json={"action": "delete"}).status_code == 422
    assert unlocked.post("/api/review/entity/ent_nope", json={"action": "confirm"}).status_code == 404
    assert unlocked.post(f"/api/review/lab/{item['id']}", json={"action": "confirm"}).status_code == 404
    assert unlocked.app.state.vault.all("correction_log") == []  # failed attempts log nothing
    r = unlocked.post(f"/api/review/entity/{item['id']}", json={"action": "correct", "value": "HP:0001386"})
    assert r.status_code == 200
    x = next(x for x in unlocked.get("/api/entries").json()[0]["entities"] if x["id"] == item["id"])
    assert x["review"] == "corrected" and x["hpo_id"] == "HP:0001386" and "fixed_by_patient" in x["flags"]
    logs = unlocked.app.state.vault.all("correction_log")
    assert len(logs) == 1
    log = logs[0]
    assert log["kind"] == "entity" and log["item_id"] == item["id"] and log["action"] == "correct" and log["ts"]
    assert log["before"]["hpo_id"] == "HP:0002829" and log["before"]["review"] == "needs_review"
    assert log["after"]["hpo_id"] == "HP:0001386" and log["after"]["review"] == "corrected"
    assert "knees ache" in log["source_excerpt"].lower()
    # corrected entities count as evidence
    assert "Joint swelling" in {t["clinical"] for t in unlocked.get("/api/timeline").json()["terms"]}
    assert b"knees" not in (unlocked.app.state.settings.data_dir / "clario.db").read_bytes().lower()  # encrypted at rest


def test_review_kinds_are_pluggable(unlocked):
    class Lab:
        def items(self):
            return [{"kind": "lab", "id": "lab_1", "entry_id": None, "display": "WBC", "value": "3.1", "confidence": 0.4,
                     "source_excerpt": "WBC 3.1"}]

        def apply(self, item_id, action, value):
            return {"before": {"value": "3.1"}, "after": {"value": value or "3.1"}}

    register_review_kind(unlocked.app, "lab", Lab())
    assert queue(unlocked)["count"] == 1
    assert unlocked.post("/api/review/lab/lab_1", json={"action": "confirm"}).status_code == 200
    assert unlocked.app.state.vault.all("correction_log")[0]["kind"] == "lab"


def test_patch_review_values(unlocked):
    unlocked.post("/api/entries", json={"text": "So tired"})
    x = wait_extracted(unlocked)[0]["entities"][0]
    assert unlocked.patch(f"/api/entities/{x['id']}", json={"review": "confirmed"}).json()["review"] == "confirmed"
    assert unlocked.patch(f"/api/entities/{x['id']}", json={"review": "needs_review"}).status_code == 422


def test_brief_marks_only_low_confidence_items():
    def ent(**kw):
        return SharedEntity(entry_id="e1", occurred_on="2026-09-01", type="symptom", quote="q", canonical="Fatigue",
                            hpo_id="HP:0012378", **kw)

    def joint(**kw):
        return ent(**kw).model_copy(update={"canonical": "Arthralgia", "hpo_id": "HP:0002829"})

    pkg = SharePackage(package_id="pkg_1", patient_alias="Ash-1", created_at="x", expires_at="y", period=("a", "b"),
                       entries=[], entities=[ent(reviewed=False, needs_review=True), ent(), joint(reviewed=False),
                                             ent().model_copy(update={"canonical": "Lupus", "family_history": True})])
    texts = {i.text for i in patient_items(pkg)}
    assert any(t.startswith("Fatigue") and LOW_CONFIDENCE in t for t in texts)
    assert any(t.startswith("Arthralgia") and LOW_CONFIDENCE not in t for t in texts)  # unchecked but confident: no mark
    assert any(t.startswith("Family history: Lupus") and LOW_CONFIDENCE not in t for t in texts)


def test_share_carries_every_term_but_rejected_ones(unlocked):
    ents = add_hedged_entry(unlocked)
    entries = [Entry.model_validate(e) for e in unlocked.get("/api/entries").json()]
    pkg = build_package(entries, "2026-01-01", "2026-12-31", "a", None, [], 1)
    assert len(pkg.entities) == 3 and not any(x.reviewed for x in pkg.entities)
    assert [x.canonical for x in pkg.entities if x.needs_review] == ["Arthralgia"]
    unlocked.patch(f"/api/entities/{ents[0]['id']}", json={"review": "rejected"})
    entries2 = [Entry.model_validate(e) for e in unlocked.get("/api/entries").json()]
    pkg2 = build_package(entries2, "2026-01-01", "2026-12-31", "a", None, [], 1)
    assert len(pkg2.entities) == 2 and ents[0]["id"] not in {x.id for x in pkg2.entities}

from fastapi.testclient import TestClient

from conftest import settings, wait_extracted
from test_share_clinic import share_body
from clario.app import create_app
from clario.clinic_ddx import disease_url, system_key
from clario.knowledge import Ontology


def shared_giulia(unlocked, clinic_server):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)  # no confirmation step: extracted terms are shared as they are
    r = unlocked.post("/api/share", json=share_body(clinic_server))
    assert r.status_code == 200, r.text
    return r.json()["package_id"]


def test_differential_names_conditions_and_asks_a_separating_question(unlocked, clinic_server, tmp_path):
    pid = shared_giulia(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        d = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert d["conditions"] and d["n_terms"] >= 3
        top = d["conditions"][0]
        assert top["rank"] == 1 and top["name"] and top["signal"] in ("weak", "moderate", "strong")
        assert top["matched"] and all(m["count"] >= 1 for m in top["matched"])
        assert top["url"] and top["url"].startswith("https://")
        q = d["question"]
        assert q and q["question"].endswith("?") and q["ig"] > 0 and q["freq_by"]
        assert q["feature_id"] not in {m["hpo_id"] for c in d["conditions"] for m in c["matched"]}  # never asks what is known

        r = clinic.post(f"/api/inbox/{pid}/ddx/answer", json={"feature_id": q["feature_id"], "answer": "yes"}).json()
        after = r["differential"]
        assert r["before"] and after["answers"][-1]["feature_id"] == q["feature_id"]
        assert not after["question"] or after["question"]["feature_id"] != q["feature_id"]  # not asked again
        bad = clinic.post(f"/api/inbox/{pid}/ddx/answer", json={"feature_id": "HP:9999999", "answer": "yes"})
        assert bad.status_code == 422
        reset = clinic.delete(f"/api/inbox/{pid}/ddx/answers").json()
        assert reset["answers"] == [] and reset["question"]["feature_id"] == q["feature_id"]
        it = clinic.get(f"/api/inbox/{pid}/ddx", params={"lang": "it"}).json()
        assert it["question"]["question"].startswith("Il paziente presenta")


def test_clinician_rejects_an_unsure_term_and_it_leaves_the_differential(unlocked, clinic_server, tmp_path):
    pid = shared_giulia(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        rash = [x for x in pkg["entities"] if x["canonical"] == "Malar rash"]
        assert rash and all(x["id"] for x in rash)
        before = clinic.get(f"/api/inbox/{pid}/ddx").json()
        for x in rash:
            assert clinic.patch(f"/api/inbox/{pid}/terms/{x['id']}", json={"decision": "rejected"}).status_code == 200
        after = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert after["n_terms"] == before["n_terms"] - 1
        assert all(m["hpo_id"] != "HP:0025300" for c in after["conditions"] for m in c["matched"])
        assert clinic.get(f"/api/inbox/{pid}/decisions").json()["terms"][rash[0]["id"]] == "rejected"
        assert clinic.patch(f"/api/inbox/{pid}/terms/nope", json={"decision": "rejected"}).status_code == 404
        assert clinic.patch(f"/api/inbox/{pid}/terms/{rash[0]['id']}", json={"decision": "maybe"}).status_code == 422
        stored = (tmp_path / "clinic" / "decisions" / f"{pid}.json").read_bytes()
        assert b"rejected" not in stored  # decisions are encrypted at rest


def test_privacy_counts_only_lists_entries_with_personal_details(unlocked):
    unlocked.post("/api/entries", json={"text": "Called Dr. Bianchi at 333 123 4567. Knees ache."})
    unlocked.post("/api/entries", json={"text": "Knees ache again."})
    wait_extracted(unlocked)
    counts = unlocked.get("/api/privacy/counts").json()
    assert list(counts.values()) == [2] or list(counts.values()) == [3]
    assert len(counts) == 1


def test_system_keys_group_terms_by_organ_system(unlocked):
    onto = Ontology.load()
    assert system_key(onto, "HP:0025300") == "skin"  # malar rash
    assert system_key(onto, "HP:0002829") == "joints"  # arthralgia
    assert system_key(onto, "HP:0000093") == "kidney"  # proteinuria
    assert system_key(onto, None) == "other"
    r = unlocked.get("/api/terms/systems", params={"ids": "HP:0025300,HP:0002829"}).json()
    assert r == {"HP:0025300": "skin", "HP:0002829": "joints"}
    assert disease_url("ORPHA:536") == "https://www.orpha.net/en/disease/detail/536"
    assert disease_url("OMIM:152700") == "https://omim.org/entry/152700"

from datetime import date, timedelta

from fastapi.testclient import TestClient

from conftest import confirm_all, settings, sse, wait_extracted
from clario.app import create_app
from clario.share import ClinicKeys, build_package, seal


def share_body(url, **kw):
    today = date.today()
    return {"clinic_url": url, "since": (today - timedelta(days=56)).isoformat(), "until": today.isoformat(),
            "note": "Is the joint pain and rash connected?", **kw}


def test_share_draft_review_finalize(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    key = unlocked.get("/api/clinic/key", params={"url": clinic_server}).json()
    assert len(key["fingerprint"].split()) == 5
    r = unlocked.post("/api/share", json=share_body(clinic_server))
    assert r.status_code == 200, r.text
    sh = r.json()
    assert sh["entries"] < 19 and sh["entities"] > 0 and sh["qr_svg"].startswith("data:image/svg+xml")
    pid = sh["package_id"]

    # The clinic process is separate; open a client on the same clinic data dir.
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        inbox = clinic.get("/api/inbox").json()
        assert [p["package_id"] for p in inbox] == [pid] and inbox[0]["brief_state"] == "none"
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        assert all(x["entry_id"] in {e["id"] for e in pkg["entries"]} for x in pkg["entities"])
        assert all(ent["review"] == "confirmed" for e in pkg["entries"] for ent in e["entities"])

        rid = clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"]
        events = sse(clinic, rid)
        assert events[-1]["stage"] == "done", events[-1]
        brief = events[-1]["payload"]
        ai = [i for i in brief["items"] if i["origin"] == "ai"]
        texts = " ".join(i["text"] for i in brief["items"])
        assert "You have lupus" not in texts and "200 mg" not in texts  # guardrail dropped it
        assert "Uncited claim" not in texts
        assert all(i["review"] == "pending" for i in ai)
        assert any(i["origin"] == "patient" and "Is the joint pain" in i["text"] for i in brief["items"])

        assert clinic.post(f"/api/inbox/{pid}/brief/finalize").status_code == 409
        for i, item in enumerate(ai):
            review = ["accepted", "rejected", "edited"][i % 3]
            body = {"review": review} | ({"text": "Edited by clinician."} if review == "edited" else {})
            assert clinic.patch(f"/api/brief-items/{pid}/{item['id']}", json=body).status_code == 200
        assert clinic.get("/api/clinic/metrics").json() == {"briefs": [], "totals": {"accepted": 0, "edited": 0, "rejected": 0},
                                                            "finalized": 0, "timed": 0, "mean_review_seconds": None}
        fin = clinic.post(f"/api/inbox/{pid}/brief/finalize", json={"seconds": 220.44}).json()
        assert fin["finalized"] is True and fin["review_seconds"] == 220.4
        want = {k: sum(1 for j in range(len(ai)) if ["accepted", "rejected", "edited"][j % 3] == k) for k in ("accepted", "rejected", "edited")}
        m = clinic.get("/api/clinic/metrics").json()
        assert m["finalized"] == 1 and m["timed"] == 1 and m["mean_review_seconds"] == 220.4
        assert m["totals"] == want and m["briefs"][0]["package_id"] == pid and m["briefs"][0]["accepted"] == want["accepted"]
        assert "text" not in m["briefs"][0]
        md = clinic.get(f"/api/inbox/{pid}/brief.md").text
        rejected = [it["text"] for k, it in enumerate(ai) if k % 3 == 1]
        assert all(t not in md for t in rejected)
        assert "Edited by clinician." in md and "reviewed by the clinician" in md
        assert clinic.patch(f"/api/brief-items/{pid}/{ai[0]['id']}", json={"review": "pending"}).status_code == 409


def test_clinic_rejects_foreign_and_expired_packages(tmp_path):
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        other = ClinicKeys(tmp_path / "other")
        pkg = build_package([], "2026-01-01", "2026-01-31", "Ash-001", None, [], 1)
        assert clinic.post("/api/inbox", json={"package_id": pkg.package_id,
                                               "sealed": seal(pkg, other.public_b64)}).status_code == 400
        key = clinic.get("/api/clinic/key").json()["public_key"]
        expired = pkg.model_copy(update={"expires_at": "2020-01-01T00:00:00+00:00"})
        assert clinic.post("/api/inbox", json={"package_id": pkg.package_id,
                                               "sealed": seal(expired, key)}).status_code == 410
        assert clinic.get("/api/inbox/pkg_../../etc").status_code == 404


def test_share_needs_reachable_clinic(unlocked):
    unlocked.post("/api/entries", json={"text": "Knees ache"})
    assert unlocked.post("/api/share", json=share_body("http://127.0.0.1:9")).status_code == 502
    assert unlocked.post("/api/share", json=share_body("file:///etc/passwd")).status_code == 422

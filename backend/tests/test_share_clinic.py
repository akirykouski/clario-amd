from datetime import date, timedelta

from fastapi.testclient import TestClient

from conftest import confirm_all, settings, sse, wait_extracted
from clario.app import create_app
from clario.brief_pdf import page_count
from clario.share import ClinicKeys, build_package, seal


def share_body(url, **kw):
    today = date.today()
    return {"clinic_url": url, "since": (today - timedelta(days=56)).isoformat(), "until": today.isoformat(),
            "note": "Is the joint pain and rash connected?", **kw}


def test_share_draft_edit_sign(unlocked, clinic_server, tmp_path):
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

              # the draft opens as a one-page PDF marked as an unreviewed AI draft
        pdf = clinic.get(f"/api/inbox/{pid}/brief.pdf")
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
        assert page_count(pdf.content) == 1 and "draft" in pdf.headers["content-disposition"]
        png = clinic.get(f"/api/inbox/{pid}/brief.png")  # the same page as an image for the in-console preview
        assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"

        # "Edit and sign": plain text with the sections kept, code checks as warnings
        t = clinic.get(f"/api/inbox/{pid}/brief/text").json()
        text = t["text"]
        assert t["signed"] is False and "## Summary" in text and "## Timeline" in text
        lines = {i["id"]: next(l for l in text.splitlines() if i["text"] in l) for i in ai}
        flagged = next(i for i in ai if i["flag"] == "citation_mismatch")
        assert any(w["kind"] == "citation" and w["line"] == lines[flagged["id"]][2:] for w in t["warnings"])
        assert not any(w["kind"] in ("hedge", "diagnosis") for w in t["warnings"])
        other = next(i for i in ai if i["section"] == "questions")
        edited = text.replace(lines[flagged["id"]] + "\n", "")  # reject the flagged line
        edited = edited.replace(other["text"], other["text"].rstrip(".") + ", and since when.")  # edit one
        edited += "\n## Patterns\n- You have lupus.\n"
        w = clinic.post(f"/api/inbox/{pid}/brief/check", json={"text": edited}).json()["warnings"]
        assert {x["kind"] for x in w} >= {"hedge", "diagnosis"} and not any(x["kind"] == "citation" for x in w)
        edited = edited.replace("- You have lupus.", "- Joint pain and rash together may be worth discussing.")
        assert clinic.post(f"/api/inbox/{pid}/brief/check", json={"text": edited}).json()["warnings"] == []

        assert clinic.post(f"/api/inbox/{pid}/brief/sign", json={"text": edited, "clinician": "  "}).status_code == 422
        assert clinic.post(f"/api/inbox/{pid}/brief/sign", json={"text": "", "clinician": "Dr Rossi"}).status_code == 422
        assert clinic.get("/api/clinic/metrics").json() == {"briefs": [], "totals": {"accepted": 0, "edited": 0, "rejected": 0},
                                                            "finalized": 0, "timed": 0, "mean_review_seconds": None}
        fin = clinic.post(f"/api/inbox/{pid}/brief/sign", json={"text": edited, "clinician": "Dr Anna Rossi", "seconds": 220.44}).json()
        assert fin["finalized"] is True and fin["review_seconds"] == 220.4 and fin["signed_by"] == "Dr Anna Rossi"
        assert fin["text"].strip() == edited.strip() and fin["pseudonymized"] is False  # offline fixtures: nothing left the server
        by_id = {i["id"]: i for i in fin["items"]}
        assert by_id[flagged["id"]]["review"] == "rejected" and by_id[other["id"]]["review"] == "edited"
        assert any(i["origin"] == "clinician" and i["section"] == "patterns" for i in fin["items"])
        want = {"accepted": len(ai) - 2, "edited": 1, "rejected": 1}
        m = clinic.get("/api/clinic/metrics").json()
        assert m["finalized"] == 1 and m["timed"] == 1 and m["mean_review_seconds"] == 220.4
        assert m["totals"] == want and m["briefs"][0]["package_id"] == pid and m["briefs"][0]["accepted"] == want["accepted"]
        assert "text" not in m["briefs"][0]
        md = clinic.get(f"/api/inbox/{pid}/brief.md").text
        assert flagged["text"] not in md and "and since when." in md and "may be worth discussing" in md
        assert clinic.get(f"/api/inbox/{pid}/brief/text").json() == {"text": fin["text"], "items": [], "sections": [], "warnings": [],
                                                                     "lang": "en", "signed": True}

        signed = clinic.get(f"/api/inbox/{pid}/brief.pdf")
        assert page_count(signed.content) == 1 and "signed" in signed.headers["content-disposition"]
        assert clinic.post(f"/api/inbox/{pid}/brief/sign", json={"text": edited, "clinician": "Dr Rossi"}).status_code == 409
        assert clinic.get("/api/inbox").json()[0]["brief_state"] == "final"


def test_share_edit_sign_cards(unlocked, clinic_server, tmp_path):
    """The card editor: lines by id, warnings on the line they belong to, exact kept/edited/removed counts."""
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    pid = unlocked.post("/api/share", json=share_body(clinic_server)).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        t = clinic.get(f"/api/inbox/{pid}/brief/text").json()
        items = t["items"]
        assert [s["key"] for s in t["sections"]] == ["summary", "timeline", "symptoms", "negatives", "findings", "labs", "medications", "patterns", "questions"]
        assert [i["id"] for i in items] and all(set(i) >= {"id", "section", "text", "cites", "origin"} for i in items)
        cit = next(w for w in t["warnings"] if w["kind"] == "citation")
        flagged = items[cit["item"]]
        assert flagged["origin"] == "ai" and flagged["text"] in cit["line"]
        ai = [i for i in items if i["origin"] == "ai"]
        edit = next(i for i in ai if i["id"] != flagged["id"])
        lines = [{"id": i["id"], "section": i["section"], "text": i["text"], "cites": i["cites"]} for i in items if i["id"] != flagged["id"]]
        for ln in lines:
            if ln["id"] == edit["id"]:
                ln["text"] = "Completely rewritten by the clinician."  # far from the draft: still `edited`, by id
        lines.append({"section": "patterns", "text": "You have lupus."})
        w = clinic.post(f"/api/inbox/{pid}/brief/check", json={"items": lines}).json()["warnings"]
        assert {x["kind"] for x in w if x.get("item") == len(lines) - 1} >= {"hedge", "diagnosis"}
        assert not any(x["kind"] == "citation" for x in w)
        lines[-1]["text"] = "Joint pain and rash together may be worth discussing."
        assert clinic.post(f"/api/inbox/{pid}/brief/check", json={"items": lines}).json()["warnings"] == []
        pv = clinic.post(f"/api/inbox/{pid}/brief/preview.pdf", json={"items": lines})
        assert pv.status_code == 200 and pv.content[:5] == b"%PDF-" and page_count(pv.content) == 1
        assert clinic.post(f"/api/inbox/{pid}/brief/sign", json={"items": [], "clinician": "Dr Rossi"}).status_code == 422
        fin = clinic.post(f"/api/inbox/{pid}/brief/sign", json={"items": lines, "clinician": "Dr Rossi"}).json()
        by_id = {i["id"]: i for i in fin["items"]}
        assert by_id[flagged["id"]]["review"] == "rejected" and by_id[edit["id"]]["review"] == "edited"
        assert "Completely rewritten by the clinician." in fin["text"] and flagged["text"] not in fin["text"]
        assert "## Patterns software noticed (not a diagnosis)" in fin["text"] and "may be worth discussing" in fin["text"]
        assert clinic.get("/api/clinic/metrics").json()["totals"] == {"accepted": len(ai) - 2, "edited": 1, "rejected": 1}
        assert clinic.post(f"/api/inbox/{pid}/brief/preview.pdf", json={"items": lines}).status_code == 409


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

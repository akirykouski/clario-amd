"""Brief as a PDF (#22): pseudonymised model input with day numbers, edit-and-sign text, one-page PDF."""

import json

from fastapi.testclient import TestClient

from clario import brief as briefing
from clario import brief_pdf
from clario.app import create_app
from clario.fixtures import OfflineLLM
from clario.fixtures import _stats as _fx_stats
from clario.models import Brief, BriefItem, Entry
from clario.share import build_package, seal
from conftest import settings, sse


def _pkg():
    entries = [Entry(id="e_1", created_at="2026-03-01T00:00:00+00:00", occurred_on="2026-03-01", text="Sono Giulia Rossi, ginocchia doloranti"),
               Entry(id="e_2", created_at="2026-03-12T00:00:00+00:00", occurred_on="2026-03-12", text="Stanca, il 3 marzo peggio")]
    return build_package(entries, "2026-03-01", "2026-03-31", "Ash-001", None, [], 24)


def test_relative_dates_leave_no_calendar_date_and_come_back():
    pkg = _pkg()
    sent = json.loads(briefing.model_input(pkg, "it", relative_dates=True))
    assert [e["date"] for e in sent["entries"]] == ["day 1", "day 12"] and sent["period"] == ["day 1", "day 31"]
    assert "2026-03" not in json.dumps(sent) and "day numbers" in sent["dates"]
    assert json.loads(briefing.model_input(pkg, "it"))["entries"][1]["date"] == "2026-03-12"  # local model: dates as they are
    assert briefing.restore_days("Day 12: stanchezza; giorno 1 ginocchia; day 99 stays", pkg) == \
        "2026-03-12: stanchezza; 2026-03-01 ginocchia; day 99 stays"


def test_text_round_trip_and_sign_decisions():
    pkg = _pkg()
    ai = [BriefItem(id="a1", section="summary", text="Knee pain and tiredness in March.", cites=["e_1", "e_2"]),
          BriefItem(id="a2", section="questions", text="Ask when the tiredness started."),
          BriefItem(id="a3", section="timeline", text="Tiredness noted.", cites=["e_2"])]
    pat = BriefItem(id="p1", section="symptoms", text="Arthralgia (HP:0002829): recorded once, 1 Mar 2026", origin="patient", review="accepted")
    b = Brief(package_id=pkg.package_id, items=[pat, *ai], lang="en")
    text = briefing.brief_text(pkg, briefing.shown_items(pkg, b, None), "en")
    assert text.startswith("## Summary\n- Knee pain and tiredness in March. [1 Mar, 12 Mar]\n")
    assert "## Recorded symptoms\n- Arthralgia" in text
    edited = text.replace("Ask when the tiredness started.", "Ask when the tiredness started and how long it lasts.")
    edited = edited.replace("- Tiredness noted. [12 Mar]\n", "") + "- Lives alone.\n"
    items = {i.id: i for i in briefing.sign_items(pkg, briefing.shown_items(pkg, b, None), edited, "en")}
    assert items["a1"].review == "accepted" and items["a2"].review == "edited" and items["a3"].review == "rejected"
    assert items["a2"].text.endswith("how long it lasts.") and "p1" in items
    assert any(i.origin == "clinician" and i.text == "Lives alone." for i in items.values())


def test_pdf_is_one_page_and_prints_italian():
    lines = [f"Riga {n}: perché è già più così, città, attività — “citazione” ≥ 2" for n in range(30)]
    b = brief_pdf.PdfBrief(lang="it", title="Riepilogo clinico: Ash-001", subtitle="Periodo", sections=[("Riepilogo", lines)],
                           provenance=brief_pdf.provenance("amd-token-factory", "Gemma-4-31B-IT", True, True, "it"))
    data = brief_pdf.render(b)
    assert data[:5] == b"%PDF-" and brief_pdf.page_count(data) == 1
    assert brief_pdf.provenance("amd-token-factory", "Gemma-4-31B-IT", True, True, "en") == [
        "Drafted by Gemma 4 31B on AMD Token Factory.",
        "Model input sent pseudonymised (names, contacts, ids and dates replaced)."]
    assert brief_pdf.provenance("offline-fixtures", "x", False, False, "en")[1].startswith("Offline demo")


def test_clinic_brief_input_is_pseudonymised_when_forced(tmp_path):
    """CLARIO_PSEUDONYMIZE=1 on the clinic (what a remote model gets by default): the brief prompt carries no name and no
    calendar date, the call log says redacted, the drafted timeline still has real dates, the brief records it."""
    with TestClient(create_app(settings(tmp_path, "clinic", pseudonymize=True))) as clinic:
        key = clinic.get("/api/clinic/key").json()["public_key"]
        pkg = _pkg()
        assert clinic.post("/api/inbox", json={"package_id": pkg.package_id, "sealed": seal(pkg, key)}).status_code == 200
        ev = sse(clinic, clinic.post(f"/api/inbox/{pkg.package_id}/brief").json()["run_id"])
        assert ev[-1]["stage"] == "done", ev[-1]
        b = ev[-1]["payload"]
        assert b["pseudonymized"] is True and b["model_remote"] is False
        calls = clinic.get("/api/privacy/calls").json()
        assert calls[0]["purpose"] == "brief" and calls[0]["redacted"] is True and calls[0]["replacements"] >= 2
        assert "Giulia" not in json.dumps(calls) and "2026-03-12" not in calls[0]["redacted_preview"]
        timeline = [i["text"] for i in b["items"] if i["section"] == "timeline"]
        assert timeline and all(" Mar" in t and "2026-" not in t for t in timeline)


class _AliasCitingLLM(OfflineLLM):
    """A remote-like model: it sees only the pseudonymised brief input and cites the ids it was given."""
    sent: list[str] = []

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        if task != "brief":
            return await super()._complete(task, messages, json_mode, max_tokens, payload)
        user = messages[-1]["content"]
        _AliasCitingLLM.sent.append(user)
        entries = json.loads(user)["entries"]
        items = [{"section": "summary", "text": "Knee pain, then tiredness.", "cites": [e["id"] for e in entries]}]
        items += [{"section": "timeline", "text": f"{e['date']}: noted.", "cites": [e["id"]]} for e in entries]
        return json.dumps({"items": items}), _fx_stats()


def test_pseudonymised_brief_cites_aliases_and_keeps_every_line(tmp_path, monkeypatch):
    """Ids with digits (e_demo_1234567890) are cut by the pseudonymiser ("e_demo_[RECORD_NO]"), so the input carries
    aliases (E1, E2) instead; the model cites those and every line comes back cited with the real entry ids."""
    from clario import app as app_mod
    from clario import privacy

    entries = [Entry(id="e_demo_1234567890", created_at="2026-03-01T00:00:00+00:00", occurred_on="2026-03-01", text="Ginocchia doloranti"),
               Entry(id="e_demo_9876543210", created_at="2026-03-12T00:00:00+00:00", occurred_on="2026-03-12", text="Stanca")]
    pkg = build_package(entries, "2026-03-01", "2026-03-31", "Ash-001", None, [], 24)
    assert "[RECORD_NO]" in privacy.pseudonymize(json.dumps({"id": entries[0].id}))[0]  # why ids cannot be sent as they are
    sent = briefing.model_input(pkg, "en", relative_dates=True)
    assert privacy.pseudonymize(sent)[0] == sent and "e_demo_" not in sent  # aliases survive the pseudonymiser untouched

    _AliasCitingLLM.sent = []
    monkeypatch.setattr(app_mod, "make_llm", lambda s, log=None: privacy.wrap(_AliasCitingLLM(1), s, log))
    with TestClient(create_app(settings(tmp_path, "clinic", pseudonymize=True))) as clinic:
        key = clinic.get("/api/clinic/key").json()["public_key"]
        assert clinic.post("/api/inbox", json={"package_id": pkg.package_id, "sealed": seal(pkg, key)}).status_code == 200
        ev = sse(clinic, clinic.post(f"/api/inbox/{pkg.package_id}/brief").json()["run_id"])
        assert ev[-1]["stage"] == "done", ev[-1]
    assert [e["id"] for e in json.loads(_AliasCitingLLM.sent[0])["entries"]] == ["E1", "E2"]
    ai = [i for i in ev[-1]["payload"]["items"] if i["origin"] == "ai"]
    assert len(ai) == 3  # summary + two timeline lines: none dropped for an unknown cite
    assert ai[0]["section"] == "summary" and ai[0]["cites"] == ["e_demo_1234567890", "e_demo_9876543210"]
    assert [i["cites"] for i in ai[1:]] == [["e_demo_1234567890"], ["e_demo_9876543210"]]


def test_restore_cites_maps_aliases_and_leaves_the_rest():
    pkg = _pkg()
    assert briefing.restore_cites(["E2", " e1 ", "e_1", "E9", "e_[RECORD_NO]", "E2"], pkg) == ["e_2", "e_1", "E9", "e_[RECORD_NO]"]

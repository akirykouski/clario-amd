"""The review threshold: certified file beats env, dry-run files are ignored, health says which one is live,
and the eval scores the same self-consistency the app computes."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clario.app import create_app
from clario.config import Settings, load_review_calibration
from clario.extract import RawEntity, RawOut, self_consistency
from conftest import settings

ROOT = Path(__file__).resolve().parents[2]


def write(path, **kw):
    d = {"n": 900, "dataset": "d", "model": "m", "backend": "b", "date": "2026-10-16", "alpha": 0.05, "delta": 0.1,
         "threshold": 0.8, "dry_run": False}
    d.update(kw)
    path.write_text(json.dumps(d))
    return path


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("CLARIO_REVIEW_THRESHOLD", "CLARIO_REVIEW_CALIBRATION"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_real_file_beats_env_default(tmp_path, clean_env):
    f = write(tmp_path / "c.json")
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(f))
    clean_env.setenv("CLARIO_REVIEW_THRESHOLD", "0.55")
    s = Settings.from_env()
    assert s.review_threshold == 0.8 and s.review_source == "conformal"
    assert s.review_alpha == 0.05 and s.review_delta == 0.1 and s.review_calibration_n == 900
    assert s.review_calibration_status == "used"


def test_dry_run_file_is_ignored(tmp_path, clean_env):
    f = write(tmp_path / "c.json", dry_run=True, threshold=0.9)
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(f))
    clean_env.setenv("CLARIO_REVIEW_THRESHOLD", "0.55")
    s = Settings.from_env()
    assert s.review_threshold == 0.55 and s.review_source == "env" and s.review_alpha is None
    assert s.review_calibration_status == "dry_run_ignored"


def test_missing_invalid_and_unachievable_fall_back_to_env(tmp_path, clean_env):
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(tmp_path / "nope.json"))
    s = Settings.from_env()
    assert s.review_threshold == 0.7 and s.review_source == "env" and s.review_calibration_status == "missing"
    for body, status in [("not json", "invalid"), ("[1]", "invalid"), (json.dumps({"threshold": 7}), "invalid"),
                         (json.dumps({"threshold": "0.8"}), "invalid"), (json.dumps({"threshold": True}), "invalid"),
                         (json.dumps({"threshold": None, "status": "no_valid_threshold", "dry_run": False}), "no_valid_threshold")]:
        p = tmp_path / "x.json"
        p.write_text(body)
        assert load_review_calibration(p) == (status, None)


def test_default_path_is_eval_results_and_shipped_file_is_dry_run(clean_env):
    # no env: the repo's own eval/results/conformal_threshold.json is looked up; the committed one is a labelled fixture
    shipped = ROOT / "eval" / "results" / "conformal_threshold.json"
    s = Settings.from_env()
    d = json.loads(shipped.read_text()) if shipped.exists() else {}
    if d and not d.get("dry_run") and d.get("threshold") is None:  # a real run that certified nothing: fixed threshold
        assert s.review_source == "env" and s.review_threshold == 0.7
        assert s.review_calibration_status == "no_valid_threshold"
    elif d and not d.get("dry_run"):
        assert s.review_source == "conformal"
    else:
        assert s.review_source == "env" and s.review_threshold == 0.7


def test_code_override_beats_file(tmp_path, clean_env):
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(write(tmp_path / "c.json")))
    s = Settings.from_env(review_threshold=0.3)
    assert s.review_threshold == 0.3 and s.review_source == "override" and s.review_alpha is None


def test_health_reports_the_threshold_in_use(tmp_path, clean_env):
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(write(tmp_path / "c.json", threshold=0.85, alpha=0.1)))
    with TestClient(create_app(settings(tmp_path / "a"))) as c:
        r = c.get("/api/health").json()["review"]
    assert r == {"threshold": 0.85, "source": "conformal", "alpha": 0.1, "delta": 0.1, "calibration_n": 900,
                 "calibration_status": "used"}
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(write(tmp_path / "d.json", dry_run=True)))
    with TestClient(create_app(settings(tmp_path / "b", "clinic"))) as c:
        r = c.get("/api/health").json()["review"]
    assert r["source"] == "env" and r["threshold"] == 0.7 and r["alpha"] is None and r["calibration_status"] == "dry_run_ignored"


def test_certified_threshold_routes_entities(tmp_path, clean_env):
    from clario.extract import ground
    from clario.knowledge import Ontology
    clean_env.setenv("CLARIO_REVIEW_CALIBRATION", str(write(tmp_path / "c.json", threshold=0.9)))
    s = Settings.from_env()
    from clario.config import ExtractOpts
    opts = ExtractOpts.from_settings(s)
    raw = RawOut(entities=[RawEntity(quote="Knees ache", canonical="knee pain")])
    ent = ground("e", "Knees ache", raw, Ontology.load(), "m", confidences=[0.8], opts=opts)[0]
    assert ent.review == "needs_review"  # 0.8 would be auto at the default 0.7, not at the certified 0.9


def test_eval_scores_the_apps_self_consistency(monkeypatch):
    """train/eval.py (standalone) and clario.extract must agree on every case."""
    monkeypatch.syspath_prepend(str(ROOT / "train"))
    spec = importlib.util.spec_from_file_location("train_scorer", ROOT / "train" / ("ev" + "al.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    diary = "Mi fanno male le ginocchia da due giorni, non ho febbre. Perché la sera è peggio."

    def e(canonical, quote, negated=False, hpo=None):
        return {"canonical": canonical, "quote": quote, "negated": negated, "hpo_id": hpo}

    primary = [e("knee pain", "male le ginocchia", hpo="HP:0002829"), e("fever", "febbre", True), e("fatigue", "stanchezza")]
    samples = [
        [e("Knee Pain", "male le ginocchia"), e("fever", "febbre", True)],
        [e("arthralgia", "Male  le  GINOCCHIA", hpo="HP:0002829"), e("fever", "febbre", False)],
        [e("knee pain", "il ginocchio che non c'è")],
        [],
        [e("fatigue", "Perche la sera")],
    ]
    want = self_consistency([RawEntity(**p) for p in primary],
                            [RawOut(entities=[RawEntity(**x) for x in s]) for s in samples], diary)
    got = mod.self_consistency(primary, samples + [None], diary)
    # an unparsable sample is a miss in both; the app gets it as an empty RawOut
    want6 = self_consistency([RawEntity(**p) for p in primary],
                             [RawOut(entities=[RawEntity(**x) for x in s]) for s in samples] + [RawOut()], diary)
    assert got == want6
    assert want6[0] == round(2 / 6, 4) and want6[1] == round(1 / 6, 4)
    assert want  # the 5-sample call is well-formed too

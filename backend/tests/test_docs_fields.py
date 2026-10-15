"""Every {{placeholder}} in the README and talk docs names a field the writing script really emits."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "docs/PITCH.md", "docs/VIDEO_SCRIPT.md", "docs/SUBMISSION.md"]


def placeholders():
    out = set()
    for d in DOCS:
        out |= set(re.findall(r"\{\{([a-z_]+\.[^}]+)\}\}", (ROOT / d).read_text()))
    return out


def src(*parts):
    return (ROOT.joinpath(*parts)).read_text()


def test_placeholders_use_the_exact_field_names_the_scripts_write():
    docs_src, bench_src = src("backend", "scripts", "eval_documents.py"), src("bench", "bench.py")
    train_src, eval_src = src("train", "train_rocm.py"), src("train", "eval.py")
    curve_src = src("eval", "review_curve.py")
    seen = placeholders()
    assert seen
    for ph in sorted(seen):
        parts = ph.split(".")
        kind, field = parts[0], parts[-1]
        if kind == "documents":
            assert f'"{field}"' in docs_src, ph
        elif kind == "bench":
            assert f'"{field}"' in bench_src, ph
        elif kind == "train":
            assert f'"{field}"' in train_src, ph
        elif kind == "extraction":
            assert f'"{field}"' in eval_src, ph
        elif kind == "review_curve":
            assert parts[1] == "tolerances" and re.fullmatch(r"(1|2|5)pct", parts[2]) and field == "review_share", ph
            assert '"review_share"' in curve_src, ph


def test_review_curve_is_labelled_as_routing_by_self_reported_confidence():
    s = src("eval", "review_curve.py")
    assert "confidence_source" in s and "self-reported" in s and "not coverage" in s
    assert "coverage_at" not in (ROOT / "README.md").read_text()


def test_bench_and_train_results_land_in_eval_results_with_provenance():
    for f in (src("bench", "bench.py"), src("train", "train_rocm.py")):
        assert '"eval"' in f and "results" in f
        for k in ('"n"', '"dataset"', '"backend"', '"date"'):
            assert k in f, k
    assert '"model"' in src("bench", "bench.py") and '"model"' in src("train", "train_rocm.py")

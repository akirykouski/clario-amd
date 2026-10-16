import pytest


@pytest.fixture(autouse=True)
def _no_real_lexicon(monkeypatch):
    """Tests are deterministic whether or not a generated train/lay_lexicon.json is present."""
    import synth
    monkeypatch.setattr(synth, "LEX", {})

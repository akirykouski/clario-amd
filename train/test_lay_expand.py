import argparse
import asyncio
import json
import random
import string
from types import SimpleNamespace

import pytest

import lay_expand as lx
import synth

ONTO = lx.Ontology.load()
ITCH = "HP:0000989"  # Pruritus


def args(tmp_path, **kw):
    a = dict(terms=5, per_term=6, out=str(tmp_path / "lex.json"), base_url="http://x/v1", model="m", api_key_env="",
             concurrency=4, seed=1, fresh=False, offline=False)
    a.update(kw)
    return argparse.Namespace(**a)


class FakeClient:
    """Answers generation calls with fixed phrases and verification calls by a rule on the phrase."""

    def __init__(self, phrases, keep):
        self.phrases, self.keep = phrases, keep
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, model, temperature, max_tokens, messages):
        user = messages[1]["content"]
        if messages[0]["content"] == lx.SYSTEM:
            body = {"phrases": self.phrases}
        else:  # verification: find the target's letter from the options listed
            opts = [l for l in user.splitlines() if len(l) > 2 and l[1] == ")"]
            phrases = [l.split(". ", 1)[1] for l in user.splitlines() if l[:1].isdigit()]
            target = next(o[0] for o in opts if o[3:] == self.target_label)
            body = {"answers": [target if self.keep(p) else "none" for p in phrases]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))])


def test_code_checks_reject_clinical_wording_and_bad_length():
    assert lx.code_ok(ONTO, ITCH, "my knee is so itchy") is None
    assert lx.code_ok(ONTO, ITCH, "pruritus") == "length"
    assert lx.code_ok(ONTO, ITCH, "bad pruritus on legs") == "clinical_word"
    assert lx.code_ok(ONTO, "HP:0002829", "arthralgia in both knees") == "clinical_word"  # -algia
    assert lx.code_ok(ONTO, ITCH, "itchy for 3 days") == "digit"
    assert lx.code_ok(ONTO, ITCH, "itch " * 12) == "length"
    two_word = next(t for t in lx.LAY if len((ONTO.label(t) or "").split()) == 2)
    assert lx.code_ok(ONTO, two_word, f"really bad {ONTO.label(two_word)} today") == "clinical_label"


def test_distractors_are_similar_but_never_the_target_or_its_family():
    pool = lx.candidate_terms(ONTO, 0)
    t = pool[0]
    ds = lx.distractors(ONTO, t, pool, random.Random(0))
    assert len(ds) == lx.N_DISTRACTORS and t not in ds
    related = ONTO.ancestors(t) | ONTO.descendants(t)
    assert not set(ds) & related


def test_offline_run_writes_a_lexicon_and_stats(tmp_path):
    s = asyncio.run(lx.run(args(tmp_path, offline=True, terms=8)))
    lex = json.loads((tmp_path / "lex.json").read_text())
    assert s["terms_with_phrases"] == len(lex) > 0 and s["generator"] == "offline"
    assert all(lx.code_ok(ONTO, t, p) is None for t, ps in lex.items() for p in ps)
    assert json.loads((tmp_path / "lex.json.stats.json").read_text())["phrases"] == s["phrases"]
    again = asyncio.run(lx.run(args(tmp_path, offline=True, terms=8)))  # resumes: nothing left to do
    assert again["terms_with_phrases"] == s["terms_with_phrases"]


def test_only_phrases_that_survive_code_checks_and_the_blind_round_trip_are_kept(tmp_path):
    t = lx.candidate_terms(ONTO, 1)[0]
    client = FakeClient(["my skin keeps acting up", "kind of weird feeling", "bad pruritus here", "x", "my skin keeps acting up"],
                        keep=lambda p: "skin" in p)
    client.target_label = ONTO.label(t)
    reasons = lx.Counter()
    got = asyncio.run(lx.expand_term(client, args(tmp_path), ONTO, t, lx.candidate_terms(ONTO, 0), random.Random(3), reasons))
    assert got == ["my skin keeps acting up"]
    assert reasons["duplicate"] == 1 and reasons["failed_round_trip"] == 1 and reasons["verified"] == 1
    assert reasons["clinical_word"] + reasons["length"] == 2


def test_refuses_anthropic_endpoints(tmp_path):
    with pytest.raises(SystemExit):
        asyncio.run(lx.run(args(tmp_path, base_url="https://api.anthropic.com/v1/")))


def test_synth_words_english_symptoms_from_the_lexicon(monkeypatch):
    diseases = [d for d in ONTO.diseases() if sum(1 for t in d.phenotypes if synth.term_ok(ONTO, t)) >= 3][:50]
    lex = {t: ["my body feels off again"] for d in diseases for t in d.phenotypes}
    monkeypatch.setattr(synth, "LEX", lex)
    monkeypatch.setattr(synth, "P_LEX", 1.0)
    rng = random.Random(5)
    plans = [p for p in (synth.plan(ONTO, diseases, rng, it_frac=0.0) for _ in range(40)) if p and p["kind"] == "clinical"]
    p = next(x for x in plans if x.get("say"))
    assert set(p["say"]) <= set(p["present"]) | {f["id"] for f in p["family"]}
    t = next(iter(p["say"]))
    assert '"my body feels off again"' in synth.user_prompt(ONTO, p)
    reply = synth.offline_reply(ONTO, {**p, "say": {t: p["say"][t]}, "present": [t], "absent": [], "family": [],
                                       "onset": {}, "severity": {}, "trigger": None})
    assert reply["mentions"][0]["quote"] == "my body feels off again"
    it_plans = [x for x in (synth.plan(ONTO, diseases, random.Random(9), it_frac=1.0) for _ in range(20)) if x]
    assert not any("say" in x or "voice" in x for x in it_plans)  # Italian entries are unchanged

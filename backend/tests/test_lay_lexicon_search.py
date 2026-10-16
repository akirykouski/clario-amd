import gzip
import json

from clario.knowledge import DEFAULT_PATH, Ontology

ITCH = "HP:0000989"  # Pruritus


def raw():
    with gzip.open(DEFAULT_PATH, "rt", encoding="utf-8") as f:
        return json.load(f)


def test_lay_lexicon_phrases_help_search_but_are_not_synonyms():
    plain = Ontology(raw())
    phrase = "my knee keeps driving me crazy"
    assert ITCH not in [t.hpo_id for t in plain.search(phrase, 10)]
    rich = Ontology(raw(), {ITCH: [phrase]})
    assert rich.search(phrase, 10)[0].hpo_id == ITCH
    assert phrase not in rich.synonyms(ITCH)  # the lexicon feeds search only
    assert rich.label(ITCH) == plain.label(ITCH)

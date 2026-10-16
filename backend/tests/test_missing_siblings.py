from clario.knowledge import Ontology
from clario.patterns import missing_terms


def test_missing_never_paraphrases_a_recorded_joint_symptom():
    onto = Ontology.load()
    patient = {"HP:0001386", "HP:0002829"}  # joint swelling, joint pain
    for d in onto.diseases():
        if "HP:0001369" in d.phenotypes and d.phenotypes["HP:0001369"] > 0.5:
            ids = {t.hpo_id for t in missing_terms(onto, d, patient, k=20)}
            assert "HP:0001369" not in ids

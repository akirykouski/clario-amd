# eval/data

`psytar_hpo.jsonl` is built by `train/psytar_hpo.py` from PsyTAR and is not present until someone downloads the source workbook (the site blocks scripted downloads).

Attribution (CC BY 4.0): Zolnoori M, Fung KW, Patrick TB, et al. A systematic approach for developing a corpus of patient reported adverse drug events: A case study for SSRI and SNRI medications. J Biomed Inform 90 (2019). doi:10.1016/j.jbi.2018.12.005. Source: https://www.askapatient.com/research/pharmacovigilance/corpus-ades-psychiatric-medications.asp

Mapping to HPO is lexical and conservative (match score at least 0.95); the coverage numbers are written to `psytar_hpo.stats.json`. Rows are marked `gold_complete: false`, so precision on this set is a lower bound.

import io
import json
import zipfile
from xml.sax.saxutils import escape

import pytest

import psytar_hpo as ps
from clario.knowledge import Ontology

ONTO = Ontology.load()
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def col(i):
    return chr(65 + i)


def make_xlsx(sheets: dict) -> bytes:
    """Smallest valid xlsx with shared strings for text cells and plain numbers: enough to exercise the reader."""
    shared, idx = [], {}

    def sid(s):
        if s not in idx:
            idx[s] = len(shared)
            shared.append(s)
        return idx[s]

    sheet_xml = {}
    for name, rows in sheets.items():
        body = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, v in enumerate(row):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    cells.append(f'<c r="{col(c)}{r}"><v>{v}</v></c>')
                else:
                    cells.append(f'<c r="{col(c)}{r}" t="s"><v>{sid(v)}</v></c>')
            body.append(f'<row r="{r}">{"".join(cells)}</row>')
        sheet_xml[name] = f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        names = list(sheets)
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names))) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>")
        for i, n in enumerate(names):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", sheet_xml[n])
    return buf.getvalue()


SHEETS = {
    "Sentence_Labeling": [["drug_id", "sentence_index", "sentences"],
                          ["101", 1, "I got a terrible headache and felt dizzy every morning."],
                          ["101", 2, "Zoloft helped my depression a little."],
                          ["102", 1, "Mostly just some weird vibes and a rash on my skin."]],
    "ADR_Mapped": [["drug_id", "sentence_index", "ADRs", "UMLS1", "SNOMED-CT"],
                   ["101", 1, "headache", "C0018681", "25064002"],
                   ["101", 1, "dizzy", "C0012833", "404640003"],
                   ["102", 1, "weird vibes", "C9999999", None],
                   ["102", 1, "not in the sentence", None, None]],
    "WD-Mapped ": [["drug_id", "sentence_id", "WDs"], ["102", 1, "rash"]],
    "SSI_Mapped": [["drug_id", "sentence_index", "SSI"]],
    "DI_Mapped": [["drug_id", "sentence_index", "DIs"], ["101", 2, "depression"]],
}


def test_reader_parses_sheets_and_header_rows():
    sheets = ps.read_xlsx(make_xlsx(SHEETS))
    assert set(sheets) == set(SHEETS)
    assert sheets["Sentence_Labeling"][0] == {"drug_id": "101", "sentence_index": "1",
                                              "sentences": "I got a terrible headache and felt dizzy every morning."}
    assert sheets["ADR_Mapped"][2]["UMLS1"] == "C9999999" and "SNOMED-CT" not in sheets["ADR_Mapped"][2]


def test_build_maps_only_confident_hpo_matches_and_reports_coverage():
    rows, st = ps.build(ps.read_xlsx(make_xlsx(SHEETS)), ONTO, min_conf=0.95)
    assert st["mentions_total"] == 5 and st["mentions_by_type"] == {"ADR": 4, "WD": 1}  # drug indication sheet is not used
    assert st["not_verbatim"] == 1 and st["mapped"] + st["below_threshold"] + st["no_match"] == 4
    assert st["mapping_coverage"] == round(st["mapped"] / 5, 4) and "doi:10.1016/j.jbi.2018.12.005" in st["citation"]
    by_id = {r["id"]: r for r in rows}
    r = by_id["psytar-101-1"]
    assert r["gold_complete"] is False and r["partial"] is True and r["lang"] == "en" and r["licence"] == "CC BY 4.0"
    ents = {e["quote"]: e for e in r["target"]["entities"]}
    assert ents["headache"]["hpo_id"] == "HP:0002315" and ents["headache"]["canonical"] == ONTO.label("HP:0002315")
    assert all(e["quote"] in r["diary"] for x in rows for e in x["target"]["entities"])
    assert st["mapped"] == 1 and st["below_threshold"] == 2  # "dizzy" -> Vertigo and "rash" -> Skin rash are too loose to keep
    assert "weird vibes" not in {e["quote"] for x in rows for e in x["target"]["entities"]}  # junk stays out
    assert "psytar-101-2" not in by_id  # a sentence with only a drug indication has no gold


def test_threshold_controls_what_is_kept():
    sheets = ps.read_xlsx(make_xlsx(SHEETS))
    strict_rows, strict = ps.build(sheets, ONTO, 0.999)
    loose_rows, loose = ps.build(sheets, ONTO, 0.5)
    assert loose["mapped"] >= strict["mapped"] and loose["below_threshold"] <= strict["below_threshold"]


def test_missing_sheet_is_reported_and_zip_input(tmp_path):
    only = {k: v for k, v in SHEETS.items() if k != "SSI_Mapped"}
    _, st = ps.build(ps.read_xlsx(make_xlsx(only)), ONTO)
    assert st["sheets_missing"] == ["SSI_Mapped"]
    with pytest.raises(SystemExit):
        ps.build({"Other": []}, ONTO)
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("PsyTAR_dataset.xlsx", make_xlsx(SHEETS))
    assert set(ps.read_xlsx(ps.workbook_bytes(z))) == set(SHEETS)


def test_cli_writes_rows_and_stats(tmp_path, monkeypatch):
    x = tmp_path / "PsyTAR_dataset.xlsx"
    x.write_bytes(make_xlsx(SHEETS))
    out = tmp_path / "psytar_hpo.jsonl"
    monkeypatch.setattr("sys.argv", ["psytar_hpo.py", "--xlsx", str(x), "--out", str(out)])
    ps.main()
    rows = [json.loads(l) for l in open(out)]
    assert rows and json.load(open(tmp_path / "psytar_hpo.stats.json"))["rows"] == len(rows)


def test_missing_file_explains_manual_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["psytar_hpo.py", "--xlsx", str(tmp_path / "nope.xlsx"), "--out", str(tmp_path / "o.jsonl")])
    with pytest.raises(SystemExit) as e:
        ps.main()
    assert "browser" in str(e.value) and "CC BY 4.0" in str(e.value)

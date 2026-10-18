"""Reading load and cost per brief for the demo patient: what a clinician would read without Clario, against the brief.

    uv run --project backend python eval/impact_proxy.py        -> eval/results/impact_proxy.json

Reading load: words in what the patient shares (diary notes, what was tried and tested, the three lab reports as
printed) against words in the one-page brief Gemma 4 31B drafted on AMD Token Factory for the same patient
(backend/clario/data/demo/giulia_briefs.json, English draft). Minutes use 238 words per minute, the average silent
reading rate for English non-fiction in Brysbaert, J Mem Lang 109 (2019) 104047. This is a proxy on one synthetic
patient: it measures how much text there is to read, not how long a clinician takes, and nothing here was timed
with a clinician.

Cost per brief: the AMD Token Factory gateway reports a cost per request; eval/results/bench_tf-gemma4-31b.json
holds it for 6 briefs per concurrency level. No price is assumed here.
"""
import datetime
import json
import os
import re

import pypdfium2 as pdfium

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.join(ROOT, "backend", "clario", "data", "demo")
WPM = 238


def words(text):
    return len(re.findall(r"[^\W_]+(?:['’.-][^\W_]+)*", text or ""))


def pdf_text(path):
    doc = pdfium.PdfDocument(path)
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def main():
    diary = json.load(open(os.path.join(DEMO, "giulia_labels_en.json"), encoding="utf-8"))["entries"]
    care = json.load(open(os.path.join(DEMO, "giulia_care_en.json"), encoding="utf-8"))
    briefs = json.load(open(os.path.join(DEMO, "giulia_briefs.json"), encoding="utf-8"))["drafts"]
    brief = next(b for b in briefs if b.get("lang") == "en")

    diary_w = sum(words(e["text"]) for e in diary)
    care_w = sum(words(" ".join(str(v) for v in item.values())) for key in ("tried", "tested") for item in care[key])
    labs = sorted(f for f in os.listdir(DEMO) if f.startswith("ref_") and f.endswith(".pdf"))
    labs_w = sum(words(pdf_text(os.path.join(DEMO, f))) for f in labs)
    package_w = diary_w + care_w + labs_w
    brief_w = sum(words(i["text"]) for i in brief["output"]["items"])

    bench = json.load(open(os.path.join(HERE, "results", "bench_tf-gemma4-31b.json"), encoding="utf-8"))
    rows = [r for r in bench["results"] if r["workload"] == "brief"]
    cost = [{"concurrency": r["concurrency"], "briefs": r["ok"], "cost_usd_total": r["cost_usd"],
             "cost_usd_per_brief": round(r["cost_usd"] / r["ok"], 7), "latency_p50_s": r["p50_s"],
             "mean_prompt_tokens": r["mean_prompt_tokens"], "mean_out_tokens": r["mean_out_tokens"]} for r in rows]

    out = {
        "label": "impact-proxy-giulia-en", "date": datetime.date.today().isoformat(),
        "patient": "Giulia (EN), synthetic demo persona", "words_per_minute": WPM,
        "wpm_source": "Brysbaert M. How many words do we read per minute? J Mem Lang 109 (2019) 104047",
        "package": {"diary_entries": len(diary), "diary_words": diary_w, "care_words": care_w,
                    "lab_reports": len(labs), "lab_report_words": labs_w, "total_words": package_w,
                    "reading_minutes": round(package_w / WPM, 1)},
        "brief": {"part": "AI-written summary, timeline and questions (the PDF adds a code-built symptom list)",
                  "items": len(brief["output"]["items"]), "words": brief_w, "reading_minutes": round(brief_w / WPM, 1),
                  "model": brief["model"], "backend": brief["backend"], "generated": brief["generated"],
                  "latency_s": round(brief["stats"]["latency_ms"] / 1000, 1)},
        "reduction": {"words_ratio": round(package_w / brief_w, 1),
                      "minutes_saved_reading": round((package_w - brief_w) / WPM, 1)},
        "cost_per_brief": cost,
        "cost_source": "gateway-reported cost per request, eval/results/bench_tf-gemma4-31b.json",
        "caveats": "One synthetic patient. Measures text to read, not clinician time; no clinician was timed. "
                   "A real patient's months of notes and reports would be longer than this demo.",
    }
    path = os.path.join(HERE, "results", "impact_proxy.json")
    json.dump(out, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

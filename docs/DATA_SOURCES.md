# Clario data sources: candidate datasets, licences, and plan

Research date: 2026-10-14. Web research only. Nothing was downloaded and no model was run. Where a claim rests on a search snippet or a third-party mirror instead of the primary page, it is flagged. Anything not confirmed is marked UNVERIFIED. This is an engineering reading of licence text and is not legal advice.

## 1. Bottom line

1. No public dataset gives lay-language text, span-level symptoms, negation, and HPO IDs together. Every real corpus needs a label bridge (UMLS or SNOMED to HPO) or a hand-made gold set.
2. The only English lay-language corpora we can legally put in a public repo are PsyTAR (CC BY 4.0) and, with caveats, COMETA (code is MIT, data licence not stated). CADEC is the best-known lay corpus but its CSIRO Data Licence forbids redistribution and is non-commercial. Keep it out of the repo.
3. Italian real data is thin. E3C is clinical case-report register and is not lay. There is no Italian patient-forum symptom corpus that we could find. The Italian eval set has to be hand-made by the team.
4. The Anthropic position on training a model on Claude outputs is amber to red (section 5). Safest path for the demo: generate synthetic training data with an open-weights model on the AMD cloud, and use Claude only for roles that do not create training targets.
5. HPO files carry a custom licence with a no-alteration clause. Do not commit modified copies of hp.json. Download a pinned release at build time.

## 2. Ranked shortlist

| Use | Rank 1 | Rank 2 | Rank 3 | Why |
|---|---|---|---|---|
| Best for TRAIN | Synthetic data from an open model, seeded with HPO labels and layperson synonyms plus CHV lay phrases | PsyTAR (CC BY 4.0) | SympTEMIST and E3C as register diversity (they are not lay) | Only synthetic data carries HPO IDs and our exact schema. PsyTAR is the one real lay corpus that is safe to redistribute. |
| Best for EVAL | Hand-annotated Clario gold set (100 to 150 diary-style docs, EN and IT), with real lay text drawn from PsyTAR | PsyTAR held-out reviews (spans, patient-written, CC BY 4.0) | COMETA mentions (lay phrase to SNOMED, for term-normalization accuracy) | Real, non-synthetic, and publishable. CADEC is a stronger-known benchmark but can only be used privately. |
| Best for ITALIAN | Hand-made Italian lay gold set (team plus an Italian-speaking annotator) | E3C Italian (clinical register, CC BY 4.0 per project snippets) | HPO Italian translation labels (UNVERIFIED coverage) and SympTEMIST multilingual Italian silver standard (UNVERIFIED licence and quality) | No native Italian lay symptom corpus found. |

## 3. Licence verdicts at a glance

Verdict key. Green: can train a public demo and redistribute derived data with attribution. Amber: usable but with a condition or an unverified licence. Red: do not use in the public repo, or cannot get access this week.

| Source | Train for public demo | Redistribute in public repo | Overall |
|---|---|---|---|
| PsyTAR | Yes | Yes, with CC BY attribution | GREEN |
| MedMentions | Yes | Yes (CC0) | GREEN (low value, scientific text) |
| SympTEMIST | Yes | Yes, with attribution | GREEN (Spanish, SNOMED) |
| E3C | Likely yes | Likely yes, licence taken from search snippet | AMBER |
| COMETA | Probably | Unclear, data licence not stated, Reddit origin | AMBER |
| TwiMed | Probably | Unclear, tweet text limits | AMBER |
| BC5CDR | Yes (public domain per secondary source) | Likely | AMBER (low value) |
| NCBI Disease | Likely | Unclear | AMBER (low value) |
| GSC+ and HPO gold corpus | Yes | Only under HPO licence conditions | AMBER |
| CHV | Likely | Licence not stated on download page | AMBER |
| HPO hp.json and phenotype.hpoa | Yes | Only unaltered, cited, versioned | AMBER |
| CADEC | Only if our use counts as non-commercial | No, licence forbids distribution | RED for repo |
| SMM4H | Maybe, on request | No, tweets and request-only | RED this week |
| Micromed | UNVERIFIED | UNVERIFIED | RED until checked |
| n2c2 / i2b2 | No (DUA) | No | RED |
| MIMIC | No (credentialed, no third-party or API sharing) | No | RED |
| BioCreative VIII Track 3 | Registration, terms UNVERIFIED | UNVERIFIED | AMBER to RED |

## 4. Full per-dataset table

Columns: size, genre, language, annotation, negation, licence as stated, access and speed.

### 4.1 Patient-written and social media

**CADEC (CSIRO AskaPatient)**
- URL: https://data.csiro.au/collection/csiro:10948 and https://researchdata.edu.au/cadec/3378330 (DOI 10.4225/08/570FB102BDAD2, version 3, 2016-04-15).
- Size: 1,250 forum posts on 12 drugs (from search results describing the corpus).
- Genre: lay, patient-written drug reviews. English.
- Annotation: spans for ADR, drug, finding, disease, symptom. Mapping of spans to SNOMED CT and MedDRA is described in the Karimi et al. paper (https://arxiv.org/pdf/1504.06936) but not verified on the data page: UNVERIFIED. Negation as a flag: not seen, UNVERIFIED.
- Licence: "Other", the CSIRO Data Licence, "All Rights (including copyright) CSIRO 2015". Section 2.1 grants a licence "to use the Data solely for your non commercial purposes". Section 2.2: "You may not distribute the Data to any other person." Rights are "not sub-licensable". The licence page says it was retired for new collections on 15 July 2021 (https://research.csiro.au/dap/licences/csiro-data-licence/).
- (a) Training for a public hackathon demo: amber. A company team building a product demo may count as "profit or gain". Treat as private research use only. (b) Redistribute derived data: no. Adapted forms stay under the same restriction.
- Access: open and free, same day. HuggingFace mirrors (KevinSpaghetti/cadec, akramRedjdal/cadec-ner-dataset-clean, others, https://huggingface.co/api/datasets?search=cadec) list no licence. Mirrors do not remove the CSIRO terms.

**PsyTAR**
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6495095 and https://huggingface.co/datasets/bigbio/psytar.
- Size: 891 drug reviews from askapatient.com (Zoloft, Lexapro, Cymbalta, Effexor XR). Sentence and span counts not confirmed: UNVERIFIED.
- Genre: lay, patient-written. English.
- Annotation: spans for adverse reactions, withdrawal symptoms, signs and symptoms of the illness, drug indications, effectiveness. The paper describes mapping to medical vocabularies, but I could not confirm UMLS or SNOMED IDs in the released file: UNVERIFIED. Negation as a flag: not mentioned, UNVERIFIED.
- Licence: paper states the data is under "CC BY 4.0 Data" license. HuggingFace card: "cc-by-4.0", 43 kB total.
- (a) Yes. (b) Yes with attribution. The underlying text was scraped from a public forum, so keep the attribution and the citation intact.
- Access: open download, same day. Best single real lay corpus we can legally publish.

**SMM4H shared tasks (ADE in tweets and Reddit, plus later tasks)**
- URL: https://healthlanguageprocessing.org/smm4h-2025/ (page not opened, UNVERIFIED). Overview papers via https://aclanthology.org.
- Size: varies by year and task. 2022 covered English and Spanish on Twitter, Reddit, WebMD. 2024 added Japanese, German, French. 2025 had six tasks (ADE and vaccine events, substance use, dementia caregiving, insomnia, foodborne outbreaks).
- Genre: lay, social media. Multilingual, no Italian found.
- Annotation: ADE span extraction and some normalization (task dependent). Negation: not a standard layer.
- Licence: overview papers say data is available "upon request". No dataset licence found. The CC BY 4.0 on the NAIST record covers the paper and does not cover the data (https://naist.repo.nii.ac.jp/records/2001050).
- (a) Unclear. (b) No: tweet text is also bound by platform terms.
- Access: registration form and organizer approval, days to weeks (UNVERIFIED). Not usable this week.

**TwiMed**
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5438461 and https://www.repository.cam.ac.uk/handle/1810/291990.
- Size: 1,000 tweets and 1,000 PubMed sentences, 3,144 entities, 2,749 relations, 5,003 attributes.
- Genre: lay (tweets) plus scientific (PubMed). English.
- Annotation: drugs, diseases, symptoms, relations, attributes. Normalization ontology and negation: UNVERIFIED.
- Licence: the Cambridge record shows "Attribution 4.0 International" for the article. Dataset licence not found: UNVERIFIED. Other groups report only 663 tweets retrievable under Twitter's terms.
- (a) Probably. (b) Only IDs for tweets, with no text. Amber.
- Access: download location not confirmed, UNVERIFIED.

**Micromed (Jimeno-Yepes et al., 2015)**
- Described in search results as a Twitter corpus annotated with disease, drug, and symptom mentions. Not a CSIRO forum corpus. I could not find the download, size, or licence. Treat as UNVERIFIED and skip.

**COMETA**
- URL: https://github.com/cambridgeltl/cometa, paper https://arxiv.org/abs/2010.03295.
- Size: about 20k expert-annotated entity mentions (paper abstract, via search results) from 68 health subreddits over four years (README). Exact document counts not confirmed.
- Genre: lay Reddit posts. English.
- Annotation: mention-level linking to SNOMED CT with a General and a Specific identifier. Not a full span-extraction-in-document corpus. No negation layer found.
- Licence: repository shows an MIT licence file (copyright 2025 Cambridge Language Technology Lab), which governs code. The README names no licence for the corpus. SNOMED CT licensing is not discussed. The text originates from Reddit. Data licence: UNVERIFIED.
- (a) Probably for research. (b) Do not redistribute until the data licence is confirmed with the authors.
- Access: Google Drive and Dropbox links in the README, same day.
- Value: best source of real lay-phrase to concept pairs (for example slang for symptoms). Use for term-normalization eval and for seeding synthetic data prompts.

**RHMD (Reddit health mention dataset)**
- 10,015 labeled Reddit posts mentioning 15 diseases or symptoms, GitHub (https://researchers.mq.edu.au/en/publications/rhmd-a-real-world-dataset-for-health-mention-classification-on-re/). Post-level classification (personal, non-personal, figurative, hyperbolic), with no spans. Licence UNVERIFIED. Useful only to filter real versus figurative mentions ("this headache of a meeting").

### 4.2 Scientific and clinical text with ontology normalization

**MedMentions**
- URL: https://github.com/chanzuckerberg/MedMentions.
- Size: 4,392 PubMed titles and abstracts. Mention total is not on the page.
- Genre: scientific. English. Annotation: UMLS (2017AA) concept IDs and semantic types, PubTator format. No negation.
- Licence: "This data is being released under the CC0 license."
- (a) Yes. (b) Yes. Using the CUI mapping to HPO needs a UMLS licence on the developer's side (free, individual, https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/release/license_agreement.html), and that licence forbids distributing Metathesaurus subsets.
- Access: open, same day. Low relevance to lay text.

**NCBI Disease**
- URL: https://www.ncbi.nlm.nih.gov/research/bionlp/Data/disease/. 793 abstracts, 6,892 disease mentions, MeSH and OMIM, 790 unique concepts. Scientific, English. No negation mentioned. Licence not stated on the page (links NLM web policies): UNVERIFIED. Low relevance.

**BC5CDR**
- 1,500 PubMed articles, 5,818 diseases, 4,409 chemicals, MeSH. Scientific, English. Licence: HuggingFace loader lists Public Domain Mark 1.0, and the paper record says US government authors, public domain in the US. Both are secondary. Official repo not checked: UNVERIFIED. Low relevance.

**GSC+ and the HPO gold standard corpus (Groza et al.)**
- URL: https://data.monarchinitiative.org/hpo/README.txt (hpo_corpus.tar.gz, 228 manually annotated OMIM-cited abstracts, stand-off "start::end HPO URI | text"). GSC+ extends it. Counts conflict across sources (1,933 annotations or 2,773 mentions, 497 unique HPO IDs). PhenoTagger repo ships corpora in data/corpus.zip (https://github.com/ncbi-nlp/PhenoTagger).
- Genre: scientific abstracts. English. HPO IDs native. Negation: none found.
- Licence: README only points to https://hpo.jax.org/app/license. See section 6. PhenoTagger repo is MIT, which does not obviously cover the corpus.
- Access: open, same day. Native HPO labels make it the right sanity-check eval for ID accuracy and a poor one for lay language.

**ID-68**
- Described as 68 real clinical notes (Anazi et al., 2017) used by PhenoBERT and AutoPCR (https://arxiv.org/pdf/2507.19315). I could not find a public download or licence: UNVERIFIED. Skip.

**PhenoTagger and PhenoBERT data**
- PhenoTagger builds its training set by distant supervision from the HPO ontology file itself (no hand labels) and uses GSC+ as dev. Code is MIT per the repo page. This validates our synthetic plan: ontology labels plus synonyms generate usable training data. PhenoBERT data: UNVERIFIED.

**BioCreative VIII Track 3 (dysmorphology exams to HPO)**
- 3,136 de-identified observations from 1,652 pediatric patients at CHOP, normalized to HPO (overview: https://doi.org/10.1093/database/baaf051; track resources need registration per https://biocreative.bioinformatics.udel.edu/). Genre: clinical, terse. English. HPO native. Licence and post-competition access: UNVERIFIED. Registration, possibly days. Not lay text, so low value for us.

**n2c2 / i2b2**
- Data use agreement and institutional sign-up. The n2c2 site returned HTTP 403 to my fetch, so terms are UNVERIFIED. No HPO labels, clinical register. Weeks. Skip.

**MIMIC (III, IV notes)**
- PhysioNet credentialed licence. The licence says "The LICENSEE will not share access to PhysioNet restricted data with anyone else" and limits use to "lawful use in scientific research" (https://physionet.org/content/mimiciv/view-license/3.1/). PhysioNet's 2025 notice prohibits sending the data to third-party LLM APIs unless zero retention, no training, and no human review can be verified (https://physionet.org/news/post/llm-responsible-use). Credentialing (training course plus DUA) takes days to weeks. No symptom or HPO annotations. Skip.

### 4.3 Multilingual and Italian

**E3C (European Clinical Case Corpus)**
- URL: https://e3c.fbk.eu/, https://nlplab.fbk.eu/projects/e3c, https://live.european-language-grid.eu/catalogue/corpus/7618.
- Languages: Italian, English, Spanish, French, Basque. Layers: manual entities, temporal info, and factuality (layer 1), semi-automatic entities (layer 2), unannotated (layer 3). Entities: pathologies, symptoms, procedures, body parts. Factuality covers negation, uncertainty, hedge per the project page.
- Genre: clinical case reports, which are not lay.
- Licence: a search snippet states "Creative Commons License Attribution 4.0 International (CC BY 4.0)". The project pages I opened do not state a licence, and the ELG page did not render: UNVERIFIED on primary source.
- HuggingFace: NLP-FBK/e3c-sentences-IT-revised has 1,471 sentences (train 632, validation 101, test 738), one entity type CLINENTITY, no licence tag on the card (https://huggingface.co/datasets/NLP-FBK/e3c-sentences-IT-revised). Caution: the card describes this as the English layer 1 projected into Italian, so it is projected data and is not native Italian annotation. DrBenchmark/E3C has about 27.7k rows across five languages (https://huggingface.co/datasets/DrBenchmark/E3C), integer NER tags, empty README, no licence.
- Access: open, same day.

**SympTEMIST (BSC, BioCreative VIII)**
- URL: https://zenodo.org/records/10635215.
- Size: 1,000 Spanish clinical case reports, 12,196 annotations (search results), 452.8 MB archive (not downloaded). Annotation: symptom, sign, finding spans normalized to SNOMED CT. Negation not mentioned on the record.
- Licence: "Creative Commons Attribution 4.0 International (CC BY 4.0)", access open.
- Italian: the record lists a multilingual silver standard that search results say includes Italian. Silver means machine-produced, quality UNVERIFIED.
- Genre: clinical case reports. Spanish. Useful for symptom span style, and the SNOMED-to-HPO bridge could be tested.

**Other Italian resources found**
- PharmaER.IT: Italian drug leaflets, 57 leaflets, 16,833 entity mentions in the GOLD corpus, includes symptoms (from search results). Leaflet register, licence UNVERIFIED.
- Italian EHR corpus (Pisa, arpi.unipi.it) and CardioCCC (BSC MultiCardioNER): clinical, licences UNVERIFIED.
- NLP-FBK/medical-wikipedia-italian: cc-by-sa-4.0, unannotated Italian medical text, usable only as a vocabulary source (https://huggingface.co/datasets/NLP-FBK/medical-wikipedia-italian). Share-alike applies to anything derived from it.
- ItaCare and SIMPITIKI: I found nothing relevant. UNVERIFIED, not recommended.
- No Italian patient-forum symptom corpus found.

### 4.4 Lay vocabularies and HPO resources

**HPO layperson synonyms**
- Work by Vasilevsky et al. adds non-expert synonyms to HPO classes. Preprint: https://zenodo.org/records/1168737 (CC BY 4.0, but the preprint only). Over 6,000 classes carry layperson synonyms, about 36% of terms (ICBO 2018 abstract, via search results). Sources include Wikipedia, MedlinePlus, Mayo Clinic, OMIM, and patient forums.
- The synonyms live inside hp.json, so the HPO licence applies. How layperson synonyms are tagged in the file (synonym scope or a flag): UNVERIFIED. Inspect the pinned hp.json before relying on a filter.
- Italian: HPO translations run through the HPO Translation Effort (Crowdin and Babelon TSV, https://github.com/obophenotype/hpo-translations). Whether Italian exists and how complete it is: UNVERIFIED.

**Consumer Health Vocabulary (CHV)**
- URL: https://biomedinfo.smhs.gwu.edu/chv-files. Open-access and collaborative CHV, flat files, last updated 2011-02-04. A later paper reports 158,519 terms and 57,819 UMLS CUIs. Download page states no licence. CHV is also a UMLS source (https://www.nlm.nih.gov/research/umls/sourcereleasedocs/current/CHV, restriction category not retrieved): UNVERIFIED.
- Genre: lay terms mapped to concepts, English. No spans, no negation.
- Value: high. Lay phrase to CUI, then CUI to HPO via the HPO xrefs, gives a big lay lexicon for synthetic generation.

**MedlinePlus**
- Not fetched. Plain-language health text from NLM, terms of use UNVERIFIED. Useful as a lay phrasing reference only, do not ingest into the repo.

### 4.5 HuggingFace hub scan

Searches run on the HF API (symptom, HPO, medical ner, italian medical, cadec, e3c).

| Dataset | Relevance | Licence shown | Note |
|---|---|---|---|
| biololab/symptom_ner_cases | Symptom NER by name | Gated (manual approval) | Content unknown, UNVERIFIED. Request access, treat as private. |
| biololab/hpo_spanish_synonims | Spanish HPO synonyms | Gated, none | Spanish only. |
| junliang/symptom | Token classification | "Other", Chinese | Wrong language. |
| pandalla/datatager_symptom_recognition_and_advice | Symptom recognition from consultation text | Apache-2.0 | Language and provenance UNVERIFIED. |
| gretelai/symptom_to_diagnosis | Free-text symptom to diagnosis classification | Apache-2.0 | Classification only, no spans. Likely synthetic. |
| mfaruqi/indonesian-medical-ner | Patient forum complaints | cc-by-nc-4.0 | Indonesian, non-commercial. |
| bigbio/psytar | PsyTAR mirror | cc-by-4.0 | Use this one. |
| NLP-FBK/e3c-sentences-IT-revised | Italian clinical entities | None shown | See E3C. |

No lay-language HPO or symptom NER corpus with a permissive licence turned up on the hub.

## 5. Anthropic terms: can we finetune a small extraction model on Claude-generated data?

**Verdict: AMBER to RED. Not clearly permitted for our use, and the safest course is to avoid it or get written permission.**

Quoted clauses:

1. Commercial Terms of Service, effective June 17, 2025, Section D.4 (https://www.anthropic.com/legal/commercial-terms): "Customer may not and must not attempt to (a) access the Services to build a competing product or service, including to train competing AI models or resell the Services except as expressly approved by Anthropic". Section B: "Anthropic hereby assigns to Customer its right, title and interest (if any) in and to Outputs." Section D.2 incorporates the Usage Policy.
2. Claude Help Center, "Can I use my outputs to train an AI model?", published March 16, 2026 (https://support.claude.com/en/articles/12326764-can-i-use-my-outputs-to-train-an-ai-model): "You can use Claude's Outputs to train models that don't compete with Anthropic's own models." It lists information extraction tools among the permitted examples. The same article says "We prohibit customers from using our services to train or develop AI models without our written permission", and lists "Using Outputs as training targets for models" among prohibited uses. The article does not say how to request permission.
3. Usage Policy (https://www.anthropic.com/legal/aup), shown on the page as "Effective November 12, 2026", which is after today's date. Under "Do Not Abuse Our Platform": "Use outputs to train an AI model (e.g., 'model scraping' or 'model distillation') without prior authorization from Anthropic". The page links a Previous Version I could not retrieve, so I cannot say what the in-force wording is today. A third-party tracker (ConductAtlas) shows the clause record as withdrawn from publication, which adds to the uncertainty.

Plain reading:
- Ownership of outputs is ours, but ownership and permission to train are separate questions.
- Clause 1 and the permitted-uses list in clause 2 support the view that a narrow symptom-extraction model does not compete with Claude, so it is allowed.
- Clause 2's other sentences and clause 3 are broader: they ask for written permission or prior authorization for any training on outputs. A strict reading puts our plan outside the allowed zone until we have that permission.
- Because the wording conflicts and one source carries a future effective date, treat it as unresolved. Do not rely on the permissive reading for a public demo.

Practical consequences:
1. Ask Anthropic for written permission, citing a narrow extraction model, if Claude-generated data is wanted. Do not wait on it for the build week.
2. Generate synthetic data with an open-weights model on the AMD cloud. Gemma 4 e4b-it is listed as Apache 2.0 on its HuggingFace card (https://huggingface.co/google/gemma-4-e4b-it). The linked Google licence document was not read, so confirm it does not add output-use restrictions: UNVERIFIED.
3. Do not use Claude to label real text that becomes training targets. Using Claude as an eval judge or for writing prompts and templates by hand does not create training targets, which is the lower-risk use, though still not covered by an explicit grant.
4. Any Claude-generated rows already made should be tagged and kept out of the training set and the public repo until permission arrives.

## 6. HPO, hp.json, phenotype.hpoa, and Orphanet licensing

- HPO files point to a custom licence at https://hpo.jax.org/app/license (also listed by OBO Foundry, https://obofoundry.org/ontology/hp.html, with license name "hpo"). The page returned HTTP 404 to my fetch, so I read the terms from the Leicester vocabulary mirror (https://www162.lamp.le.ac.uk/vocabularies/hpo) and HL7's copy (https://terminology.hl7.org/CodeSystem-HPO.html), both reproducing "Original license terms". Current wording on the HPO site: UNVERIFIED.
- Three conditions: (1) "That the Human Phenotype Ontology Consortium is acknowledged and cited properly." (2) "That any HPO Consortium file(s) displayed publicly include the date(s) and/or version number(s) of the relevant HPO file(s)." (3) That neither the content of the HPO files nor the logical relationships embedded within them be altered in any way. A request to include the HPO logo is also made.
- Reading for us: using HPO IDs and labels in a model and a demo is fine with citation and a version string. Committing a filtered or edited copy of hp.json to a public repo risks breaking condition 3. Commit a download script that pins the release instead, and ship only IDs plus the release tag in training data.
- phenotype.hpoa and Orphanet: the Monarch README for HPO files points to the same licence page, with no separate terms. phenotype.hpoa mixes annotations from several sources including OMIM and Orphanet. I did not verify the upstream terms for OMIM (commonly restrictive) or Orphanet (commonly CC BY 4.0): both UNVERIFIED. Clario does not need disease-to-phenotype annotations for symptom extraction. Skip phenotype.hpoa.
- UMLS: free but individual, and "LICENSEE is prohibited from distributing the UMLS Metathesaurus or subsets of it". A CUI to HPO crosswalk table built from UMLS must not be committed.

## 7. Recommended plan for this week

Use four sources.

**1. Synthetic training set (open model on AMD cloud), seeded from HPO and CHV**
- Seeds: HPO labels and layperson synonyms from a pinned hp.json (download in the build step), CHV lay phrases (private, not committed), COMETA lay phrases (private until licence confirmed).
- Generate diary entries in English and Italian with entity spans, negation, severity, and type. HPO IDs come from the seed term, so labels are exact by construction (same logic as PhenoTagger's distant supervision).
- Italian: seed from HPO Italian labels if present (UNVERIFIED), otherwise have the generator produce Italian lay variants and spot-check 100 by a native reader.

**2. PsyTAR (CC BY 4.0), real lay text for train augmentation and eval**
- Hold out a test slice for eval before any training. Use the rest for light real-text augmentation.
- Map labels: PsyTAR span categories to Clario type (adverse reaction or sign or symptom to symptom, drug indication to skip or context). HPO IDs: run the strongest HPO normalizer available plus manual review for the eval slice.

**3. Hand-built Clario gold set (EN 100 to 150, IT 100 to 150)**
- Real, non-synthetic, and ours, so it can be public. Sample real lay sentences from PsyTAR for English. For Italian write diary-style entries from real patient-phrasing patterns, annotated by two people with adjudication on a 30-doc overlap.
- Report agreement and keep annotators' guidelines in the repo.

**4. COMETA (private use) for lay-term normalization eval, and E3C Italian as a clinical-register stress test**
- COMETA: measure how often the model's canonical term and HPO ID agree with the SNOMED target after the crosswalk. Never publish the raw data until the authors confirm a licence.
- E3C IT: check span recall for symptom-type entities. Remember the HF Italian sentence set is projected from English.

**Label mapping to HPO**
1. Source label (SNOMED CT, UMLS CUI, MeSH, MedDRA) to HPO ID through the xrefs in a pinned hp.json (UMLS, SNOMEDCT_US, MSH cross-references are expected in the file, check in the pinned release). Use a UMLS licence on the developer machine for CUI lookups.
2. Unmapped lay phrases: embedding or LLM-free fuzzy match against HPO labels plus layperson synonyms, then manual review of the eval slice.
3. Spans with no HPO equivalent: keep as canonical term with HPO ID null. Do not force a wrong ID.
4. Negation: none of the real corpora gives a clean negation flag, so derive it for the eval slice by hand and for synthetic data by construction. Run NegEx-style or manual checks on PsyTAR spans.

**Keep out of the public repo**
- CADEC and any file derived from it (CSIRO Data Licence: no distribution, non-commercial).
- Raw COMETA, TwiMed tweet text, SMM4H, RHMD text until licences are confirmed.
- Any MIMIC, n2c2, or BioCreative Track 3 data (credentialed or registered).
- UMLS-derived crosswalks, MedMentions CUI-to-text bridge tables, SNOMED CT content.
- Modified copies of hp.json or phenotype.hpoa. Commit the download script and the release tag.
- Any Claude-generated training rows, pending written permission.
- CHV flat files (licence not stated), until confirmed.

## 8. Open items to settle fast

1. Confirm the COMETA data licence with the Cambridge LTL authors (one email).
2. Read the pinned hp.json to see how layperson synonyms and Italian labels are encoded, and whether UMLS and SNOMED xrefs are present.
3. Decide whether to email Anthropic for written permission or drop Claude from the data pipeline.
4. Confirm the Gemma 4 licence document at ai.google.dev has no output-use restrictions.
5. Check PsyTAR's released files for UMLS or SNOMED IDs and negation fields.

"""Synthetic workloads for the Clario bench. No real patient data."""

EXTRACT_SYSTEM = (
    "You read one entry from a patient's symptom diary. Extract every symptom, sign or relevant "
    "context as an entity. Each entity must quote a verbatim span from the entry. "
    "Reply with JSON only: {\"entities\": [{\"span\": str, \"concept\": str, \"negated\": bool, "
    "\"severity\": \"mild\"|\"moderate\"|\"severe\"|null}]}. No prose, no markdown."
)

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["entities"],
    "properties": {"entities": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["span", "concept", "negated", "severity"],
        "properties": {
            "span": {"type": "string"}, "concept": {"type": "string"},
            "negated": {"type": "boolean"},
            "severity": {"type": ["string", "null"], "enum": ["mild", "moderate", "severe", None]}}}}},
}

DIARY = [
    "Woke up with my knees really stiff, took about an hour to loosen up. Tired by 3pm again.",
    "Another migraine behind my left eye, lights were way too bright. Lay in the dark most of the afternoon.",
    "Hands were numb and tingly when I woke up, mostly my ring and pinky fingers. Gone after I shook them out.",
    "No fever today but I'm so wiped out I could barely climb the stairs. Heart was racing when I stood up too fast.",
    "Stomach cramps after lunch, bloated like crazy. Ran to the bathroom twice. Haven't had this in a few days though.",
    "Couldn't find my words in the meeting, felt foggy all day. Slept 9 hours and still exhausted.",
    "My jaw clicks and aches when I chew, especially on the right. Mild headache too.",
    "Rash on both cheeks again after a walk in the sun. Joints in my fingers are sore and a bit puffy.",
    "Dizzy for a few minutes when I got out of bed, the room was spinning. Passed on its own. No fainting.",
    "Legs felt heavy like lead on the walk to the bus. Muscle cramps in my calves at night, woke me twice.",
    "Mouth ulcers are back, three this time. Dry eyes too, they feel gritty by evening.",
    "Bad night. Pain in my lower back and hips, worse in the morning, better once I move around. No numbness.",
    "Cold fingers turned white and then blue at the supermarket freezer aisle, then red and throbbing.",
    "Constantly thirsty, up three times last night to pee. Blurry vision this afternoon, probably nothing.",
    "Heart fluttering for maybe ten minutes while I was resting. Not painful, just weird. Anxious afterwards.",
    "My hair is coming out in clumps in the shower. Also very cold all the time, even in the office.",
    "Hip hurts when I climb stairs, left side. Walked with a bit of a limp this morning.",
    "Brain fog is better today. Still had the burning feeling in my feet at night, worse than last week.",
    "Throat is sore and my neck glands are swollen. Night sweats again, soaked the sheets.",
    "Skin on my elbows is red and flaky, itchy. Nails look pitted. Knee a bit swollen.",
    "I fainted briefly in the kitchen, only a few seconds, my sister saw it. Felt hot and nauseous before.",
    "Double vision for about twenty minutes in the evening, right eye droopy. Better after resting.",
    "Short of breath walking up one flight, never used to be. Ankles are swollen at the end of the day.",
    "Slept badly, restless legs again, had to keep moving. Tired and irritable all day.",
    "Ear ringing in the left ear, muffled hearing. Not dizzy today, which is a relief.",
    "Shooting pain down the back of my right leg when I sit too long. Toes tingle a little.",
    "Easy bruising this week, found three big ones on my thighs and no idea how. Gums bleed when I brush.",
    "Lost my appetite and dropped a couple of kilos this month without trying. Constant nausea in the morning.",
    "Joints all over ache, but my elbows and wrists are the worst. Hypermobile, I can bend my thumb to my arm.",
    "Felt great today, no pain, no fatigue, walked 40 minutes. Wondering if this is just a good day.",
]

# ~2,000-token shared package summary: fixed prefix so prefix caching is exercised realistically.
_WEEKS = [
    ("2026-08-03", "Morning stiffness in both knees lasting 45 to 60 minutes on 5 of 7 days. Fatigue by mid-afternoon on 6 days. One migraine with photophobia."),
    ("2026-08-10", "Stiff knees and hands in the morning, 60 minutes. Cheek rash after sun exposure on two days. Mouth ulcers (two). Fatigue daily, sleep 8 to 9 hours."),
    ("2026-08-17", "Joint pain in fingers and wrists with mild swelling. Dry gritty eyes in the evening on 4 days. Brain fog on 3 days. No fever recorded."),
    ("2026-08-24", "Raynaud-like colour change in fingers in cold (white, blue, red) twice. Fatigue daily. Hair shedding noted in the shower. Mild headache on 4 days."),
    ("2026-08-31", "Rash on cheeks, one episode lasting two days. Swollen finger joints on waking. Night sweats once. Shortness of breath on one flight of stairs, new."),
    ("2026-09-07", "Mouth ulcers (three). Knee stiffness 30 to 60 minutes. Palpitations once for ten minutes at rest. Dizziness on standing, twice, no fainting."),
    ("2026-09-14", "Fatigue daily, worse after poor sleep. Joint pain in elbows and wrists. Dry eyes. Ankle swelling at end of day on 3 days."),
    ("2026-09-21", "Cheek rash after sun, fingers white in cold. Morning stiffness 45 minutes. One day without symptoms. Concentration problems at work on 4 days."),
]
_TERMS = [
    ("morning stiffness", 31, "strong"), ("fatigue", 38, "strong"), ("photosensitive skin rash", 6, "moderate"),
    ("oral ulcers", 7, "moderate"), ("dry eyes", 11, "moderate"), ("Raynaud phenomenon", 4, "moderate"),
    ("arthralgia of fingers and wrists", 19, "strong"), ("joint swelling", 9, "moderate"),
    ("cognitive difficulty (brain fog)", 14, "moderate"), ("alopecia (shedding)", 3, "weak"),
    ("palpitations", 2, "weak"), ("orthostatic dizziness", 3, "weak"), ("dyspnea on exertion", 2, "weak"),
    ("peripheral edema", 5, "weak"), ("night sweats", 2, "weak"), ("headache", 12, "moderate"),
]


def _package_summary() -> str:
    lines = ["PATIENT PACKAGE (alias P-4821), period 2026-08-03 to 2026-09-27, 56 entries, shared for visit on Thursday.", "",
             "WEEKLY DIARY DIGEST (patient wording, condensed):"]
    for d, t in _WEEKS:
        lines.append(f"- Week of {d}: {t}")
    lines += ["", "CONFIRMED TERMS (patient confirmed, with evidence counts):"]
    for label, n, lvl in _TERMS:
        lines.append(f"- {label}: {n} entries, signal {lvl}")
    lines += ["", "PATTERN SIGNALS (deterministic overlap score, not a diagnosis):",
              "- Resembles a multi-system autoimmune connective tissue picture: moderate (joint, skin, mucosal, fatigue terms overlap).",
              "- Resembles an inflammatory arthritis picture: weak to moderate (morning stiffness > 30 min, small-joint pain).",
              "- Resembles Sjogren-type sicca picture: weak (dry eyes, mouth ulcers; dry mouth not recorded).",
              "", "WHAT IS MISSING: no lab results, no dry mouth record, no temperature log, no medication list, no family history.", ""]
    # Pad with per-entry evidence lines to reach ~2,000 tokens, fixed text so the prefix is identical across calls.
    for i, snip in enumerate(DIARY):
        lines.append(f"EVIDENCE entry E{i+1:02d}: \"{snip}\"")
    lines += ["", "DATED ENTRY LOG (first 12 entries):"]
    for i, snip in enumerate(DIARY[:12]):
        lines.append(f"2026-08-{i+3:02d} E{i+1:02d} (confirmed by patient): {snip}")
    return "\n".join(lines)


PACKAGE_SUMMARY = _package_summary()

BRIEF_SYSTEM = (
    "You draft a one-page clinician brief from a patient's shared symptom package. "
    "Never diagnose and never recommend treatment. Use hedged phrasing such as 'resembles' or 'consider discussing'. "
    "Every item must cite entry ids from the package. Reply with JSON only: "
    "{\"summary\": str, \"timeline\": [{\"item\": str, \"cites\": [str]}], "
    "\"patterns\": [{\"item\": str, \"level\": \"weak\"|\"moderate\"|\"strong\", \"cites\": [str]}], "
    "\"missing\": [str], \"questions_for_visit\": [str]}"
)

BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "timeline", "patterns", "missing", "questions_for_visit"],
    "properties": {
        "summary": {"type": "string"},
        "timeline": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["item", "cites"], "properties": {"item": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}}},
        "patterns": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["item", "level", "cites"], "properties": {"item": {"type": "string"},
            "level": {"type": "string", "enum": ["weak", "moderate", "strong"]}, "cites": {"type": "array", "items": {"type": "string"}}}}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "questions_for_visit": {"type": "array", "items": {"type": "string"}}},
}

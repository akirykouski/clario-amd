"""Synthetic demo diary. Giulia, 29, Milan: ten weeks of plain-language notes.

Written to resemble a real pre-diagnosis period (joint pain, rash after sun, mouth sores, fatigue,
hair loss, a lab result), with everyday noise. Entirely fictional.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

GIULIA = [
    (70, "Really tired all week, even after 9 hours of sleep. Climbing the stairs to the office felt like a mountain.", 4),
    (66, "My knees and the small joints in my fingers ache in the morning, stiff for about an hour before they loosen up.", 4),
    (63, "Long lunch outside at the lake on Sunday. By evening my cheeks and nose went red, like a butterfly shape. It burned a bit.", 5),
    (59, "Sore in my mouth again, on the roof of the mouth. It doesn't hurt much but it's the third one this month.", 5),
    (55, "Fingers turned white and then blue in the cold this morning waiting for the tram. Took ages to warm up.", 4),
    (52, "Knees ache 6/10 today. No fever. Work was stressful but I don't think that's it.", 3),
    (48, "Noticed more hair than usual in the shower drain. Brushing it, it comes out in small clumps.", 3),
    (45, "Feeling a bit better this week, more energy. Went for a short walk.", 7),
    (41, "Red rash on my cheeks came back after a sunny afternoon at the market.", 4),
    (37, "Chest hurts when I take a deep breath, sharp, on the left side. Better when I sit forward. Lasted two days.", 3),
    (34, "Low fever in the evening, 37.9. Joints in my wrists swollen.", 3),
    (30, "GP blood test: she said there is protein in my urine and my white cells are a bit low. Another test in a month.", 4),
    (26, "Mouth sore again. Tired. Ankles a little puffy at the end of the day.", 3),
    (21, "Wrists and fingers stiff and swollen in the morning, could not open a jar.", 3),
    (17, "Good weekend, slept well, no pain on Saturday.", 7),
    (13, "Rash on my cheeks after 20 minutes in the sun. Headache in the afternoon.", 4),
    (9, "Fingers went white again in the supermarket freezer aisle.", 4),
    (5, "Exhausted. Hair still falling out. Knees and wrists ache, 5/10.", 3),
    (2, "Writing down questions for the rheumatology appointment on Thursday. I want to ask about the joint pain and the rash.", 5),
]


# Same clinical picture in everyday Italian: a negation ("niente febbre"), a relative's condition ("mia madre ha il lupus"),
# onset hints ("da lunedì"), a 0-10 rating ("6/10"), two hedged sentences that land in the review queue.
GIULIA_IT = [
    (70, "Stanchissima da lunedì, anche dopo nove ore di sonno. Le scale per salire in ufficio sembravano una montagna.", 4),
    (66, "Le ginocchia e le dita delle mani mi fanno male la mattina, rigide per un'oretta prima di sciogliersi.", 4),
    (63, "Pranzo lungo all'aperto sul lago, domenica. Verso sera guance e naso erano rossi, a forma di farfalla. Bruciava un po'.", 5),
    (59, "Di nuovo una piaga in bocca, sul palato. Non fa tanto male ma è la terza questo mese.", 5),
    (55, "Stamattina in attesa del tram le dita sono diventate bianche e poi blu per il freddo. Ci hanno messo una vita a scaldarsi.", 4),
    (52, "Ginocchia che fanno male, 6/10 oggi. Niente febbre. Il lavoro è stressante ma non credo c'entri.", 3),
    (48, "Ho notato più capelli del solito nello scarico della doccia. Spazzolandoli vengono via a ciocche.", 3),
    (45, "Questa settimana va un po' meglio, più energia. Ho fatto una breve passeggiata. Mia madre ha il lupus, me l'ha detto solo ora, e ci sto pensando.", 7),
    (41, "Forse il rossore sulle guance è tornato dopo un pomeriggio di sole al mercato.", 4),
    (37, "Mi fa male il petto quando faccio un respiro profondo, una fitta a sinistra. Va meglio se mi siedo in avanti. È durato due giorni.", 3),
    (34, "Un po' di febbre alla sera, 37,9. Polsi gonfi.", 3),
    (30, "Esami del sangue dal medico: dice che ho proteine nelle urine e i globuli bianchi un po' bassi. Altro controllo fra un mese.", 4),
    (26, "Mi sembra di nuovo una piaga in bocca. Stanca da tre giorni. Caviglie un po' gonfie a fine giornata.", 3),
    (21, "Polsi e dita rigidi e gonfi al mattino, non riuscivo ad aprire un barattolo.", 3),
    (17, "Bel weekend, ho dormito bene, sabato tutto tranquillo.", 7),
    (13, "Rossore sulle guance dopo venti minuti al sole. Mal di testa nel pomeriggio.", 4),
    (9, "Le dita sono diventate bianche di nuovo, al banco frigo del supermercato.", 4),
    (5, "Esausta. I capelli continuano a cadere. Ginocchia e polsi fanno male, 5/10.", 3),
    (2, "Sto scrivendo le domande per la visita di reumatologia di giovedì. Voglio chiedere del dolore alle articolazioni e dell'eruzione sul viso.", 5),
]

PERSONAS = {"giulia": GIULIA, "giulia_it": GIULIA_IT}
PERSONA_LANG = {"giulia": "en", "giulia_it": "it"}
DEMO_DIR = Path(__file__).parent / "data" / "demo"


def persona_entries(persona: str, today: date | None = None) -> list[tuple[str, str, int]]:
    today = today or date.today()
    return [((today - timedelta(days=d)).isoformat(), text, mood) for d, text, mood in PERSONAS[persona]]


def giulia_entries(today: date | None = None) -> list[tuple[str, str, int]]:
    return persona_entries("giulia", today)


def demo_referti() -> list[Path]:
    """The three synthetic Italian lab reports shipped with the app (generated by scripts/make_referti.py)."""
    return sorted(DEMO_DIR.glob("ref_*.pdf"))

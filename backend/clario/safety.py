"""Safety rules that run in code, before and after any model call.

1. Red-flag interceptor: emergency descriptions in a diary entry get an immediate notice.
2. Hedge validator: AI-written text that sounds like a diagnosis or treatment advice is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY_NUMBER = "112"


@dataclass
class SafetyNotice:
    level: str  # "emergency" | "advice"
    message: str
    matched: str

    def as_dict(self) -> dict:
        return {"level": self.level, "message": self.message, "matched": self.matched}


# (pattern, label in English, label in Italian)
_EMERGENCY = [
    (r"\b(chest (pain|pressure|tightness))\b.*\b(breath|arm|jaw|sweat)", "chest pain with other warning signs",
     "dolore al petto con altri segnali di allarme"),
    (r"\b(can'?t|cannot|unable to|struggling to) breathe\b|\bthroat (is )?(closing|swelling)\b", "trouble breathing",
     "difficoltà a respirare"),
    (r"\b(face (is )?droop|slurred speech|one side of (my|the) (body|face) (is )?(numb|weak))", "stroke signs",
     "segni di ictus"),
    (r"\b(kill myself|end my life|suicid|want to die|self[- ]harm|hurt myself)\b", "thoughts of self-harm",
     "pensieri di farsi del male"),
    (r"\b(coughing|vomiting|throwing up) (up )?blood\b|\bbleeding (that )?(won'?t|will not) stop\b", "serious bleeding",
     "sanguinamento grave"),
    (r"\bseizure\b.*\b(won'?t stop|more than 5 minutes|five minutes)\b", "prolonged seizure", "crisi convulsiva prolungata"),
    (r"\b(passed out|fainted|lost consciousness)\b.*\b(hit my head|chest|heart)\b",
     "fainting with injury or chest symptoms", "svenimento con trauma o sintomi al petto"),
    # Italian
    (r"\b(dolore al petto)\b.*\b(respir|braccio|mascella|sudor)", "chest pain with other warning signs",
     "dolore al petto con altri segnali di allarme"),
    (r"\b(non riesco a respirare|gola (che )?si chiude)\b", "trouble breathing", "difficoltà a respirare"),
    (r"\b(voglio morire|farla finita|uccidermi|farmi del male)\b", "thoughts of self-harm", "pensieri di farsi del male"),
    (r"\b(sputo sangue|vomito sangue|emorragia che non si ferma)\b", "serious bleeding", "sanguinamento grave"),
]

_SELF_HARM_KEYS = ("self-harm", "pensieri di farsi")
TELEFONO_AMICO = "02 2327 2327"


_MED = (r"(?:ibuprofen\w*|paracetamol\w*|acetaminophen|aspirin\w*|naproxen\w*|cortisone|prednison\w*|steroid\w*|antibiotic\w*|"
        r"pills?|meds?|medic\w+|dos(?:e|es|age)|tablets?|capsules?|drugs?|mg|farmac\w+|pastigli\w+|compress\w+|pillol\w+|"
        r"dosi|terapia|ibuprofene|paracetamolo|aspirina|antibiotic\w*|antidolorific\w*|antinfiammator\w*)")
_CHANGE = (r"(?:take|taking|use|double|increase|decrease|reduce|skip|stop|quit|start|switch|mix|combine|"
           r"prendere|prendo|aumentare|ridurre|raddoppiare|smettere|sospendere|saltare|assumere|usare|combinare)")
_Q_CUE = r"(?:\?|\b(?:can|could|should|may|is it|are they|safe|ok to|okay to|posso|potrei|devo|dovrei|conviene|si può|è sicuro|e se)\b)"
# (pattern, label en, label it). A dosing or medicine-change QUESTION, not a note that mentions a medicine.
_DOSING = [
    (rf"\b(?:can|could|should|may|do) i\b[^.?!]{{0,30}}\b{_CHANGE}\b[^.?!]{{0,40}}\b{_MED}\b", "medicine question", "domanda sui farmaci"),
    (rf"\b(?:is it|are they) (?:ok|okay|safe)\b[^.?!]{{0,20}}\b{_CHANGE}\b[^.?!]{{0,40}}\b{_MED}\b", "medicine question", "domanda sui farmaci"),
    (rf"\bhow (?:much|many)\b[^.?!]{{0,30}}\b{_MED}\b[^.?!]{{0,20}}\b(?:should|can|do) i\b", "medicine question", "domanda sui farmaci"),
    (rf"\b(?:posso|potrei|devo|dovrei|conviene|si può)\b[^.?!]{{0,40}}\b{_CHANGE}\b[^.?!]{{0,50}}\b{_MED}\b", "medicine question", "domanda sui farmaci"),
    (rf"\b(?:smetto|sospendo|salto|raddoppio|aumento|riduco|prendo)\b[^.?!]{{0,40}}\b{_MED}\b[^.!]{{0,20}}\?", "medicine question", "domanda sui farmaci"),
    (rf"\b(?:e se|se) (?:smetto|sospendo|salto|raddoppio|aumento|riduco)\b", "medicine question", "domanda sui farmaci"),
    (rf"\b(?:pregnan\w*|breastfeeding|trying to conceive|incinta|gravidanza|allatt\w+)\b[^.!]{{0,80}}\b{_MED}\b[^.!]{{0,60}}{_Q_CUE}",
     "medicine in pregnancy", "farmaci in gravidanza"),
    (rf"{_Q_CUE}[^.!]{{0,60}}\b{_MED}\b[^.!]{{0,80}}\b(?:pregnan\w*|breastfeeding|trying to conceive|incinta|gravidanza|allatt\w+)\b",
     "medicine in pregnancy", "farmaci in gravidanza"),
]


def check_entry(text: str, lang: str = "en") -> SafetyNotice | None:
    """Red-flag interceptor. Runs on the raw text before any model call. `lang` only picks the wording of the notice."""
    low = text.lower()
    it = lang == "it"
    for pat, label_en, label_it in _EMERGENCY:
        if re.search(pat, low):
            label = label_it if it else label_en
            if label_en == "thoughts of self-harm":
                msg = (f"Da quello che hai scritto sembra che tu stia pensando di farti del male. Non devi affrontarlo senza nessuno accanto. "
                       f"Se sei in pericolo adesso, chiama il {EMERGENCY_NUMBER}. In Italia puoi anche chiamare Telefono Amico "
                       f"{TELEFONO_AMICO}." if it else
                       f"You wrote something that sounds like thoughts of hurting yourself. You do not have to "
                       f"handle this alone. If you are in danger now, call {EMERGENCY_NUMBER}. In Italy you can "
                       f"also call Telefono Amico {TELEFONO_AMICO}.")
            else:
                msg = (f"Quello che hai scritto può essere il segno di un'emergenza ({label}). Se sta succedendo adesso, chiama il "
                       f"{EMERGENCY_NUMBER}. Clario è un diario e non può aiutare in un'emergenza." if it else
                       f"What you wrote can be a sign of an emergency ({label}). If it is happening now, call "
                       f"{EMERGENCY_NUMBER}. Clario is a diary and cannot help in an emergency.")
            return SafetyNotice("emergency", msg, label)
    for pat, label_en, label_it in _DOSING:
        if re.search(pat, low):
            msg = ("Le domande su dosi, su smettere o cambiare un farmaco, o su farmaci in gravidanza sono per il medico o il "
                   "farmacista: Clario non può rispondere. Parlane con loro prima di cambiare qualcosa. La nota è stata salvata "
                   "e non viene inviata a nessun modello." if lang == "it" else
                   "Questions about doses, stopping or changing a medicine, or medicines in pregnancy are for your clinician "
                   "or pharmacist. Clario cannot answer them. Talk to them before you change anything. Your note was saved "
                   "and is not sent to any model.")
            return SafetyNotice("advice", msg, label_it if lang == "it" else label_en)
    return None


# --------------------------------------------------------------------------- hedging
_BANNED = [
    r"\byou (have|suffer from|are suffering from)\b",
    r"\b(diagnos(is|e|ed|ing)|confirms?|confirmed|definitely|certainly|clearly (is|has))\b",
    r"\b(start|stop|increase|decrease|reduce|double|take|taking) (your |the )?(dose|medication|medicine|pills?|mg)\b",
    r"\b\d+\s?(mg|mcg|ml)\b",
    r"\b(prescribe|treatment plan|cure|you should take)\b",
    r"\b\d{1,3}\s?%",
    # Italian
    r"\b(soffri|soffre) di\b|\b(sei|è) (affett[oa]|malat[oa]) (da|di)\b",
    r"\bdiagnos\w+|\b(conferma\w*|confermato|sicuramente|certamente|senza dubbio)\b",
    r"\b(inizia\w*|inizi|smett\w+|aument\w+|ridu\w+|assum\w+|prend\w+)\b[^.]{0,30}\b(dose|dosi|farmac\w+|medicin\w+|compress\w+|pillol\w+|mg)\b",
    r"\b(prescriv\w+|piano terapeutico|terapia consigliata|dovresti prendere|deve prendere)\b",
]
_HEDGES = re.compile(r"\b(resembl|may|might|could|worth discussing|consider|pattern|overlap|similar|somigli|potrebb|forse|"
                     r"vale la pena|da valutare|da discutere|schem[ai]|sovrappon|simil|compatibil|ricorda)\w*", re.I)


def hedge_problems(text: str) -> list[str]:
    """Empty list = acceptable. Otherwise the reasons it was rejected."""
    low = text.lower()
    problems = [p for p in _BANNED if re.search(p, low)]
    if not _HEDGES.search(text):
        problems.append("no hedging language")
    return problems


def is_hedged(text: str) -> bool:
    return not hedge_problems(text)


# --------------------------------------------------------------------------- red-flag and untouchable terms
# Terms that must never become a question: emergency symptoms (they get the red-flag notice, not a quiz),
# and medicine or lab-only terms a patient cannot notice or should not answer about.
_RED_FLAG_TERMS = re.compile(
    r"chest pain|chest tightness|shortness of breath|dyspnea|difficulty breathing|respiratory (distress|failure|arrest)|"
    r"apnea|cyanosis|hemoptysis|coughing (up )?blood|hematemesis|vomiting blood|blood in (the )?vomit|"
    r"syncope|fainting|loss of consciousness|unconscious|seizure|convuls|status epilepticus|stroke|"
    r"hemipar|hemipleg|paralysis|slurred|aphasia|sudden (loss|vision)|suicid|self[- ]?(harm|injur|mutilat)|"
    r"hemorrhage|bleeding|anaphyla|throat (closing|swelling)|angioedema|coma\b|confusion|delirium|"
    r"hallucinat|psychosis|cardiac arrest|heart attack|myocardial infarction|sepsis", re.I)
_NOT_NOTICEABLE = re.compile(
    r"serum|plasma|blood level|urine level|concentration|antibod|autoantibod|elevated|decreased circulating|"
    r"increased circulating|laborator|biopsy|histolog|on (mri|ct|x-ray|imaging|examination|ultrasound|eeg)|"
    r"radiograph|electromyogra|echocardiogra|ecg|electrocardiogra|karyotype|chromosom|genotype|mutation|"
    r"medicat|drug|treatment|therapy|reaction to|sensitivity to|intoleran|toxicity|overdose|"
    r"\b(mri|ct|eeg|emg)\b|enzyme|hormone level|\bgene\b|cell count|hemoglobin|creatinine|\blevels?\b", re.I)


def is_red_flag_term(*names: str) -> bool:
    return any(_RED_FLAG_TERMS.search(n) for n in names if n)


def is_unnoticeable_term(*names: str) -> bool:
    return any(_NOT_NOTICEABLE.search(n) for n in names if n)

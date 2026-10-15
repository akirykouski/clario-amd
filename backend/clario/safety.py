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


_EMERGENCY = [
    (r"\b(chest (pain|pressure|tightness))\b.*\b(breath|arm|jaw|sweat)", "chest pain with other warning signs"),
    (r"\b(can'?t|cannot|unable to|struggling to) breathe\b|\bthroat (is )?(closing|swelling)\b", "trouble breathing"),
    (r"\b(face (is )?droop|slurred speech|one side of (my|the) (body|face) (is )?(numb|weak))", "stroke signs"),
    (r"\b(kill myself|end my life|suicid|want to die|self[- ]harm|hurt myself)\b", "thoughts of self-harm"),
    (r"\b(coughing|vomiting|throwing up) (up )?blood\b|\bbleeding (that )?(won'?t|will not) stop\b", "serious bleeding"),
    (r"\bseizure\b.*\b(won'?t stop|more than 5 minutes|five minutes)\b", "prolonged seizure"),
    (r"\b(passed out|fainted|lost consciousness)\b.*\b(hit my head|chest|heart)\b", "fainting with injury or chest symptoms"),
    # Italian
    (r"\b(dolore al petto)\b.*\b(respir|braccio|mascella|sudor)", "dolore al petto con altri segnali"),
    (r"\b(non riesco a respirare|gola (che )?si chiude)\b", "difficoltà a respirare"),
    (r"\b(voglio morire|farla finita|uccidermi|farmi del male)\b", "pensieri di farsi del male"),
]

_SELF_HARM_KEYS = ("self-harm", "pensieri di farsi")


def check_entry(text: str) -> SafetyNotice | None:
    low = text.lower()
    for pat, label in _EMERGENCY:
        if re.search(pat, low):
            if any(k in label for k in _SELF_HARM_KEYS):
                msg = (f"You wrote something that sounds like thoughts of hurting yourself. You do not have to "
                       f"handle this alone. If you are in danger now, call {EMERGENCY_NUMBER}. In Italy you can "
                       f"also call Telefono Amico 02 2327 2327.")
            else:
                msg = (f"What you wrote can be a sign of an emergency ({label}). If it is happening now, call "
                       f"{EMERGENCY_NUMBER}. Clario is a diary and cannot help in an emergency.")
            return SafetyNotice("emergency", msg, label)
    return None


# --------------------------------------------------------------------------- hedging
_BANNED = [
    r"\byou (have|suffer from|are suffering from)\b",
    r"\b(diagnos(is|e|ed|ing)|confirms?|confirmed|definitely|certainly|clearly (is|has))\b",
    r"\b(start|stop|increase|decrease|reduce|double|take|taking) (your |the )?(dose|medication|medicine|pills?|mg)\b",
    r"\b\d+\s?(mg|mcg|ml)\b",
    r"\b(prescribe|treatment plan|cure|you should take)\b",
    r"\b\d{1,3}\s?%",
]
_HEDGES = re.compile(r"\b(resembl|may|might|could|worth discussing|consider|pattern|overlap|similar)\w*", re.I)


def hedge_problems(text: str) -> list[str]:
    """Empty list = acceptable. Otherwise the reasons it was rejected."""
    low = text.lower()
    problems = [p for p in _BANNED if re.search(p, low)]
    if not _HEDGES.search(text):
        problems.append("no hedging language")
    return problems


def is_hedged(text: str) -> bool:
    return not hedge_problems(text)

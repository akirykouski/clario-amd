"""Synthetic demo diary. Giulia, 29, Milan: ten weeks of plain-language notes.

Written to resemble a real pre-diagnosis period (joint pain, rash after sun, mouth sores, fatigue,
hair loss, a lab result), with everyday noise. Entirely fictional.
"""

from __future__ import annotations

from datetime import date, timedelta

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


def giulia_entries(today: date | None = None) -> list[tuple[str, str, int]]:
    today = today or date.today()
    return [((today - timedelta(days=d)).isoformat(), text, mood) for d, text, mood in GIULIA]

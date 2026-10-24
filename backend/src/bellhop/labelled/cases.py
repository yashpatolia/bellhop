"""Hand-labelled demo calls. Fictional, no real patient data."""

from __future__ import annotations

from dataclasses import dataclass, field

Turn = tuple[str, str]


@dataclass(frozen=True)
class LabelledCase:
    id: str
    transcript: list[Turn]
    risk_flags: list[str] = field(default_factory=list)
    expected_urgency: int = 1
    expected_category: str = ""
    note: str = ""


def _c(
    id: str, text: str, urgency: int, category: str, note: str, flags: list[str] | None = None
) -> LabelledCase:
    return LabelledCase(id, [("resident", text)], flags or [], urgency, category, note)


CASES: tuple[LabelledCase, ...] = (
    # Urgency 1: company and chat
    _c(
        "u1-tea-scene",
        "I just feel lonely. Could you stay and have a cup of tea with me?",
        1,
        "social",
        "Demo scene 1: lonely, tea with two sugars",
    ),
    _c(
        "u1-grandson",
        "I was thinking about my grandson today. Can I tell you about him?",
        1,
        "social",
        "Reminiscing",
    ),
    _c("u1-bored", "It is so quiet in here. I am a bit bored.", 1, "social", "Boredom"),
    _c(
        "u1-weather",
        "Is it still raining outside? I like to know what the weather is doing.",
        1,
        "social",
        "Small talk",
    ),
    _c(
        "u1-music",
        "Would you put some music on? Something from the fifties.",
        1,
        "social",
        "Entertainment request",
    ),
    _c(
        "u1-negated-fall",
        "I did not fall, I just sat down hard on the bed. I am fine, just chatty.",
        1,
        "social",
        "Negation: no fall",
        ["falls"],
    ),
    _c(
        "u1-dementia-lost",
        "Where am I? Is this my house? I am not sure what day it is.",
        1,
        "confusion",
        "Confusion alone is not urgent",
        ["dementia"],
    ),
    _c(
        "u1-dementia-husband",
        "Has my husband come yet? He should be here for dinner.",
        1,
        "confusion",
        "Dementia, no danger words",
        ["dementia"],
    ),
    # Urgency 2: simple requests
    _c("u2-water", "Could I have a glass of water please?", 2, "request", "Simple request"),
    _c(
        "u2-blanket",
        "I am a little cold. Can someone bring me a blanket?",
        2,
        "request",
        "Simple request",
    ),
    _c(
        "u2-bathroom-help",
        "I need help getting to the bathroom, please.",
        2,
        "mobility",
        "Assisted mobility",
        ["falls"],
    ),
    _c(
        "u2-tv-remote",
        "I dropped the remote and cannot reach it. Could you pick it up?",
        2,
        "request",
        "Item on floor, not a person",
    ),
    _c(
        "u2-ambiguous-bad",
        "I am not feeling that great today, to be honest.",
        2,
        "ambiguous",
        "Vague, lean slightly up",
    ),
    _c(
        "u2-dementia-help",
        "I cannot find my glasses and I am getting upset. Where is everyone?",
        2,
        "confusion",
        "Distress from confusion, no danger words",
        ["dementia"],
    ),
    # Urgency 3: nurse soon
    _c(
        "u3-hip-pain",
        "My hip has been hurting again since yesterday. It is a dull ache.",
        3,
        "pain",
        "Demo scene 2: known hip pain, tell nurse",
        ["falls"],
    ),
    _c(
        "u3-dizzy",
        "I feel dizzy every time I stand up. I had to hold the wall.",
        3,
        "dizziness",
        "Dizziness on standing",
    ),
    _c(
        "u3-med-confusion",
        "I do not remember if I took my pills this morning. Should I take them again?",
        3,
        "medication",
        "Medication confusion",
        ["medication"],
    ),
    _c(
        "u3-wrong-pill",
        "These pills look different from the ones I usually take.",
        3,
        "medication",
        "Possible medication mix-up",
        ["medication"],
    ),
    _c(
        "u3-headache",
        "I have had a bad headache all afternoon and it is not going away.",
        3,
        "pain",
        "Persistent pain",
    ),
    _c("u3-nausea", "I feel sick to my stomach and could not eat lunch.", 3, "nausea", "Nausea"),
    _c(
        "u3-near-fall",
        "I nearly fell getting out of the chair. My legs felt weak.",
        3,
        "mobility",
        "Near miss, not a fall",
        ["falls"],
    ),
    _c(
        "u3-ambiguous-pain",
        "Something does not feel right in my side. It comes and goes.",
        3,
        "ambiguous",
        "Ambiguous pain, escalate to nurse",
    ),
    _c(
        "u3-dementia-pain",
        "My leg hurts. Why does nobody help me? I want to go home.",
        3,
        "pain",
        "Pain word in dementia call",
        ["dementia"],
    ),
    # Urgency 4: emergencies
    _c(
        "u4-fall",
        "I have fallen and I cannot get up. My hip is in terrible pain.",
        4,
        "fall",
        "Demo scene 3: fall",
        ["falls"],
    ),
    _c(
        "u4-chest-pain",
        "I have a pain in my chest and it is spreading down my arm.",
        4,
        "cardiac",
        "Chest pain",
    ),
    _c(
        "u4-breathe",
        "I cannot breathe properly. Please, I cannot catch my breath.",
        4,
        "respiratory",
        "Breathing difficulty",
    ),
    _c(
        "u4-hedged-chest",
        "It is probably nothing but my chest feels tight.",
        4,
        "cardiac",
        "Hedged phrasing must still escalate",
    ),
    _c(
        "u4-hedged-fall",
        "Sorry to bother you, I think I might have fallen. I cannot stand up.",
        4,
        "fall",
        "Hedged fall",
        ["falls"],
    ),
    _c(
        "u4-dementia-fall",
        "I am on the floor. Why am I on the floor? My head hurts.",
        4,
        "fall",
        "Danger words override dementia",
        ["dementia", "falls"],
    ),
    _c(
        "u4-unresponsive",
        "Help, my roommate is not waking up and she is very pale.",
        4,
        "unresponsive",
        "Another resident in danger",
    ),
)

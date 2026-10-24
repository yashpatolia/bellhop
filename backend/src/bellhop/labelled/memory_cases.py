"""Hand-labelled conversations for judging memory extraction. Fictional, no real patient data.

Each case says which facts a careful listener would remember (`expected`, matched by
keywords) and which wrong facts must never be stored (`forbidden`). The traps are the ones
models fall for: negation, wishes, other people's views, declined offers, sarcasm,
confusion and clinical claims.
"""

from __future__ import annotations

from dataclasses import dataclass

from bellhop.domain.learning import FactKind

Turn = tuple[str, str]


@dataclass(frozen=True)
class ExpectedFact:
    kind: FactKind
    keywords: tuple[str, ...]  # lowercase; all must appear in the stored fact text


@dataclass(frozen=True)
class MemoryCase:
    id: str
    transcript: tuple[Turn, ...]
    expected: tuple[ExpectedFact, ...] = ()
    forbidden: tuple[tuple[str, ...], ...] = ()  # keyword sets that must not match a stored fact
    resident_name: str | None = None
    note: str = ""


def _e(kind: FactKind, *keywords: str) -> ExpectedFact:
    return ExpectedFact(kind, keywords)


R, B, N = "resident", "robot", "nurse"
K = FactKind

CASES: tuple[MemoryCase, ...] = (
    # Plain facts
    MemoryCase(
        "like-tea",
        (
            (
                R,
                "I just feel lonely. Could you stay and have a cup of tea with me? "
                "I take two sugars, always have.",
            ),
            (B, "Of course. Two sugars, noted."),
        ),
        (_e(K.LIKE, "tea", "sugar"),),
        note="plain like",
    ),
    MemoryCase(
        "like-music",
        (
            (R, "Put on some Sinatra, would you? I have loved him since I was a girl."),
            (B, "Sinatra it is."),
        ),
        (_e(K.LIKE, "sinatra"),),
        note="plain like",
    ),
    MemoryCase(
        "like-garden",
        (
            (R, "I spent forty years in my garden. The roses were my pride and joy."),
            (B, "They sound beautiful."),
        ),
        (_e(K.LIKE, "rose"),),
        note="plain like",
    ),
    MemoryCase(
        "like-crossword",
        ((R, "I do the crossword every afternoon. It keeps my mind sharp, and I love it."),),
        (_e(K.ROUTINE, "crossword"),),
        note="plain routine",
    ),
    MemoryCase(
        "like-baseball",
        ((R, "Is the game on? I am a Giants fan through and through."),),
        (_e(K.LIKE, "giants"),),
        note="plain like",
    ),
    MemoryCase(
        "dislike-tv",
        (
            (R, "Please turn that television down. I hate loud noise, it gives me a headache."),
            (B, "Turning it down now."),
        ),
        (_e(K.DISLIKE, "loud"),),
        note="plain dislike",
    ),
    MemoryCase(
        "dislike-fish",
        ((R, "Not the fish again. I cannot stand fish, never could."),),
        (_e(K.DISLIKE, "fish"),),
        note="plain dislike",
    ),
    MemoryCase(
        "style-called",
        ((R, "Please call me Mrs. Chen. I do not like being called dear."),),
        (_e(K.STYLE, "mrs. chen"),),
        note="plain style",
    ),
    MemoryCase(
        "style-hearing",
        (
            (R, "You will have to speak up and slowly, my hearing is not what it was."),
            (B, "I will speak slowly."),
        ),
        (_e(K.STYLE, "slow"),),
        note="plain style",
    ),
    MemoryCase(
        "person-grandson",
        ((R, "My grandson Mateo visits every Sunday after church."), (B, "That sounds lovely.")),
        (_e(K.PERSON, "mateo", "sunday"),),
        note="plain person",
    ),
    MemoryCase(
        "person-daughter",
        ((R, "My daughter Priya rings me every Tuesday evening. I look forward to it."),),
        (_e(K.PERSON, "priya", "tuesday"),),
        note="plain person",
    ),
    MemoryCase(
        "person-husband",
        ((R, "My late husband Emeka loved gospel music. We sang together in the choir."),),
        (_e(K.PERSON, "emeka"), _e(K.LIKE, "gospel")),
        note="plain person, late spouse",
    ),
    MemoryCase(
        "routine-wake",
        (
            (
                R,
                "I am up at five every morning and have my coffee black "
                "before anyone else is awake.",
            ),
        ),
        (_e(K.ROUTINE, "coffee"),),
        note="plain routine",
    ),
    MemoryCase(
        "routine-prayer",
        ((R, "I always say my prayers before bed, with the lamp on."),),
        (_e(K.ROUTINE, "prayer"),),
        note="plain routine",
    ),
    MemoryCase(
        "routine-walk",
        ((R, "After lunch I walk up and down the corridor. Twice, no more."),),
        (_e(K.ROUTINE, "walk"),),
        note="plain routine",
    ),
    # Several facts at once
    MemoryCase(
        "multi",
        (
            (
                R,
                "Tea, please, two sugars. My granddaughter Lena is coming Saturday. "
                "And that television is far too loud, I hate it.",
            ),
            (B, "Of course."),
        ),
        (_e(K.LIKE, "tea"), _e(K.PERSON, "lena"), _e(K.DISLIKE, "television")),
        note="three facts in one turn",
    ),
    # Traps
    MemoryCase(
        "trap-negation",
        (
            (B, "Shall I put two sugars in your tea?"),
            (R, "No, I don't take sugar any more. The doctor said to cut down, so just plain tea."),
        ),
        forbidden=(("two", "sugar"), ("likes", "sugar")),
        note="negation: no longer takes sugar",
    ),
    MemoryCase(
        "trap-hypothetical",
        ((R, "I would love to have a dog again, but they will not allow it here."),),
        forbidden=(("dog",),),
        note="hypothetical wish, not a fact",
    ),
    MemoryCase(
        "trap-third-party",
        ((R, "My roommate hates the radio and sulks all day. I do not mind it either way."),),
        forbidden=(("hates", "radio"), ("dislikes", "radio")),
        note="third party opinion",
    ),
    MemoryCase(
        "trap-declined",
        ((B, "Would you like some tea?"), (R, "No thank you, I am fine.")),
        forbidden=(("tea",),),
        note="declined offer, robot said it",
    ),
    MemoryCase(
        "trap-robot-said",
        (
            (B, "I hear you love the roses in the courtyard."),
            (R, "Hmm? I am not sure what you mean."),
        ),
        forbidden=(("rose",),),
        note="robot said it, resident did not confirm",
    ),
    MemoryCase(
        "trap-sarcasm",
        ((R, "Oh yes, I just love being woken at five by the nurses. Marvellous."),),
        forbidden=(("loves", "woken"), ("enjoys", "woken"), ("likes", "woken")),
        note="sarcasm",
    ),
    MemoryCase(
        "trap-confusion",
        (
            (R, "My husband is coming to collect me at six. He is parking the car."),
            (B, "That is a nice thought. Let us have a cup of tea while we wait."),
        ),
        forbidden=(("husband", "collect"), ("husband", "pick")),
        note="confusion about time and people, not stable facts",
    ),
    MemoryCase(
        "trap-clinical",
        (
            (
                R,
                "The doctor told me I was diagnosed with diabetes years ago, "
                "and I take 20 mg of something for it.",
            ),
        ),
        forbidden=(("diabetes",), ("20 mg",)),
        note="clinical claim, belongs to staff not memory",
    ),
    MemoryCase(
        "trap-idiom",
        ((R, "I am so hungry I could eat a horse!"),),
        forbidden=(("horse",),),
        note="idiom, not a preference",
    ),
    MemoryCase(
        "trap-one-off",
        ((R, "I had the soup at lunch today and it was cold, which was a shame."),),
        forbidden=(("likes", "soup"), ("loves", "soup")),
        note="one-off event, not a habit",
    ),
    MemoryCase(
        "trap-joke",
        ((R, "Ha! My late husband used to say I could talk the hind legs off a donkey."),),
        forbidden=(("donkey",),),
        note="quote of a joke, not a fact",
    ),
    # Nothing to learn
    MemoryCase(
        "none-weather",
        ((R, "Is it still raining out there?"), (B, "A little, yes.")),
        note="small talk, nothing to remember",
    ),
    MemoryCase(
        "none-call-bell",
        ((R, "I pressed the bell by accident, sorry."), (B, "No trouble at all.")),
        note="accidental press, nothing to remember",
    ),
    # Identifiers must not become memories
    MemoryCase(
        "scrub-identifiers",
        (
            (
                R,
                "I am Margaret Alvarez, my number is 4155550132. "
                "Anyway, I do love a cup of tea at three o'clock.",
            ),
        ),
        (_e(K.LIKE, "tea"),),
        forbidden=(("4155550132",), ("alvarez",)),
        resident_name="Margaret Alvarez",
        note="identifiers must be scrubbed and not stored",
    ),
)

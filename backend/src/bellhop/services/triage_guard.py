"""Deterministic triage safety net around the real (model-based) triage.

Pure and dependency-free. The guard only ever raises urgency; it never lowers
what the model said. It leans toward escalation and does not diagnose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bellhop.domain.models import Urgency

Turn = tuple[str, str]

_NEGATORS = {"no", "not", "never", "without", "nothing", "none", "hardly"}
# Words after a negator that mean the resident is hedging, not denying.
_HEDGES = {"sure", "know", "if", "whether", "think", "remember", "certain"}
_CLAUSE_SPLIT = re.compile(r"[.,;:!?\n]+|\b(?:but|though|however|although)\b")
_NEG_WINDOW = 4
_HELP_REPEAT = 3


@dataclass(frozen=True)
class FloorResult:
    urgency: Urgency | None
    matched: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    urgency: Urgency
    reason: str


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    floor: Urgency
    label: str
    negatable: bool = True  # False when the phrase is itself a negation ("cannot ...")
    requires: re.Pattern[str] | None = None  # extra context needed in the same clause


def _rule(
    pat: str, floor: Urgency, label: str, negatable: bool = True, requires: str | None = None
) -> _Rule:
    return _Rule(
        re.compile(pat), floor, label, negatable, re.compile(requires) if requires else None
    )


E, U = Urgency.EMERGENCY, Urgency.NURSE_SOON

_RULES: tuple[_Rule, ...] = (
    # Emergency
    _rule(
        r"\bcannot get (?:\w+ ){0,2}?(?:back )?up\b|\bcannot (?:stand|sit) (?:back )?up\b"
        r"|\bcannot get (?:off|out of)\b|\bcannot (?:stand on|walk|bear weight|weight bear)\b",
        E,
        "can't get up",
        False,
    ),
    _rule(r"\bcannot (?:move|feel) my (?:legs?|hips?|arms?)\b", E, "can't move limb", False),
    _rule(r"(?<!nearly )(?<!almost )\b(?:fell|fallen)\b", E, "fall"),
    _rule(r"\b(?:had|took) a fall\b|\bfall(?:ing)? (?:down|over)\b", E, "fall"),
    _rule(r"\b(?:slipped|tripped) (?:and|on|in|over)\b", E, "fall"),
    _rule(r"\b(?:tumbled|collapsed|blacked out|toppled)\b", E, "collapse"),
    _rule(r"\bon (?:the )?(?:floor|ground)\b", E, "on the floor"),
    _rule(
        r"\b(?:went|gone|go|going)\b(?:\W+\w+){0,3}?\W+(?:down|over)\b",
        E,
        "fall",
        requires=r"\b(?:stairs|floor|ground|hard|crash\w*|kitchen|bathroom|hall\w*|bed|shower"
        r"|leg|legs|hip|head|cannot|will not|stuck|hurt\w*|pain\w*)\b",
    ),
    _rule(
        r"\b(?:will not|would not) (?:hold|support) (?:me|my)\b"
        r"|\b(?:legs?|knees?) (?:gave|giving|gives|buckl\w*)\b|\bgave (?:way|out)\b",
        E,
        "legs gave way",
        False,
    ),
    _rule(
        r"\bchest\b.{0,25}\b(?:tight|tightness|pain\w*|hurt\w*|ach\w*|sore|discomfort|pressure|heavy|squeez\w*)\b"
        r"|\b(?:tight|pain|pressure|tightness|discomfort) (?:in|across) (?:my|the) chest\b"
        r"|\bclutching (?:his|her|my|the) chest\b"
        r"|\b(?:pain\w*|hurt\w*|ach\w*|shooting)\b.{0,25}\b(?:left arm|jaw)\b"
        r"|\bleft arm\b.{0,20}\b(?:pain\w*|hurt\w*|ach\w*|numb\w*|tingl\w*)\b"
        r"|\b(?:jaw|heart)\b.{0,20}\b(?:pain\w*|hurt\w*|ach\w*|tight)\b"
        r"|\bheart (?:is |was )?(?:racing|pounding|fluttering|thumping|hammering)\b"
        r"|\b(?:arm|hand|face|leg)\b.{0,15}\b(?:numb\w*|tingl\w*)\b",
        E,
        "chest pain/tightness",
    ),
    _rule(
        r"\bcannot (?:breathe|catch (?:my|a) breath)\b|\bcannot get (?:my|a) breath\b",
        E,
        "can't breathe",
        False,
    ),
    _rule(
        r"\b(?:short of breath|struggling (?:to|for) breathe?|hard to breathe|gasping"
        r"|(?:trouble|difficulty) breathing|breathless|wheez\w*|throat (?:is )?closing"
        r"|cannot (?:get|take|draw)(?: any| enough| a)? (?:air|breath))\b",
        E,
        "breathing difficulty",
    ),
    _rule(r"\bchok(?:e|es|ed|ing)\b", E, "choking"),
    _rule(
        r"\b(?:cannot|unable)\b(?:\W+\w+){0,2}?\W+(?:breath\w*"
        r"|(?:get|take|draw|catch)\W+(?:(?:any|enough|some|more|a)\W+)?(?:air|breath))\b",
        E,
        "can't breathe",
        False,
    ),
    _rule(
        r"\b(?:trouble|difficulty|struggl\w*|hard|harder|labou?red)\b(?:\W+\w+){0,3}?\W+"
        r"(?:breath\w*|(?:get|getting|take|taking|draw|drawing)\W+"
        r"(?:(?:any|enough|some|more|a)\W+)?air)\b",
        E,
        "breathing difficulty",
    ),
    _rule(
        r"\b(?:heart attack|seizures?|convuls\w*|cardiac arrest|overdos\w*|paraly\w*)\b"
        r"|\b(?:took|taken|swallowed) too (?:many|much)\b"
        r"|\b(?:a|mini|having|had) stroke\b(?!\s+of)"
        r"|\blopsided\b|\bnot making sense\b|\bface (?:is )?(?:sagging|crooked)\b"
        r"|\bwords (?:keep |are )?(?:coming out )?(?:wrong|jumbled|mixed up)\b"
        r"|\bspeech is (?:all )?(?:wrong|slurred|garbled)\b|\bworst headache\b"
        r"|\bone side\b.{0,20}\b(?:weak\w*|numb\w*)\b"
        r"|\bsudden(?:ly)?\b.{0,25}\b(?:weak\w*|numb\w*|confus\w*|vision|headache"
        r"|cannot see|cannot speak)\b",
        E,
        "cardiac/stroke/overdose signs",
    ),
    _rule(
        r"\bbleed(?:ing)?\b|\b(?:lot of|much) blood\b|\bblood (?:everywhere|pouring)\b",
        E,
        "bleeding",
    ),
    _rule(
        r"\b(?:unresponsive|unconscious|passed out|not (?:waking|responding)\b"
        r"|will not wake|not wake|not breathing)",
        E,
        "unresponsive",
        False,
    ),
    _rule(
        r"\bslurr(?:ed|ing)\b|\bdroop(?:ing|y)?\b|\bface (?:is )?numb\b"
        r"|\bcannot (?:lift|move|feel) (?:my )?(?:left |right )?(?:arm|face|hand)\b"
        r"|\bcannot (?:speak|talk) (?:properly|right)\b",
        E,
        "stroke signs",
        False,
    ),
    # Urgent, not emergency
    _rule(r"\b(?:dizzy|dizziness|lightheaded|light headed|faint(?:ing)?)\b", U, "dizzy"),
    _rule(r"\b(?:nearly|almost) (?:fell|fall)\b", U, "near fall"),
    _rule(
        r"\b(?:legs?|knees?|arms?) (?:felt|feel|feels|are|is) weak\b|\bweak (?:legs?|knees?)\b",
        U,
        "weakness",
    ),
    _rule(r"\b(?:nausea|nauseous|vomit\w*|sick to my stomach)\b", U, "nausea"),
    _rule(r"\bheadache\b", U, "headache"),
    _rule(r"\b(?:hurt|hurts|hurting|ache|aches|aching|pain|pains|painful|sore)\b", U, "pain"),
    _rule(
        r"\bnot (?:feel|feeling) (?:right|well)\b|\bnot (?:like )?(?:feeling )?myself\b",
        U,
        "doesn't feel right",
        False,
    ),
    _rule(
        r"\bfeel(?:ing|s)? (?:very |really |so |a bit )?"
        r"(?:strange|unwell|off|odd|wrong|ill|terrible|awful|sick|poorly)\b"
        r"|\bsomething(?:'s| is| feels| seems)? (?:wrong|off|not right)\b",
        U,
        "feels unwell",
    ),
    _rule(
        r"\bbeen sick\b|\bthrowing up\b|\bcannot keep (?:\w+ ){0,2}down\b"
        r"|\b(?:pale|clammy|sweaty|cold sweat)\b",
        U,
        "sickness/sweating",
    ),
)

# Clause-level contexts that make a rule a non-event (idioms, seasons, noise, play).
_BENIGN: dict[str, re.Pattern[str]] = {
    "fall": re.compile(r"\b(?:in love|asleep|leaves|autumn|season|behind|apart)\b"),
    "on the floor": re.compile(r"\b(?:sat|sit|sitting|play|playing|picnic|stretch\w*|yoga)\b"),
    "breathing difficulty": re.compile(r"\b(?:breath away|fresh air|breath of)\b"),
    "can't breathe": re.compile(r"\b(?:breath away|fresh air|breath of)\b"),
    "pain": re.compile(r"\b(?:ears?|volume|loud|noise|noisy)\b"),
}

_MED_WORDS = re.compile(
    r"\b(?:pills?|medications?|medicines?|tablets?|capsules?|meds|insulin|thinners?|doses?)\b"
)
_MED_TROUBLE = re.compile(
    r"\b(?:remember|forgot|forget|different|wrong|again|twice|double|mixed|mixing|extra"
    r"|too many|too much|by mistake|mistake|accident\w*)\b"
    r"|\b(?:took|taken|take|swallowed|had|gave|given) (?:\w+ ){0,3}more\b"
)


def _normalise(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"\bcan't\b|\bcan not\b|\bcouldn't\b|\bunable to\b", "cannot", t)
    t = t.replace("won't", "will not").replace("n't", " not")
    return re.sub(r"[ \t]+", " ", t)


def _negated(prefix: str) -> bool:
    tokens = re.findall(r"[a-z']+", prefix)[-_NEG_WINDOW:]
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i] in _NEGATORS:
            return not any(tok in _HEDGES for tok in tokens[i + 1 :])
    return False


def keyword_floor(transcript: list[Turn]) -> FloorResult:
    """Scan resident utterances only; return the minimum urgency the words imply."""
    best: Urgency | None = None
    matched: list[str] = []
    help_count = 0
    for speaker, text in transcript:
        if speaker != "resident":
            continue
        norm = _normalise(text)
        help_count += len(re.findall(r"\bhelp\b", norm))
        for clause in _CLAUSE_SPLIT.split(norm):
            if not clause or not clause.strip():
                continue
            for rule in _RULES:
                if rule.requires and not rule.requires.search(clause):
                    continue
                for m in rule.pattern.finditer(clause):
                    if rule.negatable and _negated(clause[: m.start()]):
                        continue
                    benign = _BENIGN.get(rule.label)
                    if benign and benign.search(clause):
                        continue
                    if rule.label not in matched:
                        matched.append(rule.label)
                    best = rule.floor if best is None else max(best, rule.floor)
                    break
            if (
                _MED_WORDS.search(clause)
                and _MED_TROUBLE.search(clause)
                and "medication confusion" not in matched
            ):
                matched.append("medication confusion")
                best = U if best is None else max(best, U)
    if help_count >= _HELP_REPEAT:
        matched.append(f"repeated help x{help_count}")
        best = E
    return FloorResult(best, matched)


_NAMES = {
    Urgency.CHAT: "chat",
    Urgency.ROUTINE: "routine",
    Urgency.NURSE_SOON: "nurse soon",
    Urgency.EMERGENCY: "emergency",
}


def apply_floor(
    model_urgency: Urgency | None,
    model_confidence: float | None,
    floor: FloorResult,
    low_confidence: float = 0.6,
) -> Decision:
    """Final urgency = max(model, floor), with safe defaults for a failed/unsure model."""
    if model_urgency is None:
        base, reason = Urgency.NURSE_SOON, "model unavailable, defaulted to nurse soon"
    else:
        base, reason = model_urgency, f"model: {_NAMES[model_urgency]}"
        if model_confidence is not None and model_confidence < low_confidence:
            base = Urgency(min(model_urgency + 1, Urgency.EMERGENCY))
            reason = (
                f"low model confidence ({model_confidence:.2f}), "
                f"raised from {_NAMES[model_urgency]} to {_NAMES[base]}"
            )
    if floor.urgency is not None and floor.urgency > base:
        return Decision(floor.urgency, "keyword: " + ", ".join(floor.matched[:3]))
    return Decision(base, reason)


class TriageGuard:
    def __init__(self, low_confidence: float = 0.6) -> None:
        self._low_confidence = low_confidence

    def decide(
        self,
        transcript: list[Turn],
        model_urgency: Urgency | None,
        model_confidence: float | None,
    ) -> Decision:
        floor = keyword_floor(transcript)
        return apply_floor(model_urgency, model_confidence, floor, self._low_confidence)

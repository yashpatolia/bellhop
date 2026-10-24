"""Score a fact extractor against the labelled memory cases.

Headline numbers are about *stored* facts, because those are the ones Bellhop will say
out loud: precision of what was stored automatically, recall of what should be remembered,
and a hard count of forbidden facts that slipped into memory without a nurse's review.

    uv run python -m bellhop.labelled.memory_eval --extractor rule
    ANTHROPIC_API_KEY=... uv run python -m bellhop.labelled.memory_eval --extractor claude
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.domain import Turn
from bellhop.labelled.memory_cases import CASES, MemoryCase
from bellhop.ports.learning import FactExtractor
from bellhop.services.memory_guard import MemoryGuard
from bellhop.services.memory_learner import MemoryLearner
from bellhop.services.memory_service import MemoryService

_AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
_RESIDENT = "r1"


class _Clock:
    def now(self) -> datetime:
        return _AT


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self, prefix: str = "id") -> str:
        self.n += 1
        return f"{prefix}-{self.n}"


def _has(text: str, keywords: Sequence[str]) -> bool:
    low = text.casefold()
    return all(k in low for k in keywords)


@dataclass
class CaseResult:
    case_id: str
    accepted: list[str]
    pending: list[str]
    expected_total: int
    hit: int
    hit_auto: int
    unexpected_auto: list[str]
    pending_unexpected: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    pending_violations: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)


@dataclass
class EvalResult:
    cases: list[CaseResult]

    @staticmethod
    def _ratio(num: int, den: int) -> float:
        return num / den if den else 1.0

    @property
    def expected_total(self) -> int:
        return sum(c.expected_total for c in self.cases)

    @property
    def recall(self) -> float:
        return self._ratio(sum(c.hit for c in self.cases), self.expected_total)

    @property
    def recall_auto(self) -> float:
        return self._ratio(sum(c.hit_auto for c in self.cases), self.expected_total)

    @property
    def stored_auto(self) -> int:
        return sum(len(c.accepted) for c in self.cases)

    @property
    def precision_auto(self) -> float:
        bad = sum(len(c.unexpected_auto) for c in self.cases)
        return self._ratio(self.stored_auto - bad, self.stored_auto)

    @property
    def precision_all(self) -> float:
        total = self.stored_auto + sum(len(c.pending) for c in self.cases)
        bad = sum(len(c.unexpected_auto) + len(c.pending_unexpected) for c in self.cases)
        return self._ratio(total - bad, total)

    @property
    def forbidden_auto(self) -> int:
        return sum(len(c.violations) for c in self.cases)

    @property
    def forbidden_pending(self) -> int:
        return sum(len(c.pending_violations) for c in self.cases)

    @property
    def dropped(self) -> dict[str, int]:
        total: Counter[str] = Counter()
        for c in self.cases:
            total.update(c.dropped)
        return dict(total)


def _score(case: MemoryCase, extractor: FactExtractor) -> CaseResult:
    index = DeletableLocalMemoryIndex()
    guard = MemoryGuard(MemoryService(index, _Clock(), _Ids()), index)
    transcript = [Turn(speaker=s, text=t, at=_AT) for s, t in case.transcript]
    report = MemoryLearner(extractor, guard).learn(_RESIDENT, transcript, case.resident_name)
    accepted = [f.text for f in report.stored]
    pending = [p.text for p in guard.pending(_RESIDENT)]
    wanted = [e.keywords for e in case.expected]
    missed = [" ".join(k) for k in wanted if not any(_has(t, k) for t in accepted + pending)]
    return CaseResult(
        case_id=case.id,
        accepted=accepted,
        pending=pending,
        expected_total=len(wanted),
        hit=sum(1 for k in wanted if any(_has(t, k) for t in accepted + pending)),
        hit_auto=sum(1 for k in wanted if any(_has(t, k) for t in accepted)),
        unexpected_auto=[t for t in accepted if not any(_has(t, k) for k in wanted)],
        pending_unexpected=[t for t in pending if not any(_has(t, k) for k in wanted)],
        violations=[" ".join(k) for k in case.forbidden if any(_has(t, k) for t in accepted)],
        pending_violations=[
            " ".join(k) for k in case.forbidden if any(_has(t, k) for t in pending)
        ],
        missed=missed,
        dropped=report.dropped,
    )


def run_eval(extractor: FactExtractor, cases: Sequence[MemoryCase] = CASES) -> EvalResult:
    return EvalResult([_score(c, extractor) for c in cases])


def format_report(result: EvalResult, title: str = "memory extraction") -> str:
    pct = lambda x: f"{x * 100:5.1f}%"  # noqa: E731
    lines = [
        f"== {title} ({len(result.cases)} cases, {result.expected_total} expected facts) ==",
        f"precision of stored facts   {pct(result.precision_auto)}"
        f"   ({result.stored_auto} stored without review)",
        f"precision incl. review queue{pct(result.precision_all)}",
        f"recall (stored or queued)   {pct(result.recall)}",
        f"recall (stored only)        {pct(result.recall_auto)}",
        f"forbidden facts stored      {result.forbidden_auto}   (must be 0)",
        f"forbidden facts queued      {result.forbidden_pending}",
        f"candidates dropped by gates {result.dropped or 'none'}",
    ]
    problems = [
        c
        for c in result.cases
        if c.violations or c.missed or c.unexpected_auto or c.pending_violations
    ]
    if problems:
        lines.append("")
        lines.append("cases to look at:")
        for c in problems:
            bits = []
            if c.violations:
                bits.append(f"STORED FORBIDDEN {c.violations}")
            if c.pending_violations:
                bits.append(f"queued forbidden {c.pending_violations}")
            if c.unexpected_auto:
                bits.append(f"unexpected stored {c.unexpected_auto}")
            if c.missed:
                bits.append(f"missed {c.missed}")
            lines.append(f"  {c.case_id}: " + "; ".join(bits))
    return "\n".join(lines)


def _build_extractor(name: str, model: str | None) -> FactExtractor:
    if name == "rule":
        from bellhop.adapters.rule_extractor import RuleFactExtractor

        return RuleFactExtractor()
    from bellhop.adapters.claude_extractor import ClaudeFactExtractor

    return ClaudeFactExtractor(model=model) if model else ClaudeFactExtractor()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--extractor", choices=["rule", "claude"], default="rule")
    p.add_argument("--model", help="Claude model id (claude extractor only)")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    extractor = _build_extractor(args.extractor, args.model)
    title = args.extractor + (f" ({args.model})" if args.model else "")
    result = run_eval(extractor)
    print(format_report(result, title))
    return 1 if result.forbidden_auto else 0


if __name__ == "__main__":
    raise SystemExit(main())

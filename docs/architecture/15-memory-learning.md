# Memory learning

How Bellhop turns a finished conversation into memories it can use on the next visit, and how we measure whether those memories are right. Code: `services/memory_learner.py`, `adapters/claude_extractor.py`, `adapters/rule_extractor.py`, `labelled/memory_eval.py`.

## Principle

A wrong memory does more harm than a missing one (a resident with dementia can be misled, a nurse can lose trust). So a model only **proposes** facts. Code decides what is trusted, and anything doubtful waits for a nurse. Precision is the number we protect.

## Flow

```text
finished call transcript
   -> scrub (resident name, phones, emails, long digit runs)        services/scrub.py
   -> FactExtractor.extract(transcript, known_facts)                 ports/learning.py
        ClaudeFactExtractor (structured output) or RuleFactExtractor (offline baseline)
   -> gates, in order                                                MemoryLearner._gate
        empty -> not_grounded -> not_about_resident -> low_confidence
   -> confidence adjustments                                         MemoryLearner._confidence
        hedged quote x0.6; health facts capped at 0.55
   -> MemoryGuard.propose(...)                                       existing
        clinical_claim / duplicate rejected; < 0.6 goes to the nurse review queue; else stored
```

It runs after a visit, never inside the voice loop. Extraction latency does not matter; recall latency (under 50 ms) is unchanged.

## The gates

| Gate | Drops a candidate when | Why |
| --- | --- | --- |
| `not_grounded` | its `quote` is not found, word for word (case and punctuation ignored), in a turn by the claimed speaker | The model cannot invent a fact or credit the robot's words to the resident |
| `not_about_resident` | `subject` is someone else and the kind is not `person` | "My roommate hates the radio" is not the resident's preference |
| `low_confidence` | confidence is under 0.3 after adjustments | Noise, not worth a nurse's time |
| hedge | quote contains a wish or maybe ("would love", "maybe", "one day", "used to") | Confidence x0.6, which pushes it to review |
| health cap | kind is `health` | Capped at 0.55, so always reviewed by a nurse |

Facts are stored with their kind as a tag (`like`, `dislike`, `person`, `routine`, `health`, `style`, `event`).

## Scrubbing

Names of family and friends stay (they are the memory). The resident's own name, phone numbers, emails and digit runs of six or more are replaced before the text reaches any model. The quote check runs against the scrubbed transcript.

## Choosing the extractor

`BELLHOP_LEARNING=rule` (default) uses phrase patterns, offline and free. `BELLHOP_LEARNING=claude` uses `ClaudeFactExtractor`, which needs `ANTHROPIC_API_KEY` (or an `ant auth login` profile) and reads the model from `BELLHOP_EXTRACTOR_MODEL` (default `claude-opus-5-5`). The extractor uses structured outputs (`messages.parse` with `ExtractedFacts`) and effort `high`. Do not use forced tool choice: it is rejected by current models.

## Measuring accuracy

```bash
cd backend
uv run python -m bellhop.labelled.memory_eval --extractor rule
ANTHROPIC_API_KEY=... uv run python -m bellhop.labelled.memory_eval --extractor claude
ANTHROPIC_API_KEY=... uv run python -m bellhop.labelled.memory_eval --extractor claude --model claude-sonnet-5-5
```

`labelled/memory_cases.py` holds 30 fictional conversations: plain likes, dislikes, people, routines and style, plus the traps models fall for (negation, wishes, other people's opinions, declined offers, sarcasm, confusion, clinical claims, idioms, one-off events, jokes) and identifier scrubbing. Each case lists the facts a careful listener would keep and the wrong facts that must never be stored.

Reported numbers: precision of facts stored without review, precision including the review queue, recall (stored or queued, and stored only), forbidden facts stored (must be 0) and queued, and what the gates dropped. The command exits non-zero if any forbidden fact was stored.

Baseline (`rule`, 30 cases, 20 expected facts): precision 69.2% (13 stored), recall 50.0%, 1 forbidden fact stored (it took sarcasm literally). A model extractor has to beat this. Compare models by running the same command with different `--model` values and keeping the most accurate one that is affordable.

Caveat: this set was written alongside the extractor prompt, so it is a development set. Before trusting a score, write a fresh batch that nobody tuned against (see the triage lesson in [05-testing.md](05-testing.md)).

## Limits and next steps

- Facts keep only `text` and a kind tag. Source, confidence, quote and call id are not persisted yet; that needs extra `MemoryFact` fields and a contract regeneration.
- Contradictions ("prefers tea" then "now prefers coffee") are not resolved; a new fact is only checked for duplicates.
- `LearnOnResolve` (`services/learn_on_resolve.py`) subscribes to `CallResolved` and runs `MemoryLearner.learn` on a background thread, so the robot's resolve request never waits on a model. It skips calls with no known resident or where the resident never spoke, and logs any failure instead of raising. The default extractor is still the offline `rule` baseline until the Claude numbers are measured.
- Nightly consolidation, habit statistics and the pre-visit briefing are separate steps (see the plan in the team notes).

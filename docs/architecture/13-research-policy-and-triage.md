# 13. Research: policy layer, clinical alignment, paraphrase recall

Status: research only, no code changed. Date: 2026-10-23. Package facts come from PyPI and Hugging Face APIs queried today. Items marked (measured) I ran in a throwaway venv outside the repo (16-core x86 laptop). Items marked (unverified) are from memory or secondary sources. Not medical advice: this is a flagging backstop.

## 1. Decision policy: data instead of code?

Our rules today: a transition map in `domain/models.py` (already a declarative dict), a ratchet in `Call.score`, a 4-level `Urgency`, and ad hoc dispatch/alert branches in `dispatcher.py`. That is small. The pain is the 303-line guard, not the dispatch rules.

| Tool | Facts (PyPI, today) | Fit | Verdict |
| --- | --- | --- | --- |
| json-logic / json-logic-qubit | last release 2015 / 2018 | rules as JSON, but abandoned | SKIP |
| durable_rules | 2.0.28, June 2020, no releases since | Rete engine, forward chaining, overkill | SKIP |
| business-rules | 1.1.1, March 2022 | JSON rules, python 2-era code | SKIP |
| python-statemachine | 3.2.2, 2026-10-14, MIT, 160 KB wheel, 5 deps | active; declarative states, guards, diagrams | LATER (only if Call grows parallel/nested states) |
| transitions | 0.9.3, July 2025, MIT, 3 deps | mature, callbacks, diagrams | LATER (same reason) |
| Our hand-rolled map + `transition()` | ~15 lines of data in `models.py` | already data, already property-tested | KEEP |
| py-trees | 2.6.0, 2026-09, BSD, 8 MB sdist | behaviour trees suit robot control, not alert policy | SKIP (revisit for robot navigation, not here) |
| OPA / Rego | docs current; Python binding `opa-wasm` last 2022 | needs a sidecar or WASM runtime; built for authorization | SKIP |
| Cedar (`cedarpy`) | 4.12.2, 2026-10-14, 3-4 MB native wheel | authorization (who may do what), not triage | SKIP |
| LangGraph | 1.2.17, MIT, 6 deps | LLM-workflow orchestration, pulls a framework | SKIP |
| pydantic-graph | 2.60.0, MIT, 4 deps | typed graph for LLM agents; we have one LLM call | SKIP |

Sketch in the best candidate, which is plain data in Python (frozen rows, one pure function). No new dependency.

```python
@dataclass(frozen=True)
class Row:                       # first matching row wins; order is priority
    urgency_min: Urgency         # inclusive floor of the combined score
    status_in: frozenset[CallStatus] | None
    robot_available: bool | None
    resident_flag: str | None    # e.g. "high_fall_risk", "dementia"
    action: Action               # ALERT_NOW, ALERT_SUMMARY, ROBOT_VISIT, ROBOT_THEN_NURSE
    notify: Role                 # NURSE_ON_DUTY, CHARGE_NURSE, ALL
    reason: str                  # shown on the dashboard, asserted in tests

POLICY: tuple[Row, ...] = (
    Row(E, None, None, None, ALERT_NOW, ALL, "emergency: robot stays, humans paged"),
    Row(U, None, None, None, ALERT_SUMMARY, NURSE_ON_DUTY, "nurse soon: written summary"),
    Row(R, {RINGING}, True, "high_fall_risk", ROBOT_THEN_NURSE, NURSE_ON_DUTY, "..."),
    Row(R, {RINGING}, True, None, ROBOT_VISIT, None, "routine: robot visits"),
    Row(R, None, False, None, ALERT_SUMMARY, NURSE_ON_DUTY, "no robot: nurse takes it"),
)
def decide(call, ctx) -> Row: return next(r for r in POLICY if r.matches(call, ctx))
```

Honest comparison against a 30-line pure function plus a table-driven test:

| Question | Answer |
| --- | --- |
| Does a rule engine or graph beat the pure function for the MVP? | No. We have about 5 to 8 rules, one author team, and the rules ship with the code. |
| What does data buy us? | Rules become reviewable in one table, and the test iterates the same table (every row needs a case). That is the real win, and a tuple of rows gets it. |
| When would a library help? | When non-engineers (care managers) edit rules without deploys, or rules exceed about 30. Neither is true. |
| Biggest hazard of a rule engine here | Rule order and conflict resolution become implicit. A safety path must stay "ratchet up only, first read of the code explains it". |
| Verdict | ADOPT NOW: the row table above only if dispatcher branches exceed about 6; otherwise leave as is. ADOPT NOTHING from the libraries. |

The policy layer does not fix recall. The recall problem is in section 3.

## 2. Clinical and safety standards to align with

| Source | What it is | Use for us |
| --- | --- | --- |
| INTERACT Stop and Watch | Early-warning tool for direct-care staff in nursing homes: plain-language checks such as "seems different than usual", "talks or communicates less", eating less, pain, new or worsening confusion, falls | Source of wording for NURSE_SOON (3) cues: change from baseline, not only emergencies |
| INTERACT SBAR | Situation, Background, Assessment, Recommendation call script for the nurse | Shape the alert summary the nurse receives (see below). Note: the form is copyrighted by Florida Atlantic University and must not be embedded in software without permission, so copy the structure, not the form |
| NEWS2 (RCP 2017, guidance 2020) | Vital-sign score, needs measurements. Trigger: single parameter score of 3 or aggregate 5 or 7. New confusion scores 3 and is a trigger on its own | We have no vitals. Borrow one idea: new confusion or reduced consciousness alone justifies escalation |
| ESI v5 (ENA, 2023) | ER 5-level triage. Decision Point B: high-risk situation, new confusion/lethargy/disorientation, severe pain or distress goes to level 2 | Same three triggers map to our EMERGENCY or NURSE_SOON. I could not read the v5 text; v4 wording was confirmed (unverified for v5) |
| Manchester Triage | Flowchart with general discriminators (airway, breathing, shock, unresponsive, severe pain) | Not verified (search returned nothing); skip as a source |
| Alarm fatigue | Joint Commission NPSG.06.01.01 is a hospital goal: prioritise which alarms matter, written policy. AAMI: desensitised staff ignore or silence alarms | Alert only when action is needed; report false-alert rate next to under-escalation rate. No nursing-home-specific source found |

SBAR-shaped alert summary (suggestion): S what the resident said (verbatim) plus room; B resident flags and last visit note; A the urgency level and which cue fired; R "check in person now" or "within the hour".

Red-flag categories to cover in the exemplar bank (checkable list; level is our flag, not a diagnosis):

| # | Category | Implied patterns (speaker may be resident or a third party) | Flag |
| --- | --- | --- | --- |
| 1 | Fall or collapse | fell, hit the deck, went down, keeled over, on the floor, cannot get up, blacked out, she's collapsed | 4 |
| 2 | Breathing | cannot breathe, trouble getting air, gasping, wheezing, choking, something stuck in throat | 4 |
| 3 | Chest or cardiac | chest pain, tightness, pressure, squeezing, heart racing, pain down arm or jaw | 4 |
| 4 | Colour and sweat | gone blue around the lips, grey, clammy, pale and sweating | 4 |
| 5 | Stroke signs | face drooping, slurred speech, sudden weakness or numbness one side, sudden vision loss | 4 |
| 6 | Unresponsive or new confusion | not answering, will not wake, does not know where they are | 4 (confusion new: 3 or 4) |
| 7 | Bleeding or vomiting blood | bleeding will not stop, blood everywhere, black stools | 4 |
| 8 | Overdose or swallowing harm | took too many tablets, swallowed cleaner | 4 |
| 9 | Severe sudden pain | worst headache, agonising belly pain | 3 or 4 |
| 10 | Change from baseline (Stop and Watch) | not eating, much quieter, new incontinence, dizzy, new swelling, hot or shivering, new pain | 3 |
| 11 | Self-harm or abuse disclosure | do not want to live, someone hurt me | 4 |
| 12 | Help repeated | same call three times (already in guard) | 3 |

## 3. NLP that targets the measured weakness

Measured on my own 10 unseen positives and 10 negatives (author-written, tiny, optimistic; use only for orders of magnitude). Bank: 33 exemplars. Max cosine to bank.

| Option | Install and model size | Offline | Latency per utterance | Licence | uv reliability | Measured result |
| --- | --- | --- | --- | --- | --- | --- |
| model2vec `potion-base-8M` | package 87 KB + numpy; model 30 MB | yes after first download | 0.1 ms | MIT | clean | thr 0.4: recall 5/10, false+ 2/10. Too weak. 32M model (129 MB) no better |
| fastembed + `all-MiniLM-L6-v2` | fastembed 91 KB + onnxruntime 14 MB wheel; venv about 180 MB with model2vec; model 90 MB (quantised 23 MB exists) | yes | 2.2 ms (laptop); Pi 5 maybe 10 to 30 ms (unverified) | Apache-2.0 | clean, 20 s install | thr 0.5: recall 7/10, false+ 2/10 |
| fastembed + `bge-small-en-v1.5` | model 133 MB (quantised 66 MB) | yes | 3.7 ms | MIT | clean | scores compress to 0.57-0.80: all 10 positives above 0.67 but negatives reach 0.80. Needs a calibrated threshold |
| sentence-transformers 6.2.0 | pulls torch, 31 deps, hundreds of MB | yes | 5-20 ms (unverified) | Apache-2.0 | heavy, flaky downloads | SKIP, fastembed does the same job lighter |
| Zero-shot NLI (deberta-v3-xsmall) | 87 MB quantised ONNX, needs transformers or custom ONNX glue | yes | tens of ms per label (unverified) | MIT | heavy | SKIP: slower, no better than exemplars |
| medspaCy ConText 1.3.1 | spacy and deps: venv 311 MB; no model needed with blank pipeline | yes | 0.2 ms | MIT | clean | see below |
| negspaCy 1.1.0 | small, needs spaCy | yes | ms | MIT | clean | negation only |
| pyConTextNLP 0.7 | last release 2019 | yes | n/a | Apache | stale | SKIP |

medspaCy measured behaviour with default rules on 8 test sentences:

| Sentence | Result | Safe? |
| --- | --- | --- |
| "I do not have any chest pain" | negated | good |
| "if I fall I will call you" | hypothetical | good |
| "no fall today" | negated | good |
| "I am not sure if my chest hurts" | tagged negated and hypothetical | BAD: would suppress a hedged symptom |
| "my husband fell in the bathroom" | experiencer = other | BAD if it downgrades: third-party falls must alert |
| "she has collapsed" | not marked other | inconsistent |
| "I fell yesterday morning" | not marked historical | inconsistent |

Conclusion: ConText is not a drop-in fix and costs 311 MB. Our existing negation window plus hedge list already does the useful part. Embeddings cannot see negation ("I do not have any chest pain" scored 0.80 on bge, 0.83 on MiniLM, the highest negative). So the design must be asymmetric: negation may only block a keyword or embedding match when it is explicit and local, hedges never block, and third-person experiencer never blocks.

LLM second opinion (Claude), verified on platform docs today:

| Item | Fact |
| --- | --- |
| Structured output | `output_config.format` with `json_schema` (grammar constrained), plus `strict: true` on tool input schemas; both supported on Haiku 4.5 and 5.5 |
| Haiku 5.5 price | $0.10 per MTok input (prompts up to 100k), $0.50 per MTok output; cache read $0.01 |
| Cost per call | about 700 input and 80 output tokens is about $0.00011, so 10,000 calls is about $1.10 |
| Haiku 4.5 price | $1 / $5 per MTok per aggregator sites only (unverified) |
| Guardrail pattern | schema `{urgency 1-4, cues[], third_party bool, uncertain bool}`; code applies `max(model, guard)` and a failure defaults to urgency 3 (already ADR) |

## 4. Recommended plan (one)

Keep the regex guard as the cheap first floor, add an embedding nearest-neighbour floor beside it, keep the model as the main scorer, and measure honestly.

| Step | Detail | Hours |
| --- | --- | --- |
| 1 Bank | About 150 exemplars: 12 to 15 per category in the table above (1 to 10), 5 each for 11 and 12, written in first and third person, with slang and dialect. Store as a data file `triage_exemplars.yaml` with category, level, text | 3 |
| 2 Matcher | `fastembed` with `all-MiniLM-L6-v2` (quantised 23 MB model if it holds up). Embed the bank once at start (about 50 ms), top-1 cosine per clause. Two thresholds: high gives floor 4, mid gives floor 3. Raise only, never lower. Behind a port with an in-memory fake so tests need no download; optional extra in `pyproject` | 3 |
| 3 Negation | Reuse the existing window rules on the clause before the embedding floor applies. Rule: explicit negator within 4 tokens blocks; hedge words, third person and past tense never block | 1 |
| 4 Evaluation | Held-out batches written by someone who has not seen the bank, 40 positives and 40 negatives per batch, 3 batches, produced before tuning thresholds. Report separately: under-escalation (true urgency 4 got less than 4, the dangerous error), under-escalation by one level, and over-escalation (alert rate on benign speech, the alarm-fatigue cost). Tune thresholds on batch 1, freeze, report on batches 2 and 3 | 3 |
| 5 Failure bank | Every miss from the evaluation becomes an exemplar, but then that batch is burnt: write a fresh batch to report | 1 |
| Total | | about 11 |

Target: at least 90% recall (a floor of at least level 4 for level-4 phrases) on batches 2 and 3 with a Wilson 95% interval reported (40 positives cannot prove 90%; the lower bound will be about 77% at 36/40, so say so). Over-escalation reported but not gated. My toy result (7/10 at 33 exemplars) suggests the plan is plausible but the 90% target is NOT demonstrated yet.

## 5. Not verified

| Item | Status |
| --- | --- |
| Pi 5 latency | not measured, estimates only |
| Manchester Triage details, ESI v5 text | could not retrieve |
| Nursing-home-specific alarm fatigue evidence | none found; sources are hospital |
| Embedding numbers | author-written 20-phrase toy set; not a recall estimate |
| Haiku 4.5 price | aggregator only; Haiku 5.5 from official pricing page |
| Download reliability | the four models fetched fine here (15 to 37 s each); flakiness not reproduced |

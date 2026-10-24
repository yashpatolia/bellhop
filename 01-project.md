# Bellhop: the robot that answers the call bell

Oct 9, 2026 · @yash

Bellhop is a small AI robot that rolls to a resident's room when the bell rings, talks to them, and calls a nurse only when the situation needs one.

## The problem

Care homes are short-staffed, and one nurse can be responsible for 20, 30 or even 50 residents. Residents are told to use the call bell only for emergencies or something important, but some ring to talk or to ask for a coffee. A nurse cannot tell from the bell alone which kind of call it is, so every ring pulls them away from someone who may need clinical care.

**The numbers behind it** (sources and caveats are on the Research tab):

- **Thin staffing.** No federal staffing ratio is in force. US nursing homes average [3.68 nursing hours per resident per day against 4.10 recommended](https://nursinghome411.org/data/staffing/staffing-q4-2023/), and [70.3% fall short of the 2.45 aide-hour benchmark](https://www.hebrewseniorlife.org/news/new-study-shows-nursing-home-staffing-patterns-can-reduce-harmful-falls-among-residents). In four New York homes each aide had [8 to 13 residents and each LPN 9 to 14](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7148550/).
- **Calls that don't need a nurse.** In a [survey of 808 hospital staff](https://link.springer.com/article/10.1186/1472-6963-10-52) only 52% said calls needed a nurse, with about 6.5 calls an hour per person at roughly 4 minutes each. By our estimate that is about 1.7 hours of every 8-hour shift. In one nursing home, [72% of staff who answered open questions](https://journals.sagepub.com/doi/10.1177/2377960820903546) said residents ring for non-urgent requests.
- **Slow responses.** In a 300-bed home [the average response was 9 minutes](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7148550/), about half of calls missed the home's 5-minute standard, and in 7.5% of calls residents got up or shouted for help.
- **Falls are the danger.** [More than half of nursing-home residents fall each year](https://nursinghome411.org/wp-content/uploads/2022/09/Fact-Sheet-Fall-Prevention.pdf), and in well-staffed homes [each extra RN hour went with nearly 40% fewer injurious falls](https://www.hebrewseniorlife.org/news/new-study-shows-nursing-home-staffing-patterns-can-reduce-harmful-falls-among-residents).

We found no study that counts deaths caused by non-urgent calls, so our claims are about nurse time and response speed, not lives saved.

**Pitch:** don't send a nurse to every bell. Send a robot first, and let it work out whether a nurse is needed.

## How it works

&#91;embedded content: bell to outcome · 4 steps, 4 urgency levels\]

Bellhop reads the resident's memory before it speaks, so it already knows who it is talking to. Urgency 1 and 2 never reach a nurse, 3 arrives with a short written summary, and 4 sets off an alert immediately while the robot stays with the resident.

## The agents

Six core agents, each with one job, pass work to each other. The split also makes the build easy to share across teammates.

| Agent | Job | Runs on | Uses |
| --- | --- | --- | --- |
| Dispatcher | Decides who answers each bell: robot, nurse, or both, using the resident's risk flags and how busy nurses are | Cloud | Shared realtime state |
| Navigator | Drives to the room, stops for obstacles, parks facing the resident | Robot (Pi 5) | Line tracking, ultrasonic sensor, servo head |
| Companion | Holds the conversation: listens, answers, jokes, reminds, stays calm with confused residents | Cloud + robot audio | Speech-to-text, Claude, text-to-speech |
| Triage | Scores urgency 1 to 4 from what was said, how it was said and what the camera sees | Cloud | Jev for the fast score, Claude for the reasoning |
| Memory | Keeps each resident's profile: likes, people, routines, mood over time. Fed to Companion before every visit | Cloud | Vector search, resident database |
| Staff Liaison | Pings the right person with a short summary, or creates a task for an aide, the kitchen or family | Cloud | Nurse dashboard, push alerts |

## Hardware and materials

The robot is the Freenove 4WD Smart Car Kit with a Raspberry Pi 5 on top. The kit already gives us four drive wheels, a camera and ultrasonic head on servos, line-tracking sensors and LEDs. We add audio, a bell and a few props.

| Part | Role in Bellhop | Status |
| --- | --- | --- |
| Freenove 4WD Smart Car Kit | Chassis, motors, camera, ultrasonic sensor, servo head, line tracking, LEDs | Have |
| Raspberry Pi 5 | Runs the robot's drive code, camera and audio streaming | Have |
| Batteries for kit and Pi | Kit does not include them; use a separate stable supply for the Pi so motors cannot brown it out | Confirm |
| USB speakerphone (mic + speaker) | The robot's ears and voice; the kit has no audio | Confirm |
| Wi-Fi bell button (ESP32 or Pico W) | The call bell; pressing it sends a call to the Dispatcher. A web button works as a backup | Confirm |
| Black tape and QR stickers | Hallway line for Navigator; one QR per room door so the camera knows where it is | Make |
| Touchscreen display on the robot | Board games, captions for hard-of-hearing residents and a friendly face | Have |
| Laptop or tablet | Nurse dashboard and alerts during the demo | Have |
| Phone hotspot or travel router | Backup network in case venue Wi-Fi is unreliable | Confirm |

The kit's LEDs double as a status light: idle, listening, nurse on the way and emergency each get a colour, so judges can read the robot's state from across the room.

## Software and tools

Most of this is glue around services we call, which is what makes 48 hours realistic. Claude writes the glue; we spend our time on the robot and the demo.

| Layer | Choice | Why |
| --- | --- | --- |
| Robot code | Python on the Pi 5, starting from Freenove's open-source car server | Motors, servos, camera and sensors already work |
| Voice | Cartesia Ink (speech-to-text) and Sonic (text-to-speech), streamed. Piper running on the Pi is the local option, with voice picks on the Research tab | Fast first audio and built-in turn detection, so it feels like a conversation |
| Conversation brain | Claude with a per-resident persona and memory in the prompt | Warm, flexible dialogue and good judgement on edge cases |
| Urgency scoring | Jev, with Claude as the fallback and the explainer (details on the Research tab) | One fast typed call returns urgency and category with probabilities |
| Agent orchestration | Claude Agent SDK for Companion and Triage; plain async Python workers for the rest | Keeps each agent small and testable |
| Shared realtime state | SpacetimeDB: call queue, robot status, resident profiles, visit log | The dashboard updates live with no polling code |
| Memory recall | Semantic search over each resident's notes, from the sponsor list below | Pulls the right memory into the chat in milliseconds |
| Nurse dashboard | Web app (TypeScript/React) with a live call feed, robot status, summaries and a nurse-minutes-saved counter | The screen judges will look at |
| Alerts | Dashboard banner plus a phone notification | Urgency 3 and 4 must reach a human fast |
| Vision (stretch) | Claude vision on camera snapshots for "person on the floor" and posture checks | Adds an emergency trigger beyond what the resident says |

## Sponsor APIs for bonus points

Bonus points are optional, so we pick a few sponsors that do real work in the build rather than name-dropping ten. The first five rows are the recommended set; each has a genuine job in the flow above. What each sponsor offers and how sure we are is on the Research tab.

| Sponsor | Job in Bellhop | Fit |
| --- | --- | --- |
| Anthropic (cohost) | Claude is the Companion's brain, writes the nurse summaries, reasons about edge cases and reads camera snapshots | Core |
| Cartesia | Streaming speech-to-text with turn detection and fast text-to-speech, so the robot talks like a person | Core |
| SpacetimeDB (cohost) | Shared realtime state for the call queue, robot status, resident profiles and visit log; the dashboard updates live | Core |
| Fetch.ai | Register Dispatcher, Triage and Liaison as agents on Agentverse so a nurse can ask "what happened in room 12?" through ASI:One | Strong |
| Moss | Sub-10 ms semantic recall of a resident's preferences and history, inside the voice loop | Strong |
| Engramme | Alternative or add-on memory layer for long-term resident memory, if API access works | Optional |
| Elastic | Hybrid search over care-plan notes and visit logs; Agent Builder for a nurse-facing question agent | Optional |
| Convex | Alternative to SpacetimeDB for shared state; we use one or the other, not both | Optional |
| SpaceXAI | Grok Voice as a multilingual voice fallback if Cartesia has an outage | Optional |
| Runpod | GPU endpoint for an open vision model (fall detection) or an offline-capable Llama if we want a privacy story | Stretch |
| Context.dev | Pulls today's weather, news or sports so the robot has something fresh to chat about | Stretch |
| Creao | Builds a scheduled shift-summary agent for nurses without extra code | Stretch |
| Coinbase | x402 payments let an agent reorder supplies in stablecoin after a human signs off. The very last step, only if everything else works (inventory idea on the Extra ideas tab) | Last |

## 48-hour build plan

&#91;embedded content: 48-hour plan · 3 lanes, 13 items\]

The first end-to-end run (a bell press that ends in a spoken answer and a dashboard entry) is the milestone that matters. Everything after it is improvement, and the last ten hours are for rehearsal, not new features.

### Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Venue Wi-Fi is slow or drops, and voice needs the network | Phone hotspot or travel router; keep replies short so audio streams quickly |
| Floor navigation is unreliable | Drive the robot with the Freenove app for the demo while everything else stays real |
| Pi browns out when the motors draw current | Separate stable supply for the Pi, as in the kit's own reviews |
| Triage gets a case wrong on stage | Bias toward escalating; Claude double-checks any score below a confidence threshold; rehearse scripted cases |
| A sponsor API has no access or breaks | Each sponsor sits behind one small adapter, so Claude-only or local versions can replace it in minutes |

## Demo script

Three short scenes, one per outcome tier, with a teammate playing the resident. The dashboard stays on screen throughout.

| Scene | Resident says | Bellhop does | Dashboard shows |
| --- | --- | --- | --- |
| 1. Just lonely | "Can I get a cup of tea and a chat?" | Rolls over, greets her by name, remembers she takes two sugars and asks about her grandson, and sends a tea request to the kitchen | Urgency 1, resolved, no nurse alert |
| 2. Needs a nurse, not urgently | "My hip has been aching since last night." | Asks where and how bad on a 1 to 10 scale, reassures her, and sends the nurse a short summary | Urgency 3 card with the summary; nurse taps "on my way" |
| 3. Emergency | "I've fallen and I can't get up." (or the camera sees someone on the floor) | LEDs go red, alerts the nurse immediately, stays and keeps the resident calm until help arrives | Urgency 4 banner, alert time, live transcript |

The closing shot is the counter for calls the robot resolved and nurse minutes saved. It uses an assumed minutes-per-call that we state openly on screen.

### Alternative opening: judges play the residents

- Bellhop opens by saying who it is and what it can do, which steers judges toward questions we have rehearsed.
- A teammate stands behind the robot holding funny prompt cards, such as "ASK IT TO PLAY A GAME", to guide the next question.
- This runs for about the first minute. Then we switch to the dashboard and show that the conversation was recorded and the judge is now a resident in the database.
- The venue will be loud, so the judge has to speak close to the robot or it may pick up someone else. A small, close-up robot makes that feel natural.

## Cost and savings

A robot is a one-time hardware cost plus usage-based API fees, so extending to more residents means adding robots. In the base case one robot frees about 970 staff hours a year, worth about $24,100 at a loaded $24.80 an hour, for about $3,200 a year in running costs, and the hardware pays back in under two months. These are model results from untested assumptions (4 minutes saved per call, a $2,500 fleet robot, 40 calls resolved a day), laid out with sources on the Research tab. Freed time becomes cash only if it cuts overtime or agency hours, or buys more clinical care.

| Calls resolved a day | Staff hours freed a year | Equivalent staff | Value of freed time | API plus upkeep | Net a year | Hardware payback |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 243 | 0.12 | $6,035 | $1,087 | $4,948 | 6.1 months |
| 20 | 487 | 0.23 | $12,069 | $1,799 | $10,270 | 2.9 months |
| 40 (base) | 973 | 0.47 | $24,139 | $3,222 | $20,917 | 1.4 months |
| 70 | 1,703 | 0.82 | $42,242 | $5,357 | $36,885 | 0.8 months |

- **Per call:** about $0.22 of running cost against about $1.65 of staff time, roughly 7.5 times cheaper.
- **Per resident:** a net saving of about $700 a year at 30 residents per robot.

| Robots (base case) | One-time hardware | Net saving a year | Residents covered |
| --- | --- | --- | --- |
| 1 | $2,500 | $20,917 | 30 |
| 10 | $25,000 | $209,170 | 300 |
| 50 | $125,000 | $1,045,850 | 1,500 |

The dashboard shows these live: calls resolved without a nurse, minutes saved with the assumption labelled, cost per call, and the share answered within 10 minutes.

## Scope and guardrails

- **Prototype only.** Residents in the demo are teammates, there is no real patient data.
- **The bell stays a bell.** Anyone can still press it to reach a person, and the robot never discourages someone from calling a nurse.
- **Lean toward escalation.** When the score is uncertain, Bellhop treats the call as more urgent, not less.
- **No diagnosis.** The robot gathers information and passes it on; it does not give medical advice.
- **Calm with confusion.** For residents with memory loss it stays gentle, never argues and never corrects them sharply.

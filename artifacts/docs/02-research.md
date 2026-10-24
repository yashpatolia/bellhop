# Research

Everything we looked up while shaping Bellhop, kept off the main page.

## Why the problem is real

The best evidence we found says a large share of call-bell traffic does not need a nurse, and the reasons are predictable. Most of it comes from hospitals rather than care homes, and much of it is self-reported by staff.

- **Volume and speed.** In a [2010 survey of 808 nursing staff in four US hospitals](https://link.springer.com/article/10.1186/1472-6963-10-52), each person answered about 6.5 calls an hour, and by their own estimate a call took about 4 minutes to answer.
- **Many calls don't need a nurse.** In the same survey only 52% of staff said the calls required a nurse's attention, and 53% said answering them kept them from the critical parts of their job.
- **The reasons are predictable.** Toileting, pain medication and IV alarms led the list. The survey's options also included getting a nurse's attention and asking for companionship at the bedside.
- **Tiers already exist on paper.** The author suggests call panels with three levels: urgent, normal, and orderly assistance such as repositioning, personal help, information or companionship. That is close to our four-level triage.
- **Industry estimate.** A [Studer Group article](https://www.studergroup.com/hardwired-results/hardwired-results-03/give-your-nurses-back-166-hours-every-month) (a consulting firm, so read it as marketing) puts call-light time at about 10,000 minutes per nurse per month and says four reasons made up nearly 71% of calls on one orthopedic unit.
- **A target metric.** A [Belgian nursing-home study](https://research.vu.nl/en/publications/care-on-demand-in-nursing-homes-a-queueing-theoretic-approach/) built a queueing model from real call-button data and proposed an 80/10 service level: 80% of calls answered within 10 minutes. We can borrow that as a dashboard metric.

**Not verified:** no study we found counts deaths caused specifically by nurses being tied up on non-urgent calls. The "By the numbers" section below uses the nearest evidence instead.

## By the numbers

The figures answer three questions in turn. Nursing-home data is used where we found it; hospital data fills gaps and is labelled. Several numbers are from a single home or a survey of staff, so treat them as ranges, not facts to quote without the caveat.

### How many residents is one nurse responsible for?

The 20 to 50 residents in our brief is plausible for licensed nurses, but there is no single US figure because no federal ratio is in force.

| Measure | Figure | Source |
| --- | --- | --- |
| Average nursing time per resident, all nursing staff | 3.68 hours a day in late 2023, against 4.10 recommended by a 2001 federal study | [NursingHome411](https://nursinghome411.org/data/staffing/staffing-q4-2023/) |
| Federal minimum | None. The 2024 rule (3.48 hours, with 0.55 RN and 2.45 aide hours) was repealed in December 2025 | [AHA](https://www.aha.org/news/headline/2025-12-02-cms-repeals-minimum-staffing-requirements-skilled-nursing-long-term-care-facilities) |
| Homes meeting the 2.45 aide-hour benchmark | Nearly 30%; 70.3% fell short | [Hebrew SeniorLife](https://www.hebrewseniorlife.org/news/new-study-shows-nursing-home-staffing-patterns-can-reduce-harmful-falls-among-residents) |
| Observed assignments, four New York homes | 8 to 13 residents per aide and 9 to 14 per LPN, with thinner staffing on evenings and nights | [JMIR 2020](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7148550/) |
| State minimums | New Jersey 1 aide per 8 residents on days. Pennsylvania 1 aide per 10 (days), 11 (evenings), 15 (nights) and 1 LPN per 25, 30 and 40. Florida 1 aide per 20 and 1 licensed nurse per 40 | [Boostpoint summary](https://boostpoint.com/industries-healthcare/nursing-home-staffing-ratios/) |

Our arithmetic: 3.68 nursing hours per resident per day over 24 hours is about one nursing staff member for every 6.5 residents on average. That includes managers and breaks and is worse at night, so a nurse covering 20 to 50 residents on a shift is realistic.

### How often do residents ring for things that don't need a nurse?

| Finding | Figure | Setting and source |
| --- | --- | --- |
| Staff who said calls needed a nurse | 52%, so about 48% did not | 808 staff in four hospitals, [2010 survey](https://link.springer.com/article/10.1186/1472-6963-10-52) |
| Calls answered per staff member | About 6.5 an hour, roughly 52 in an 8-hour shift | Same survey |
| Requests that needed no nurse | Nearly half | Hospital improvement project, from [call-system categories](https://diglib.uwgb.edu/digital/api/collection/p17003coll5/id/69/download) |
| Staff saying residents use bells for non-urgent requests | 72% of those who answered the open questions, about 66 people | One 300-bed nursing home, [2020 survey](https://journals.sagepub.com/doi/10.1177/2377960820903546) |
| Common nursing-home requests | Position changes first, then toileting and accidental presses, with peaks around mealtimes | Same paper and the [JMIR study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7148550/) |

Our estimate, from the hospital figures: about half of roughly 52 calls is 26 calls per 8-hour shift. At 4 minutes each that is about 104 minutes, or 1.7 hours, per staff member per shift spent on calls that didn't need a nurse. Nursing-home timings may differ.

### How often does delay cause harm?

We found no study that links non-urgent calls to deaths. The evidence below shows that slow responses are common, that falls are the main danger, and that thin staffing goes with more injuries.

| Finding | Figure | Source |
| --- | --- | --- |
| Observed response times in a 300-bed home (201 calls) | Average 9 minutes; about half over the home's 5-minute standard; some up to 20 minutes | [JMIR 2020](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7148550/) |
| Residents told to wait, or forgotten | Asked to wait in 10% of calls; forgotten in about 3% | Same study |
| Residents who got up or shouted when no one came | 7.5% of calls (15 of 201) | Same study |
| Residents who fall each year | More than half | [NursingHome411 fact sheet](https://nursinghome411.org/wp-content/uploads/2022/09/Fact-Sheet-Fall-Prevention.pdf) |
| Deaths from falls in US nursing homes | About 1,800 a year, with residents 5% of people over 65 but 20% of fall deaths in that age group | [Law-firm page citing the CDC](https://www.dsslaw.com/blog/nursing-home-slip-and-falls-how-big-is-the-problem/) |
| Faster call response and falls | Faster response linked to lower fall and injurious-fall rates in four hospitals | [BMC study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3364911/) |
| Staffing and injurious falls | In well-staffed homes, each extra RN hour went with nearly 40% fewer injurious falls (11,183 homes) | [Hebrew SeniorLife](https://www.hebrewseniorlife.org/news/new-study-shows-nursing-home-staffing-patterns-can-reduce-harmful-falls-among-residents) |
| After-hours staffing, Australia | An adverse event on average every second shift per home; fewer nurses after hours went with more falls and pressure injuries (10 homes, 1,020 beds) | [Collegian 2022](https://researchonline.nd.edu.au/med_article/1523) |
| Preventable deaths, Australia | Falls were 81.5% of preventable nursing-home deaths in a coronial review | [Union summary](https://www.nswnma.asn.au/?p=3127) |

All of these are associations, and the staffing studies do not prove cause. The 1,800 figure comes through a secondary page, so check the CDC original before quoting it.

**Safe claims for the pitch:** staff report that a large share of calls don't need a nurse; responses in nursing homes are often slower than their own standard; falls are the main danger and track with thin staffing. Bellhop should claim to cut nurse time on non-urgent calls and to shorten response times, which the dashboard can measure, and not to prevent deaths.

## Cost and savings model

In the base case one robot frees about 970 staff hours a year, worth about $24,100, for about $3,200 a year in running costs plus a one-time hardware cost that pays back in under two months. This is a model built on assumptions we have not tested, so treat it as a way to explain scale, not a forecast. Freed time turns into cash only when it cuts overtime or agency hours, or lets staff give more clinical care.

### Assumptions (change these first)

| Input | Value | Basis |
| --- | --- | --- |
| Loaded cost of care-staff time | $24.80 an hour | [BLS mean nursing-assistant wage](https://www.bls.gov/opub/ted/2025/nursing-assistants-week-recognizes-the-third-largest-healthcare-occupation.htm) of $19.84 (May 2024), times 1.25 for benefits, which is our assumption |
| Minutes saved per call the robot resolves | 4 | From the hospital survey and Studer estimate; the nursing-home study saw 9-minute average responses |
| Conversations per resolved call | 1.5 | Our assumption: some conversations end in a handoff to staff |
| Hardware per fleet robot, one time | $2,500 | Placeholder for a sturdier build. Our prototype is about $250, and the kit alone lists at $75.87 |
| Upkeep | $375 a year | 15% of hardware, our assumption |
| Residents covered per robot | 30 | Our assumption |

The API cost per conversation is our estimate for a 3-minute exchange:

| Part | Cost | Basis |
| --- | --- | --- |
| Speech-to-text, 3 minutes | $0.0065 | Ink at about [$0.13 an hour](https://www.cloudtalk.io/cartesia-pricing/) on Cartesia's Scale plan |
| Text-to-speech, 1.5 minutes | $0.047 | About $1.87 per hour of speech on [Scale, per a competitor's comparison](https://soniox.com/pricing/tts/soniox-vs-cartesia), at roughly one credit per character per [Cartesia's docs](https://docs.cartesia.ai/pricing) |
| Claude, about 30,000 input and 1,000 output tokens | $0.07 | [$2 and $10 per million tokens](https://anotherwrapper.com/tools/llm-pricing/claude-sonnet-5-5) per a price tracker |
| Jev, about 20,000 input tokens | Under $0.001 | $0.042 per million input tokens |
| **Total** | **About $0.12, rounded up to $0.13** |  |

### One robot, four usage levels

| Calls resolved a day | Staff hours freed a year | Equivalent staff | Value of freed time | API plus upkeep | Net a year | Hardware payback |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 243 | 0.12 | $6,035 | $1,087 | $4,948 | 6.1 months |
| 20 | 487 | 0.23 | $12,069 | $1,799 | $10,270 | 2.9 months |
| 40 (base) | 973 | 0.47 | $24,139 | $3,222 | $20,917 | 1.4 months |
| 70 | 1,703 | 0.82 | $42,242 | $5,357 | $36,885 | 0.8 months |

Equivalent staff uses 2,080 hours per full-time job. Even at 10 calls a day the hardware pays back inside a year.

**Headline numbers for the base case:**

- A resolved call costs about $0.22 in running costs, against about $1.65 of staff time for the same 4 minutes. That is roughly 7.5 times cheaper.
- One robot does the work of about 0.47 of a full-time aide, whose loaded cost is about $51,600 a year.
- The net saving is about $700 per resident per year, at 30 residents per robot.

### Extending to a fleet (base case)

| Robots | One-time hardware | Value of freed time a year | Running cost a year | Net a year | Residents covered |
| --- | --- | --- | --- | --- | --- |
| 1 | $2,500 | $24,139 | $3,222 | $20,917 | 30 |
| 5 | $12,500 | $120,695 | $16,110 | $104,585 | 150 |
| 10 | $25,000 | $241,390 | $32,220 | $209,170 | 300 |
| 25 | $62,500 | $603,475 | $80,550 | $522,925 | 750 |
| 50 | $125,000 | $1,206,950 | $161,100 | $1,045,850 | 1,500 |

The rows scale linearly because each robot is independent. The cost is mostly one-time hardware plus usage-based API fees, so there are no per-seat licences.

**What this leaves out:** connecting to real nurse-call systems, insurance and liability, regulatory review, staff training, repairs and Wi-Fi coverage, and any night shift where calls are fewer. Voice plans also have credit limits: Cartesia's Scale plan covers roughly 3 robots at the base usage, so a larger fleet needs volume pricing.

**What the demo can measure:** the dashboard can show calls resolved without a nurse, minutes saved using the 4-minute assumption (labelled on screen), cost per call against staff cost per call, and the share of calls answered within 10 minutes.

## What Jev is

Jev is a model that makes decisions instead of writing text: you send it a piece of state and a set of typed questions, and it returns answers with probabilities in about a tenth of a second. It is the first "System One" model from TypeSafe AI, a San Francisco lab, and it launched in mid-September 2026.

- **How it works.** Per [Vercel's announcement](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway), you pass a state and named questions. Boolean returns a probability, Choice picks one option from a set you define, and Score grades against a scale you define. All questions are answered in parallel.
- **No words out.** It does not write replies or explanations, which is why we would pair it with Claude rather than replace Claude.
- **Speed and price.** [TypeSafe's site](https://typesafe.ai) claims up to 193.6x faster and 444.6x cheaper than LLMs on its own workflows, with a demo finishing in 0.114 seconds. [Trending Topics](https://www.trendingtopics.eu/jev-warum-dieses-neuartige-ki-modell-gerade-entwickerinnen-begeistert/) reports 70 to 500 ms responses and $0.042 per million input tokens, with no charge for output.
- **Calibrated confidence.** It is trained to return probabilities you can set thresholds on, so software acts when confident and escalates when not. That is the behaviour we want from a triage step.
- **Where the claims are weak.** The headline numbers are the vendor's own, and its reference answers were an average of two frontier chat models. Confidence scores need checking on our own data. Choice questions top out at 255 options, and it does not handle images.
- **Access.** Early access with a waitlist, and the API briefly buckled under launch demand. [Vercel AI Gateway](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway) serves it as `typesafe-ai/jev`, which a community list says needs no TypeSafe waitlist. The same list names Cloudflare Workers AI, OpenRouter and Netlify as other routes.
- **The name.** It comes from Jevons, the economist whose paradox says cheaper resources get used more.

## How Jev could plug into Bellhop

Jev is worth using for one job, the Triage score, with Claude as the backup and the voice. Triage is a pure decision (conversation in, category out), it must be fast so the robot never goes quiet, and the probabilities tell us when to escalate. Jev should not touch conversation, memory or anything that needs words.

The state is the transcript so far, a short description of what the camera sees, the resident's risk flags and the time of day. Questions we would ask on every turn:

| Question | Type | What it decides |
| --- | --- | --- |
| Does this resident need a nurse right now? | Boolean | Fires an immediate alert above a threshold we set |
| How urgent is this, 1 to 4? | Score | The tier shown on the dashboard |
| What is this about? Chat, comfort item, toileting, pain, medication, breathing or chest, fall, confusion, other | Choice | Who gets the task: aide, kitchen, nurse |
| Does the resident seem confused or disoriented? | Boolean | Switches Companion into its gentle mode |

A tenth of a second for the decision means Jev can score the call while Claude is still forming its reply, so escalation never waits on the conversation. Because Jev gives no reasons, Claude writes the plain-English summary the nurse reads.

**Ways to call it**, easiest first:

1. Vercel AI Gateway with the AI SDK's `evaluate` call (TypeScript). It also offers zero data retention and no-training options per request, which suits a health-data story.
2. TypeSafe's own HTTP API or Python SDK, which needs an early-access key.
3. Microsoft Agent Framework for Python, where [Microsoft documents an alpha TypeSafe integration](https://learn.microsoft.com/pl-pl/agent-framework/integrations/by-provider/type-safe-ai). Only relevant if we orchestrate with that framework.

**Plan B and testing.** Put Triage behind one small interface so the same four questions can go to Claude as a structured-output call if Jev access fails. Write about 30 labelled example calls from our demo scripts and use them to set the thresholds, which is also what Vercel's own guidance recommends.

## Sponsor research

Details below come from public docs and news summaries, not from the sponsors' hackathon briefs. Confirm API access, credits and judging criteria at each sponsor's table before committing. Fetch.ai's criteria in particular are taken from its other hackathon packs.

| Sponsor | What it offers | Notes |
| --- | --- | --- |
| [Cartesia](https://docs.cartesia.ai/get-started/overview) | Sonic 3.5 text-to-speech streams the first audio in about 90 ms; Ink 2 speech-to-text with built-in turn detection; 40+ languages | Strong fit. Its docs target real-time voice agents |
| [SpacetimeDB](https://spacetimedb.com/docs/resources/mcp) | A database that runs your server logic inside it and pushes live updates to clients; has a `spacetime mcp` command for coding agents | Strong fit for a live dashboard. Modules are written in Rust, C#, TypeScript or C++ |
| [Convex](https://docs.convex.dev/components/understanding) | Reactive TypeScript backend: queries update live, with built-in vector indexes and reusable components | Same job as SpacetimeDB. Pick one |
| [Fetch.ai](https://innovationlab.fetch.ai/events/hackathons/mhacks-2026/hackpack) | uAgents (Python agent library), Agentverse (registry and hosting), ASI:One (an LLM that finds and calls registered agents through a Chat Protocol) | Its hackathon packs score registering agents on Agentverse and ASI:One discoverability. Good match for a multi-agent project |
| [Moss](https://ycombinator.com/companies/moss) | Semantic search runtime that answers in under 10 ms and runs in the browser, on a device or in the cloud | Fits memory recall inside a voice loop |
| [Engramme](https://www.testingcatalog.com/engramme-opens-memory-api-beta-for-app-developers-and-teams/) | Memory API in public beta, built around retrieving real past events from tools like Gmail, Zoom and Slack | Aimed at work apps, so fit for resident memory is unclear. Don't confuse it with Engram, a different memory startup |
| [Elastic](https://www.elastic.co/search-labs/blog/ai-agentic-workflows-elastic-ai-agent-builder) | Hybrid keyword and vector search; Agent Builder for agents with tools; MCP and agent-to-agent support | Heavier setup than Moss for the same recall job |
| [SpaceXAI](https://www.testingcatalog.com/spacexai-launches-21-new-grok-voices-on-xai-console/) | Grok realtime voice agent, text-to-speech and speech-to-text APIs across 25+ languages (formerly xAI) | Optional fallback voice stack |
| [Runpod](https://www.runpod.io/product/serverless) | Serverless GPU endpoints with per-second billing | Only needed for a vision or open model we host ourselves |
| [Context.dev](https://toolradar.com/tools/context-dev) | Web scraping, search and structured extraction API with a free tier | Light fit: fresh chat topics for the robot |
| [Creao](https://pulse2.com/creao-ai-10-million-raised-to-build-autonomous-super-agent-platform-for-ai-workflows/) | Builds reusable scheduled agent apps from a chat prompt, with memory | Light fit: a shift-summary agent |
| [Wajo](https://www.trendingaitools.com/?p=45165) | Fo, an action agent that makes calls and emails and hands tasks to a human when stuck | Invite-only alpha, so risky to depend on |
| [Decagon](https://decagon.ai/blog/aop-the-future-of-cx) | Customer-support agents defined by natural-language "Agent Operating Procedures" | Useful idea for writing our triage policy, but no public API we could plan around |

**Checked and not a fit:** Hyphenate builds finance automation agents, AfterQuery sells expert training data, and Armadin does offensive cybersecurity testing. The trading and payments sponsors (Visa, Capital One, Citadel, Jane Street, D. E. Shaw, Coinbase, MoonPay) have no obvious role in the core flow. The exception we're weighing is Coinbase's x402 for nurse-approved restocking, on the Extra ideas tab.

**Not researched or not identified:** Apify, Bright Data, Atlassian, Figma, Canva, Adobe, Meta, Scale AI, Factory, Greptile, Microsoft beyond the Agent Framework note above, and the sponsors we could not identify from the channel names, such as Opal Electronics and Savvy. Ask about those at the booths, especially any hardware or parts offers.

## Existing robots and how Bellhop differs

Two robots are the closest neighbours. In what we found, neither is described as answering the call bell and triaging it.

- **Moxi** from Diligent Robotics is a hospital robot that fetches and delivers supplies so clinical staff don't have to; [per The Robot Report](https://www.therobotreport.com/diligent-robotics-joins-agetech-collaborative-aarp-accelerator-program/) it is expanding into senior living and long-term care.
- **ElliQ** from Intuition Robotics is a [tabletop AI companion for older adults](https://venturebeat.com/ai/intuition-robotics-elliq-help-the-aged) that talks, keeps them company and connects them to family and caregivers.

Bellhop is mobile like Moxi and conversational like ElliQ, but its trigger is the call bell and its job is deciding who should respond. That claim comes from a quick search only, so check it before calling the idea novel on stage.

## Notes on the Freenove kit

- **What it is.** Per the Amazon listing, a four-wheel-drive car with a rotatable head holding a camera and ultrasonic sensor, line tracking, app control from Android, iPhone or a computer, and downloadable step-by-step Python code. It works with Raspberry Pi 5, 4B, 3B+ and others. The Pi and batteries are not included.
- **Open code.** The car's server code is on [Freenove's GitHub](https://github.com/Freenove/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi), so we can run our own audio and navigation as a separate process and leave their drive code alone.
- **Proven on a Pi 5.** One builder's [hands-on page](https://denis-legault.duckdns.org/4wd-car-kit/index.html) covers motor, servo and ultrasonic tests on a Pi 5, controlled from Freenove's iPhone client. That client is our manual-drive fallback.
- **Gotchas from reviews.** One [reviewer](https://www.desertcart.lk/products/166100862) saw the Pi lose power at full throttle on weak batteries and a tutorial camera app fail until they tried libcamera. An older review mentions Python 2.7, so check which Python version the current download expects.
- **No audio.** The listing mentions no microphone or speaker, and from general knowledge the Pi 5 has no headphone jack, so plan on a USB speakerphone.

## Robot voice and personality

We want Bellhop to sound bubbly and energetic, closer to an excited kid than the calm tone most care assistants use, because it's a little robot car. The voice we're trying first is Piper's semaine voice at medium size with the poppy speaker. Test voices on the [Piper samples page](https://rhasspy.github.io/piper-samples/#en_US-amy-medium).

Piper's English voices on Hugging Face (rhasspy/piper-voices), listed on 2026-10-21. Each comes in some of four sizes: x\_low, low, medium and high, and not every voice has every size.

- **en\_US (21):** amy, arctic, bryce, danny, hfc\_female, hfc\_male, joe, john, kathleen, kristin, kusal, l2arctic, lessac, libritts, libritts\_r, ljspeech, mike, norman, reza\_ibrahim, ryan, sam
- **en\_GB (9):** alan, alba, aru, cori, jenny\_dioco, northern\_english\_male, semaine, southern\_english\_female, vctk

| Voice | Size | Why it's a candidate |
| --- | --- | --- |
| semaine (speaker poppy) | Medium | Team's first pick to test |
| amy | Medium | Warm, clear female voice; a common pick for friendly assistants |
| kristin | Medium | Newer US female voice, more conversational than lessac |
| jenny\_dioco | Medium | British female with a friendly, bright tone |
| cori | Medium or high | British female, clear and fairly lively |
| ryan | Medium or high | The usual male pick; expressive for Piper |
| libritts\_r | High | Many speakers in one model, so we can pick the liveliest speaker ID; bigger and slower on the Pi |

- **Judge by ear.** Nobody has listened to these yet. The "energetic" labels come from general reputation.
- **Energy comes partly from settings.** Piper voices are trained on read speech, so none are truly bubbly. A slightly lower --length-scale (about 0.9) sounds faster and perkier, and a higher --noise-scale adds variation. For seniors, don't go much faster than 1.0, because clarity matters more than pace.
- **Size versus speed.** On a 2 GB Pi 5, medium voices are comfortable. High voices work but add latency, which streaming sentence by sentence should mostly hide.
- **Piper or Cartesia.** The Project tab plans on Cartesia Sonic for speech. Piper runs on the Pi with no network, so it's the fallback if venue Wi-Fi fails, or the main voice if we prefer how it sounds.

## Sources

Pages we opened in full:

- [Tzeng 2010, patient-initiated call lights (BMC Health Services Research)](https://link.springer.com/article/10.1186/1472-6963-10-52)
- [Studer Group, call-light time estimate](https://www.studergroup.com/hardwired-results/hardwired-results-03/give-your-nurses-back-166-hours-every-month)
- [Vercel, Jev on AI Gateway (16 Sep 2026)](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway)
- [Trending Topics, Jev explainer](https://www.trendingtopics.eu/jev-warum-dieses-neuartige-ki-modell-gerade-entwickerinnen-begeistert/)
- [TypeSafe AI home page](https://typesafe.ai)

Read through search summaries only: [Microsoft Learn, TypeSafe integration](https://learn.microsoft.com/pl-pl/agent-framework/integrations/by-provider/type-safe-ai), [community Jev list](https://github.com/valentynkit/awesome-jev-typesafe/wiki), the Belgian nursing-home queueing abstract and every sponsor and robot page linked above.

Added with the numbers: the [JMIR nursing-home call-light study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7148550/) and the [SAGE Open Nursing staff survey](https://journals.sagepub.com/doi/10.1177/2377960820903546) were opened in full. The other figures in that section came from search summaries, so open the source before quoting any of them.

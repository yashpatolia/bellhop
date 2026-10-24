# Extra ideas

Additions that make Bellhop more than a talking car. Change the status column as we decide.

## Ideas to add

| Idea | What it adds | Hours | Wow | Status |
| --- | --- | --- | --- | --- |
| Nurse-minutes-saved dashboard | A live counter of calls the robot resolved and the share of calls answered within 10 minutes, the 80/10 target from the Belgian study | 2 | High | Proposed |
| SBAR hand-off summary | Every escalation reaches the nurse in Situation, Background, Assessment, Recommendation form, a format nurses already use | 2 | High | Proposed |
| Mood and loneliness trend | Tracks tone and engagement across visits and flags "quieter than usual this week", an early warning no bell would give | 4 | High | Proposed |
| Multilingual conversation | Detects the resident's language and replies in it; Cartesia covers 40+ languages | 2 | High | Proposed |
| Shift-change digest | One summary per resident for the incoming nurse, built from the visit log | 2 | Medium | Proposed |
| Fall and distress detection | Claude checks a camera snapshot for someone on the floor and escalates without waiting for words | 4 | High | Proposed |
| Purposeful rounding mode | The robot visits at-risk residents on a schedule and asks about toileting, position and pain before they ring, the pattern Studer describes for cutting calls | 4 | Medium | Proposed |
| Pain check-in with trend | Asks for a 1 to 10 pain score, charts it through the day and flags a rise | 3 | Medium | Proposed |
| Dementia-safe mode | When the confusion question fires, the robot slows down, repeats gently, never corrects and alerts staff if distress grows | 2 | Medium | Proposed |
| Staff task board | Aides and kitchen tick off tasks the robot created, and the robot tells the resident "your tea is on its way" | 3 | Medium | Proposed |
| Accessibility settings | Captions on a small screen plus slower or louder speech, set per resident | 3 | Medium | Proposed |
| Privacy mode and audit log | A consent screen and a log of what was recorded and shared, which helps the pitch to care homes | 3 | Medium | Proposed |
| Multi-robot simulation | A virtual fleet on the dashboard shows how the Dispatcher shares calls across robots and nurses | 4 | Medium | Proposed |
| Family update (opt-in) | A gentle daily note to family about how the day went; needs consent from the resident | 3 | Medium | Proposed |

Hours are rough guesses per feature, assuming Claude writes most of the code.

### Companionship ideas (added)

| Idea | What it adds | Hours | Wow | Status |
| --- | --- | --- | --- | --- |
| Board games on the touchscreen (planned extension) | A small touchscreen or tablet on the robot lets residents play tic-tac-toe, checkers, chess, Go, bingo, Wordle-style word games, trivia or cards against Claude. Large buttons and voice control, adjustable difficulty, and warm commentary. Engagement feeds the mood trend. Start with tic-tac-toe and trivia, then add checkers | 6 | High | Proposed |
| Friendly conversation mode | Scheduled social visits for lonely residents: reminiscing about their photos and past, jokes, stories, music, and today's weather or news (Context.dev). Uses the resident's memory so each visit builds on the last | 3 | High | Proposed |

The display also unlocks captions for hard-of-hearing residents, so it pairs with the accessibility idea above. Games are the strongest visual demo and fit after the first end-to-end run. They should stay optional and never replace human contact. Describe them as companionship and activity, not as therapy.

### Team brainstorm (from the Calhacks ideas doc)

| Idea | What it adds | Hours | Wow | Status |
| --- | --- | --- | --- | --- |
| Call a specific nurse | A resident says "I want to see \[nurse\]" and the robot calls that nurse's phone, so the nurse can answer out loud through the robot's speaker. Nurses get an "I'm busy" setting in the mobile app, since this could be used often | 3 | High | Proposed |
| Remote camera view (Jeremy's idea) | A phone can open the robot's camera feed remotely, so staff can check on a room without walking there | 3 | Medium | Proposed |
| Inventory tracking with x402 restocking (last step) | Only after everything else works. The robot logs pills given and supplies used to the dashboard. When stock runs low, an agent drafts the order and pays in stablecoin through Coinbase's x402 protocol, but only after a nurse or doctor signs off. Takes inventory admin off nurses and gives Coinbase a sponsor role | 6 | Medium | Proposed |

Open questions from the brainstorm: would a care home fund stablecoin purchases from the same budget as normal inventory orders, and does restocking pull focus from the call-bell story? Hours and Wow for these three are rough guesses, like the rest.

### Added after the team review

| Idea | What it adds | Hours | Wow | Status |
| --- | --- | --- | --- | --- |
| Call reason tracking | Every call is tagged with why the robot was called and whether it was resolved, so we can see what residents need and improve | 2 | Medium | Proposed |
| Resident feedback monitoring | A spoken "did that help?" after each visit plus tone and engagement, logged per resident and flagged on the dashboard | 2 | Medium | Proposed |
| Audiobook reader | Reads an ebook aloud with pause, resume and saved position, using public-domain books | 4 | Medium | If time allows |
| Reminiscence mode (expanded) | Guided memory chats using the resident's profile, era-specific music, news and photos, with life-story notes and mood signals. Companionship, not therapy | 4 | High | If time allows |
| Apify content feed | Scrapes era-specific material for reminiscence, and supplier prices if we reach x402. Only if it does real work | 3 | Medium | Conditional |
| Fleet dispatch simulation | A virtual fleet that shows the Dispatcher choosing robots by position, battery and workload | 4 | Medium | Proposed |

## Recommended bundle

Five software-only additions fit in about 12 hours of work alongside the hardware lane: the nurse-minutes-saved dashboard, SBAR hand-off, mood and loneliness trend, multilingual conversation and the shift-change digest. Each shows up on the dashboard, so judges see it without extra staging, and together they make Bellhop look like a nurse workflow tool rather than a talking car.

- **If hours remain:** fall and distress detection, since it makes the emergency scene work even when the resident says nothing.
- **Pitch as roadmap:** family updates and the privacy audit log need real consent flows.
- **Don't claim:** that Bellhop diagnoses anything or reads health from a voice. It gathers information and passes it to staff.

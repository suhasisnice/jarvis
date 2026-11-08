# Jarvis roadmap: from 2/10 to 7/10

Written 2026-11-07. This is the order of work from now on. It replaces the v1/v2/v3 order in FEATURES.md
(that file stays as the feature list). The old "Phase 2" (phone access, docs/PHASE2.md) is built and becomes
step 1.1 below.

"10" = movie Jarvis. Every score has a **test** so we know when we've reached it; a score counts only
when its test passes.

## Scorecard

| Aspect | Now | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|---|
| **Talk** like a person | 4 | **5** | 6 | 7 |
| **Know** things | 4 | **5** | 6 | 7 |
| **Act** in the world | 0 | **5** | 6 | 7 |
| **Notice** things and bring them to you | 0 | 3 | 6 | 7 |
| **See** (screen, camera, photos) | 0 | 3 | 6 | 7 |
| **Everywhere** (laptop, phone, rooms) | 2 | **5** | 6 | 7 |

Phase 1 = 5 in four aspects (bold), with a start on the other two. Phase 2 = 6 in all. Phase 3 = 7 in all.

**Phase 1 build status (2026-11-07): all six aspects coded to 5, awaiting the user's live tests.**
- Talk: Smart Turn v3.2 (legion/smart_turn.py): reply 0.6 s after a finished sentence, wait up to 2.5 s mid-thought.
- Know: remember/forget facts (in every prompt), homelab status, laptop online check, local time.
- Act: apps, sites, volume, lock, sleep, screenshot, play/pause/next songs, timers + reminders.
- Notice: reminders fire on their own, 8 AM morning brief, disk-over-90% alert, laptop warns when the homelab drops.
- See: "what's on my screen?" (laptop), photos sent on Telegram.
- Everywhere: laptop voice, Telegram (text, voice, photos, pushes), web page on :9443.
Verified on the VM (staging, real Gemini): reminder set and delivered, fact recalled, server + laptop status, screenshot read,
morning brief. Unit checks: legion/test_actions.py, legion/recorder.py, vm/test_skills.py, vm/test_scheduler.py, vm/test_phase2.py.

## How "hands" will work (decided once, used by every phase)
The brain lives on the VM, but most actions happen on the laptop. So a tool on the VM doesn't do the action:
it returns an **action** (e.g. `{"do": "open_app", "name": "vscode"}`) with the reply, and the laptop runs it.
- Safe actions (open app, volume, timer) run straight away.
- Risky ones (shutdown, delete, send, restart a service) ask "Confirm, sir?" first (FEATURES.md #12).
- From the phone, an action that needs the laptop says "your PC is asleep, shall I wake it?" (Phase 2).

---

## Phase 1: reach 5 (Talk, Know, Act, Everywhere)

**1.1 Finish phone access** (your steps, ~5 min): add `TELEGRAM_ALLOWED_IDS`, restart, test text + voice note;
optional phone page on port 9443 (docs/PHASE2.md, steps 6-8).
Test: a text and a voice note both get correct answers; a stranger's message gets no reply.
Status 2026-11-07: DONE (text + voice note verified live; allow-list on; web page on :9443).

**1.2 Talk: no cut-offs, faster first words**
- Smart Turn v3 (the queued item): he waits until you've finished, not a fixed 1.3 s of silence.
- Speak sentence by sentence: start saying sentence 1 while sentence 2 is still being turned into audio.
Test: 10-turn chat with natural pauses: 0 cut-offs; on simple questions he starts talking within 1.5 s (median).

**1.3 Act: the basic hands** (FEATURES.md #6, #7, #10, #12)
- Timers and reminders ("remind me in 20 minutes to stretch"); they fire by voice, and by Telegram if the laptop is off.
- Open apps and websites; volume, mute, lock, sleep, screenshot.
- Confirm step for anything risky.
Test: 15 spoken commands, at least 13 done right first try; 0 risky actions without confirmation.
Status 2026-11-07: apps, sites, volume, mute, lock, sleep (asks first), screenshot, play song (YouTube) + pause/next, mic mute BUILT (legion/actions.py,
`laptop` tool in vm/tools.py, laptop turns only). Real Gemini test passed on the VM. Not yet: timers/reminders, spoken 15-command test.

**1.4 Know: remembers you and your setup**
- "Remember that ..." facts kept forever (memory.py already has SQLite); "what do you know about me?".
- Homelab status: "is the server up?", disk, the jarvis-brain service (read-only, over SSH).
- Time and date questions answered locally (no Gemini call).
Test: 20-question quiz (live facts, your facts, homelab), at least 17 right.

**1.5 Small starts on Notice and See (to 3)**
- Notice: reminders from 1.3 arriving on their own already counts; add one alert, "homelab went offline", to Telegram.
- See: "what's on my screen?" sends a screenshot to Gemini vision.
Test: unplug or stop the server, get a Telegram alert within 2 minutes; screen question answered correctly 4/5 times.

**Exit Phase 1** when every test above passes.

---

## Phase 2: reach 6 in everything

**Build status (2026-11-08): coded, tested on the VM with real Gemini, installed (awaiting brain restart + user tests).**
- Talk: fast lane (laptop qwen3.5:4b, ~1 s, no Gemini) for timers/reminders/volume/open/play; exact phrases instant;
  two requests in one sentence go to Gemini; barge-in needs loud AND speech (Silero); sentence-by-sentence voice.
  Not met yet: first word within 1 s (voice generation alone is ~0.8 s over the internet).
- Know: file finder (Desktop/Documents/Downloads), calendar (iCal link) + Gmail (IMAP), read-only, ONLY once the
  user adds CAL_ICS_URL / GMAIL_USER / GMAIL_APP_PASSWORD to .env. News via web search.
- Act: phone -> laptop actions (laptop_remote, queued via /notify), wake laptop from anywhere (Wake-on-LAN from the VM),
  multi-step requests via Gemini. Not built: homelab service restarts (needs a sudoers rule).
- Notice: rain alert (Open-Meteo, max once per 3 h), calendar heads-up 10 min before, quiet hours 23-07 (alerts silent).
- See: screen answers quote the error and give a fix; Telegram photos.
- Everywhere: alerts go to the laptop if you used it (keyboard or voice) in the last 10 min, else Telegram.

**2.1 Talk (6)**: replies stream from Gemini word by word into speech; barge-in uses voice detection
(Silero, already installed) instead of loudness, so a cough doesn't stop him but "stop" does; one turn can
hold two requests ("weather, then set a timer").
Test: median first word within 1 s; 10 barge-in tries, 9 work, 0 false stops from his own voice.

**2.2 Know (6)**: finds files ("the resume I edited last week"); reads your calendar and Gmail (read-only);
news headlines.
Test: 20-question quiz including files and calendar, at least 18 right.

**2.3 Act (6)**: multi-step jobs ("open VS Code in the jarvis folder and start the server"); music play/pause/skip;
wake or sleep the PC from the phone through DevStation; homelab actions such as restarting a service
(needs a sudoers rule you add, scoped to that one service).
Test: 10 multi-step commands, 8 done fully; "wake my PC" from Telegram works with the laptop asleep.

**2.4 Notice (6)**: a watcher on the VM that checks things on a schedule and tells you:
morning brief at a set time (weather, reminders, server health, headlines); rain alert; a price you choose to
watch (e.g. gold under a number). Quiet hours so he never wakes you.
Test: a week of morning briefs arrive on time; each alert type fires once on a staged trigger; nothing during quiet hours.

**2.5 See (6)**: send a photo on Telegram, "what is this?"; "read the error on my screen" gives the error and a fix.
Test: 10 photos/screens, 8 described correctly.

**2.6 Everywhere (6)**: alerts go to wherever you are (laptop voice if you're at the PC, Telegram if not);
the orb shows what he's doing (listening, thinking, searching).
Test: the same reminder lands on the laptop when you're active and on the phone when you've been idle 10 min.

**Exit Phase 2** when every test above passes.

---

## Phase 3: reach 7 in everything

**3.1 Talk (7)**: evaluate Gemini Live (speech in, speech out, no separate STT/TTS) for sub-second replies;
keep the current pipeline if Live costs money or loses the Ryan voice. Understands Hindi/Telugu mixed in.
Test: a 5-minute chat that a friend watching would call "natural"; median first word under 0.8 s.

**3.2 Know (7)**: knows your projects: search over the projects folder and notes; recalls past chats by topic
("what did we decide about the gold rate last week?"); says where an answer came from when asked.
Test: 10 questions about your own projects, 8 right with the right source.

**3.3 Act (7)**: routines ("I'm going to bed": sleep the PC, set an alarm, lights off); drafts emails and calendar
events, always confirming before sending; smart plugs or lights (needs hardware, see risks).
Test: 3 routines run end to end; 5 drafts, 0 sent without a yes.

**3.4 Notice (7)**: acts on what he notices, with permission: "Sir, the homelab is offline. Shall I restart it?"
then does it; heads-up 10 minutes before calendar events; learns which alerts you ignore and stops sending them.
Test: a staged outage gets noticed, offered and fixed after your yes; ignored alert types drop off within a week.

**3.5 See (7)**: notices you sit down at the PC (webcam, on the laptop only) and offers the brief; watches a
screen region you point at ("tell me when this download finishes").
Test: greets you 4/5 times when you sit down, 0 false greetings in an empty room; the download watch fires.

**3.6 Everywhere (7)**: a second room: an old phone or a cheap ESP32 mic + speaker as an always-on Jarvis
satellite; start a chat on the laptop, continue it on the phone (memory is already shared).
Test: "Hey Jarvis" works from the second room; a chat started on the laptop continues correctly on Telegram.

**Exit Phase 3** = 7/10 everywhere.

---

## Risks and limits to plan around
- **Free Gemini quota.** Watchers, vision and streaming all add calls. Watch the 429s; use cheap checks first
  (ping, price API) and call Gemini only when something changed.
- **Laptop must be on** for laptop actions; the phone path works around it with DevStation wake (sleep only,
  not from shutdown).
- **sudo on the homelab** is yours; any homelab action needs a narrow sudoers rule you add once.
- **Hardware**: smart plugs/lights (3.3) and a room satellite (3.6) need a purchase. Pick the cheapest option when we get there.
- **Privacy**: webcam frames stay on the laptop (local presence detection); screenshots and photos go to Gemini
  only when you ask a question about them.
- **Never** put the brain on the public Funnel ports (443/8443/10000); see docs/PHASE2.md.

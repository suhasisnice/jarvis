# Phase 2 — talk to Jarvis from your phone

Built 2026-11-02 (overnight). Scope from FEATURES.md v2 "Phone access" + the Phase 2 plan:
**Telegram (text + voice notes) and a phone voice web page**, both using the same VM brain,
memory, persona and tools as the laptop.

Ticked as each item was done and tested. Nothing is ticked without a test.

## Checklist

### 0. Queued (asked to be put on the list, not part of Phase 2)
- [ ] **"Talk after he's done"**: Smart Turn v3 end-of-turn model on the laptop, so Jarvis replies when
      you have actually finished instead of after a fixed 1.3 s of silence. Status: QUEUED, not started.
      Notes: local ONNX model, runs on top of the existing VAD (docs/VOICE_AGENT_LEARNINGS.md, B1).

### 1. Research (community advice = the decision-maker)
- [x] Searched repos, docs and community threads; decisions below, each with its source
- [x] Proved PyAV (pip, no ffmpeg/sudo) converts the Ryan voice to Telegram OGG/Opus
- [x] Proved Gemini transcribes Telegram-style OGG/Opus and 16 kHz WAV word-perfect (~1.7 s each)

### 2. Code (VM side)
- [x] `vm/voice.py`: transcribe audio with Gemini; Ryan voice as MP3; MP3 -> OGG/Opus (both packages optional)
- [x] `vm/brain.py`: one turn at a time (lock), so phone + laptop can't interleave memory
- [x] `vm/telegram_bot.py`: long polling, allow-list, setup mode, text + voice, typing, 4096 split, token redaction, retry/backoff
      (first draft by fcode / Mistral Codestral; review fixed 3 real bugs, see "Helper notes")
- [x] `vm/server.py`: starts the bot thread; `GET /voice` page; `POST /voice/turn` (10 MB cap)
- [x] `vm/voice.html`: hold-to-talk orb, records WAV in the browser, plays the reply, typing box fallback, iPhone audio unlock

### 3. Tests
- [x] `vm/test_phase2.py`: 19 offline tests (fake Telegram, stubbed brain, real HTTP server on a random port) pass on this PC
- [x] Same 19 tests pass on the VM's Python 3.14.4
- [x] Real end-to-end on the VM (staged copy, private port, separate memory file): phone WAV -> heard
      "Good evening, sir. All systems are online." exactly -> brain replied, 2.7 s total; Telegram OGG transcribed in 1.4 s;
      without edge-tts it falls back to text-only cleanly
- [x] Real `speech()` on this PC: Ryan voice -> 4.1 s OGG/Opus voice bubble, 28 KB (under 1 MB, so Telegram shows the waveform)
- [x] Live Jarvis untouched: VM brain still the 19:26 process, /ping ok; laptop app running; laptop code not changed in Phase 2
- [x] Live Telegram round trip (2026-11-07): locked to 1 user; text answered; voice note -> "I heard: ...", text reply, voice bubble. Phone page live on :9443.

### 4. Hand-off
- [x] Files staged on the VM in `~/jarvis-phase2/` (inert until you copy them in; staging memory file deleted)
- [x] Morning steps below are complete and in order
- [x] Found and avoided a public-exposure trap (see "Port 9443, not 443")
- [x] PC put to sleep (last step, same Suspend method as DevStation so Wake-on-LAN still works)

## Morning steps (about 10 minutes)

**1. Create the bot (on your phone).** In Telegram open **@BotFather**, send `/newbot`, name it `Jarvis`,
pick a username ending in `bot`. Copy the token it gives you. This must be a NEW bot: the DevStation bot
is already being read by the ESP32, and two readers on one bot break both.

**2. In your homelab SSH window, install the voice packages (no sudo):**
```
~/jarvis/venv/bin/pip install edge-tts av
```

**3. Back up, copy Phase 2 in, and run the tests:**
```
cd ~/jarvis && mkdir -p backup-pre-phase2 && cp brain.py server.py backup-pre-phase2/
cp ~/jarvis-phase2/{brain.py,server.py,voice.py,telegram_bot.py,voice.html,test_phase2.py} ~/jarvis/
./venv/bin/python3 test_phase2.py
```
Expect `phase2 tests passed` (the WARNING/ERROR lines above it are from deliberate failure tests).

**4. Add the token:** `nano ~/jarvis/.env`, add one line, save (Ctrl+O, Enter, Ctrl+X):
```
TELEGRAM_BOT_TOKEN=paste-the-token-here
```

**5. Restart:** `sudo systemctl restart jarvis-brain`

**6. Lock it to you.** Message your new bot anything. It answers *"Setup mode. Your Telegram ID is N…"* and nothing else.
Add that number to `.env` and restart again:
```
nano ~/jarvis/.env        # add: TELEGRAM_ALLOWED_IDS=N
sudo systemctl restart jarvis-brain
```

**7. Test it:** text "what's 2 plus 2", then send a voice note "what's the gold rate today".
You should get "I heard: …", the answer as text, then the answer as a voice bubble in Ryan's voice.

**8. Phone voice page (optional; your phone must have Tailscale on):**
```
sudo tailscale serve --bg --https=9443 http://127.0.0.1:8000
```
Then open **https://jarvis.tail60b568.ts.net:9443/voice** on your phone. Hold the orb, talk, release.

**If anything breaks, roll back:**
```
cp ~/jarvis/backup-pre-phase2/*.py ~/jarvis/ && sudo systemctl restart jarvis-brain
```
**See what it's doing:** `journalctl -u jarvis-brain -n 40 --no-pager`

## Port 9443, not 443 (important)
Tailscale **Funnel is on** for this VM: `https://jarvis.tail60b568.ts.net/` (old team-board app, port 8080) and
`/portfolio` (port 8099) are reachable from the **public internet**. Serving Jarvis on 443 would have replaced
that route and put the brain on the public internet with no login. Funnel can only publish ports 443, 8443 and
10000, so **9443 is tailnet-only by design**: only your own Tailscale devices can open the phone page.

## Decisions (from community advice)
| Decision | Source |
|---|---|
| Long polling, not webhooks: no open ports on the homelab | Telegram Bot FAQ; OpenClaw Telegram docs |
| Only ONE program polls the bot, or Telegram returns 409 Conflict. The bot runs as a thread inside the existing `jarvis-brain` service, so there is never a second poller and no new service to install | ZeroClaw/CoClaw 409 troubleshooting |
| Clear any webhook at start (`deleteWebhook`, retried until it works), a common cause of stuck 409s | CoClaw 409 guide |
| Allow-list of numeric Telegram user IDs; strangers get no reply at all. If the list is empty, "setup mode" only tells the sender their ID | OpenClaw security docs ("open" bots can be controlled by anyone) |
| Voice notes go straight to Gemini as `audio/ogg` (no Whisper on the VM). Transcribe first, then the normal brain, so phone turns share the laptop's memory, persona and tools | Google's "voice-enabled Telegram bot with Gemini" tutorial |
| Text reply first, then voice; a voice failure never blocks the text | Same tutorial |
| Voice in -> voice out; text in -> text out | dylanninin/chatgpt-telegram-bot voice-reply option; Google tutorial |
| Voice replies as OGG/Opus via `sendVoice` (a real voice bubble); MP3 via `sendAudio` is the fallback | Telegram Bot API (`sendVoice` needs OGG/Opus) |
| Same voice as the laptop (edge-tts `en-GB-RyanNeural`) instead of Gemini TTS: consistent, free, no extra quota | Our Phase 1 choice |
| Bot token redacted from every error before logging (requests puts URLs with the token in its errors) | Standard secret hygiene; found in review |
| Phone web page needs HTTPS for the mic; `tailscale serve` (valid cert, tailnet-only on 9443) | MDN getUserMedia; Tailscale Serve docs |
| The web page records WAV in the browser: Gemini does not list WebM, and iPhone and Android record different formats | Gemini audio docs (WAV/MP3/AAC/OGG/FLAC) |

## Known limits / later
- **No login on port 8000.** `/ask` and `/voice` answer anyone on your home Wi-Fi or tailnet (true of `/ask` since Phase 1). Fine at home; add a token or bind to the tailnet before inviting others onto the network.
- **Public Funnel already on** for the team-board app and portfolio (not changed; check it's intended).
- **The phone page only works on devices signed into your Tailscale** (by design).
- **Each voice note costs two Gemini calls** (hear + answer), on the same free quota as the laptop.
- **One conversation at a time.** Laptop and phone share one memory; a second request waits for the first.
- **No group chats, photos or files** on Telegram yet (polite "text and voice only" reply).
- Smart Turn (item 0) is queued.

## Helper notes
- fcode (`feature`, Mistral Codestral, 1 attempt, 26 s) drafted `telegram_bot.py` against a written contract plus 13 tests.
  Review found 3 bugs the tests missed: Telegram's long-poll `timeout` was swallowed as the HTTP timeout (a tight polling loop);
  a failed voice download leaked the bot token into logs; `deleteWebhook` sat outside the retry loop (the bot dies if the network
  is down at boot). Fixed inline, plus 4 regression tests and 2 server/voice tests. Logged in notes_test/limits-log.md.

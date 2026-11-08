# Jarvis feature list

A voice assistant for this Windows PC, in the style of Tony Stark's Jarvis: calm, British, calls you "sir", and gets things done.
Features are tiered. We build v1 fully before starting v2.

## v1: core (it talks and does basic things)
| # | Feature | Example | Default tech |
|---|---------|---------|--------------|
| 1 | Wake word | "Hey Jarvis" wakes it; otherwise it ignores you | openWakeWord (free, has a ready "hey jarvis" model) |
| 2 | Hears you | Speech turned into text | faster-whisper (local, free) |
| 3 | Thinks | Understands any request, chats naturally | Ollama on this PC (free); Gemini as backup |
| 4 | Speaks | Replies in a British voice | Piper TTS (local, free, neural voice) |
| 5 | Personality | Dry wit, short answers, "sir" | System prompt |
| 6 | Time, date, timers, reminders | "Remind me in 20 minutes to stretch" | Python stdlib |
| 7 | Open apps and sites | "Open VS Code", "open YouTube" | Python stdlib |
| 8 | Web search and quick answers | "Who won the match yesterday?" | Search API, summarised by the model |
| 9 | Weather | "Do I need an umbrella?" | Open-Meteo (free, no key) |
| 10 | PC control | Volume, lock, sleep, screenshot | Windows commands |
| 11 | Conversation memory | Remembers what was said earlier in this session | In-memory list |
| 12 | Safety | Asks "Confirm, sir?" before shutdown, delete or sending anything | Confirm step |

## v2: personal (it knows you and your setup)
- Long-term memory: your name, preferences and facts you tell it, kept across restarts (SQLite)
- Morning briefing: time, weather, reminders, homelab status, news headlines
- Homelab: "Is the server up?", service status, disk space (SSH to .108)
- DevStation: wake or sleep the PC through the existing ESP32 + Telegram setup
- Phone access: talk to Jarvis from Telegram when you're away
- Music: play, pause, skip (Spotify or YouTube)
- Screen awareness: "What's on my screen?" (screenshot + vision model)
- File finder: "Find the resume I edited last week"

## v3: Stark-level (the cool parts)
- HUD window: sci-fi overlay with a live voice waveform and status rings
- Email and calendar: read and draft (always confirms before sending)
- Proactive alerts: "Sir, the homelab went offline 3 minutes ago"
- Smart home: lights and plugs through the ESP32 or smart plugs
- Hindi/Telugu understanding
- Interrupt mid-sentence ("Jarvis, stop")

## Decisions (locked 2026-11-01)
1. **Activation:** wake word — "Hey Jarvis" always listening
2. **Brain:** Gemini first, Ollama fallback
3. **Voice:** British male — Piper TTS `en_GB-alan-medium`

# What the community actually does — tools, smartness, snappiness

Research done 2026-11-01 from Home Assistant forums, r/LocalLLaMA, r/homeassistant,
and GitHub Jarvis repos. This is the "learn from their trial and error before building" pass.

## The one pattern everyone converges on

**Tool/function calling driven by the LLM, not a hand-written command parser.**
You hand the model a small set of typed functions (get_weather, set_timer, web_search…),
it decides which to call, you run it, feed the result back, it speaks the answer.
Nobody who got something good is doing `if "weather" in text:` branching — that path
dies the moment someone phrases things differently.

## Trial-and-error lessons (the expensive ones they already paid for)

1. **Model choice makes or breaks tool calling.** Small default Ollama models
   (heavily Q4-quantized) call tools unreliably. People who struggled with Qwen3-4B
   fixed it by moving to a tool-capable model at decent quant: GPT-OSS 20B, Gemma 26B,
   GLM-4 Flash. We already use **Gemini first** — Gemini does function-calling well,
   so we're ahead here. Ollama is only our fallback.

2. **Expose FEW tools, with tight descriptions.** Entity/tool descriptions + system
   prompt must fit the context window. Too many tools → accuracy tanks and latency
   rises. Group things (one "control_lights" not one tool per bulb). Start with 3-4.

3. **Force a tool call for fact-shaped questions.** Left alone, the model answers
   "I don't have that" instead of calling web_search. The prompt must say: for
   weather / current events / "look up X", you MUST call the tool.

4. **Never let the model invent tool data.** HA users hit the LLM *fabricating*
   weather when the real intent fell through. Rule: if the tool fails or returns
   nothing, say so — don't guess. (Our persona already says this.)

5. **Strip markdown/emoji before TTS.** The voice reads `*` and `😀` aloud. Clean
   the reply text before it goes to edge-tts.

6. **Snappy = streaming + GPU + caching, not a faster model.**
   - Stream tokens and speak sentence-by-sentence (don't wait for the whole reply).
   - Prompt caching was *the* biggest speed win people reported.
   - STT accuracy: bigger Whisper on GPU, or Parakeet-V3 (Wyoming) — fast AND accurate.
     This is exactly our planned RealtimeSTT-on-the-4060 fix.

7. **Start narrow, earn trust.** Repeated theme across Reddit/Quora: do-it-all
   assistants become "more work than help" and get abandoned. The ones people keep
   using do a few things reliably. Add a tool only once the last one is trustworthy.

## What tools people actually hand it (in the order they add them)

| Tier | Tools | Why first / notes |
|------|-------|-------------------|
| 1 — local, instant, safe | get_time/date, set_timer, set_reminder, remember/recall a note | no network, no keys, impossible to get "wrong", immediate payoff |
| 2 — read-only web | get_weather, web_search | fixes "it's 2024 / Biden" and weather; needs one API (or a scrape); read-only = low risk |
| 3 — your life | calendar read/add, to-do list, play music | useful but needs accounts/auth; add after tiers 1-2 are solid |
| 4 — control (gated) | smart-home, PC control (open app, type, volume) | powerful, but a wrong call *does* something — confirm/guard these |

## Repos worth copying from
- `jekalmin/extended_openai_conversation` — the reference for clean HA function-calling.
- `llm-guy/jarvis` — minimal local Jarvis: Qwen via Ollama + LangChain tools
  (ships basically one tool, `get_time`; good tiny template for the loop).
- `JoshuaKasa/JARVIS`, `Gichbuoy/AI_Assistant`, `Rkmv6374/Jarvis` — reference designs.

## Recommendation for our Jarvis (concrete)
We already have the hard part: a brain that talks to Gemini with a persona + memory.
The missing piece is the **tool loop**. Add it in the VM `brain.py` using Gemini's
native function-calling, and start with **Tier 1 + web_search + weather**:
- `get_datetime` (kills the 2024 problem for good, even offline)
- `web_search` (current events, "who is president", general lookup)
- `get_weather` (the thing you actually asked for)
- `set_timer` / `remember` (instant, local, satisfying)

Everything else (calendar, music, home/PC control) waits until these are trustworthy.

# What other voice-assistant builders learned, applied to Jarvis

Research 2026-11-02. Draft written by a local model (gpt-oss:20b) from a fact sheet, then checked and corrected by hand.

**Summary**
Jarvis already does several things the community recommends (VAD against hallucinations, cached stock phrases, few tools, short spoken answers).
The biggest remaining gaps are how he decides you've finished talking, speaking before the whole answer is ready, and barge-in on speakers (needs echo cancellation).
Builders also agree the thing that makes people keep using an assistant is reliable actions (timers, notes), not a better voice.

## Where Jarvis stands

| Stage | Jarvis today | What others do |
|-------|--------------|----------------|
| Wake word | openWakeWord "hey_jarvis", threshold 0.6 | Home Assistant users report false activations are common; one found "hey jarvis" only triggered within about 1 m of the device |
| End of speech | loudness threshold + 1.3 s of silence | Pipecat Smart Turn: a small model judges from tone and wording whether a pause means "done", so the silence wait can be ~0.2 s |
| Speech-to-text | faster-whisper "small" on GPU, VAD filter on, default beam | Vocalis: "base.en" with beam size 2, about 0.43 s |
| Brain | Gemini flash-lite, not streamed, last 20 messages, 2 tools | GLaDOS streams the model's answer and speaks it sentence by sentence |
| Actions | weather, web search only | Builders say the action layer (doing things) is what changes the experience |
| Voice | edge-tts Ryan (online), ~1 s to synthesize a sentence, whole reply before first word | Kokoro TTS about 0.16 s per response, runs offline |
| Barge-in | mic loudness check, no echo cancellation | Real speaker barge-in needs WebRTC-grade echo cancellation; headphones are the simple fix |
| Waiting | narrates tool use ("Checking the weather in X, sir.") | GLaDOS aims for replies under 600 ms; a local-pipeline guide says under 1.5 s tests best with users |
| Measured latency | ~4 s simple turn, ~14 s weather/search | LiveKit/HF: log every stage's timing before tuning anything |

## What others learned

- **GLaDOS** (local voice assistant) targets replies under 600 ms. It streams the model's answer, splits it into sentences and synthesizes later sentences while earlier ones play. Its README warns it can loop when it hears its own voice without proper audio hardware, and barge-in can be switched off.
- **Vocalis** (r/LocalLLaMA) uses faster-whisper base.en with beam size 2 (~0.43 s) and Kokoro TTS (~0.16 s). The best comment in the thread: transcribe live and start an answer on every ~500 ms pause. That saves more time than speeding up TTS, because the real waste is the silence wait.
- **Pipecat Smart Turn** runs on top of VAD. When VAD hears a pause, the model looks at the last 8 seconds of audio (tone, wording) and decides "finished" or "still thinking". v3 runs locally on CPU via ONNX. It costs some compute. AssemblyAI's point: plain silence detection either waits too long or cuts off thinking pauses, and that's exactly the trade-off Jarvis has.
- **LiveKit Agents + Hugging Face latency playbook:** the end-of-speech wait is the first and most configurable part of perceived latency. Pre-emptive generation (starting the answer before the turn is confirmed) gave one developer only ~200 ms. Measure first.
- **Echo cancellation:** speaker barge-in needs proper echo cancellation. WebRTC's AEC3 has no ready pip package on Windows. Browsers have it built in (`echoCancellation: true`), but only for audio the browser itself plays, it needs ~3-5 s to adapt, and talking over each other is its hardest case.
- **Gemini Live API:** one streaming connection for audio in and out, with built-in turn detection and barge-in. One forum report says latency creeps up over long sessions until restarted. Free-tier limits couldn't be confirmed.
- **Whisper hallucinations:** phantom "Thank you for watching" comes from silence reaching the model; filter silence with VAD first (Jarvis does). `condition_on_previous_text=False` and `no_speech_threshold` are further knobs. Hotwords can make hallucinations worse.
- **Jarvis builders on Reddit:** the interesting part is no longer the wake word or the voice but the action layer. One Pi builder saw 0.5-3 s and argued a short wait after the wake word is fine.

## What to change

### A. Quick wins (minutes each)
1. **Speech-to-text:** try the English-only `small.en` with `beam_size=2` and `condition_on_previous_text=False`. *Gain:* faster transcription, possibly fewer odd outputs. Measure on your voice.
2. **Log per-stage timings** (silence wait, transcribe, brain, synthesize) to a file every turn. The app's console log never reaches a file today, so tuning is guesswork.
3. **Barge-in:** use headphones, or raise `BARGE_RMS` in `speaker.py`. True speaker barge-in needs echo cancellation (C1).

### B. Medium (an evening each)
1. **Smart Turn v3** on top of the VAD. *Gain:* fixes "a tiny pause and I'm cooked" and lets the silence wait drop well below 1.3 s. This is the fix for your current biggest complaint.
2. **Sentence streaming** like GLaDOS. *Gain:* biggest for multi-sentence answers; smaller now that answers are one sentence.
3. **Local TTS (Kokoro)**, about 0.16 s vs edge-tts ~1 s, works offline. *Trade-off:* compare voices by ear; Ryan may sound more natural.
4. **Action tools:** timers, reminders, remember-a-note. *Gain:* this is what builders say keeps an assistant in daily use.

### C. Big bets (test for an hour before committing)
1. **Real barge-in on speakers:** move mic capture and playback into the Edge orb window (already open) to get the browser's echo cancellation, or find a WebRTC AEC library for Windows. Large refactor.
2. **Gemini Live API:** replaces speech-to-text + brain + voice with one streaming connection. *Risks:* free-tier limits unknown, your key already had model-availability problems, you lose the Ryan voice, and long sessions may slow down.

### D. What Jarvis already does right
- Silero VAD filter stops "Thank you." hallucinations.
- Narrates tool use instead of sitting silent.
- Cached stock phrases play instantly.
- Few tools with tight descriptions, short-answer voice persona.
- Gemini first with a local Ollama fallback.

## Sources
- https://github.com/dnhkng/GlaDOS
- https://www.reddit.com/r/LocalLLaMA/comments/1jy1x1b/vocalis_local_conversational_ai_assistant_speech/
- https://docs.pipecat.ai/server/utilities/smart-turn/smart-turn-overview
- https://www.assemblyai.com/blog/voice-agent-turn-detection
- https://huggingface.co/blog/dvalle08/voice-agent-latency-playbook
- https://docs.livekit.io/agents/build/audio
- https://www.kunalganglani.com/blog/local-ai-voice-assistant-whisper-piper-ollama.md
- https://github.com/ssethia2/aria/pull/6
- https://github.com/codejq/webrtc-aec
- https://dev.to/orca_forge/browser-voice-interaction-ai-pitfall-guide-2026-16-common-traps-with-aec-getusermedia-and-40hd
- https://sdk.airefinery.accenture.com/tutorial/realtime/tutorial_realtime_bargein/
- https://www.weblineglobal.com/blog/asterisk-audiosocket-barge-in-fix-ai-voicebots/
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api
- https://discuss.ai.google.dev/t/gemini-live-api-native-audio-response-latency-gradually-increases-during-long-sessions/115508
- https://localaimaster.com/blog/whisper-hallucination-fix
- https://github.com/SYSTRAN/faster-whisper/pull/731
- https://community.home-assistant.io/t/home-assistant-voice-pe-device-together-with-openwakeword/842680
- https://open-clawai-com.pages.dev/en/blog/voice-assistant-build-jarvis

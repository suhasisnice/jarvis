Over the past few weeks I built my own MCU-style Jarvis voice assistant. I say "Hey Jarvis" on my laptop, a British voice answers, and I can cut him off mid-sentence. An open-source turn-detection model (Pipecat's Smart Turn) listens to how I speak, so when I pause mid-thought he waits instead of talking over me.

Everyday commands (timers, reminders, volume, opening apps, playing a song on YouTube) run on a small local model on my laptop in about a second, with no cloud call. Harder questions like the weather, live search or today's gold rate go to Gemini. The brain runs 24/7 on a Proxmox VM on my home server, reachable privately over Tailscale, and speech-to-text runs on my laptop GPU with faster-whisper.

He also reaches me on my phone through a Telegram bot (text, voice notes, photos) and nudges me first: reminders, a morning brief, rain warnings. He knows if I'm at the laptop: if I am, he says it out loud; if I'm not, it goes to my phone. He can also look at my screen, and find a file I edited ("find my resume").

It's a personal project, not a product, and questions that need Gemini still take a few seconds. The biggest lesson: the AI wasn't the hardest part. The feel was: latency, interruptions, and not talking over me. 🎙️

If you've built a voice agent, what helped you cut latency the most?

#AI #VoiceAssistant #Python #HomeLab #BuildInPublic

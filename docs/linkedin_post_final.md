Over the last few weeks I built my own MCU-style Jarvis voice assistant. I say "Hey Jarvis" on my laptop, a British voice answers, and I can cut him off mid-sentence. An open-source turn-detection model (Pipecat's Smart Turn) listens to my speech patterns, so when I pause mid-thought he waits rather than talking over me.

Everyday commands (timers, reminders, volume, opening apps, playing a song on YouTube) run on a small local model on my laptop in about a second, without a cloud call. Harder questions like the weather, live search or today's gold rate go to Gemini. I run the brain 24/7 on a Proxmox VM on my home server, accessible privately via Tailscale. Speech-to-text runs on my laptop GPU with faster-whisper.

He also reaches me on my phone through a Telegram bot (text, voice notes, photos), and he pings me first: reminders, a morning brief, rain warnings. If I'm at the laptop he says it out loud, but if I'm not, it goes to my phone. He can also look at my screen and find a file I edited ("find my resume").

It's a personal project, not a product, and questions that require Gemini still take a few seconds. The biggest lesson learned: the AI was not the hardest part. The feel was: latency, interruptions, and not talking over me. 🎙️

If you've built a voice agent, what helped you cut latency the most?

#AI #VoiceAssistant #Python #HomeLab #BuildInPublic

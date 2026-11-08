"""Check for actions.py: plan() must turn brain actions into the right Windows steps. Run: python test_actions.py"""
import actions

DOWN, UP, MUTE, WIN, PRTSC = 0xAE, 0xAF, 0xAD, 0x5B, 0x2C
p = actions.plan

assert p({"do": "open_app", "target": "VS Code"}) == ("start", "code")
assert p({"do": "open_app", "target": "chrome"}) == ("start", "chrome")
assert p({"do": "open_app", "target": "notepad"}) == ("start", "notepad")
assert p({"do": "open_app", "target": "obs"}) == ("start", "obs")          # unknown plain names pass through
assert p({"do": "open_app", "target": "claude"}) == ("start", "claude")
assert p({"do": "open_website", "target": "youtube.com"}) == ("url", "https://youtube.com")
assert p({"do": "open_website", "target": "https://x.com/a?b=1&c=2"}) == ("url", "https://x.com/a?b=1&c=2")
assert p({"do": "volume", "target": "50"}) == ("keys", [DOWN] * 50 + [UP] * 25)   # each key = 2%
assert p({"do": "volume", "target": "150"}) == ("keys", [DOWN] * 50 + [UP] * 50)  # clamped to 100
assert p({"do": "volume", "target": "0"}) == ("keys", [DOWN] * 50)
assert p({"do": "mute"}) == ("keys", [MUTE])
assert p({"do": "screenshot"}) == ("hotkey", [WIN, PRTSC])   # Windows saves it to Pictures\Screenshots
assert p({"do": "play", "target": "Loser by Tame Impala"}) == ("play", "Loser by Tame Impala")
assert p({"do": "pause"}) == ("keys", [0xB3])          # media play/pause key: works on YouTube too
assert p({"do": "next"}) == ("keys", [0xB0])
# first_video(): pull the first video out of a YouTube results page (no API key needed)
page = 'x "videoId":"dQw4w9WgXcQ" y "videoId":"AAAAAAAAAAA"'
assert actions.first_video(page) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
assert actions.first_video("no results here") is None
assert p({"do": "lock"}) == ("lock", None)
assert p({"do": "sleep"}) == ("sleep", None)
for bad in ({"do": "volume", "target": "loud"}, {"do": "format_disk"}, {"do": "open_app", "target": ""}, {},
            {"do": "open_app", "target": "notepad|calc"}, {"do": "open_app", "target": "a^&calc"}, {"do": "play", "target": " "}):
    try:
        p(bad)
        raise AssertionError(f"should have refused {bad}")
    except ValueError:
        pass
# run() in dry mode plans but executes nothing, and never raises: it returns a short sentence
assert "code" in actions.run({"do": "open_app", "target": "vscode"}, dry=True)
assert "couldn't" in actions.run({"do": "format_disk"}, dry=True).lower()
print("actions tests passed")

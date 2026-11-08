"""Check for actions.find_files / the "find" action. Run: python test_find.py"""
import os, tempfile, time
import actions

root = tempfile.mkdtemp()
def touch(rel, days_ago):
    p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close(); t = time.time() - days_ago * 86400; os.utime(p, (t, t)); return os.path.normpath(p)
old = touch("Docs/Resume_v2.pdf", 40)
new = touch("Desktop/Resume v3 final.pdf", 2)
touch("Desktop/notes.txt", 1)
touch("Downloads/resume-template.docx", 10)
touch(".venv/lib/resume.py", 0)                       # hidden/tooling folders are skipped
touch("node_modules/x/resume.js", 0)

found = actions.find_files("resume", [root])
assert found[0] == new and old in found and not any(".venv" in f or "node_modules" in f for f in found), found
assert actions.find_files("resume", [root], days=7) == [new]              # edited in the last week only
assert actions.find_files("RESUME final", [root]) == [new]                # every word must match, any case
assert actions.find_files("zebra", [root]) == []
assert len(actions.find_files("resume", [root], limit=2)) == 2

assert actions.plan({"do": "find", "target": "resume|7"}) == ("find", "resume|7")
try:
    actions.plan({"do": "find", "target": " "}); raise AssertionError("empty find must be refused")
except ValueError:
    pass
actions.SEARCH_ROOTS = [root]
r = actions.run({"do": "find", "target": "resume|7"}, dry=True)
assert "Resume v3 final.pdf" in r, r
assert "couldn't find" in actions.run({"do": "find", "target": "zebra"}, dry=True).lower()
print("find tests passed")

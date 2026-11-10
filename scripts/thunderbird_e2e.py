"""Drives the real add-on inside a throwaway Thunderbird, through the real bridge.

Run by scripts/test-thunderbird-e2e.sh. Uses its own port, so a running engine and the
user's own Thunderbird are left alone.
"""
import sys
import time

from dictation.mailbridge import MailBridge

bridge = MailBridge(int(sys.argv[1]))
assert bridge.start(), "port in use"
failures = 0


def check(label, got, want):
    global failures
    same = got == want
    failures += not same
    print(("PASS " if same else "FAIL ") + label + ("" if same else f"\n     got  {got!r}\n     want {want!r}"), flush=True)


for _ in range(120):
    if bridge.connected():
        break
    time.sleep(0.5)
check("the add-on connects to the engine", bridge.connected(), True)
if not bridge.connected():
    sys.exit(1)
windows = 0
for _ in range(60):
    status = bridge.request({"op": "status"})
    windows = status.get("compose_windows", 0)
    if windows:
        break
    time.sleep(0.5)
check("the add-on sees the compose window", windows, 1)
print("     in front, as the add-on sees it:", status.get("ready"), flush=True)
if windows:
    def r(message):  # headless windows are never in front, so ask for any window
        return bridge.request(dict(message, any_window=True))
    time.sleep(2)  # let the editing code load into the new window
    check("without a window in front, requests are refused",
          bridge.request({"op": "context"}).get("why") if not status.get("ready") else "mail not focused",
          "mail not focused")
    check("context", r({"op": "context"}).get("ok"), True)
    before = r({"op": "text"}).get("text", "")
    print("     message text:", repr(before), flush=True)
    check("insert", r({"op": "insert", "text": "Dictated words"}).get("ok"), True)
    check("the words are in the message", "Dictated words" in r({"op": "text"}).get("text", ""), True)
    check("context sees them", r({"op": "context"}).get("before", "").endswith("Dictated words"), True)
    check("scratch", r({"op": "command", "name": "scratch"}).get("ok"), True)
    check("back to how it was", r({"op": "text"}).get("text", ""), before)
    check("select a word in the message", r({"op": "command", "name": "select", "arg": "hello"}).get("ok"), True)
    check("it is selected", r({"op": "text"}).get("selected"), "hello")
    check("unknown request falls through", r({"op": "move", "steps": []}).get("why"), "unknown request")
print("failures:", failures, flush=True)
sys.exit(1 if failures else 0)

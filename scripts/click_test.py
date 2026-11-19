"""Presses the things in scripts/click_window.py by their names, through the desktop's
accessibility service, as "click OK" does. Run by scripts/test-click.sh."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dictation import clicking  # noqa: E402

made = sys.argv[1]
failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def appeared(path, seconds=3.0):
    until = time.monotonic() + seconds
    while time.monotonic() < until and not os.path.exists(path):
        time.sleep(0.1)
    return os.path.exists(path)


def click(name):
    try:
        return clicking.click(name)
    except clicking.CantClick as e:
        return {"ok": False, "why": str(e)}


# The window takes a moment to come up and be the one in front: asked until it is.
until = time.monotonic() + 8
while True:
    reply = click("remember my choice")
    if reply.get("ok") or time.monotonic() > until:
        break
    time.sleep(0.5)
check("a tick box is ticked by its name", (reply, appeared(made + ".tick")), ({"ok": True, "kind": "pressed"}, True))
reply = click("press me")
check("a button is pressed by its name", (reply, appeared(made + ".button")), ({"ok": True, "kind": "pressed"}, True))
reply = click("remember")
check("the start of a name will do", reply.get("ok"), True)
reply = click("not this one")
check("what is greyed is not pressed", (reply.get("ok"), appeared(made + ".greyed", 1.0)), (False, False))
reply = click("nothing is called this")
check("what nothing is called is not found", (reply.get("ok"), reply.get("why")), (False, "can't find that"))
print("failures:", failures)
sys.exit(1 if failures else 0)

#!/usr/bin/env bash
# Runs the Thunderbird add-on's editing code in a headless Firefox, which has the same
# editing engine. Uses its own throwaway profile. Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
profile="$PWD/build/test-firefox-profile"   # snap Firefox can only read files in the home folder
rm -rf "$profile" && mkdir -p "$profile"
python3 - "$PWD/thunderbird" "$profile" <<'PY'
import functools, http.server, subprocess, sys, threading
folder, profile = sys.argv[1], sys.argv[2]
result = []
done = threading.Event()
class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the test page, so its frames share one origin, and takes the results."""
    def log_message(self, *a): pass
    def do_POST(self):
        result.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode())
        self.send_response(204); self.end_headers()
        done.set()
server = http.server.ThreadingHTTPServer(("127.0.0.1", 47699), functools.partial(Handler, directory=folder))
threading.Thread(target=server.serve_forever, daemon=True).start()
browser = subprocess.Popen(["firefox", "--headless", "--no-remote", "--profile", profile,
                            "http://127.0.0.1:47699/test/test.html"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = done.wait(90)
browser.terminate()
try: browser.wait(10)
except subprocess.TimeoutExpired: browser.kill()
if not ok:
    sys.exit("the test page never reported back")
print(result[0])
sys.exit(0 if result[0].strip().endswith("failures: 0") else 1)
PY
rm -rf "$profile"

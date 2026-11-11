#!/usr/bin/env bash
# Loads the add-on into a throwaway Thunderbird profile with a compose window open, and
# talks to it through the engine's bridge on a test port. Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
port=47614
work="$PWD/build/tb-test"            # snap Thunderbird can only read files in the home folder
rm -rf "$work" && mkdir -p "$work/profile/extensions" "$work/addon"
cp thunderbird/manifest.json thunderbird/compose.js "$work/addon/"
# The test copy uses the test port, opens its own compose window, and treats any compose
# window as in front, because a headless window never is.
sed -e "s/127.0.0.1:47613/127.0.0.1:$port/" \
    -e 's/const front = tabs.find((t) => t.focused);/const front = tabs.find((t) => t.focused) || (message.any_window ? tabs[0] : undefined);/' \
    thunderbird/background.js > "$work/addon/background.js"
grep -q any_window "$work/addon/background.js" || { echo "test patch did not apply"; exit 1; }
echo 'setTimeout(() => messenger.compose.beginNew({ body: "<p>hello there</p>", isPlainText: false }), 1500);' >> "$work/addon/background.js"
(cd "$work/addon" && zip -q "../profile/extensions/linux-speaking@jontio.github.io.xpi" *)
cat > "$work/profile/user.js" <<'PREFS'
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.enabledScopes", 15);
user_pref("xpinstall.signatures.required", false);
user_pref("mail.accountmanager.accounts", "account1");
user_pref("mail.accountmanager.defaultaccount", "account1");
user_pref("mail.accountmanager.localfoldersserver", "server1");
user_pref("mail.account.account1.identities", "id1");
user_pref("mail.account.account1.server", "server1");
user_pref("mail.identity.id1.fullName", "Test");
user_pref("mail.identity.id1.useremail", "test@example.invalid");
user_pref("mail.identity.id1.compose_html", true);
user_pref("mail.server.server1.type", "none");
user_pref("mail.server.server1.hostname", "Local Folders");
user_pref("mail.server.server1.userName", "nobody");
user_pref("mail.server.server1.name", "Local Folders");
user_pref("mail.server.server1.directory-rel", "[ProfD]Mail/Local Folders");
user_pref("mail.shell.checkDefaultClient", false);
user_pref("mail.provider.suppress_dialog_on_startup", true);
user_pref("mailnews.start_page.enabled", false);
user_pref("mail.spotlight.firstRunDone", true);
user_pref("app.update.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("mail.rights.version", 1);
PREFS
thunderbird --headless --no-remote --profile "$work/profile" >"$work/tb.log" 2>&1 &
pid=$!
cleanup() { kill $pid 2>/dev/null || true; sleep 2; pkill -f "$work/profile" 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT
python3 scripts/thunderbird_e2e.py "$port" || { echo "--- thunderbird log"; tail -15 "$work/tb.log"; exit 1; }

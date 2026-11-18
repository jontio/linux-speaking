// Links the speech engine to the message being written.
//
// The engine can't call in, so this keeps one request open to it (a long poll). The
// engine answers with the next thing to do; the result goes back with the next poll.
//
// Anything on this computer could listen where the engine listens, or ask what this asks.
// So the two prove themselves to each other with a key that the installer makes for this
// computer and builds into this add-on's file (key.js). Each request carries a number made
// up for it, and the answer is only believed if it is signed over that number; each answer
// brings a number that the next request is signed over. See the engine's mailbridge.py.
"use strict";

const ENGINE = "http://127.0.0.1:47613/poll";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const text = new TextEncoder();
const hex = (bytes) => Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
const madeUp = () => hex(crypto.getRandomValues(new Uint8Array(16)));
let key = null;

// Proof of holding the key, made over the parts of what is being said.
async function prove(...parts) {
  if (!key) {
    key = await crypto.subtle.importKey("raw", text.encode(LINUX_SPEAKING_KEY),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  }
  return hex(await crypto.subtle.sign("HMAC", key, text.encode(parts.join("\n"))));
}

// Whether two proofs are the same, taking as long whether or not they are.
function same(given, wanted) {
  if (typeof given !== "string" || given.length !== wanted.length) return false;
  let differ = 0;
  for (let i = 0; i < wanted.length; i++) differ |= given.charCodeAt(i) ^ wanted.charCodeAt(i);
  return differ === 0;
}

// One exchange with the engine. `turn` is the number its last answer gave, or "" to begin.
// Gives the next turn and what to do, or null if what answered didn't prove it is the engine.
async function ask(turn, replies) {
  const nonce = madeUp();
  const body = { nonce };
  if (turn) {
    body.turn = turn;
    body.payload = JSON.stringify({ replies });
    body.auth = await prove("poll", turn, nonce, body.payload);
  }
  // (Not kept in Thunderbird's cache: every answer would be a file on the disk there.)
  const response = await fetch(ENGINE, { method: "POST", body: JSON.stringify(body), cache: "no-store" });
  const answer = await response.json();
  if (typeof answer.turn !== "string" || typeof answer.payload !== "string" ||
      !same(answer.auth, await prove("next", nonce, answer.turn, answer.payload))) {
    return null;
  }
  return { turn: answer.turn, request: JSON.parse(answer.payload) };
}

// The editing code runs inside each compose window opened from now on.
messenger.composeScripts.register({ js: [{ file: "compose.js" }] });

async function composeTabs() {
  const windows = await messenger.windows.getAll({ populate: true, windowTypes: ["messageCompose"] });
  return windows.flatMap((w) => w.tabs.map((tab) => ({ tab, focused: w.focused })));
}

async function handle(message) {
  const tabs = await composeTabs();
  // Clearing the numbers must work whether or not the message window is in front.
  if (message.op === "command" && message.name === "cancel_choices") {
    for (const { tab } of tabs) {
      try { await messenger.tabs.sendMessage(tab.id, message); } catch (e) { /* closing */ }
    }
    return { ok: true };
  }
  const front = tabs.find((t) => t.focused);
  if (message.op === "status") {
    return { ok: true, ready: Boolean(front), compose_windows: tabs.length };
  }
  if (!front) {
    return { ok: false, why: "mail not focused" };
  }
  try {
    return await messenger.tabs.sendMessage(front.tab.id, message);
  } catch (e) {
    // A compose window that was already open when the add-on was installed.
    return { ok: false, why: "mail not focused", error: String(e) };
  }
}

async function run() {
  if (!LINUX_SPEAKING_KEY) {
    console.error("Linux Speaking: this add-on has no key. Install the file the installer made.");
    return;
  }
  let replies = [];
  let turn = "";
  let said = false; // whether the console has been told that the answers prove nothing
  for (;;) {
    try {
      const answer = await ask(turn, replies);
      replies = [];
      if (!answer) {
        turn = ""; // not the engine, or an engine with another key: nothing it said is done
        if (!said) {
          said = true; // once, not every few seconds
          console.error("Linux Speaking: what answers on the engine's port doesn't prove it holds " +
            "this computer's key. If the engine is running, this add-on was made for another key: " +
            "install the file the installer made, linux-speaking-thunderbird.xpi, again.");
        }
        await sleep(3000);
        continue;
      }
      said = false;
      turn = answer.turn;
      const request = answer.request;
      if (request.id) {
        let reply;
        try {
          reply = await handle(request.message);
        } catch (e) {
          reply = { ok: false, why: "error", error: String(e) };
        }
        replies.push({ id: request.id, reply });
      }
    } catch (e) {
      replies = [];
      turn = "";
      await sleep(3000); // the engine isn't running; try again shortly
    }
  }
}

// Never send a message with the choice numbers still showing.
messenger.compose.onBeforeSend.addListener(async (tab) => {
  try {
    await messenger.tabs.sendMessage(tab.id, { op: "command", name: "cancel_choices" });
  } catch (e) { /* no editing code in that window */ }
  return {};
});

run();

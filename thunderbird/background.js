// Links the speech engine to the message being written.
//
// The engine can't call in, so this keeps one request open to it (a long poll). The
// engine answers with the next thing to do; the result goes back with the next poll.
"use strict";

const ENGINE = "http://127.0.0.1:47613/poll";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
  let replies = [];
  for (;;) {
    try {
      const response = await fetch(ENGINE, { method: "POST", body: JSON.stringify({ replies }) });
      replies = [];
      const request = await response.json();
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

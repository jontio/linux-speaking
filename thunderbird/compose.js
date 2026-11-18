// Edits the message being written, on request from the speech engine.
//
// Answers the same requests as the LibreOffice Writer extension: what is around the
// cursor, insert this, and commands such as backspace, select and undo. Text changes
// go through the editor's own commands, so Thunderbird's undo keeps working.
"use strict";

(function () {
  const PARAGRAPH = "\u2029";
  const LINE = "\u2028";
  const BLOCKS = new Set(["P", "DIV", "LI", "BLOCKQUOTE", "PRE", "H1", "H2", "H3", "H4", "H5",
    "H6", "TD", "TH", "UL", "OL", "TABLE", "BODY"]);
  const MAX_CHOICES = 20;
  const CHOICE_MS = 25000;
  const WORD_CHAR = /[\p{L}\p{N}'\u2019]/u;
  const LETTER = /[\p{L}\p{N}]/u;
  // Whether the character at `i` is part of a word. An apostrophe is, between two
  // letters ("don't"); beside a word it is a quote mark, and no part of it ('hello').
  const inWord = (text, i) => LETTER.test(text[i]) ||
    ((text[i] === "'" || text[i] === "\u2019") && i > 0 && i + 1 < text.length &&
     LETTER.test(text[i - 1]) && LETTER.test(text[i + 1]));

  let history = [];    // the text of recent phrases, newest last
  let choices = null;  // { ranges, layer, timer } while numbers are showing
  // After "correct ...": { mark, range, where }, the place the cursor was at, the words
  // chosen, and whether the cursor was "before", "among" or "after" them, until something
  // is said over them.
  let correction = null;

  const ok = (extra) => Object.assign({ ok: true }, extra || {});
  const fail = (why) => ({ ok: false, why });
  const sel = () => window.getSelection();
  const run = (command, value) => document.execCommand(command, false, value);

  function blockOf(node) {
    while (node && node !== document.body) {
      if (node.nodeType === 1 && BLOCKS.has(node.nodeName)) return node;
      node = node.parentNode;
    }
    return document.body;
  }

  // The text of the line the cursor is on: `tail` keeps what follows the last line
  // break (for text before the cursor), otherwise what comes before the first.
  function lineText(fragment, tail) {
    let out = "";
    const walker = document.createTreeWalker(fragment, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeType === 3) {
        out += n.data;
      } else if (n.nodeName === "BR" || BLOCKS.has(n.nodeName)) {
        if (tail) out = "";
        else if (n.nodeName === "BR" || out) break;
      }
    }
    return out.replace(/\u00a0/g, " ");
  }

  function around() {
    const s = sel();
    if (!s.rangeCount) return null;
    const r = s.getRangeAt(0);
    const before = document.createRange();
    before.selectNodeContents(blockOf(r.startContainer));
    before.setEnd(r.startContainer, r.startOffset);
    const after = document.createRange();
    after.selectNodeContents(blockOf(r.endContainer));
    after.setStart(r.endContainer, r.endOffset);
    const reply = { before: lineText(before.cloneContents(), true), after: lineText(after.cloneContents(), false) };
    if (!s.isCollapsed) reply.selected = true; // what is dictated will replace the selection
    return reply;
  }

  function extend(direction, count) {
    for (let i = 0; i < count; i++) sel().modify("extend", direction, "character");
  }

  function move(direction, count) {
    for (let i = 0; i < count; i++) sel().modify("move", direction, "character");
  }

  // ---- "correct ...": the cursor goes back afterwards --------------------------
  // The place the cursor is at now, kept as the text around it changes.
  function placeNow() {
    const s = sel();
    if (!s.rangeCount) return null;
    const mark = s.getRangeAt(0).cloneRange();
    mark.collapse(false);
    return mark;
  }

  // Remember that the cursor was at `mark` when the words in `range` were chosen.
  function chose(range, mark) {
    correction = null;
    if (!mark) return;
    const where = mark.compareBoundaryPoints(Range.START_TO_START, range) <= 0 ? "before"
      : mark.compareBoundaryPoints(Range.END_TO_END, range) >= 0 ? "after" : "among";
    correction = { mark, range: range.cloneRange(), where };
  }

  // Where the cursor was before "correct ...", if the words it chose are still what is
  // selected. Forgotten either way: the next thing said or done settles it.
  function correcting() {
    const was = correction;
    correction = null;
    const s = sel();
    if (!was || !s.rangeCount || s.isCollapsed) return null;
    const now = s.getRangeAt(0);
    return now.compareBoundaryPoints(Range.START_TO_START, was.range) === 0 &&
      now.compareBoundaryPoints(Range.END_TO_END, was.range) === 0 ? was : null;
  }

  function goTo(mark) {
    const range = mark.cloneRange();
    range.collapse(true);
    setSelection(range);
  }

  // ---- inserting ---------------------------------------------------------------
  function insert(m) {
    const s = sel();
    if (!s.rangeCount) return fail("no cursor");
    const text = m.text || "";
    if (!text && !m.delete_before && !m.delete_after) return ok({ text: "" });
    const back = correcting();
    if (!s.isCollapsed) run("delete"); // dictating over a selection replaces it
    if (m.delete_before) { extend("backward", m.delete_before); run("delete"); }
    if (m.delete_after) { extend("forward", m.delete_after); run("delete"); }
    let piece = "";
    const flush = () => { if (piece) { run("insertText", piece); piece = ""; } };
    for (const ch of text) {
      if (ch === PARAGRAPH) { flush(); run("insertParagraph"); }
      else if (ch === LINE) { flush(); run("insertLineBreak"); }
      else piece += ch;
    }
    flush();
    if (m.capitalise_next) {
      const rest = around().after;
      const at = rest.search(/\p{L}/u);
      if (at >= 0 && rest[at] !== rest[at].toUpperCase()) {
        move("forward", at);
        extend("forward", 1);
        run("insertText", rest[at].toUpperCase());
        move("backward", at + 1);
      }
    }
    if (text) {
      history.push(text);
      if (history.length > 20) history.shift();
    }
    if (back && back.where !== "among" && s.rangeCount) {
      // After "correct ...": back to where the cursor was before it. A place that was
      // after the old words is never before the end of the new ones.
      const now = s.getRangeAt(0);
      if (back.where === "before" || back.mark.compareBoundaryPoints(Range.START_TO_START, now) > 0) {
        goTo(back.mark);
      }
    }
    return ok(back ? { text, back: true } : { text });
  }

  // ---- the last phrase ----------------------------------------------------------
  const squash = (t) => t.replace(/[\s\u2028\u2029\u00a0]/g, "");

  // Select the last phrase, if the cursor is still right after it.
  function selectLast() {
    if (!history.length) return false;
    const text = history[history.length - 1];
    const s = sel();
    if (!s.rangeCount) return false;
    if (!s.isCollapsed) s.collapseToEnd();
    extend("backward", Array.from(text).length);
    if (squash(s.toString()) === squash(text)) return true;
    s.collapseToEnd();
    return false;
  }

  function scratch() {
    if (!selectLast()) return fail("nothing to scratch");
    run("delete");
    history.pop();
    return ok();
  }

  // ---- finding words --------------------------------------------------------------
  // The message as one string, with where each character lives. Line and paragraph
  // breaks become "\n", which no search phrase can cross.
  function textIndex() {
    let flat = "";
    const map = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeType === 3) {
        for (let i = 0; i < n.data.length; i++) map.push([n, i]);
        flat += n.data;
      } else if (n.nodeName === "BR" || BLOCKS.has(n.nodeName)) {
        flat += "\n";
        map.push(null);
      }
    }
    return { flat, map };
  }

  const normChar = (c) => (c === "\u2019" ? "'" : c.toLowerCase());

  // Every whole-word match for the phrase, ignoring case and punctuation.
  function findAll(phrase) {
    const words = Array.from(phrase).map((c) => (WORD_CHAR.test(c) ? normChar(c) : " "))
      .join("").split(" ").map((word) => word.replace(/^'+|'+$/g, "")).filter(Boolean);
    if (!words.length) return [];
    const needle = words.join(" ");
    const { flat, map } = textIndex();
    let chars = "";
    const index = [];
    let gap = true;
    for (let i = 0; i < flat.length; i++) {
      const c = flat[i];
      if (c === "\n") { chars += "\n"; index.push(i); gap = true; }
      else if (inWord(flat, i)) { chars += normChar(c); index.push(i); gap = false; }
      else if (!gap) { chars += " "; index.push(i); gap = true; }
    }
    const edge = (c) => c === undefined || c === " " || c === "\n";
    const found = [];
    for (let at = chars.indexOf(needle); at >= 0; at = chars.indexOf(needle, at + 1)) {
      const end = at + needle.length;
      if (!edge(chars[at - 1]) || !edge(chars[end])) continue;
      const first = map[index[at]];
      const last = map[index[end - 1]];
      const range = document.createRange();
      range.setStart(first[0], first[1]);
      range.setEnd(last[0], last[1] + 1);
      found.push(range);
    }
    return found;
  }

  // How far a match is from the cursor: 0 if the cursor is inside it.
  function distance(range, cursor) {
    if (cursor.compareBoundaryPoints(Range.START_TO_START, range) >= 0 &&
        cursor.compareBoundaryPoints(Range.START_TO_END, range) <= 0) return 0;
    const between = document.createRange();
    if (cursor.compareBoundaryPoints(Range.START_TO_START, range) < 0) {
      between.setStart(cursor.startContainer, cursor.startOffset);
      between.setEnd(range.startContainer, range.startOffset);
    } else {
      between.setStart(range.endContainer, range.endOffset);
      between.setEnd(cursor.startContainer, cursor.startOffset);
    }
    return between.toString().length + 1;
  }

  function setSelection(range) {
    const s = sel();
    s.removeAllRanges();
    s.addRange(range);
    const element = range.startContainer.parentElement;
    if (element && element.scrollIntoView) element.scrollIntoView({ block: "nearest" });
  }

  // `mark` is given for "correct ...": the place the cursor was at, to go back to.
  function select(phrase, nearest, mark) {
    const s = sel();
    correction = null;
    let matches = findAll(phrase);
    if (!matches.length) return fail("can't find that");
    const take = (range) => { setSelection(range); chose(range, mark); return ok(); };
    const cursor = s.rangeCount ? s.getRangeAt(0).cloneRange() : null;
    if (cursor) {
      cursor.collapse(true);
      // Keep the matches closest to the cursor, in the order they appear.
      const ranked = matches.map((range, i) => ({ range, i, d: distance(range, cursor) }));
      ranked.sort((a, b) => a.d - b.d || a.i - b.i);
      if (nearest) return take(ranked[0].range);
      matches = ranked.slice(0, MAX_CHOICES).sort((a, b) => a.i - b.i).map((r) => r.range);
    }
    if (matches.length === 1 || nearest) return take(matches[0]);
    showChoices(matches);
    choices.mark = mark;
    return ok({ choices: matches.length });
  }

  // ---- numbered choices ---------------------------------------------------------
  // Small numbers drawn over the page, outside the message text, so nothing in the
  // message changes.
  function showChoices(ranges) {
    clearChoices();
    const layer = document.createElement("div");
    layer.setAttribute("data-linux-speaking", "numbers");
    layer.setAttribute("contenteditable", "false");
    layer.style.cssText = "position:absolute;left:0;top:0;width:0;height:0;pointer-events:none;z-index:2147483647;";
    ranges.forEach((range, i) => {
      const box = range.getClientRects()[0];
      if (!box) return;
      const tag = document.createElement("span");
      tag.textContent = String(i + 1);
      tag.style.cssText = "position:absolute;left:" + (box.left + window.scrollX) + "px;top:" +
        (box.top + window.scrollY - 11) + "px;font:bold 10px sans-serif;line-height:12px;" +
        "padding:0 3px;border-radius:3px;color:#fff;background:#d32f2f;";
      layer.appendChild(tag);
    });
    document.documentElement.appendChild(layer);
    choices = { ranges, layer, timer: setTimeout(clearChoices, CHOICE_MS) };
  }

  function clearChoices() {
    if (!choices) return;
    clearTimeout(choices.timer);
    choices.layer.remove();
    choices = null;
  }

  // ---- moving the cursor ------------------------------------------------------------
  function leafBlocks() {
    const all = [document.body].concat(Array.from(document.body.querySelectorAll("*"))
      .filter((e) => BLOCKS.has(e.nodeName)));
    return all.filter((e) => !Array.from(e.children).some((c) => BLOCKS.has(c.nodeName)) &&
      e.textContent.trim() !== "");
  }

  function place(block, atStart) {
    const range = document.createRange();
    range.selectNodeContents(block);
    if (!atStart && block.lastChild && block.lastChild.nodeName === "BR") {
      range.setEndBefore(block.lastChild); // stay on the last line of text
    }
    range.collapse(atStart);
    setSelection(range);
  }

  function emptyBetween(startNode, startOffset, endNode, endOffset) {
    const range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    return range.toString().trim() === "";
  }

  // To the end (or start) of the paragraph. Already there, carry on to the next one.
  function paragraphEdge(toEnd) {
    const s = sel();
    if (!s.rangeCount) return fail("no cursor");
    const r = s.getRangeAt(0);
    const blocks = leafBlocks();
    const here = blockOf(r.startContainer);
    let at = blocks.indexOf(here);
    if (at < 0) { place(here, !toEnd); return ok(); }
    const edge = toEnd
      ? emptyBetween(r.endContainer, r.endOffset, here, here.childNodes.length)
      : emptyBetween(here, 0, r.startContainer, r.startOffset);
    if (edge) at = Math.max(0, Math.min(blocks.length - 1, at + (toEnd ? 1 : -1)));
    place(blocks[at], !toEnd);
    return ok();
  }

  // ---- formatting -----------------------------------------------------------------
  const TITLE = (t) => {
    // A capital on each word. Capitals that are there already stay, so "the NASA report"
    // is "The NASA Report", and so does the small first letter of a word spelled like
    // "iPhone". Only text that is all in capitals is brought down first. (As title() in
    // dictation/formatting.py, which Writer, Kate and typed-into boxes use.)
    if (!/\p{Ll}/u.test(t)) t = t.toLowerCase();
    return t.replace(/(?<![\p{L}\p{N}_'\u2019])\p{L}[\p{L}\p{N}_'\u2019]*/gu,
      (word) => (/^\p{Ll}.*\p{Lu}/u.test(word) ? word : word.replace(/^\p{L}/u, (c) => c.toUpperCase())));
  };
  const CASES = { cap: TITLE, all_caps: (t) => t.toUpperCase(), no_caps: (t) => t.toLowerCase() };
  const STYLES = { bold: "bold", italic: "italic", underline: "underline" };

  function format(name) {
    const s = sel();
    let last = false;
    if (!s.rangeCount || s.isCollapsed) {
      if (!selectLast()) return fail("nothing to format");
      last = true;
    }
    // The last phrase was selected only to be worked on: the cursor goes back after it, or
    // the next words would take its place.
    if (STYLES[name]) {
      if (!document.queryCommandState(STYLES[name])) run(STYLES[name]);
      if (last) { s.collapseToEnd(); run(STYLES[name]); } // and what comes next is plain again
      return ok();
    }
    const changed = CASES[name](s.toString());
    run("insertText", changed);
    if (last) history[history.length - 1] = changed;
    else extend("backward", Array.from(changed).length);
    return ok();
  }

  // ---- commands -------------------------------------------------------------------
  function command(m) {
    const s = sel();
    const name = m.name;
    if (name === "cancel_choices") return ok();
    if (name === "choose") {
      if (!choices) return fail("nothing to choose from");
      const n = parseInt(m.arg, 10);
      if (!(n >= 1 && n <= choices.ranges.length)) return fail("no such number");
      const range = choices.ranges[n - 1];
      const mark = choices.mark;
      clearChoices();
      setSelection(range);
      chose(range, mark);
      return ok();
    }
    if (!s.rangeCount) return fail("no cursor");
    switch (name) {
      case "new_paragraph": return insert({ text: PARAGRAPH });
      case "new_line": return insert({ text: LINE });
      case "undo": run("undo"); return ok();
      case "scratch": return scratch();
      case "delete":
        if (s.isCollapsed) return scratch();
        run("delete");
        return ok();
      case "backspace":
        if (s.isCollapsed) extend("backward", Math.max(1, Math.min(99, parseInt(m.arg, 10) || 1)));
        run("delete");
        return ok();
      case "select": return select(m.arg || "", Boolean(m.nearest));
      case "correct": return select(m.arg || "", Boolean(m.nearest), placeNow());
      case "select_last": return selectLast() ? ok() : fail("nothing to select");
      case "select_all": s.selectAllChildren(document.body); return ok();
      case "unselect": {
        const back = correcting();
        if (back) goTo(back.mark); // after "correct ...", where it was
        else s.collapseToEnd();
        return ok();
      }
      case "line_end": s.modify("move", "forward", "lineboundary"); return ok();
      case "line_start": s.modify("move", "backward", "lineboundary"); return ok();
      case "word_left": case "word_right": {
        const words = Math.max(1, Math.min(99, parseInt(m.arg, 10) || 1));
        for (let i = 0; i < words; i++) s.modify("move", name === "word_left" ? "backward" : "forward", "word");
        return ok();
      }
      case "line_up": case "line_down": {
        const lines = Math.max(1, Math.min(999, parseInt(m.arg, 10) || 1));
        for (let i = 0; i < lines; i++) s.modify("move", name === "line_up" ? "backward" : "forward", "line");
        return ok();
      }
      case "select_line": case "delete_line": {
        const lines = name === "delete_line" ? Math.max(1, Math.min(99, parseInt(m.arg, 10) || 1)) : 1;
        for (let i = 0; i < lines; i++) {
          s.modify("move", "backward", "lineboundary");
          s.modify("extend", "forward", "lineboundary");
          if (name === "select_line") break;
          if (!s.isCollapsed) run("delete");
          run("forwardDelete"); // and the line break, so the lines below move up
        }
        return ok();
      }
      case "para_end": return paragraphEdge(true);
      case "para_start": return paragraphEdge(false);
      case "doc_top": { const b = leafBlocks(); place(b.length ? b[0] : document.body, true); return ok(); }
      case "doc_end": { const b = leafBlocks(); place(b.length ? b[b.length - 1] : document.body, false); return ok(); }
      case "bold": case "italic": case "underline":
      case "cap": case "all_caps": case "no_caps":
        return format(name);
      default: return fail("unknown command");
    }
  }

  function handle(m) {
    try {
      if (choices && (m.op === "insert" || (m.op === "command" && m.name !== "choose"))) {
        clearChoices(); // doing anything else takes the numbers away
      }
      if (m.op === "command" && !["correct", "unselect", "choose", "cancel_choices"].includes(m.name)) {
        correction = null; // "correct ..." is only for what is said next
      }
      switch (m.op) {
        case "ping": return ok();
        case "status": return ok({ ready: true });
        case "context": { const a = around(); return a ? ok(a) : fail("no cursor"); }
        case "insert": return insert(m);
        case "command": return command(m);
        case "text": // for tests
          return ok({ text: textIndex().flat.replace(/\u00a0/g, " ").replace(/^\n+|\n+$/g, ""),
            selected: sel().toString(), numbers: choices ? choices.ranges.length : 0 });
        default: return fail("unknown request");
      }
    } catch (e) {
      return { ok: false, why: "error", error: String(e) };
    }
  }

  window.linuxSpeaking = handle; // for the test page
  if (typeof browser !== "undefined" && browser.runtime && browser.runtime.onMessage) {
    browser.runtime.onMessage.addListener((m) => Promise.resolve(handle(m)));
  }
})();

// Edits the document in the active editor, on request from the Linux Speaking engine.
//
// Each VS Code window listens on its own socket in the user's runtime folder and answers
// the same requests as the LibreOffice Writer extension: what is around the cursor,
// insert this, and commands such as backspace, select and undo. One JSON line in, one out.
"use strict";

const vscode = require("vscode");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");

const PARAGRAPH = String.fromCharCode(0x2029);
const LINE = String.fromCharCode(0x2028);
const MAX_CHOICES = 20;
const CHOICE_MS = 25000;
const SEARCH_AROUND = 20000; // characters either side of the cursor that "select" looks through
const HISTORY = 20;
const NO_FOCUS_CHECK = process.env.LINUX_SPEAKING_NO_FOCUS_CHECK === "1"; // for the test

// Markdown markers at the start of a line: headings, list items, quotes, check boxes.
const BLOCK_PREFIX = /^\s*(?:(?:#{1,6}|[-*+]|\d+[.)]|>)\s+(?:\[[ xX]\]\s+)?)+/;
const LIST_ITEM = /^(\s*)(?:([-*+])|(\d+)([.)]))(\s+)(\[[ xX]\]\s+)?/;
const QUOTE = /^(\s*>\s?)/;
const WORD_CHAR = /[\p{L}\p{N}'\u2019]/u;
const BLANK_LINE = /\n[ \t\r]*(?=\n)/;

let history = [];    // { uri, start, text } for recent phrases, newest last
let choices = null;  // { ranges, type, timer } while numbers are showing
let server = null;
let socketPath = "";
let queue = Promise.resolve();

const ok = (extra) => Object.assign({ ok: true }, extra || {});
const fail = (why) => ({ ok: false, why });
const isMarkdown = (doc) => doc.languageId === "markdown";
const isCode = (doc) => doc.languageId === "c" || doc.languageId === "cpp";
const NAME = /[A-Za-z_][A-Za-z0-9_]+/g;
const MAX_NAMES = 300;
const unix = (text) => text.replace(/\r\n/g, "\n");

// ---- which editor --------------------------------------------------------------------
function target() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme === "output") return undefined;
  return NO_FOCUS_CHECK || vscode.window.state.focused ? editor : undefined;
}

// VS Code reports cursor moves back to an extension a moment after they happen, and a late
// report of an older position would overwrite a newer one set here. So after moving the
// cursor, wait until that move itself has been reported back (or briefly, if nothing
// needed to change) before handling the next request.
function settled(editor, selection) {
  return new Promise((resolve) => {
    let timer = null;
    const listener = vscode.window.onDidChangeTextEditorSelection((event) => {
      if (event.textEditor === editor && event.selections.length &&
          event.selections[0].isEqual(selection)) finish();
    });
    const finish = () => { clearTimeout(timer); listener.dispose(); resolve(); };
    timer = setTimeout(finish, 150);
  });
}

async function place(editor, position) {
  const selection = new vscode.Selection(position, position);
  const reported = settled(editor, selection);
  editor.selection = selection;
  editor.revealRange(new vscode.Range(position, position));
  await reported;
}

async function select(editor, range) {
  const selection = new vscode.Selection(range.start, range.end);
  const reported = settled(editor, selection);
  editor.selection = selection;
  editor.revealRange(range);
  await reported;
}

// Where text ends if it is put at `start`.
function endOf(start, text) {
  const lines = text.split("\n");
  return lines.length === 1
    ? start.translate(0, text.length)
    : new vscode.Position(start.line + lines.length - 1, lines[lines.length - 1].length);
}

const edit = (editor, change) =>
  editor.edit(change, { undoStopBefore: true, undoStopAfter: true });

// ---- reading -------------------------------------------------------------------------
function around(editor) {
  const doc = editor.document;
  const sel = editor.selection;
  let before = doc.lineAt(sel.start.line).text.slice(0, sel.start.character);
  const after = doc.lineAt(sel.end.line).text.slice(sel.end.character);
  // After "# " or "- " a sentence is starting, whatever the marker looks like.
  if (isMarkdown(doc)) before = before.replace(BLOCK_PREFIX, "");
  const reply = { before, after, language: doc.languageId };
  if (!sel.isEmpty) reply.selected = true; // what is dictated will replace the selection
  return reply;
}

// The names used in the file, nearest the cursor first, so the engine can recognise them
// when they are spoken as words.
function names(editor) {
  const doc = editor.document;
  const cursor = doc.offsetAt(editor.selection.active);
  const base = Math.max(0, cursor - SEARCH_AROUND);
  const text = doc.getText(new vscode.Range(doc.positionAt(base), doc.positionAt(cursor + SEARCH_AROUND)));
  const nearest = new Map();
  for (const m of text.matchAll(NAME)) {
    const distance = Math.abs(m.index - (cursor - base));
    if (!nearest.has(m[0]) || distance < nearest.get(m[0])) nearest.set(m[0], distance);
  }
  return Array.from(nearest.entries()).sort((a, b) => a[1] - b[1]).slice(0, MAX_NAMES).map((e) => e[0]);
}

// What the C/C++ language server (clangd, or Microsoft's) says could come next at the
// cursor: the names in scope and what kind of thing each is. Empty if there is no such
// extension, or it takes too long. VS Code's own word suggestions come back as "word".
const KINDS = {};
for (const [kind, name] of [
  ["Function", "function"], ["Method", "function"], ["Constructor", "function"],
  ["Variable", "variable"], ["Field", "variable"], ["Constant", "variable"],
  ["EnumMember", "variable"], ["Property", "variable"],
  ["Class", "type"], ["Struct", "type"], ["Interface", "type"], ["Enum", "type"],
  ["TypeParameter", "type"], ["Module", "namespace"], ["Keyword", "keyword"], ["Text", "word"],
]) KINDS[vscode.CompletionItemKind[kind]] = name;
const SCOPE_MS = 900;
const MAX_SCOPE = 250;

async function scope(editor) {
  const doc = editor.document;
  if (!isCode(doc)) return [];
  const asked = vscode.commands.executeCommand(
    "vscode.executeCompletionItemProvider", doc.uri, editor.selection.active);
  const list = await Promise.race([asked, new Promise((resolve) => setTimeout(() => resolve(null), SCOPE_MS))]);
  const found = [];
  const seen = new Set();
  for (const item of (list && list.items) || []) {
    if (item.kind === vscode.CompletionItemKind.Snippet) continue;
    const insert = typeof item.insertText === "string" ? item.insertText : item.insertText && item.insertText.value;
    const label = typeof item.label === "string" ? item.label : item.label && item.label.label;
    const m = /[A-Za-z_][A-Za-z0-9_]*/.exec(item.filterText || insert || label || "");
    if (!m || seen.has(m[0])) continue;
    seen.add(m[0]);
    found.push({ name: m[0], kind: KINDS[item.kind] || "other" });
    if (found.length >= MAX_SCOPE) break;
  }
  return found;
}

function indentUnit(editor) {
  const size = Number(editor.options.tabSize) || 4;
  return editor.options.insertSpaces === false ? "\t" : " ".repeat(size);
}

// ---- Markdown lists --------------------------------------------------------------------
// What a new line should start with, to carry on the list or quote that `line` is in.
function continuation(line) {
  const item = LIST_ITEM.exec(line);
  if (item) {
    const marker = item[2] ? item[2] : String(parseInt(item[3], 10) + 1) + item[4];
    return item[1] + marker + item[5] + (item[6] ? "[ ] " : "");
  }
  const quote = QUOTE.exec(line);
  return quote ? quote[1] : "";
}

// Turn the engine's break characters into line breaks. In Markdown, "new line" inside a
// list carries the list on, and "new paragraph" leaves a blank line and ends it. Anywhere
// else a new line keeps the indentation of the line before, and in C and C++ it goes one
// step deeper after "{" and one step back for a "}".
function expandBreaks(editor, position, text) {
  const doc = editor.document;
  const unit = indentUnit(editor);
  let line = doc.lineAt(position.line).text;
  if (!isMarkdown(doc)) line = line.slice(0, position.character);
  let out = "";
  for (const ch of text) {
    if (isMarkdown(doc)) {
      if (ch === PARAGRAPH) { out += "\n\n"; line = ""; }
      else if (ch === LINE) { line = continuation(line); out += "\n" + line; }
      else out += ch;
      continue;
    }
    if (ch === PARAGRAPH || ch === LINE) {
      let indent = /^[ \t]*/.exec(line)[0];
      if (isCode(doc) && line.trimEnd().endsWith("{")) indent += unit;
      out += (ch === PARAGRAPH ? "\n\n" : "\n") + indent;
      line = indent;
    } else {
      if (ch === "}" && isCode(doc) && line.trim() === "" && line.endsWith(unit) && out.endsWith(unit)) {
        out = out.slice(0, -unit.length); // a closing brace steps back out
        line = line.slice(0, -unit.length);
      }
      out += ch;
      line += ch;
    }
  }
  return out;
}

// ---- inserting -------------------------------------------------------------------------
async function insert(editor, m) {
  const doc = editor.document;
  const sel = editor.selection;
  const deleteBefore = Math.max(0, m.delete_before | 0);
  const deleteAfter = Math.max(0, m.delete_after | 0);
  const text = expandBreaks(editor, sel.start, String(m.text || ""));
  if (!text && !deleteBefore && !deleteAfter) return ok({ text: "" });
  // Spaces are only ever removed within the line.
  let start = sel.start.translate(0, -Math.min(deleteBefore, sel.start.character));
  const lead = doc.lineAt(start.line).text.slice(0, start.character);
  const unit = indentUnit(editor);
  if (isCode(doc) && text.startsWith("}") && lead.trim() === "" && lead.endsWith(unit)) {
    start = start.translate(0, -unit.length); // a closing brace on its own line steps back out
  }
  const lineEnd = doc.lineAt(sel.end.line).range.end;
  const end = sel.end.translate(0, Math.min(deleteAfter, lineEnd.character - sel.end.character));
  let capital = null;
  if (m.capitalise_next) {
    const rest = doc.lineAt(end.line).text.slice(end.character);
    const at = rest.search(/\p{L}/u);
    if (at >= 0 && rest[at] !== rest[at].toUpperCase() && rest[at].toUpperCase().length === 1) {
      const from = end.translate(0, at);
      capital = { range: new vscode.Range(from, from.translate(0, 1)), text: rest[at].toUpperCase() };
    }
  }
  const done = await edit(editor, (builder) => {
    builder.replace(new vscode.Range(start, end), text);
    if (capital) builder.replace(capital.range, capital.text);
  });
  if (!done) return fail("could not edit");
  await place(editor, endOf(start, text));
  if (text) {
    history.push({ uri: doc.uri.toString(), start, text });
    if (history.length > HISTORY) history.shift();
  }
  return ok({ text });
}

// ---- the last phrase -------------------------------------------------------------------
// Where the last phrase is, if it is still where it was put or just before the cursor.
function lastRange(editor) {
  const doc = editor.document;
  while (history.length && history[history.length - 1].uri !== doc.uri.toString()) history.pop();
  if (!history.length) return null;
  const phrase = history[history.length - 1];
  const tries = [phrase.start];
  const cursor = doc.offsetAt(editor.selection.active);
  if (cursor >= phrase.text.length) tries.push(doc.positionAt(cursor - phrase.text.length));
  for (const start of tries) {
    const range = doc.validateRange(new vscode.Range(start, endOf(start, phrase.text)));
    if (unix(doc.getText(range)) === phrase.text) return range;
  }
  return null;
}

async function scratch(editor) {
  const range = lastRange(editor);
  if (!range) {
    history.pop();
    return fail("nothing to scratch");
  }
  history.pop();
  if (!(await edit(editor, (builder) => builder.delete(range)))) return fail("could not edit");
  await place(editor, range.start);
  return ok();
}

// ---- finding words ---------------------------------------------------------------------
const normChar = (c) => (c === "\u2019" ? "'" : c.toLowerCase());

// Start and end of every whole-word match in `text`, ignoring case and punctuation.
// A match never runs across a line break.
function findAll(text, phrase) {
  const words = Array.from(phrase).map((c) => (WORD_CHAR.test(c) ? normChar(c) : " "))
    .join("").split(" ").filter(Boolean);
  if (!words.length) return [];
  const needle = words.join(" ");
  let chars = "";
  const index = [];
  let gap = true;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "\n") { chars += "\n"; index.push(i); gap = true; }
    else if (WORD_CHAR.test(c)) { chars += normChar(c); index.push(i); gap = false; }
    else if (!gap) { chars += " "; index.push(i); gap = true; }
  }
  const edge = (c) => c === undefined || c === " " || c === "\n";
  const found = [];
  for (let at = chars.indexOf(needle); at >= 0; at = chars.indexOf(needle, at + 1)) {
    const end = at + needle.length;
    if (edge(chars[at - 1]) && edge(chars[end])) found.push([index[at], index[end - 1] + 1]);
  }
  return found;
}

async function selectWords(editor, phrase, nearest) {
  const doc = editor.document;
  const cursor = doc.offsetAt(editor.selection.active);
  const base = Math.max(0, cursor - SEARCH_AROUND);
  const window = new vscode.Range(doc.positionAt(base), doc.positionAt(cursor + SEARCH_AROUND));
  const where = cursor - base;
  const matches = findAll(doc.getText(window), phrase).map(([start, end], i) => ({
    i, start, end,
    distance: where < start ? start - where : where > end ? where - end : 0,
  }));
  if (!matches.length) return fail("can't find that");
  matches.sort((a, b) => a.distance - b.distance || a.i - b.i);
  const range = (m) => new vscode.Range(doc.positionAt(base + m.start), doc.positionAt(base + m.end));
  if (nearest || matches.length === 1) {
    await select(editor, range(matches[0]));
    return ok();
  }
  // The closest few, numbered in the order they appear.
  const shown = matches.slice(0, MAX_CHOICES).sort((a, b) => a.i - b.i).map(range);
  showChoices(editor, shown);
  return ok({ choices: shown.length });
}

// ---- numbered choices ------------------------------------------------------------------
// A small number drawn before each match. Nothing in the document changes.
function showChoices(editor, ranges) {
  clearChoices();
  const type = vscode.window.createTextEditorDecorationType({
    backgroundColor: "rgba(211, 47, 47, 0.18)",
    borderRadius: "2px",
  });
  editor.setDecorations(type, ranges.map((range, i) => ({
    range,
    renderOptions: {
      before: {
        contentText: String(i + 1),
        color: "#ffffff",
        backgroundColor: "#d32f2f",
        fontWeight: "bold",
        margin: "0 2px 0 0",
        // The extra declarations ride in on this property: there is no other way to set them.
        textDecoration: "none; font-size: 0.75em; padding: 0 3px; border-radius: 3px; vertical-align: text-top",
      },
    },
  })));
  choices = { ranges, type, uri: editor.document.uri.toString(), timer: setTimeout(clearChoices, CHOICE_MS) };
}

function clearChoices() {
  if (!choices) return;
  clearTimeout(choices.timer);
  choices.type.dispose();
  choices = null;
}

// ---- paragraphs ------------------------------------------------------------------------
// A paragraph is a run of lines with no blank line in it. Already at its edge, carry on
// to the next (or previous) paragraph.
function paragraphEnd(after) {
  let edge = BLANK_LINE.exec(after);
  const here = edge ? after.slice(0, edge.index) : after;
  if (here.trim() === "") {
    const body = after.replace(/^[ \t\r\n]+/, "");
    if (!body) return 0;
    edge = BLANK_LINE.exec(body);
    const length = edge ? edge.index : body.replace(/[ \t\r\n]+$/, "").length;
    return after.length - body.length + length;
  }
  return edge ? edge.index : after.replace(/[\r\n]+$/, "").length;
}

function paragraphStart(before) {
  const lastStart = (text) => {
    const afterBlank = /\n(?:[ \t\r]*\n)+/g;
    let end = 0;
    for (let m = afterBlank.exec(text); m; m = afterBlank.exec(text)) end = m.index + m[0].length;
    return end;
  };
  const start = lastStart(before);
  if (before.slice(start).trim() === "") {
    return lastStart(before.slice(0, start).replace(/[ \t\r\n]+$/, ""));
  }
  return start;
}

async function paragraphEdge(editor, toEnd) {
  const doc = editor.document;
  const cursor = doc.offsetAt(editor.selection.active);
  if (toEnd) {
    const range = new vscode.Range(editor.selection.active, doc.positionAt(cursor + 4 * SEARCH_AROUND));
    await place(editor, doc.positionAt(cursor + paragraphEnd(doc.getText(range))));
  } else {
    const base = Math.max(0, cursor - 4 * SEARCH_AROUND);
    const range = new vscode.Range(doc.positionAt(base), editor.selection.active);
    await place(editor, doc.positionAt(base + paragraphStart(doc.getText(range))));
  }
  return ok();
}

// ---- formatting ------------------------------------------------------------------------
const TITLE = (t) => t.toLowerCase().replace(/(^|[^\p{L}'\u2019])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());
const CASES = { cap: TITLE, all_caps: (t) => t.toUpperCase(), no_caps: (t) => t.toLowerCase() };
const WRAPS = { bold: "**", italic: "*" };

async function format(editor, name) {
  const doc = editor.document;
  const fromSelection = !editor.selection.isEmpty;
  const range = fromSelection ? new vscode.Range(editor.selection.start, editor.selection.end) : lastRange(editor);
  if (!range) return fail("nothing to format");
  const old = unix(doc.getText(range));
  let changed;
  if (CASES[name]) {
    changed = CASES[name](old);
  } else if (WRAPS[name] && isMarkdown(doc)) {
    // Markers go inside any spaces at the edges, or Markdown won't treat them as emphasis.
    const inner = old.trim();
    if (!inner) return fail("nothing to format");
    const lead = old.slice(0, old.indexOf(inner));
    changed = lead + WRAPS[name] + inner + WRAPS[name] + old.slice(lead.length + inner.length);
  } else if (name === "underline" && isMarkdown(doc)) {
    return fail("markdown has no underline");
  } else {
    return fail("plain text has no formatting");
  }
  if (changed !== old && !(await edit(editor, (builder) => builder.replace(range, changed)))) {
    return fail("could not edit");
  }
  const end = endOf(range.start, changed);
  if (fromSelection) {
    await select(editor, new vscode.Range(range.start, end));
  } else {
    history[history.length - 1] = { uri: doc.uri.toString(), start: range.start, text: changed };
    await place(editor, end);
  }
  return ok();
}

// ---- commands --------------------------------------------------------------------------
async function command(editor, m) {
  const doc = editor.document;
  const sel = editor.selection;
  // These commands act on whatever has the keyboard, which may be the chat box or the
  // terminal rather than the document. Give the document the keyboard first.
  const run = async (id, ...args) => {
    await vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup");
    await vscode.commands.executeCommand(id, ...args);
    await new Promise((resolve) => setTimeout(resolve, 40)); // let the cursor report arrive
  };
  switch (m.name) {
    case "choose": {
      if (!choices || choices.uri !== doc.uri.toString()) return fail("nothing to choose from");
      const n = parseInt(m.arg, 10);
      if (!(n >= 1 && n <= choices.ranges.length)) return fail("no such number");
      const range = choices.ranges[n - 1];
      clearChoices();
      await select(editor, range);
      return ok();
    }
    case "new_paragraph": return insert(editor, { text: PARAGRAPH });
    case "new_line": {
      // "New line" on an empty list item ends the list, as pressing Enter there would.
      const line = doc.lineAt(sel.start.line);
      const item = isMarkdown(doc) && sel.isEmpty ? LIST_ITEM.exec(line.text) || QUOTE.exec(line.text) : null;
      if (item && item[0].length === line.text.length && line.text.trim() !== "") {
        if (!(await edit(editor, (builder) => builder.delete(line.range)))) return fail("could not edit");
        await place(editor, line.range.start);
        return ok();
      }
      return insert(editor, { text: LINE });
    }
    case "press_enter": await run("type", { text: "\n" }); return ok(); // the real Enter key
    case "undo": {
      const range = lastRange(editor);
      await run("undo");
      if (range) history.pop();
      return ok();
    }
    case "scratch": return scratch(editor);
    case "delete":
      if (sel.isEmpty) return scratch(editor);
      return (await edit(editor, (builder) => builder.delete(sel))) ? ok() : fail("could not edit");
    case "backspace": {
      let range = new vscode.Range(sel.start, sel.end);
      if (sel.isEmpty) {
        const count = Math.max(1, Math.min(99, parseInt(m.arg, 10) || 1));
        range = new vscode.Range(doc.positionAt(Math.max(0, doc.offsetAt(sel.start) - count)), sel.start);
      }
      if (!(await edit(editor, (builder) => builder.delete(range)))) return fail("could not edit");
      await place(editor, range.start);
      return ok();
    }
    case "select": return selectWords(editor, String(m.arg || ""), Boolean(m.nearest));
    case "select_last": {
      const range = lastRange(editor);
      if (!range) return fail("nothing to select");
      await select(editor, range);
      return ok();
    }
    case "select_all": await run("editor.action.selectAll"); return ok();
    case "unselect": await place(editor, sel.end); return ok();
    case "line_end": await run("cursorEnd"); return ok();
    case "line_start": await run("cursorHome"); return ok();
    case "word_left": case "word_right": {
      const words = Math.max(1, Math.min(99, parseInt(m.arg, 10) || 1));
      const step = m.name === "word_left" ? "cursorWordStartLeft" : "cursorWordStartRight";
      await vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup");
      for (let i = 0; i < words; i++) await vscode.commands.executeCommand(step);
      await new Promise((resolve) => setTimeout(resolve, 40)); // let the cursor report arrive
      return ok();
    }
    case "line_up": case "line_down": {
      const lines = Math.max(1, Math.min(999, parseInt(m.arg, 10) || 1));
      // By the lines you see, so a long wrapped paragraph moves a row at a time.
      await run("cursorMove", { to: m.name === "line_up" ? "up" : "down", by: "wrappedLine", value: lines });
      return ok();
    }
    case "go_to_line": {
      const wanted = Math.max(1, Math.min(doc.lineCount, parseInt(m.arg, 10) || 1)) - 1;
      const indent = doc.lineAt(wanted).firstNonWhitespaceCharacterIndex;
      await place(editor, new vscode.Position(wanted, indent));
      return ok();
    }
    case "select_line": {
      const line = doc.lineAt(sel.active.line);
      await select(editor, line.range);
      return ok();
    }
    case "delete_line": {
      const lines = Math.max(1, Math.min(99, parseInt(m.arg, 10) || 1));
      for (let i = 0; i < lines; i++) await run("editor.action.deleteLines");
      return ok();
    }
    case "tab": await run("tab"); return ok(); // the real Tab key: indents as the editor is set to
    case "duplicate_line": await run("editor.action.copyLinesDownAction"); return ok();
    case "indent": await run("editor.action.indentLines"); return ok();
    case "outdent": await run("editor.action.outdentLines"); return ok();
    case "comment_line": await run("editor.action.commentLine"); return ok();
    case "para_end": return paragraphEdge(editor, true);
    case "para_start": return paragraphEdge(editor, false);
    case "doc_top": await run("cursorTop"); return ok();
    case "doc_end": await run("cursorBottom"); return ok();
    case "cap": case "all_caps": case "no_caps":
    case "bold": case "italic": case "underline":
      return format(editor, m.name);
    default: return fail("unknown command");
  }
}

async function handle(m) {
  if (m.op === "ping") return ok();
  if (m.op === "open" && NO_FOCUS_CHECK) {
    // The test opens its second scratch file this way.
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(String(m.path)));
    return ok();
  }
  if (m.op === "quit" && NO_FOCUS_CHECK) {
    // The test closes its own window this way, so VS Code shuts down normally.
    setTimeout(() => vscode.commands.executeCommand("workbench.action.quit"), 100);
    return ok();
  }
  if (m.op === "command" && m.name === "cancel_choices") {
    clearChoices(); // works whether or not this window is in front
    return ok();
  }
  const editor = target();
  if (m.op === "status") return ok({ ready: Boolean(editor) });
  if (!editor) return fail("editor not focused");
  if (choices && (m.op === "insert" || (m.op === "command" && m.name !== "choose"))) {
    clearChoices(); // doing anything else takes the numbers away
  }
  switch (m.op) {
    case "context": return ok(around(editor));
    case "symbols": return ok({ names: names(editor), scope: await scope(editor) });
    case "insert": return insert(editor, m);
    case "command": return command(editor, m);
    case "text": // for tests
      return ok({
        text: unix(editor.document.getText()),
        selected: unix(editor.document.getText(editor.selection)),
        numbers: choices ? choices.ranges.length : 0,
        language: editor.document.languageId,
        version: editor.document.version,
        dirty: editor.document.isDirty,
      });
    default: return fail("unknown request");
  }
}

// ---- the socket ------------------------------------------------------------------------
function defaultSocketPath() {
  // Not XDG_RUNTIME_DIR: a snap-packaged VS Code is given a private one the engine can't see.
  const shared = path.join("/run/user", String(os.userInfo().uid));
  const folder = fs.existsSync(shared) ? shared : process.env.XDG_RUNTIME_DIR || os.tmpdir();
  return path.join(folder, "linux-speaking-vscode-" + process.pid + ".sock");
}

function listen() {
  socketPath = process.env.LINUX_SPEAKING_VSCODE_SOCKET || defaultSocketPath();
  try { fs.unlinkSync(socketPath); } catch (e) { /* not there */ }
  server = net.createServer((connection) => {
    let data = "";
    connection.setEncoding("utf8");
    connection.on("error", () => {});
    connection.on("data", (chunk) => {
      data += chunk;
      const end = data.indexOf("\n");
      if (end < 0) return;
      const line = data.slice(0, end);
      data = "";
      // One request at a time, in the order they arrive.
      queue = queue.then(async () => {
        let reply;
        try {
          reply = await handle(JSON.parse(line));
        } catch (e) {
          reply = { ok: false, why: "error", error: String(e) };
        }
        connection.end(JSON.stringify(reply) + "\n");
      });
    });
  });
  server.on("error", (e) => console.error("Linux Speaking: " + e));
  server.listen(socketPath, () => {
    try { fs.chmodSync(socketPath, 0o600); } catch (e) { /* best effort */ }
  });
}

function activate(context) {
  listen();
  context.subscriptions.push(
    // An edit moves text, so the numbered places are no longer right.
    vscode.workspace.onDidChangeTextDocument((event) => {
      if (choices && event.document.uri.toString() === choices.uri) clearChoices();
    }),
    { dispose: deactivate }
  );
}

function deactivate() {
  clearChoices();
  if (server) {
    server.close();
    server = null;
    try { fs.unlinkSync(socketPath); } catch (e) { /* already gone */ }
  }
}

module.exports = { activate, deactivate };

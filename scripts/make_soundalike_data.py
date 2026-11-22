#!/usr/bin/env python3
"""Makes dictation/soundalike.txt: how often each word of a sound-alike set stands in
each place (see dictation/soundalike.py, which reads it).

    python3 -I scripts/make_soundalike_data.py BOOKS             # make the file again
    python3 -I scripts/make_soundalike_data.py BOOKS --measure   # try it on books kept back
    python3 -I scripts/make_soundalike_data.py --numbers         # which books it was made from

    --index GUTINDEX.ALL    the mirrors' list of all the books, for their titles
    --any                   count every book in the folder, not only those of the shipped file
    --tried                 with --measure: the sets that were tried and left out as well

BOOKS is a folder of plain-text books from Project Gutenberg (gutenberg.org), each as
NUMBER.txt, where NUMBER is the book's number there. They are in the public domain in
the United States. Nothing of their text goes into the file that is made: only counts
of which word stood next to which. The file names every book it was made from, at its
top, and --numbers prints their numbers. To fetch them from a mirror, one or two a
second (the folder is only ever read as text, never run):

    for n in $(python3 scripts/make_soundalike_data.py --numbers); do
      d=$(echo $n | sed 's/.$//;s/./&\//g')
      curl -s -o BOOKS/$n.txt https://mirrors.xmission.com/gutenberg/$d$n/$n-0.txt; sleep 0.5
    done

With --measure every fifth book is kept back, the counts are taken from the rest, and
each sound-alike word in the books kept back is tried three ways: as the last word
before a pause, as the first word after one, and anywhere else. As it was written, any
change is a wrong one. With each other word of its set put in its place, is it put
right? The figures are printed set by set. A set earns its place in soundalike.SETS only
by those figures: TRIED, below, are the sets that did not.

As shipped (825 books, 165 of them kept back, some 790,000 sound-alike words in those):
before a pause 0.35 in a thousand right words were changed and 64 in a hundred mix-ups put
right; after a pause 0.42 and 57; anywhere else 0.02 and 32. No set was wrong more than
twice in a thousand. Making the file takes about three minutes and a gigabyte of memory.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dictation import soundalike  # noqa: E402

# Sets that were tried on the books kept back and left out of soundalike.SETS, each with
# why. They are counted and measured again with --tried.
TRIED = (
    (("whose", "who's"), "put right too seldom to be worth it"),
    (("son", "sun"), "put right too seldom to be worth it"),
    (("whole", "hole"), "wrong too often"),
    (("piece", "peace"), "put right too seldom to be worth it"),
    (("break", "brake"), "wrong too often"),
    (("male", "mail"), "too seldom met to tell"),
    (("sale", "sail"), "too seldom met to tell"),
    (("tale", "tail"), "put right too seldom to be worth it"),
    (("wait", "weight"), "wrong too often"),
    (("principal", "principle"), "too seldom met to tell"),
    (("affect", "effect"), "not the same sound, and wrong too often"),
    (("accept", "except"), "not the same sound"),
    (("plain", "plane"), "put right too seldom to be worth it"),
    (("night", "knight"), "put right too seldom to be worth it"),
    (("flower", "flour"), "put right too seldom to be worth it"),
    (("sight", "site"), "\"site\" is far commoner now than in the books"),
    (("steal", "steel"), "put right too seldom to be worth it"),
    (("waste", "waist"), "put right too seldom to be worth it"),
    (("board", "bored"), "wrong too often"),
    (("course", "coarse"), "wrong too often"),
    (("role", "roll"), "too seldom met to tell"),
    (("stare", "stair"), "too seldom met to tell"),
    (("fair", "fare"), "put right too seldom to be worth it"),
    (("great", "grate"), "next to never mixed up"),
    (("higher", "hire"), "\"hire\" is used otherwise now"),
    (("pause", "paws"), "wrong too often"),
    (("rain", "reign", "rein"), "put right too seldom to be worth it"),
    (("red", "read"), "\"read\" as it is said now is not \"red\""),
    (("root", "route"), "too seldom met to tell"),
    (("soul", "sole"), "wrong too often"),
    (("stake", "steak"), "too seldom met to tell"),
    (("toe", "tow"), "too seldom met to tell"),
    (("vain", "vein"), "put right too seldom to be worth it"),
    (("lessen", "lesson"), "too seldom met to tell"),
    (("idle", "idol"), "too seldom met to tell"),
    (("heal", "heel"), "too seldom met to tell"),
    (("lead", "led"), "\"lead\" is said two ways"),
    (("loan", "lone"), "too seldom met to tell"),
    (("manner", "manor"), "wrong too often"),
    (("pain", "pane"), "put right too seldom to be worth it"),
    (("profit", "prophet"), "too seldom met to tell"),
    (("sell", "cell"), "\"cell\" is far commoner now than in the books"),
    (("serial", "cereal"), "hardly met in the books"),
    (("shore", "sure"), "not the same sound for most"),
    (("stationary", "stationery"), "too seldom met to tell"),
    (("suite", "sweet"), "wrong too often"),
    (("time", "thyme"), "hardly met in the books"),
    (("wave", "waive"), "too seldom met to tell"),
    (("wine", "whine"), "put right too seldom to be worth it"),
    (("wrap", "rap"), "too seldom met to tell"),
    (("yoke", "yolk"), "hardly met in the books"),
    (("aunt", "ant"), "put right too seldom to be worth it"),
    (("ball", "bawl"), "put right too seldom to be worth it"),
    (("band", "banned"), "hardly met in the books"),
    (("base", "bass"), "put right too seldom to be worth it"),
    (("beach", "beech"), "too seldom met to tell"),
    (("berry", "bury"), "too seldom met to tell"),
    (("born", "borne"), "put right too seldom to be worth it"),
    (("bread", "bred"), "put right too seldom to be worth it"),
    (("build", "billed"), "too seldom met to tell"),
    (("capital", "capitol"), "too seldom met to tell"),
    (("ceiling", "sealing"), "too seldom met to tell"),
    (("chews", "choose"), "hardly met in the books"),
    (("council", "counsel"), "put right too seldom to be worth it"),
    (("creek", "creak"), "too seldom met to tell"),
    (("days", "daze"), "put right too seldom to be worth it"),
    (("die", "dye"), "put right too seldom to be worth it"),
    (("fir", "fur"), "too seldom met to tell"),
    (("flew", "flu", "flue"), "hardly met in the books"),
    (("foul", "fowl"), "too seldom met to tell"),
    (("find", "fined"), "put right too seldom to be worth it"),
    (("gate", "gait"), "wrong too often"),
    (("hall", "haul"), "wrong too often"),
    (("heir", "air"), "put right too seldom to be worth it"),
    (("holy", "wholly"), "wrong too often"),
    (("horse", "hoarse"), "wrong too often"),
    (("in", "inn"), "one of them is far too common to be taken for the other"),
    (("I", "eye"), "one of them is far too common to be taken for the other"),
    (("be", "bee"), "one of them is far too common to be taken for the other"),
    (("not", "knot"), "one of them is far too common to be taken for the other"),
    (("but", "butt"), "one of them is far too common to be taken for the other"),
    (("or", "oar", "ore"), "one of them is far too common to be taken for the other"),
    (("we", "wee"), "one of them is far too common to be taken for the other"),
    (("him", "hymn"), "one of them is far too common to be taken for the other"),
    (("so", "sew", "sow"), "one of them is far too common to be taken for the other"),
    (("been", "bean"), "one of them is far too common to be taken for the other"),
    (("do", "due", "dew"), "one of them is far too common to be taken for the other"),
    (("we'll", "wheel", "well"), "one of them is far too common to be taken for the other"),
)

# What is written down. With less asked of a place (3 meetings, 2 times, 4 times) the
# file is three times the size and puts right about five mix-ups in a hundred more; these
# keep it at half a megabyte, a tenth of which is the list of the books.
ROW = 15            # a place met fewer times than this in all is not written down
SAYS = 4.0          # nor one that favours no word of the set over another by this much
OTHERWISE = 8.0     # nor a wider one that says the same as the narrower, to within this


def index(path: str) -> dict:
    """{number: (title, author, whether it is in English)} from the mirrors' list of all
    the books, GUTINDEX.ALL: a book fetched from a mirror often has no heading of its
    own to say what it is."""
    listed, now = {}, None
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", "replace").replace("\r\n", "\n")
    for line in text.split("\n"):
        entry = re.match(r"^(\S.*?)\s{2,}(\d+)[A-Z]?\s*$", line)
        if entry:
            now = int(entry.group(2))
            title, _, author = entry.group(1).strip().rpartition(", by ")
            listed.setdefault(now, [title or author, author if title else "", True])
        elif now is not None and line.startswith(" ") and line.strip():
            if "[Language:" in line and "English" not in line:
                listed[now][2] = False
        elif not line.strip():
            now = None
    return {number: tuple(entry) for number, entry in listed.items()}


_PLAIN = frozenset("the and of to a in that it was he".split())


def books(folder: str, listed: dict = None):
    """(number, title, author, the paragraphs) of each English book in the folder."""
    listed = listed or {}
    for name in sorted(os.listdir(folder), key=lambda n: (len(n), n)):
        if not re.fullmatch(r"\d+\.txt", name):
            continue
        number = int(name[:-4])
        with open(os.path.join(folder, name), "rb") as f:
            text = f.read().decode("utf-8", "replace").replace("\r\n", "\n")
        head = text[:4000]
        title = re.search(r"^Title:\s*(.+)$", head, re.M)
        author = re.search(r"^Author:\s*(.+)$", head, re.M)
        tongue = re.search(r"^Language:\s*(.+)$", head, re.M)
        title = title.group(1).strip() if title else listed.get(number, ("", "", True))[0]
        author = author.group(1).strip() if author else listed.get(number, ("", "", True))[1]
        if (tongue and tongue.group(1).strip() != "English") or not listed.get(number, ("", "", True))[2]:
            continue
        start = re.search(r"^\*\*\* ?START OF.*$", text, re.M)
        finish = re.search(r"^\*\*\* ?END OF.*$", text, re.M)
        body = text[start.end() if start else 0:finish.start() if finish else len(text)].replace("_", "")
        words = re.findall(r"[a-z]+", body[:200000].lower())
        if len(words) < 2000 or sum(word in _PLAIN for word in words) < 0.15 * len(words):
            continue                      # not a book in English, whatever it says of itself
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body)]
        yield (number, title or "(no title in the file)", author,
               [p for p in paragraphs if len(p) > 40 and not p.isupper()])


def count(shelf: list) -> dict:
    """{set: [how often each word was met, {place: how often each stood there}]}. A place
    met fewer than ROW times in all is dropped at once: there are millions of those."""
    sets = {}
    for words in soundalike.SETS:
        entry = [[0] * len(words), {}, words, [w.lower() for w in words]]
        for word in entry[3]:
            sets.setdefault(word, entry)
    for _, _, _, paragraphs in shelf:
        for paragraph in paragraphs:
            names = [soundalike.END] + [part[0] for part in soundalike.pieces(paragraph)]
            if names[-1] != soundalike.END:
                names.append(soundalike.END)
            for at, name in enumerate(names):
                entry = sets.get(name)
                if entry is None:
                    continue
                which = entry[3].index(name)
                entry[0][which] += 1
                tally = entry[1]
                for kind, key in soundalike.places(names, at):
                    key = "%d%s %s" % (which, kind, key)       # one number to a key: far less room
                    tally[key] = tally.get(key, 0) + 1
    counted = {}
    for entry in {id(e): e for e in sets.values()}.values():
        rows = {}
        for key, times in entry[1].items():
            row = rows.get(key[1:])
            if row is None:
                row = rows[key[1:]] = [0] * len(entry[2])
            row[int(key[0])] = times
        entry[1] = None
        counted[entry[2]] = [entry[0], {key: row for key, row in rows.items() if sum(row) >= ROW}]
    return counted


def table(words: tuple, totals: list, met: dict):
    made = soundalike._Counts(words, tuple(totals))
    made.met = {key: tuple(row) for key, row in met.items()}
    return made


def says(counts, key: str) -> float:
    """How strongly a place favours some word of the set over another, at the most."""
    most = 0.0
    for a in range(len(counts.words)):
        for w in range(len(counts.words)):
            if a != w:
                how, seen = soundalike.ratio(counts, key, a, w)
                if seen:
                    most = max(most, how)
    return most


def thin(words: tuple, totals: list, met: dict) -> dict:
    """The places worth writing down: met often enough, and saying something. A place
    left out is one of which nothing is known, which is how it is then treated.

    The two words before (LL), the two after (RR) and the two it stands between (B) are
    only written down where they change what the one word next to it says, or what the
    two sides say together, by OTHERWISE times or more: most of them only say it again."""
    if min(totals) < 20:
        return {}                         # a word hardly met at all: nothing to go by
    full = table(words, totals, met)
    pairs = [(a, w) for a in range(len(words)) for w in range(len(words)) if a != w]
    kept = {}
    for key, row in met.items():
        if sum(row) < ROW or says(full, key) < SAYS:
            continue
        kind, _, rest = key.partition(" ")
        if kind != "L" and kind != "R":
            if kind == "B":
                left, right = rest.split(" ")
                narrow = ["L " + left, "R " + right]
            else:
                narrow = [kind[0] + " " + (rest.split(" ")[1] if kind == "LL" else rest.split(" ")[0])]
            for a, w in pairs:
                without = 1.0
                for near in narrow:
                    without *= soundalike.ratio(full, near, a, w)[0]
                with_it = soundalike._wider(full, key, without, False, a, w)[0]
                if with_it >= OTHERWISE * without or without >= OTHERWISE * with_it:
                    break
            else:
                continue                  # it changes nothing much, whichever two words are weighed
        kept[key] = row
    return kept


def write(path: str, counted: dict, shelf: list) -> int:
    lines = ["# How often each word of a sound-alike set stood in each place: see soundalike.py.",
             "# Made by scripts/make_soundalike_data.py from these books of Project Gutenberg's",
             "# (number, title, author), all in the public domain in the United States:"]
    lines += [f"#   {number}  {title}  ({author})" if author else f"#   {number}  {title}"
              for number, title, author, _ in shelf]
    lines.append("# A line that starts with = names a set and says how often each word was met;")
    lines.append("# under it, each place (L the word before, R after, LL and RR two, B between two).")
    for words in soundalike.SETS:
        totals, met = counted[words]
        kept = thin(words, totals, met)
        if not kept:
            continue
        lines.append("= " + " ".join(words) + "\t" + " ".join(map(str, totals)))
        lines += [key + "\t" + " ".join(map(str, kept[key])) for key in sorted(kept)]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.getsize(path)


def measure(shelf: list) -> None:
    global ROW
    kept_back = [book for n, book in enumerate(shelf) if n % 5 == 4]
    ROW = round(ROW * 0.8)                # four fifths of the books: four fifths of the meetings
    counted = count([book for n, book in enumerate(shelf) if n % 5 != 4])
    tables = {}
    for words in soundalike.SETS:
        totals, met = counted[words]
        made = table(words, totals, thin(words, totals, met))
        for word in words:
            tables.setdefault(word.lower(), made)
    wheres = ("before", "after", "")
    figures = {}          # set -> where -> [as written, wrongly changed, swapped in, put right, made another]
    for _, _, _, paragraphs in kept_back:
        for paragraph in paragraphs:
            names = [soundalike.END] + [part[0] for part in soundalike.pieces(paragraph)]
            if names[-1] != soundalike.END:
                names.append(soundalike.END)
            for at, name in enumerate(names):
                counts = tables.get(name)
                if counts is None or not counts.met:
                    continue
                lower = [w.lower() for w in counts.words]
                mine = lower.index(name)
                # Only the two words either side are ever looked at: so only those are handed over.
                low = max(0, at - 2)
                near, here = names[low:at + 3], at - low
                for where in wheres:
                    # A word before a pause is tried with nothing known beyond the two
                    # words after it, as it would be; and so on.
                    tally = figures.setdefault(counts.words, {}).setdefault(where, [0, 0, 0, 0, 0])
                    tally[0] += 1
                    tally[1] += soundalike.decide(counts, near, here, where) is not None
                    for other in range(len(lower)):
                        if other == mine:
                            continue
                        swapped = near[:here] + [lower[other]] + near[here + 1:]
                        chosen = soundalike.decide(counts, swapped, here, where)
                        tally[2] += 1
                        tally[3] += chosen is not None and chosen[0] == mine
                        tally[4] += chosen is not None and chosen[0] != mine
    print("books counted: %d, kept back: %d" % (len(shelf) - len(kept_back), len(kept_back)))
    print("%-28s %7s | %-21s | %-21s | %-21s" % ("set", "met", "last before a pause", "first after a pause",
                                               "anywhere else"))
    print("%-28s %7s | %-21s | %-21s | %-21s" % ("", "", "wrong/1000  put right", "wrong/1000  put right",
                                               "wrong/1000  put right"))
    sums = {where: [0, 0, 0, 0, 0] for where in wheres}
    for words in soundalike.SETS:
        if words not in figures:
            continue
        line = "%-28s %7d" % (" ".join(words), figures[words]["before"][0])
        for where in wheres:
            n, wrong, swapped, right, another = figures[words][where]
            line += " | %9.1f  %8.0f%%%s" % (1000 * wrong / max(n, 1), 100 * right / max(swapped, 1),
                                           " !" if another else "  ")
            for i, value in enumerate(figures[words][where]):
                sums[where][i] += value
        print(line)
    line = "%-28s %7d" % ("all of them", sums["before"][0])
    for where in wheres:
        n, wrong, swapped, right, another = sums[where]
        line += " | %9.2f  %8.0f%%  " % (1000 * wrong / max(n, 1), 100 * right / max(swapped, 1))
    print(line)


def numbers(path: str) -> list:
    """The numbers of the books a file of counts says it was made from."""
    found = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                book = re.match(r"#   (\d+)  ", line)
                if book:
                    found.append(int(book.group(1)))
                elif not line.startswith("#"):
                    break
    except OSError:
        pass
    return found


def main() -> None:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args, listed, skip = [], {}, False
    for at, arg in enumerate(sys.argv[1:], 1):
        if skip:
            skip = False
        elif arg == "--index":
            listed, skip = index(sys.argv[at + 1]), True
        elif not arg.startswith("--"):
            args.append(arg)
    if "--numbers" in flags:
        print(" ".join(map(str, numbers(soundalike.DATA))))
        return
    if not args:
        sys.exit(__doc__)
    if "--tried" in flags:
        soundalike.SETS = soundalike.SETS + tuple(words for words, _ in TRIED)
    shelf = list(books(args[0], listed))
    shipped = set(numbers(soundalike.DATA))
    if shipped and "--any" not in flags:
        shelf = [book for book in shelf if book[0] in shipped]
    if "--measure" in flags:
        measure(shelf)
        return
    out = args[1] if len(args) > 1 else soundalike.DATA
    size = write(out, count(shelf), shelf)
    print("%d books counted; %s written, %.0f kB" % (len(shelf), out, size / 1000))


if __name__ == "__main__":
    main()

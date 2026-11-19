# Changelog

## Unreleased

- **The sound sent to another computer is packed, and you choose how.** It used to go as
  it is, 32 kB for each second of speech. Now it goes as FLAC, which halves it and gives
  back exactly what was heard. **Sound sent**, in Settings under the other computer's
  address, also offers Opus, about a tenth of the size for a slow or metered connection
  with a little of the sound lost, and Raw, as before. Nothing more is installed for it.
  A computer with an earlier version is sent the sound raw, so the two need not be
  updated together, and Settings says when that is happening.
- **A computer that shares its recogniser can be kept to one network.** Where it is on
  more than one, Settings shows **Reachable from** under "Let other computers use this
  one": every network this computer is on, as before, or one of them by name, such as
  the home network or a VPN. It then answers there alone and shows the address to give
  to the others. It follows that address if it changes, and if the computer isn't on
  that network it answers nobody, and says so, until it is.
- "No comma after Hello or Hi" knows more greetings: "Greetings Dave", "Hello there
  Dave", "Welcome Dave", "Kia ora Dave" and "G'day Dave" lose the comma too. ("He sends
  his greetings, Dave" and "You're welcome, Dave" keep theirs.)
- "No comma after Hello or Hi" now also works further on in a sentence: "so if I say
  hello Jill and I say hello Peter" used to keep both commas, because the greeting had to
  start the sentence. A comma before a name that begins something new stays, as in "I
  said hello, Bob said goodbye", and so does one after a word that is also a time of
  day, as in "I saw her this morning, Bob".
- **The key for sharing a recogniser can be changed.** "New key…", beside "Copy key" in
  Settings, makes another in its place, after asking. Nobody is answered with the old
  one from then on, so a key that was given out can be taken back.
- **Windows: the installer can fetch its own Python.** On a PC with no Python that will
  do (none, or only an old one), it now asks "Fetch it now?" and, on yes, fetches Python
  3.14 as the Python Software Foundation publishes it into the install folder: about
  15 MB to download, 50 MB on disk. Nothing else on the PC is changed, a Python that is
  already there is left as it is, its signature is checked before it is used, and
  uninstalling removes it. `LS_FETCH_PYTHON` (1 or 0) answers for an install with
  nobody at the keyboard.
- Windows: an update no longer stops with "Python wasn't found" when the install's own
  Python still runs.
- **A small computer needs no speech model of its own.** One with little disk space, or
  too slow to recognise speech, can leave all the listening to another computer. **The
  installer now asks whether to download the speech models**: answer no, then tick "Use
  another computer" in Settings. That is about half a gigabyte on Linux and 600 MB on
  Windows, where an ordinary install is twice that. It asks once, and an update keeps
  the answer. A model can still be installed later, from Settings: the first to arrive
  is put to use straight away, and a Parakeet brings the Small model it needs with it.
  It used to need a model all the same: the installer stopped without one, and the
  program let nothing through to the other computer until one had loaded. With no model here, "wake up" is listened for on the other computer too, so
  **Listen for "wake up" there too** is ticked and greyed, and says why; with a model
  here it is yours to set, and unticked to begin with. If the other computer can't be
  reached, nothing is heard, and the tray icon and Settings say so: each phrase is tried
  twice first, and the other computer is asked again five seconds later.
- **"Redo that."** It does again what "undo that" has just taken back: the program's
  own Redo, in Word, Outlook, Writer, Thunderbird and Visual Studio Code. In a box that
  is typed into it is the key for it: Ctrl+Y on Windows, Ctrl+Shift+Z on Linux. In
  Kate, where "undo that" takes back the last phrase, it puts that phrase back. "Redo"
  and "redo it" do the same. It has its own line in Settings, under Editing, beside
  "Undo that". In a sentence it is only words: "I will redo that section" is typed.
- **"Scratch that" after "select" or "correct" puts the old words back.** A phrase said
  over selected words takes their place. "Scratch that" then took the phrase away and
  left nothing where the words had been. Now they come back, selected as they were, so
  they can be said again straight away; after "correct" the cursor still goes back to
  its place once they have been. A space that was taken out beside them, and a capital
  given to the next word, are put right too. It is the same for words selected by
  hand. In Writer they come back just as they were, bold and all. In a box that is
  typed into they are typed again, which is done for words on one line.
- A shortcut can type its text and then press a key: write the text, and under it, on
  a line that begins with a space, `keys: enter`. (A `\n` in a text was never an Enter:
  nothing is escaped, so that a Windows path can be written as it is.)
- **The spelling box hears letters better, and sooner.** It is now heard by the Medium
  Whisper model where that is installed (loaded when the box is first used, let go ten
  minutes after), told to expect letters, through a short listening window. Over the
  alphabet and a few "B as in bravo"s in three voices that was 88 of 105 right at 0.7
  seconds each, where it had been 72 at 1.1 seconds. Letters that sound alike (B, D, E,
  G, P, T, V) are still the ones missed: for those, "B as in bravo" now goes by the
  word, whatever the letter was heard as, even where the letter was heard as words
  ("We are in Bravo" is how a recogniser once wrote it).
- **And the model you dictate with hears the spelling box as well.** It knows your
  voice and is the better at whole words: told to expect letters, the other wrote
  "dumb" for "done". So a word of command ("done", "cancel", "backspace", "start again")
  goes by your own model, letters go by the one that is best at letters, and where
  that one wrote nothing the box knows, yours is taken. The two together got 117 of 140
  letters and words right in four voices, where the one alone got 111. "In" and "an"
  said by themselves are the letter N.
- **The spelling box keeps up on a slower computer.** The Medium model is the best at
  letters and the slowest over them, and on some computers each letter was a wait. How
  long it takes is now measured as the box is used, over three letters. Where it takes
  more than a second at its quickest, the Small model hears the box from then on,
  beside the model you dictate with: 84 of 102 letters and words right where Medium
  got 89, in a third of the time (on a laptop where Medium made each letter a wait of
  two seconds, three quarters of a second).
  What was found is remembered, and written in the log. The model is also loaded as
  the box opens, not when the first letter has been said, and it follows one way of
  writing a letter, not five, which was a sixth quicker and no worse. (A shorter
  listening window was tried too, and cost too many letters to be worth it.)
- In Settings, the mouse wheel scrolls the page when the pointer passes over the My
  words box or the My shortcuts and commands box, where it used to stop and scroll the
  box. Click into a box and the wheel is that box's.
- **"Click OK".** A new option under Other programs in Settings: say "click" and the
  name that a button, a link, a tick box, a tab or a menu shows, and it is pressed.
  The window in front is asked what it has through the desktop's accessibility service,
  and the one you named is pressed through the same service: no mouse is moved. If
  nothing there has the name, the words are typed as words. Off to begin with.
- **"What can I say?" can be narrowed by voice.** What you say while its Find box has
  the keyboard goes into the box: say "select" and the list shows what has to do with
  selecting. "Scratch that", "undo that", "select all" and the spelling box work there.
- On Windows, a window of this program's own that is opened by voice now takes the
  keyboard. It came up, but the keyboard stayed with the program that had it, so what
  was typed or said went there and not into the window.
- **Commands of your own.** A line under **My shortcuts and commands** in Settings can
  do something where a shortcut types something: `new tab = keys: ctrl+t` presses keys,
  `my notes = open: ~/notes.txt` opens a file, a folder or a web page, and `build it =
  run: make -C ~/project` starts a program. Further lines under it are further steps,
  with `wait: 2` to give a program time and `type:` to type a text. They are said by
  themselves, word for word, like a shortcut, and "What can I say?" lists them.
- **Running programs is off until you tick "Let my own commands run programs".** Only
  what you wrote is run: nothing you say is passed on, and no shell reads the line. A
  command that runs a program has to be two words or more, a notice says what was run,
  and a command that begins with `ask first` waits for you to say "yes".
- **Commands only.** A tick box beside that list, for using the program for voice
  commands and not for dictation: ticked, nothing you say is typed, and only commands
  are acted on, yours and the program's. It is chosen in Settings and kept; nothing that
  is said switches it. The tray icon shows a C while it is ticked.
- **The model you choose does all the listening, "wake up" included.** It used to be
  the Small Whisper model that listened for "wake up", whatever you had chosen. A
  Parakeet answers several times sooner (about a tenth of a second against a second, on
  the computer it was measured on), heard a set of made-up voices saying "wake up" as
  reliably, and was no more often woken by other phrases or by noises; and a model
  trained on your voice is the one that listens. There is nothing to tick: it is one
  rule. With another computer doing the recognising and "wake up" listened for there,
  the same holds; a computer there with an earlier version carries on with its Whisper.
- With a Whisper model chosen, only that model is loaded: it does everything. With a
  Parakeet chosen, Small is still kept beside it for the spelling box and the short
  second listen for punctuation, which lean on a hint that a Parakeet can't be given.
- Source code in C and C++ files, with a Parakeet chosen, is heard by the Medium Whisper
  model where it is installed: it leans most on its hint, the names in the file. Medium
  is loaded when code is first dictated and let go ten minutes after the last of it.
  Without Medium, Small does it as before.
- "C plus plus" is typed C++. Parakeet Unified writes it as "C ??", two question marks,
  which were taken for the end of a question and dropped: only "C" was typed, and the
  next word got a capital. Parakeet v2 writes the words, which are now put right too.
  The same for g++, clang++ and Notepad++.
- **A phrase no longer takes up to twenty seconds to be acted on when the room gets
  louder.** The end of a phrase is the pause after it, and a pause was sound below what
  the room had been measured to be. If the room got louder after you began (a fan
  coming on, a microphone that turns itself up when the talking stops), that pause never
  came: the program went on listening to its limit of twenty seconds before doing
  anything with what you had said. Now sound that falls far below your voice, and stays
  level as a fan or a hiss does, also ends the phrase, and is taken as the room from
  then on. Talking that goes soft still rises and falls, and is kept as talking. The log
  says when a phrase ended this way, or at the limit.
- **And where the room's noise rises and falls** (a fan that roars, a keyboard, wind on
  the microphone), so that no pause shows at all, the voice itself is watched: a voice
  has a pitch and such a noise has none. When a voice has been heard in a phrase and
  then not for a second and a quarter, the phrase is over, though the sound goes on.
  When a voice starts in the middle of the room's noise, the noise before it is left
  out. And a phrase that ran to the limit with no voice in it at all is taken as the
  room, which stops such a noise from starting one twenty-second phrase after another.
  Measured on recorded sentences with a noise starting as the speaker did: acted on
  about two seconds after the last word, where it had been about sixteen. Dictating in
  a whisper is listened to as before: nothing is cut for want of a voice that was never
  there.
- **And where what is left is flat and has a pitch of its own** (a fan, an electrical
  hum), which neither of those two catches, it is the flatness that gives it away:
  talking rises and falls with every syllable, and of ten thousand one-second stretches
  of recorded sentences not one was flat. A second of flat sound after something
  clearly louder ends the phrase. A sound that is flat from its start for two seconds is
  no phrase at all: nothing of it is taken down, it is the room from then on, and while
  the room is flat like that a voice need only be a little louder than it to be heard.
  A long "ummm" is not mistaken for it. Measured on recorded sentences with such a hum
  coming on as the speaker began, at a quarter and at half the loudness of the voice:
  acted on under a second after the last word, where it had been fifteen.
- On Windows, what a command of your own opens or runs now comes to the front. Windows
  keeps a program that isn't in front from putting a window there, and this one lives in
  the tray: a folder opened by voice opened behind the other windows.
- On Windows a command of your own that presses keys now presses them as a keyboard
  does: each key with its place on the keyboard, one after another. Sent all at once by
  number alone, Alt+F4 was taken no notice of. The log says which program the keys went
  to, and a notice says so if Windows wouldn't take them.

## 0.6.0

After updating to this version, these are left for you to do by hand:

- **Another computer doing the recognising: both computers need this version.** The
  way the two talk has changed, so a computer with an earlier version is told to
  update, and Settings says under the address which of the two it is. Until both are
  updated, each does its own listening.
- **Thunderbird: add the add-on again from its file.** In Thunderbird choose Add-ons
  and Themes, the gear, Install Add-on From File, and pick
  `linux-speaking-thunderbird.xpi` in the install folder. Then open a new message. The
  add-on from an earlier version is no longer answered, and nothing is typed into
  Thunderbird until the new one is in. The tray icon's tip says so while the old one
  is asking.
- **Visual Studio Code: close it and open it again**, so that it loads the new
  extension.
- **LibreOffice: if it was open while you updated, close it once**, for ten seconds or
  so. Its new extension goes in while it is closed, and a notice says when Writer is
  ready.

For newcomers:

- The first time it starts, a "Getting started" window opens in place of Settings. It
  shows whether the microphone hears you, says what to do in four steps, and has a box
  to try dictating into before any other program is involved. It opens by itself that
  once only, and "Getting started" in the tray icon's menu opens it again. An install
  from an earlier version is not shown it.
- That window has a button that downloads Parakeet Unified, the recommended speech
  model, and switches dictation to it when it has arrived. On Windows it also asks
  which key, if any, should switch dictation on and off, and whether to start when you
  sign in.
- "What can I say?", in the tray icon's menu or said aloud, opens a list of everything
  that can be said, with a box to narrow it down. It says which are switched off.
- A click on the tray icon wakes dictation when it is asleep or off, and switches it off
  when it is awake.
- The tray icon has a shape for each state as well as a colour: a "z" when asleep, and
  a grey disc with a yellow "!" when no speech model could be loaded.
- Where the desktop has no system tray, as GNOME as it comes has none, a small window
  stands in for the icon, with the menu's entries as buttons. It does not take the
  keyboard when it appears.
- Dictation is English only, and the README now says so in its first lines. It also
  says at the top that it runs on Windows.
- The README is short: what it is, what you need, installing, the first minute and the
  commonest problems. The rest is in pages under `docs/`.

Telling you what is wrong:

- When you speak and no program that can be typed into is in front, a notice says so
  and names the programs that would do, at most once a minute. The tray icon's tip says
  "(nothing to type into)" after the words.
- The tip says where your words will go only while dictation is awake, and looks every
  few seconds, so it is no longer out of date. Asleep, it says: Dictation: Asleep. Say
  "wake up" to dictate.
- A microphone that can't be opened: a notice gives the reason in plain words, and on
  Windows names the privacy switch. The notice "Awake" is no longer shown when nothing
  is listening.
- A microphone that stops by itself, as when a headset is unplugged: a notice says so,
  and dictation comes back asleep by itself when the microphone works again. It is
  tried every two seconds for three minutes, and is left for you to try after three
  stops within a minute.
- No speech model, or one that won't load: the state is "No speech model", with what to
  do, where it said "Loading…" for ever. It tries again by itself once a model has been
  installed.
- A model chosen in Settings that won't load: dictation stays with the one in use, the
  choice goes back to it, and a notice says so.
- Things that stay wrong are listed in the tray icon's tip and at the top of Settings,
  each with what to do: Thunderbird's add-on being an older one, the desktop refusing
  key presses, the port for Thunderbird being in use, a part missing for Word and
  Outlook, a microphone that stopped, other computers not being able to use this one
  for recognition.
- "Open the log", in the tray icon's menu, shows what the program has written down
  since it started. "Copy all" there takes it for a report, with the version and the
  model in use. As ever, nothing that was said is in it: a notice is written there
  without its words, as "Selected: (12 characters)".
- A click on the tray icon, the key or "toggle" does not wake dictation while a reading
  or a voice-test recording has the microphone: a notice says to pause or stop the
  recording first.
- A Writer extension that can't be put into LibreOffice is reported once, with the
  reason, where it was tried every five seconds with nothing said. A notice says
  "Writer is ready" when it is in.
- On Windows, a key that Windows won't give, because another program has it, is said
  beside the chooser and at the top of Settings.
- If something goes wrong with a phrase inside the program, a notice says that it was
  not typed.

Dictating and commands:

- Notices for commands that leave nothing to see: "Selected:" and the words after
  "select" or "correct"; the program's name and "can't do" where the program in front
  has no such command; and "Say a number, 1 to 3, or "cancel"." when the words are in
  several places.
- While numbers show, a single word that is neither a number nor a command is no longer
  typed into the document: it is most likely a number misheard, so the numbers stay and
  a notice asks again. Two words or more take the numbers away and are typed, as they
  always were. "Second", "the second one", "2nd" and "three please" pick a number, and
  "none" or "neither" takes the numbers away.
- Commands take "please" at either end, and an "um", "uh", "er", "erm", "oh" or "OK" in
  front when two or more words follow: "OK, scratch that". A "no" in front is passed
  over only where you paused after it, which the recogniser writes as a comma: "No,
  scratch that". "And" is not passed over: "And select all" is typed.
- "The" may be said or left out: "go to the beginning of the line", "go to the end of
  the document". A phrase that ends with "the" is the start of a sentence, and is not
  taken for a command: "New paragraph. The" keeps its "The". "Down the line" is typed
  too. (What follows "select" or "correct" is another matter: "select the" still looks
  for a "the".)
- More ways of saying commands: "capitalize that", "deselect that", "delete that line",
  "select that line", "comment that line", "indent that line", "press the tab key",
  and "newline" as one word, said by itself.
- "Tab 3", "tab three times" and "tab twice" press the Tab key that many times, 20 at
  most.
- Counts can be said in words up to ninety-nine: "go to line forty two". A count bigger
  than a command takes is taken as the most it takes: "backspace 100" removes 99.
- A command said twice in one breath, "scratch that, scratch that", is done once.
- A sentence that begins with "Select" or "Correct" is typed, and not taken for the
  command, when the recogniser wrote punctuation straight after that word or more than
  eight words follow. "Select Save." is still the command where "save" is near the
  cursor, and the notice says what was selected.
- "Select" finds more of what is there: "1,250" by "1250", "21" by "twenty one", "U.S."
  by "US", "p.m." by "pm", "Dr." by "doctor", "colour" by "color", "dog's" by "dogs" and
  "café" by "cafe". Visual Studio Code and Thunderbird look for exactly the words. They
  find "U.S." and "p.m." when the recogniser writes what you said with the dots, but not
  when it writes "US", and they don't find a word that differs by an apostrophe or an
  accent.
- "Delete last word" takes a whole price, number or address: after "costs $25.50" it
  leaves "costs".
- "Cap that" keeps acronyms and words like "iPhone": "the NASA report" becomes "The
  NASA Report". That is so in Writer, Kate, typed-into boxes, Visual Studio Code and
  Thunderbird. In Word it is still Word's own title case, which lowers them.
- Asleep, "make up", "woke up", "take up", "walk up" and "wake me up" no longer wake it.
  "Wake up" misheard as "wake app", "wake op" or "weak up" still does.
- Commands for the app's own windows: "what can I say", "open dictation settings",
  "show microphone level" and "close that window". They are one tick box, on to begin
  with. "Close that window" with none of the app's windows open is typed as words.
- "Keep the full stop or question mark the recogniser writes at the end of a phrase", a
  new tick box under Formatting, off to begin with. It suits short messages said in one
  go.
- Still not done: "redo" is not a command; a tab can't be said inside a phrase, only by
  itself; and words put in front of a sentence that is already there leave that
  sentence's capital where it was. Two phrases still come out wrong: "A colon the first
  option", at the start of a phrase, keeps the word "colon", and "The house number sign
  fell off" types a "#".

Punctuation and capitals:

- A sum of money is always typed in figures. The recognisers write "one hundred and
  twenty dollars" as $120 but leave "a hundred and fifty dollars" in words, so the same
  kind of thing came out two ways from one sentence to the next. Now both are $120 and
  $150, and so with cents ($20.50), thousands ($2,500), millions ($1.5 million) and
  "twenty or thirty dollars" ($20 or $30). Whose dollars is kept, in two letters: NZ$100,
  AU$300, US$50, CA$20. Euros are written €100. Pounds are written £100 where they are
  said to be money ("UK pounds", "British pounds", "pounds sterling"), with pence after
  the point: "a hundred pounds" alone may be a weight and stays in words. A number said
  straight after a money sign is in figures too: with the 5 of "$5" selected, "six"
  makes "$6". A tick box under Formatting in Settings, on to begin with, leaves sums as
  written instead.
- The space before a dollar sign is no longer lost with a Parakeet model: "I spent $120"
  was typed "I spent$120". The models write that space as a piece by itself, and the
  library that joins their pieces into text left it out; the text is now put together
  from the pieces here.
- More punctuation can be said by name, on to begin with: "open paren" and "close
  paren", "open square bracket" and "close square bracket", "open curly bracket" and
  "close curly bracket" (or "brace"), "open single quote" and "close single quote", "em
  dash", "en dash", "forward slash", "backslash", "apostrophe", "at sign", "ampersand",
  "percent sign", "hash sign" or "number sign", "dollar sign" and "euro sign". Each has
  a tick box in Settings.
- Off to begin with, because they are everyday words too: "dash" (an en dash with a
  space either side), "slash", and "quote" with "unquote" or "end quote". "Quote" opens
  a quotation, or closes one that is open.
- A punctuation word after "a", "an", "the" or "the word" stays a word, as in "put a
  comma there" and "press the comma key". So do "colon cancer" and "at sign in".
  ("Comma key" without "the" has a comma in it.)
- After "a" or "the", these are signs all the same: a hyphen inside a word made with
  hyphens ("state hyphen of hyphen the hyphen art" gives "state-of-the-art"), and an
  opening quote or bracket whose closing one comes later in the phrase.
- "Newline" as one word inside a sentence is the word, as in "strip the trailing
  newline". Said by itself it is the command.
- A backslash has a space before it, as in "ends with \n", except inside a file path.
- "Hello. Comma. How are you?", which is how the recogniser writes a comma said after a
  pause, gives "Hello, how are you".
- The full stop of "p.m.", "U.S.", "etc." and "Ph.D." stays at the end of a phrase, and
  before punctuation that is said. What comes after it goes by what you said. If you
  only paused, the next phrase carries on in small letters: "at 3 p.m." and then "On
  Tuesday" gives "at 3 p.m. on Tuesday". If you said "full stop", the next phrase starts
  a sentence, and no second stop is typed.
- In the middle of a sentence, the first word of a phrase loses the capital the
  recogniser gave it, also when the next word has one: "I will see you" and then "Next
  Monday" gives "next Monday". A name keeps it: "Mark Jones", "in May", and a word
  that names begin with, as in "New Zealand", "Uncle Bob" and "Lake Taupo".
- An everyday word that is also a name loses that capital: "the report" and then
  "States that" gives "states that", and "Thanks" and then "Will do" gives "will do".
  Known and left: "Will Mark be there?" in the middle of a sentence keeps "Will", and
  "Windows" keeps its capital.
- "Hello, Monday works" and "Hi, OK, …" keep their comma with "No comma after Hello or
  Hi" ticked.
- No space is put after `**`, `_` or a backtick typed by hand where it opens, nor after
  a "$", "€", "@" or "\" typed by hand.
- A word spelled the American way is an everyday word with a British dictionary, and
  the other way about: "Color" in the middle of a sentence loses the capital the
  recogniser gave it.

The spelling box:

- "B for bravo" and "B as in boy" give one b, and "all caps N A S A" gives capitals.
- "Double U" is the letter W, however the recogniser writes it. Say "U U" for two of
  the letter u.
- Accented letters can be spelled, and an accent can be said after its letter: "e
  acute", "a macron".
- More signs: comma, colon, semicolon, slash, backslash, ampersand, plus, equals, hash,
  percent, dollar, asterisk, brackets, question mark and exclamation mark.

In C and C++:

- Strings keep their apostrophes and capitals: "quote don't panic quote" types `"don't
  panic"`.
- A comment is written as a sentence, with its capitals and apostrophes, and ends at a
  spoken "new line", with code after it.
- "Pipe equals" and the other operators that end in equals: `|=`, `%=`, `^=`, `&=`,
  `<<=` and `>>=`.
- "M underscore count" types `m_count`.
- "One hundred", "two hundred and fifty six", and "zero x f f" for `0xff`.
- "A and b" between two values types `a && b`, and "a or b" types `a || b`.
- "uint8_t value" and "std::string name" are two words.

Your own words and shortcuts:

- **My shortcuts**, a new box in Settings: `what is said = what is typed`, one to a
  line. Said by itself, the phrase types the text exactly as written, capitals and all,
  also at the start of a sentence: an email address stays in small letters. A line that
  starts with a space carries on the one above as a new line of it, which is how an
  address is written.
- A name in My words keeps its capital at the start of a phrase: with "Rose" listed, "I
  spoke to" and then "Rose" gives "I spoke to Rose".
- By sound, a listed name takes the place of another spelling that sounds the same,
  also one the dictionary knows: with "Sarah" listed, "Sara" becomes Sarah, and with
  "Jon", "John" becomes Jon. It goes by the consonants, the kind of the first vowel
  and the number of syllables.
- By sound, a listed name no longer takes the place of a name that only resembles it
  (Dan for Don or Dean, Tom for Tim, Mary for Maria), or swallows the word beside it.
- Two words heard for one listed word are joined: "Libre Office" becomes "LibreOffice".
  At the very start of a sentence that is done only where the first of the two is no
  everyday word.
- A listed name said by itself is put in, and so is one said after "Best wishes," or
  "Love,".
- "Hi team," and "Thanks, done." are not turned into listed names.
- Part numbers of three characters work: "MP3", "CO2", "B12".
- Everyday words are no longer turned into a part number that has the same letters and
  figures: with "A380" listed, "a 380 pound gorilla" stays as it is, and with "Win11",
  so does "we win 11 games".
- A word on the list with letters and figures in it, such as a part number ("vLR5340",
  "vLR54H20"), is now put in as you spelled it wherever the recogniser wrote the same
  letters and figures: "VLR5340", "VLR 5340", "VLR-5340", "V L R 54 H 20", or said as
  words, "V L R fifty three forty". Before, its figures were thrown away when it was
  looked for by its sound, so every such word sounded like every other: "VLR 5340" came
  out as "vLR54H20 5340".
- A word that is written with a small first letter and a capital later ("vLR5340",
  "iPhone", "eBay") keeps its small letter at the start of a sentence, where it was given
  a capital.

The app's windows:

- The About window, the README and the welcome window no longer say that nothing is
  sent anywhere, which stopped being true when another computer of your own could be
  given the recognising. They say what is true either way: nothing you say goes to the
  cloud, and there is no account or service behind the program. About then says how it
  is set now: all on this computer, or which computer of yours the sound goes to,
  encrypted. The reading window says the same of the sentences read aloud.
- In Settings a tip is shown for whatever is tabbed to, as it is for whatever the mouse
  rests on, so that the help can be read without a mouse. Alt and an underlined letter
  jumps to a group or presses a button.
- The mouse wheel no longer changes a chooser as the page scrolls past it, and the arrow
  keys open its list: a speech model is no longer loaded by scrolling. Choosing the
  model that is already in use loads nothing.
- In the app's windows the Escape key closes the window, and Enter presses the button
  that has the keyboard. Where a window asks before deleting something, "No" is the
  answer that Enter gives.
- "Start when I sign in" is a tick box in Settings, on Linux and on Windows.
- On Linux, a key of your own can switch dictation: Settings shows, under Keyboard, a
  command to bind it to in your desktop's shortcut settings, with a button to copy it.
- Only one copy of the app runs, on Linux as on Windows. Starting it again shows
  Settings.
- In the tray icon's menu, "Show level meter" is now "Microphone level…", and "Turn on"
  and "Turn off" are "Turn microphone on" and "Turn microphone off". "What can I say?",
  "Getting started" and "Open the log" are new.
- The microphone level window closes by itself after a minute with nothing heard, and
  counts down for the last fifteen seconds. Dictation is off while it is open, so
  somebody working by voice alone could not get it back.
- On Windows, "Look again" beside the microphone chooser reads the list afresh, for a
  headset plugged in later. Windows allows that only while nothing is being recorded,
  so listening stops for a moment; if the microphone can't then be opened again, that is
  said, and it is tried again. A chosen microphone that is not connected is shown as
  "(not connected now)".
- On Windows the microphone chooser shows each name whole. The names were cut off at 31
  letters ("Microphone (Realtek High Defini"), however wide the window: that is all
  Windows' simplest sound interface, the one recorded through, gives. The rest is now
  looked up from the newer interfaces. Your choice is kept as it was.
- Long lines in Settings no longer make the window wider than a small screen: what they
  said in brackets has moved to the help. Settings is never bigger than the screen, and
  the sizes of text follow the system's.
- A tick box that would do nothing as things stand is grey and says "(no effect at
  present)". It can still be reached with the keyboard, so that the help can say why.
- The reading window's instructions are in the ordinary colour of text, and are told
  apart from the sentence to read by being smaller and slanted.

Models:

- Parakeet Unified is the recommended model: the best so far, quick and with the fewest
  words wrong. Settings, the models window and the welcome window say so, and Settings
  has a "Get Parakeet Unified…" button while it isn't installed.
- In the choosers the models are named "Parakeet Unified: recommended, the best so
  far", "Parakeet v2: quick and accurate, not Whisper" and "Small: good, and quick
  enough for most computers".
- A download can be paused: "Pause" keeps what has arrived, "Carry on" goes on from
  there, and "Discard" asks first. A download that finishes, or fails, is announced
  whichever windows are open, and every window shows the same download.

The voice test, reading and training:

- The voice test's recording ends by itself when you have read the passage and been
  quiet for eight seconds. A test goes on if the window is closed, and a notice says
  when it is done. "Use it for dictation" puts the suggested model to use.
- Reading aloud: a sentence that the model twice won't take for the right one can be
  kept as you read it, with the space bar. Speaking counts as being there, so the window
  doesn't pause itself while you read.
- A text of your own to read aloud that Windows saved as "Plain Text" or "Unicode" is
  read properly.
- The reading and training windows say, when they open, if the computer has less free
  memory than a training run wants.
- Training: "Stop" while a run is still getting ready, fetching its model, stops it at
  once. The install of the training tools and the download of Parakeet v2 can be
  stopped too. A run that failed has an "Open the log" button, and says what to try. A
  run started on a system without the login service can be stopped cleanly as well.
- Training: putting the computer's clock forward no longer makes a run that is going
  look as if it had failed. A run whose notes were lost appears under "Clear stopped
  runs".

Installing and removing:

- Both installers install the Python packages from one list, `requirements.txt`, which
  allows each package's fixes but not its next big version.
- Both installers fetch the speech models with the app's own downloader, which shows
  how far it has got, carries on where it stopped, and uses the system's proxy and
  certificates. The models can be copied in by hand where the download isn't allowed.
- Both installers check that the packages and models load before they say "Done", and
  the closing lines say what was and wasn't set up.
- Both installers stop if they are run from the folder they install into, and refuse a
  folder with other things in it.
- Both uninstallers ask before removing recordings, kept noises and retrained models,
  find the install folder themselves, remove only what was installed, and say what they
  could not remove.
- An update keeps your choice about starting when you sign in. `LS_NO_AUTOSTART=1` and
  `LS_NO_START=1` install without setting it to start at sign-in, or without starting
  it now.
- Linux: the installer uses the system's Python whatever comes first on PATH, prints
  its version, and stops below 3.10. `LS_PYTHON` names another.
- Linux: it lists the system packages before asking for the password, carries on if the
  package lists can't all be refreshed, and checks disk space first.
- Linux: on a system without systemd it carries on, and the menu entry starts the
  program itself.
- Linux: after a distribution upgrade the installer rebuilds its Python packages.
- Linux: a LibreOffice from Flatpak or Snap is noticed and said to be out of reach.
- Linux: the installer no longer changes VS Code's `argv.json`. The app adds its line
  when "Dictate into other programs' text boxes" is ticked, and uninstalling takes it
  out.
- Linux: a Kate or KWrite launcher of your own is changed in place, with a copy kept,
  and put back on uninstalling.
- Linux: `scripts/launch.sh toggle` (also `wake`, `sleep`, `off`, `settings`) for a
  keyboard shortcut of your own, and `start`, `stop`, `restart`.
- Linux: uninstalling puts back the desktop's accessibility switch if the app turned it
  on, and removes extra settings added to the login service.
- Windows: the installer accepts only a 64-bit Python from 3.10 to 3.14, and says what
  it found otherwise. `LS_PYTHON` names one.
- Windows: an install outside your user folder is closed to the PC's other accounts.
- Windows: an install whose Python has been removed is set up afresh by running the
  installer again.
- Windows: the uninstaller is kept with the install and has a Start menu entry,
  "Uninstall Linux Speaking".
- Windows: the installer says whether the VS Code extension went in, and tries VS Code
  Insiders and VSCodium too.

Noises written as words:

- A noise is written with less conviction than a word that was said, and that is now
  used. One of the words Parakeet makes of a noise ("yeah", "okay", "hmm") stands by
  itself only if the recogniser was sure of it, even where the voice detector hears a
  voice, as it does in a sneeze or a sigh. A word or two of any other kind, with no clear
  speech behind it, stands only if the recogniser was sure: a model retrained on your
  own voice writes "hit", "back" or "hey" for a noise where the stock one writes "yeah".
  On recorded coughs, sneezes and laughs, what was still written fell from 9 to between
  2 and 4, for one more lost of 364 spoken one-word commands.
- **"That was a noise."** Say it when a rustle or a click has been written as a word. The
  word is taken back and the sound is kept on your computer, in `noises` in the state
  folder, so that the rules can be tried against the noises you really make. It has a
  tick box under Hearing in Settings, off to begin with, and beside it a line says how
  many sounds are kept, with buttons to open their folder and to delete them all.
- "That was a noise" leaves the words alone if another program has come to the front
  since they were written, and a notice says which program they are in. The sound is
  kept all the same.
- The voice detector that tells speech from other sounds is asked again after it fails.
  One failure used to switch it off until the app was started again; now it is given up
  only after five failures running.
- **Leave out whispering**, a new tick box under Hearing, off to begin with. A whisper
  is breath without a voice, and with this ticked a phrase that is mostly breath is left
  out before it reaches the recogniser: so something can be said under the breath without
  being written. With any model. The tray icon's tip says when a phrase was left out.
- In Settings, every voice command and punctuation word is shown in quotes, as what you
  say, so that it can be told from the settings beside it. Rest the mouse on any line
  for more about it; the four buttons for speech models each say what they do.
- For a phrase of a word or two the log now says how long it was, how much clear speech
  the detector found in it and how sure the recogniser was. No words, as ever.

Made safer:

- **Another computer doing the recognising: what is sent is now encrypted.** The sound,
  the text before the cursor and the words that come back are sealed with a key the two
  computers agree afresh for each run of phrases. That key is never sent and is then
  forgotten, so what was overheard can't be read later, even by someone who has since got
  hold of the key in Settings. It needs the `cryptography` package, which the installers
  now fetch; without it the link is not used at all, and nothing is sent in the clear.
- Each computer also proves to the other that it holds the key before any sound is sent,
  so one that merely answers at the same address is given nothing. Every answer is signed, and one that isn't is not believed:
  nothing it says is typed or obeyed. A request is good once, so one that was overheard
  can't be sent again. Both computers need this version: an older one is told to update,
  and meanwhile each does its own listening.
- Sharing a recogniser: a computer without the key can no longer use up the sharing
  computer. Eight callers are attended to at once, each has a few seconds to show that
  it holds the key, and nothing more of a request is read until it has. A long phrase
  over a slow link is then given time in keeping with its length, up to 55 seconds.
- An address for the other computer that could not be one, such as one with a space in
  it, is refused when it is entered, with "That isn't an address…". It used to be taken,
  and every phrase was then lost.
- If the other computer stalls, or something else answers at its address, the phrase is
  heard on this computer instead: after five seconds at most for the hello, and a
  minute for a phrase. The tray icon's tip says that the other computer can't be
  reached, and Settings says why under the address: "The other computer took too long
  to answer."
- **Thunderbird.** The add-on and the engine prove themselves to each other with a key
  made for your computer and built into the add-on's file, so that another person's
  program, or one that is kept apart from your files, can't pass itself off as either
  one: read what you dictate, or reach into the message you are writing. The add-on has to be installed again from the new file
  (Add-ons and Themes, the gear, Install Add-on From File); the old one is told nothing,
  and the tray icon's tip and the top of Settings say what to do.
- Thunderbird: an add-on from before the key no longer keeps Thunderbird and the app
  busy asking each other thousands of times a second. An add-on made for another key
  than this computer has now is noticed too, and the tip says so. The tip's line goes
  as soon as the right add-on connects. After the add-on has been loaded again, the
  first thing asked of it is no longer lost.
- **Thunderbird keeps nothing of the exchanges in its cache any more.** The app says so
  with every answer, and the add-on asks without caching. Before, Thunderbird kept a
  file on the disk for every exchange between the two: an older add-on asking without
  a pause made over a million of them in a day.
- **VS Code on Windows.** Before anything is sent to VS Code's extension, the link is
  checked to be yours: Windows is asked who owns it, and whether it was made by a
  program that Windows keeps apart from your own. (If Windows won't answer the second
  question, the first decides, and the log says so once.) Another account on the same
  computer could have taken the extension's name and been sent what you dictated.
- Sounds kept with "that was a noise" are for your own account only to read, and a
  folder of them from an earlier version is closed to other accounts when the program
  starts. Only the app's own sound files in that folder are counted, pruned or deleted,
  and new ones are named by a count and the time, as in
  `noise-000123-20261118T051809Z.wav`.
- Settings that are a link to a file kept elsewhere stay a link when they are saved,
  and two saves at the same moment both go through.

Put right after a review of the whole program:

- One of your own words is no longer put in place of an everyday word because it sounds
  like it: with "Dan" among them, "I'm done" stays "I'm done". It still goes in where the
  recogniser wrote a name or a word it didn't know, and by itself after a greeting or a
  sign-off ("Cheers," and then your name).
- "And do that" is words again. It was taken for "undo that".
- No space is put before a straight quote mark that closes: with the cursor between a
  pair, as programs often leave it, the words go in as "come here" and not "come here ".
- A word that is spelled out keeps its last full stop: "e.g." and "etc.".
- In C and C++, a name in the file that begins with "to", "for" or "in" is that name:
  "to string" is `to_string`, where the "to" was taken for a 2.
- On Windows, changing the look while a model is downloading no longer leaves the
  download's window behind, where a second one could start the same download or throw it
  away. The download goes on by itself, and the window made in the new look shows it.
- "Train on my voice": answering yes to fetching Parakeet v2 and then closing the window
  no longer leaves the run unstarted. It starts when the model is here.
- Reading aloud: a rest before reading a sentence is no part of it. After more than 36
  seconds of quiet the sentence was lost as "too long".
- The voice test: a second recording given up by closing the window no longer takes the
  place of the one that was kept.
- A model that is retrained while it is loaded (chosen for dictation after the run began,
  or a run that was carried on) is loaded afresh when the run ends, where dictation went
  on with the old one until the app was restarted.
- "Train on my voice" has a button to clear what stopped runs have kept, 2.4 GB or more
  each, and says how much that is.
- `uninstall.ps1` stops a training run or an install of the training tools that is under
  way before it removes the folder, leaves a folder alone that isn't Linux Speaking's,
  and says so if not everything could be removed. It asks before the recordings made
  for training go too: see "Installing and removing".
- A name the dictionary lists as a name keeps its capital in the middle of a sentence:
  "I think James said so", where it was "james" (taken for "jam" with an ending).
- Inside a phrase, a shortening's own full stop no longer gives the next word a capital:
  "the U.S. government", "at 5 p.m. tomorrow". The next word is left as the recogniser
  wrote it, with a capital or without. (After a pause, how the next phrase starts goes
  by whether "full stop" was said: see "Punctuation and capitals".)
- After the mark of a list item, a heading or a quotation at the start of a line ("- ",
  "# ", "> "), the first word gets its capital in every program, not only in VS Code.
- "Select" and "correct" find a word that has a quote mark beside it: hello in 'hello',
  boys in "the boys' toys".
- "Cap that" leaves the letter after an apostrophe small in Kate, Writer and typed-into
  boxes: "Don't Stop", where it was "Don'T Stop".
- "Delete 3 lines" removes three in Writer and in typed-into boxes, where it removed one.
  In Writer, "delete line" on an empty line takes that line away, where it took out the
  last phrase you had said. "Delete one line" and "go to line 1,250" are understood.
- One of your own words is never put in place of a command because it sounds like it:
  with "Andy" among them, "undo" is still "undo".
- In C and C++, "!=" written by the recogniser is kept, where it became "=".
- Thunderbird: "bold that" and "cap that" on the last phrase no longer leave it selected,
  where the next words took its place.
- Text with a face or other such character in it no longer throws the cursor out by one
  in Notepad and other Windows edit boxes, or "select" in a web page's text box on Linux.
- The app writes an unexpected error to its log and goes on, where it could close. A list
  of recordings saved by an editor in another encoding no longer stops the reading and
  training windows opening.
- Settings are saved whole or not at all, so a full disk can't leave half a file, and on
  Linux only your own account can read them (they may hold the keys for sharing a
  recogniser). A
  settings file with the wrong things in it gives the usual settings and the app starts.
- Reading aloud: a recording deleted by hand no longer lets the next one be kept under
  its number and so with its words; a newly chosen text of your own starts at its first
  reading.
- The voice test no longer shows fewer than no words wrong when a slip every recogniser
  made was made twice by one of them.
- Training: on Linux an install or a run that has ended is no longer shown as still
  going. An install that stopped part of the way is offered again, where the window took
  the tools for installed and every run failed. On Windows a run no longer fails when the
  window reads its notes at the moment they are written, and a model name with an accent
  in it no longer stops the trainer. The install is no longer ended by restarting the app.
- Two windows can no longer fetch the same model at once into the same folder.
- The other computer: a caller who sends a malformed key gets "wrong key" and nothing is
  written to the log; the server no longer says which version it is to a caller without
  the key.
- Thunderbird's link: a request that was given up on is not carried out when Thunderbird
  comes back to life, and Thunderbird closing is noticed sooner.
- The installer stops if it is run from inside its own install folder, as a clone made in
  the home folder under the project's name is: it copied the program into itself, and
  uninstalling deleted the clone. The README now clones into another name. The uninstaller
  leaves a folder that holds a git repository. Only your own LibreOffice counts as open.
  The line added to VS Code's `argv.json` no longer breaks the file when the last setting
  has a comment after it. The Writer extension starts on a system with no dictionary.
- On Windows, an install put somewhere other than the usual folder is found again after
  signing in, where the app started with nothing.

- "Correct *words*" selects words as "select *words*" does, for putting a mistake right
  further up without losing your place. Say what should stand there and it takes the
  place of the old words, then the cursor goes back to where it was before. "Unselect
  that" goes back as well, leaving the words as they were. Any other command in between
  leaves the cursor with the words ("space" is taken for words: it stands in their place). It works in every program dictated into. In Writer,
  Thunderbird and VS Code the cursor goes back once their extension is the one from this
  version; with an older one the words are selected, the cursor stays with them, and the
  tray icon's tooltip says so beside what it heard. (Thunderbird's add-on has to be the
  new one before anything at all is dictated there: see "Made safer".) In a text box that is typed into, the way back is by arrow keys, so a
  cursor more than 3,000 characters away stays where the new words are (300 in a program
  that takes keys one at a time), and the tooltip says that too. It can be switched off
  in Settings.
- A phrase that begins with "select" or "correct" is that command when the words after it
  are found near the cursor. When they aren't, it is now typed like anything else, so
  "Correct me if I'm wrong" and "Select the best option" are still sentences. Before, a
  "select" that found nothing typed nothing.
- Runs on Windows 10 and 11, dictating into Microsoft Word, classic Outlook and Visual
  Studio Code. `install.ps1` installs it and `uninstall.ps1` removes it.
- On Windows, a microphone chooser in Settings, and small numbers shown on screen over the
  matches for "select" in Word and Outlook.
- On Windows, the app's windows and the tray icon's menu can be given the look of
  Windows 10, Windows 7 or Windows XP, chosen under Appearance in Settings.
- On Windows, the "other programs" setting types into any text box that has the keyboard,
  such as a chat box, reading what is around the cursor through UI Automation. An empty
  box is read as empty: its hint ("Type a message") and the page around it are not taken
  for text before the cursor, so the first words get their capital and no space in front.
- The Visual Studio Code extension is packaged by a Python script, the same on Linux and
  Windows.
- "My words" in Settings: names and unusual words that get misheard. They are given to
  the recogniser as a hint, and a second listen without the hint keeps an ordinary word
  ordinary.
- On Linux, the "other programs" setting now covers VS Code's panels (an assistant's chat
  box, the terminal) and other programs built from a web browser. Their text boxes are
  read through the accessibility interface and typed into with key presses, which the
  desktop asks you to allow once. Ticking the setting switches on VS Code's
  `force-renderer-accessibility` so that its panels can be read, and a notice says to
  restart VS Code. The installer leaves VS Code's settings alone, and uninstalling takes
  the line out again.
- On Linux, dictation no longer comes back switched off after the service is restarted
  while it was on.
- A notice says when dictation is switched off, as it already did for awake and asleep.
- On Windows, Notepad and other programs with one of Windows' own edit boxes are read
  and written by messages to the box itself: the words are handed over whole, with no
  keys pressed. Sent as a burst of characters, Windows 11's Notepad wrote the last
  character of the burst for all of them, and sent as fast key presses it dropped some.
  Other programs that aren't built from a browser get key presses at about a hundred a
  second.
- On Windows, Notepad++ can be dictated into. Its editing area is asked for its text by
  message, since it offers nothing through the accessibility interface.
- "Second opinions", a tick box and a trial: each phrase is also heard by a second model,
  and by a third where the two differ, and the two that agree win. They are Small and
  Medium; if you dictate with one of those, the other one and Parakeet v2. The voice test tries
  the same three together. A computer that shares its recogniser keeps three models
  loaded for guests, so that being asked for three in turn doesn't reload them each time.
- The Distil models are no longer shown the text before the cursor. It made them lose
  their place and leave out whole sentences; without it they are as accurate as the rest.
- Words spoken over a selection are fitted to what is around it. A word double-clicked in
  Word, which takes its space with it, is replaced without the space being lost.
- On Windows the installer fetches English dictionaries, so that an ordinary word in the
  middle of a sentence loses the capital the recogniser gave it.
- "Test the models on my voice": read a passage once and see, for every installed recogniser,
  how many words it got wrong on your own voice and how long it took. The window has a
  tab for each step: reading, choosing what to try, and the results. Half of the passage
  is words easily taken for others ("better" and "beta"), and slips that every recogniser
  made alike, which were in the reading, are not counted. It also counts near misses:
  words that came out right, but that the recogniser was less than 90% sure of.
- "Question mark" said by itself after an unfinished question is typed. Whisper wrote a
  bare "?" for it, which was thrown away as no words at all.
- "Quicker recognition", a tick box: Whisper is given only as much sound as the phrase
  needs, which is three or four times quicker. A phrase that goes wrong is done again the
  usual way.
- Parakeet can be installed and chosen as the recogniser: quicker than Whisper and about
  as accurate as its Medium model, English only. The models window also offers NVIDIA's
  newer Parakeet Unified, and each of the two at full precision (2.5 GB), to try against
  the usual one in the voice test.
- In "Read aloud for training", a text read to its end can be gone through again.
- "Read aloud for training", a trial: a window that shows one sentence at a time and
  keeps the sound of each beside its text, as material for retraining a recogniser to
  one voice. Three hundred sentences come with it, or a text file of your own can be
  read. Nothing has to be pressed: it moves on when the recogniser has heard the sentence
  to its end. A sitting can be paused for a rest and carried on, and a later one begins
  where the last left off.
- In Settings, a tick box that would do nothing with the model in use is greyed, and
  says why when the mouse rests on it.
- "Wake" and "sleep" by themselves can stand for "wake up" and "go to sleep": tick
  **Wake, sleep** in Settings. The longer phrases go on working.
- The level meter window opens the microphone by itself, so it works whether dictation
  is on or off, and has the reading window's bar and colours, with each phrase judged in
  words above it. Dictation is off while it is open, and comes back as it was when it is
  closed. It no longer opens by itself when the program starts; a second start of the
  program shows Settings.
- "Train on my voice", a trial: retrains Parakeet (Unified or v2) on the sentences read aloud, from
  a window that asks for the folder, the model to start from and a name for the result.
  It learns from the sentences and from single words cut out of them, runs by itself
  for about an hour, can be stopped and carried on, tests the result on sentences
  and single words kept out of the training, and puts it among the speech models. It needs
  training tools of about 2 GB, which the window installs with one button on Linux and
  on Windows.
- Parakeet no longer writes "yeah" for a rustle or a key press. A phrase it writes words
  for is also put to a voice detector, and one with no speech in it is left out. "Leave
  out sounds that aren't speech" in Settings switches that off.
- Whisper uses one thread for each processor core, not two, which is quicker on small
  processors.
- Another computer can do the speech recognition: one shares its recogniser, the other
  sends it each phrase over the network and carries on by itself if it can't be reached.
- Speech models can be installed and removed from Settings: nine of them, from Tiny to
  Large, downloaded from Hugging Face and checked before use.
- On Windows, a key switches dictation between off and awake, whichever program is in
  front. It is chosen in the welcome window or under Keyboard in Settings: the number
  pad's +, Pause, Scroll Lock, F9, Ctrl+Alt+D or Ctrl+Alt+Space. No key is taken until
  one is chosen, because Windows hands the key to this program alone while it is
  taken, and "None" gives it back. An install from before there was a choice keeps the
  number pad's +, which is what it had.
- A full stop, question mark or exclamation mark said after a short pause is no longer
  lost now and then. The last words of such a phrase are listened to again by themselves.
- On Windows the program's windows carry its own name and icon on the taskbar, also
  when Python came from the Microsoft Store, which used to show Python's. "Awake" and the
  other notices are small pop-ups of its own by the clock, no longer Windows
  notifications labelled Python.
- "Enter" by itself can press the Enter key, like "press enter". It is a setting, off to
  start with.
- "Correct that" highlights the last phrase, the same as "select that". What is said
  next takes its place.
- Words spoken over a phrase highlighted with "select that" keep the space before them.
  In Word and Kate the highlight no longer takes in that space.
- "Space" said by itself types a space, and "space 3" three of them.
- "Hello Bob", not "Hello, Bob": the comma the recogniser puts between a greeting and a
  name is left out. A setting brings it back.
- "Select" finds words that sound the same as the one heard, and numbers written either
  way: "select two" finds "2", "two", "to" and "too".
- "Cancel" takes away the numbers shown for "select" without typing anything.
- Text before the cursor that is one word over and over is no longer shown to the
  recogniser, which used to carry on repeating it whatever was said.
- On Windows, a passing error from Word no longer sends the next words to be typed in as
  keystrokes, and the log says which program is being typed into and what an error was.
- Clicking the tray icon when dictation is off turns it on awake, ready to talk, not
  asleep.

## 0.5.0

- Dictation into Visual Studio Code, with extras for Markdown: capitals after heading and
  list markers, lists that carry on with "new line", and bold and italic as `**` and `*`.
- Coding by voice in C and C++ files in VS Code: spoken symbols, C-style spacing,
  indentation, and names recognised from the file. One setting switches it on or off.
- With a C/C++ language server such as clangd in VS Code, misheard names are corrected to
  the ones in scope, and keywords and numbers are judged by where the cursor is.
- An optional setting to dictate into any Qt or GTK program's text boxes, through the
  desktop's accessibility interface. Password boxes are refused.
- Speaking over a selection no longer adds spaces around the replacement.
- "Move left 3 words" and "move right 3 words".
- "Select all" and "tab".
- "Move to" and "jump to" work wherever "go to" does.
- Line commands: up and down by lines, go to line, select line, delete line, and in
  VS Code duplicate line, indent, outdent and comment line.
- "Press enter" is a single line break in plain-text editors.
- The tray icon is red when off, orange when asleep and green when awake.
- A demo video, linked from the README.
- Fixed: faint noises could wake it up.

## 0.4.0

The first public release.

- Dictation into LibreOffice Writer, Thunderbird messages, Kate and KWrite, sent to
  whichever is in front.
- "Wake up" and "go to sleep" by voice.
- Spacing, capitals and punctuation words fitted to the text around the cursor.
- Editing commands: scratch that, undo that, backspace, delete last word, delete that,
  select with numbered choices, select that, unselect that, spell that.
- Cursor commands by line, paragraph and document.
- Formatting commands: cap, all caps, no caps, bold, italic, underline.
- A tray icon with a microphone level meter that turns red when the signal is too loud.
- A Settings window to switch commands and punctuation words on and off and to choose the
  speech model.
- An installer and uninstaller for KDE Plasma desktops.

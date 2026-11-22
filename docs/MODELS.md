# Speech models

The speech model is the part that turns sound into words. This page is about choosing
one, the settings that go with listening, trying models on your own voice, and
retraining one to it. All of them hear English only. Back to the [README](../README.md).

- [Which model to use](#which-model-to-use)
- [Settings that depend on the model](#settings-that-depend-on-the-model)
- [Parakeet](#parakeet)
- [Noises written as words](#noises-written-as-words)
- ["That was a noise"](#that-was-a-noise)
- [Leave out whispering](#leave-out-whispering)
- [Installing and removing models](#installing-and-removing-models)
- [Copying the speech models in by hand](#copying-the-speech-models-in-by-hand)
- [Testing the models on your voice](#testing-the-models-on-your-voice)
- [Second opinions](#second-opinions)
- [Reading aloud for training](#reading-aloud-for-training)
- [Training on your voice](#training-on-your-voice)

## Which model to use

**Parakeet Unified.** It is the best of the models so far: quick, and it gets the fewest
words wrong. It is the one to use.

The installers don't fetch it, because it is a 660 MB download on top of the rest. They
fetch two small Whisper models, Base and Small, which your first dictation needs. So a new install dictates with Small until you get Parakeet
Unified:

- the **welcome window**, the first time the app starts, has a button for it, **Install
  Parakeet Unified**. It downloads the model and switches dictation to it when it has
  arrived. The download goes on if the window is closed, and can be paused. (That
  window opens by itself only the first time: "Getting started" in the tray icon's menu
  opens it again. A download of the model that was started from the list of models
  instead is not put to use by itself: choose it in Settings when it has arrived.) Or
- in Settings, under Speech recognition, **Get Parakeet Unified** opens the list of
  models, where **Install** beside it downloads it. Then choose it as the model used for
  dictation.

In the lists it is called "Parakeet Unified: recommended, the best so far". Parakeet
Unified is NVIDIA's Parakeet Unified 0.6b, under the NVIDIA Open Model License. There
is more about it [below](#parakeet).

The other models are there for comparison, and for a computer that suits them better.
Among the Whisper models, bigger ones make fewer mistakes but take longer after each
phrase.

**The model you choose does all the listening**: dictation, the commands, and "wake up"
while dictation is asleep. So how quickly it wakes is how quick that model is, and a
Parakeet answers several times sooner than a Whisper model.

One thing a Parakeet can't do is take a hint: be shown words to expect. So with a
Parakeet chosen, the Small Whisper model is kept beside it for the short second listen
for punctuation said after a pause, which leans on one.

Two things are heard by the Medium Whisper model where it is installed, whichever model
you have chosen, because they are the hardest to hear and Medium does them best. It is
loaded when it is first needed and let go ten minutes after it was last used; without
it, Small does them.

- **The spelling box.** Single letters are the hardest thing there is to tell apart.
  Measured over the alphabet in five voices, Medium told to expect letters got 106 of
  130 right, Small 93, and the Parakeets 62 and 73. No model gets them all: B, D, E, G,
  P, T and V sound alike. Say **"B as in bravo"**, or just **"bravo"**, for a letter
  that is misheard: then it is the word that settles it. The model you dictate with
  hears the box as well, and settles the words of command, such as "done", which it is
  the better at.

  Medium is also the slowest over a letter, and a letter that is waited for is no good
  either. So how long it takes on your computer is measured as you use the box, over
  three letters, and where that is more than a second Small hears the box from then
  on, in about a third of the time: with the model you dictate with beside it, 84 of
  102 letters and words right where Medium got 89. The log says when that has
  happened. To have it measured again, see
  [Troubleshooting](TROUBLESHOOTING.md#on-either-system).
- **Source code** in C and C++ files, which leans on a hint of the names in the file.
Which model hears *you* best is for [the voice test](#testing-the-models-on-your-voice)
to say.

**If the model you choose won't load**, dictation stays with the one that was in use,
the choice in Settings goes back to it, and a notice says so.

**If there is no model to load at all**, or none will load, the tray icon turns grey
with a yellow "!" and its tip says "No speech model", with the reason and what to do:
install one from Settings, or run the installer again if a part the recogniser needs is
missing. The top of Settings says the same. When a model has been installed, loading is
tried again by itself the next time the microphone hears a sound.

## Settings that depend on the model

Nearly every setting is about what is done with the words, and works the same whichever
model wrote them, on this computer or another: the commands, the punctuation words,
"wake" and "sleep", your own words. A few are about the listening itself, and a tick box
that would do nothing with the model in use is greyed, has "(no effect at present)"
after its words, and says why in its tip (rest the mouse on it, or tab to it). It can still be ticked, for when
it will do something.

- **Leave out sounds that aren't speech** is for Parakeet models.
- **Second opinions** want two more models installed to give them.
- **Quicker recognition** is for Whisper; with a Parakeet model it only quickens what
  Whisper still hears, which is spelling, source code and second opinions.

**Quicker recognition** is a tick box under "Speed". Whisper works through half a minute
of sound however short the phrase, and that is most of the wait. Ticked, it is given only
as much as the phrase needs, which is three or four times quicker with the same words. Now
and then Whisper loses its place when treated this way and writes a phrase over and over;
that is spotted, and the phrase is done again the usual way.

## Parakeet

**Parakeet** is a different recogniser from Whisper, chosen like any other model. It is
quicker again than Whisper with quicker recognition, and about as accurate as Whisper's
Medium. It is English only. It is run by
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx).

What is different about it:

- It can't be shown the text before the cursor.
- It finds your own words by their sound once it has written them down, not by being
  told to expect them: where it wrote a name or a word it doesn't know, or a word by
  itself right after a greeting or a sign-off. See
  [Your own words](COMMANDS.md#your-own-words).
- "Wake up", spelling and source code are still done by Whisper.

The models window lists Parakeet in four forms:

- **Parakeet Unified** is NVIDIA's newer Parakeet Unified 0.6b, under the NVIDIA Open
  Model License. By NVIDIA's own figures it gets slightly fewer words wrong. It is the
  recommended model.
- **Parakeet v2** is NVIDIA's Parakeet TDT 0.6b v2, licensed CC BY 4.0.
- Either of the two can also be had **at full precision**: the same recogniser with its
  numbers as they were trained, where the usual form rounds each one to eight bits to
  make it a quarter of the size. That is a 2.5 GB download, takes longer to start, and
  is a little slower for each phrase.

Whether any of them hears you better than the others is for the voice test to say.

## Noises written as words

Parakeet has one bad habit: given a short noise by itself, a rustle of clothing or a key
press, it will now and then write a word for it, nearly always "yeah", "uh" or "okay".

So each phrase it writes words for is also put to a voice detector (Silero's, the one
Whisper already uses), and a phrase with nothing like speech in it is left out, as is one
of those few words with no clear speech behind it. A real "yeah" is kept. It adds a few
thousandths of a second to a phrase. **Leave out sounds that aren't speech** in Settings
switches it off.

How well it does: tried on some 750 recorded noises of things, such as typing, mouse
clicks, a ticking clock and dripping water, Parakeet Unified wrote words for 77 of them
and all but 2 were left out. It took nothing from 51 read sentences, and one of 364
single-word commands spoken by many people.

A cough, a sneeze or a laugh is made with the voice, and the detector hears a voice in
it. So the recogniser's own doubt is used as well: it writes a noise with much less
conviction than a word that was said. One of those few noise words by itself stands only
if the recogniser was sure of it, and so does a word or two of any other kind that has
no clear speech behind it (a model retrained on your voice writes all sorts of short
words for a noise, not only "yeah"). On the recorded coughs, sneezes and laughs that took
what was still written from 9 to between 2 and 4, depending on the model, and cost one
more of the 364 commands.

## "That was a noise"

Recorded noises are not your noises, though, and a rustle at a laptop's own microphone
may still get through. Tick **"That was a noise"** under **Hearing** in Settings (it is
off to begin with), and when one does, say **"that was a noise"**. What was written is
taken back, and the sound of it is kept in a folder on your computer (`noises`, beside
the recordings for training), with what it was written as. Nothing is sent anywhere,
and on Linux the folder and what is in it can be read by your own account only (a
folder kept by an earlier version is closed to other accounts when the program starts).
Those sounds are what the rules can then be tried against, to find what tells your
noises from your speech. The last 300 are kept.

It works only on the last thing written, within two minutes, and only once: said again,
or with nothing just written, it does nothing. Unticked, the words are typed like any
others.

If another program has come to the front since the words were written, they are left
where they are: taking back the last phrase in the program now in front would remove
something you really said. The sound is kept all the same, and a notice says which
program the words are in, for you to take out there.

Under **Hearing** in Settings a line says how many sounds are kept, with **Open the
folder** to look at them (and listen, or delete any you didn't mean to keep) and
**Delete them** to remove them all, which asks first. In the folder each sound is a
file named by a count and by when it was marked, such as
`noise-000123-20261118T051809Z.wav` (the time is UTC), and `list.txt` has a line for
each: the file, what it was written as, how long it was, how much clear speech the
detector found and how sure the recogniser was. Only those files are counted, pruned
and deleted: any other sound you put in that folder is left alone. Sounds that are left
out without being marked are not kept; the log only says that one was, and why.

## Leave out whispering

**Leave out whispering**, also under **Hearing** and off to begin with, is for saying
something under your breath, to yourself or to the person beside you, without it being
written.

A voice has a pitch and a whisper is only breath. Ticked, each phrase is looked at for
voice before anything else is done with it, with any model, and one that is mostly
breath goes no further; many rustles and clicks go the same way. You can speak as quietly
as you like, so long as it is with your voice, and "wake up" has to be said aloud too.
When something is left out for this, the tray icon's tip says so.

It is not perfect at the length of a single word. Tried on recordings, whispered
sentences were left out 158 times in 160 and whispered pieces the length of a word about
nine times in ten; spoken sentences were never left out, but about one very short spoken
word in twenty was (a clipped "up" or "stop", or one said in a noisy room): say it again
a little more fully.

## Installing and removing models

**Install or remove models**, under the chooser in Settings, lists the models that can
be had, from Tiny (78 MB) to Large (3.1 GB), with a button to download or remove each.
Models come from [Hugging Face](https://huggingface.co); only the download itself goes
over the internet.

- **A download goes on if you close the window**, and a notice says when the model is
  installed, or that it could not be downloaded and why, whichever windows are open.
  One model is downloaded at a time.
- **Pause** stops it and keeps what has arrived. Pressed while the download is only
  just starting, it takes effect a moment later. **Carry on** goes on from there, and
  so does a download that was cut short by the connection. **Discard** throws away what
  has arrived, and asks first.
- **A download is checked** before the model is offered.
- **Remove** asks first. The model in use can't be removed, nor can Small, which is
  kept for the spelling box beside a Parakeet model.

Any other [faster-whisper](https://github.com/SYSTRAN/faster-whisper) model placed in
the models folder appears in the list too. The models folder is
`~/linux-speaking/models/` on Linux, and `models` in the install folder on Windows
(`C:\Users\you\linux-speaking\models`).

## Copying the speech models in by hand

For a computer that can't reach huggingface.co, as on some work networks. A model is a
folder of a few files, and the app takes any that is in its models folder.

The installer needs two, and stops if it can't fetch them: `base.en` and `small.en`.
Either:

- **Copy them from another computer** where Linux Speaking is installed. Copy the
  folders `base.en` and `small.en` out of its models folder, whole, and put them in the
  models folder of this one (make the folder if it isn't there yet).
- **Or download them with a web browser**, from
  `https://huggingface.co/Systran/faster-whisper-base.en/tree/main` and
  `https://huggingface.co/Systran/faster-whisper-small.en/tree/main`. From each page
  download `config.json`, `model.bin`, `tokenizer.json` and `vocabulary.txt`, and put
  them in a folder named `base.en` or `small.en` in the models folder.

Then run the installer again. It finds them, says "already here", and goes on.

Parakeet Unified can be copied the same way, from another computer's models folder: its
folder is called `parakeet-unified-en-0.6b`. It then appears in the list in Settings.

## Testing the models on your voice

**Test the models on my voice** finds out which model suits you. The window has a tab
for each step.

1. **Read aloud.** You read a passage aloud once. Half of it is ordinary sentences,
   which a good recogniser gets right every time. The other half is made of words one
   vowel away from another word ("pen" and "pin", "better" and "beta"), which is where
   recognisers differ and where an accent shows. The recording ends by itself when you
   have read the passage and been quiet for eight seconds, or press **Stop recording**.
   Dictation is off while you record. Closing the window gives the recording up, and
   the one kept before stays.
2. **What to try.** You tick the models to try: every one installed, to begin with. Each
   then hears that one recording, cut into phrases at your pauses as dictation would cut
   it. A test can take a quarter of an hour or more, so it goes on if the window is
   closed, and a notice says when it is done.
3. **Results.** How many words each got wrong and how long it took for a phrase, with
   the best trade-off pointed out. Choose a row to see the words it got wrong. **Use it
   for dictation** puts the suggested model to use, if it is one on this computer.

A word that every model wrote the same wrong way was most likely read differently from
the text, so it is listed but not counted against any of them. The recording is kept on
your computer, so the test can be run again after anything changes. (If another computer
does your recognising, its models can be tried too, and the recording is sent to it for
that, as dictation is.)

The results also count **near misses**: words a model got right, but was less than 90%
sure of as it wrote them. Two models that both get every word right can still differ in
how much they had in hand, and a near miss today is a wrong word on a worse day. Choose
a row to see which words they were. The first word of each phrase is left out, since the
doubt there is mostly whether to give it a capital. Compare near misses between forms of
the same recogniser, such as Parakeet with its full-precision form, or one Whisper model
with another: different recognisers don't measure their own sureness alike, and one can
be sure and wrong. Finding this out changes nothing about how a model listens, and the
moment it takes is left out of the time for a phrase. Several models working together
show a dash.

With Parakeet, Small and Medium all installed, the list also offers the three working
together: **Parakeet, checked by Small and Medium**. Each of them gets some words wrong
that the others get right. Parakeet and Small both hear the phrase; where they wrote the
same, that stands, and where they differ Medium is asked and the two that agree win.

## Second opinions

To dictate that way, tick **Second opinions** in Settings. It is experimental. Each
phrase is heard by your chosen model first, then by a second, and by a third only if
those two differ, so most phrases take a little longer and some a good deal longer.

The second and third are Small and Medium; if you dictate with Small they are Medium and
Parakeet v2, and with Medium, Small and Parakeet v2. The others listen wherever the
first did: on the other computer if recognition is done there and it has the models,
else on this one. Punctuation you say aloud and your own words are never changed by a
second opinion. Spelling, source code and "wake up" are left as they were.

## Reading aloud for training

**Read aloud for training** collects recordings of your voice with the words that go with
each. It is the first half of an experiment, retraining Parakeet to one person's voice;
the second half, the retraining, is [Train on my voice](#training-on-your-voice).

**How it goes.** One sentence is shown at a time. Read it aloud, the way you dictate, and
it moves on by itself. At each pause the model you dictate with hears the sentence so
far, and when it has heard it to the end the sound is kept and the next sentence comes
up: with Parakeet, about a second after you stop. A pause in the middle of a sentence is
waited out.

**What counts as read.** Up to a quarter of the words may be heard wrong and the sentence
still counts as read, since the words a recogniser gets wrong are the ones worth teaching
it. Something that isn't the sentence at all is not kept, and you are asked to read it
again. If the model doesn't take your second reading for the sentence either, that
reading is held: press the space bar to keep it as you read it, or A to read it once
more. Somebody whose speech the model takes wrongly is the very person the training is
for, and is not sent round the same sentence for ever.

**The keys.** The space bar moves on at once, keeping what you read, or passes over a
sentence you haven't read. Untick **Move on by itself** to work that way throughout. If
you stumble, press A to start the sentence again, or the backspace key to go back one.
P pauses.

**The level bar.** A bar under the sentence shows how loud you are as you speak, with no
steps in it: its length is the loudness and its colour the verdict, from grey and blue
for too quiet for the room, through green for a good level, to yellow, orange and red as
the microphone runs out of room. Beside it the sentence as a whole is judged in words.

**Pausing and stopping.** One button starts, pauses and carries on. Pause for a rest
whenever you like: the microphone is closed, dictation comes back as it was, and the
space bar carries on from the same sentence. It pauses by itself if nothing is read or
pressed for a minute, and then brings dictation back asleep, so that it doesn't write
down what it overhears. When you have had enough, close the window: the next sitting,
today or another day, begins at the first sentence not yet read.

While a reading is going, or a voice-test recording is being made, a click on the tray
icon, the key and "toggle" do not wake dictation: a notice says to pause the reading or
stop the recording first. Dictation beside it would type what you read aloud.

**Memory.** Training on what you read wants about 14 GB of free memory. If the computer
hasn't that much free when the window opens, it says so before you spend half an hour
reading. You can read all the same, and train when there is room.

**What there is to read.** Three hundred sentences come with it, about half an hour's
reading, a fifth of them built from words a vowel away from another word. When you have
read them all, **Read them all again** starts over from the top, for more of your voice,
or your voice in another room: what you read before is kept, and the new readings beside
it. You can read a plain text file of your own instead, such as something you wrote,
which has your own words in it. Its sentences with figures or unusual marks in them are
left out, because a recogniser may write those another way.

**Where it is kept.** Each sentence is kept as a sound file with the silence trimmed off,
in a folder for the day, beside a list of what was read (`said.txt`). The folders are in
`~/.local/state/linux-speaking/training/`, or on Windows in `state\training` in the
install folder; the window has a button that opens it. The recordings are kept on your
computer and nowhere else, and dictation is switched off while you read. (If another
computer does your recognising, each sentence is sent to it to be heard, as dictation
is; it keeps nothing.)

## Training on your voice

**Train on my voice** does the retraining, on the computer's own processor. It is
experimental too: whether it makes a model better for you is what it is there to find
out. It wants at least 30 sentences read, and the more the better.

**What it asks.** Three things: the folder of sentences (the reading window's own to
begin with), the model to start from (Parakeet Unified or Parakeet v2), and a name for
the result.

**What it tells you.** One sentence in six is kept out of the training, and when it is
over the model as it came and the retrained one both hear those: the window says how
many words each got wrong, and how many it got right without being sure of. The new model
is then among the speech models under its name, to be chosen for dictation or tried in
the voice test beside the others.

**Single words.** It learns from single words as well as from the sentences. A recogniser
learns only from what it gets wrong or is unsure of, and in a sentence the other words
settle what a word is: trained on sentences alone, a model heard them a little better and
single words no better at all. So the words of each sentence are cut out and learned from
one by one, where there is nothing but the voice to go by. On single words cut from
sentences kept out of the training, one pass took Parakeet Unified from 56 in a hundred
right to 80, with the sentences heard as well as before. The window's result counts
those single words too.

The cutting is done with Parakeet v2, which says closely when each word was spoken, so it
wants that model installed whichever one is being retrained; if it is missing the window
offers to fetch it first, and without it only the sentences are learned from. (Parakeet
Unified hears better, but writes each word a third of a second or so after it was said,
and unevenly; Whisper's word times are as loose.)

**How long, and how much memory.** Half an hour of reading takes about an hour to train
on, on an eight-core processor, and about 14 GB of memory. So the work runs by itself, at
low priority: close the window or the app and it goes on, and dictation goes on working,
a little slower. The window shows how far it has come whenever it is opened, and a notice
says when it has ended. It goes over the sentences up to ten times, and stops sooner when
the sentences it keeps aside to judge by stop being heard better: a first run of ten
passes was at its best after two.

**Stopping.** It can be stopped, and carried on later from the last pass that was
finished. While it is still getting ready, fetching the model or cutting out the words,
**Stop** ends it at once. Once the passes have begun it stops at the next few
sentences. A stopped run keeps the model as far as it had got, 2.4 GB or more; the
window has a button, **Clear stopped runs**, that clears what stopped runs have kept,
once you no longer mean to carry them on. It also lists a run whose notes were lost.

**If a run fails**, the window says what to try, and **Open the log** shows what the
trainer wrote down. A run that stops without saying why has most likely run out of
memory: close other programs and press **Carry on**.

**The training tools.** They are no part of the ordinary install: they are a Python of
their own with PyTorch and NeMo, about 2 GB. The first time, the window offers to install
them, with one button, on Linux and on Windows; the install goes on if the window is
closed, and **Stop installing** stops it and keeps what has arrived. (It runs
`scripts/install-training.sh` or `scripts/install-training.ps1`, which can be run by
hand too.) They go into a folder of their own, `training`, beside the app, and removing
that folder removes them. The first run also fetches the model's training checkpoint,
2.5 GB. A run wants about 14 GB of free memory, and the window says so when it opens if
there isn't that much.

On Windows the tools install and every step of a run has been tried, in a reduced form,
on a four-core laptop without the free memory for a real one; a full run there has not
been timed, and is reckoned at three hours or so.

## The punctuation model

Where Settings has **Full stops at the ends of phrases** set to "where the words show a
sentence has ended" (see [the commands](COMMANDS.md#at-the-end-of-a-phrase)), a second,
much smaller model decides whether a sentence ended where you paused. It is sherpa-onnx's
English online punctuation and casing model, `sherpa-onnx-online-punct-en-2024-08-06`: a
CNN-BiLSTM by frankyoujian ([Edge-Punct-Casing](https://github.com/frankyoujian/Edge-Punct-Casing),
Apache-2.0; [arXiv 2407.13142](https://arxiv.org/abs/2407.13142)), trained on Wikipedia and
on interview, podcast and TED talk transcripts. Only its punctuation is used, and only at
the pauses.

It is fetched the first time that way is chosen, from
[sherpa-onnx's releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/punctuation-models):
a 31 MB archive, checked against its published SHA-256, of which the two files needed
(7.6 MB, each checked again) are kept in the models folder, in `punctuation-en`. It runs
with onnxruntime, which the speech models already need. Until it is there, the
recogniser's own full stops are kept.

Others were measured on the same dictation and not chosen, though some did better: a
larger tagger (Horizon-Labs' multilingual punctuation and truecasing model) made two thirds
of the mistakes, but is a 303 MB download and takes twenty times as long; a small language
model used to score each choice did about as well as the tagger for 139 MB; a model of our
own, counted from openly licensed writing, did a little worse than the one chosen.

## The model that checks what makes sense

With **Put right what was just typed** ticked (as it is to begin with), a small language
model checks the few places where a recogniser most often writes something nobody would:
a spoken command heard as a word ("comma" after "Hi Joe" sounds like "common", and
"coma" and "karma" are heard too), and a sign-off said by itself on its line ("Cheers"
heard as "Chairs"). Each reading is typed as it would be, after the text before it, and
the model says how likely each is as written English. Only readings that sound like what
was heard are ever tried, and the other one is taken only where it is far more likely: by
a margin that, on readings made up to test it, put every spoken comma right and left
every real "common" and "coma" alone. Nothing is asked where none of those words was
heard, so it costs nothing the rest of the time, and about a tenth of a second where it
is asked.

The model is SmolLM2-135M by Hugging Face ([model card](https://huggingface.co/HuggingFaceTB/SmolLM2-135M),
Apache-2.0), the base model, in the int8 ONNX build published by
[onnx-community](https://huggingface.co/onnx-community/SmolLM2-135M-ONNX). It is fetched
when dictation is first switched on with the box ticked, from a fixed version of that
page: two files, 138 MB, each checked against its published SHA-256, kept in the models
folder in `sense-en`. It runs with onnxruntime, which the speech models already need.
Until it is there, phrases are typed as heard. The instruct version of the same model, and
a model nearly four times larger (Qwen2.5-0.5B), were tried on the same readings and did
no better.

## Hearing each phrase with the end of the one before

A Parakeet model hears each phrase by itself, cut where you paused. With **Hear each phrase
with the end of the one before** ticked (under Speed, as it is to begin with), the last four
seconds of the phrase before are heard with it, as you said them, and only the words the
model puts after the join are typed: by the model's own times for its words, with a word
begun before the join and a mark written at the join left to the phrase before. What the
model wrote at the join, heard with both sides, is kept: where the words decide the full
stops (see [the commands](COMMANDS.md#at-the-end-of-a-phrase)), it decides the full stop
there, and the punctuation model is asked only where there is no hearing of the join (the
first phrase, or after a command). The phrase before is the last one typed as dictation, or
a line break said ("new paragraph" in front of "Cheers" helps it be heard as that); a cough
in between changes nothing; "scratch that" and the rest that take a phrase back go back to
the one before it; any other command, the spelling box, source code, sleep, switching off or
another program in front start afresh, and so does a phrase ended more than thirty seconds
ago.

What was measured, on four samples of natural dictation (232 words) and on read sentences:
misheard words fell from 12 to 7 (from 6 to 4 outside the sample the method was first tried
on); at the pauses where the recogniser wrote a full stop, the mark it wrote at the join,
heard with left context, was right at 9 of 10 where the words alone were right at 6; on 1,325
pauses in read sentences, heard with the whole of both phrases as this does, a full stop wrongly
kept fell from 11% to 3% and real sentence ends lost from 7% to 4%. Four samples are few: the gains are clearest in the words and at the
pauses, and less sure in the typed result as a whole. Each phrase takes about a third of a
second longer on a laptop. Cutting the pause after the phrase before short was tried, and the
words came out a little worse; "hot words" (words the recogniser is told to expect) were
tried with it, and did no better overall.

With the other computer doing the listening, the end of the phrase before goes there with
the phrase, and it says it took it so; one with an earlier version is asked again without
it, and not sent it again.


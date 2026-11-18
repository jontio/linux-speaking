import os
import tempfile
import unittest
import wave

import numpy as np

from dictation import config, reading
from dictation.reading import ASTRAY, DONE, NOT_YET, Cutter, Kept, sentences_from, verdict
from dictation.reading_text import SENTENCES

QUIET = np.full(config.FRAME, 3, dtype=np.int16)
LOUD = np.full(config.FRAME, 4000, dtype=np.int16)
OTHER = np.full(config.FRAME, 5000, dtype=np.int16)  # speech that can be told from LOUD


class TheSentences(unittest.TestCase):
    def test_there_is_half_an_hour_of_them_and_none_twice(self):
        self.assertGreaterEqual(len(SENTENCES), 300)
        self.assertEqual(len(set(SENTENCES)), len(SENTENCES))

    def test_each_is_one_a_reader_can_say_in_a_breath(self):
        for sentence in SENTENCES:
            self.assertEqual(sentences_from(sentence), ([sentence], 0), sentence)
            self.assertLessEqual(len(sentence.split()), 18, sentence)
            self.assertGreaterEqual(len(sentence.split()), 6, sentence)

    def test_nothing_that_can_be_written_two_ways(self):
        numbers = set("zero one two three four five six seven eight nine ten eleven twelve "
                      "twenty thirty forty fifty hundred thousand million first second third "
                      "half once twice".split())
        either = set("colour color favourite favorite centre center metre meter litre liter "
                     "grey gray realise realize organise organize travelled traveled "
                     "cancelled canceled neighbour neighbor harbour harbor programme "
                     "licence license practise practice towards toward afterwards outwards "
                     "learnt learned spelt spelled spilt spilled burnt burned cannot okay ok "
                     "disc tyre tire cheque theatre theater mum mom".split())
        for sentence in SENTENCES:
            words = set(sentence.lower().replace(",", " ").replace(".", " ")
                        .replace("?", " ").split())
            self.assertFalse(words & numbers, sentence)
            self.assertFalse(words & either, sentence)
            self.assertFalse(any("n't" in word or word.endswith(("'ll", "'ve", "'re", "'d", "'m"))
                                 for word in words), sentence)
            self.assertNotIn("-", sentence)
            self.assertNotIn("!", sentence)


class OwnText(unittest.TestCase):
    def test_sentences_are_found_across_line_breaks(self):
        found, left_out = sentences_from("The cat sat on\nthe mat. Did it stay\nthere long?\n\n"
                                         "It did not stay.")
        self.assertEqual(found, ["The cat sat on the mat.", "Did it stay there long?",
                                 "It did not stay."])
        self.assertEqual(left_out, 0)

    def test_figures_and_odd_marks_are_left_out(self):
        found, left_out = sentences_from(
            "We sold 40 of them. The rest (about half) are here. Prices rose; sales fell. "
            "It works well enough.")
        self.assertEqual(found, ["It works well enough."])
        self.assertEqual(left_out, 3)

    def test_scraps_and_long_sentences_are_left_out(self):
        long = "This " + "goes on and on " * 9 + "for ever."
        found, left_out = sentences_from(f"Chapter the next\n\nYes. {long} That will do nicely.")
        self.assertEqual(found, ["That will do nicely."])
        self.assertEqual(left_out, 3)

    def test_curly_marks_are_made_plain_and_a_repeat_is_left_out(self):
        found, left_out = sentences_from("“It’s the dog’s bowl,” she said. "
                                         "It's the dog's bowl, she said.")
        self.assertEqual(found, ["It's the dog's bowl, she said."])
        self.assertEqual(left_out, 1)

    def test_a_chosen_text_is_copied_and_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(reading.own_text(folder), ([], 0))
            source = os.path.join(folder, "mine.txt")
            with open(source, "w", encoding="utf-8") as f:
                f.write("The cat sat on the mat. It cost $5.")
            training = os.path.join(folder, "training")
            self.assertEqual(reading.choose_own_text(source, training),
                             (["The cat sat on the mat."], 1))
            self.assertEqual(reading.own_text(training), (["The cat sat on the mat."], 1))
            with open(source, "w", encoding="utf-8") as f:
                f.write("1 2 3")  # nothing to read: the text chosen before is kept
            self.assertEqual(reading.choose_own_text(source, training), ([], 1))
            self.assertEqual(reading.own_text(training), (["The cat sat on the mat."], 1))

    def test_a_chosen_text_is_read_however_it_was_saved(self):
        # Word's "Plain Text" is in the Windows encoding and its "Unicode" is UTF-16.
        # Read as UTF-8, the one lost every sentence with a curly mark in it (one of
        # these three was left) and the other had no sentences at all.
        text = "The cat’s mat is here. “Is it?” she asked. A plain sentence with nothing odd in it."
        wanted = (["The cat's mat is here.", "Is it? she asked.",
                   "A plain sentence with nothing odd in it."], 0)
        with tempfile.TemporaryDirectory() as folder:
            for saved_as in ("utf-8", "utf-8-sig", "cp1252", "utf-16"):
                source = os.path.join(folder, saved_as + ".txt")
                with open(source, "wb") as f:
                    f.write(text.encode(saved_as))
                training = os.path.join(folder, "training-" + saved_as)
                self.assertEqual(reading.choose_own_text(source, training), wanted, saved_as)
                self.assertEqual(reading.own_text(training), wanted, saved_as)

    def test_a_long_text_cut_in_the_middle_of_a_letter_is_still_utf_8(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "cut.txt")
            with open(source, "wb") as f:
                f.write("The café was shut today. Is it é".encode("utf-8")[:-1])
            self.assertEqual(reading._text_of(source), "The café was shut today. Is it ")


class ReadToTheEnd(unittest.TestCase):
    SAID = "Nothing important has changed, although the price went up a little in the autumn."

    def test_the_whole_sentence_is_done_whatever_the_marks_and_capitals(self):
        self.assertEqual(verdict(self.SAID, self.SAID), DONE)
        self.assertEqual(verdict(self.SAID, "nothing important has changed although the price "
                                            "went up a little in the autumn"), DONE)

    def test_a_word_or_two_misheard_is_still_done(self):
        self.assertEqual(verdict(self.SAID, "Nothing important has changed, although the prize "
                                            "went up a little in autumn."), DONE)
        self.assertEqual(verdict("Fill the pool until it is full.", "Fill the pole until it is full."),
                         DONE)
        self.assertEqual(verdict("Fill the pool until it is full.", "Fill the pool until it is fool."),
                         DONE)  # the last word, too
        self.assertEqual(verdict("Fill the pool until it is full.", "Uh, fill the pool until it is full."),
                         DONE)

    def test_a_pause_part_way_through_is_not_yet(self):
        self.assertEqual(verdict(self.SAID, "Nothing important has changed,"), NOT_YET)
        self.assertEqual(verdict(self.SAID, "Nothing important has changed, although the price "
                                            "went up a little in the"), NOT_YET)
        self.assertEqual(verdict(self.SAID, "Nothing important his changed"), NOT_YET)
        self.assertEqual(verdict("Which of these do you think is better?", "Which of these"), NOT_YET)

    def test_a_cough_or_nothing_is_not_yet(self):
        self.assertEqual(verdict(self.SAID, ""), NOT_YET)
        self.assertEqual(verdict(self.SAID, "Hmm."), NOT_YET)
        self.assertEqual(verdict(self.SAID, "Right, so"), NOT_YET)

    def test_something_else_is_astray(self):
        self.assertEqual(verdict(self.SAID, "Hang on, I will be back in a minute."), ASTRAY)
        self.assertEqual(verdict("Fill the pool until it is full.",
                                 "Fill the pool, fill the pool until it is full."), ASTRAY)
        self.assertEqual(verdict(self.SAID, "The dog needs a walk before it gets dark."), ASTRAY)

    def test_two_sentences_shown_together_are_both_wanted(self):
        both = "Thanks for getting back to me. I have read through the notes."
        self.assertEqual(verdict(both, "Thanks for getting back to me."), NOT_YET)
        self.assertEqual(verdict(both, "Thanks for getting back to me. I have read through the notes."),
                         DONE)


def feed(cutter, *runs):
    """Feed runs of (frame, how many). Returns every Take that came out."""
    takes = []
    for frame, count in runs:
        for _ in range(count):
            takes += cutter.feed(frame)
    return takes


def ready() -> Cutter:
    cutter = Cutter()
    feed(cutter, (QUIET, 30))  # the room is measured
    return cutter


def loud_frames(take) -> int:
    return int(np.sum(np.abs(take.samples.astype(np.int32)) > 1000)) // config.FRAME


class Cutting(unittest.TestCase):
    def test_it_is_not_ready_until_the_room_is_measured(self):
        cutter = Cutter()
        feed(cutter, (QUIET, 10))
        self.assertFalse(cutter.ready)
        feed(cutter, (QUIET, 20))
        self.assertTrue(cutter.ready)

    def test_a_sentence_is_kept_with_a_little_quiet_either_side(self):
        cutter = ready()
        self.assertEqual(feed(cutter, (QUIET, 40), (LOUD, 100), (QUIET, 60)), [])
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(take.problem, "")
        self.assertEqual(loud_frames(take), 100)
        frames = len(take.samples) // config.FRAME
        self.assertEqual(frames, config.PREROLL_FRAMES + 100 + reading.TAIL_FRAMES)
        self.assertAlmostEqual(take.seconds, frames * config.FRAME / config.RATE)

    def test_next_pressed_before_the_last_word_is_out_loses_nothing(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 50))
        cutter.next()  # still speaking
        self.assertEqual(feed(cutter, (LOUD, 30), (QUIET, reading.PAUSE_FRAMES - 1)), [])
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(loud_frames(take), 80)

    def test_each_sentence_gets_its_own_sound(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 60), (QUIET, 40))
        cutter.next()
        first, = feed(cutter, (QUIET, 30), (OTHER, 70), (QUIET, 40))
        cutter.next()
        second, = feed(cutter, (QUIET, 1))
        self.assertEqual(int(np.max(first.samples)), 4000)
        self.assertEqual(loud_frames(first), 60)
        self.assertEqual(int(np.max(second.samples)), 5000)
        self.assertEqual(loud_frames(second), 70)

    def test_next_without_reading_keeps_nothing(self):
        cutter = ready()
        feed(cutter, (QUIET, 50))
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertIsNone(take.samples)
        self.assertEqual(take.problem, reading.NOTHING_HEARD)

    def test_a_click_is_not_a_sentence(self):
        cutter = ready()
        feed(cutter, (QUIET, 30), (LOUD, 6), (QUIET, 50))
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(take.problem, reading.NOTHING_HEARD)

    def test_next_twice_passes_over_the_following_sentence(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 50))
        cutter.next()
        cutter.next()
        first, second = feed(cutter, (QUIET, 1))
        self.assertEqual(loud_frames(first), 50)
        self.assertEqual(second.problem, reading.NOTHING_HEARD)

    def test_again_forgets_the_stumble(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 40), (QUIET, 30))
        cutter.again()
        feed(cutter, (QUIET, 20), (OTHER, 90), (QUIET, 30))
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(int(np.max(take.samples)), 5000)
        self.assertEqual(loud_frames(take), 90)

    def test_someone_who_never_pauses_is_cut_in_the_end(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 50))
        cutter.next()
        takes = feed(cutter, (LOUD, reading.WAIT_FRAMES))
        self.assertEqual(len(takes), 1)
        self.assertEqual(takes[0].problem, "")

    def test_reading_straight_on_after_an_early_press_keeps_the_next_one_s_beginning(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 50))
        cutter.next()  # still speaking
        first, = feed(cutter, (LOUD, 20), (QUIET, reading.PAUSE_FRAMES))
        feed(cutter, (OTHER, 60), (QUIET, 40))  # the next sentence, with no more of a gap
        cutter.next()
        second, = feed(cutter, (QUIET, 1))
        self.assertEqual(loud_frames(first), 70)
        self.assertEqual(second.problem, "")
        self.assertEqual(loud_frames(second), 60)
        self.assertEqual(int(np.max(second.samples[:reading.PAUSE_FRAMES * config.FRAME])), 3)

    def test_again_while_still_speaking_passes_over_the_rest_of_the_stumble(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 40))
        cutter.again()
        feed(cutter, (LOUD, 25), (QUIET, 30), (OTHER, 90), (QUIET, 30))
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(take.problem, "")
        self.assertEqual(int(np.max(take.samples)), 5000)
        self.assertEqual(loud_frames(take), 90)

    def test_what_follows_someone_who_never_pauses_belongs_to_no_sentence(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 50))
        cutter.next()
        first, = feed(cutter, (LOUD, reading.WAIT_FRAMES))
        feed(cutter, (LOUD, 40), (QUIET, 30), (OTHER, 80), (QUIET, 30))
        cutter.next()
        second, = feed(cutter, (QUIET, 1))
        self.assertEqual(int(np.max(first.samples)), 4000)
        self.assertEqual(int(np.max(second.samples)), 5000)
        self.assertEqual(loud_frames(second), 80)

    def test_after_a_rest_the_room_is_not_measured_again(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 60), (QUIET, 30))
        cutter.reopened()  # the stumble before the rest is forgotten
        self.assertTrue(cutter.ready)
        feed(cutter, (QUIET, 8), (OTHER, 70), (QUIET, 30))  # read almost at once
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(take.problem, "")
        self.assertEqual(int(np.max(take.samples)), 5000)
        self.assertEqual(loud_frames(take), 70)

    def test_a_sentence_begun_before_the_microphone_opened_is_not_kept(self):
        for reopen in (False, True):
            cutter = ready()
            if reopen:
                cutter.reopened()
                feed(cutter, (QUIET, 2), (LOUD, 60), (QUIET, 30))
            else:
                cutter = Cutter()
                feed(cutter, (QUIET, 20), (LOUD, 5 + 60), (QUIET, 30))  # talking as it measures
            cutter.next()
            take, = feed(cutter, (QUIET, 1))
            self.assertIsNone(take.samples)
            self.assertEqual(take.problem, reading.MISSED_START)

    def test_a_pause_after_speech_is_worth_a_recogniser_s_while_once(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 60), (QUIET, reading.CHECK_FRAMES - 1))
        self.assertFalse(cutter.due)
        feed(cutter, (QUIET, 1))
        self.assertTrue(cutter.due)
        mark, sound = cutter.checkpoint()
        self.assertEqual(int(np.sum(np.abs(sound.astype(np.int32)) > 1000)) // config.FRAME, 60)
        feed(cutter, (QUIET, 30))
        self.assertFalse(cutter.due)  # nothing new has been said
        self.assertTrue(cutter.accept(mark))
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(loud_frames(take), 60)
        self.assertEqual(len(take.samples) // config.FRAME,
                         config.PREROLL_FRAMES + 60 + reading.TAIL_FRAMES)

    def test_a_pause_part_way_through_is_waited_out(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 40), (QUIET, reading.CHECK_FRAMES))
        early, _ = cutter.checkpoint()  # the recogniser says: not yet
        feed(cutter, (QUIET, 15), (LOUD, 50), (QUIET, reading.CHECK_FRAMES))
        self.assertTrue(cutter.due)
        mark, sound = cutter.checkpoint()
        self.assertEqual(int(np.sum(np.abs(sound.astype(np.int32)) > 1000)) // config.FRAME, 90)
        self.assertTrue(cutter.accept(mark))
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(loud_frames(take), 90)

    def test_what_is_said_after_the_sentence_was_heard_out_belongs_to_nothing(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 60), (QUIET, reading.CHECK_FRAMES))
        mark, _ = cutter.checkpoint()
        feed(cutter, (OTHER, 30))  # talking to somebody while the recogniser thinks
        self.assertTrue(cutter.accept(mark))
        take, = feed(cutter, (OTHER, 10))
        self.assertEqual(int(np.max(take.samples)), 4000)
        self.assertEqual(loud_frames(take), 60)
        feed(cutter, (QUIET, 30), (LOUD, 70), (QUIET, 30))  # then the next sentence
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(int(np.max(take.samples)), 4000)
        self.assertEqual(loud_frames(take), 70)

    def test_a_checkpoint_of_a_sentence_started_again_is_no_use(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 60), (QUIET, reading.CHECK_FRAMES))
        mark, _ = cutter.checkpoint()
        cutter.again()
        self.assertFalse(cutter.accept(mark))
        self.assertEqual(feed(cutter, (QUIET, 5)), [])

    def test_a_microphone_left_open_is_not_a_sentence(self):
        cutter = ready()
        feed(cutter, (QUIET, 20), (LOUD, 100), (QUIET, reading.LONGEST_FRAMES))
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(take.problem, reading.TOO_LONG)
        feed(cutter, (QUIET, 20), (LOUD, 60), (QUIET, 30))  # and the next one is as usual
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(loud_frames(take), 60)

    def test_a_rest_before_reading_is_no_part_of_the_sentence(self):
        cutter = ready()
        rest = reading.LONGEST_FRAMES + 200           # longer than any sentence may be
        self.assertEqual(feed(cutter, (QUIET, rest), (LOUD, 100), (QUIET, 60)), [])
        self.assertTrue(cutter.due)                   # it is asked about, as any other is
        cutter.next()
        take, = feed(cutter, (QUIET, 1))
        self.assertEqual(take.problem, "")
        self.assertEqual(loud_frames(take), 100)
        self.assertEqual(len(take.samples) // config.FRAME,
                         config.PREROLL_FRAMES + 100 + reading.TAIL_FRAMES)

    def test_but_speech_that_runs_on_too_long_is_still_too_long(self):
        cutter = ready()
        feed(cutter, (QUIET, 300), (LOUD, reading.LONGEST_FRAMES + 50))
        cutter.next()
        take, = feed(cutter, (QUIET, reading.PAUSE_FRAMES + 1))
        self.assertEqual(take.problem, reading.TOO_LONG)


class Level(unittest.TestCase):
    """The bar beside the sentence: its length is the loudness, its colour the verdict."""

    def test_the_bar_goes_by_ear(self):
        self.assertEqual(reading.level_place(0.0), 0.0)
        self.assertEqual(reading.level_place(1.0), 100.0)
        self.assertEqual(reading.level_place(2.0), 100.0)
        halved = [reading.level_place(1.0 / 2 ** n) for n in range(5)]
        steps = [a - b for a, b in zip(halved, halved[1:])]
        for step in steps:
            self.assertAlmostEqual(step, steps[0])  # each halving of the sound, the same step back
        self.assertEqual(reading.level_place(0.001), 0.0)  # under the bar's empty end

    def test_the_colour_runs_from_grey_through_green_to_red_without_a_step(self):
        self.assertEqual(reading.level_colour(10, 0.02), reading.GREY)
        self.assertEqual(reading.level_colour(50, 0.1), reading.BLUE)
        self.assertEqual(reading.level_colour(90, 0.6), reading.YELLOW)
        self.assertEqual(reading.level_colour(90, 0.3), reading.GREEN)
        self.assertEqual(reading.level_colour(90, 0.7), reading.ORANGE)
        self.assertEqual(reading.level_colour(90, config.CLIP_LEVEL), reading.RED)
        self.assertEqual(reading.level_colour(10, 0.95), reading.RED)
        # no two neighbouring levels differ by more than a shade
        for peak in (0.05, 0.3):
            shades = [reading.level_colour(above, peak) for above in range(0, 101)]
            for a, b in zip(shades, shades[1:]):
                self.assertLess(max(abs(x - y) for x, y in zip(a, b)), 20)
        shades = [reading.level_colour(90, peak / 200) for peak in range(60, 181)]
        for a, b in zip(shades, shades[1:]):
            self.assertLess(max(abs(x - y) for x, y in zip(a, b)), 20)

    def test_a_sentence_is_judged_by_the_most_it_came_to(self):
        self.assertEqual(reading.level_verdict(20, 0.02)[0], "Too quiet")
        self.assertEqual(reading.level_verdict(50, 0.05), ("A little quiet", reading.BLUE))
        self.assertEqual(reading.level_verdict(80, 0.3), ("Good level", reading.GREEN))
        self.assertEqual(reading.level_verdict(100, 0.75)[0], "Nearly too loud")
        self.assertEqual(reading.level_verdict(100, 0.95), ("Too loud", reading.RED))
        for above, peak in ((20, 0.02), (50, 0.05), (80, 0.3), (100, 0.75), (100, 0.95)):
            self.assertTrue(reading.ADVICE[reading.level_verdict(above, peak)[0]])  # each has its advice

    def test_an_ear_follows_the_room_and_the_voice_and_keeps_nothing(self):
        ear = reading.Ear()
        self.assertFalse(ear.ready)  # the room has to be heard first
        for _ in range(40):
            quiet = ear.feed(QUIET)
        self.assertTrue(ear.ready)
        self.assertFalse(ear.speaking)
        self.assertLess(quiet, ear.room * config.RATIO)
        for _ in range(10):
            loud = ear.feed(LOUD)
        self.assertTrue(ear.speaking)
        self.assertGreater(loud, 10 * ear.room)
        for _ in range(60):
            ear.feed(QUIET)
        self.assertFalse(ear.speaking)  # the pause after it
        self.assertFalse(hasattr(ear, "_frames"))

    def test_the_cutter_says_what_it_is_hearing(self):
        cutter = ready()
        self.assertFalse(cutter.speaking)
        self.assertLess(cutter.loudness(QUIET), cutter.room * config.RATIO)
        feed(cutter, (QUIET, 20), (LOUD, 10))
        self.assertTrue(cutter.speaking)
        self.assertGreater(cutter.loudness(LOUD), 10 * cutter.room)


class Keeping(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = os.path.join(self.temp.name, "training")
        self.sound = np.arange(config.RATE, dtype=np.int16)  # a second of it

    def test_nothing_kept_to_begin_with(self):
        kept = Kept(self.folder, "2026-01-02")
        self.assertEqual(kept.texts(), set())
        self.assertEqual(kept.totals(), (0, 0.0))
        self.assertEqual(kept.take_back(), "")

    def test_a_sentence_is_kept_as_a_sound_file_and_a_line(self):
        kept = Kept(self.folder, "2026-01-02")
        path = kept.keep(self.sound, "The cat sat.")
        kept.keep(self.sound, "It  stayed\tthere.")
        self.assertEqual(path, os.path.join(self.folder, "2026-01-02", "001.wav"))
        with wave.open(path, "rb") as f:
            self.assertEqual((f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()),
                             (1, 2, config.RATE, config.RATE))
        with open(os.path.join(self.folder, "2026-01-02", "said.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "001\tThe cat sat.\n002\tIt stayed there.\n")
        self.assertEqual(kept.totals(), (2, 2.0))

    def test_days_add_up_and_numbers_carry_on(self):
        Kept(self.folder, "2026-01-02").keep(self.sound, "The cat sat.")
        later = Kept(self.folder, "2026-01-03")
        later.keep(self.sound, "It stayed there.")
        again = Kept(self.folder, "2026-01-03")  # the window opened again the same day
        self.assertTrue(again.keep(self.sound, "Then it left.").endswith("002.wav"))
        self.assertEqual(again.texts(), {"The cat sat.", "It stayed there.", "Then it left."})
        self.assertEqual(again.totals(), (3, 3.0))
        self.assertEqual(reading.unread(["A new one.", "The cat sat.", "Then it left."], again),
                         ["A new one."])

    def test_a_text_read_to_its_end_can_be_gone_through_again(self):
        text = ["The cat sat.", "It stayed there.", "Then it left."]
        first = Kept(self.folder, "2026-01-02")
        for sentence in text:
            first.keep(self.sound, sentence)
        self.assertEqual(first.rounds("mine"), 1)  # once, unless asked again
        self.assertEqual(reading.unread(text, first, first.rounds("mine")), [])
        self.assertEqual(reading.read_through(text, first), 1)
        first.set_rounds("mine", reading.read_through(text, first) + 1)
        later = Kept(self.folder, "2026-01-05")  # another day: the round is remembered
        self.assertEqual(later.rounds("mine"), 2)
        self.assertEqual(later.rounds("another text"), 1)
        self.assertEqual(reading.unread(text, later, 2), text)
        later.keep(self.sound, "The cat sat.")
        self.assertEqual(reading.unread(text, later, 2), text[1:])  # the place is kept
        self.assertEqual(later.times()["The cat sat."], 2)
        self.assertEqual(reading.read_through(text, later), 1)
        self.assertEqual(later.totals(), (4, 4.0))  # what was read before is kept beside it
        for sentence in text[1:]:
            later.keep(self.sound, sentence)
        self.assertEqual(reading.unread(text, later, 2), [])
        self.assertEqual(reading.read_through(text, later), 2)

    def test_a_sentence_kept_twice_by_some_slip_does_not_start_a_round(self):
        kept = Kept(self.folder, "2026-01-02")
        for sentence in ("The cat sat.", "The cat sat.", "It stayed there."):
            kept.keep(self.sound, sentence)
        self.assertEqual(reading.unread(["The cat sat.", "It stayed there."], kept, kept.rounds("mine")), [])
        self.assertEqual(reading.read_through(["The cat sat.", "Never read."], kept), 0)

    def test_the_last_one_can_be_taken_back_but_only_this_sitting_s(self):
        Kept(self.folder, "2026-01-02").keep(self.sound, "The cat sat.")
        kept = Kept(self.folder, "2026-01-02")
        kept.keep(self.sound, "It stayed there.")
        kept.keep(self.sound, "Then it left.")
        self.assertEqual(kept.take_back(), "Then it left.")
        self.assertEqual(kept.take_back(), "It stayed there.")
        self.assertEqual(kept.take_back(), "")
        self.assertEqual(kept.texts(), {"The cat sat."})
        self.assertEqual(os.listdir(os.path.join(self.folder, "2026-01-02")).count("002.wav"), 0)
        self.assertTrue(kept.keep(self.sound, "It came back.").endswith("002.wav"))

    def test_a_sound_file_removed_by_hand_no_longer_counts(self):
        kept = Kept(self.folder, "2026-01-02")
        os.remove(kept.keep(self.sound, "The cat sat."))
        self.assertEqual(kept.texts(), set())
        self.assertEqual(kept.totals(), (0, 0.0))

    def test_time_text(self):
        self.assertEqual(reading.time_text(42.7), "42 s")
        self.assertEqual(reading.time_text(605), "10 min 5 s")


class KeepingAfterMeddling(unittest.TestCase):
    """What happens when the folder has been changed by hand between sittings."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = os.path.join(self.temp.name, "training")
        self.sound = np.arange(config.RATE, dtype=np.int16)

    def test_a_number_is_not_used_again_after_its_sound_was_deleted(self):
        kept = Kept(self.folder, "2026-01-02")
        kept.keep(self.sound, "The cat sat.")
        gone = kept.keep(self.sound, "It stayed there.")
        os.remove(gone)
        path = Kept(self.folder, "2026-01-02").keep(self.sound, "Then it left.")
        self.assertTrue(path.endswith("003.wav"))
        again = Kept(self.folder, "2026-01-02")
        self.assertEqual(again.texts(), {"The cat sat.", "Then it left."})
        self.assertEqual(again.totals()[0], 2)

    def test_a_number_listed_twice_goes_with_its_later_line(self):
        day = os.path.join(self.folder, "2026-01-02")
        Kept(self.folder, "2026-01-02").keep(self.sound, "Old words.")
        with open(os.path.join(day, "said.txt"), "a", encoding="utf-8") as f:
            f.write("001\tNew words.\n")
        self.assertEqual(Kept(self.folder, "2026-01-02").texts(), {"New words."})
        from dictation import training
        self.assertEqual([text for _, text in training.sentences(self.folder)], ["New words."])

    def test_a_list_saved_in_another_encoding_is_read_as_far_as_it_can_be(self):
        day = os.path.join(self.folder, "2026-01-02")
        Kept(self.folder, "2026-01-02").keep(self.sound, "The cat sat.")
        with open(os.path.join(day, "said.txt"), "ab") as f:
            f.write("002\tCaf\u00e9.\n".encode("latin-1"))
        self.assertEqual(Kept(self.folder, "2026-01-02").totals()[0], 1)
        from dictation import training
        self.assertEqual(len(training.sentences(self.folder)), 1)

    def test_a_folder_that_cannot_be_written_does_not_stop_reading_again(self):
        kept = Kept(os.path.join(self.temp.name, "a-file"), "2026-01-02")
        with open(kept.folder, "w") as f:
            f.write("not a folder")
        kept.set_rounds("the sentences that come with it", 2)   # nothing raised
        self.assertEqual(kept.rounds("the sentences that come with it"), 1)


if __name__ == "__main__":
    unittest.main()

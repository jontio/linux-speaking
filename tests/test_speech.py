import os
import unittest
import unittest.mock

import numpy as np

from dictation import config, speech
from dictation.speech import not_speech, only_noise_words

SOUND = np.zeros(config.RATE, dtype=np.float32)  # a stand-in: the detectors below don't listen


def detector(some: float, clear: float):
    """A voice detector that finds `some` seconds of speech on its easy reading and
    `clear` on its usual one, and remembers what it was asked."""
    asked = []

    def spoken(audio, threshold):
        asked.append(threshold)
        return some if threshold == speech.SOME else clear
    spoken.asked = asked
    return spoken


class NoiseWords(unittest.TestCase):
    def test_what_parakeet_writes_for_a_noise(self):
        for text in ("Yeah.", "yeah", "Uh,", "Okay.", "Mm-hmm.", "Uh-huh", "Ha ha ha.", "Yeah, okay.", "OK", "Hmm"):
            self.assertTrue(only_noise_words(text), text)

    def test_anything_else_is_not(self):
        for text in ("Yes.", "No", "Yeah, I think so.", "Scratch that", "Comma", "New line", "Okay then",
                     "The", "I", "Thank you.", "", " . "):
            self.assertFalse(only_noise_words(text), text)


class SpeechOrNoise(unittest.TestCase):
    def test_a_sound_with_nothing_like_speech_in_it_is_a_noise_whatever_was_written(self):
        self.assertEqual(not_speech("Brilliant.", SOUND, detector(0.0, 0.0)), "nothing like speech in it")
        self.assertEqual(not_speech("Yeah.", SOUND, detector(0.0, 0.0)), "nothing like speech in it")

    def test_real_words_need_only_something_like_speech(self):
        spoken = detector(0.04, 0.0)
        self.assertEqual(not_speech("Scratch that", SOUND, spoken), "")
        self.assertEqual(spoken.asked, [speech.SOME])  # the usual reading isn't taken at all
        self.assertEqual(not_speech("Yes.", SOUND, detector(0.04, 0.0)), "")

    def test_a_noise_word_needs_clear_speech_behind_it(self):
        self.assertEqual(not_speech("Yeah.", SOUND, detector(0.3, 0.0)),
                         "a noise word, with no clear speech behind it")
        self.assertEqual(not_speech("Uh", SOUND, detector(0.3, speech.CLEAR_SECONDS)),
                         "a noise word, with no clear speech behind it")
        self.assertEqual(not_speech("Yeah.", SOUND, detector(0.4, 0.31)), "")  # really said
        self.assertEqual(not_speech("Okay.", SOUND, detector(0.4, 0.2)), "")

    def test_nothing_written_is_not_asked_about(self):
        spoken = detector(0.0, 0.0)
        self.assertEqual(not_speech("", SOUND, spoken), "")
        self.assertEqual(not_speech("  ", SOUND, spoken), "")
        self.assertEqual(spoken.asked, [])

    def test_without_a_detector_everything_stands(self):
        self.assertEqual(not_speech("Yeah.", SOUND, lambda audio, threshold: None), "")

    def a_detector(self, answer):
        """Have `answer(audio, options)` stand where the real detector is, for this test."""
        import sys
        import types
        stand_in = types.ModuleType("faster_whisper")
        stand_in.vad = types.SimpleNamespace(VadOptions=lambda **options: options,
                                             get_speech_timestamps=answer)
        for patch in (unittest.mock.patch.dict(sys.modules, {"faster_whisper": stand_in}),
                      unittest.mock.patch.object(speech, "_unusable", False),
                      unittest.mock.patch.object(speech, "_failures", 0),
                      unittest.mock.patch("builtins.print")):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_detector_that_fails_once_is_asked_again_and_everything_stands_meanwhile(self):
        failing, asked = [True], []

        def answer(audio, options):
            asked.append(1)
            if failing[0]:
                raise RuntimeError("no memory to spare, this once")
            return [{"start": 0, "end": 3200}]

        self.a_detector(answer)
        self.assertIsNone(speech.spoken(SOUND, speech.SOME))
        self.assertEqual(not_speech("Yeah.", SOUND), "")           # it stands as it was written
        self.assertFalse(speech._unusable)
        failing[0] = False
        self.assertAlmostEqual(speech.spoken(SOUND, speech.SOME), 0.2)     # and it is asked again
        self.assertEqual(not_speech("Brilliant.", SOUND), "")
        self.assertEqual(speech._failures, 0)

    def test_one_that_fails_time_after_time_is_given_up_on(self):
        asked = []

        def answer(audio, options):
            asked.append(1)
            raise RuntimeError("no model")

        self.a_detector(answer)
        for _ in range(speech.MOST_FAILURES + 3):
            self.assertIsNone(speech.spoken(SOUND, speech.SOME))
        self.assertTrue(speech._unusable)
        self.assertEqual(len(asked), speech.MOST_FAILURES)         # and no more is asked of it
        self.assertEqual(not_speech("Yeah.", SOUND), "")

    def test_failures_with_answers_between_them_are_not_a_run(self):
        turn = [0]

        def answer(audio, options):
            turn[0] += 1
            if turn[0] % 2:
                raise RuntimeError("now and then")
            return []

        self.a_detector(answer)
        for _ in range(4 * speech.MOST_FAILURES):
            speech.spoken(SOUND, speech.SOME)
        self.assertFalse(speech._unusable)

    def test_a_detector_that_is_not_there_is_not_asked_for_again(self):
        import sys
        self.a_detector(lambda audio, options: [])
        with unittest.mock.patch.dict(sys.modules, {"faster_whisper": None}):   # not installed
            self.assertIsNone(speech.spoken(SOUND, speech.SOME))
        self.assertTrue(speech._unusable)
        self.assertIsNone(speech.spoken(SOUND, speech.SOME))       # even now that it could be had

    def test_the_detector_s_spans_are_added_up_in_seconds(self):
        import sys
        import types
        was, kept = speech._unusable, sys.modules.get("faster_whisper")
        asked = {}

        def get_speech_timestamps(audio, options):
            asked.update(options)
            return [{"start": 1600, "end": 4800}, {"start": 8000, "end": 9600}]

        stand_in = types.ModuleType("faster_whisper")
        stand_in.vad = types.SimpleNamespace(VadOptions=lambda **options: options,
                                             get_speech_timestamps=get_speech_timestamps)
        sys.modules["faster_whisper"] = stand_in
        speech._unusable = False
        try:
            self.assertAlmostEqual(speech.spoken(SOUND, 0.5), 0.3)
            self.assertEqual(asked["threshold"], 0.5)
            self.assertEqual(asked["speech_pad_ms"], 0)
        finally:
            speech._unusable = was
            if kept is None:
                del sys.modules["faster_whisper"]
            else:
                sys.modules["faster_whisper"] = kept


class HowSureTheRecogniserWas(unittest.TestCase):
    """A noise is written with less conviction than a word that was said."""

    def test_a_noise_word_with_speech_behind_it_stands_only_if_it_was_sure(self):
        behind = detector(0.4, 0.3)                    # a sneeze, a sigh: the detector hears a voice
        self.assertEqual(not_speech("Yeah.", SOUND, behind, sure=0.55),
                         "a noise word that the recogniser wasn't sure of")
        self.assertEqual(not_speech("Yeah.", SOUND, behind, sure=0.97), "")   # really said
        self.assertEqual(not_speech("Yeah.", SOUND, behind), "")              # it didn't say how sure

    def test_a_word_or_two_of_any_kind_needs_clear_speech_or_to_be_sure(self):
        faint = detector(0.1, 0.0)
        self.assertEqual(not_speech("Hit.", SOUND, faint, sure=0.41),
                         "a word or two that the recogniser wasn't sure of, with no clear speech behind")
        self.assertEqual(not_speech("Hey, shoot.", SOUND, faint, sure=0.48)[:13], "a word or two")
        self.assertEqual(not_speech("Up.", SOUND, faint, sure=1.0), "")       # quiet, but sure
        self.assertEqual(not_speech("Hit.", SOUND, detector(0.4, 0.3), sure=0.41), "")  # clear speech
        self.assertEqual(not_speech("Hit.", SOUND, faint), "")

    def test_longer_phrases_are_not_doubted(self):
        self.assertEqual(not_speech("It was a hit.", SOUND, detector(0.1, 0.0), sure=0.2), "")

    def test_the_usual_reading_is_only_taken_when_it_matters(self):
        spoken = detector(0.4, 0.3)
        not_speech("Scratch that", SOUND, spoken, sure=0.99)
        self.assertEqual(spoken.asked, [speech.SOME])
        not_speech("Scratch that", SOUND, spoken, sure=0.5)
        self.assertEqual(spoken.asked, [speech.SOME, speech.SOME, speech.CLEAR])

    def test_what_was_measured_can_be_had_for_the_log(self):
        numbers = {"seconds": 1.0}
        self.assertEqual(not_speech("Stop.", SOUND, detector(0.4, 0.31), sure=0.934, numbers=numbers), "")
        self.assertEqual(numbers, {"seconds": 1.0, "clear": 0.31, "sure": 0.93})
        self.assertEqual(speech.told(numbers), " (1.0 s, 0.31 s of clear speech, sure 0.93)")
        self.assertEqual(speech.told({"seconds": 4.0}), "")
        self.assertEqual(speech.told(None), "")


def buzz(seconds: float, pitch: float = 120.0):
    """Something like a voice holding a vowel: a pitch and the tones above it."""
    t = np.arange(int(config.RATE * seconds)) / config.RATE
    return sum(np.sin(2 * np.pi * pitch * n * t) / n for n in range(1, 25)) / 3


def hiss(seconds: float, seed: int = 0):
    """Something like breath: no pitch at all."""
    return np.random.default_rng(seed).normal(size=int(config.RATE * seconds))


class AVoiceOrOnlyBreath(unittest.TestCase):
    """A whisper has no voice in it, and can be left out for that."""

    def test_a_voice_is_nearly_all_voice(self):
        for pitch in (80.0, 120.0, 220.0, 350.0):  # a deep voice to a child's
            self.assertGreater(speech.voiced(buzz(1.0, pitch)), 0.9, pitch)

    def test_breath_is_none(self):
        self.assertLess(speech.voiced(hiss(2.0)), 0.05)

    def test_a_voice_in_a_noisy_room_is_still_a_voice(self):
        sound = buzz(1.0)
        self.assertGreater(speech.voiced(sound / sound.std() + hiss(1.0)), speech.VOICED * 2)

    def test_a_short_word_with_quiet_round_it_is_a_voice(self):
        room = 0.001 * hiss(0.5)
        self.assertGreater(speech.voiced(np.concatenate([room, buzz(0.2), room])), 0.8)

    def test_a_whisper_with_a_moment_of_voice_in_it_is_still_a_whisper(self):
        sound = hiss(3.0)
        sound[config.RATE:config.RATE + config.RATE // 10] += 3 * buzz(0.1)
        self.assertLess(speech.voiced(sound), speech.VOICED)

    def test_breath_on_the_microphone_is_not_a_pitch(self):
        t = np.arange(config.RATE) / config.RATE
        self.assertEqual(speech.voiced(np.sin(2 * np.pi * 30 * t) + 0.05 * hiss(1.0)), 0.0)

    def test_how_loud_it_is_makes_no_difference(self):
        sound = buzz(0.5) + 0.3 * hiss(0.5)
        self.assertAlmostEqual(speech.voiced(sound), speech.voiced(sound * 20000), places=6)
        self.assertAlmostEqual(speech.voiced(sound), speech.voiced((sound * 3000).astype(np.int16)),
                               places=1)

    def test_nothing_and_next_to_nothing(self):
        for sound in (np.zeros(0), np.zeros(100), np.zeros(config.RATE), buzz(0.02)):
            self.assertEqual(speech.voiced(sound), 0.0)


class KeepingANoise(unittest.TestCase):
    def test_the_sound_and_a_line_about_it_are_kept(self):
        import tempfile
        import wave
        import numpy as np
        folder = os.path.join(tempfile.mkdtemp(), "noises")
        sound = np.full(8000, 0.25, dtype=np.float32)
        path = speech.keep_noise(folder, sound, "Yeah.", "a-model", {"clear": 0.2, "sure": 0.5})
        with wave.open(path, "rb") as f:
            self.assertEqual((f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()),
                             (1, 2, 16000, 8000))
        other = speech.keep_noise(folder, sound, "Hit.")                # the same second: its own file
        self.assertNotEqual(path, other)
        with open(os.path.join(folder, "list.txt"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0].split("\t")[1:], ["Yeah.", "clear=0.2 model=a-model seconds=0.5 sure=0.5"])
        self.assertEqual(len(lines), 2)

    def test_what_is_kept_can_be_counted_and_removed(self):
        import tempfile
        import numpy as np
        folder = os.path.join(tempfile.mkdtemp(), "noises")
        self.assertEqual(speech.noises_kept(folder), (0, 0))
        speech.keep_noise(folder, np.zeros(16000, dtype=np.float32), "Yeah.")
        speech.keep_noise(folder, np.zeros(8000, dtype=np.float32), "Hit.")
        count, size = speech.noises_kept(folder)
        self.assertEqual(count, 2)
        self.assertGreater(size, 48000)
        with open(os.path.join(folder, "mine.txt"), "w") as f:      # something put there by hand
            f.write("keep me")
        speech.forget_noises(folder)
        self.assertEqual(sorted(os.listdir(folder)), ["mine.txt"])  # only that is left
        os.remove(os.path.join(folder, "mine.txt"))
        speech.keep_noise(folder, np.zeros(160, dtype=np.float32), "Yeah.")
        speech.forget_noises(folder)
        self.assertFalse(os.path.exists(folder))                    # and an empty folder goes

    def test_the_list_keeps_only_the_lines_whose_sound_is_kept(self):
        import tempfile
        import numpy as np
        folder = tempfile.mkdtemp()
        with unittest.mock.patch.object(speech, "MOST_NOISES", 2):
            for n in range(4):
                speech.keep_noise(folder, np.zeros(160, dtype=np.float32), f"word{n}")
        with open(os.path.join(folder, "list.txt"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        kept = sorted(name for name in os.listdir(folder) if name.endswith(".wav"))
        self.assertEqual(len(kept), 2)
        self.assertEqual(sorted(line.split("\t")[0] for line in lines), kept)
        self.assertEqual([line.split("\t")[1] for line in lines], ["word2", "word3"])

    def test_only_so_many_are_kept(self):
        import tempfile
        import numpy as np
        folder = tempfile.mkdtemp()
        for n in range(4):
            open(os.path.join(folder, f"2020010{n}-000000.wav"), "w").close()
        with unittest.mock.patch.object(speech, "MOST_NOISES", 3):
            speech.keep_noise(folder, np.zeros(160, dtype=np.float32), "x")
        kept = sorted(name for name in os.listdir(folder) if name.endswith(".wav"))
        self.assertEqual(len(kept), 3)
        self.assertNotIn("20200100-000000.wav", kept)

    def keep(self, folder, text="x"):
        import numpy as np
        return os.path.basename(speech.keep_noise(folder, np.zeros(160, dtype=np.float32), text))

    @unittest.skipIf(os.name == "nt", "who may read a file is not set this way there")
    @unittest.skipIf(os.name == "nt", "Windows keeps the folder private another way")
    def test_a_folder_from_before_is_closed_when_the_program_starts(self):
        import stat
        import tempfile
        folder = os.path.join(tempfile.mkdtemp(), "noises")
        os.makedirs(folder)
        for name in ("20261118-151737.wav", speech.LIST, "holiday.wav"):
            with open(os.path.join(folder, name), "w") as f:
                f.write("x")
            os.chmod(os.path.join(folder, name), 0o644)
        os.chmod(folder, 0o755)
        speech.for_its_owner_alone(folder)
        mode = lambda name: stat.S_IMODE(os.stat(os.path.join(folder, name)).st_mode)
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        self.assertEqual((mode("20261118-151737.wav"), mode(speech.LIST)), (0o600, 0o600))
        self.assertEqual(mode("holiday.wav"), 0o644)      # not the app's: left as it was
        speech.for_its_owner_alone(os.path.join(folder, "no such folder"))   # and no folder is no trouble

    def test_what_is_kept_is_for_its_owner_alone_to_read(self):
        import stat
        import tempfile
        was = os.umask(0o022)                                       # the usual: others may read
        self.addCleanup(os.umask, was)
        folder = os.path.join(tempfile.mkdtemp(), "noises")
        name = self.keep(folder, "Yeah.")
        mode = lambda path: stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode(folder), 0o700)
        self.assertEqual(mode(os.path.join(folder, name)), 0o600)
        self.assertEqual(mode(os.path.join(folder, "list.txt")), 0o600)
        # A folder from before this, open to others' eyes, is closed when it is next used:
        # and so is the list, when it is next written or tidied.
        os.chmod(folder, 0o755)
        os.chmod(os.path.join(folder, "list.txt"), 0o644)
        with unittest.mock.patch.object(speech, "MOST_NOISES", 1):
            self.keep(folder, "Hit.")
        self.assertEqual(mode(folder), 0o700)
        self.assertEqual(mode(os.path.join(folder, "list.txt")), 0o600)

    def test_no_other_sound_in_the_folder_is_counted_taken_away_or_removed(self):
        import tempfile
        folder = tempfile.mkdtemp()
        others = ["holiday.wav", "Recording 1.wav", "noise.wav", "noise-1.wav", "20261101.wav", "notes.txt"]
        for name in others:
            with open(os.path.join(folder, name), "w") as f:
                f.write("mine, put here by hand")
        with unittest.mock.patch.object(speech, "MOST_NOISES", 2):
            made = [self.keep(folder) for _ in range(4)]            # with two taken away as the oldest
        self.assertEqual(speech.noises_kept(folder)[0], 2)
        left = sorted(os.listdir(folder))
        self.assertEqual(left, sorted(others + made[2:] + ["list.txt"]))
        speech.forget_noises(folder)
        self.assertEqual(sorted(os.listdir(folder)), sorted(others))
        self.assertEqual(speech.noises_kept(folder), (0, 0))

    def test_the_newest_are_kept_whatever_the_clock_does(self):
        import tempfile
        import time
        folder = tempfile.mkdtemp()
        real_strftime, real_gmtime = time.strftime, time.gmtime
        # Two just before the clock is put back an hour, and two after.
        moments = [1793498400, 1793498401, 1793494800, 1793494801]

        def stamped(form, *when):
            return real_strftime(form, real_gmtime(moments.pop(0)))

        with unittest.mock.patch.object(speech, "MOST_NOISES", 2), \
                unittest.mock.patch.object(speech.time, "strftime", stamped):
            made = [self.keep(folder, f"word{n}") for n in range(4)]
        self.assertEqual(sorted(name for name in os.listdir(folder) if name.endswith(".wav")),
                         sorted(made[2:]))                          # the last two made
        with open(os.path.join(folder, "list.txt"), encoding="utf-8") as f:
            self.assertEqual([line.split("\t")[1] for line in f.read().splitlines()], ["word2", "word3"])

    def test_those_named_before_the_count_are_the_oldest(self):
        import tempfile
        folder = tempfile.mkdtemp()
        before = ["20991231-235959-01.wav", "20991231-235959-02.wav", "20991231-235958.wav"]
        for name in before:
            open(os.path.join(folder, name), "w").close()
        self.assertEqual(speech.noises_kept(folder)[0], 3)          # they are the app's own, too
        with unittest.mock.patch.object(speech, "MOST_NOISES", 2):
            made = self.keep(folder)                                # though by their names they are later
        self.assertEqual(sorted(name for name in os.listdir(folder) if name.endswith(".wav")),
                         sorted(["20991231-235959-02.wav", made]))

    def test_several_at_the_same_moment_each_get_a_file_and_a_line(self):
        import tempfile
        import threading
        folder = os.path.join(tempfile.mkdtemp(), "noises")
        several = [threading.Thread(target=self.keep, args=(folder, f"word{n}")) for n in range(8)]
        for one in several:
            one.start()
        for one in several:
            one.join()
        with open(os.path.join(folder, "list.txt"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(sorted(line.split("\t")[0] for line in lines),
                         sorted(name for name in os.listdir(folder) if name.endswith(".wav")))
        self.assertEqual(len(lines), 8)


if __name__ == "__main__":
    unittest.main()

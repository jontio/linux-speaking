"""Seeing the voice stop where the room is too loud for a pause."""
import unittest

import numpy as np

import sys
import types
from unittest import mock

from dictation import config, speech
from dictation.segmenter import END, NO_VOICE, START, Segmenter, SegmenterConfig
from dictation.speech import BEGAN_LATE, GONE, PIECE_OF_SPEECH, VoiceWatch

RATE, FRAME = config.RATE, config.FRAME


def voice(seconds: float, loud: float = 3000.0, pitch: float = 140.0) -> np.ndarray:
    """Something with a pitch, as a voice has: a tone and its overtones, rising and
    falling by the syllable."""
    t = np.arange(int(seconds * RATE)) / RATE
    tone = sum(np.sin(2 * np.pi * pitch * n * t) / n for n in range(1, 8))
    syllables = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)
    return (tone * syllables * loud).astype(np.float32)


def room(seconds: float, loud: float = 1600.0, seed: int = 1) -> np.ndarray:
    """A noise with no pitch, whose loudness wanders: a fan that roars, a keyboard."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    steps = n // 1600 + 2
    wander = np.interp(np.arange(n), np.arange(steps) * 1600, np.exp(rng.normal(0, 0.5, steps)))
    return (rng.normal(0, 1, n) * wander * loud).astype(np.float32)


def frames(sound: np.ndarray):
    for at in range(0, len(sound) - FRAME + 1, FRAME):
        yield sound[at:at + FRAME].astype(np.int16)


def watched(sound: np.ndarray, detector=None, watch=None) -> list:
    """What the watch says of `sound`, and when: [(seconds in, what), ...]. With no
    detector to ask, it looks for the voice's pitch."""
    watch = watch or VoiceWatch(detector=detector)
    said = []
    for count, frame in enumerate(frames(sound), 1):
        seen = watch.feed(frame)
        if seen:
            said.append((round(count * FRAME / RATE, 2), seen))
            if seen == GONE:
                break
    return said


class TheVoiceIsWatchedByItsPitch(unittest.TestCase):
    """Where there is no voice detector to ask: as it was done before there was one."""

    def test_it_is_seen_to_have_gone_though_the_room_goes_on(self):
        sound = room(12.0)
        sound[:3 * RATE] += voice(3.0)                    # three seconds said, in a loud room
        said = watched(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertGreater(said[0][0], 3.0 + 1.0)        # not before it has really stopped
        self.assertLess(said[0][0], 3.0 + 2.6)           # and not twenty seconds after

    def test_a_room_with_no_voice_in_it_is_never_cut_for_want_of_one(self):
        self.assertEqual(watched(room(15.0, seed=2)), [])  # as a whisper would not be

    def test_talking_with_short_gaps_in_it_is_not_cut(self):
        sound = room(12.0, seed=3)
        for start in (0.0, 2.6, 5.2, 7.8):               # four stretches, 0.6 s apart
            sound[int(start * RATE):int((start + 2.0) * RATE)] += voice(2.0)
        said = watched(sound[:int(9.8 * RATE)])
        self.assertEqual(said, [])

    def test_a_voice_that_begins_well_into_the_rooms_noise_is_said_to_have_begun_late(self):
        sound = room(12.0, seed=4)
        sound[6 * RATE:9 * RATE] += voice(3.0)           # six seconds of the room, then a voice
        said = watched(sound)
        self.assertEqual([what for _, what in said], [BEGAN_LATE, GONE])
        self.assertTrue(6.0 < said[0][0] < 7.3)          # within a look or two of its start
        self.assertTrue(9.0 + 1.0 < said[1][0] < 9.0 + 2.6)

    def test_a_voice_that_begins_the_phrase_did_not_begin_late(self):
        sound = room(6.0, seed=5)
        sound[:2 * RATE] += voice(2.0)
        self.assertEqual([what for _, what in watched(sound)], [GONE])

    def test_in_a_quiet_room_too_the_voice_is_seen(self):
        sound = np.concatenate([voice(2.0), np.zeros(4 * RATE, np.float32)])
        self.assertEqual([what for _, what in watched(sound)], [GONE])

    def test_it_keeps_count_for_the_one_who_cuts_the_phrase(self):
        watch = VoiceWatch(detector=None)
        self.assertEqual((watch.frames_for(1.0), watch.frames_for(watch.AFTER)), (50, 20))
        watch.start(15)                                   # the moment before the phrase is kept
        self.assertEqual((watch.frames, watch.heard, watch.frames_since_voice()), (15, False, 0))
        sound = room(5.0, seed=6)
        sound[:2 * RATE] += voice(2.0)
        for frame in frames(sound):
            if watch.feed(frame) == GONE:
                break
        self.assertGreaterEqual(watch.frames_since_voice(), watch.frames_for(watch.GONE_SLOWLY))
        watch.began_at(75)
        self.assertEqual((watch.frames, watch.frames_since_voice()), (75, 0))

    def test_a_detector_that_does_not_answer_leaves_it_to_the_pitch(self):
        asked = []
        sound = room(12.0)
        sound[:3 * RATE] += voice(3.0)
        watch = VoiceWatch(detector=lambda sound: asked.append(len(sound)) or None)
        said = watched(sound, watch=watch)
        self.assertEqual(len(asked), 1)                   # asked once in the phrase, and not again
        self.assertEqual([what for _, what in said], [GONE])
        self.assertTrue(3.0 + 1.0 < said[0][0] < 3.0 + 2.6)
        watch.start()                                     # in the next phrase it is asked afresh:
        watched(sound, watch=watch)                       # it may only have failed the once
        self.assertEqual(len(asked), 2)

    def test_one_that_answers_for_the_wrong_number_of_pieces_is_not_believed(self):
        sound = room(12.0)
        sound[:3 * RATE] += voice(3.0)
        said = watched(sound, detector=lambda sound: np.ones(3, dtype=np.float32))
        self.assertTrue(3.0 + 1.0 < said[0][0] < 3.0 + 2.6)


# ---- with the detector ------------------------------------------------------------------
# A stand-in for it, which needs no model: "speech" here is a whistle at 1000 Hz, and a
# piece is speech if most of what is in it is that whistle. Like the real one it goes by
# what the sound is and not by how loud: a whistle a tenth as loud is speech as well.
def speaking(seconds: float, loud: float = 3000.0) -> np.ndarray:
    """It rises and falls by the syllable, as talking does: what stays level is a fan."""
    t = np.arange(int(seconds * RATE)) / RATE
    return (np.sin(2 * np.pi * 1000 * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 4 * t)) * loud).astype(np.float32)


def hiss(seconds: float, loud: float = 300.0, seed: int = 1) -> np.ndarray:
    return (np.random.default_rng(seed).normal(0, 1, int(seconds * RATE)) * loud).astype(np.float32)


def keys(seconds: float, loud: float = 9000.0, seed: int = 1) -> np.ndarray:
    """Keys being pressed: a burst of noise every fifth of a second, far louder than a voice."""
    rng = np.random.default_rng(seed)
    sound = hiss(seconds, 100.0, seed)
    for at in range(RATE // 10, len(sound) - 400, RATE // 5):
        sound[at:at + 160] += (rng.normal(0, 1, 160) * loud).astype(np.float32)
    return sound


def whistle_detector(sound) -> np.ndarray:
    pieces = np.asarray(sound, dtype=np.float64).reshape(-1, PIECE_OF_SPEECH)
    power = np.abs(np.fft.rfft(pieces, axis=1)) ** 2
    return (power[:, 31:34].sum(axis=1) > 0.5 * np.maximum(power.sum(axis=1), 1e-12)).astype(np.float32)


WAIT = VoiceWatch.GONE_AFTER   # how long after the voice the phrase is ended, where no pause shows


class TheVoiceIsWatchedByTheDetector(unittest.TestCase):
    def said(self, sound, **changes):
        watch = VoiceWatch(detector=whistle_detector)
        for name, value in changes.items():
            setattr(watch, name, value)
        self.watch = watch
        return watched(sound, watch=watch)

    def test_it_is_seen_to_have_gone_soon_after_it_stops_though_the_room_goes_on(self):
        sound = hiss(12.0, 600.0)
        sound[:3 * RATE] += speaking(3.0)
        said = self.said(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertGreaterEqual(said[0][0], 3.0 + WAIT)                    # not before the wait is up
        self.assertLess(said[0][0], 3.0 + WAIT + 0.25)                     # and no second or two after
        self.assertFalse(self.watch.soft)

    def test_it_knows_closely_when_the_voice_stopped(self):
        sound = hiss(8.0, 600.0)
        sound[:3 * RATE] += speaking(3.0)
        self.said(sound)
        since = self.watch.frames_since_voice() / self.watch.per_second
        gone_at = self.watch.frames / self.watch.per_second
        self.assertAlmostEqual(gone_at - since, 3.0, delta=0.1)    # to within a tenth of a second

    def test_a_short_word_among_louder_key_presses_is_heard_and_its_end_seen(self):
        sound = keys(12.0)
        sound[RATE:int(1.45 * RATE)] += speaking(0.45, 1500.0)
        said = self.said(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertTrue(1.45 + WAIT <= said[0][0] < 1.45 + WAIT + 0.3, said)
        # By its pitch such a word was seen to have gone two seconds after it had, or
        # never: where the key presses were the loud part of every second, it wasn't seen
        # at all, and the phrase ran on to its limit.
        by_pitch = keys(12.0)
        by_pitch[RATE:int(1.45 * RATE)] += voice(0.45, 1500.0)
        late = watched(by_pitch)
        self.assertTrue(not late or late[0][0] > 1.45 + 2.0, late)

    def test_a_room_with_no_voice_in_it_is_never_cut_for_want_of_one(self):
        self.assertEqual(self.said(keys(15.0, seed=2)), [])
        self.assertEqual(self.said(hiss(15.0, 2000.0)), [])
        self.assertFalse(self.watch.heard)

    def test_a_click_or_two_taken_for_speech_is_no_voice(self):
        sound = hiss(10.0, 600.0)
        for at in (1.0, 2.0, 3.0):                                 # each of one piece: no run of them
            sound[int(at * RATE):int(at * RATE) + PIECE_OF_SPEECH] += speaking(PIECE_OF_SPEECH / RATE)
        self.assertEqual(self.said(sound), [])
        self.assertFalse(self.watch.heard)

    def test_talking_with_short_gaps_in_it_is_not_cut_and_with_a_long_one_is(self):
        sound = hiss(12.0, 600.0)
        for start in (0.0, 2.6, 5.2, 7.8):                         # four stretches, 0.6 s apart
            sound[int(start * RATE):int((start + 2.0) * RATE)] += speaking(2.0)
        self.assertEqual(self.said(sound[:int(9.8 * RATE)]), [])
        sound = hiss(12.0, 600.0)
        for start in (0.0, 3.0):                                   # two stretches, a second apart
            sound[int(start * RATE):int((start + 2.0) * RATE)] += speaking(2.0)
        said = self.said(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertLess(said[0][0], 3.0)

    def test_a_voice_that_begins_well_into_the_rooms_noise_is_said_to_have_begun_late(self):
        sound = keys(12.0, seed=4)
        sound[6 * RATE:9 * RATE] += speaking(3.0)
        said = self.said(sound)
        self.assertEqual([what for _, what in said], [BEGAN_LATE, GONE])
        self.assertTrue(6.0 < said[0][0] <= 6.35, said)            # within a look or two of its start
        self.assertTrue(9.0 + WAIT <= said[1][0] < 9.0 + WAIT + 0.3, said)

    def test_a_voice_that_begins_the_phrase_did_not_begin_late(self):
        sound = hiss(6.0, 600.0)
        sound[:2 * RATE] += speaking(2.0)
        self.assertEqual([what for _, what in self.said(sound)], [GONE])

    def test_in_a_quiet_room_too_the_voice_is_seen(self):
        sound = np.concatenate([speaking(2.0), np.zeros(4 * RATE, np.float32)])
        self.assertEqual([what for _, what in self.said(sound)], [GONE])

    def test_other_people_talking_far_more_softly_do_not_hold_the_phrase_open(self):
        sound = hiss(12.0, 30.0)
        sound += speaking(12.0, 300.0)                             # talk in the background, all through
        sound[:3 * RATE] += speaking(3.0, 3000.0)                  # and three seconds said at the microphone
        said = self.said(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertTrue(3.0 + VoiceWatch.SOFT_AFTER <= said[0][0] < 3.0 + VoiceWatch.SOFT_AFTER + 0.3, said)
        # It was talk that went on, so nothing after the voice is to be left out of the
        # phrase: it might have been the same person, in an aside.
        self.assertTrue(self.watch.soft)

    def test_a_soft_end_to_a_word_is_part_of_the_voice(self):
        # The last sound of a word may be far softer than the rest of it. The wait is
        # counted from the end of that, and what is kept of the phrase reaches it.
        sound = hiss(8.0, 30.0)
        sound[:2 * RATE] += speaking(2.0, 3000.0)
        sound[2 * RATE:int(2.3 * RATE)] += speaking(0.3, 300.0)
        said = self.said(sound)
        self.assertTrue(2.3 + WAIT <= said[0][0] < 2.3 + WAIT + 0.25, said)
        self.assertFalse(self.watch.soft)
        since = self.watch.frames_since_voice() / self.watch.per_second
        self.assertAlmostEqual(self.watch.frames / self.watch.per_second - since, 2.3, delta=0.1)

    def test_talk_nearly_as_loud_as_the_voice_is_taken_for_the_voice_going_on(self):
        sound = hiss(12.0, 30.0)
        sound += speaking(12.0, 1500.0)                            # half as loud: who is to say
        sound[:3 * RATE] += speaking(3.0, 3000.0)
        self.assertEqual(self.said(sound), [])

    def test_somebody_whose_voice_is_soft_from_the_start_is_heard_to_the_end(self):
        sound = hiss(12.0, 30.0)
        sound[:6 * RATE] += speaking(6.0, 250.0)                   # all of it soft: that is its voice
        said = self.said(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertGreaterEqual(said[0][0], 6.0 + WAIT)
        self.assertFalse(self.watch.soft)

    def test_it_is_shown_the_sound_turned_up_and_measures_it_as_it_came(self):
        seen = []

        def detector(sound):
            seen.append(float(np.max(np.abs(sound))))
            return whistle_detector(sound)
        sound = hiss(4.0, 3.0)
        sound[:2 * RATE] += speaking(2.0, 60.0)                    # very quiet at the microphone
        watch = VoiceWatch(detector=detector)
        self.assertEqual([what for _, what in watched(sound, watch=watch)], [GONE])
        self.assertTrue(all(0.05 < peak <= config.NORMALISE_PEAK + 1e-6 for peak in seen), seen[:3])
        self.assertLess(watch._loud, 0.01)                         # the loudness is as it came

    def test_it_is_given_the_start_of_the_phrase_that_was_kept_from_before(self):
        # A quarter of a second said, of which the phrase had been going for only the
        # last twentieth: without the frames kept from before, that is all the watch has.
        sound = keys(6.0)
        sound[RATE:int(1.25 * RATE)] += speaking(0.25, 1500.0)
        every = list(frames(sound))
        begins = int(1.2 * RATE) // FRAME                      # the frame at which the phrase starts
        for kept, heard in ((every[begins - 15:begins], True), ((), False)):
            watch = VoiceWatch(detector=whistle_detector)
            watch.start(len(kept), kept)
            seen = [watch.feed(frame) for frame in every[begins:begins + 100]]
            self.assertEqual((watch.heard, GONE in seen), (heard, heard), len(kept))

    def test_a_phrase_cut_down_to_its_end_is_counted_from_there(self):
        watch = VoiceWatch(detector=whistle_detector)
        watch.start(15)
        self.assertEqual((watch.frames, watch.heard, watch.frames_since_voice(), watch.soft),
                         (15, False, 0, False))
        watch.heard = True
        watch.began_at(75)
        self.assertEqual((watch.frames, watch.frames_since_voice()), (75, 0))


class TheEnginesListeningLoop(unittest.TestCase):
    """Engine._listen, which feeds the microphone to the segmenter and the watch and cuts
    the phrases: given a sound in place of a microphone."""

    def heard(self, sound):
        """The phrases the engine cuts from `sound`, in seconds each, and what the log said."""
        from dictation import engine as engine_module
        from tests.test_engine_telling import bare
        engine = bare()
        engine.boost = 1.0
        engine._recorder = None                               # so that its ending is nobody's fault
        data = sound.astype("<i2").tobytes()
        at = [0]

        def read(count):
            piece = data[at[0]:at[0] + count]
            at[0] += count
            return piece
        recorder = mock.Mock()
        recorder.read.side_effect = read
        with mock.patch.object(engine_module.speech, "VoiceWatch",
                               lambda: VoiceWatch(detector=whistle_detector)), \
                mock.patch.object(engine_module, "log") as log, mock.patch.object(engine, "_hearing"):
            engine._listen(recorder)
        phrases = []
        while not engine._phrases.empty():
            kind, audio = engine._phrases.get()
            phrases.append(round(len(audio) / RATE, 2))
        return phrases, [call.args[0] for call in log.call_args_list]

    def test_a_phrase_in_a_noisy_room_is_ended_soon_after_the_voice_and_cut_just_past_it(self):
        sound = np.concatenate([hiss(1.0, 20.0), keys(8.0, 3000.0)])
        sound[RATE:3 * RATE] += speaking(2.0)                 # two seconds said, as the keys begin
        phrases, said = self.heard(sound)
        # What was kept from before it, the two seconds, and a little after: no more.
        kept = config.PREROLL_FRAMES * FRAME / RATE + 2.0 + VoiceWatch.AFTER
        self.assertAlmostEqual(phrases[0], kept, delta=0.15)
        self.assertIn("the voice in it had stopped, though the sound went on", said[0])

    def test_when_what_goes_on_is_far_softer_talk_none_of_it_is_left_out(self):
        sound = hiss(9.0, 20.0)
        sound[RATE:] += speaking(8.0, 300.0)                  # talk in the background, from then on
        sound[RATE:3 * RATE] += speaking(2.0, 3000.0)         # and two seconds said at the microphone
        phrases, said = self.heard(sound)
        whole = config.PREROLL_FRAMES * FRAME / RATE + 2.0 + VoiceWatch.SOFT_AFTER
        self.assertTrue(whole <= phrases[0] < whole + 0.3, phrases)   # all of it, up to where it was ended
        self.assertIn("the talking in it had gone far softer", said[0])


class AskingTheDetectorPieceByPiece(unittest.TestCase):
    """speech.likelihoods(): the detector that comes with the speech packages."""

    def setUp(self):
        for name in ("_no_pieces", "_piece_failures", "_unusable", "_failures"):
            self.addCleanup(setattr, speech, name, getattr(speech, name))
        speech._no_pieces, speech._piece_failures = False, 0

    def have(self, model):
        """Stand a detector in for the one in the speech packages."""
        vad = types.ModuleType("faster_whisper.vad")
        vad.get_vad_model = lambda: model
        package = types.ModuleType("faster_whisper")
        package.vad = vad
        patch = mock.patch.dict(sys.modules, {"faster_whisper": package, "faster_whisper.vad": vad})
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_answers_for_each_whole_piece_and_the_last_ends_where_the_sound_ends(self):
        given = []

        def model(sound):
            given.append(sound.copy())
            return np.linspace(0.1, 0.9, len(sound) // PIECE_OF_SPEECH).reshape(-1, 1)
        self.have(model)
        sound = np.arange(3 * PIECE_OF_SPEECH + 100, dtype=np.float32) / 1e4
        marks = speech.likelihoods(sound)
        self.assertEqual(marks.shape, (3,))
        self.assertTrue(np.array_equal(given[0], sound[100:]))     # what is over, at the start, is left out
        self.assertEqual(len(speech.likelihoods(np.zeros(100, dtype=np.float32))), 0)

    def test_without_the_speech_packages_there_is_none_and_it_is_said_once(self):
        with mock.patch.dict(sys.modules, {"faster_whisper": None}), mock.patch("builtins.print") as said:
            self.assertIsNone(speech.likelihoods(np.zeros(PIECE_OF_SPEECH, dtype=np.float32)))
            self.assertIsNone(speech.likelihoods(np.zeros(PIECE_OF_SPEECH, dtype=np.float32)))
        self.assertEqual(said.call_count, 1)
        self.assertIn("pitch", said.call_args[0][0])

    def test_one_that_keeps_failing_is_given_up_and_the_noise_check_goes_on_using_its_own(self):
        calls = []

        def model(sound):
            calls.append(1)
            raise RuntimeError("no memory")
        self.have(model)
        with mock.patch("builtins.print") as said:
            for _ in range(speech.MOST_FAILURES + 3):
                self.assertIsNone(speech.likelihoods(np.zeros(PIECE_OF_SPEECH, dtype=np.float32)))
        self.assertEqual(len(calls), speech.MOST_FAILURES)         # and then not asked again
        self.assertEqual(said.call_count, 1)
        self.assertFalse(speech._unusable)                         # spoken() is not given up with it

    def test_an_answer_of_the_wrong_length_is_a_failure(self):
        self.have(lambda sound: np.ones(1))
        self.assertIsNone(speech.likelihoods(np.zeros(4 * PIECE_OF_SPEECH, dtype=np.float32)))
        self.assertEqual(speech._piece_failures, 1)


class ThePhraseIsCutFromOutside(unittest.TestCase):
    def test_cut_ends_the_phrase_and_leaves_the_room_as_it_was_taken_to_be(self):
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        unsteady = [900, 900, 900, 400, 900, 900, 500, 900, 900, 400] * 10   # no fan: it rises and falls
        events = [s.feed(level) for level in [40] * 50 + [2000, 2000, 2000, 400] * 12 + unsteady]
        self.assertEqual([e for e in events if e], [START])
        before = s.noise
        self.assertEqual(s.cut(), END)
        self.assertEqual((s.in_phrase, s.ended_by, s.noise), (False, NO_VOICE, before))
        self.assertEqual((s.voice_was > 0, s.tail_was), (True, 900))
        self.assertEqual(s.cut(), "")                     # there is nothing to cut twice

    def test_a_phrase_with_no_voice_in_it_that_ran_to_the_limit_was_the_room(self):
        import random
        random.seed(8)
        # A noise that rises and falls, louder than the room was taken to be: it starts a
        # phrase that runs to the limit, and then another, and another.
        noise = [180 * random.choice((0.5, 0.8, 1.0, 1.4, 1.9)) for _ in range(3000)]
        s = Segmenter(SegmenterConfig(warmup_ms=0, min_level=60, ratio=2.5))
        endings = 0
        for level in [40] * 100 + noise[:1100]:
            if s.feed(level) == END:
                endings += 1
        self.assertEqual((endings, s.ended_by), (1, "limit"))
        before = s.threshold
        s.was_the_room()                                   # the engine saw no voice in it
        self.assertGreater(s.threshold, before)
        started = sum(1 for level in noise[1100:] if s.feed(level) == START)
        self.assertLessEqual(started, 2)                   # it no longer starts one phrase after another
        for level in [40] * 200:                           # and when the room is quiet again
            s.feed(level)
        self.assertLess(s.threshold, before + 1)           # it is taken to be quiet again

    def test_a_phrase_cut_down_to_its_end_has_its_limit_counted_from_there(self):
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        unsteady = [900, 900, 900, 400, 900, 900, 500, 900, 900, 400]
        for level in [40] * 50 + unsteady * 90:           # eighteen seconds of a room that rises and falls
            s.feed(level)
        self.assertTrue(s.in_phrase)
        s.began_again(75)                                  # a voice began: only the last 1.5 s is kept
        events = [s.feed(level) for level in unsteady * 50]  # ten seconds more
        self.assertEqual([e for e in events if e], [])     # which the old count would have cut at two


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
import wave
from unittest import mock

from dictation import settings, training
from dictation.trainer import words as single


def day(folder, name, texts, seconds=1.0):
    path = os.path.join(folder, name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, training.SAID), "a", encoding="utf-8") as said:
        for at, text in enumerate(texts, 1):
            with wave.open(os.path.join(path, f"{at:03d}.wav"), "wb") as sound:
                sound.setnchannels(1)
                sound.setsampwidth(2)
                sound.setframerate(16000)
                sound.writeframes(b"\0\0" * int(16000 * seconds))
            said.write(f"{at:03d}\t{text}\n")
    return path


class WhatThereIsToTrainOn(unittest.TestCase):
    def test_a_folder_of_days_or_a_day_by_itself(self):
        folder = tempfile.mkdtemp()
        first = day(folder, "2026-01-01", ["One two.", "Three four."])
        day(folder, "2026-01-02", ["Five six."], seconds=2.0)
        os.makedirs(os.path.join(folder, "not-a-day"))
        self.assertEqual([os.path.basename(d) for d in training.day_folders(folder)],
                         ["2026-01-01", "2026-01-02"])
        self.assertEqual([text for _, text in training.sentences(folder)],
                         ["One two.", "Three four.", "Five six."])
        self.assertEqual(training.found(folder), (3, 4.0))
        self.assertEqual(training.found(first), (2, 2.0))  # one day chosen by itself

    def test_a_line_without_its_sound_is_left_out_and_nothing_is_nothing(self):
        folder = tempfile.mkdtemp()
        path = day(folder, "a", ["Kept.", "Lost."])
        os.remove(os.path.join(path, "002.wav"))
        self.assertEqual([text for _, text in training.sentences(folder)], ["Kept."])
        self.assertEqual(training.found(tempfile.mkdtemp()), (0, 0.0))
        self.assertEqual(training.found(os.path.join(folder, "no such place")), (0, 0.0))

    def test_the_split_is_whole_and_always_the_same(self):
        train, choose, test = training.split(300)
        self.assertEqual((len(train), len(choose), len(test)), (225, 25, 50))
        self.assertEqual(sorted(train + choose + test), list(range(300)))
        self.assertEqual(training.split(300), (train, choose, test))
        self.assertEqual(training.split(3), ([0, 1, 2], [], []))

    def test_every_reading_of_a_text_goes_the_same_way(self):
        once = [f"Sentence {n}." for n in range(60)]
        self.assertEqual(training.split_of(once), training.split(60))
        twice = once + once  # the text read through a second time
        train, choose, test = training.split_of(twice)
        self.assertEqual(sorted(train + choose + test), list(range(120)))
        for part in (train, choose, test):
            self.assertEqual(len(part) % 2, 0)
        self.assertFalse({twice[at] for at in test} & {twice[at] for at in train + choose})
        self.assertEqual({twice[at] for at in test}, {once[at] for at in training.split(60)[2]})

    def test_words_wrong(self):
        self.assertEqual(training.wrong("A big bag of pegs.", "a big bag of pigs"), 1)
        self.assertEqual(training.wrong("See you to-morrow", "see you tomorrow"), 0)
        self.assertEqual(training.wrong("one two three", "one three"), 1)


class WhatItIsCalled(unittest.TestCase):
    def test_the_folder_name_carries_the_name(self):
        base = training.BY_KEY["parakeet-v2"]
        self.assertEqual(training.slug("  My Voice, November! "), "my-voice-november")
        self.assertEqual(training.model_folder(base, "My voice"), base.folder + "-mine-my-voice")
        self.assertEqual(training.name_problem("My voice"), "")
        self.assertTrue(training.name_problem("   "))
        self.assertTrue(training.name_problem("!!!"))

    def test_a_model_made_here_is_listed_by_its_name(self):
        models = tempfile.mkdtemp()
        base = training.BY_KEY["parakeet-v2"]
        mine = training.model_folder(base, "Evening voice")
        for name in (mine, base.folder):
            os.makedirs(os.path.join(models, name))
            for part in ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"):
                open(os.path.join(models, name, part), "w").close()
        with open(os.path.join(models, mine, training.ABOUT), "w") as f:
            json.dump({"name": "Evening voice", "base": base.key}, f)
        listed = dict(settings.available_models(models))
        self.assertTrue(listed[mine].startswith("Evening voice: Parakeet v2 retrained to your voice"))
        self.assertTrue(listed[base.folder].startswith("Parakeet"))
        self.assertEqual(training.label(models, base.folder), "")


class WhatCanBeRetrained(unittest.TestCase):
    def test_each_has_its_checkpoint_and_its_loss_and_its_own_folder(self):
        self.assertEqual([base.key for base in training.BASES], ["parakeet-unified", "parakeet-v2"])
        for base in training.BASES:
            self.assertIn(base.loss, ("tdt", "rnnt"))
            self.assertTrue(base.file.endswith(".nemo"))
            self.assertTrue(training.model_folder(base, "Mine").startswith(base.folder + "-mine-"))
        folders = [training.model_folder(base, "Mine") for base in training.BASES]
        self.assertEqual(len(set(folders)), len(folders))


class ARun(unittest.TestCase):
    def setUp(self):
        self.job = training.Job(os.path.join(tempfile.mkdtemp(), "run"))

    def test_notes_are_added_to_and_read_back(self):
        self.job.note(state="training", pid=os.getpid(), passes=10)
        self.job.note(**{"pass": 3}, batch=5, batches=50)
        said = self.job.status()
        self.assertEqual((said["state"], said["pass"], said["passes"]), ("training", 3, 10))
        self.assertTrue(self.job.running())

    def test_a_run_that_has_gone_is_said_to_have_failed(self):
        self.job.note(state="training", pid=2 ** 22 + 12345, started=0)  # nobody's number
        said = self.job.status()
        self.assertEqual(said["state"], "failed")
        self.assertIn(self.job.log, said["error"])
        self.assertFalse(self.job.running())

    def test_a_run_just_started_is_given_time_to_say_it_is_there(self):
        self.job.note(state="starting", pid=0, started=1000.0)
        self.assertEqual(self.job.status(now=1050.0)["state"], "starting")
        self.assertEqual(self.job.status(now=1000.0 + training.Job.GRACE + 1)["state"], "failed")

    def test_a_run_begun_afresh_forgets_the_last_and_one_carried_on_does_not(self):
        with mock.patch.object(training, "python", lambda: "py"), \
                mock.patch.object(training.subprocess, "Popen") as started:
            base = training.BASES[0]
            self.job.note(state="done", finished=3, before={"wrong": 6}, after={"wrong": 6})
            self.job.start("/data", base, "Mine", resume=True)
            self.assertEqual(self.job._read().get("finished"), 3)
            self.job.start("/data", base, "Mine")
            said = self.job._read()
            self.assertEqual((said["state"], said.get("finished"), said.get("before")), ("starting", None, None))
            self.assertEqual(started.call_count, 2)

    def test_stopping_is_a_file_the_run_looks_for(self):
        self.job.stop()
        self.assertTrue(os.path.exists(self.job.stop_file))

    def test_no_notes_is_no_run(self):
        self.assertEqual(self.job.status(), {})
        self.assertFalse(self.job.running())

    def test_the_latest_run(self):
        with mock.patch.object(training, "RUNS", tempfile.mkdtemp()):
            self.assertIsNone(training.latest())
            one, two = (training.Job(os.path.join(training.RUNS, n)) for n in ("one", "two"))
            one.note(state="done")
            two.note(state="stopped")
            os.utime(one.notes, (1, 1))
            self.assertEqual(training.latest().folder, two.folder)

    def test_the_command_runs_the_trainer_apart_and_at_low_priority(self):
        base = training.BY_KEY["parakeet-v2"]
        with mock.patch("shutil.which", lambda name: "/usr/bin/" + name):
            made = training.command("/t/venv/bin/python", "/data", base, "My voice", "/job", resume=True)
        self.assertEqual(made[:3], ["systemd-run", "--user", "--scope"])
        self.assertIn("nice", made)
        at = made.index("/t/venv/bin/python")
        self.assertEqual(made[at:at + 4], ["/t/venv/bin/python", "-u", "-m", "dictation.trainer"])
        self.assertEqual(made[made.index("--name") + 1], "My voice")
        self.assertEqual(made[-1], "--resume")
        with mock.patch("shutil.which", lambda name: None):
            self.assertEqual(training.command("py", "/data", base, "x", "/job")[0], "py")

    def test_memory(self):
        self.assertEqual(training.memory_problem(20.0), "")
        self.assertIn("8 GB is free", training.memory_problem(8.0))


class SingleWords(unittest.TestCase):
    """Cut out of sentences, to be learned from with nothing round them."""
    PIECES = [" The", " p", "en", " is", " on", " the", " des", "k", "."]
    TIMES = [0.20, 0.40, 0.48, 0.80, 0.96, 1.10, 1.30, 1.50, 1.70]
    LASTS = [0.16, 0.08, 0.24, 0.16, 0.08, 0.16, 0.16, 0.16, 0.08]

    def test_pieces_are_put_together_into_words_with_their_times(self):
        heard = single.spans(self.PIECES, self.TIMES, self.LASTS)
        self.assertEqual([w for w, _, _ in heard], ["The", "pen", "is", "on", "the", "desk."])
        self.assertEqual(heard[1][1], 0.40)
        self.assertAlmostEqual(heard[1][2], 0.72)

    def test_only_the_words_worth_cutting_out_and_each_up_to_the_next(self):
        heard = single.spans(self.PIECES, self.TIMES, self.LASTS)
        found = single.pieces_of("The pen is on the desk.", heard, 2.5)
        self.assertEqual([w for w, _, _ in found], ["pen", "desk"])  # not the little words
        word, start, end = found[0]
        self.assertAlmostEqual(start, 0.40 - single.LEAD)
        self.assertEqual(end, 0.80)  # where "is" begins
        self.assertAlmostEqual(found[1][2], 1.78 + single.LAST)  # the last runs on a little
        self.assertAlmostEqual(single.pieces_of("The pen is on the desk.", heard, 1.9)[1][2], 1.9)

    def test_a_sentence_not_written_word_for_word_is_left_alone(self):
        heard = single.spans(self.PIECES, self.TIMES, self.LASTS)
        self.assertEqual(single.pieces_of("The pin is on the desk.", heard, 2.5), [])
        self.assertEqual(single.pieces_of("The pen is on the big desk.", heard, 2.5), [])

    def test_a_word_too_short_or_too_long_to_be_a_clean_cut_is_left_out(self):
        heard = single.spans([" Pen", " desk"], [0.0, 0.1], [0.08, 0.08])
        self.assertEqual([w for w, _, _ in single.pieces_of("Pen desk", heard, 5.0)], ["desk"])
        heard = single.spans([" Pen", " desk"], [0.0, 2.0], [0.08, 0.08])
        self.assertEqual([w for w, _, _ in single.pieces_of("Pen desk", heard, 5.0)], ["desk"])


class InstallingTheTools(unittest.TestCase):
    def setUp(self):
        self.install = training.Install(tempfile.mkdtemp())

    def note(self, pid):
        with open(self.install.notes, "w") as f:
            json.dump({"pid": pid, "started": 0}, f)

    def test_never_started_it_is_nothing_or_done_as_the_tools_are_there_or_not(self):
        with mock.patch.object(training, "python", lambda: ""):
            self.assertEqual(self.install.state(), "")
        with mock.patch.object(training, "python", lambda: "/t/python"):
            self.assertEqual(self.install.state(), "done")  # put there some other way

    def test_while_its_process_lives_it_is_installing(self):
        self.note(os.getpid())
        self.assertEqual(self.install.state(), "installing")

    def test_ended_it_is_done_only_if_it_said_so_and_the_tools_are_there(self):
        self.note(2 ** 22 + 12345)  # nobody's number
        with open(self.install.log, "w") as f:
            f.write("== PyTorch\r\nDownloading torch (110MiB)\r\n")
        with mock.patch.object(training, "python", lambda: "/t/python"):
            self.assertEqual(self.install.state(), "failed")  # it stopped part of the way
        self.assertEqual(self.install.last_line(), "Downloading torch (110MiB)")
        with open(self.install.log, "a") as f:
            f.write('== Done. Open Settings and press "Train on my voice".\n\n')
        with mock.patch.object(training, "python", lambda: ""):
            self.assertEqual(self.install.state(), "failed")
        with mock.patch.object(training, "python", lambda: "/t/python"):
            self.assertEqual(self.install.state(), "done")

    def test_the_script_is_the_one_for_this_system(self):
        with mock.patch.object(training.config, "WINDOWS", False):
            made = training.install_command()
            self.assertEqual(made[0], "bash")
            self.assertTrue(made[-1].endswith(os.path.join("scripts", "install-training.sh")))
            self.assertTrue(os.path.exists(made[-1]))
        with mock.patch.object(training.config, "WINDOWS", True):
            made = training.install_command()
            self.assertEqual(made[0], "powershell.exe")
            self.assertTrue(os.path.exists(made[-1]))

    def test_room_on_the_disk(self):
        self.assertEqual(training.room_problem(40e9), "")
        self.assertIn("5 GB is free", training.room_problem(5e9))


class SayingHowItGoes(unittest.TestCase):
    def test_each_stage_has_its_words_and_the_bar_only_goes_forward(self):
        stages = [{"state": "starting"}, {"state": "cutting"}, {"state": "fetching"},
                  {"state": "listening"},
                  {"state": "training", "pass": 1, "batch": 1, "batches": 50, "passes": 10},
                  {"state": "training", "pass": 5, "batch": 25, "batches": 50, "passes": 10,
                   "pass_seconds": 400.0},
                  {"state": "training", "pass": 10, "batch": 50, "batches": 50, "passes": 10},
                  {"state": "exporting", "passes": 10, "finished": 10},
                  {"state": "comparing", "passes": 10, "finished": 10},
                  {"state": "done", "name": "My voice", "base": "parakeet-v2",
                   "before": {"wrong": 9, "words": 600, "sentences": 50, "near": 20},
                   "after": {"wrong": 4, "words": 600, "sentences": 50, "near": 6}}]
        bars = [training.fraction(said) for said in stages]
        self.assertEqual(bars, sorted(bars))
        self.assertEqual(bars[-1], 1.0)
        for said in stages:
            self.assertTrue(training.describe(said)[0], said)
        self.assertEqual(training.describe(stages[5])[0], "Training: pass 5 of 10")
        # Five and a half passes to go at 400 s, and the making and comparing after them.
        self.assertEqual(training.time_left(stages[5]), 5.5 * 400 + training.TAIL_SECONDS)
        self.assertIn("to go", training.describe(stages[5])[1])
        self.assertIsNone(training.time_left(stages[4]))
        headline, detail = training.describe(stages[-1])
        self.assertIn("My voice", headline)
        self.assertIn("9 of 600 words wrong, and retrained 4", detail)
        self.assertIn("20 before, 6 after", detail)
        self.assertNotIn("single words", detail)
        with_words = dict(stages[-1], before=dict(stages[-1]["before"], alone=127, alone_of=228),
                          after=dict(stages[-1]["after"], alone=182, alone_of=228))
        self.assertIn("Of 228 single words cut from them: 127 right before, 182 after.",
                      training.describe(with_words)[1])

    def test_stopped_and_failed(self):
        said = {"state": "stopped", "finished": 3, "passes": 10}
        self.assertIn("3 of 10 passes are done and kept", training.describe(said)[1])
        self.assertAlmostEqual(training.fraction(said), 0.05 + 0.85 * 0.3)
        self.assertEqual(training.describe({"state": "failed", "error": "No room."}),
                         ("It could not be finished.", "No room."))
        self.assertEqual(training.describe({}), ("", ""))

    def test_time_in_words(self):
        self.assertEqual(training.time_text(20), "1 min")
        self.assertEqual(training.time_text(59 * 60), "59 min")
        self.assertEqual(training.time_text(3600), "1 h")
        self.assertEqual(training.time_text(75 * 60), "1 h 15 min")


if __name__ == "__main__":
    unittest.main()

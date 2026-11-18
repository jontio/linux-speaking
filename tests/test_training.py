import json
import os
import sys
import tempfile
import time
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
        # In words only: the window says what to try, and has a button for the log.
        self.assertEqual(said["error"], "The training stopped without saying why.")
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
        self.assertIn("--name=My voice", made)
        # A name that begins with a dash is still a name, to the trainer and to the window.
        self.assertIn("--name=-odd", training.command("py", "/data", base, "-odd", "/job"))
        self.assertTrue(training.name_problem("-odd"))
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
        with mock.patch.object(training.config, "WINDOWS", False), \
                mock.patch("shutil.which", lambda name: None):
            made = training.install_command()
            self.assertEqual(made[0], "bash")
        with mock.patch.object(training.config, "WINDOWS", False), \
                mock.patch("shutil.which", lambda name: "/usr/bin/" + name):
            made = training.install_command()   # apart from the app, where the desktop can
            self.assertEqual(made[:3] + made[-2:-1], ["systemd-run", "--user", "--scope", "bash"])
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


class StillGoing(unittest.TestCase):
    """Whether a process the app started is still at work."""

    @unittest.skipIf(os.name == "nt", "how Linux keeps an ended process on the books")
    def test_one_that_has_ended_is_not_taken_for_alive(self):
        import subprocess
        import time
        ended = subprocess.Popen(["true"])
        for _ in range(200):               # it ends, and stays on the books until asked after
            with open(f"/proc/{ended.pid}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                    break
            time.sleep(0.01)
        self.assertFalse(training._alive(ended.pid))
        ended.wait()

    def test_this_one_is(self):
        import time
        self.assertTrue(training._alive(os.getpid()))
        self.assertTrue(training._alive(os.getpid(), time.time()))

    def test_a_number_now_held_by_a_later_process_is_not_ours(self):
        import time
        born = training._born(os.getpid())
        if born is None:
            self.skipTest("this system doesn't say when a process was started")
        self.assertLess(abs(born - time.time()), 3600)
        self.assertFalse(training._alive(os.getpid(), born - training.LATE - 60))

    def test_an_install_seen_to_have_ended_is_not_asked_after_again(self):
        install = training.Install(tempfile.mkdtemp())
        with open(install.notes, "w") as f:
            json.dump({"pid": 2 ** 22 + 12345, "started": 0}, f)
        with open(install.log, "w") as f:
            f.write("== Done.\n")
        with mock.patch.object(training, "python", lambda: "/t/python"):
            self.assertEqual(install.state(), "done")
            with open(install.notes) as f:
                self.assertTrue(json.load(f)["ended"])
            with mock.patch.object(training, "_alive", lambda *a: True):   # the number, reused
                self.assertEqual(install.state(), "done")

    def test_tools_whose_install_failed_are_not_ready(self):
        folder = tempfile.mkdtemp()
        with mock.patch.object(training, "python", lambda: "/t/python"), \
                mock.patch.object(training.config, "STATE_FILE", os.path.join(folder, "state")):
            self.assertTrue(training.ready())                        # put there some other way
            with open(os.path.join(folder, "training-install.json"), "w") as f:
                json.dump({"pid": 2 ** 22 + 12345, "started": 0}, f)
            self.assertFalse(training.ready())                       # it stopped part of the way

    @unittest.skipIf(os.name == "nt", "there, when a process was made is written down once and kept")
    def test_the_clock_put_forward_does_not_make_a_run_that_is_going_seem_to_have_failed(self):
        import subprocess
        import time
        going = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(going.wait)
        self.addCleanup(going.kill)
        job = training.Job(os.path.join(tempfile.mkdtemp(), "run"))
        job.note(state="training", pid=going.pid, started=time.time())   # as the trainer notes itself
        if not job._read().get("born"):
            self.skipTest("this system doesn't say what tells one process from the next")
        real = training._born
        # The clock is put forward an hour: when the computer started, as it is worked
        # out from the clock, moves with it, and so does when every process was born.
        now = time.time
        with mock.patch.object(training, "_born", lambda pid: real(pid) + 3600), \
                mock.patch("time.time", lambda: now() + 3600):
            self.assertEqual(job.status()["state"], "training")
            self.assertTrue(job.running())
            job.discard()                                            # which is for runs that are over
        self.assertTrue(os.path.exists(job.folder))

    def test_a_number_that_has_passed_to_another_process_is_told_by_its_mark(self):
        import time
        mine = training._mark(os.getpid())
        if not mine:
            self.skipTest("this system doesn't say what tells one process from the next")
        self.assertEqual(mine, training._mark(os.getpid()))          # the same for as long as it lives
        self.assertTrue(training._alive(os.getpid(), time.time(), mine))
        # Ours had the number before the computer was last started, or earlier in this run of it.
        self.assertFalse(training._alive(os.getpid(), time.time(), "another-start-of-the-computer:12345"))
        job = training.Job(os.path.join(tempfile.mkdtemp(), "run"))
        job.note(state="training", pid=os.getpid(), started=time.time())
        with open(job.notes) as f:
            said = json.load(f)
        self.assertEqual(said["born"], mine)                         # noted with the number, by itself
        with open(job.notes, "w") as f:
            json.dump(dict(said, born=mine + "0"), f)
        self.assertEqual(job.status()["state"], "failed")
        self.assertEqual(training._mark(0), "")
        self.assertEqual(training._mark("abc"), "")


class DamagedNotes(unittest.TestCase):
    """The notes are a file like any other. Whatever is in them, the window opens."""

    def setUp(self):
        self.runs = tempfile.mkdtemp()
        patch = mock.patch.object(training, "RUNS", self.runs)
        patch.start()
        self.addCleanup(patch.stop)
        self.job = training.Job(os.path.join(self.runs, "run"))
        os.makedirs(self.job.folder)

    def write(self, said):
        with open(self.job.notes, "w") as f:
            f.write(said if isinstance(said, str) else json.dumps(said))

    def test_a_process_number_that_is_not_one_is_never_asked_after(self):
        asked, real = [], os.waitpid if hasattr(os, "waitpid") else None

        def waitpid(pid, options):
            asked.append(pid)
            return real(pid, options)

        for odd in (2 ** 70, -1, 0, "abc", 1.5, True, None, [7], {"a": 1}, 2 ** 31):
            self.write({"state": "training", "pid": odd, "started": 0})
            with mock.patch("os.waitpid", waitpid, create=True):
                self.assertEqual(self.job.status()["state"], "failed", odd)
                self.assertFalse(self.job.running())
                training.unfinished()
                self.assertEqual(training.latest().folder, self.job.folder)
            self.assertFalse(training._alive(odd), odd)
        self.assertEqual(asked, [])                                  # a negative one would mean every process

    def test_a_start_that_is_not_a_time_and_figures_that_are_not_figures(self):
        for odd in ({"started": "yesterday"}, {"started": None}, {"started": [1]}, {"started": float("nan")},
                    {"pass": "x", "passes": None, "batch": [], "batches": {}, "finished": "2"},
                    {"pass_seconds": "long", "state": "training"}, {"error": 7, "name": ["a"]},
                    {"before": "x", "after": {"wrong": "a", "words": 3}, "state": "done"},
                    {"before": {"wrong": 1}, "after": {"wrong": 1, "words": 3}, "state": "done"}):
            for state in ("starting", "training", "stopped", "failed", "done"):
                self.write({"state": state, "pid": os.getpid(), **odd})
                said = self.job.status()
                training.fraction(said), training.time_left(said), training.describe(said)
                training.unfinished(), training.latest()
        self.write({"state": "starting", "pid": 0, "started": "yesterday"})
        self.assertEqual(self.job.status()["state"], "failed")

    def test_notes_that_are_not_notes_at_all(self):
        for odd in ("", "{", "[1, 2]", '"training"', "null", "\x00\x00"):
            self.write(odd)
            self.assertEqual(self.job.status(), {}, odd)
            self.assertFalse(self.job.running())
            training.unfinished(), training.latest()

    def test_the_trainer_goes_on_from_notes_with_odd_things_in_them(self):
        self.write({"state": "training", "pid": "abc", "pass": "x", "name": "Mine"})
        said = self.job.note(batch=3)
        self.assertEqual((said["name"], said["batch"]), ("Mine", 3))
        self.assertNotIn("pass", said)

    def test_install_notes_that_cannot_be_made_out_are_not_taken_for_a_finished_install(self):
        install = training.Install(self.runs)
        for odd in ('{"pid": 12', "[]", '{"pid": -1}', '{"pid": "abc", "started": "x"}', '{"pid": 1e400}'):
            with open(install.notes, "w") as f:
                f.write(odd)                                         # as half written, or damaged
            with mock.patch.object(training, "python", lambda: "/t/python"), \
                    mock.patch.object(training.config, "STATE_FILE", os.path.join(self.runs, "state")):
                self.assertEqual(install.state(), "failed", odd)
                self.assertFalse(training.ready(), odd)

    def test_install_notes_are_put_in_place_whole_or_not_at_all(self):
        install = training.Install(self.runs)
        with open(install.notes, "w") as f:
            json.dump({"pid": 2 ** 22 + 12345, "started": 0, "ended": True}, f)
        started = mock.Mock(pid=os.getpid())
        with mock.patch.object(training.subprocess, "Popen", return_value=started), \
                mock.patch.object(training, "_end") as ended, \
                mock.patch("os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                install.start()
        with open(install.notes) as f:
            self.assertTrue(json.load(f)["ended"])                   # the notes there were, untouched
        self.assertEqual([name for name in os.listdir(self.runs) if name.endswith(".new")], [])
        self.assertEqual(ended.call_args[0][0], os.getpid())         # and nothing is left going unnoted
        with mock.patch.object(training.subprocess, "Popen", return_value=started):
            install.start()
        with open(install.notes) as f:
            said = json.load(f)
        self.assertEqual((said["pid"], said["born"]), (os.getpid(), training._mark(os.getpid())))
        self.assertEqual(install.state(), "installing")


def waited(what, seconds=6.0):
    """Whether what() comes true within `seconds`."""
    until = time.monotonic() + seconds
    while time.monotonic() < until and not what():
        time.sleep(0.05)
    return bool(what())


def gone(pid) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return True


@unittest.skipIf(os.name == "nt", "ending a process and all that came of it is done another way there")
class StoppingWhatWasStarted(unittest.TestCase):
    """Work that goes on apart from the app can be stopped from it, and leaves things tidy."""

    def setUp(self):
        import warnings
        self.folder = tempfile.mkdtemp()
        patch = mock.patch.object(training, "PATIENCE", 0.5)
        patch.start()
        self.addCleanup(patch.stop)
        # What is started here is meant to go on by itself, and nothing keeps hold of it:
        # Python remarks on that, when it comes to clear up, and need not.
        warnings.filterwarnings("ignore", "subprocess .* is still running", ResourceWarning)

    def test_an_install_is_stopped_with_all_it_started_and_is_then_neither_going_nor_failed(self):
        install = training.Install(self.folder)
        # Stands in for the install script: it starts something of its own, as the script
        # starts the programs that do the fetching, and says which.
        script = ("import subprocess, sys, time\n"
                  "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                  "print('== fetching, with', child.pid, flush=True)\n"
                  "time.sleep(60)\n")
        with mock.patch.object(training, "install_command", lambda: [sys.executable, "-c", script]), \
                mock.patch.object(training, "python", lambda: "/t/python"), \
                mock.patch.object(training.config, "STATE_FILE", os.path.join(self.folder, "state")):
            self.assertFalse(install.stop())                         # nothing to stop yet
            install.start()
            self.assertTrue(waited(lambda: "fetching" in install.last_line()))
            child = int(install.last_line().split()[-1])
            with open(install.notes) as f:
                parent = json.load(f)["pid"]
            self.assertEqual(install.state(), "installing")
            self.assertTrue(install.stop())
            self.assertEqual(install.state(), "stopped")             # at once: not "failed"
            self.assertFalse(training.ready())                       # and not ready, though its Python is there
            self.assertTrue(waited(lambda: gone(parent) and gone(child)))
            self.assertFalse(install.stop())                         # nothing to stop any more
            self.assertEqual(install.state(), "stopped")
            install.start()                                          # and it can be started again
            self.assertEqual(install.state(), "installing")
            self.assertTrue(install.stop())

    def run_that_is(self, state, script="import time; time.sleep(60)"):
        """A run started as the window starts one, whose trainer has said it is at `state`."""
        job = training.Job(os.path.join(self.folder, "run"))
        with mock.patch.object(training, "command", lambda *_: [sys.executable, "-c", script]), \
                mock.patch.object(training, "python", lambda: "py"):
            job.start("/data", training.BASES[0], "Mine")
        with open(job.notes) as f:
            pid = json.load(f)["pid"]
        self.addCleanup(lambda: gone(pid) or os.kill(pid, 9))
        self.assertGreater(pid, 0)                                   # known from the first moment
        job.note(state=state)
        self.assertEqual(job.status()["state"], state)
        return job, pid

    def test_a_run_that_is_still_getting_ready_is_ended_at_once_and_can_be_carried_on(self):
        job, pid = self.run_that_is("fetching")                      # 2.5 GB, the first time
        with open(os.path.join(job.folder, "fetched"), "w") as f:
            f.write("what it had")
        job.stop()
        self.assertTrue(waited(lambda: gone(pid)))
        said = job.status()
        self.assertEqual((said["state"], said["error"]), ("stopped", ""))   # not "failed"
        self.assertFalse(job.running())
        self.assertTrue(os.path.exists(os.path.join(job.folder, "fetched")))
        self.assertFalse(job.end())                                  # nothing to end any more
        with mock.patch.object(training, "RUNS", self.folder):
            self.assertEqual(training.latest().status()["state"], "stopped")
        with mock.patch.object(training, "command", lambda *_: [sys.executable, "-c", "pass"]), \
                mock.patch.object(training, "python", lambda: "py"):
            job.start("/data", training.BASES[0], "Mine", resume=True)   # carried on: the past is past
        self.assertFalse(os.path.exists(job.end_file))
        self.assertFalse(os.path.exists(job.stop_file))

    def test_one_that_said_it_failed_because_it_was_told_to_end_is_said_to_have_been_stopped(self):
        job, pid = self.run_that_is("cutting")
        self.assertTrue(job.end())
        self.assertTrue(waited(lambda: gone(pid)))
        job.note(state="failed", error="KeyboardInterrupt: ")        # as the trainer says on its way out
        self.assertEqual(job.status()["state"], "stopped")
        self.assertEqual(training.describe(job.status())[0], "Stopped.")

    def test_one_that_takes_no_notice_of_being_asked_is_made_to_end(self):
        job, pid = self.run_that_is(
            "listening", "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
                         "signal.signal(signal.SIGTERM, signal.SIG_IGN); print('deaf', flush=True); time.sleep(60)")
        def deaf() -> bool:
            try:
                with open(job.log) as f:
                    return "deaf" in f.read()
            except OSError:
                return False

        self.assertTrue(waited(deaf))
        self.assertTrue(job.end())
        self.assertTrue(waited(lambda: gone(pid)))
        self.assertEqual(job.status()["state"], "stopped")

    def test_during_the_passes_it_is_only_asked_and_after_them_it_is_left_to_finish(self):
        for state in ("training", "exporting", "comparing"):
            job, pid = self.run_that_is(state)
            self.assertFalse(job.end())
            job.stop()
            self.assertTrue(os.path.exists(job.stop_file))           # which the trainer looks for
            time.sleep(0.3)
            self.assertFalse(gone(pid))
            self.assertEqual(job.status()["state"], state)
            os.kill(pid, 9)
            self.assertTrue(waited(lambda: gone(pid)))


class RunsThatLostTheirNotes(unittest.TestCase):
    def setUp(self):
        self.runs = tempfile.mkdtemp()
        patch = mock.patch.object(training, "RUNS", self.runs)
        patch.start()
        self.addCleanup(patch.stop)

    def holding(self, name, megabytes=2):
        job = training.Job(os.path.join(self.runs, name))
        os.makedirs(job.folder, exist_ok=True)
        with open(os.path.join(job.folder, "last.pt"), "wb") as f:
            f.truncate(megabytes * 1_000_000)
        return job

    def found(self):
        return [os.path.basename(job.folder) for job, _ in training.unfinished()]

    def test_a_run_begun_afresh_keeps_the_notes_it_had_if_the_new_cannot_be_written(self):
        job = self.holding("one")
        job.note(state="stopped", name="one", pid=0, finished=3)
        real = os.replace

        def full(source, target):         # as after a pass has been kept, and filled the disk
            if target == job.notes:
                raise OSError(28, "No space left on device")
            return real(source, target)

        with mock.patch.object(training, "python", lambda: "py"), \
                mock.patch.object(training.subprocess, "Popen") as started, mock.patch("os.replace", full):
            with self.assertRaises(OSError):
                job.start("/data", training.BASES[0], "one")
        started.assert_not_called()
        self.assertEqual((job.status()["state"], job.status()["finished"]), ("stopped", 3))
        self.assertEqual(self.found(), ["one"])                      # still there to be cleared
        self.assertEqual(training.latest().folder, job.folder)
        self.assertEqual([name for name in os.listdir(job.folder) if name.endswith(".new")], [])

    def test_a_folder_with_no_notes_or_none_that_can_be_made_out_is_listed_to_be_cleared(self):
        none, damaged = self.holding("none"), self.holding("damaged")
        with open(damaged.notes, "w") as f:
            f.write('{"state": "trai')
        odd = self.holding("odd")
        with open(odd.notes, "w") as f:
            json.dump({"state": "somewhere"}, f)
        self.holding("small", megabytes=0)                           # nothing in it worth saying
        self.assertEqual(self.found(), ["damaged", "none", "odd"])
        self.assertTrue(none.adrift())
        none.discard()
        self.assertFalse(os.path.exists(none.folder))
        self.assertEqual(self.found(), ["damaged", "odd"])

    def test_notes_that_only_cannot_be_read_this_moment_are_not_taken_for_lost(self):
        job = self.holding("busy")
        job.note(state="training", pid=os.getpid())
        real = open

        def in_use(path, *args, **more):  # Windows, with the trainer writing them just now
            if path == job.notes:
                raise PermissionError(13, "in use")
            return real(path, *args, **more)

        with mock.patch("builtins.open", in_use):
            self.assertFalse(job.adrift())
            self.assertEqual(self.found(), [])
        self.assertFalse(job.adrift())


class NotesThatCannotBeWritten(unittest.TestCase):
    """On Windows the window reading the notes can be in the trainer's way for a moment."""

    def setUp(self):
        self.job = training.Job(tempfile.mkdtemp())
        self.job.note(state="training", pid=7, done=1)

    def test_it_tries_again_and_the_run_goes_on(self):
        real, calls = os.replace, []

        def busy(source, target):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "in use")
            return real(source, target)

        with mock.patch("os.replace", busy), mock.patch("time.sleep"):
            self.job.note(done=2)
        self.assertEqual(self.job.status()["done"], 2)

    def test_how_far_a_pass_has_come_is_let_go_but_a_change_of_state_is_not(self):
        with mock.patch("os.replace", side_effect=PermissionError(13, "in use")), mock.patch("time.sleep"):
            self.assertEqual(self.job.note(done=5)["done"], 5)       # nothing raised
            with self.assertRaises(PermissionError):
                self.job.note(state="done")

    def test_notes_that_cannot_be_read_just_now_are_not_written_over_with_less(self):
        real = open

        def unreadable(path, *args, **more):
            if path == self.job.notes and (not args or "r" in args[0]):
                raise PermissionError(13, "in use")
            return real(path, *args, **more)

        with mock.patch("builtins.open", unreadable), mock.patch("time.sleep"):
            said = self.job.note(done=3)
        self.assertEqual((said["pid"], said["state"], said["done"]), (7, "training", 3))
        self.assertEqual(self.job.status()["pid"], 7)


class WhatStoppedRunsHold(unittest.TestCase):
    def setUp(self):
        self.runs = tempfile.mkdtemp()
        patch = mock.patch.object(training, "RUNS", self.runs)
        patch.start()
        self.addCleanup(patch.stop)

    def run_of(self, name, state, megabytes=0):
        job = training.Job(os.path.join(self.runs, name))
        job.note(state=state, name=name, pid=0)
        if megabytes:
            with open(os.path.join(job.folder, "last.pt"), "wb") as f:
                f.truncate(megabytes * 1_000_000)
            if hasattr(os, "link"):       # the best pass so far is the same file, under another name
                os.link(os.path.join(job.folder, "last.pt"), os.path.join(job.folder, "best.pt"))
        return job

    def test_stopped_and_failed_runs_that_kept_the_model_are_found(self):
        stopped = self.run_of("one", "stopped", 5)
        self.run_of("two", "failed", 3)
        self.run_of("three", "done", 4)               # finished: nothing to carry on
        self.run_of("four", "stopped")                # only its notes
        found = dict((os.path.basename(job.folder), size) for job, size in training.unfinished())
        self.assertEqual(sorted(found), ["one", "two"])
        if hasattr(os, "link"):
            self.assertLess(found["one"], 5_100_000)  # counted once, though it has two names
        self.assertEqual(stopped.size(), found["one"])

    def test_clearing_one_removes_its_folder_and_no_other(self):
        stopped, done = self.run_of("one", "stopped", 2), self.run_of("three", "done", 2)
        stopped.discard()
        self.assertFalse(os.path.exists(stopped.folder))
        self.assertTrue(os.path.exists(done.folder))
        self.assertEqual(training.unfinished(), [])

    def test_a_run_that_is_going_is_not_cleared(self):
        going = self.run_of("one", "training", 2)
        going.note(pid=os.getpid(), started=__import__("time").time())
        going.discard()
        self.assertTrue(os.path.exists(going.folder))


if __name__ == "__main__":
    unittest.main()

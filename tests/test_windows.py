"""The app's own windows, made off screen, with a stand-in engine and a throwaway folder
for settings and state. Nothing is shown on a screen, no key is pressed on the keyboard,
the microphone is never opened and nothing on this computer is switched.

Skipped where PyQt6 isn't installed for the Python that runs the tests.

The app reads where its settings and state are kept once, when it is first loaded. In a
run of the whole suite other tests have loaded it by then, with the person's own folders.
So these tests are then run in a process of their own, where the throwaway folder is
named before anything of the app is loaded: see the foot of this file.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

ALONE = "dictation.config" not in sys.modules  # nothing of the app has been loaded yet

if HAVE_QT and ALONE:
    FOLDER = tempfile.mkdtemp(prefix="ls-windows-")
    os.environ.update(
        QT_QPA_PLATFORM="offscreen",
        LS_STATE_FILE=os.path.join(FOLDER, "state", "state"),
        LS_SETTINGS_FILE=os.path.join(FOLDER, "settings.json"),
        LS_INSTALL_DIR=FOLDER, LS_MODEL_DIR=os.path.join(FOLDER, "models"),
        LS_TRAINING_DIR=os.path.join(FOLDER, "training"),
        LS_MAIL="0", LS_VSCODE="0", LS_EDITOR="0", LS_NOTIFY="1")

    from types import SimpleNamespace

    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QDesktopServices, QFocusEvent, QKeyEvent, QWheelEvent
    from PyQt6.QtWidgets import QApplication, QPlainTextEdit, QPushButton
    from PyQt6.QtTest import QTest

    from dictation import audio, autostart, config, control, hotkey, models, training, tray
    from dictation import settings as settings_module
    from dictation.settings import Settings
    from dictation.status import State, Status

    APP = QApplication.instance() or QApplication([])
    OPENED, SWITCHED = [], []  # what would have been opened, and switched, on a real desktop
    STOOD_IN = []              # what the stand-ins below took the place of, to be put back

    def setUpModule():
        def no_microphone(name=""):
            raise RuntimeError("the tests never open the microphone")
        for owner, name, stand_in in (
                (audio, "open_microphone", no_microphone),
                (autostart, "state", lambda *a, **k: True),
                (autostart, "switch", lambda on, *a, **k: SWITCHED.append(on) or ""),
                (QDesktopServices, "openUrl", staticmethod(lambda url: OPENED.append(url) or True)),
                (training, "memory_problem", lambda free=None: ""),
                (tray, "tell", lambda window, text, kind="warning": OPENED.append(text)),
                (tray, "ask", lambda window, text, careful=False: True)):
            STOOD_IN.append((owner, name, getattr(owner, name)))
            setattr(owner, name, stand_in)

    def tearDownModule():
        for window in QApplication.topLevelWidgets():
            window.close()
        for owner, name, real in STOOD_IN:  # for tests of other modules run after these
            setattr(owner, name, real)
        shutil.rmtree(FOLDER, ignore_errors=True)

    class Engine:
        """Stands in for the engine: it has what the windows read, and keeps what they ask."""

        def __init__(self, on_change=lambda: None, transcriber=None):
            self.settings = Settings.load(os.environ["LS_SETTINGS_FILE"])
            self.status = Status()
            self.status.state = State.ASLEEP
            self.boost, self.share_problem, self.share_address = 1.0, "", ""
            self.targets = SimpleNamespace(office=None, own=None)
            self.on_event, self.on_level = (lambda name: None), (lambda: None)
            self.asked = []
            self.sampler = None

        def turn_on(self, awake=False):
            self.asked.append("turn_on")
            self.status.state = State.AWAKE if awake else State.ASLEEP

        def turn_off(self, remember=True):
            self.asked.append("turn_off")
            self.status.state = State.OFF

        def wake(self):
            self.asked.append("wake")
            self.status.state = State.AWAKE

        def sleep(self):
            self.asked.append("sleep")
            if self.status.state is not State.OFF:
                self.status.state = State.ASLEEP

        def set_model(self, model):
            self.asked.append(("model", model))
            self.settings.model = model

        def hold(self): self.asked.append("hold")
        def unhold(self, asleep=False): self.asked.append("unhold")
        def setting_changed(self, key): self.asked.append(("setting", key))
        def set_words(self, text): self.asked.append(("words", text))

        def set_sentence_ends(self, chosen):
            self.asked.append(("sentence_ends", chosen))
            self.settings.set_sentence_ends(chosen)
        def set_microphone(self, name): self.asked.append(("microphone", name))
        def check_remote(self): return {"ok": False, "why": ""}

        def new_share_key(self):
            self.asked.append("new key")
            self.settings.share["key"] = "a-new-key"

        def set_sharing(self, on, where=None):
            self.asked.append(("sharing", on, where))
            self.settings.share.update(on=on, key=self.settings.share["key"] or "k",
                                       where=self.settings.share["where"] if where is None else where)
        def model_renewed(self, name): pass
        def quit(self): self.asked.append("quit")

    def key(window, which, text=""):
        """Hand a window a key press as Qt would, without a keyboard."""
        QApplication.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, which,
                                                 Qt.KeyboardModifier.NoModifier, text))

    def wheel(widget):
        """One notch of the mouse wheel over a widget. Returns whether it took it."""
        event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)
        return event.isAccepted()

    def wheel_from(widget):
        """One notch of the wheel with the pointer over `widget`, handed up from it to what
        it is in until something takes it: which is what Qt does with a wheel that comes
        from a real mouse. (One that a program sends is given to the one widget, and goes
        no further.) Returns what took it, or None."""
        while widget is not None:
            event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            if QApplication.sendEvent(widget, event) and event.isAccepted():
                return widget
            widget = None if widget.isWindow() else widget.parentWidget()
        return None

    def a_model(name):
        """Put something that counts as an installed Whisper model in the models folder."""
        os.makedirs(os.path.join(config.MODEL_DIR, name), exist_ok=True)
        open(os.path.join(config.MODEL_DIR, name, models.WHISPER), "wb").close()

    class Choosers(unittest.TestCase):
        def chooser(self):
            chooser = tray.Chooser()
            self.addCleanup(chooser.deleteLater)
            for word in ("one", "two", "three"):
                chooser.addItem(word, word)
            chosen = []
            chooser.activated.connect(chosen.append)
            return chooser, chosen

        def test_the_wheel_no_longer_changes_a_chooser(self):
            chooser, chosen = self.chooser()
            for _ in range(3):
                self.assertFalse(wheel(chooser))  # left for the page to scroll by
            self.assertEqual((chooser.currentIndex(), chosen), (0, []))
            chooser.setFocus()  # nor when it has the keyboard
            wheel(chooser)
            self.assertEqual((chooser.currentIndex(), chosen), (0, []))

        def test_an_arrow_key_opens_the_list_and_chooses_nothing(self):
            chooser, chosen = self.chooser()
            opened = []
            chooser.showPopup = lambda: opened.append(True)
            key(chooser, Qt.Key.Key_Down)
            key(chooser, Qt.Key.Key_End)
            self.assertEqual((chooser.currentIndex(), chosen, len(opened)), (0, [], 2))

        def test_every_chooser_in_settings_is_such_a_one(self):
            from PyQt6.QtWidgets import QComboBox
            a_model("small.en")
            a_model("medium.en")
            engine = Engine()
            window = tray.SettingsWindow(engine)
            self.addCleanup(window.deleteLater)
            found = window.findChildren(QComboBox)
            self.assertTrue(found)
            self.assertTrue(all(isinstance(box, tray.Chooser) for box in found))
            self.assertGreaterEqual(window.models.count(), 2)
            before = window.models.currentIndex()
            for _ in range(3):
                wheel(window.models)  # scrolling past it, with the pointer over it
            self.assertEqual(window.models.currentIndex(), before)
            self.assertEqual(engine.asked, [])  # and no model was loaded

    class WakeUpOnTheOtherComputer(unittest.TestCase):
        """The tick box for "wake up" being listened for on the other computer: ticked
        and greyed where this computer has no speech model, free to choose where it has
        one, and unticked to begin with."""

        def have(self, models):
            """Say which speech models are on this computer."""
            for where in (tray, settings_module):
                was = where.available_models
                where.available_models = lambda folder, models=models: list(models)
                self.addCleanup(setattr, where, "available_models", was)

        def window(self, models, wake=False):
            self.have(models)
            engine = Engine()
            engine.settings.remote.update(on=True, address="office-pc", key="k", model="", wake=wake)
            engine.set_remote = lambda on, address, key, model, wake, sound="": engine.asked.append(("remote", wake))
            self.engine = engine
            window = tray.SettingsWindow(engine)
            self.addCleanup(window.close)
            return window

        def test_with_no_model_here_it_is_ticked_and_greyed_and_stays_ticked(self):
            window = self.window([])
            box = window.remote_wake
            self.assertTrue(box.isChecked())
            self.assertIn("it has to", box.text())
            self.assertIn("color", box.styleSheet())                  # greyed
            self.assertIn("no speech model of its own", box.toolTip())
            box.click()                                               # it can't be unticked
            self.assertTrue(box.isChecked())
            self.assertNotIn(("remote", True), self.engine.asked)
            # What was chosen is kept as it was, for when a model is installed here.
            window.apply_remote()
            self.assertEqual(self.engine.asked[-1], ("remote", False))

        def test_with_a_model_here_it_is_unticked_to_begin_with_and_can_be_ticked(self):
            window = self.window([("small.en", "Small")])
            box = window.remote_wake
            self.assertFalse(box.isChecked())
            self.assertEqual((box.text(), box.styleSheet()), ('Listen for "wake up" there too', ""))
            box.click()
            self.assertTrue(box.isChecked())
            self.assertEqual(self.engine.asked[-1], ("remote", True))

        def test_with_a_model_here_a_tick_that_was_chosen_is_kept(self):
            self.assertTrue(self.window([("small.en", "Small")], wake=True).remote_wake.isChecked())

        def test_it_follows_the_models_as_they_come_and_go(self):
            window = self.window([])
            self.assertTrue(window.remote_wake.isChecked())
            self.have([("small.en", "Small")])
            window.refill_models()                                    # as when one is installed
            self.assertFalse(window.remote_wake.isChecked())
            self.assertEqual(window.remote_wake.styleSheet(), "")

    class DictationSamples(unittest.TestCase):
        """The window that records dictation as it is really done, with what was meant."""

        def window(self):
            import tempfile
            try:
                os.remove(tray.learn_module.LEARNED)      # (what an earlier test learned)
            except OSError:
                pass
            engine = Engine()
            self.engine = engine
            self.folder = tempfile.mkdtemp()
            window = tray.SamplesWindow(engine, self.folder)
            self.addCleanup(window.close)
            window.show()
            QApplication.processEvents()
            return window

        def test_its_box_takes_dictation_and_the_phrases_are_kept_with_what_was_meant(self):
            import numpy as np
            from dictation import samples
            window = self.window()
            self.assertIs(self.engine.sampler, window.catcher)
            window.on_box_focus(True)
            self.assertIs(self.engine.targets.own, window.own)
            targets = SimpleNamespace(own=window.own, name="the samples box")
            self.assertTrue(window.catcher.wants(targets))
            self.assertFalse(window.catcher.wants(SimpleNamespace(own=None, name="Writer")))
            self.assertFalse(window.keep_button.isEnabled())          # nothing dictated yet
            window.catcher.add(np.zeros(8000, dtype=np.float32), "Also, it should be an option.", 10.0, 0.5)
            window.catcher.add(np.zeros(8000, dtype=np.float32), "That the user can select.", 12.0, 0.5)
            QApplication.processEvents()
            self.assertTrue(window.keep_button.isEnabled())
            self.assertIn("2 phrases", window.said.text())
            window.box.setPlainText("Also, it should be an option that the user can select.")
            window.keep()
            kept = samples.kept(self.folder)
            self.assertEqual(len(kept), 1)
            here, record = kept[0]
            self.assertEqual(record["meant"], "Also, it should be an option that the user can select.")
            self.assertEqual([p["written"] for p in record["phrases"]],
                             ["Also, it should be an option.", "That the user can select."])
            self.assertEqual([p["pause_before"] for p in record["phrases"]], [None, 1.5])
            self.assertTrue(os.path.exists(os.path.join(here, "phrase-01.wav")))
            self.assertEqual(window.box.toPlainText(), "")            # emptied for the next
            self.assertIn("1 sample kept", window.kept_label.text())

        def test_phrases_dictated_are_shown_though_the_engine_is_on_its_own_thread(self):
            import threading
            import numpy as np
            window = self.window()
            told = []
            window.taken.connect(lambda: told.append(1))
            window.catcher.taken()            # (the window's own signal: a timer started on
            self.assertEqual(told, [1])       #  the engine's thread would never fire)
            done = threading.Thread(target=window.catcher.add,
                                    args=(np.zeros(800, dtype=np.float32), "Hello.", 1.0, 0.1))
            done.start()
            done.join()
            QApplication.processEvents()      # the window hears of it on its own thread
            self.assertIn("1 phrase", window.said.text())
            self.assertTrue(window.keep_button.isEnabled())

        def test_the_samples_kept_are_listed_and_can_be_deleted(self):
            import numpy as np
            from dictation import samples
            answers = []
            yes = [True, False, True]     # delete one; delete all, answered No; then Yes

            def ask(window, text, careful=False):
                answers.append((text, careful))
                return yes.pop(0)
            self.addCleanup(setattr, tray, "ask", tray.ask)
            tray.ask = ask
            window = self.window()
            for written, meant in (("Hello.", "Hello."), ("Again.", "Again.")):
                window.catcher.add(np.zeros(800, dtype=np.float32), written, 1.0, 0.1)
                window.box.setPlainText(meant)
                window.keep()
            oldest, newest = [path for path, _ in samples.kept(self.folder)]
            self.assertEqual(window.kept_list.count(), 2)
            self.assertIn("phrase", window.kept_list.item(0).text())
            self.assertEqual(window.kept_list.item(0).toolTip(), "Again.")   # newest first
            self.assertEqual(window.kept_list.item(1).toolTip(), "Hello.")
            self.assertEqual(answers, [])
            window.kept_list.setCurrentRow(1)              # the older one, chosen on purpose
            window.delete_one()
            self.assertEqual([path for path, _ in samples.kept(self.folder)], [newest])
            self.assertEqual(window.kept_list.count(), 1)
            self.assertIn("Delete the sample kept", answers[-1][0])
            self.assertTrue(answers[-1][1])                # asked first, and carefully
            window.delete_all()                            # answered No: nothing goes
            self.assertEqual(len(samples.kept(self.folder)), 1)
            window.delete_all()                            # answered Yes: it goes
            self.assertEqual(samples.kept(self.folder), [])
            self.assertEqual(window.kept_list.count(), 0)
            self.assertFalse(window.delete_button.isEnabled())
            self.assertFalse(window.delete_all_button.isEnabled())

        def test_the_row_chosen_stays_chosen_while_you_dictate(self):
            import numpy as np
            window = self.window()
            for written, meant in (("Hello.", "Hello."), ("Again.", "Again.")):
                window.catcher.add(np.zeros(800, dtype=np.float32), written, 1.0, 0.1)
                window.box.setPlainText(meant)
                window.keep()
            window.kept_list.setCurrentRow(1)              # the older one
            chosen = window.chosen()
            window.catcher.add(np.zeros(800, dtype=np.float32), "More.", 3.0, 0.1)
            QApplication.processEvents()                   # (as each dictated phrase does)
            self.assertEqual(window.chosen(), chosen)      # a phrase arriving moves nothing

        def test_the_folder_can_be_opened(self):
            from unittest import mock
            window = self.window()
            with mock.patch.object(tray.QDesktopServices, "openUrl") as opened:
                window.show_folder()
            self.assertTrue(os.path.isdir(self.folder))
            self.assertEqual(opened.call_args[0][0].toLocalFile(), self.folder)

        def test_corrections_made_in_a_sample_are_noted(self):
            import numpy as np
            window = self.window()
            window.catcher.add(np.zeros(800, dtype=np.float32), "Cheers, Junty.", 1.0, 0.1)
            window.typed = "Cheers, Junty."          # (what the program typed into the box)
            window.box.setPlainText("Cheers, Jonti.")
            window.keep()
            self.assertEqual(window.learned, {"junty": "Jonti"})
            self.assertIn("Noted 1 correction", window.learn_label.text())
            self.assertIn("not put in as blanket changes", window.learn_label.text())
            self.assertIn("→ Jonti", window.learn_label.toolTip())

        def test_deleting_a_sample_forgets_what_it_taught(self):
            import numpy as np

            def ask(window, text, careful=False):
                return True
            self.addCleanup(setattr, tray, "ask", tray.ask)
            tray.ask = ask
            window = self.window()
            window.catcher.add(np.zeros(800, dtype=np.float32), "Cheers, Junty.", 1.0, 0.1)
            window.typed = "Cheers, Junty."
            window.box.setPlainText("Cheers, Jonti.")
            window.keep()
            self.assertEqual(window.learned, {"junty": "Jonti"})
            window.delete_all()
            self.assertEqual(window.learned, {})
            self.assertIn("No corrections to note", window.learn_label.text())

        def test_check_scores_the_samples_and_offers_the_best_way(self):
            import time
            import numpy as np
            from unittest import mock
            window = self.window()
            self.engine.settings.sentence_ends = "said"
            window.catcher.add(np.zeros(800, dtype=np.float32), "Hello.", 1.0, 0.1)
            window.box.setPlainText("Hello.")
            window.keep()
            stub = {"samples": 1, "phrases": 1, "words": 5, "misheard": 0,
                    "ways": {way: {"per_100": 100.0 * n, "errors": n}
                             for n, way in enumerate(tray.bench_module.SHORT)},
                    "best": "words"}
            with mock.patch.object(tray.bench_module, "check", return_value=stub):
                window.check_samples()
                for _ in range(100):
                    QApplication.processEvents()
                    if not window._checking:
                        break
                    time.sleep(0.02)
            self.assertIn("wrong marks per 100 words", window.check_label.text())
            self.assertFalse(window.use_button.isHidden())
            window.use_best()
            self.assertEqual(self.engine.settings.sentence_ends, "words")
            self.assertTrue(window.use_button.isHidden())

        def test_a_later_check_with_no_best_withdraws_the_offer(self):
            import time
            import numpy as np
            from unittest import mock
            window = self.window()
            self.engine.settings.sentence_ends = "said"
            window.catcher.add(np.zeros(800, dtype=np.float32), "Hello.", 1.0, 0.1)
            window.box.setPlainText("Hello.")
            window.keep()
            ways = {way: {"per_100": 10.0, "errors": 1} for way in tray.bench_module.SHORT}
            offers = [{"samples": 1, "phrases": 1, "words": 5, "misheard": 0,
                       "ways": ways, "best": "words", "model": True},
                      {"samples": 1, "phrases": 1, "words": 5, "misheard": 0,
                       "ways": ways, "best": "", "model": True}]
            for answer in offers:
                with mock.patch.object(tray.bench_module, "check", return_value=answer):
                    window.check_samples()
                    for _ in range(100):
                        QApplication.processEvents()
                        if not window._checking:
                            break
                        time.sleep(0.02)
            self.assertTrue(window.use_button.isHidden())     # a tie: no old offer stands
            self.assertEqual(window._best, "")

        def test_checking_with_no_samples_starts_nothing(self):
            window = self.window()
            self.assertFalse(window.check_button.isEnabled())
            window.check_samples()
            self.assertFalse(window._checking)

        def test_start_again_keeps_nothing(self):
            import numpy as np
            from dictation import samples
            window = self.window()
            window.catcher.add(np.zeros(800, dtype=np.float32), "Hello.", 1.0, 0.1)
            window.box.setPlainText("Hello")
            window.start_again()
            self.assertEqual((samples.kept(self.folder), window.box.toPlainText()), ([], ""))

        def test_closed_it_takes_nothing(self):
            window = self.window()
            window.hide()
            self.assertIsNone(self.engine.sampler)

    class WhereFullStopsGo(unittest.TestCase):
        """The choice of where full stops go at the ends of phrases, in place of the old
        tick box for keeping the recogniser's."""

        def window(self, **states):
            engine = Engine()
            engine.settings.states.update(states)
            engine.settings.sentence_ends = "pause" if states.get("keep_final") else "said"
            self.engine = engine
            window = tray.SettingsWindow(engine)
            self.addCleanup(window.close)
            return window

        def test_three_choices_in_place_of_the_tick_box(self):
            window = self.window()
            chooser = window.sentence_ends
            self.assertEqual([chooser.itemData(n) for n in range(chooser.count())], ["said", "words", "pause"])
            self.assertEqual(chooser.currentData(), "said")
            self.assertNotIn("keep_final", window.ticks)
            self.assertIn("next words", chooser.toolTip())

        def test_the_old_tick_shows_as_every_pause(self):
            self.assertEqual(self.window(keep_final=True).sentence_ends.currentData(), "pause")

        def test_choosing_is_passed_on_and_kept(self):
            window = self.window()
            chooser = window.sentence_ends
            chooser.setCurrentIndex(chooser.findData("words"))
            chooser.activated.emit(chooser.currentIndex())
            self.assertEqual(self.engine.asked[-1], ("sentence_ends", "words"))
            self.assertEqual(self.engine.settings.sentence_ends, "words")
            self.assertFalse(self.engine.settings.states["keep_final"])

    class HowTheSoundIsSent(unittest.TestCase):
        """The choice of how the sound is packed for the journey to the other computer."""

        def window(self, **remote):
            engine = Engine()
            engine.settings.remote.update(on=True, address="office-pc", key="k", **remote)
            engine.set_remote = lambda on, address, key, model, wake, sound="": engine.asked.append(("sound", sound))
            self.engine = engine
            window = tray.SettingsWindow(engine)
            self.addCleanup(window.close)
            return window

        def test_it_starts_as_flac_and_offers_the_three(self):
            chooser = self.window().remote_sound
            self.assertEqual([chooser.itemData(n) for n in range(chooser.count())], ["flac", "opus", "pcm"])
            self.assertEqual(chooser.currentData(), "flac")
            self.assertEqual([chooser.itemText(n).split(":")[0] for n in range(chooser.count())],
                             ["FLAC", "Opus", "Raw"])
            self.assertIn("exactly what was heard", chooser.toolTip())

        def test_it_shows_what_was_chosen_before(self):
            self.assertEqual(self.window(sound="opus").remote_sound.currentData(), "opus")

        def test_choosing_one_is_passed_on(self):
            window = self.window()
            window.remote_sound.setCurrentIndex(window.remote_sound.findData("opus"))
            window.remote_sound.activated.emit(window.remote_sound.currentIndex())
            self.assertEqual(self.engine.asked[-1], ("sound", "opus"))

        def test_it_says_so_when_the_sound_cannot_go_the_way_chosen(self):
            window = self.window()
            window.on_remote_checked({"ok": True, "models": [], "sound": "flac", "sound_there": True})
            self.assertEqual(window.remote_note.text(), "Connected. Recognition is done on the other computer.")
            window.on_remote_checked({"ok": True, "models": [], "sound": "pcm", "sound_there": False})
            self.assertIn("The sound goes raw, not as FLAC", window.remote_note.text())
            self.assertIn("earlier Linux Speaking", window.remote_note.text())
            window.on_remote_checked({"ok": True, "models": [], "sound": "pcm", "sound_there": True})
            self.assertIn("this computer can't pack it", window.remote_note.text())
            self.engine.settings.remote["sound"] = "opus"
            window.on_remote_checked({"ok": True, "models": [], "sound": "flac", "sound_there": False})
            self.assertIn("The sound goes as FLAC, not as Opus", window.remote_note.text())
            # One that says nothing of it (the windows of an earlier engine): nothing is said.
            window.on_remote_checked({"ok": True, "models": []})
            self.assertEqual(window.remote_note.text(), "Connected. Recognition is done on the other computer.")

    class ANewKeyForSharing(unittest.TestCase):
        """Changing the key, so that whoever was given the old one is no longer answered."""

        def window(self, answer=True, **share):
            self.questions = []

            def ask(window, text, careful=False):
                self.questions.append((text, careful))
                return answer
            self.addCleanup(setattr, tray, "ask", tray.ask)
            tray.ask = ask
            engine = Engine()
            engine.settings.share.update(share)
            self.engine = engine
            window = tray.SettingsWindow(engine)
            self.addCleanup(window.close)
            return window

        def test_with_sharing_off_there_is_no_key_to_change(self):
            self.assertTrue(self.window().share_new_key.isHidden())

        def test_it_asks_first_and_then_shows_the_new_key(self):
            window = self.window(on=True, key="the-old-key")
            self.assertFalse(window.share_new_key.isHidden())
            self.assertIn("Key: the-old-key", window.share_note.text())
            window.share_new_key.click()
            (question, careful), = self.questions
            self.assertIn("Nobody will be answered with the old key", question)
            self.assertTrue(careful)                              # Enter alone changes nothing
            self.assertIn("new key", self.engine.asked)
            self.assertIn("Key: a-new-key", window.share_note.text())
            self.assertNotIn("the-old-key", window.share_note.text())

        def test_answered_no_nothing_changes(self):
            window = self.window(answer=False, on=True, key="the-old-key")
            window.share_new_key.click()
            self.assertEqual(len(self.questions), 1)
            self.assertNotIn("new key", self.engine.asked)
            self.assertIn("Key: the-old-key", window.share_note.text())

        def test_it_says_what_it_is_for(self):
            tip = self.window(on=True, key="k").share_new_key.toolTip()
            self.assertIn("no longer to use this computer", tip)
            self.assertIn("has to be given the new key", tip)

    class WhichNetworkItIsSharedOn(unittest.TestCase):
        """The choice between every network this computer is on and one of them, by name."""

        HOME = [("Wi-Fi", "192.168.1.20")]
        TWO = [("Wi-Fi", "192.168.1.20"), ("office-vpn", "10.8.0.6")]

        def window(self, here=(), address="", **share):
            self.here = list(here)
            for owner, name, value in ((tray.remote, "networks", lambda: list(self.here)),
                                       (config, "SHARE_ADDRESS", address)):
                self.addCleanup(setattr, owner, name, getattr(owner, name))
                setattr(owner, name, value)
            engine = Engine()
            engine.settings.share.update(share)
            self.engine = engine
            window = tray.SettingsWindow(engine)
            self.addCleanup(window.close)
            return window

        def shown(self, window):
            return (not window.share_where.isHidden(), not window.share_where_label.isHidden())

        def offered(self, window):
            chooser = window.share_where
            return [(chooser.itemText(n), chooser.itemData(n)) for n in range(chooser.count())]

        def test_with_sharing_off_there_is_nothing_to_choose(self):
            self.assertEqual(self.shown(self.window(self.TWO)), (False, False))

        def test_on_one_network_there_is_nothing_to_choose(self):
            window = self.window(self.HOME, on=True, key="k")
            self.assertEqual(self.shown(window), (False, False))
            self.assertIn("Key: k", window.share_note.text())

        def test_on_more_than_one_it_offers_each_by_name_and_starts_as_every_network(self):
            window = self.window(self.TWO, on=True, key="k")
            self.assertEqual(self.shown(window), (True, True))
            self.assertEqual([name for _, name in self.offered(window)], ["", "Wi-Fi", "office-vpn"])
            self.assertEqual(self.offered(window)[0][0], "Every network this computer is on")
            self.assertIn("192.168.1.20", self.offered(window)[1][0])
            self.assertEqual(window.share_where.currentData(), "")
            self.assertIn("encrypted", window.share_where.toolTip())

        def test_choosing_one_is_passed_on_and_so_is_going_back(self):
            window = self.window(self.TWO, on=True, key="k")
            window.share_where.setCurrentIndex(window.share_where.findData("office-vpn"))
            window.share_where.activated.emit(window.share_where.currentIndex())
            self.assertEqual(self.engine.asked[-1], ("sharing", True, "office-vpn"))
            self.assertEqual(window.share_where.currentData(), "office-vpn")
            window.share_where.setCurrentIndex(0)
            window.share_where.activated.emit(0)
            self.assertEqual(self.engine.asked[-1], ("sharing", True, ""))
            self.assertEqual(window.share_where.currentData(), "")

        def test_kept_to_one_it_shows_the_address_that_finds_it_there(self):
            window = self.window(self.TWO, on=True, key="k", where="office-vpn")
            self.engine.share_address = "10.8.0.6"
            window.refresh_sharing()
            self.assertEqual(window.share_where.currentData(), "office-vpn")
            self.assertIn("Address: 10.8.0.6", window.share_note.text())

        def test_kept_to_one_that_has_gone_it_says_so_and_can_still_be_changed(self):
            window = self.window(self.HOME, on=True, key="k", where="office-vpn")
            self.engine.share_problem = 'this computer isn\'t on the network "office-vpn" just now'
            window.refresh_sharing()
            self.assertEqual(self.shown(window), (True, True))       # though only one network is here
            self.assertEqual(window.share_where.currentData(), "office-vpn")
            self.assertIn("isn't on it just now", window.share_where.currentText())
            self.assertIn("Not working yet: this computer isn't on the network", window.share_note.text())
            self.assertIn("looked for again", window.share_note.text())

        def test_the_list_follows_the_networks_as_they_come_and_go(self):
            window = self.window(self.HOME, on=True, key="k")
            self.assertEqual(self.shown(window), (False, False))
            self.here.append(("office-vpn", "10.8.0.6"))             # a VPN is switched on
            window.refresh_sharing()                                  # as when Settings is next shown
            self.assertEqual(self.shown(window), (True, True))
            self.assertEqual([name for _, name in self.offered(window)], ["", "Wi-Fi", "office-vpn"])

        def test_an_address_said_when_it_was_started_settles_it(self):
            window = self.window(self.TWO, address="192.168.1.20", on=True, key="k")
            self.assertEqual(self.shown(window), (False, False))
            # And it says why there is no choice to be seen, and what would bring it back.
            self.assertIn("Address: 192.168.1.20  (fixed by LS_SHARE_ADDRESS)", window.share_note.text())
            self.assertIn("Reachable from", window.share_note.toolTip())

        def test_without_one_nothing_is_said_of_it(self):
            window = self.window(self.TWO, on=True, key="k")
            self.assertNotIn("LS_SHARE_ADDRESS", window.share_note.text())
            self.assertEqual(window.share_note.toolTip(), "")

        def test_on_linux_a_name_that_says_little_is_said_with_its_kind(self):
            was = config.WINDOWS
            self.addCleanup(setattr, config, "WINDOWS", was)
            config.WINDOWS = False
            self.assertEqual(tray.network_label("wlp3s0", "192.168.1.20"), "Wi-Fi, wlp3s0  (192.168.1.20)")
            self.assertEqual(tray.network_label("enp1s0", "10.0.0.4"), "Wired, enp1s0  (10.0.0.4)")
            self.assertEqual(tray.network_label("office-vpn", "10.8.0.6"), "office-vpn  (10.8.0.6)")
            config.WINDOWS = True
            self.assertEqual(tray.network_label("Wi-Fi", "192.168.1.20"), "Wi-Fi  (192.168.1.20)")
            self.assertEqual(tray.network_label("Ethernet 2", "10.0.0.4"), "Ethernet 2  (10.0.0.4)")

    class TextInAPageThatScrolls(unittest.TestCase):
        """Scrolling down Settings, the wheel stays with the page when the pointer comes
        to rest on a box of text."""

        def box(self):
            box = tray.PageText()
            self.addCleanup(box.deleteLater)
            box.setPlainText("\n".join(f"line {n}" for n in range(60)))
            box.setFixedHeight(80)
            box.show()
            QApplication.processEvents()
            self.assertGreater(box.verticalScrollBar().maximum(), 0)   # it has more than it shows
            return box      # (the wheel reaches such a box by its viewport, as the mouse does)

        def click(self, box):
            QTest.mouseClick(box.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))

        def leave(self, box):
            QApplication.sendEvent(box, QEvent(QEvent.Type.Leave))

        def test_the_wheel_is_the_pages_while_the_box_is_only_passed_over(self):
            box = self.box()
            for _ in range(3):
                self.assertFalse(wheel(box.viewport()))  # left for the page to scroll by
            self.assertEqual(box.verticalScrollBar().value(), 0)
            self.assertEqual(box.focusPolicy(), Qt.FocusPolicy.StrongFocus)  # nor is it given the keyboard by it

        def test_clicked_the_wheel_is_its_own(self):
            box = self.box()
            self.click(box)
            self.assertTrue(wheel(box.viewport()))
            self.assertGreater(box.verticalScrollBar().value(), 0)

        def test_until_the_pointer_leaves_it(self):
            box = self.box()
            self.click(box)
            self.leave(box)
            self.assertFalse(wheel(box.viewport()))
            self.assertEqual(box.verticalScrollBar().value(), 0)

        def test_having_the_keyboard_is_not_enough(self):
            # It was typed in a while ago, and still has the keyboard: the page is being
            # scrolled past it now.
            box = self.box()
            box.hasFocus = lambda: True
            self.assertFalse(wheel(box.viewport()))
            self.assertEqual(box.verticalScrollBar().value(), 0)

        def test_at_the_end_of_its_text_the_wheel_goes_on_to_the_page(self):
            box = self.box()
            self.click(box)
            bar = box.verticalScrollBar()
            bar.setValue(bar.maximum())
            self.assertFalse(wheel(box.viewport()))

        def test_the_wheel_over_its_own_scroll_bar_is_the_pages_too(self):
            box = self.box()
            bar = box.verticalScrollBar()
            self.assertFalse(wheel(bar))
            self.assertEqual(bar.value(), 0)
            QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))   # taken hold of
            QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
            bar.setValue(0)
            self.assertTrue(wheel(bar))
            self.assertGreater(bar.value(), 0)

        def test_the_boxes_of_text_in_settings_are_such(self):
            window = tray.SettingsWindow(Engine())
            self.addCleanup(window.deleteLater)
            found = window.findChildren(QPlainTextEdit)
            self.assertEqual(len(found), 2)                  # My words, My shortcuts and commands
            self.assertTrue(all(isinstance(box, tray.PageText) for box in found))
            self.assertIs(window.shortcuts.lineWrapMode(), QPlainTextEdit.LineWrapMode.NoWrap)

        def test_scrolling_down_settings_over_a_long_list_of_shortcuts_moves_the_page(self):
            from PyQt6.QtWidgets import QScrollArea
            window = tray.SettingsWindow(Engine())
            self.addCleanup(window.deleteLater)
            window.shortcuts.setPlainText("\n".join(f"word {n} = text {n}" for n in range(40)))
            window.shortcuts_timer.stop()                    # nothing is to be saved by this
            window.resize(window.width(), 300)
            window.show()
            QApplication.processEvents()
            page, box = window.findChild(QScrollArea).verticalScrollBar(), window.shortcuts.verticalScrollBar()
            self.assertGreater(page.maximum(), 0)
            self.assertGreater(box.maximum(), 0)
            window.shortcuts.setFocus()                      # it was typed in last, even
            took = wheel_from(window.shortcuts.viewport())   # the pointer is over the box
            self.assertGreater(page.value(), 0)              # and it is the page that moved
            self.assertEqual(box.value(), 0)
            self.assertIs(took, window.findChild(QScrollArea).viewport())
            was = page.value()
            self.assertIs(wheel_from(box), took)             # over the box's own scroll bar, too
            self.assertGreater(page.value(), was)
            self.assertEqual(box.value(), 0)
            self.click(window.shortcuts)                     # clicked, the box moves
            self.assertIs(wheel_from(window.shortcuts.viewport()), window.shortcuts.viewport())
            self.assertGreater(box.value(), 0)

    class Keyboard(unittest.TestCase):
        def test_escape_closes_a_window(self):
            for make in (lambda: tray.HelpWindow(Engine()), lambda: tray.SettingsWindow(Engine()),
                         lambda: tray.LogWindow(Engine()), lambda: tray.AboutWindow(Engine())):
                window = make()
                self.addCleanup(window.deleteLater)
                window.show()
                self.assertTrue(window.isVisible())
                key(window, Qt.Key.Key_Escape)
                self.assertFalse(window.isVisible(), window.windowTitle())

        def test_enter_presses_the_button_that_has_the_keyboard(self):
            window = tray.HelpWindow(Engine())
            self.addCleanup(window.deleteLater)
            window.show()
            close = next(b for b in window.findChildren(QPushButton) if "lose" in b.text())
            close.setFocus()
            self.assertIs(window.focusWidget(), close)
            key(window, Qt.Key.Key_Return)
            self.assertFalse(window.isVisible())

        def test_the_engine_is_told_how_many_windows_are_showing(self):
            engine = Engine()
            first, second = tray.HelpWindow(engine), tray.LogWindow(engine)
            self.addCleanup(first.deleteLater)
            self.addCleanup(second.deleteLater)
            before = len(tray.Window.showing)
            first.show()
            second.show()
            self.assertEqual(engine.status.own_windows, before + 2)
            self.assertIs(tray.Window.in_front(), second)  # the one opened last
            second.close()
            self.assertEqual(engine.status.own_windows, before + 1)
            self.assertIs(tray.Window.in_front(), first)
            first.close()
            self.assertEqual(engine.status.own_windows, before)

        def test_a_question_that_deletes_answers_no_to_enter(self):
            from unittest import mock
            from dictation import looks
            asked = []
            engine = Engine()
            engine.settings.look = "10"
            window = SimpleNamespace(engine=engine, windowTitle=lambda: "Models")
            with mock.patch.object(config, "WINDOWS", True), \
                    mock.patch.object(looks, "message", lambda *a, **k: asked.append(k) or "No"):
                self.assertFalse(REAL_ASK(window, "Remove this model?", careful=True))
                self.assertFalse(REAL_ASK(window, "Install the tools?"))
            self.assertEqual([k.get("default") for k in asked], ["No", "Yes"])

    class TheMicrophoneChooser(unittest.TestCase):
        def test_a_name_windows_cut_off_is_shown_whole_and_chosen_by_the_cut_one(self):
            from unittest import mock
            from PyQt6.QtWidgets import QLabel
            cut = "Microphone (Realtek High Defini"
            engine = Engine()
            engine.settings.microphone = cut
            window = SimpleNamespace(engine=engine, microphones=tray.Chooser(),
                                     microphones_note=QLabel())
            with mock.patch.object(tray.audio, "microphones", lambda fresh=False: ["Headset", cut]), \
                    mock.patch.object(tray.audio, "whole", lambda name: name + "tion Audio)"
                                      if name == cut else name):
                tray.SettingsWindow.refill_microphones(window, fresh=False)
            box = window.microphones
            self.assertEqual([box.itemText(i) for i in range(box.count())],
                             ["Windows' default recording device", "Headset",
                              "Microphone (Realtek High Definition Audio)"])
            self.assertEqual(box.currentText(), "Microphone (Realtek High Definition Audio)")
            self.assertEqual(box.currentData(), cut)     # what is remembered and opened

    class TheBoxToTryItIn(unittest.TestCase):
        def setUp(self):
            self.engine = Engine()
            self.window = tray.WelcomeWindow(self.engine)
            self.addCleanup(self.window.deleteLater)
            self.own = self.window.own
            self.box = self.window.box

        def test_it_answers_as_a_program_does(self):
            self.assertEqual(self.own.request({"op": "status"}), {"ok": True, "ready": True})
            self.assertEqual(self.own.request({"op": "context"}),
                             {"ok": True, "before": "", "after": "", "selected": ""})
            self.assertTrue(self.own.name)

        def test_a_request_that_was_given_up_on_is_not_carried_out_late(self):
            # Asked from the engine's thread while the window's thread is held up for
            # longer than the engine waits: it is told no, and the words must not then
            # turn up in the box after all.
            self.own.WAIT = 0.2
            answers = []
            asker = threading.Thread(target=lambda: answers.append(
                self.own.request({"op": "insert", "text": "too late"})))
            asker.start()
            time.sleep(0.5)                  # this, the window's thread, is busy meanwhile
            asker.join(2)
            APP.processEvents()              # now it gets round to what was asked
            self.assertEqual(answers, [{"ok": False, "why": "the box here did not answer"}])
            self.assertEqual(self.box.toPlainText(), "")

        def test_words_go_in_at_the_cursor_and_the_context_follows(self):
            self.assertEqual(self.own.request({"op": "insert", "text": "Hello there"}),
                             {"ok": True, "text": "Hello there"})
            self.own.request({"op": "insert", "text": " world."})
            self.assertEqual(self.box.toPlainText(), "Hello there world.")
            cursor = self.box.textCursor()
            cursor.setPosition(5)
            self.box.setTextCursor(cursor)
            said = self.own.request({"op": "context"})
            self.assertEqual((said["before"], said["after"], said["selected"]),
                             ("Hello", " there world.", ""))

        def test_what_is_selected_is_told_and_replaced(self):
            self.box.setPlainText("the black cat sat")
            cursor = self.box.textCursor()
            cursor.setPosition(4)
            cursor.setPosition(9, cursor.MoveMode.KeepAnchor)
            self.box.setTextCursor(cursor)
            said = self.own.request({"op": "context"})
            self.assertEqual((said["before"], said["selected"], said["after"]),
                             ("the ", "black", " cat sat"))
            self.own.request({"op": "insert", "text": "white"})
            self.assertEqual(self.box.toPlainText(), "the white cat sat")

        def test_delete_before_takes_back_what_is_before_the_cursor(self):
            self.own.request({"op": "insert", "text": "one two."})
            self.own.request({"op": "insert", "text": ", three", "delete_before": 1})
            self.assertEqual(self.box.toPlainText(), "one two, three")

        def test_scratch_takes_back_the_last_thing_put_in(self):
            self.own.request({"op": "insert", "text": "First."})
            self.own.request({"op": "insert", "text": " Second."})
            scratch = {"op": "command", "name": "scratch", "arg": ""}
            self.assertEqual(self.own.request(scratch), {"ok": True})
            self.assertEqual(self.box.toPlainText(), "First.")
            self.assertEqual(self.own.request(scratch), {"ok": True})
            self.assertEqual(self.box.toPlainText(), "")
            self.assertFalse(self.own.request(scratch)["ok"])  # nothing is left to take back

        def test_undo_that_and_redo_that_are_the_boxes_own(self):
            self.own.request({"op": "insert", "text": "First."})
            self.own.request({"op": "insert", "text": " Second."})
            self.assertEqual(self.own.request({"op": "command", "name": "undo"}), {"ok": True})
            self.assertEqual(self.box.toPlainText(), "First.")
            self.assertEqual(self.own.request({"op": "command", "name": "redo"}), {"ok": True})
            self.assertEqual(self.box.toPlainText(), "First. Second.")

        def test_scratch_puts_back_the_words_a_phrase_was_said_over(self):
            self.box.setPlainText("the black cat sat")
            cursor = self.box.textCursor()
            cursor.setPosition(4)
            cursor.setPosition(9, cursor.MoveMode.KeepAnchor)
            self.box.setTextCursor(cursor)
            self.own.request({"op": "insert", "text": "white,", "delete_after": 1})
            self.assertEqual(self.box.toPlainText(), "the white,cat sat")
            scratch = {"op": "command", "name": "scratch", "arg": ""}
            self.assertEqual(self.own.request(scratch), {"ok": True, "restored": True})
            self.assertEqual(self.box.toPlainText(), "the black cat sat")
            self.assertEqual(self.box.textCursor().selectedText(), "black")   # to be said again
            self.own.request({"op": "insert", "text": "grey"})
            self.assertEqual(self.box.toPlainText(), "the grey cat sat")

        def test_the_other_commands_it_knows_and_the_rest_it_does_not(self):
            self.own.request({"op": "insert", "text": "A line"})
            self.assertTrue(self.own.request({"op": "command", "name": "new_line"})["ok"])
            self.assertTrue(self.own.request({"op": "command", "name": "new_paragraph"})["ok"])
            self.assertEqual(self.box.toPlainText(), "A line\n\n\n")
            self.assertTrue(self.own.request({"op": "command", "name": "undo"})["ok"])
            self.assertEqual(self.box.toPlainText(), "A line\n")
            self.assertTrue(self.own.request({"op": "command", "name": "select_all"})["ok"])
            self.assertEqual(self.own.request({"op": "context"})["selected"], "A line\n")
            self.assertEqual(self.own.request({"op": "command", "name": "bold", "arg": ""}),
                             {"ok": False, "why": "unknown command"})
            self.assertFalse(self.own.request({"op": "dance"})["ok"])

        def test_asked_from_the_engines_thread_it_answers_on_the_windows(self):
            replies = []
            asker = threading.Thread(target=lambda: replies.append(
                self.own.request({"op": "insert", "text": "from another thread"})))
            asker.start()
            until = time.monotonic() + 5
            while asker.is_alive() and time.monotonic() < until:
                APP.processEvents()
                time.sleep(0.005)
            asker.join(1)
            self.assertEqual(replies, [{"ok": True, "text": "from another thread"}])
            self.assertEqual(self.box.toPlainText(), "from another thread")

        def test_the_engine_types_into_it_only_while_it_has_the_keyboard(self):
            self.window.show()
            self.window.on_box_focus(True)
            self.assertIs(self.engine.targets.own, self.own)
            self.window.on_box_focus(False)
            self.assertIsNone(self.engine.targets.own)
            self.window.on_box_focus(True)
            self.window.close()  # and never into a window that is closed
            self.assertIsNone(self.engine.targets.own)

    class Welcome(unittest.TestCase):
        def test_it_says_what_to_do_and_that_it_is_for_english(self):
            from PyQt6.QtWidgets import QLabel
            window = tray.WelcomeWindow(Engine())
            self.addCleanup(window.deleteLater)
            words = " ".join(label.text() for label in window.findChildren(QLabel))
            for wanted in ("English", "\"wake up\"", "\"go to sleep\"", "1.", "4.",
                           "Getting started"):
                self.assertIn(wanted, words)
            buttons = [b.text().replace("&", "") for b in window.findChildren(QPushButton)]
            for wanted in ("What can I say?", "Settings…", "Close"):
                self.assertIn(wanted, buttons)

        def test_it_promises_no_cloud_and_no_more_than_is_true(self):
            from PyQt6.QtWidgets import QLabel
            said = lambda window: " ".join(label.text() for label in window.findChildren(QLabel))
            engine = Engine()
            here = tray.WelcomeWindow(engine)
            self.addCleanup(here.deleteLater)
            self.assertIn("Nothing you say goes to the cloud: it is all done on this computer.", said(here))
            engine.settings.remote = dict(engine.settings.remote, on=True, address="192.0.2.7")
            there = tray.WelcomeWindow(engine)
            self.addCleanup(there.deleteLater)
            self.assertIn("it is all done on a computer of your own.", said(there))
            about = tray.AboutWindow(engine).text()
            self.assertIn("Nothing you say goes to the cloud", about)
            self.assertIn("is sent to the computer of yours that you chose in Settings (192.0.2.7)", about)
            self.assertIn("encrypted on the way", about)
            self.assertNotIn("sent anywhere", about)
            engine.settings.remote = dict(engine.settings.remote, on=False)
            about = tray.AboutWindow(engine).text()
            self.assertIn("everything is done on this computer", about)
            self.assertIn("another computer of your own", about)
            self.assertNotIn("sent anywhere", about)

        def test_the_level_is_said_in_words_as_well_as_shown(self):
            engine = Engine()
            window = tray.WelcomeWindow(engine)
            self.addCleanup(window.deleteLater)
            self.assertEqual(window.level.text(), "Say something")
            engine.status.meter = 80
            for _ in range(4):
                window.follow()
            self.assertEqual(window.level.text(), "Good level")
            engine.status.meter, engine.status.loud = 100, True
            for _ in range(4):
                window.follow()
            self.assertEqual(window.level.text(), "Too loud")
            engine.status.state = State.OFF
            window.follow()
            self.assertEqual(window.level.text(), "Off")
            self.assertIn("microphone is off", window.heard.text())
            self.assertFalse(window.turn_on.isHidden())
            # Its button turns the microphone on with dictation asleep, not awake: the
            # next step in the window is to say "wake up".
            engine.asked.clear()
            window.turn_on.click()
            self.assertEqual(engine.asked, ["turn_on"])
            self.assertIs(engine.status.state, State.ASLEEP)
            window.follow()
            self.assertIn("Asleep. Say \"wake up\" to dictate.", window.state.text())
            self.assertTrue(window.turn_on.isHidden())

        def test_it_names_the_model_to_use_until_it_is_in_use(self):
            engine = Engine()
            window = tray.WelcomeWindow(engine)
            self.addCleanup(window.deleteLater)
            self.assertFalse(window.model_box.isHidden())
            self.assertIn("Parakeet Unified is the best of the models so far",
                          window.model_note.text())
            engine.settings.model = tray.RECOMMENDED
            window.refresh_model()
            self.assertTrue(window.model_box.isHidden())

        def test_it_gives_the_words_that_always_wake_it_and_the_short_ones_only_where_they_work(self):
            engine = Engine()
            window = tray.WelcomeWindow(engine)
            self.addCleanup(window.deleteLater)
            steps = window.steps.text()
            self.assertIn('Say "wake up".', steps)
            self.assertIn('Say "go to sleep" when', steps)
            self.assertNotIn('"wake"', steps)
            engine.settings.states["short_wake"] = True      # switched on in Settings since
            window.refresh_state() if hasattr(window, "refresh_state") else window.say_steps()
            window.say_steps()
            steps = window.steps.text()
            self.assertIn('Say "wake up" (or just "wake").', steps)
            self.assertIn('Say "go to sleep" (or just "sleep") when', steps)

        def test_its_button_downloads_it_and_puts_it_to_use_on_arrival(self):
            engine, started = Engine(), []
            changed = []
            window = tray.WelcomeWindow(engine)
            window.hub.changed = lambda: changed.append(True)
            self.addCleanup(window.deleteLater)
            fetches = window.downloads
            real_start, real_usable = fetches.start, models.transducers_usable
            fetches.start = lambda name: started.append(name) or ""
            models.transducers_usable = lambda: True
            self.addCleanup(setattr, fetches, "start", real_start)
            self.addCleanup(setattr, models, "transducers_usable", real_usable)
            window.refresh_model()
            self.assertEqual(window.model_go.text(), "Install Parakeet Unified")
            window.on_model_go()
            self.assertEqual(started, [tray.RECOMMENDED])
            fetches.finished.emit(tray.RECOMMENDED, "")  # it has arrived
            self.assertIn(("model", tray.RECOMMENDED), engine.asked)
            self.assertEqual(changed, [True])
            self.assertIn("now the model in use", window.model_note.text())

        def test_a_download_that_fails_says_why_in_the_window(self):
            window = tray.WelcomeWindow(Engine())
            self.addCleanup(window.deleteLater)
            real_usable = models.transducers_usable
            models.transducers_usable = lambda: True
            self.addCleanup(setattr, models, "transducers_usable", real_usable)
            window.wanted = True
            window.downloads.finished.emit(tray.RECOMMENDED, "The download site could not be reached.")
            self.assertIn("could not be reached", window.model_note.text())
            self.assertFalse(window.wanted)

    class WhatCanISay(unittest.TestCase):
        def setUp(self):
            self.engine = Engine()
            self.window = tray.HelpWindow(self.engine)
            self.addCleanup(self.window.deleteLater)

        def test_it_lists_every_command_and_sign_with_its_help(self):
            options = settings_module.OPTIONS
            wanted = [item.key for item in settings_module.ITEMS if item.key not in options]
            self.assertEqual([key for key in self.window.shown if key], wanted)
            page = self.window.page.toPlainText()
            for words in ("\"Wake up\"", "\"Go to sleep\"", "\"Scratch that\"", "\"Comma\"",
                          settings_module.HELP["scratch"], "Editing", "Punctuation"):
                self.assertIn(words, page)

        def test_what_is_said_goes_into_the_find_box_while_it_has_the_keyboard(self):
            own = self.window.own
            self.window.on_find_focus(True)                       # as when it is clicked in
            self.window.show()
            self.window.on_find_focus(True)
            self.assertIs(self.engine.targets.own, own)
            self.assertEqual(own.request({"op": "status"}), {"ok": True, "ready": True})
            self.assertEqual(own.request({"op": "insert", "text": "Select"}), {"ok": True, "text": "Select"})
            self.assertEqual(self.window.find.text(), "Select")
            self.assertIn("select", self.window.shown)            # and the list narrowed to it
            self.assertNotIn("say:comma", self.window.shown)
            self.assertEqual(own.request({"op": "context"}),
                             {"ok": True, "before": "Select", "after": "", "selected": ""})
            # A second word goes after the first, on the one line it has.
            own.request({"op": "insert", "text": " all\u2029"})
            self.assertEqual(self.window.find.text(), "Select all")
            self.assertEqual(own.request({"op": "command", "name": "scratch"})["ok"], True)
            self.assertEqual(self.window.find.text(), "Select")
            own.request({"op": "command", "name": "select_all"})
            own.request({"op": "insert", "text": "comma"})        # said over what is selected
            self.assertEqual(self.window.find.text(), "comma")
            # Taken back, what it was said over is there again, and selected again.
            self.assertEqual(own.request({"op": "command", "name": "scratch"}),
                             {"ok": True, "restored": True})
            self.assertEqual((self.window.find.text(), self.window.find.selectedText()),
                             ("Select", "Select"))
            own.request({"op": "insert", "text": "comma"})
            self.assertEqual(self.window.find.text(), "comma")
            self.assertEqual(own.request({"op": "insert", "text": "", "delete_before": 2})["ok"], True)
            self.assertEqual(self.window.find.text(), "com")
            self.assertEqual(own.request({"op": "command", "name": "scratch"}),
                             {"ok": False, "why": "nothing to scratch"})   # it was changed since
            # Left, or its window closed, it is no longer where words go.
            self.window.on_find_focus(False)
            self.assertIsNone(self.engine.targets.own)
            self.window.on_find_focus(True)
            self.window.hide()
            self.assertIsNone(self.engine.targets.own)
            self.window.find.setText("")

        def test_it_does_not_take_the_words_from_another_box_that_has_them(self):
            other = object()
            self.engine.targets.own = other                       # the welcome window's box, say
            self.addCleanup(setattr, self.engine.targets, "own", None)
            self.window.on_find_focus(False)
            self.assertIs(self.engine.targets.own, other)

        def test_it_lists_the_persons_own_commands(self):
            self.engine.settings.shortcuts = {"new tab": "keys: ctrl+t",
                                              "my address": "12 High Street\nDunedin 9016",
                                              "shut down": "ask first\nrun: systemctl poweroff"}
            self.addCleanup(setattr, self.engine.settings, "shortcuts", {})
            self.window.fill()
            page = self.window.page.toPlainText()
            for words in ("My shortcuts and commands", "\"New tab\"", "Does: presses keys", "\"My address\"",
                          "Types: 12 High Street / Dunedin 9016",
                          "Does: asks first, then runs a program"):
                self.assertIn(words, page)
            self.assertNotIn("systemctl", page)          # what it does, not what was written
            self.window.find.setText("runs a program")
            self.assertIn("\"Shut down\"", self.window.page.toPlainText())
            self.assertNotIn("\"New tab\"", self.window.page.toPlainText())
            self.window.find.setText("")

        def test_the_list_narrows_as_the_box_is_typed_in(self):
            everything = len(self.window.shown)
            self.window.find.setText("scratch")
            self.assertIn("scratch", self.window.shown)
            self.assertLess(len(self.window.shown), everything)
            self.assertNotIn("\"Comma\"", self.window.page.toPlainText())
            self.window.find.setText("Punctuation COMMA")  # every word, in any case
            self.assertEqual(self.window.shown, ["say:comma"])
            self.assertIn("1 shown", self.window.count.text())
            self.window.find.setText("xyzzy")
            self.assertEqual(self.window.shown, [])
            self.assertIn("Nothing that can be said", self.window.page.toPlainText())
            self.window.find.setText("")
            self.assertEqual(len(self.window.shown), everything)

        def test_what_is_switched_off_is_marked_in_words(self):
            self.window.find.setText("\"period\"")
            self.assertEqual(self.window.shown, ["say:period"])
            self.assertIn("Switched off in Settings", self.window.page.toPlainText())
            self.engine.settings.states["say:period"] = True
            self.window.fill()
            self.assertNotIn("Switched off in Settings", self.window.page.toPlainText())

    class Settings_(unittest.TestCase):
        def setUp(self):
            self.engine = Engine()
            self.window = tray.SettingsWindow(self.engine)
            self.addCleanup(self.window.deleteLater)

        def focus(self, widget):
            QApplication.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn,
                                                       Qt.FocusReason.TabFocusReason))

        def shown(self):
            """What the tips were asked to show, in place of really showing them."""
            asked = []
            real = tray.QToolTip.showText
            tray.QToolTip.showText = staticmethod(lambda at, text, *more: asked.append(text))
            self.addCleanup(setattr, tray.QToolTip, "showText", real)
            return asked

        def test_tabbing_to_something_shows_its_tip_as_resting_the_mouse_on_it_does(self):
            asked = self.shown()
            scratch, line = self.window.ticks["scratch"], self.window.ticks["new_line"]
            self.focus(scratch)
            self.assertEqual(asked, [scratch.toolTip()])
            self.assertIn(settings_module.HELP["scratch"], asked[0])
            self.focus(line)
            self.assertIn("send the message", asked[-1])
            QApplication.sendEvent(line, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
            self.assertIsNone(self.window.tips.showing)

        def test_a_click_shows_no_tip_and_there_is_no_strip_at_the_foot(self):
            asked = self.shown()
            QApplication.sendEvent(self.window.ticks["undo"],
                                   QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
            self.assertEqual(asked, [])              # the mouse has its own way to the tip
            self.assertFalse(hasattr(self.window, "strip"))
            self.assertIsNone(self.window.findChild(tray.QLabel, "helpStrip"))

        def test_commands_only_is_a_tick_box_beside_the_list_of_commands_and_off(self):
            tick = self.window.ticks["commands_only"]
            self.assertFalse(tick.isChecked())
            self.assertIs(tick.parentWidget(), self.window.shortcuts.parentWidget())
            self.engine.asked.clear()
            tick.setChecked(True)
            self.assertTrue(self.engine.settings.enabled("commands_only"))
            self.assertIn(("setting", "commands_only"), self.engine.asked)   # the engine is told at once

        def test_running_programs_is_a_tick_box_in_the_box_of_my_commands_and_off(self):
            tick = self.window.ticks["run_programs"]
            self.assertFalse(tick.isChecked())
            box = tick.parentWidget()
            self.assertIsInstance(box, tray.QGroupBox)
            self.assertIn("shortcuts and commands", box.title().replace("&", "").lower())
            self.assertIs(self.window.shortcuts.parentWidget(), box)   # the same box as the lines
            self.assertEqual(len([b for b in self.window.findChildren(tray.QGroupBox)
                                  if "shortcuts and commands" in b.title().replace("&", "").lower()]), 1)
            tick.setChecked(True)
            self.assertTrue(self.engine.settings.enabled("run_programs"))

        def test_a_greyed_tick_box_says_why_first_and_can_be_tabbed_to(self):
            idle = settings_module.without_effect(config.AWAKE_MODEL, self.engine.settings.remote,
                                                  config.MODEL_DIR)
            self.assertTrue(idle)  # with no Parakeet model here, at least one does nothing
            for name, why in idle.items():
                tick = self.window.ticks[name]
                self.assertTrue(tick.isEnabled())
                self.assertTrue(tick.text().endswith(self.window.IDLE))
                # The reason first, in its tip: where quotation marks are written for a web page.
                import html
                self.assertIn(html.escape(why), tick.toolTip())
                self.assertTrue(tick.accessibleDescription().startswith(why))

        def test_every_tick_box_has_its_help_as_tip_and_description(self):
            for name, tick in self.window.ticks.items():
                about = settings_module.help_for(name)
                if about:
                    self.assertIn(about, tick.accessibleDescription(), name)
                    self.assertTrue(tick.toolTip(), name)

        def test_a_long_line_gives_its_brackets_to_its_help(self):
            long = "Leave out sounds that aren't speech  (Parakeet can write a rustle as \"yeah\")"
            self.assertEqual(tray.tick_words(long),
                             ("Leave out sounds that aren't speech",
                              "Parakeet can write a rustle as \"yeah\"."))
            short = "\"Tab\"  (the Tab key)"
            self.assertEqual(tray.tick_words(short), (short, ""))
            longest = max(len(tick.text()) for tick in self.window.ticks.values())
            self.assertLess(longest, 100)

        def test_what_is_wrong_is_said_at_the_top_and_nothing_when_nothing_is(self):
            self.assertTrue(self.window.banner_box.isHidden())
            self.engine.status.problems = ["Port 47613 is in use, so Thunderbird can't be reached."]
            self.engine.status.failed = "No model could be loaded."
            self.window.refresh_banner()
            self.assertFalse(self.window.banner_box.isHidden())
            self.assertIn("Port 47613", self.window.banner.text())
            self.assertIn("No model could be loaded.", self.window.banner.text())
            self.engine.status.problems, self.engine.status.failed = [], ""
            self.window.refresh_banner()
            self.assertTrue(self.window.banner_box.isHidden())

        def test_the_recommended_model_is_parakeet_unified(self):
            from PyQt6.QtWidgets import QLabel
            words = " ".join(label.text() for label in self.window.findChildren(QLabel))
            self.assertIn("Parakeet Unified is the best of the models so far", words)
            # One rule, said where the model is chosen: no other model listens for "wake up".
            self.assertIn("The model chosen here does all the listening, \"wake up\" included.", words)
            self.assertNotIn("still listened for", words)
            self.assertNotIn("recommended model", words)
            self.assertFalse(self.window.suggest.isHidden())  # it isn't installed here

        def test_choosing_a_model_loads_it_once(self):
            a_model("small.en")
            a_model("medium.en")
            self.window.refill_models()
            at = self.window.models.findData("medium.en")
            self.window.models.activated.emit(at)
            self.assertEqual(self.engine.asked.count(("model", "medium.en")), 1)
            self.window.models.activated.emit(self.window.models.findData("medium.en"))
            self.assertEqual(self.engine.asked.count(("model", "medium.en")), 1)  # the same again

        @unittest.skipUnless(hasattr(Settings, "set_shortcuts"), "the settings have no shortcuts yet")
        def test_my_shortcuts_are_kept_as_typed_and_unclear_lines_are_shown(self):
            box = self.window.shortcuts
            box.setPlainText("my address = 12 High Street\n    Dunedin 9016\nno equals sign here\n")
            self.window.save_shortcuts()
            self.assertEqual(getattr(self.engine.settings, "shortcuts", {}).get("my address"),
                             "12 High Street\nDunedin 9016")
            self.assertFalse(self.window.shortcuts_note.isHidden())
            self.assertIn("no equals sign here", self.window.shortcuts_note.text())
            self.assertIn("1 line couldn't be understood", self.window.shortcuts_note.text())
            self.assertTrue(box.toPlainText().startswith("my address"))  # left as it was typed
            box.setPlainText("my address = 12 High Street\n    Dunedin 9016\n")
            self.window.save_shortcuts()
            self.assertTrue(self.window.shortcuts_note.isHidden())

        def test_start_when_i_sign_in_is_asked_and_switched_through_autostart(self):
            tick = self.window.start_tick
            self.assertFalse(tick.tick.isEnabled())  # not asked until the window is shown
            tick.refresh()
            self.assertTrue(tick.tick.isEnabled() and tick.tick.isChecked())
            del SWITCHED[:]
            tick.on_click(False)
            self.assertEqual(SWITCHED, [False])
            real = autostart.state
            autostart.state = lambda *a, **k: None
            self.addCleanup(setattr, autostart, "state", real)
            tick.refresh()
            self.assertFalse(tick.tick.isEnabled())
            self.assertEqual(tick.note.text(), autostart.CANT_TELL)

    class TheKey(unittest.TestCase):
        def test_no_key_to_begin_with_and_the_choice_is_handed_on(self):
            engine, asked = Engine(), []
            hub = tray.Hub()
            hub.set_hotkey = lambda name: asked.append(name) or ""
            chooser = tray.KeyChooser(engine, hub)
            self.addCleanup(chooser.deleteLater)
            self.assertEqual(chooser.keys.itemText(0), "None")
            self.assertEqual([chooser.keys.itemData(n) for n in range(1, chooser.keys.count())],
                             list(hotkey.KEYS))
            self.assertEqual(chooser.keys.currentData(), tray.hotkey_of(engine.settings))
            chooser.keys.activated.emit(chooser.keys.findData("Pause"))
            self.assertEqual(asked, ["Pause"])

        def test_a_key_windows_refused_is_said_beside_the_chooser(self):
            engine, hub = Engine(), tray.Hub()
            engine.settings.hotkey = "F9"
            hub.hotkey_problem = lambda: "Windows wouldn't give the key \"F9\"."
            chooser = tray.KeyChooser(engine, hub)
            self.addCleanup(chooser.deleteLater)
            self.assertEqual(chooser.keys.currentData(), "F9")
            self.assertIn("wouldn't give", chooser.note.text())
            hub.hotkey_problem = lambda: ""
            chooser.refresh()
            self.assertEqual(chooser.note.text(), hotkey.COSTS["F9"])

        def test_settings_from_before_the_choice_are_read_with_care(self):
            self.assertEqual(tray.hotkey_of(SimpleNamespace(hotkey="Pause")), "Pause")
            self.assertEqual(tray.hotkey_of(SimpleNamespace(hotkey="Caps Lock")), "")
            old = SimpleNamespace(enabled=lambda key: True)
            self.assertEqual(tray.hotkey_of(old), "Number pad +")
            def none(key):
                raise KeyError(key)
            self.assertEqual(tray.hotkey_of(SimpleNamespace(enabled=none)), "")

    class TheTray(unittest.TestCase):
        """The tray itself, with the stand-in engine in the real one's place."""

        @classmethod
        def setUpClass(cls):
            cls.real = tray.Engine
            tray.Engine = Engine
            for path in (config.SETTINGS_FILE, config.STATE_FILE):
                if os.path.exists(path):
                    os.remove(path)  # as on a first start: nothing has been kept yet
            cls.tray = tray.Tray(APP)
            cls.tray.update_timer.stop()
            cls.tray.show_timer.stop()

        @classmethod
        def tearDownClass(cls):
            tray.Engine = cls.real
            cls.tray.tray.hide()

        def setUp(self):
            self.t = self.tray
            self.engine = self.t.engine
            self.engine.asked.clear()
            self.said = []
            self.t.say = lambda title, message, icon, ms: self.said.append((title, message, ms))

        def test_a_window_of_its_own_takes_leave_to_come_forward_before_it_asks_for_the_keyboard(self):
            from unittest import mock
            order = []
            window = SimpleNamespace(isMinimized=lambda: False, show=lambda: order.append("show"),
                                     raise_=lambda: order.append("raise"),
                                     activateWindow=lambda: order.append("keyboard"))
            with mock.patch.object(tray.actions, "let_come_forward", lambda: order.append("leave")):
                tray.bring(window)
            self.assertEqual(order, ["show", "leave", "raise", "keyboard"])

        def test_commands_only_shows_on_the_icon_and_is_not_in_the_menu(self):
            self.assertFalse(hasattr(self.t, "commands_only"))
            self.assertFalse([a for a in self.t.menu.actions() if "ommand" in a.text()])
            self.engine.status.state = State.AWAKE
            self.addCleanup(setattr, self.engine.status, "state", State.ASLEEP)
            self.addCleanup(setattr, self.engine.status, "commands_only", False)
            plain = self.t.icon_now()
            self.engine.status.commands_only = True            # as ticked in Settings
            marked = self.t.icon_now()
            self.assertIsNot(marked, plain)                    # the icon with a "C" on it
            self.assertIs(marked, self.t.command_icons[State.AWAKE, self.engine.status.level])
            # A "C" really is drawn: the two pictures differ.
            self.assertNotEqual(tray.make_pixmap(State.AWAKE, commands=True).toImage(),
                                tray.make_pixmap(State.AWAKE).toImage())
            # Asleep or off there is no typing to warn about: the usual icons.
            self.engine.status.state = State.ASLEEP
            self.assertIs(self.t.icon_now(), self.t.icons[State.ASLEEP, self.engine.status.level])

        def test_the_first_time_the_welcome_window_is_shown_not_settings(self):
            self.assertTrue(self.t.welcome_window.isVisible())
            self.assertFalse(self.t.settings_window.isVisible())

        def test_and_only_the_first_time(self):
            # The settings are kept as soon as the welcome has been shown, changed or
            # not: so the next start finds them, and is not a first time again.
            self.assertTrue(os.path.exists(config.SETTINGS_FILE))
            self.assertFalse(Settings.load(config.SETTINGS_FILE).first_time)
            self.assertFalse(self.engine.settings.first_time)

        def test_the_window_that_stands_in_for_the_icon_follows_the_menu_and_dies_quietly(self):
            actions = [self.t.wake, self.t.quit] if hasattr(self.t, "wake") else list(self.t.menu.actions())[:2]
            window = tray.StatusWindow(self.engine, actions)
            self.assertTrue(window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
            actions[0].setText("Go to sleep")
            self.assertEqual(window.buttons[0].text(), "Go to sleep")
            raised = []
            real, sys.excepthook = sys.excepthook, lambda *about: raised.append(about)
            self.addCleanup(setattr, sys, "excepthook", real)
            window.close()
            tray.sip.delete(window)          # as a change of look does away with it
            actions[0].setText("Wake up")    # its buttons are gone: nothing may reach for them
            self.assertEqual(raised, [])

        def test_a_notice_from_the_engine_is_shown(self):
            self.engine.on_notice("Nothing to type into. Click in Writer.", "problem")
            self.engine.on_notice("Selected: the black cat", "info")
            self.assertEqual(self.said, [
                (tray.APP_NAME, "Nothing to type into. Click in Writer.", 6000),
                (tray.APP_NAME, "Selected: the black cat", 2500)])

        def test_a_click_wakes_from_asleep_or_off_and_switches_off_from_awake(self):
            for state, wanted in ((State.ASLEEP, "wake"), (State.OFF, "wake"),
                                  (State.AWAKE, "turn_off"), (State.HEARING, "turn_off"),
                                  (State.THINKING, "turn_off")):
                self.engine.status.state = state
                self.engine.asked.clear()
                self.t.on_click(tray.QSystemTrayIcon.ActivationReason.Trigger)
                self.assertEqual(self.engine.asked, [wanted], state)
            self.engine.asked.clear()
            self.t.on_click(tray.QSystemTrayIcon.ActivationReason.Context)  # the menu's click
            self.assertEqual(self.engine.asked, [])

        def test_the_menu_has_the_new_entries_and_says_microphone(self):
            words = [action.text() for action in self.t.menu.actions() if action.text()]
            for wanted in ("What can I say?", "Getting started", "Open the log",
                           "Microphone level…", "Settings…", "Quit"):
                self.assertIn(wanted, words)
            self.engine.status.state = State.OFF
            self.t.refresh()
            self.assertEqual(self.t.toggle.text(), "Turn microphone on")
            self.engine.status.state = State.ASLEEP
            self.t.refresh()
            self.assertEqual(self.t.toggle.text(), "Turn microphone off")

        def test_what_is_asked_from_outside_is_done(self):
            self.engine.status.state = State.ASLEEP
            control.ask("toggle")
            self.t.check_requests()
            self.assertEqual(self.engine.asked, ["wake"])
            control.ask("sleep")
            control.ask("off")
            self.t.check_requests()
            self.assertEqual(self.engine.asked, ["wake", "sleep", "turn_off"])
            self.t.settings_window.hide()
            control.ask("settings")
            self.t.check_requests()
            self.assertTrue(self.t.settings_window.isVisible())
            self.t.settings_window.hide()
            control.ask(control.SHOW)  # a second start, or the menu's entry
            self.t.check_requests()
            self.assertTrue(self.t.settings_window.isVisible())
            self.t.settings_window.hide()

        def test_the_windows_asked_for_by_voice_open_and_close(self):
            self.t.help_window.hide()
            self.t.notify("app:help")
            self.assertTrue(self.t.help_window.isVisible())
            self.t.notify("app:close")  # the one opened last
            self.assertFalse(self.t.help_window.isVisible())
            self.t.notify("app:settings")
            self.assertTrue(self.t.settings_window.isVisible())
            self.t.notify("app:close")
            self.assertFalse(self.t.settings_window.isVisible())

        def test_awake_is_only_said_when_it_woke(self):
            self.engine.status.state = State.OFF  # the microphone couldn't be opened
            self.t.notify("wake")
            self.assertEqual(self.said, [])
            self.engine.status.state = State.AWAKE
            self.t.notify("wake")
            self.assertEqual([message for _, message, _ in self.said], ["Awake"])

        def test_ready_says_how_to_start_only_while_asleep(self):
            self.engine.status.state = State.AWAKE
            self.t.notify("ready")
            self.engine.status.state = State.ASLEEP
            self.t.notify("ready")
            self.assertEqual([message for _, message, _ in self.said],
                             ["Ready.", "Ready. Say \"wake up\" to start."])

        def test_no_model_has_an_icon_and_a_notice_of_its_own(self):
            self.engine.status.failed = "The model small.en could not be loaded."
            try:
                self.assertIs(self.t.icon_now(), self.t.failed_icon)
                self.t.notify("failed")
                self.assertIn("could not be loaded", self.said[0][1])
                self.assertIn("Install or remove models", self.said[0][1])
                self.assertFalse(self.t.settings_window.banner_box.isHidden())
            finally:
                self.engine.status.failed = ""
                self.t.settings_window.refresh_banner()
            self.assertIsNot(self.t.icon_now(), self.t.failed_icon)

        def test_a_writer_extension_that_fails_is_said_once_and_not_tried_again(self):
            self.t.updating = True
            self.t.on_extension("unopkg: the extension is damaged")
            self.assertTrue(self.t.extension_failed)
            self.assertFalse(self.t.updating)
            self.assertIn("could not be put into LibreOffice", self.said[0][1])
            self.assertIn("the extension is damaged", self.t.settings_window.banner.text())
            self.t.extension_failed = False
            self.t.settings_window.extension_problem = ""
            self.said.clear()
            self.t.on_extension("")
            self.assertIn("Writer is ready", self.said[0][1])
            self.t.settings_window.refresh_banner()

        def test_with_no_tray_a_window_stands_in_for_the_icon(self):
            window = self.t.status_window
            self.assertFalse(window.isVisible())
            if tray.QSystemTrayIcon.isSystemTrayAvailable():
                self.skipTest("this desktop has a tray")
            self.t.no_tray = 0
            for _ in range(self.t.NO_TRAY_CHECKS - 1):
                self.t.check_tray()  # it may only be late in coming up
                self.assertFalse(window.isVisible())
            self.t.check_tray()
            self.assertTrue(window.isVisible())
            words = [button.text() for button in window.buttons]
            self.assertIn("Quit", words)
            self.assertIn("Settings…", words)
            self.t.say = type(self.t).say.__get__(self.t)
            self.t.say(tray.APP_NAME, "Asleep", self.t.icon_now(), 1500)
            self.assertEqual(window.notice.text(), "Asleep")  # there is no tray to say it
            window.close()  # there is nothing else to work the program by: it stays
            self.assertTrue(window.isVisible() or window.isMinimized())
            window.stay = False
            window.close()

    class LongTasks(unittest.TestCase):
        def test_the_level_meter_closes_itself_after_a_minute_of_quiet(self):
            window = tray.MeterWindow(Engine())
            self.addCleanup(window.deleteLater)
            closed = []
            window.close = lambda: closed.append(True)
            window.listening = True
            window.last_sound = time.monotonic() - (window.CLOSE_SECONDS - 10)
            window.check()
            self.assertEqual(closed, [])
            self.assertIn("Closing in", window.closing.text())  # it says that it will
            window.on_level(window.opening, 80, 0.3, True)  # somebody spoke: it stays
            window.check()
            self.assertEqual(window.closing.text(), window.STAYS)
            window.last_sound = time.monotonic() - window.CLOSE_SECONDS - 1
            window.check()
            self.assertEqual(closed, [True])
            window.listening = False

        def test_a_download_is_paused_not_thrown_away_and_its_rows_stay_put(self):
            engine = Engine()
            window = tray.ModelsWindow(engine, lambda: None)
            self.addCleanup(window.deleteLater)
            name = "tiny.en"
            button = window.rows[name][3]
            self.assertEqual((button.text(), button.accessibleName()), ("Install", "Install Tiny"))
            fetches = window.downloads
            fetches.name = name
            fetches.download = SimpleNamespace(cancelled=False, cancel=lambda: setattr(
                fetches.download, "cancelled", True))
            self.addCleanup(setattr, fetches, "name", "")
            self.addCleanup(setattr, fetches, "download", None)
            window.refresh()
            self.assertIs(window.rows[name][3], button)  # changed where it stands
            self.assertEqual(button.text(), "Pause")
            fetches.progress.emit(name, 40, 100)
            self.assertIn("Downloading: 40%", window.status[name].text())
            window.on_button(name)
            self.assertTrue(fetches.download.cancelled)
            os.makedirs(os.path.join(config.MODEL_DIR, name + models.PART), exist_ok=True)
            with open(os.path.join(config.MODEL_DIR, name + models.PART, "model.bin"), "wb") as f:
                f.truncate(40_000_000)
            fetches.name, fetches.download = "", None
            fetches.finished.emit(name, tray.Downloads.PAUSED)
            self.assertEqual(button.text(), "Carry on")
            self.assertIn("Paused", window.status[name].text())
            self.assertTrue(os.path.exists(os.path.join(config.MODEL_DIR, name + models.PART)))
            self.assertFalse(window.rows[name][4].isHidden())  # and "Discard" beside it
            shutil.rmtree(os.path.join(config.MODEL_DIR, name + models.PART))

        def test_a_finished_download_is_said_whether_or_not_a_window_is_open(self):
            for window in QApplication.topLevelWidgets():
                window.hide()  # no window is open to say it in
            fetches, said = tray.downloads(), []
            real = fetches.announce
            fetches.announce = lambda text, kind="info": said.append((text, kind))
            self.addCleanup(setattr, fetches, "announce", real)
            fetches.on_over("medium.en", "")
            fetches.on_over("medium.en", tray.Downloads.PAUSED)
            fetches.on_over("medium.en", "The download site could not be reached.")
            self.assertEqual(said[0], ("Medium is installed.", "info"))
            self.assertEqual(len(said), 2)  # paused on purpose is not news
            self.assertEqual(said[1][1], "problem")
            # And with a window open that shows downloads, but another model's: the
            # failure of this one would otherwise be said nowhere.
            welcome = tray.WelcomeWindow(Engine())
            self.addCleanup(welcome.deleteLater)
            self.addCleanup(welcome.close)   # not left open for the tests after this one
            welcome.show()
            fetches.on_over("medium.en", "The download site could not be reached.")
            self.assertEqual(len(said), 3)

        def test_only_one_download_at_a_time_and_room_is_asked_about_first(self):
            fetches = tray.downloads()
            fetches.name = "medium.en"
            self.addCleanup(setattr, fetches, "name", "")
            self.assertIn("Another model is being downloaded", fetches.start("tiny.en"))
            fetches.name = ""
            real = models.free_space
            models.free_space = lambda folder: 1_000_000
            self.addCleanup(setattr, models, "free_space", real)
            self.assertIn("enough free disk space", fetches.start("tiny.en"))
            self.assertEqual(fetches.name, "")
            self.assertTrue(fetches.start("no-such-model"))

        def downloads_that_only_pretend(self, here):
            """The downloads, with nothing really fetched: `here` is what is installed,
            and grows as each "arrives". Returns (the downloads, what was started, what
            was said)."""
            fetches, started, said = tray.downloads(), [], []

            class Pretend:
                cancelled = False

                def __init__(self, known, folder, progress=None):
                    started.append(known.name)

            class NoThread:
                def __init__(self, target=None, daemon=None):
                    pass

                def start(self):
                    pass

            for where, name, stand_in in (
                    (models, "Download", Pretend), (tray.threading, "Thread", NoThread),
                    (models, "free_space", lambda folder: 10 ** 12),
                    (models, "is_installed", lambda folder, name: name in here),
                    # (Where Speech Note's models are used, the helper goes by its name
                    # for it, which is none that can be fetched: here it is the usual one.)
                    (config, "WAKE_MODEL", "small.en"),
                    (fetches, "announce", lambda text, kind="info": said.append((text, kind)))):
                self.addCleanup(setattr, where, name, getattr(where, name))
                setattr(where, name, stand_in)
            self.addCleanup(setattr, fetches, "name", "")
            self.addCleanup(setattr, fetches, "after", "")
            self.addCleanup(setattr, fetches, "download", None)
            return fetches, started, said

        def test_a_parakeet_brings_small_with_it_where_small_is_not_here(self):
            # A computer installed with no models: a Parakeet leans on Small, so Small is
            # fetched first, and the Parakeet when that is in.
            here = set()
            fetches, started, said = self.downloads_that_only_pretend(here)
            self.assertEqual(fetches.start(tray.RECOMMENDED), "")
            self.assertEqual((started, fetches.name, fetches.after),
                             ([config.WAKE_MODEL], config.WAKE_MODEL, tray.RECOMMENDED))
            self.assertIn("Small is fetched first", said[0][0])
            here.add(config.WAKE_MODEL)
            fetches.on_over(config.WAKE_MODEL, "")           # Small has arrived
            self.assertEqual((started, fetches.name, fetches.after),
                             ([config.WAKE_MODEL, tray.RECOMMENDED], tray.RECOMMENDED, ""))
            fetches.on_over(tray.RECOMMENDED, "")
            self.assertEqual((len(started), fetches.name), (2, ""))

        def test_with_small_here_a_parakeet_is_fetched_by_itself(self):
            here = set()
            fetches, started, said = self.downloads_that_only_pretend(here)
            here.add(config.WAKE_MODEL)
            self.assertEqual(fetches.start(tray.RECOMMENDED), "")
            self.assertEqual((started, fetches.after, said), ([tray.RECOMMENDED], "", []))

        def test_a_whisper_model_is_fetched_by_itself_too(self):
            fetches, started, said = self.downloads_that_only_pretend(set())
            self.assertEqual(fetches.start("medium.en"), "")
            self.assertEqual((started, fetches.after), (["medium.en"], ""))

        def test_small_paused_or_failed_leaves_the_parakeet_for_another_time(self):
            for problem in (tray.Downloads.PAUSED, "The download site could not be reached."):
                fetches, started, said = self.downloads_that_only_pretend(set())
                fetches.start(tray.RECOMMENDED)
                fetches.on_over(config.WAKE_MODEL, problem)
                self.assertEqual((started, fetches.name, fetches.after), ([config.WAKE_MODEL], "", ""))

        def test_the_first_model_to_arrive_is_handed_to_the_engine(self):
            told = []
            handler = SimpleNamespace(engine=SimpleNamespace(model_installed=told.append))
            tray.Tray.on_model_installed(handler, "small.en", "")
            tray.Tray.on_model_installed(handler, "medium.en", "The download site could not be reached.")
            self.assertEqual(told, ["small.en"])
            tray.Tray.on_model_installed(SimpleNamespace(engine=Engine()), "small.en", "")   # an engine that isn't asked

        def test_the_voice_test_goes_on_with_its_window_closed(self):
            hub, said = tray.Hub(), []
            hub.announce = lambda text, kind="info": said.append(text)
            window = tray.VoiceTestWindow(Engine(), hub=hub)
            self.addCleanup(window.deleteLater)
            window.running = True
            window.close()
            self.assertFalse(window.stop.is_set())  # the test isn't ended by closing
            self.assertTrue(window.busy())
            window.on_finished(True)
            self.assertFalse(window.busy())
            self.assertEqual(len(said), 1)
            self.assertIn("voice test has finished", said[0])
            window.recording = True  # but nobody reads to a closed window
            window.close()
            self.assertTrue(window.stop.is_set() and window.given_up)
            window.recording = False

        def test_the_reading_window_keeps_its_keys_and_lets_buttons_be_pressed(self):
            window = tray.ReadWindow(Engine())
            self.addCleanup(window.deleteLater)
            moved = []
            window.on_next = lambda: moved.append(True)
            window.show()
            # The window itself has the keyboard to begin with, not the first button.
            self.assertIn(window.focusWidget(), (None, window))
            key(window, Qt.Key.Key_Space, " ")
            self.assertEqual(moved, [True])
            self.assertEqual(window.by_itself.focusPolicy(), Qt.FocusPolicy.TabFocus)
            self.assertEqual(window.next.focusPolicy(), Qt.FocusPolicy.NoFocus)
            close = next(b for b in window.findChildren(QPushButton)
                         if b.text().replace("&", "") == "Close")
            close.setFocus()
            key(window, Qt.Key.Key_Return)  # presses Close, and starts no reading
            self.assertEqual(moved, [True])
            self.assertFalse(window.isVisible())
            self.assertFalse(window.idle.isActive())  # nothing ticks while it is closed

        def test_reading_that_is_not_taken_for_the_sentence_is_still_somebody_reading(self):
            from dictation import reading
            window = tray.ReadWindow(Engine())
            self.addCleanup(window.deleteLater)
            orders = []
            window.order = lambda name, *more: orders.append(name)
            window.reading = window.listening = True
            window.current, window.epoch = "The cat sat on the mat.", 3
            window.acted = time.monotonic() - 50
            window.on_level(60, 0.3, True)
            self.assertLess(time.monotonic() - window.acted, 1)  # speech counts: no pause
            window.on_heard(3, 10, "something else entirely was said here instead")
            self.assertEqual(orders, ["again"])
            self.assertFalse(window.offered)
            window.on_heard(3, 20, "something else entirely was said here instead")
            self.assertEqual(orders, ["again"])  # the second reading is held, not thrown away
            self.assertTrue(window.offered)
            self.assertIn("press the space bar to keep it as you read it", window.said.text())
            self.assertEqual(reading.verdict(window.current, "something else entirely was said "
                                             "here instead"), reading.ASTRAY)
            window.reading = window.listening = False

    REAL_ASK = tray.ask

else:
    class InAProcessOfTheirOwn(unittest.TestCase):
        @unittest.skipUnless(HAVE_QT, "PyQt6 isn't installed for this Python")
        def test_the_windows(self):
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env = {name: value for name, value in os.environ.items() if not name.startswith("LS_")}
            done = subprocess.run([sys.executable, "-m", "unittest", "tests.test_windows"],
                                  cwd=here, env=env, capture_output=True, text=True, timeout=600)
            self.assertEqual(done.returncode, 0, "\n" + done.stderr[-6000:])


if __name__ == "__main__":
    unittest.main()

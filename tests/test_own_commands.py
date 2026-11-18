"""Commands of the person's own that do something, and the choice of commands only."""
import os
import unittest
from unittest import mock

from dictation import actions, commands, config
from dictation.commands import Command, interpret
from dictation.settings import ITEMS, OPTIONS, Settings, parse_shortcuts
from dictation.status import State, Status

from tests.test_engine_correct import Program
from tests.test_engine_telling import Quiet, bare


class AsTheyAreWritten(unittest.TestCase):
    def test_a_text_is_still_a_shortcut(self):
        for written in ("12 High Street\nDunedin 9016", "Kind regards,", "see: the notes",
                        "a note: keys are under the mat"):
            self.assertIsNone(actions.parse(written), written)

    def test_each_kind_of_step(self):
        self.assertEqual(actions.parse("keys: Ctrl+Shift+T"), [("keys", ["ctrl+shift+t"])])
        self.assertEqual(actions.parse("keys: ctrl+k ctrl+s"), [("keys", ["ctrl+k", "ctrl+s"])])
        self.assertEqual(actions.parse("keys: ctrl+k, ctrl+s"), [("keys", ["ctrl+k", "ctrl+s"])])
        self.assertEqual(actions.parse("open: ~/notes.txt"), [("open", "~/notes.txt")])
        self.assertEqual(actions.parse("Run: make -C ~/project"), [("run", "make -C ~/project")])
        self.assertEqual(actions.parse("type: open: the door"), [("type", "open: the door")])
        self.assertEqual(actions.parse("wait: 2"), [("wait", 2.0)])
        self.assertEqual(actions.parse("wait: 0.5 seconds"), [("wait", 0.5)])

    def test_further_lines_are_further_steps(self):
        self.assertEqual(actions.parse("open: https://example.org/news\nwait: 2\nkeys: page down"),
                         [("open", "https://example.org/news"), ("wait", 2.0), ("keys", ["pagedown"])])
        self.assertEqual(actions.parse("ask first\nrun: systemctl poweroff"),
                         [("ask",), ("run", "systemctl poweroff")])

    def test_keys_by_their_other_names(self):
        self.assertEqual(actions.chords("Control+Esc alt+F4 win+d ctrl+plus shift+Return ctrl+Page Up"),
                         ["ctrl+escape", "alt+f4", "win+d", "ctrl+plus", "shift+enter", "ctrl+pageup"])

    def test_every_key_is_known_to_both_systems(self):
        from dictation import keys_target, portal_keys
        for name in actions.KEY_NAMES:
            self.assertIn(name, keys_target.KEYS, name)
            self.assertTrue(name in portal_keys.KEYSYMS or len(name) == 1, name)
        self.assertEqual(keys_target.KEYS["f12"], 0x7B)
        self.assertEqual(portal_keys.KEYSYMS["f12"], 0xFFC9)
        # ... and the ones dictation itself has always pressed are as they were.
        self.assertEqual((keys_target.KEYS["enter"], keys_target.KEYS["a"], keys_target.KEYS["z"]),
                         (0x0D, 0x41, 0x5A))

    def test_what_cannot_be_understood_is_said_in_words(self):
        for written, word in (("keys: hyper+x", "hyper"), ("keys: ctrl", "presses none"),
                              ("keys:", "no keys"), ("wait: soon", "soon"), ("wait: 60", "up to"),
                              ("run:", "nothing is given"), ("open: x\nnonsense", "not a step"),
                              ("ask first", "nothing is done"), ("keys: a\nask first", "first step"),
                              ("run: \"unclosed", "can't be read"),
                              ("wait: 9\nwait: 9\nwait: 9\nwait: 9", "more than"),
                              ("\n".join(["keys: a"] * 13), "up to 12")):
            with self.assertRaises(ValueError, msg=written) as raised:
                actions.parse(written)
            self.assertIn(word, str(raised.exception), written)

    def test_a_command_that_runs_a_program_is_two_words_or_more(self):
        self.assertIn("two words", actions.problem("build", "run: make"))
        self.assertEqual(actions.problem("build it", "run: make"), "")
        self.assertEqual(actions.problem("tab", "keys: ctrl+t"), "")       # keys may be one word
        self.assertEqual(actions.problem("address", "12 High Street"), "")

    def test_settings_keeps_what_can_be_done_and_says_what_cannot(self):
        found, problems = parse_shortcuts(
            "my address = 12 High Street\n    Dunedin 9016\n"
            "new tab = keys: ctrl+t\n"
            "morning = open: https://example.org\n    wait: 2\n    keys: ctrl+l\n"
            "build = run: make\n"
            "odd = keys: hyper+x\n")
        self.assertEqual(found, {"my address": "12 High Street\nDunedin 9016",
                                 "new tab": "keys: ctrl+t",
                                 "morning": "open: https://example.org\nwait: 2\nkeys: ctrl+l"})
        self.assertEqual(len(problems), 2)
        self.assertTrue(problems[0].startswith("build") and "two words" in problems[0])
        self.assertTrue(problems[1].startswith("odd") and "hyper" in problems[1])

    def test_the_log_is_told_the_kinds_only(self):
        steps = actions.parse("open: ~/private/diary.txt\nrun: secret --flag\nkeys: ctrl+s")
        self.assertEqual(actions.kinds(steps), "open, run, keys")
        self.assertEqual(actions.done(steps[1]), "Ran: secret --flag")
        self.assertEqual(actions.done(steps[2]), "")


class Starting(unittest.TestCase):
    """What is started, and how: with no shell, and nothing but what was written."""

    def setUp(self):
        self.started = []
        for patch in (mock.patch.object(actions.subprocess, "Popen",
                                        lambda command, **how: self.started.append((command, how))),
                      mock.patch.object(actions.config, "WINDOWS", False),
                      mock.patch.dict(os.environ, {"HOME": "/home/somebody"}, clear=False)):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("INVOCATION_ID", None)

    def test_a_line_is_the_program_and_what_it_is_given_and_no_shell_reads_it(self):
        with mock.patch.object(actions.shutil, "which", lambda name: "/usr/bin/" + name):
            actions.Doer().run('make -C ~/project "two words" $HOME/x ; rm -rf / | cat > /etc/passwd')
        command, how = self.started[0]
        self.assertEqual(command, ["/usr/bin/make", "-C", "/home/somebody/project", "two words",
                                   "/home/somebody/x", ";", "rm", "-rf", "/", "|", "cat", ">",
                                   "/etc/passwd"])        # all of it only words given to make
        self.assertNotIn("shell", how)
        self.assertTrue(how["start_new_session"])

    def test_a_program_that_is_not_there_is_said(self):
        with mock.patch.object(actions.shutil, "which", lambda name: None):
            with self.assertRaises(actions.ActionError) as raised:
                actions.Doer().run("no-such-program --now")
        self.assertIn("no-such-program", str(raised.exception))
        self.assertEqual(self.started, [])

    def test_from_a_service_it_is_started_in_a_place_of_its_own(self):
        os.environ["INVOCATION_ID"] = "abc"
        self.addCleanup(os.environ.pop, "INVOCATION_ID", None)
        with mock.patch.object(actions.shutil, "which", lambda name: "/usr/bin/" + name):
            actions.Doer().run("kate")
        self.assertEqual(self.started[0][0],
                         ["systemd-run", "--user", "--scope", "--quiet", "--", "/usr/bin/kate"])

    def test_a_web_page_is_opened_as_it_is_written_and_a_missing_file_is_said(self):
        with mock.patch.object(actions.shutil, "which", lambda name: "/usr/bin/" + name):
            actions.Doer().open("https://example.org/a?b=~c")
            with self.assertRaises(actions.ActionError) as raised:
                actions.Doer().open("~/no/such/file.txt")
        self.assertEqual(self.started[0][0], ["/usr/bin/xdg-open", "https://example.org/a?b=~c"])
        self.assertIn("/home/somebody/no/such/file.txt", str(raised.exception))
        self.assertEqual(len(self.started), 1)


class PressingKeysOnWindows(unittest.TestCase):
    """As a keyboard does it: each key with its place, down in order and up in reverse."""

    def test_a_chord_is_each_key_down_then_up_in_reverse_with_its_place_on_the_keyboard(self):
        from dictation import keys_target
        places = {0x12: 0x38, 0x73: 0x3E, 0x11: 0x1D, 0x24: 0x47}
        events = keys_target.chord_events("alt+f4", places.get)
        self.assertEqual(events, [(0x12, 0x38, 0), (0x73, 0x3E, 0), (0x73, 0x3E, 2), (0x12, 0x38, 2)])
        # A key that shares its place with one on the number pad says which it is.
        self.assertEqual(keys_target.chord_events("ctrl+home", places.get),
                         [(0x11, 0x1D, 0), (0x24, 0x47, 1), (0x24, 0x47, 3), (0x11, 0x1D, 2)])
        self.assertGreater(keys_target.CHORD_PAUSE, 0)        # not all at once: see press_keys

    def test_what_windows_will_not_take_is_said(self):
        from dictation import keys_target
        with mock.patch.object(actions.config, "WINDOWS", True), \
                mock.patch.object(keys_target, "press_keys", side_effect=OSError("no")):
            with self.assertRaises(actions.ActionError) as raised:
                actions.Doer().press("alt+f4")
        self.assertIn("administrator", str(raised.exception))
        with mock.patch.object(actions.config, "WINDOWS", True), \
                mock.patch.object(keys_target, "press_keys", return_value="Notepad.exe"):
            self.assertEqual(actions.Doer().press("alt+f4"), "Notepad.exe")


class ComingToTheFrontOnWindows(unittest.TestCase):
    """What is opened by voice has to be let forward, or it opens behind the rest."""

    def test_leave_is_given_before_a_thing_is_opened_and_before_a_program_is_run(self):
        order = []
        with mock.patch.object(actions.config, "WINDOWS", True), \
                mock.patch.object(actions, "let_come_forward", lambda: order.append("leave")), \
                mock.patch.object(actions.os, "startfile", lambda target: order.append("open"), create=True), \
                mock.patch.object(actions.os.path, "exists", lambda path: True), \
                mock.patch.object(actions, "_start", lambda command: order.append("run")), \
                mock.patch.object(actions.shutil, "which", lambda name: "C:\\" + name):
            actions.Doer().open("C:\\notes")
            actions.Doer().run("notepad")
        self.assertEqual(order, ["leave", "open", "leave", "run"])

    def test_elsewhere_there_is_nothing_to_do(self):
        with mock.patch.object(actions.config, "WINDOWS", False):
            self.assertFalse(actions.let_come_forward())
            self.assertEqual(actions.Doer().in_front(), "")

    def test_the_log_is_told_which_program_was_in_front_afterwards(self):
        engine = engine_with({"my notes": "open: ~/notes"})
        engine._doer.in_front = lambda: "explorer.exe"
        with mock.patch("dictation.engine.log") as logged, \
                mock.patch("dictation.engine.threading.Timer") as timer:
            engine.handle_text("my notes", True)
            self.assertEqual(timer.call_args[0][0], 1.5)
            timer.call_args[0][1]()                      # as when the moment has passed
        self.assertIn(mock.call('after a command\'s "open", in front: explorer.exe'), logged.call_args_list)


class Does:
    """Stands in for what reaches outside the program."""

    def __init__(self, fails=""):
        self.did, self.fails = [], fails

    def _do(self, kind, what):
        if kind == self.fails:
            raise actions.ActionError(f"The {kind} step couldn't be done.")
        self.did.append((kind, what))

    def press(self, chord):
        self._do("keys", chord)

    def open(self, what):
        self._do("open", what)

    def run(self, line):
        self._do("run", line)

    def wait(self, seconds):
        self._do("wait", seconds)


def engine_with(shortcuts: dict, **states):
    engine = bare(**states)
    engine.settings.shortcuts = dict(shortcuts)
    engine._doer = Does()
    engine._last_typed = None
    return engine


class SaidAloud(Quiet):
    MINE = {"new tab": "keys: ctrl+t", "save all": "keys: ctrl+k ctrl+s",
            "my notes": "open: ~/notes.txt", "build it": "run: make -C ~/project",
            "morning news": "open: https://example.org\nwait: 2\nkeys: ctrl+l",
            "shut down": "ask first\nrun: systemctl poweroff",
            "sign off": "Kind regards,"}

    def test_the_log_says_which_program_the_keys_went_to_and_never_what_was_written(self):
        engine = engine_with(self.MINE)
        engine._doer.press = lambda chord: "Notepad.exe"
        with mock.patch("dictation.engine.log") as logged:
            engine.handle_text("new tab", True)
        self.assertEqual(logged.call_args[0][0], "own command (keys): done, keys to Notepad.exe")

    def test_keys_are_pressed_and_nothing_is_typed(self):
        engine = engine_with(self.MINE)
        engine.handle_text("New tab.", True)
        engine.handle_text("save all", True)
        self.assertEqual(engine._doer.did, [("keys", "ctrl+t"), ("keys", "ctrl+k"),
                                            ("wait", actions.BETWEEN_KEYS), ("keys", "ctrl+s")])
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])
        self.assertEqual(engine.notices, [])           # pressing keys shows itself

    def test_steps_are_done_in_order(self):
        engine = engine_with(self.MINE)
        engine.handle_text("morning news", True)
        self.assertEqual(engine._doer.did, [("open", "https://example.org"), ("wait", 2.0),
                                            ("keys", "ctrl+l")])
        self.assertEqual(engine.notices, [("info", "Opened: https://example.org")])

    def test_running_a_program_is_off_until_it_is_switched_on(self):
        engine = engine_with(self.MINE)
        self.assertFalse(Settings().enabled("run_programs"))
        self.assertIn("run_programs", OPTIONS)         # a setting, not something to say
        engine.handle_text("build it", True)
        self.assertEqual(engine._doer.did, [])
        self.assertEqual(engine.notices[0][0], "problem")
        self.assertIn("Let my own commands run programs", engine.notices[0][1])
        engine.settings.states["run_programs"] = True
        engine.handle_text("build it", True)
        self.assertEqual(engine._doer.did, [("run", "make -C ~/project")])
        self.assertEqual(engine.notices[-1], ("info", "Ran: make -C ~/project"))

    def test_only_the_whole_phrase_is_a_command_and_never_asleep(self):
        engine = engine_with(self.MINE, run_programs=True)
        engine.handle_text("build it tomorrow", True)
        engine.handle_text("please build it now", True)
        self.assertEqual(engine._doer.did, [])
        self.assertEqual([op for op, _ in engine.targets.asked].count("insert"), 2)   # typed
        engine.status.state = State.ASLEEP
        engine.handle_text("build it", False)
        self.assertEqual(engine._doer.did, [])

    def test_a_step_that_fails_is_said_and_the_rest_is_left(self):
        engine = engine_with(self.MINE)
        engine._doer = Does(fails="wait")
        engine.handle_text("morning news", True)
        self.assertEqual(engine._doer.did, [("open", "https://example.org")])
        self.assertEqual(engine.notices[-1], ("problem", "The wait step couldn't be done."))
        self.assertIs(engine.status.state, State.AWAKE)

    def test_whatever_goes_wrong_the_listening_goes_on(self):
        engine = engine_with(self.MINE)
        engine._doer.press = mock.Mock(side_effect=RuntimeError("the desktop fell over"))
        engine.handle_text("new tab", True)
        self.assertEqual(engine.notices[-1][0], "problem")
        self.assertIs(engine.status.state, State.AWAKE)

    def test_a_shortcut_that_types_a_text_is_as_it_was(self):
        engine = engine_with(self.MINE)
        engine.handle_text("sign off", True)
        self.assertEqual(engine._doer.did, [])
        self.assertIn("insert", [op for op, _ in engine.targets.asked])

    def test_a_type_step_types(self):
        engine = engine_with({"new note": "keys: ctrl+n\ntype: Notes for today"})
        engine.handle_text("new note", True)
        self.assertEqual(engine._doer.did, [("keys", "ctrl+n")])
        self.assertIn("insert", [op for op, _ in engine.targets.asked])


class AskingFirst(Quiet):
    MINE = {"shut down": "ask first\nrun: systemctl poweroff"}

    def asked(self):
        engine = engine_with(self.MINE, run_programs=True)
        engine.handle_text("shut down", True)
        self.assertEqual(engine._doer.did, [])
        self.assertIn("Say \"yes\"", engine.notices[-1][1])
        return engine

    def test_yes_does_it(self):
        engine = self.asked()
        engine.handle_text("Yes.", True)
        self.assertEqual(engine._doer.did, [("run", "systemctl poweroff")])
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])   # "yes" isn't typed
        engine.handle_text("yes", True)                                       # once only
        self.assertEqual(len(engine._doer.did), 1)

    def test_no_leaves_it_and_is_not_typed(self):
        engine = self.asked()
        engine.handle_text("No.", True)
        engine.handle_text("yes", True)            # too late: it was left
        self.assertEqual(engine._doer.did, [])
        self.assertEqual([op for op, _ in engine.targets.asked].count("insert"), 1)   # only that "yes"
        self.assertIn("was left", engine.notices[-1][1])

    def test_anything_else_leaves_it_and_is_heard_as_usual(self):
        engine = self.asked()
        engine.handle_text("Yeah.", True)          # what a noise is written as: never a yes
        self.assertEqual(engine._doer.did, [])
        self.assertIn("insert", [op for op, _ in engine.targets.asked])
        engine.handle_text("yes", True)
        self.assertEqual(engine._doer.did, [])

    def test_yes_said_too_late_does_nothing(self):
        engine = self.asked()
        said, steps, until = engine._asked
        engine._asked = (said, steps, until - config.ASK_SECONDS - 1)
        engine.handle_text("yes", True)
        self.assertEqual(engine._doer.did, [])

    def test_with_running_switched_off_it_does_not_even_ask(self):
        engine = engine_with(self.MINE)
        engine.handle_text("shut down", True)
        self.assertIsNone(engine._asked)
        self.assertEqual(engine.notices[-1][0], "problem")


class CommandsOnly(Quiet):
    """Chosen in Settings, and never by anything that is said."""

    def only(self, shortcuts):
        engine = engine_with(shortcuts, commands_only=True)
        engine._apply_mode()
        return engine

    def test_it_is_a_setting_that_is_off_to_begin_with_and_is_kept(self):
        import tempfile
        self.assertIn("commands_only", [item.key for item in ITEMS])
        self.assertIn("commands_only", OPTIONS)
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        settings = Settings.load(path)
        self.assertFalse(settings.enabled("commands_only"))
        settings.set("commands_only", True)
        self.assertTrue(Settings.load(path).enabled("commands_only"))    # also after a restart

    def test_nothing_said_switches_it(self):
        for said in ("Command mode.", "switch to command mode", "commands only", "normal mode",
                     "switch to normal mode", "command mode off", "dictation mode"):
            self.assertNotIsInstance(interpret(said, True), Command, said)
        self.assertFalse(hasattr(commands, "MODE_COMMANDS"))
        engine = self.only({})
        engine.handle_text("normal mode", True)
        self.assertTrue(engine.status.commands_only)                      # still: only Settings can
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])
        typing = engine_with({})
        typing.handle_text("command mode", True)                          # only words, and typed
        self.assertFalse(typing.status.commands_only)
        self.assertIn("insert", [op for op, _ in typing.targets.asked])

    def test_nothing_is_typed_and_commands_are_still_acted_on(self):
        engine = self.only({"new tab": "keys: ctrl+t", "sign off": "Kind regards,"})
        self.assertTrue(engine.status.commands_only)
        engine.handle_text("This is not a command at all.", True)
        engine.handle_text("select the missing words", True)      # a command that finds nothing
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])
        self.assertIn("not typed", engine.status.last_heard)
        engine.handle_text("new tab", True)                        # the person's own
        engine.handle_text("select all", True)                     # and the program's
        engine.handle_text("sign off", True)                       # a shortcut is a command too
        self.assertEqual(engine._doer.did, [("keys", "ctrl+t")])
        self.assertIn(("move", ""), engine.targets.asked)          # "select all" went to the program
        self.assertEqual([op for op, _ in engine.targets.asked].count("insert"), 1)

    def test_waking_and_sleeping_are_as_always(self):
        engine = self.only({})
        engine.sleep = lambda: setattr(engine.status, "state", State.ASLEEP)
        engine.wake = lambda: setattr(engine.status, "state", State.AWAKE)
        engine.handle_text("go to sleep", True)
        self.assertIs(engine.status.state, State.ASLEEP)
        engine.handle_text("wake up", False)
        self.assertIs(engine.status.state, State.AWAKE)
        self.assertTrue(engine.status.commands_only)

    def test_what_was_no_command_is_said_once_not_with_every_phrase(self):
        engine = self.only({})
        for _ in range(4):
            engine.handle_text("just talking to somebody", True)
        self.assertEqual(len(engine.notices), 1)
        self.assertIn("\"Commands only\" is ticked in Settings", engine.notices[0][1])

    def test_unticked_in_settings_it_dictates_again_at_once(self):
        engine = self.only({})
        engine.apply_accessibility = engine._vscode_switch = lambda: None
        engine.settings.states["commands_only"] = False
        engine.setting_changed("commands_only")
        self.assertFalse(engine.status.commands_only)
        engine.handle_text("Now it is typed.", True)
        self.assertIn("insert", [op for op, _ in engine.targets.asked])
        engine.settings.states["commands_only"] = True
        engine.setting_changed("commands_only")
        self.assertTrue(engine.status.commands_only)

    def test_what_the_tray_says(self):
        status = Status(state=State.AWAKE, commands_only=True, target_known=True,
                        writer_ready=True, target="Writer")
        self.assertEqual(status.label(), "Awake, commands only")
        tip = status.tooltip()
        self.assertIn("Nothing is typed", tip)
        self.assertIn("untick \"Commands only\" in Settings", tip)
        self.assertIn("Commands go to Writer", tip)
        self.assertNotIn("Typing into", tip)
        self.assertEqual(Status(state=State.AWAKE).label(), "Awake")
        self.assertEqual(Status(state=State.OFF, commands_only=True).label(), "Off")
        self.assertIn("to give commands", Status(state=State.ASLEEP, commands_only=True).tooltip())


if __name__ == "__main__":
    unittest.main()

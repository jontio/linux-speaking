import os
import tempfile
import unittest

from dictation.commands import MOVES, Command, Dictation, interpret, last_words_length, move_steps
from dictation.formatting import PARAGRAPH, fit
from dictation.settings import ITEMS, Settings, available_models, model_label, without_effect


class Defaults(unittest.TestCase):
    def test_everything_on_except_period(self):
        s = Settings()
        off = [i.key for i in ITEMS if not s.enabled(i.key)]
        # The commands and settings that are off to begin with. (The spoken signs that are
        # off are in the list below this one.)
        self.assertEqual([key for key in off if not key.startswith("say:")],
                         ["aloud", "quick_listening", "second_opinions", "short_wake", "noise",
                          "enter", "keep_final", "other_apps", "click", "commands_only", "run_programs"])
        self.assertEqual([key for key in off if key.startswith("say:")],
                         ["say:period", "say:quote", "say:dash", "say:slash"])
        self.assertEqual(s.spoken_off(), ["dash", "end quote", "period", "quote", "slash", "unquote"])
        self.assertEqual(s.disabled_commands(), frozenset({"enter", "short_wake", "noise", "click"}))  # off until asked for

    def test_a_command_that_takes_words_says_so_in_its_name(self):
        labels = {i.key: i.label for i in ITEMS}
        for key, word in (("select", "Select"), ("correct", "Correct"), ("click", "Click")):
            self.assertTrue(labels[key].startswith(f'"{word}" and the words'), labels[key])
        # And "click" says whose words, in the line itself: nothing of it is put away in
        # its help, as what a long line says in brackets is.
        self.assertEqual(labels["click"],
                         '"Click" and the words on a button, link or menu in the window in front')

    def test_the_words_that_wake_it_and_send_it_to_sleep(self):
        s = Settings()
        self.assertEqual(s.wake_words(), ("wake up", "go to sleep"))
        self.assertIsNone(interpret("Wake.", False, s.disabled_commands()))
        s.states["short_wake"] = True
        self.assertEqual(s.wake_words(), ("wake", "sleep"))
        self.assertEqual(interpret("Wake.", False, s.disabled_commands()), Command("wake"))
        self.assertEqual(interpret("Sleep.", True, s.disabled_commands()), Command("sleep"))
        self.assertEqual(interpret("Wake up.", False, s.disabled_commands()), Command("wake"))

    def test_keys_are_unique(self):
        self.assertEqual(len({i.key for i in ITEMS}), len(ITEMS))


class SaveAndLoad(unittest.TestCase):
    def test_round_trip(self):
        path = os.path.join(tempfile.mkdtemp(), "sub", "settings.json")
        s = Settings.load(path)
        s.set("scratch", False)
        s.set("say:period", True)
        s.set("say:full stop", False)
        again = Settings.load(path)
        self.assertFalse(again.enabled("scratch"))
        self.assertEqual(again.disabled_commands(), frozenset({"scratch", "enter", "short_wake", "noise", "click"}))
        self.assertEqual(again.spoken_off(),   # with the signs that are off to begin with
                         ["dash", "end quote", "full stop", "quote", "slash", "unquote"])

    def test_bad_file_gives_defaults(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        with open(path, "w") as f:
            f.write("not json")
        self.assertTrue(Settings.load(path).enabled("scratch"))


class Models(unittest.TestCase):
    def test_lists_only_folders_with_a_model_smallest_first(self):
        folder = tempfile.mkdtemp()
        for name in ("en_fasterwhisper_small", "en_fasterwhisper_tiny", "en_fasterwhisper_distil_large3",
                     "multilang_fasterwhisper_large3", "en_fasterwhisper_distil_small", "notamodel"):
            os.makedirs(os.path.join(folder, name))
            if name != "notamodel":
                open(os.path.join(folder, name, "model.bin"), "w").close()
        names = [n for n, _ in available_models(folder)]
        self.assertEqual(names, ["en_fasterwhisper_tiny", "en_fasterwhisper_distil_small",
                                 "en_fasterwhisper_small", "en_fasterwhisper_distil_large3",
                                 "multilang_fasterwhisper_large3"])
        self.assertEqual(available_models("/no/such/folder"), [])

    def test_labels(self):
        self.assertTrue(model_label("small.en")[1].startswith("Small: "))
        self.assertIn("many languages", model_label("multilang_fasterwhisper_large3")[1])
        self.assertEqual(model_label("something-else")[1], "something-else")
        self.assertTrue(model_label("parakeet-tdt-0.6b-v2")[1].startswith("Parakeet v2: "))
        self.assertTrue(model_label("parakeet-unified-en-0.6b")[1].startswith("Parakeet Unified: "))

    def test_one_model_is_the_one_recommended(self):
        from dictation import settings
        said = [name for name in ("small.en", "base.en", "medium.en", "parakeet-tdt-0.6b-v2",
                                  "parakeet-unified-en-0.6b", "parakeet-unified-en-0.6b-full",
                                  "parakeet-unified-en-0.6b-mine-my-voice")
                if "recommended" in model_label(name)[1]]
        self.assertEqual(said, [settings.RECOMMENDED])
        self.assertEqual(model_label(settings.RECOMMENDED)[0],
                         model_label("parakeet-unified-en-0.6b-full")[0])   # they sort together

    def test_shortcuts_are_written_one_to_a_line(self):
        from dictation.settings import parse_shortcuts
        found, problems = parse_shortcuts(
            "My Address = 12 High Street\n    Dunedin 9016\n# a note\n\nbtw=by the way\n"
            "no sign here\n = nothing said\nempty =\npath = C:\\new\\table\n")
        self.assertEqual(found, {"my address": "12 High Street\nDunedin 9016", "btw": "by the way",
                                 "path": "C:\\new\\table"})   # a backslash is a backslash
        self.assertEqual(problems, ["no sign here", "= nothing said", "empty ="])
        self.assertEqual(parse_shortcuts("    carried on from nothing")[1], ["carried on from nothing"])
        s = Settings()
        self.assertEqual(s.set_shortcuts("my address = 12 High Street\n  Dunedin 9016\noops"), ["oops"])
        self.assertEqual(s.shortcuts_text(), "my address = 12 High Street\n    Dunedin 9016")
        self.assertEqual(parse_shortcuts(s.shortcuts_text())[0], s.shortcuts)
        self.assertIn("at full precision", model_label("parakeet-tdt-0.6b-v2-full")[1])
        self.assertIn("at full precision", model_label("parakeet-unified-en-0.6b-full")[1])
        self.assertNotIn("full precision", model_label("parakeet-unified-en-0.6b")[1])

    def test_choice_is_saved(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        s = Settings.load(path)
        self.assertEqual(s.model, "")
        s.set_model("base.en")
        s.set("scratch", False)
        again = Settings.load(path)
        self.assertEqual((again.model, again.enabled("scratch")), ("base.en", False))

    def test_the_look_is_saved_and_windows_own_is_the_usual_one(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        s = Settings.load(path)
        self.assertEqual(s.look, "")
        s.set_look("7")
        self.assertEqual(Settings.load(path).look, "7")
        s.set_look("")
        with open(path, encoding="utf-8") as f:
            self.assertNotIn("look", f.read())  # nothing is written for the usual one
        self.assertEqual(Settings.load(path).look, "")

    def test_a_setting_that_is_no_more_is_forgotten(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"states": {"xp_look": true, "scratch": false}, "model": ""}')
        s = Settings.load(path)
        self.assertEqual(s.states, {"scratch": False})


class Effects(unittest.TestCase):
    def test_disabled_command_is_typed(self):
        off = frozenset({"scratch", "select"})
        self.assertEqual(interpret("Scratch that.", True, off), Dictation("Scratch that."))
        self.assertEqual(interpret("Select the cat.", True, off), Dictation("Select the cat."))
        self.assertEqual(interpret("Bold that.", True, off), Command("bold"))

    def test_sleep_cannot_be_disabled(self):
        self.assertEqual(interpret("Go to sleep.", True, frozenset({"sleep"})), Command("sleep"))

    def test_new_commands(self):
        self.assertEqual(interpret("Press enter.", True), Command("press_enter"))
        self.assertEqual(interpret("Go to end of line.", True), Command("line_end"))
        self.assertEqual(interpret("Go to the top.", True), Command("doc_top"))
        self.assertEqual(interpret("Go to end of paragraph.", True), Command("para_end"))
        self.assertEqual(interpret("Go to the start of the paragraph.", True), Command("para_start"))

    def test_paragraph_moves_carry_on_to_the_next_paragraph(self):
        self.assertEqual(move_steps("para_end", "some text", " more"), MOVES["para_end"])
        self.assertEqual(move_steps("para_end", "some text", "")[0][1], "gotoNextParagraph")
        self.assertEqual(move_steps("para_start", "x", "rest"), MOVES["para_start"])
        self.assertEqual(move_steps("para_start", "", "rest")[0][1], "gotoPreviousParagraph")
        self.assertEqual(move_steps("line_end", "", ""), MOVES["line_end"])

    def test_redo_that_and_how_it_gets_written(self):
        for heard in ("Redo that.", "Redo.", "Redo it.", "Re-do that.", "OK, redo that, please."):
            self.assertEqual(interpret(heard, True), Command("redo"), heard)
        # In a sentence it is only words, and so it is with its own option unticked.
        for heard in ("I will redo that section.", "Redo the", "Redo that section."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertEqual(interpret("Redo that.", True, frozenset({"redo"})), Dictation("Redo that."))
        self.assertEqual(interpret("Undo that.", True, frozenset({"redo"})), Command("undo"))

    def test_redo_that_has_a_line_of_its_own_under_editing_after_undo_that(self):
        from dictation.settings import HELP
        keys = [item.key for item in ITEMS if item.group == "Editing"]
        self.assertEqual(keys.index("redo"), keys.index("undo") + 1)
        item = next(item for item in ITEMS if item.key == "redo")
        self.assertEqual((item.label, item.default), ('"Redo that"', True))
        self.assertIn("Redo", HELP["redo"])

    def test_undo_that_and_how_it_gets_misheard(self):
        for heard in ("Undo that.", "Undo.", "Undue that.", "On do that."):
            self.assertEqual(interpret(heard, True), Command("undo"), heard)
        # People do say this one, so it is words.
        self.assertEqual(interpret("And do that.", True), Dictation("And do that."))

    def test_spell_that(self):
        self.assertEqual(interpret("Spell that.", True), Command("spell"))
        self.assertEqual(interpret("Spell that.", True, frozenset({"spell"})), Dictation("Spell that."))

    def test_move_by_words(self):
        self.assertEqual(interpret("Move left three words.", True), Command("word_left", "3"))
        self.assertEqual(interpret("Move right 2 words", True), Command("word_right", "2"))
        self.assertEqual(interpret("Move left a word.", True), Command("word_left", "1"))
        self.assertEqual(interpret("Move back one word.", True), Command("word_left", "1"))
        self.assertEqual(interpret("Go forward four words.", True), Command("word_right", "4"))
        self.assertEqual(interpret("Move right word", True), Command("word_right", "1"))
        self.assertEqual(interpret("Move left three words quickly", True),
                         Dictation("Move left three words quickly"))
        self.assertEqual(interpret("Move left 3 words.", True, frozenset({"word_left"})),
                         Dictation("Move left 3 words."))
        self.assertEqual(move_steps("word_left", "x", "x", 3), [["text", "gotoPreviousWord", False]] * 3)
        self.assertEqual(move_steps("word_right", "x", "x", 1), [["text", "gotoNextWord", False]])

    def test_line_commands(self):
        self.assertEqual(interpret("Up one line.", True), Command("line_up", "1"))
        self.assertEqual(interpret("Down 3 lines", True), Command("line_down", "3"))
        self.assertEqual(interpret("Go up two lines.", True), Command("line_up", "2"))
        self.assertEqual(interpret("Move down a line", True), Command("line_down", "1"))
        self.assertEqual(interpret("Delete line.", True), Command("delete_line", "1"))
        self.assertEqual(interpret("Delete this line", True), Command("delete_line", "1"))
        self.assertEqual(interpret("Delete three lines", True), Command("delete_line", "3"))
        self.assertEqual(interpret("Select line.", True), Command("select_line"))
        self.assertEqual(interpret("Go to line 42.", True), Command("go_to_line", "42"))
        self.assertEqual(interpret("Go to line seven", True), Command("go_to_line", "7"))
        self.assertEqual(interpret("Indent.", True), Command("indent"))
        self.assertEqual(interpret("Comment line", True), Command("comment_line"))
        self.assertEqual(interpret("Duplicate line", True), Command("duplicate_line"))
        self.assertEqual(interpret("Delete line.", True, frozenset({"delete_line"})), Dictation("Delete line."))
        self.assertEqual(interpret("up the line of battle", True), Dictation("up the line of battle"))
        self.assertEqual(move_steps("line_up", "x", "x", 3), [["view", "goUp", 3, False]])
        self.assertEqual(move_steps("delete_line", "x", "x")[1], ["view", "gotoEndOfLine", True])

    def test_move_to_is_go_to(self):
        self.assertEqual(interpret("Move to end of line.", True), Command("line_end"))
        self.assertEqual(interpret("Move to the start of the line", True), Command("line_start"))
        self.assertEqual(interpret("Move to start of paragraph", True), Command("para_start"))
        self.assertEqual(interpret("Jump to top", True), Command("doc_top"))
        self.assertEqual(interpret("Move to line 12", True), Command("go_to_line", "12"))
        self.assertEqual(interpret("Move to the shops", True), Dictation("Move to the shops"))

    def test_tab(self):
        self.assertEqual(interpret("Tab.", True), Command("tab"))
        self.assertEqual(interpret("Press tab", True), Command("tab"))
        self.assertEqual(interpret("Shift tab", True), Command("outdent"))
        self.assertEqual(interpret("Tab.", True, frozenset({"tab"})), Dictation("Tab."))
        self.assertEqual(interpret("the tab is open", True), Dictation("the tab is open"))

    def test_select_all(self):
        self.assertEqual(interpret("Select all.", True), Command("select_all"))
        self.assertEqual(interpret("Select everything", True), Command("select_all"))
        self.assertEqual(interpret("Select all the cats", True), Command("select", "all the cats"))
        self.assertEqual(interpret("Select all.", True, frozenset({"select_all"})), Dictation("Select all."))
        self.assertEqual(move_steps("select_all", "x", "x"),
                         [["view", "gotoStart", False], ["view", "gotoEnd", True]])

    def test_backspace(self):
        self.assertEqual(interpret("Backspace.", True), Command("backspace", "1"))
        self.assertEqual(interpret("Back space.", True), Command("backspace", "1"))
        self.assertEqual(interpret("Backspace 3.", True), Command("backspace", "3"))
        self.assertEqual(interpret("Backspace three times.", True), Command("backspace", "3"))
        self.assertEqual(interpret("Backspace two.", True), Command("backspace", "2"))
        self.assertEqual(interpret("Backspace key", True), Dictation("Backspace key"))
        self.assertEqual(
            interpret("Backspace.", True, frozenset({"backspace"})), Dictation("Backspace.")
        )

    def test_delete_last_word(self):
        self.assertEqual(interpret("Delete last word.", True), Command("delete_words", "1"))
        self.assertEqual(interpret("Delete the last word", True), Command("delete_words", "1"))
        self.assertEqual(interpret("Delete last three words.", True), Command("delete_words", "3"))
        self.assertEqual(interpret("Delete previous 2 words", True), Command("delete_words", "2"))
        self.assertEqual(
            interpret("Delete last word.", True, frozenset({"delete_words"})),
            Dictation("Delete last word."),
        )

    def test_last_words_length(self):
        def after(before, n):
            return before[: len(before) - last_words_length(before, n)]
        self.assertEqual(after("Hello big world", 1), "Hello big")
        self.assertEqual(after("Hello big world. ", 1), "Hello big")
        self.assertEqual(after("Hello big world", 2), "Hello")
        self.assertEqual(after("Hello big world", 9), "")
        self.assertEqual(after("I don\u2019t know", 2), "I")
        self.assertEqual(after("well-known fact", 2), "")
        self.assertEqual(last_words_length("", 1), 0)
        self.assertEqual(last_words_length(" ... ", 1), 0)

    def test_last_words_length_is_fast_on_long_paragraphs(self):
        import time
        before = "word, and another; " * 2000
        started = time.time()
        self.assertGreater(last_words_length(before, 20), 0)
        self.assertLess(time.time() - started, 0.5)

    def test_period_is_a_word_by_default(self):
        self.assertEqual(fit("for a period of time", "", "").text, "For a period of time")

    def test_period_when_switched_on(self):
        self.assertEqual(fit("the end period", "", "", spoken_off=()).text, "The end.")

    def test_full_stop_switched_off(self):
        self.assertEqual(
            fit("come to a full stop", "", "", spoken_off=["full stop"]).text,
            "Come to a full stop",
        )

    def test_new_paragraph_switched_off_inline(self):
        self.assertNotIn(PARAGRAPH, fit("a new paragraph here", "", "", spoken_off=["new paragraph"]).text)


if __name__ == "__main__":
    unittest.main()


class SettingsThatWouldDoNothing(unittest.TestCase):
    """For Settings to grey out: the few that are about the listening itself."""

    def models(self, *names):
        folder = tempfile.mkdtemp()
        for name in names:
            os.makedirs(os.path.join(folder, name))
            if "parakeet" in name:
                for part in ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"):
                    open(os.path.join(folder, name, part), "w").close()
            else:
                open(os.path.join(folder, name, "model.bin"), "w").close()
        return folder

    OFF = {"on": False, "model": ""}

    def test_everything_installed_and_a_parakeet_in_use_nothing_is_greyed(self):
        folder = self.models("small.en", "medium.en", "parakeet-unified-en-0.6b")
        self.assertEqual(without_effect("parakeet-unified-en-0.6b", self.OFF, folder), {})

    def test_leaving_out_noises_is_for_parakeet_here_or_on_the_other_computer(self):
        folder = self.models("small.en", "medium.en", "parakeet-tdt-0.6b-v2")
        self.assertIn("speech_only", without_effect("small.en", self.OFF, folder))
        self.assertNotIn("speech_only", without_effect("parakeet-tdt-0.6b-v2", self.OFF, folder))
        there = {"on": True, "model": "parakeet-unified-en-0.6b-mine-my-voice"}
        self.assertNotIn("speech_only", without_effect("small.en", there, folder))
        self.assertIn("speech_only", without_effect("small.en", {"on": True, "model": "medium.en"}, folder))
        self.assertIn("speech_only", without_effect("small.en", dict(there, on=False), folder))

    def test_second_opinions_want_two_others_installed(self):
        folder = self.models("small.en", "parakeet-unified-en-0.6b")
        why = without_effect("parakeet-unified-en-0.6b", self.OFF, folder)["second_opinions"]
        self.assertIn("Not installed: medium.en", why)
        # Small is in use, so Medium and Parakeet are the two asked: both are wanted.
        folder = self.models("small.en", "medium.en")
        self.assertIn("parakeet-tdt-0.6b-v2", without_effect("small.en", self.OFF, folder)["second_opinions"])
        folder = self.models("small.en", "medium.en", "parakeet-tdt-0.6b-v2")
        self.assertNotIn("second_opinions", without_effect("small.en", self.OFF, folder))

    def test_with_another_computer_listening_the_opinions_are_its_affair(self):
        folder = self.models("parakeet-unified-en-0.6b")
        there = {"on": True, "model": "parakeet-unified-en-0.6b"}
        self.assertNotIn("second_opinions", without_effect("parakeet-unified-en-0.6b", there, folder))

    def test_nothing_else_is_ever_greyed(self):
        folder = self.models()
        self.assertLessEqual(set(without_effect("base.en", self.OFF, folder)),
                             {"speech_only", "second_opinions"})

    def test_there_is_no_setting_for_which_model_hears_wake_up(self):
        # One rule, and so nothing to tick: the model that is chosen does the waking.
        from dictation.settings import ITEMS, OPTIONS
        self.assertNotIn("wake_same", [item.key for item in ITEMS])
        self.assertNotIn("wake_same", OPTIONS)


class TheFileItself(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "settings.json")

    def test_a_save_leaves_nothing_half_written_behind(self):
        settings = Settings.load(self.path)
        settings.model = "medium.en"
        settings.save()
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["settings.json"])
        self.assertEqual(Settings.load(self.path).model, "medium.en")

    @unittest.skipIf(os.name == "nt", "Windows keeps its own account of who may read a file")
    def test_only_its_owner_may_read_it(self):
        Settings.load(self.path).save()
        self.assertEqual(os.stat(self.path).st_mode & 0o077, 0)
        os.chmod(self.path, 0o664)                    # as one saved by an earlier version is
        Settings.load(self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o077, 0)

    def test_a_file_with_the_wrong_things_in_it_gives_the_usual_settings(self):
        for damaged in ('{"states": null}', '{"states": [1, 2]}', '{"model": "med', "[]", ""):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(damaged)
            settings = Settings.load(self.path)
            self.assertTrue(settings.enabled("scratch"), damaged)

    def saved(self) -> dict:
        import json
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def write(self, saved) -> None:
        import json
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(saved if isinstance(saved, str) else json.dumps(saved))

    def test_two_saves_at_once_both_go_through(self):
        import threading
        settings, failed = Settings.load(self.path), []

        def many(mark):                   # as the engine's worker saves, and a window's buttons
            for n in range(300):
                try:
                    settings.set_model(f"{mark}{n}")
                except Exception as e:
                    failed.append(e)

        both = [threading.Thread(target=many, args=(mark,)) for mark in "ab"]
        for one in both:
            one.start()
        for one in both:
            one.join()
        self.assertEqual(failed, [])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["settings.json"])
        self.assertIn(self.saved()["model"], ("a299", "b299"))

    def test_each_save_writes_beside_the_file_under_a_name_of_its_own(self):
        import threading
        from unittest import mock
        settings, real, beside = Settings.load(self.path), os.replace, []

        def replace(source, target):
            beside.append(source)
            return real(source, target)

        with mock.patch("os.replace", replace):
            settings.save()
            other = threading.Thread(target=settings.save)   # another thread: as another program would be
            other.start()
            other.join()
        self.assertEqual(len(set(beside)), 2)
        self.assertTrue(all(os.path.dirname(name) == os.path.dirname(self.path) for name in beside))

    def test_a_save_that_fails_leaves_the_settings_there_were_and_nothing_beside_them(self):
        from unittest import mock
        settings = Settings.load(self.path)
        settings.set_model("small.en")
        settings.model = "medium.en"
        with mock.patch("os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                settings.save()
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["settings.json"])
        self.assertEqual(Settings.load(self.path).model, "small.en")

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "links are made another way there")
    def test_a_settings_file_that_is_a_link_stays_one_and_the_file_it_leads_to_is_written(self):
        kept = os.path.join(tempfile.mkdtemp(), "kept", "settings.json")   # with the person's other settings
        os.makedirs(os.path.dirname(kept))
        self.path, link = kept, self.path
        self.write({"states": {"scratch": False}, "model": "small.en"})
        os.symlink(kept, link)
        settings = Settings.load(link)
        self.assertFalse(settings.enabled("scratch"))
        settings.set_model("medium.en")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self.saved()["model"], "medium.en")
        self.assertEqual(os.stat(kept).st_mode & 0o077, 0)
        self.assertEqual(os.listdir(os.path.dirname(link)), ["settings.json"])
        self.assertEqual(os.listdir(os.path.dirname(kept)), ["settings.json"])
        self.assertEqual(Settings.load(link).model, "medium.en")
        # A link to a file that isn't there yet: the file is made where the link leads.
        os.remove(kept)
        os.rmdir(os.path.dirname(kept))
        first = Settings.load(link)
        self.assertTrue(first.first_time)
        first.set_model("base.en")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self.saved()["model"], "base.en")

    def test_a_first_time_is_when_there_was_no_file_at_all(self):
        self.assertFalse(Settings().first_time)
        first = Settings.load(self.path)
        self.assertTrue(first.first_time)
        self.assertEqual((first.hotkey, first.shortcuts), ("", {}))
        first.save()
        self.assertFalse(Settings.load(self.path).first_time)
        for damaged in ("", "not json", "[]", '{"states": 7'):       # there, though it can't be made out
            self.write(damaged)
            again = Settings.load(self.path)
            self.assertFalse(again.first_time, damaged)
            self.assertEqual((again.hotkey, again.shortcuts), ("", {}), damaged)

    def test_the_key_that_switches_dictation_on_and_off_is_always_saved(self):
        settings = Settings.load(self.path)
        settings.save()
        self.assertEqual(self.saved()["hotkey"], "")                 # even when there is none
        settings.hotkey = "Pause"
        settings.save()
        self.assertEqual(self.saved()["hotkey"], "Pause")
        self.assertEqual(Settings.load(self.path).hotkey, "Pause")
        self.assertEqual(Settings(hotkey="F9").hotkey, "F9")
        for odd in (None, 7, ["Pause"], {"a": 1}, True):
            self.write({"states": {}, "hotkey": odd})
            self.assertEqual(Settings.load(self.path).hotkey, "", odd)

    def test_a_file_from_before_there_was_a_choice_of_key_has_the_one_there_always_was(self):
        for states, key in (({}, "Number pad +"), ({"numpad_plus": True}, "Number pad +"),
                            ({"numpad_plus": False}, ""), ({"scratch": False}, "Number pad +")):
            self.write({"states": states, "model": ""})
            settings = Settings.load(self.path)
            self.assertEqual(settings.hotkey, key, states)
            self.assertNotIn("numpad_plus", settings.states)         # that tick box is no more
        # And only the once: with the key switched off and saved, it stays off.
        self.write({"states": {}, "model": ""})
        settings = Settings.load(self.path)
        settings.hotkey = ""
        settings.save()
        self.assertEqual(Settings.load(self.path).hotkey, "")
        self.write({"states": {"numpad_plus": False}, "hotkey": "Pause"})   # the key named is the key
        self.assertEqual(Settings.load(self.path).hotkey, "Pause")
        self.write({"states": [1], "model": ""})                     # no states to say otherwise
        self.assertEqual(Settings.load(self.path).hotkey, "Number pad +")

    def test_shortcuts_are_saved_when_there_are_any_and_only_text_is_read_back(self):
        settings = Settings.load(self.path)
        settings.save()
        self.assertNotIn("shortcuts", self.saved())
        settings.shortcuts = {"my address": "1 Long Road\nSmall Town", "sig": "Best wishes"}
        settings.save()
        self.assertEqual(self.saved()["shortcuts"], settings.shortcuts)
        self.assertEqual(Settings.load(self.path).shortcuts, settings.shortcuts)
        given = {"a": "b"}
        made = Settings(shortcuts=given)
        made.shortcuts["c"] = "d"
        self.assertEqual(given, {"a": "b"})                          # its own, not the one handed in
        self.write({"states": {}, "shortcuts": {"kept": "this", "number": 7, "list": ["x"], "none": None,
                                                "nested": {"a": "b"}}})
        self.assertEqual(Settings.load(self.path).shortcuts, {"kept": "this"})
        for odd in ("text", [["a", "b"]], 7, None):
            self.write({"states": {}, "shortcuts": odd})
            self.assertEqual(Settings.load(self.path).shortcuts, {}, odd)


class WhatEachIsFor(unittest.TestCase):
    """Every tick box says, when the mouse rests on it, what it is for."""

    def test_none_is_left_without_a_word_about_it(self):
        from dictation.settings import HELP, help_for
        for item in ITEMS:
            about = help_for(item.key)
            self.assertGreater(len(about), 20, item.key)
            self.assertTrue(about.endswith((".", ")")), item.key)
        self.assertEqual(sorted(set(HELP) - {item.key for item in ITEMS}), [])  # and none for nothing

    def test_a_line_is_never_so_long_that_it_sets_the_width_of_the_window(self):
        for item in ITEMS:
            self.assertLessEqual(len(item.label), 115, item.key)


class SaidOrSet(unittest.TestCase):
    """In Settings, what you say is in quotes, and a setting is not."""

    def test_every_command_and_punctuation_word_starts_with_what_you_say_in_quotes(self):
        from dictation.settings import OPTIONS
        for item in ITEMS:
            if item.key in OPTIONS:
                self.assertFalse(item.label.startswith('"'), item.key)
            else:
                self.assertTrue(item.label.startswith('"'), item.key)
                said = item.label.split("  ")[0]
                self.assertEqual(said.count('"') % 2, 0, item.key)   # every quote is closed

import os
import tempfile
import unittest

from dictation.commands import MOVES, Command, Dictation, interpret, last_words_length, move_steps
from dictation.formatting import PARAGRAPH, fit
from dictation.settings import ITEMS, Settings, available_models, model_label


class Defaults(unittest.TestCase):
    def test_everything_on_except_period(self):
        s = Settings()
        self.assertEqual([i.key for i in ITEMS if not s.enabled(i.key)], ["other_apps", "say:period"])
        self.assertEqual(s.spoken_off(), ["period"])
        self.assertEqual(s.disabled_commands(), frozenset())

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
        self.assertEqual(again.disabled_commands(), frozenset({"scratch"}))
        self.assertEqual(again.spoken_off(), ["full stop"])

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
        self.assertTrue(model_label("small.en")[1].startswith("Small: recommended"))
        self.assertIn("many languages", model_label("multilang_fasterwhisper_large3")[1])
        self.assertEqual(model_label("something-else")[1], "something-else")

    def test_choice_is_saved(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        s = Settings.load(path)
        self.assertEqual(s.model, "")
        s.set_model("base.en")
        s.set("scratch", False)
        again = Settings.load(path)
        self.assertEqual((again.model, again.enabled("scratch")), ("base.en", False))


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

    def test_undo_that_and_how_it_gets_misheard(self):
        for heard in ("Undo that.", "Undo.", "Undue that.", "And do that."):
            self.assertEqual(interpret(heard, True), Command("undo"), heard)

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

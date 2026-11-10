import os
import tempfile
import unittest

from dictation.commands import MOVES, Command, Dictation, interpret, last_words_length, move_steps
from dictation.formatting import PARAGRAPH, fit
from dictation.settings import ITEMS, Settings, available_models, model_label


class Defaults(unittest.TestCase):
    def test_everything_on_except_period(self):
        s = Settings()
        self.assertEqual([i.key for i in ITEMS if not s.enabled(i.key)], ["say:period"])
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

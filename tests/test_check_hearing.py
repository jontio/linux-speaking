"""The check of the hearing with one's own voice: its counting, which needs no microphone."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("check_hearing", os.path.join(HERE, "scripts", "check_hearing.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Hears:
    """Stands in for the models: each way of hearing writes what it is told to."""

    def __init__(self, **wrote):
        self.wrote = wrote

    def ways(self):
        return {name: (lambda sound, text=text: text) for name, text in self.wrote.items()}

    letters = signs = waking = ways


class Counting(unittest.TestCase):
    def test_letters_are_judged_as_the_spelling_box_would_take_them(self):
        self.assertEqual(check.spelled("J, O, N."), "jon")
        self.assertEqual(check.spelled("Capital J."), "J")
        self.assertEqual(check.spelled("B as in Bravo."), "b")
        self.assertEqual(check.spelled(""), "")

    def test_every_way_is_asked_about_everything_and_judged_for_what_it_is(self):
        todo = check.plan(Hears(one="J.", two="Wake up."))
        self.assertEqual(len(todo), len(check.LETTERS) + len(check.SIGNS) + len(check.WAKING))
        part, said, judge, ways = todo[0]
        self.assertEqual((said, sorted(ways)), ("J", ["one", "two"]))
        self.assertTrue(judge("J."))
        self.assertFalse(judge("Yay."))
        signs = [item for item in todo if item[1] == "question mark"][0]
        self.assertTrue(signs[2]("Question mark."))
        self.assertFalse(signs[2]("?"))
        wake = [item for item in todo if item[1] == "wake up"][0]
        other = [item for item in todo if item[1] == "make up"][0]
        self.assertTrue(wake[2]("Wake up."))
        self.assertFalse(wake[2]("Make up."))       # it was said and not heard
        self.assertTrue(other[2]("Make up."))       # this one is right not to wake
        self.assertFalse(other[2]("Wake up."))      # ... and wrong to

    def test_the_table_counts_each_way_and_lists_what_it_got_wrong(self):
        todo = check.plan(Hears(small="J.", parakeet=""))
        results = {0: {"small": ("J.", True, 1.0), "parakeet": ("", False, 0.1)},
                   1: {"small": ("Oh.", True, 1.2), "parakeet": ("O.", True, 0.1)}}
        table = check.report(todo, results)
        self.assertIn("Letters, for the spelling box  (2 said)", table)
        self.assertIn("2 of 2 right, 1.10 s each: small", table)
        self.assertIn("1 of 2 right, 0.10 s each: parakeet", table)
        self.assertIn('you said "J": it wrote ""', table)
        self.assertNotIn("Punctuation", table)       # nothing of it was said
        self.assertIn("Nothing was said.", check.report(todo, {}))

    def test_with_nothing_to_compare_there_is_nothing_to_ask(self):
        self.assertEqual(check.plan(Hears()), [])


if __name__ == "__main__":
    unittest.main()

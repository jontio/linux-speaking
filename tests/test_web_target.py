"""Linux: text boxes read through the accessibility interface and typed into. The parts
that need no desktop."""
import unittest

from dictation.portal_keys import KEYSYMS, keysym, typable

OBJECT = "\ufffc"


from dictation.web_target import without_decoration


class Decoration(unittest.TestCase):
    """A hint drawn in an empty box is a thing inside the box, standing in its text as
    one character. It isn't text, and the cursor isn't after anything."""

    def test_an_empty_box_with_a_hint(self):
        self.assertEqual(without_decoration(OBJECT, 1, 1, [0]), ("", 0, 0))

    def test_typed_text_is_left_alone(self):
        self.assertEqual(without_decoration("Hello world", 5, 5, []), ("Hello world", 5, 5))
        self.assertEqual(without_decoration("one\ntwo", 7, 7, []), ("one\ntwo", 7, 7))

    def test_a_real_thing_in_the_text_stays(self):
        # A picture or a name tag someone put in is not decoration.
        text = "see " + OBJECT + " here"
        self.assertEqual(without_decoration(text, 6, 6, []), (text, 6, 6))

    def test_decoration_before_and_after_text_with_a_selection(self):
        text = OBJECT + "say hello" + OBJECT
        self.assertEqual(without_decoration(text, 5, 10, [0, 10]), ("say hello", 4, 9))

    def test_places_that_make_no_sense(self):
        self.assertEqual(without_decoration("abc", 9, 2, [7]), ("abc", 3, 3))


class Keys(unittest.TestCase):
    def test_a_character_and_its_key(self):
        self.assertEqual(keysym("a"), 0x61)
        self.assertEqual(keysym("A"), 0x41)
        self.assertEqual(keysym("?"), 0x3F)
        self.assertEqual(keysym("\n"), KEYSYMS["enter"])
        self.assertEqual(keysym("\t"), KEYSYMS["tab"])
        self.assertEqual(keysym("\u00e9"), 0xE9)
        self.assertEqual(keysym("\u2014"), 0x01002014)

    def test_what_the_keyboard_has_not_got_is_made_plain(self):
        self.assertEqual(typable("caf\u00e9 \u2014 na\u00efve"), "cafe - naive")
        self.assertEqual(typable("\u201cquoted\u201d and it\u2019s\u2026"), '"quoted" and it\'s...')
        self.assertEqual(typable("plain text, 100% (ok)?\nnext\tline"), "plain text, 100% (ok)?\nnext\tline")
        self.assertEqual(typable("price \u20ac5 \u00a35"), "price 5 5")   # no key, and nothing near: left out
        self.assertEqual(typable(""), "")


class TypedBack(unittest.TestCase):
    """What "scratch that" would type back has to be what the keyboard can type."""

    def test_only_words_that_would_be_the_same_typed_again(self):
        from dictation.web_target import WebBoxTarget
        target = WebBoxTarget.__new__(WebBoxTarget)
        self.assertTrue(target._types_back("plain words, 100% (ok)?"))
        self.assertFalse(target._types_back("caf\u00e9"))
        self.assertFalse(target._types_back("a \u2014 b"))
        self.assertFalse(target._types_back("one\ntwo"))
        self.assertFalse(target._types_back("see " + OBJECT + " here"))
        self.assertFalse(target._types_back(""))


if __name__ == "__main__":
    unittest.main()

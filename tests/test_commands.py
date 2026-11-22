import unittest

from dictation.commands import Command, Dictation, choice, interpret, normalise


class Asleep(unittest.TestCase):
    def test_wakes_on_wake_up(self):
        self.assertEqual(interpret("Wake up.", awake=False), Command("wake"))
        self.assertEqual(interpret("Wake-up!", awake=False), Command("wake"))

    def test_wakes_on_near_misses(self):
        for heard in ("Wake cup.", "Wakeup", "Wake up, wake up.", "Wake up up", "Awake up."):
            self.assertEqual(interpret(heard, awake=False), Command("wake"), heard)

    def test_ignores_everything_else(self):
        for heard in ("We go up", "Thank you.", "Up", "What's up?", "Wake up the kids now"):
            self.assertIsNone(interpret(heard, awake=False), heard)
        self.assertIsNone(interpret("Hello there", awake=False))
        self.assertIsNone(interpret("Go to sleep.", awake=False))
        self.assertIsNone(interpret("Wake up the kids", awake=False))


class ShortWords(unittest.TestCase):
    """ "Wake" and "sleep" by themselves, for "wake up" and "go to sleep": a setting."""
    OFF = frozenset({"short_wake"})  # how it starts: the setting is not ticked

    def test_off_a_lone_wake_is_ignored_and_a_lone_sleep_is_typed(self):
        self.assertIsNone(interpret("Wake.", False, self.OFF))
        self.assertEqual(interpret("Sleep.", True, self.OFF), Dictation("Sleep."))
        self.assertEqual(interpret("Wake.", True, self.OFF), Dictation("Wake."))

    def test_on_the_one_word_does_it(self):
        for heard in ("Wake.", "wake", "Wake!", "Wake, wake."):
            self.assertEqual(interpret(heard, False), Command("wake"), heard)
        self.assertEqual(interpret("Sleep.", True), Command("sleep"))
        self.assertEqual(interpret("Wake.", True), Command("wake"))  # not typed, awake already

    def test_the_longer_phrases_work_either_way(self):
        for off in (frozenset(), self.OFF):
            self.assertEqual(interpret("Wake up.", False, off), Command("wake"))
            self.assertEqual(interpret("Go to sleep.", True, off), Command("sleep"))

    def test_only_those_words_exactly(self):
        for heard in ("Wait.", "Week.", "Weak.", "Awake.", "Make.", "Woke.", "Wakes.", "Sleep."):
            self.assertIsNone(interpret(heard, False), heard)  # asleep, "sleep" is nothing
        for heard in ("Slip.", "Asleep.", "Sleet.", "Sleeps."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)

    def test_in_a_sentence_they_are_dictation(self):
        self.assertIsNone(interpret("Wake the kids", False))
        for heard in ("Sleep well.", "I need more sleep", "Wake me at six"):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)

    def test_sleep_can_not_be_switched_off_by_another_setting(self):
        self.assertEqual(interpret("Sleep.", True, frozenset({"sleep"})), Command("sleep"))


class Awake(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(interpret("Go to sleep.", awake=True), Command("sleep"))
        self.assertEqual(interpret("Scratch that!", awake=True), Command("scratch"))
        self.assertEqual(interpret("New paragraph.", awake=True), Command("new_paragraph"))
        self.assertEqual(interpret("Bold that.", awake=True), Command("bold"))

    def test_select(self):
        self.assertEqual(
            interpret("Select the black cat.", awake=True), Command("select", "the black cat")
        )
        self.assertEqual(interpret("Select that.", awake=True), Command("select_last"))
        self.assertEqual(interpret("Correct that.", awake=True), Command("select_last"))
        self.assertIsInstance(interpret("correct that", True, frozenset({"select_last"})), Dictation)

    def test_correct(self):
        # As "select", for the engine; the program typed into puts the cursor back after.
        self.assertEqual(
            interpret("Correct the black cat.", awake=True), Command("correct", "the black cat")
        )
        self.assertEqual(interpret("Correct that mistake", awake=True),
                         Command("correct", "that mistake"))
        self.assertEqual(interpret("Correct.", awake=True), Dictation("Correct."))
        self.assertIsInstance(interpret("Correct the cat", True, frozenset({"correct"})), Dictation)
        self.assertEqual(interpret("Select the cat", True, frozenset({"correct"})),
                         Command("select", "the cat"))
        self.assertIsNone(interpret("Correct the cat", awake=False))

    def test_dictation(self):
        self.assertEqual(interpret("The cat sat.", awake=True), Dictation("The cat sat."))
        self.assertEqual(interpret("Select.", awake=True), Dictation("Select."))

    def test_silence(self):
        self.assertIsNone(interpret(" ... ", awake=True))

    def test_normalise(self):
        self.assertEqual(normalise("  Don’t   stop-now! "), "don't stop now")


class Choosing(unittest.TestCase):
    def test_numbers(self):
        for heard, n in (("2.", 2), ("Two.", 2), ("Choose 3", 3), ("Number one.", 1),
                         ("Too.", 2), ("Pick four", 4)):
            self.assertEqual(choice(heard, 5), n, heard)

    def test_out_of_range_or_not_a_number(self):
        self.assertIsNone(choice("Six.", 5))
        self.assertIsNone(choice("The cat sat.", 5))
        self.assertIsNone(choice("Choose wisely", 5))


class Enter(unittest.TestCase):
    OFF = frozenset({"enter"})  # how it starts: the setting is not ticked

    def test_press_enter_always_was_a_command(self):
        self.assertEqual(interpret("Press enter.", True, self.OFF), Command("press_enter"))

    def test_the_one_word_is_typed_until_it_is_switched_on(self):
        self.assertIsInstance(interpret("Enter.", True, self.OFF), Dictation)
        self.assertEqual(interpret("Enter.", True), Command("enter"))

    def test_in_a_sentence_it_is_a_word(self):
        self.assertIsInstance(interpret("Enter the building", True), Dictation)

    def test_it_can_be_on_with_press_enter_off(self):
        self.assertEqual(interpret("enter", True, frozenset({"press_enter"})), Command("enter"))
        self.assertIsInstance(interpret("press enter", True, frozenset({"press_enter"})), Dictation)


class Space(unittest.TestCase):
    def test_said_by_itself(self):
        for said in ("Space.", "space bar", "Spacebar", "Press space"):
            self.assertEqual(interpret(said, True), Command("space", "1"), said)

    def test_with_a_count(self):
        self.assertEqual(interpret("space 3", True), Command("space", "3"))
        self.assertEqual(interpret("Space three times.", True), Command("space", "3"))
        self.assertEqual(interpret("space 99", True), Command("space", "20"))  # no more than that

    def test_in_a_sentence_it_is_a_word(self):
        for said in ("Space station", "We need more space", "Space for everyone", "space to", "space bar bar"):
            self.assertIsInstance(interpret(said, True), Dictation, said)

    def test_switched_off_it_is_typed(self):
        self.assertIsInstance(interpret("space", True, frozenset({"space"})), Dictation)

    def test_backspace_is_still_backspace(self):
        self.assertEqual(interpret("Backspace", True), Command("backspace", "1"))
        self.assertEqual(interpret("back space 2", True), Command("backspace", "2"))


class LineCommands(unittest.TestCase):
    def test_one_line_by_number(self):
        self.assertEqual(interpret("Delete one line.", True), Command("delete_line", "1"))
        self.assertEqual(interpret("Delete 1 line.", True), Command("delete_line", "1"))
        self.assertEqual(interpret("Delete 3 lines.", True), Command("delete_line", "3"))
        self.assertEqual(interpret("Delete the line.", True), Command("delete_line", "1"))

    def test_a_line_number_written_with_a_comma(self):
        self.assertEqual(interpret("Go to line 1,250.", True), Command("go_to_line", "1250"))
        self.assertEqual(normalise("1,250 and 3, 4"), "1250 and 3 4")


class ThatWasANoise(unittest.TestCase):
    def test_the_ways_of_saying_it(self):
        for said in ("That was a noise.", "That was noise.", "That's a noise", "That was just a noise."):
            self.assertEqual(interpret(said, True), Command("noise"), said)

    def test_it_is_off_to_begin_with_can_be_switched_on_and_is_only_heard_awake(self):
        from dictation.settings import BY_KEY, Settings
        self.assertFalse(BY_KEY["noise"].default)
        off = Settings().disabled_commands()
        self.assertIn("noise", off)
        self.assertIsInstance(interpret("That was a noise.", True, off), Dictation)
        on = Settings({"noise": True}).disabled_commands()
        self.assertNotIn("noise", on)
        self.assertEqual(interpret("That was a noise.", True, on), Command("noise"))
        self.assertIsNone(interpret("That was a noise.", False, on))

    def test_a_sentence_about_a_noise_is_a_sentence(self):
        self.assertIsInstance(interpret("That was a noise I had not heard before.", True), Dictation)


class NearWordsDoNotWake(unittest.TestCase):
    """Asleep, things said to somebody else in the room must not wake it."""

    def test_it_has_to_begin_with_wake(self):
        for heard in ("Make up.", "Woke up.", "Take up.", "Walk up.", "Shake up."):
            self.assertIsNone(interpret(heard, awake=False), heard)

    def test_and_go_on_with_something_like_up(self):
        self.assertIsNone(interpret("Wake me up.", awake=False))
        self.assertIsNone(interpret("Wake them.", awake=False))
        for heard in ("Wake us.", "Wake a.", "Wake it up.", "Wakey wakey."):
            self.assertIsNone(interpret(heard, awake=False), heard)

    def test_a_mishearing_of_either_word_of_wake_up_still_wakes(self):
        for heard in ("Wake app.", "Wake op.", "Weak up.", "Wake hup.", "Wake upp.", "Awake app."):
            self.assertEqual(interpret(heard, awake=False), Command("wake"), heard)

    def test_a_polite_or_hesitant_wake_up_still_wakes(self):
        for heard in ("Wake up, please.", "OK, wake up.", "Please wake up."):
            self.assertEqual(interpret(heard, awake=False), Command("wake"), heard)


class SentencesThatBeginWithACommandWord(unittest.TestCase):
    """ "Select" and "correct" start sentences too. Where it can be told, it is typed."""

    def test_punctuation_straight_after_the_word_makes_it_only_perhaps_a_command(self):
        # A word or two after it: perhaps the command, said with a pause; the engine decides
        # by whether they were typed a moment ago (see Engine.handle_text). More: a sentence.
        for heard, words in (("Correct, yes.", "yes"), ("Select: the first one.", "the first one"),
                             ("Correct. The cat sat.", "the cat sat"), ("Select - the cat", "the cat"),
                             ("Correct... the cat", "the cat"), ("Correct, John T.", "john t")):
            self.assertEqual(interpret(heard, True), Command(heard.split()[0].strip(",.:").lower(), words,
                                                             maybe=True), heard)
        heard = "Correct, the meeting is at three today."
        self.assertEqual(interpret(heard, True), Dictation(heard))

    def test_punctuation_further_on_does_not(self):
        self.assertEqual(interpret("Select the cat, the dog.", True), Command("select", "the cat the dog"))
        self.assertEqual(interpret("Correct the word correct.", True),
                         Command("correct", "the word correct"))

    def test_more_words_than_anyone_selects_is_a_sentence(self):
        from dictation.commands import MAX_SELECT_WORDS
        words = "one two three four five six seven eight nine ten".split()
        longest = "Select " + " ".join(words[:MAX_SELECT_WORDS])
        self.assertEqual(interpret(longest, True), Command("select", " ".join(words[:MAX_SELECT_WORDS])))
        too_long = "Select " + " ".join(words[:MAX_SELECT_WORDS + 1])
        self.assertEqual(interpret(too_long, True), Dictation(too_long))
        heard = "Select the File menu and then click the Save button to finish."
        self.assertEqual(interpret(heard, True), Dictation(heard))

    def test_a_short_one_is_still_the_command(self):
        # "Select Save." can't be told from the command: the engine says what it selected.
        self.assertEqual(interpret("Select Save.", True), Command("select", "save"))

    def test_the_command_loses_its_marks_the_way_the_search_expects(self):
        self.assertEqual(interpret("Select 1,250.", True), Command("select", "1250"))
        self.assertEqual(interpret("Select U.S.", True), Command("select", "us"))
        self.assertEqual(interpret("Correct 3:30 p.m.", True), Command("correct", "3 30 pm"))


class NearMisses(unittest.TestCase):
    """A command said a little differently is still the command, not words to type."""

    def test_please_and_a_hesitation(self):
        for heard, name in (("Go to sleep, please.", "sleep"), ("OK, scratch that.", "scratch"),
                            ("Um, new paragraph.", "new_paragraph"), ("Oh, undo that.", "undo"),
                            ("No, scratch that.", "scratch"), ("Please bold that.", "bold"),
                            ("Tab, please.", "tab"), ("No, no, delete that.", "delete"),
                            ("Oh no, scratch that.", "scratch"), ("No. Scratch that.", "scratch")):
            self.assertEqual(interpret(heard, True), Command(name), heard)
        self.assertEqual(interpret("Um, select the cat, please.", True), Command("select", "the cat"))

    def test_and_is_no_hesitation(self):
        # People dictate these: the sentence goes on from the one before.
        for heard in ("And select all.", "And delete that.", "And undo that.", "And new line.",
                      "And go to sleep.", "And correct that.", "And, um, select all.",
                      "OK, and select all.", "And select all the files that changed."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertIsNone(interpret("And wake up.", awake=False))

    def test_no_is_one_only_with_a_pause_after_it(self):
        # The recogniser writes the pause as punctuation. With none, "no" is part of
        # what is being said.
        for heard in ("No new line.", "No new paragraph.", "No tab key.", "No space bar.",
                      "No scratch that", "No comment that."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertEqual(interpret("No, new line.", True), Command("new_line"))
        self.assertEqual(interpret("No - new line", True), Command("new_line"))
        self.assertEqual(interpret("No, select the cat.", True), Command("select", "the cat"))
        self.assertEqual(interpret("No, wake up.", awake=False), Command("wake"))
        self.assertEqual(choice("No, two.", 3), 2)
        self.assertIsNone(choice("No two", 3))

    def test_one_word_is_not_enough_after_a_hesitation(self):
        for heard in ("No tab.", "And space.", "OK.", "No.", "Please.", "Um."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertEqual(interpret("No sleep.", True), Dictation("No sleep."))  # with "sleep" on

    def test_no_caps_that_is_not_no_and_cap_that(self):
        self.assertEqual(interpret("No caps that.", True), Command("no_caps"))
        self.assertEqual(interpret("No cap that.", True), Command("no_caps"))

    def test_said_twice_in_a_breath_it_is_done_once(self):
        self.assertEqual(interpret("Scratch that, scratch that.", True), Command("scratch"))
        # But two line breaks are two line breaks: that is dictation, as it was.
        self.assertEqual(interpret("New line, new line.", True), Dictation("New line, new line."))

    def test_newline_as_one_word(self):
        self.assertEqual(interpret("Newline.", True), Command("new_line"))

    def test_the_may_be_said_or_not(self):
        for heard, name in (("Go to the beginning of the line.", "line_start"),
                            ("Go to end of the line.", "line_end"),
                            ("Go to the end of line.", "line_end"),
                            ("Go to the end of the document.", "doc_end"),
                            ("Go to start of document", "doc_top"),
                            ("Jump to the bottom of the file", "doc_end"),
                            ("Move to the beginning of this paragraph", "para_start"),
                            ("Go to the bottom", "doc_end"),
                            ("Select the whole document", "select_all"),
                            ("Select all the text", "select_all"),
                            ("Press the tab key", "tab")):
            self.assertEqual(interpret(heard, True), Command(name), heard)

    def test_a_the_that_ends_the_phrase_is_the_start_of_a_sentence(self):
        # A pause after "the" cut the sentence short: these are words, not commands.
        for heard in ("New paragraph. The", "New paragraph the", "New line. The", "Undo the",
                      "Spell the", "Indent the", "Tab the", "Space the", "Backspace the",
                      "Scratch that the", "Go to sleep the", "Press enter the", "Enter the"):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        # "Select all the" is still "select" and the words, as it was: not "select all".
        self.assertEqual(interpret("Select all the", True), Command("select", "all the"))
        self.assertEqual(interpret("Select all the text", True), Command("select_all"))

    def test_down_the_line_is_something_people_say(self):
        for heard in ("Down the line.", "Up the line.", "Move down the line.", "Down the lines."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertEqual(interpret("Down one line.", True), Command("line_down", "1"))
        self.assertEqual(interpret("Down a line", True), Command("line_down", "1"))
        self.assertEqual(interpret("Delete the line.", True), Command("delete_line", "1"))

    def test_where_to_go_has_to_be_said(self):
        for heard in ("Go to the end.", "Go to the top of the hill.", "Go to the shops."):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)

    def test_other_names_for_the_same_thing(self):
        self.assertEqual(interpret("Capitalize that.", True), Command("cap"))
        self.assertEqual(interpret("Capitalise that.", True), Command("cap"))
        self.assertEqual(interpret("Deselect that.", True), Command("unselect"))
        self.assertEqual(interpret("Delete that line.", True), Command("delete_line", "1"))
        self.assertEqual(interpret("Comment that line.", True), Command("comment_line"))
        self.assertEqual(interpret("Select that line", True), Command("select_line"))

    def test_a_count_over_the_most_is_the_most(self):
        self.assertEqual(interpret("Backspace 100.", True), Command("backspace", "99"))
        self.assertEqual(interpret("Delete 150 lines", True), Command("delete_line", "99"))
        self.assertEqual(interpret("Up 150 lines", True), Command("line_up", "150"))
        self.assertEqual(interpret("Up 2000 lines", True), Command("line_up", "999"))
        self.assertEqual(interpret("Backspace 0", True), Dictation("Backspace 0"))

    def test_tab_takes_a_count_as_space_does(self):
        self.assertEqual(interpret("Tab three times.", True), Command("tab", "3"))
        self.assertEqual(interpret("Tab 2", True), Command("tab", "2"))
        self.assertEqual(interpret("Press tab twice", True), Command("tab", "2"))
        self.assertEqual(interpret("Tab once", True), Command("tab"))
        self.assertEqual(interpret("Tab 99", True), Command("tab", "20"))
        for heard in ("Tab to the next box", "tab to", "Tab space"):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertEqual(interpret("Tab 3", True, frozenset({"tab"})), Dictation("Tab 3"))

    def test_a_count_in_words_over_twenty(self):
        self.assertEqual(interpret("Go to line forty two", True), Command("go_to_line", "42"))
        self.assertEqual(interpret("Backspace twenty-one", True), Command("backspace", "21"))
        self.assertEqual(interpret("Delete the last thirty words", True), Command("delete_words", "30"))

    def test_redo_is_a_command_as_undo_is(self):
        self.assertEqual(interpret("Redo.", True), Command("redo"))
        self.assertEqual(interpret("Redo that.", True), Command("redo"))
        self.assertEqual(interpret("Redo.", True, frozenset({"redo"})), Dictation("Redo."))


class WhileNumbersShow(unittest.TestCase):
    def test_which_one_as_well_as_which_number(self):
        for heard, n in (("The second one.", 2), ("Second.", 2), ("Three please.", 3),
                         ("The first", 1), ("2nd", 2), ("Um, two.", 2), ("Choose the third one", 3)):
            self.assertEqual(choice(heard, 3), n, heard)

    def test_not_a_choice(self):
        for heard in ("The fourth one.", "One more thing", "The second sentence", "No.", "One one"):
            self.assertIsNone(choice(heard, 3), heard)

    def test_none_of_them_takes_the_numbers_away(self):
        from dictation.commands import is_cancel
        for heard in ("None.", "Neither of them.", "Cancel, please.", "No, cancel."):
            self.assertTrue(is_cancel(heard), heard)
        self.assertFalse(is_cancel("No."))


class DeleteLastWord(unittest.TestCase):
    def left(self, before, count=1):
        from dictation.commands import last_words_length
        return before[:len(before) - last_words_length(before, count)]

    def test_a_word_runs_back_to_the_space_before_it(self):
        self.assertEqual(self.left("costs $25.50"), "costs")
        self.assertEqual(self.left("it costs 1,250"), "it costs")
        self.assertEqual(self.left("bob@example.com"), "")
        self.assertEqual(self.left("the U.S."), "the")
        self.assertEqual(self.left("mail bob@example.com now", 2), "mail")

    def test_punctuation_by_itself_is_no_word(self):
        self.assertEqual(self.left("wait - what"), "wait -")
        self.assertEqual(self.left("wait - what", 2), "")


class TheAppsOwnWindows(unittest.TestCase):
    def test_what_is_said(self):
        for heard, which in (("What can I say?", "help"), ("Open dictation settings.", "settings"),
                             ("Dictation settings", "settings"), ("Show microphone level", "meter"),
                             ("Show the microphone level.", "meter"), ("Show the level meter", "meter"),
                             ("Close that window.", "close"), ("What can I say, please?", "help")):
            self.assertEqual(interpret(heard, True), Command("app", which), heard)

    def test_switched_off_as_a_group(self):
        off = frozenset({"app"})
        for heard in ("What can I say?", "Dictation settings", "Show the level meter", "Close that window."):
            self.assertEqual(interpret(heard, True, off), Dictation(heard), heard)

    def test_only_as_the_whole_phrase_and_awake(self):
        for heard in ("What can I say about it?", "The dictation settings are here", "Close that window now"):
            self.assertEqual(interpret(heard, True), Dictation(heard), heard)
        self.assertIsNone(interpret("What can I say?", False))


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from dictation import vscode_args
from dictation.vscode_args import disable, enable, with_switch, without_switch

AS_VS_CODE_WRITES_IT = '''// This configuration file allows you to pass permanent command line arguments to VS Code.
//
// NOTE: Changing this file requires a restart of VS Code.
{
\t// Use software rendering instead of hardware accelerated rendering.
\t// "disable-hardware-acceleration": true,

\t// Allows to disable crash reporting.
\t"enable-crash-reporter": true,

\t// Do not edit this value.
\t"crash-reporter-id": "00000000-0000"
}'''


def read(text: str) -> dict:
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))


class Switch(unittest.TestCase):
    def test_added_to_the_file_vs_code_makes(self):
        changed = with_switch(AS_VS_CODE_WRITES_IT)
        self.assertEqual(read(changed), {"enable-crash-reporter": True, "crash-reporter-id": "00000000-0000",
                                         "force-renderer-accessibility": True})
        self.assertIn('// "disable-hardware-acceleration": true,', changed)   # comments are kept
        self.assertIsNone(with_switch(changed))                                # and it isn't added twice

    def test_already_on(self):
        self.assertIsNone(with_switch('{\n\t"force-renderer-accessibility": true\n}'))

    def test_switched_off_is_switched_on(self):
        changed = with_switch('{\n\t"force-renderer-accessibility": false,\n\t"locale": "en"\n}')
        self.assertEqual(read(changed), {"force-renderer-accessibility": True, "locale": "en"})

    def test_an_empty_file_and_one_ending_in_comments(self):
        self.assertEqual(read(with_switch("{\n}\n")), {"force-renderer-accessibility": True})
        changed = with_switch('{\n\t"locale": "en"\n\t// a last remark\n}\n')
        self.assertEqual(read(changed), {"locale": "en", "force-renderer-accessibility": True})

    def test_a_commented_out_line_does_not_count(self):
        changed = with_switch('{\n\t// "force-renderer-accessibility": true\n\t"locale": "en"\n}')
        self.assertEqual(read(changed), {"locale": "en", "force-renderer-accessibility": True})

    def test_something_that_is_not_such_a_file_is_left(self):
        self.assertIsNone(with_switch("not json at all"))

    def test_on_disk(self):
        folder = tempfile.mkdtemp()
        self.assertIn("switched on", enable(folder))            # no file yet: one is made
        with open(os.path.join(folder, "argv.json"), encoding="utf-8") as f:
            self.assertEqual(read(f.read()), {"force-renderer-accessibility": True})
        self.assertIn("already on", enable(folder))


class ACommentAfterTheLastSetting(unittest.TestCase):
    def test_the_comma_goes_before_the_comment(self):
        made = with_switch('{\n\t"a": 1 // the last one\n}')
        self.assertIn('"a": 1, // the last one', made)
        self.assertNotIn("one,", made)

    def test_two_slashes_inside_a_setting_are_not_a_comment(self):
        made = with_switch('{\n\t"url": "http://x//y"\n}')
        self.assertIn('"url": "http://x//y",', made)


class TakenOutAgain(unittest.TestCase):
    """What the uninstaller does: the file goes back to what it was."""

    def test_what_was_added_comes_out_and_nothing_else(self):
        for before in (AS_VS_CODE_WRITES_IT,
                       "{\n}\n",
                       '{\n\t"locale": "en"\n\t// a last remark\n}\n',
                       '{\n\t"a": 1 // the last one\n}',
                       '{\n\t"url": "http://x//y"\n}'):
            with self.subTest(before=before):
                self.assertEqual(without_switch(with_switch(before)), before)

    def test_a_comma_that_was_there_before_is_not_told_from_ours(self):
        # Whose comma it was can't be known afterwards. Without it the file is still right.
        self.assertEqual(without_switch(with_switch('{\n\t"a": 1,\n}')), '{\n\t"a": 1\n}')

    def test_a_switch_somebody_set_themselves_is_left(self):
        self.assertIsNone(without_switch('{\n\t"force-renderer-accessibility": true\n}'))
        self.assertIsNone(without_switch(AS_VS_CODE_WRITES_IT))
        self.assertIsNone(without_switch("not json at all"))
        # One that was off and was switched on has no comment of ours: it stays on.
        self.assertIsNone(without_switch(
            with_switch('{\n\t"force-renderer-accessibility": false,\n\t"locale": "en"\n}')))

    def test_settings_added_after_ours_keep_the_file_whole(self):
        added = with_switch('{\n\t"locale": "en"\n}')
        later = added.replace('"force-renderer-accessibility": true',
                              '"force-renderer-accessibility": true,\n\t"password-store": "basic"')
        self.assertEqual(read(later), {"locale": "en", "force-renderer-accessibility": True,
                                       "password-store": "basic"})
        self.assertEqual(read(without_switch(later)), {"locale": "en", "password-store": "basic"})

    def test_ours_switched_off_by_hand_comes_out_too(self):
        added = with_switch('{\n\t"locale": "en"\n}').replace(": true", ": false")
        self.assertEqual(without_switch(added), '{\n\t"locale": "en"\n}')

    def test_on_disk(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "argv.json")
        self.assertEqual(disable(folder), "")                    # no file: nothing to do
        with open(path, "w", encoding="utf-8") as f:
            f.write(AS_VS_CODE_WRITES_IT)
        os.chmod(path, 0o600)
        enable(folder)
        self.assertIn("taken out", disable(folder))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), AS_VS_CODE_WRITES_IT)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)   # and its rights are as they were
        self.assertEqual(os.listdir(folder), ["argv.json"])      # nothing left beside it
        self.assertEqual(disable(folder), "")                    # a second time changes nothing

    def test_a_file_that_is_a_link_stays_one(self):
        folder, elsewhere = tempfile.mkdtemp(), tempfile.mkdtemp()
        real = os.path.join(elsewhere, "argv.json")
        with open(real, "w", encoding="utf-8") as f:
            f.write('{\n\t"locale": "en"\n}')
        os.symlink(real, os.path.join(folder, "argv.json"))
        enable(folder)
        self.assertTrue(os.path.islink(os.path.join(folder, "argv.json")))
        with open(real, encoding="utf-8") as f:
            self.assertEqual(read(f.read()), {"locale": "en", "force-renderer-accessibility": True})

    def test_a_file_that_cannot_be_read_is_not_written_over(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "argv.json")
        with open(path, "wb") as f:
            f.write(b'{\n\t"locale": "\xff\xfe"\n}')              # not UTF-8
        self.assertIn("left alone", enable(folder))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b'{\n\t"locale": "\xff\xfe"\n}')


class EveryVsCode(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.kept = vscode_args.FOLDERS
        vscode_args.FOLDERS = (os.path.join(self.home, ".vscode"), os.path.join(self.home, ".vscode-oss"))

    def tearDown(self):
        vscode_args.FOLDERS = self.kept

    def test_only_the_ones_that_have_been_run(self):
        self.assertEqual(vscode_args.switch_on(), [])
        os.mkdir(os.path.join(self.home, ".vscode"))
        self.assertEqual(len(vscode_args.switch_on()), 1)
        self.assertEqual(len(vscode_args.switch_off()), 1)
        self.assertEqual(vscode_args.switch_off(), [])           # nothing of ours is left

    def test_the_command_line(self):
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            self.assertEqual(vscode_args.main([]), 0)            # no VS Code: it says so
            os.mkdir(os.path.join(self.home, ".vscode"))
            self.assertEqual(vscode_args.main([]), 0)
            self.assertEqual(vscode_args.main(["--remove"]), 0)
            self.assertEqual(vscode_args.main(["--something-else"]), 2)
        with open(os.path.join(self.home, ".vscode", "argv.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "{\n}\n")
        self.assertIn("nothing to switch on", said.getvalue())
        self.assertIn("switched on", said.getvalue())
        self.assertIn("taken out", said.getvalue())


if __name__ == "__main__":
    unittest.main()

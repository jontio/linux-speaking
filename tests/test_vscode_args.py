import json
import os
import re
import tempfile
import unittest

from dictation.vscode_args import enable, with_switch

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


if __name__ == "__main__":
    unittest.main()

"""The Windows installer and uninstaller, read as text: PowerShell isn't there to run them
where these tests run. What can be held to from here is that the two agree with each
other and with the guide, above all about the Python the installer can fetch for itself."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts) -> str:
    with open(os.path.join(HERE, *parts), encoding="utf-8", newline="") as f:
        return f.read()


def number(text: str, name: str) -> int:
    found = re.search(r"^\$" + name + r" = (\d+)\b", text, re.M)
    assert found, name
    return int(found.group(1))


def names(text: str, start: str) -> list:
    """The quoted names in the list that begins at `start` and ends with its bracket."""
    begins = text.index(start)
    return re.findall(r'"([^"]+)"', text[begins:text.index(")", begins)])


class TheScripts(unittest.TestCase):
    def test_they_are_plain_ascii(self):
        # Windows PowerShell 5.1 reads a script with no byte-order mark in the PC's own
        # code page: a curly quote or a dash would arrive as something else.
        for name in ("install.ps1", "uninstall.ps1"):
            text = read(name)
            odd = sorted({c for c in text if ord(c) > 127})
            self.assertEqual(odd, [], name)

    def test_every_option_in_the_installers_heading_is_in_the_guide(self):
        heading = read("install.ps1").split("$ErrorActionPreference", 1)[0]
        options = sorted(set(re.findall(r"^#\s+(LS_[A-Z_]+)", heading, re.M)))
        self.assertIn("LS_FETCH_PYTHON", options)
        guide = read("docs", "WINDOWS.md")
        for option in options:
            self.assertIn("$env:" + option, guide)


class APythonOfItsOwn(unittest.TestCase):
    def setUp(self):
        self.installer = read("install.ps1")
        self.uninstaller = read("uninstall.ps1")

    def test_the_one_it_fetches_is_one_it_would_not_turn_away(self):
        oldest, newest = number(self.installer, "oldest"), number(self.installer, "newest")
        self.assertTrue(oldest <= number(self.installer, "fetchMinor") <= newest)

    def test_only_finished_versions_of_that_python_are_taken(self):
        # The line that picks a version, with Python's eyes: no alpha, beta or candidate.
        found = re.search(r'-match "(\^3\\\.\$fetchMinor\\\.\(\\d\+\)\$)"', self.installer)
        self.assertTrue(found, "the line that picks a version has changed")
        rule = re.compile(found.group(1).replace("$fetchMinor", "14"))
        listed = ["3.13.9", "3.14.0-rc1", "3.14.2", "3.14.10", "3.14.11-b1", "3.140.1", "3.15.0"]
        self.assertEqual([v for v in listed if rule.match(v)], ["3.14.2", "3.14.10"])

    def test_its_folders_are_the_installers_own_and_the_uninstaller_removes_them(self):
        # Else a second run would call the install folder "a folder with other things in
        # it", and an uninstall would leave a Python behind.
        ours = names(self.installer, "$ours = @(")
        removed = names(self.uninstaller, 'foreach ($name in "app"')
        self.assertIn('$ownPython = "$dir\\python"', self.installer)
        for folder in ("python", "python.new"):
            self.assertIn(folder, ours)
            self.assertIn(folder, removed)

    def test_it_is_checked_before_it_is_put_in_place(self):
        fetch = self.installer[self.installer.index("function Get-OwnPython"):
                               self.installer.index("function Ask-AboutPython")]
        checked = fetch.index("Get-AuthenticodeSignature")
        self.assertLess(checked, fetch.index("Rename-Item"))
        self.assertIn("O=Python Software Foundation", fetch)
        self.assertIn('-ne "Valid"', fetch)
        self.assertLess(fetch.index("Probe @("), fetch.index("Rename-Item"))

    def test_the_guide_gives_the_sizes_the_question_gives(self):
        question = self.installer[self.installer.index("function Ask-AboutPython"):]
        question = " ".join(re.findall(r'Write-Host "([^"]*)"', question[:question.index("Read-Host")]))
        sizes = re.search(r"a download of (about \d+ MB) that takes (about \d+ MB) of disk", question)
        self.assertTrue(sizes, question)
        guide = " ".join(read("docs", "WINDOWS.md").split())
        self.assertIn(f"a download of {sizes.group(1)} that takes {sizes.group(2)} of disk", guide)

    def test_it_is_fetched_only_when_asked_for(self):
        # Yes from whoever is asked, or from LS_FETCH_PYTHON: nothing else sets it going.
        sets = re.findall(r"^\s*(?:\S.*)?\$fetchPython = (.+?)\s*}?\s*$", self.installer, re.M)
        self.assertEqual(sorted(sets), ["$false", "$true", "Ask-AboutPython $turnedAway"])
        self.assertIn('if ($env:LS_FETCH_PYTHON -eq "1") { $fetchPython = $true }', self.installer)


if __name__ == "__main__":
    unittest.main()

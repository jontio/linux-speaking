"""The check both installers run before they say "Done": what it makes of an install
with no speech model."""
import importlib.util
import io
import os
import unittest
from unittest import mock


def load():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "check_install.py")
    spec = importlib.util.spec_from_file_location("check_install", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WithNoSpeechModel(unittest.TestCase):
    def check(self, skipped: bool, here=(), chosen="", loads=True):
        module, out = load(), io.StringIO()
        env = {name: value for name, value in os.environ.items() if name != "LS_SKIP_MODELS"}
        if skipped:
            env["LS_SKIP_MODELS"] = "1"
        self.loaded = []

        def load_it(name=""):
            self.loaded.append(name)
            if not loads:
                raise RuntimeError("damaged")

        with mock.patch.object(module, "missing_packages", return_value=[]), \
                mock.patch("dictation.settings.available_models", return_value=list(here)), \
                mock.patch("dictation.settings.Settings.load",
                           return_value=mock.Mock(model=chosen)), \
                mock.patch("dictation.models.is_installed", return_value=False), \
                mock.patch("dictation.engine.Transcriber", side_effect=load_it), \
                mock.patch.dict(os.environ, env, clear=True):
            return module.check(out), out.getvalue()

    def test_asked_for_it_is_no_fault(self):
        # A small computer that leaves the recognising to another one: the install goes
        # on to its end, and the installer says what to do next.
        ended, said = self.check(skipped=True)
        self.assertEqual(ended, 0)
        self.assertIn("No speech model is installed, as chosen", said)
        self.assertEqual(self.loaded, [])

    def test_not_asked_for_it_is_what_is_wrong(self):
        ended, said = self.check(skipped=False)
        self.assertEqual(ended, 1)
        self.assertIn("Run the installer again", said)

    def test_models_installed_from_settings_since_only_have_to_load(self):
        # Not the two an ordinary install starts with: whichever the person chose to have.
        ended, said = self.check(skipped=True, here=[("medium.en", "Medium")])
        self.assertEqual((ended, self.loaded), (0, ["medium.en"]))
        self.assertIn("The speech models load", said)
        # The one chosen in Settings, where that is one of them.
        self.check(skipped=True, chosen="parakeet-unified-en-0.6b",
                   here=[("small.en", "Small"), ("parakeet-unified-en-0.6b", "Parakeet Unified")])
        self.assertEqual(self.loaded, ["parakeet-unified-en-0.6b"])
        # Small, where the choice is of a model that has gone.
        self.check(skipped=True, chosen="gone", here=[("medium.en", "Medium"), ("small.en", "Small")])
        self.assertEqual(self.loaded, ["small.en"])

    def test_and_one_that_wont_load_is_still_what_is_wrong(self):
        ended, said = self.check(skipped=True, here=[("medium.en", "Medium")], loads=False)
        self.assertEqual(ended, 1)
        self.assertIn("could not be loaded", said)


class WhereTheModelsAre(unittest.TestCase):
    """The folder the program keeps its speech models in, as it works that out when it
    starts."""

    def where(self, own=(), other=()):
        import subprocess
        import sys
        import tempfile
        home = tempfile.mkdtemp()
        install = os.path.join(home, "linux-speaking")
        theirs = os.path.join(home, ".var", "app", "net.mkiol.SpeechNote", "cache", "net.mkiol",
                              "dsnote", "speech-models")
        for folder, names in ((os.path.join(install, "models"), own), (theirs, other)):
            for name in names:
                os.makedirs(os.path.join(folder, name))
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("LS_")}
        env.update(HOME=home, USERPROFILE=home, LS_INSTALL_DIR=install)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        said = subprocess.run(
            [sys.executable, "-c", "from dictation import config; "
                                   "print(config.MODEL_DIR); print(config.AWAKE_MODEL)"],
            cwd=root, env=env, capture_output=True, text=True, check=True).stdout.split("\n")
        return os.path.relpath(said[0], home).replace(os.sep, "/"), said[1]

    def test_with_none_anywhere_it_is_the_installs_own_folder(self):
        # A computer installed with no speech model: one fetched later lands here.
        self.assertEqual(self.where(), ("linux-speaking/models", "small.en"))

    def test_its_own_where_it_has_small(self):
        self.assertEqual(self.where(own=["small.en"], other=["en_fasterwhisper_small"]),
                         ("linux-speaking/models", "small.en"))

    def test_another_programs_only_where_those_are_really_there(self):
        folder, name = self.where(other=["en_fasterwhisper_small"])
        self.assertTrue(folder.endswith("dsnote/speech-models"), folder)
        self.assertEqual(name, "en_fasterwhisper_small")


if __name__ == "__main__":
    unittest.main()

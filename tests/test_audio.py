"""The microphone: what is said when it can't be opened, or stops."""
import subprocess
import sys
import unittest
from unittest import mock

from dictation import audio


class OnLinux(unittest.TestCase):
    def setUp(self):
        patch = mock.patch("dictation.audio.config.WINDOWS", False)
        patch.start()
        self.addCleanup(patch.stop)

    def recorder(self):
        recorder = audio.open_microphone()

        def see_out():
            recorder.close()
            recorder._process.wait(timeout=5)
            recorder._process.stdout.close()
            recorder._process.stderr.close()
        self.addCleanup(see_out)
        return recorder

    def test_no_recording_program_is_said_in_words(self):
        with mock.patch("dictation.audio.subprocess.Popen", side_effect=FileNotFoundError(2, "No such file")):
            with self.assertRaises(audio.MicrophoneError) as raised:
                audio.open_microphone()
        self.assertIn("parec", str(raised.exception))
        self.assertNotIn("Errno", str(raised.exception))

    def test_a_recorder_that_ends_at_once_says_why(self):
        ends = [sys.executable, "-c", "import sys; sys.stderr.write('Connection failure: Connection refused\\n')"]
        with mock.patch("dictation.audio.RECORD_COMMAND", ends):
            recorder = self.recorder()
            self.assertEqual(recorder.read(640), b"")
            self.assertIn("No sound server answered", recorder.why())

    def test_one_that_ends_without_a_word_says_nothing(self):
        with mock.patch("dictation.audio.RECORD_COMMAND", [sys.executable, "-c", "pass"]):
            recorder = self.recorder()
            self.assertEqual(recorder.read(640), b"")
            self.assertEqual(recorder.why(), "")

    def test_sound_comes_through(self):
        speaks = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes(640))"]
        with mock.patch("dictation.audio.RECORD_COMMAND", speaks):
            recorder = self.recorder()
            self.assertEqual(recorder.read(640), bytes(640))

    def test_whether_it_works_can_be_tried_without_keeping_it_open(self):
        speaks = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes(640))"]
        with mock.patch("dictation.audio.RECORD_COMMAND", speaks):
            self.assertTrue(audio.works())
        with mock.patch("dictation.audio.RECORD_COMMAND", [sys.executable, "-c", "pass"]):
            self.assertFalse(audio.works())
        with mock.patch("dictation.audio.subprocess.Popen", side_effect=FileNotFoundError(2, "none")):
            self.assertFalse(audio.works())

    def test_there_is_no_list_of_microphones(self):
        self.assertEqual(audio.microphones(fresh=True), [])


class OnWindows(unittest.TestCase):
    """With a stand-in for the sound library, which isn't here."""

    def setUp(self):
        self.library = mock.Mock()
        self.library.query_hostapis.return_value = [{"name": "MME"}]
        self.library.query_devices.return_value = [
            {"name": "Headset", "max_input_channels": 1, "hostapi": 0},
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0}]
        for patch in (mock.patch("dictation.audio.config.WINDOWS", True),
                      mock.patch.dict(sys.modules, {"sounddevice": self.library}),
                      mock.patch("dictation.audio._streams", 0)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_refusal_is_said_in_words_with_what_to_check(self):
        self.library.RawInputStream.side_effect = RuntimeError("Error opening RawInputStream: Invalid device [PaErrorCode -9996]")
        with self.assertRaises(audio.MicrophoneError) as raised:
            audio.open_microphone("Headset")
        self.assertIn("Privacy", str(raised.exception))
        self.assertIn("-9996", str(raised.exception))

    def test_the_list_is_read_again_only_while_nothing_is_recording(self):
        self.assertEqual(audio.microphones(fresh=True), ["Headset"])
        self.assertEqual(self.library._terminate.call_count, 1)
        recorder = audio.open_microphone("Headset")       # reads it again itself, once
        self.assertEqual(self.library._terminate.call_count, 2)
        self.assertEqual(audio.microphones(fresh=True), ["Headset"])
        self.assertEqual(self.library._terminate.call_count, 2)   # not under a recording
        recorder.close()
        recorder.close()                                    # twice is once
        audio.microphones(fresh=True)
        self.assertEqual(self.library._terminate.call_count, 3)

    def test_a_name_windows_cut_off_is_shown_whole(self):
        cut = "Microphone (Realtek High Defini"
        self.assertEqual(len(cut), audio.CUT_AT)
        self.library.query_hostapis.return_value = [
            {"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"},
            {"name": "Windows WDM-KS"}]
        self.library.query_devices.return_value = [
            {"name": cut, "max_input_channels": 1, "hostapi": 0},
            {"name": "Headset", "max_input_channels": 1, "hostapi": 0},
            {"name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 1, "hostapi": 1},
            {"name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 1, "hostapi": 2},
            {"name": "Microphone (Realtek High Definition Audio) out", "max_input_channels": 0, "hostapi": 2},
            {"name": "Microphone (Realtek High Definitive)", "max_input_channels": 1, "hostapi": 3}]
        self.assertEqual(audio.whole(cut), "Microphone (Realtek High Definition Audio)")
        self.assertEqual(audio.whole("Headset"), "Headset")
        # It is still chosen and opened by the name it was cut to.
        self.assertEqual(audio.microphones(), [cut, "Headset"])
        self.assertEqual(audio._device(cut), 0)

    def test_a_cut_name_that_two_devices_begin_with_is_left(self):
        cut = "Headset Microphone (USB Audio D"
        self.assertEqual(len(cut), audio.CUT_AT)
        self.library.query_hostapis.return_value = [{"name": "MME"}, {"name": "Windows WASAPI"}]
        self.library.query_devices.return_value = [
            {"name": cut, "max_input_channels": 1, "hostapi": 0},
            {"name": cut + "evice 1)", "max_input_channels": 1, "hostapi": 1},
            {"name": cut + "evice 2)", "max_input_channels": 1, "hostapi": 1}]
        self.assertEqual(audio.whole(cut), cut)
        self.library.query_devices.return_value = self.library.query_devices.return_value[:1]
        self.assertEqual(audio.whole(cut), cut)              # nothing begins with it
        self.library.query_devices.side_effect = RuntimeError("no sound system")
        self.assertEqual(audio.whole(cut), cut)

    def test_a_device_that_goes_away_ends_the_reading_and_says_why(self):
        recorder = audio.open_microphone()
        self.library.RawInputStream.return_value.read.side_effect = RuntimeError("Device unavailable")
        self.assertEqual(recorder.read(640), b"")
        self.assertEqual(recorder.why(), "Device unavailable")


if __name__ == "__main__":
    unittest.main()

"""The Windows pipe's own reasoning, with stand-ins for Windows: what is asked of a pipe
before anything is sent down it, and what is done about a busy one. The calls into
Windows themselves (who owns a pipe, how it is labelled) can only be tried there."""
import importlib
import sys
import time
import types
import unittest
from unittest import mock

ME, ADMINISTRATORS, SOMEBODY_ELSE = "S-1-5-21-1-2-3-1001", "S-1-5-32-544", "S-1-5-21-1-2-3-1002"
BUSY, NOT_FOUND, BROKEN, WAITED_OUT = 231, 2, 109, 121
FOLDER = "\\\\.\\pipe\\"
PATH = FOLDER + "linux-speaking-vscode-4242"


class WindowsError(Exception):
    """Stands in for pywintypes.error."""

    def __init__(self, winerror, funcname="", strerror=""):
        super().__init__(winerror, funcname, strerror)
        self.winerror, self.funcname, self.strerror = winerror, funcname, strerror


class Handle:
    def __init__(self):
        self.closed = False

    def Close(self):
        self.closed = True

    def __int__(self):
        return 7


class Windows:
    """What the stand-ins do, and what was done to them."""

    def __init__(self):
        self.busy = 0            # how many more times opening the pipe finds it busy
        self.waits = 0           # how many times a busy pipe was waited on
        self.handles = []
        self.written = b""
        self.reply = b'{"ok": true, "ready": true}\n'
        self.moved = 0

    def open(self, path, *_):
        if self.busy:
            self.busy -= 1
            raise WindowsError(BUSY, "CreateFile", "All pipe instances are busy.")
        self.handles.append(Handle())
        return self.handles[-1]

    def wait_for(self, path, milliseconds):
        self.waits += 1
        time.sleep(0.01)
        raise WindowsError(WAITED_OUT, "WaitNamedPipe", "The semaphore timeout period has expired.")

    def write(self, handle, data, overlapped):
        self.written += data
        self.moved = len(data)

    def read(self, handle, buffer, overlapped):
        buffer[:len(self.reply)] = self.reply
        self.moved = len(self.reply)


def module(name, **contents):
    made = types.ModuleType(name)
    vars(made).update(contents)
    return made


def later(seconds):
    """The clock, as the pipe's code reads it, put on by so much."""
    real = time.monotonic
    return mock.patch.object(pipe.time, "monotonic", lambda: real() + seconds)


def setUpModule():
    global pipe, windows, _before
    windows = Windows()
    stand_ins = {
        "pywintypes": module("pywintypes", error=WindowsError,
                             OVERLAPPED=type("OVERLAPPED", (), {"hEvent": None})),
        "winerror": module("winerror", ERROR_PIPE_BUSY=BUSY, ERROR_FILE_NOT_FOUND=NOT_FOUND,
                           ERROR_BROKEN_PIPE=BROKEN, ERROR_SEM_TIMEOUT=WAITED_OUT),
        "win32event": module("win32event", WAIT_OBJECT_0=0, CreateEvent=lambda *_: object(),
                             WaitForSingleObject=lambda *_: 0, ResetEvent=lambda *_: None),
        "win32file": module("win32file", GENERIC_READ=1, GENERIC_WRITE=2, OPEN_EXISTING=3,
                            FILE_FLAG_OVERLAPPED=4, AllocateReadBuffer=bytearray, CancelIo=lambda *_: None,
                            CreateFile=lambda *a: windows.open(*a), WriteFile=lambda *a: windows.write(*a),
                            ReadFile=lambda *a: windows.read(*a),
                            GetOverlappedResult=lambda *_: windows.moved),
        "win32pipe": module("win32pipe", WaitNamedPipe=lambda *a: windows.wait_for(*a)),
        "win32api": module("win32api", OpenProcess=lambda *_: Handle(), GetCurrentProcess=lambda: "this one"),
    }
    _before = {name: sys.modules.get(name) for name in list(stand_ins) + ["dictation.pipe"]}
    sys.modules.update(stand_ins)
    sys.modules.pop("dictation.pipe", None)
    pipe = importlib.import_module("dictation.pipe")


def tearDownModule():
    import dictation
    for name, was in _before.items():
        if was is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = was
    if _before["dictation.pipe"] is not None:
        dictation.pipe = _before["dictation.pipe"]
    elif hasattr(dictation, "pipe"):
        del dictation.pipe


class Pipes(unittest.TestCase):
    def setUp(self):
        global windows
        windows = Windows()
        pipe._ours.clear()
        pipe._left.clear()
        pipe._said.clear()
        self.there = ["linux-speaking-vscode-4242", "something-else"]
        # What Windows would say of the pipe and of this program, unless a test says otherwise.
        self.said = {"_made_by": lambda handle: (ME, ""), "_mine": lambda: {ME},
                     "_server_of": lambda handle: 4242, "_person": lambda process: ME}
        for name in self.said:
            patch = mock.patch.object(pipe, name, lambda *a, name=name: self.said[name](*a))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(pipe.os, "listdir", lambda folder: list(self.there))
        patch.start()
        self.addCleanup(patch.stop)

    def names(self):
        return pipe.names("linux-speaking-vscode-")

    def refused(self):
        with self.assertRaises(PermissionError):
            pipe.send(PATH, {"op": "insert", "text": "private words"}, 0.5)
        self.assertEqual(windows.written, b"")                 # nothing was sent down it
        self.assertTrue(all(handle.closed for handle in windows.handles))


class WhoseItIs(Pipes):
    def test_a_request_goes_down_a_pipe_that_is_ours_and_the_answer_comes_back(self):
        self.assertEqual(self.names(), [PATH])
        self.assertEqual(pipe.send(PATH, {"op": "status"}, 0.5), {"ok": True, "ready": True})
        self.assertEqual(windows.written, b'{"op": "status"}\n')
        self.assertTrue(windows.handles[0].closed)
        self.assertEqual(self.names(), [PATH])

    def test_the_owner_of_the_pipe_is_what_counts_whoever_the_process_number_now_belongs_to(self):
        # Another account made the pipe. The process that made it has ended, and its
        # number has come round to a program of this person's: asked by that number
        # alone, the pipe would pass.
        self.said["_made_by"] = lambda handle: (SOMEBODY_ELSE, "")
        self.assertEqual(pipe._person(object()), pipe._person("this one"))
        self.refused()
        self.assertFalse(pipe.ours(Handle()))

    def test_it_is_not_asked_again_for_as_long_as_it_is_there(self):
        self.said["_made_by"] = lambda handle: (SOMEBODY_ELSE, "")
        self.refused()
        self.assertEqual(self.names(), [])
        with later(86400):
            self.assertEqual(self.names(), [])                 # however long
        self.there.remove("linux-speaking-vscode-4242")
        self.assertEqual(self.names(), [])
        self.there.append("linux-speaking-vscode-4242")        # gone, and one of that name is there again:
        self.assertEqual(self.names(), [PATH])                 # it is looked at afresh

    def test_a_pipe_made_by_a_program_that_is_kept_apart_is_not_ours(self):
        self.said["_made_by"] = lambda handle: (ME, "S:(ML;;NW;;;LW)")
        self.refused()
        for label, apart in (("", False), ("S:", False), ("S:(ML;;NW;;;ME)", False),
                             ("S:(ML;;NW;;;HI)", False), ("S:(ML;;NW;;;S-1-16-8192)", False),
                             ("S:(ML;;NW;;;LW)", True), ("S:(ML;;NW;;;S-1-16-4096)", True),
                             ("S:(ML;;NW;;;S-1-16-0)", True), ("S:(ML;;NW;;;S-1-16-x)", True),
                             ("S:(AU;SA;FA;;;WD)(ML;;NWNR;;;LW)", True)):
            self.assertEqual(pipe._kept_apart(label), apart, label)

    def test_a_program_run_as_administrator_owns_things_as_the_administrators_group(self):
        self.said["_made_by"] = lambda handle: (ADMINISTRATORS, "")
        self.refused()                                         # not this program's account, as it is run
        windows.__init__()
        pipe._left.clear()
        self.said["_mine"] = lambda: {ME, ADMINISTRATORS}      # run as administrator itself
        self.assertTrue(pipe.send(PATH, {"op": "status"}, 0.5)["ok"])

    def test_the_process_at_the_other_end_is_still_looked_at_too(self):
        self.said["_person"] = lambda process: ME if process == "this one" else SOMEBODY_ELSE
        self.refused()

    def test_one_that_cannot_be_asked_is_not_taken_on_trust_and_is_asked_again_later(self):
        for failure in (OSError("the pipe won't say whose it is"), AttributeError("no such call")):
            windows.__init__()
            pipe._left.clear()

            def fails(handle, failure=failure):
                raise failure

            self.said["_made_by"] = fails
            self.assertFalse(pipe.ours(Handle()))
            self.refused()
            self.assertEqual(self.names(), [])
            with later(pipe.BUSY_REST + 1):
                self.assertEqual(self.names(), [PATH])


class Library:
    """Stands in for Windows' own libraries, as the pipe's code calls into them: it hands
    out blocks and texts, as Windows does, and keeps count of what is handed back."""

    def __init__(self, owner=ME, label="S:(ML;;NW;;;ME)", refuses=(), no_owner=False, unreadable=()):
        import ctypes
        self.owner, self.label, self.no_owner = owner, label, no_owner
        self.refuses = set(refuses)       # (what was asked for, as what kind of thing) that fail
        self.unreadable = set(unreadable)  # "owner" or "label": the text of it can't be made
        self.asked, self.out, self.back = [], [], []
        self._kept = []                   # the texts made, kept in being as Windows keeps them
        self._ctypes = ctypes

    def made(self, text="block"):
        buffer = self._ctypes.create_unicode_buffer(text)
        self._kept.append(buffer)
        self.out.append(self._ctypes.addressof(buffer))
        return self.out[-1]

    def __getattr__(self, name):
        def call(*given):
            return getattr(self, "do_" + name)(*given)
        return type("Function", (), {"argtypes": None, "restype": None,
                                     "__call__": lambda self_, *given: call(*given)})()

    def do_GetSecurityInfo(self, handle, kind, wanted, owner, group, dacl, sacl, block):
        self.asked.append((wanted, kind))
        if (wanted, kind) in self.refuses:
            return 5
        block._obj.value = self.made()
        owner._obj.value = None if self.no_owner else block._obj.value
        return 0

    def do_IsValidSid(self, sid):
        return 1

    def do_ConvertSidToStringSidW(self, sid, text):
        if "owner" in self.unreadable:
            return 0
        text._obj.value = self.made(self.owner)
        return 1

    def do_ConvertSecurityDescriptorToStringSecurityDescriptorW(self, block, revision, wanted, text, length):
        if "label" in self.unreadable:
            return 0
        text._obj.value = self.made(self.label)
        return 1

    def do_LocalFree(self, made):
        self.back.append(made.value)


class AskingWindows(unittest.TestCase):
    """How Windows is asked who owns a pipe: with stand-ins for its libraries, to see
    that what comes back is read rightly and that everything Windows hands out is handed
    back, whatever happens. That Windows answers as the stand-ins do is tried there."""

    def ask(self, **how):
        import ctypes
        self.library = Library(**how)
        pipe._said.clear()
        with mock.patch.object(ctypes, "WinDLL", lambda name, **_: self.library, create=True), \
                mock.patch.object(ctypes, "get_last_error", lambda: 5, create=True), \
                mock.patch("builtins.print"):
            return pipe._made_by(Handle())

    def all_handed_back(self):
        self.assertEqual(sorted(self.library.out), sorted(self.library.back))   # each one, and once

    def test_the_owner_and_the_label_are_read_and_everything_is_handed_back(self):
        self.assertEqual(self.ask(owner=SOMEBODY_ELSE, label="S:(ML;;NW;;;LW)"),
                         (SOMEBODY_ELSE, "S:(ML;;NW;;;LW)"))
        self.assertEqual(len(self.library.out), 3)                   # the block, and the two texts
        self.all_handed_back()
        self.assertEqual(self.library.asked, [(pipe.OWNER | pipe.LABEL, pipe.KERNEL_OBJECT)])

    def test_asked_another_way_if_the_first_is_refused_and_for_the_owner_alone_at_the_last(self):
        both = pipe.OWNER | pipe.LABEL
        self.assertEqual(self.ask(refuses=[(both, pipe.KERNEL_OBJECT)])[0], ME)
        self.assertEqual(self.library.asked[-1], (both, pipe.FILE_OBJECT))
        self.all_handed_back()
        whose, label = self.ask(refuses=[(both, pipe.KERNEL_OBJECT), (both, pipe.FILE_OBJECT)])
        self.assertEqual((whose, label), (ME, ""))                   # no label to be had: the owner still is
        self.assertEqual(self.library.asked[-1], (pipe.OWNER, pipe.KERNEL_OBJECT))
        self.all_handed_back()

    def test_a_pipe_that_will_not_say_is_not_taken_on_trust(self):
        everything = [(wanted, kind) for wanted in (pipe.OWNER | pipe.LABEL, pipe.OWNER)
                      for kind in (pipe.KERNEL_OBJECT, pipe.FILE_OBJECT)]
        for how in (dict(refuses=everything), dict(no_owner=True), dict(unreadable=["owner"])):
            with self.assertRaises(OSError, msg=how):
                self.ask(**how)
            self.all_handed_back()
            with mock.patch.object(pipe, "_made_by", side_effect=OSError("it won't say")), \
                    mock.patch("builtins.print"):
                self.assertIsNone(pipe._whose(Handle()))
                self.assertFalse(pipe.ours(Handle()))


    def test_a_label_that_cannot_be_put_into_words_leaves_it_to_the_owner(self):
        # As when the label can't be had at all: refusing would stop dictation into VS
        # Code over the lesser of the two things asked. Who owns the pipe is still known.
        with mock.patch("builtins.print"):
            self.assertEqual(self.ask(unreadable=["label"]), (ME, ""))
        self.all_handed_back()


class Busy(Pipes):
    def test_no_time_is_spent_on_a_busy_pipe_that_was_never_found_to_be_ours(self):
        windows.busy = 1000
        began = time.monotonic()
        with self.assertRaises(OSError):
            pipe.send(PATH, {"op": "status"}, 1.5)
        self.assertLess(time.monotonic() - began, 0.2)
        self.assertEqual(windows.waits, 0)
        self.assertEqual(self.names(), [])                     # and it is left alone for a while
        with later(pipe.BUSY_REST + 1):
            self.assertEqual(self.names(), [PATH])

    def test_a_busy_pipe_of_ours_is_tried_again_until_the_time_is_up(self):
        pipe.send(PATH, {"op": "status"}, 0.5)                 # found to be ours
        windows.busy = 3
        self.assertTrue(pipe.send(PATH, {"op": "status"}, 2.0)["ok"])
        self.assertEqual(windows.waits, 3)                     # not given up on at the first wait
        windows.busy, windows.waits = 1000, 0
        began = time.monotonic()
        with self.assertRaises(OSError):
            pipe.send(PATH, {"op": "status"}, 0.2)
        self.assertGreaterEqual(time.monotonic() - began, 0.15)
        self.assertGreater(windows.waits, 3)
        self.assertEqual(self.names(), [PATH])                 # still ours, and asked next time

    def test_a_pipe_that_has_gone_is_said_to_be_gone(self):
        with mock.patch.object(windows, "open", side_effect=WindowsError(NOT_FOUND, "CreateFile", "gone")):
            with self.assertRaises(FileNotFoundError):
                pipe.send(PATH, {"op": "status"}, 0.5)


if __name__ == "__main__":
    unittest.main()

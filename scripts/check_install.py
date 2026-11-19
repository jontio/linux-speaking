"""Checks a new install before the installer says "Done", for both installers.

    python scripts/check_install.py

Run with the install's own Python. It checks that the Python packages are there, that
the speech models are where the app will look for them, and that they load: the things
that would otherwise leave the tray icon on "Loading" with nobody told why.

It ends with 0 when all is well, and with 1, having said in plain words what is wrong,
when it isn't.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# What is imported, and the package it comes in.
EVERYWHERE = (("numpy", "numpy"), ("PyQt6.QtWidgets", "PyQt6"), ("faster_whisper", "faster-whisper"),
              ("sherpa_onnx", "sherpa-onnx"), ("cryptography", "cryptography"))
WINDOWS_ONLY = (("sounddevice", "sounddevice"), ("win32com.client", "pywin32"),
                ("comtypes", "comtypes"))


def missing_packages(wanted, load=importlib.import_module) -> list:
    """A line for each package that can't be loaded, saying why."""
    lines = []
    for module, package in wanted:
        try:
            load(module)
        except Exception as e:  # not only ImportError: a library it needs may fail to load
            lines.append(f"  {package}: {type(e).__name__}: {e}")
    return lines


def check(out=None) -> int:
    out = out or sys.stdout
    wanted = EVERYWHERE + (WINDOWS_ONLY if os.name == "nt" else ())
    missing = missing_packages(wanted)
    if missing:
        print("These Python packages are not there, or can't be loaded by this Python ("
              + sys.version.split()[0] + "):", file=out)
        print("\n".join(missing), file=out)
        print("Run the installer again. If it is the same again, the lines above are what "
              "to put in a report.", file=out)
        return 1
    from dictation import config, models
    from dictation.settings import Settings, available_models
    # The installer was told to fetch no models: the person's choice when it asked, or
    # LS_SKIP_MODELS=1. Then there may be none, which is no fault, or whichever ones were
    # installed from Settings since, which only have to load.
    left_out = os.environ.get("LS_SKIP_MODELS") == "1"
    here = [name for name, _ in available_models(config.MODEL_DIR)]
    if left_out and not here:
        print("  No speech model is installed, as chosen.", file=out)
        return 0
    chosen = ""
    if left_out:
        chosen = Settings.load(config.SETTINGS_FILE).model
        if chosen not in here:
            chosen = config.AWAKE_MODEL if config.AWAKE_MODEL in here else here[0]
    own = os.path.join(config.INSTALL_DIR, "models")
    for name in () if left_out else (config.ASLEEP_MODEL, config.AWAKE_MODEL):
        if not models.is_installed(config.MODEL_DIR, name):
            if config.MODEL_DIR != own and not os.environ.get("LS_MODEL_DIR"):
                # With no Small model of its own the app looks where another program
                # keeps its models: naming that folder here would only puzzle.
                print(f"The speech models base.en and small.en are not in {own}.", file=out)
            else:
                print(f"The speech model {name} is not in {config.MODEL_DIR}.", file=out)
            print("Run the installer again to fetch what is missing (without LS_SKIP_MODELS), "
                  "or copy the models in by hand: see \"Copying the speech models in by "
                  "hand\" in docs/MODELS.md.", file=out)
            return 1
    try:
        from dictation.engine import Transcriber
        Transcriber(chosen)
    except Exception as e:
        print(f"The speech models are in {config.MODEL_DIR}, but could not be loaded:", file=out)
        print(f"  {type(e).__name__}: {e}", file=out)
        print("If a download was cut short, delete the model's folder there and run the "
              "installer again.", file=out)
        return 1
    print(f"  The speech models load from {config.MODEL_DIR}", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(check())

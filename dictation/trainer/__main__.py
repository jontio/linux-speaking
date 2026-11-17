"""Retrains a recogniser on sentences read aloud, on this computer's processor, and puts
the result among the app's speech models. See the package's own note for how it is run.

It goes over the sentences up to ten times, and stops sooner when the sentences it keeps
aside to judge by stop being heard better: after that it would only be learning the others
by heart. What is kept is the pass that did best on those.

It keeps notes of how far it has come (training.Job), which the app's window follows.
It can be stopped and carried on: what it has learned is kept after every pass. A file
called "stop" in its folder ends it at the next few sentences, and --resume carries on
from the last pass that was finished.
"""
import argparse
import gc
import json
import os
import shutil
import sys
import time
import traceback
import wave

import numpy as np
import torch

from .. import models, training, voicetest
from . import words as single
from .tdt import tdt_loss

RATE = 16000
PEAK, MOST_GAIN = 0.7, 60.0  # each sentence is turned up as the app turns a phrase up
MOST_TOGETHER = 24           # sentences or single words learned from at a time,
MOST_SECONDS = 26.0          # and seconds of sound: more than this wants too much memory


class Stopped(Exception):
    """The person asked for the run to stop."""


class Failed(Exception):
    """Something the person can be told about."""


def say(*parts) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def memory() -> str:
    """The most memory this run has had at once, for the log."""
    try:
        import resource
        return f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6:.1f} GB at most so far"
    except ImportError:  # Windows
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak", "now", "peak_paged", "paged", "peak_unpaged", "unpaged",
                    "page_file", "peak_page_file")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = wintypes.HANDLE
        asked = ctypes.windll.psapi.GetProcessMemoryInfo
        asked.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if asked(process(), ctypes.byref(counters), counters.cb):
            return f"{counters.peak / 1e9:.1f} GB at most so far"
        return "memory not known"


def sound_of(path: str):
    with wave.open(path, "rb") as sound:
        if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (1, 2, RATE):
            raise Failed(f"{path} is not sound of the kind that can be trained on: 16 kHz, "
                         "one channel, 16-bit.")
        samples = np.frombuffer(sound.readframes(sound.getnframes()), dtype="<i2")
    samples = samples.astype(np.float32) / 32768.0
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    return samples * min(PEAK / peak, MOST_GAIN) if peak > 0 else samples


def load(base: training.Base):
    """The model as it is published. Fetched the first time, and kept."""
    import nemo.collections.asr as nemo_asr
    from huggingface_hub import hf_hub_download
    started = time.monotonic()
    path = hf_hub_download(repo_id=base.repo, filename=base.file)
    model = nemo_asr.models.ASRModel.restore_from(restore_path=path, map_location="cpu")
    say(f"loaded in {time.monotonic() - started:.0f} s, {memory()}")
    return model


@torch.no_grad()
def hear(model, sound) -> str:
    """What the model writes for one sentence, the way it decides when not training."""
    signal = torch.from_numpy(sound).unsqueeze(0)
    encoded, lengths = model.forward(input_signal=signal, input_signal_length=torch.tensor([len(sound)]))
    best = model.decoding.rnnt_decoder_predictions_tensor(encoded, lengths)
    best = best[0] if isinstance(best, tuple) else best
    first = best[0]
    return first.text if hasattr(first, "text") else str(first)


def listen(model, data, label: str, show: int = 12) -> dict:
    """Hear every sentence and count the words wrong."""
    was = model.training
    model.eval()
    slips = total = shown = 0
    for name, sound, text in data:
        heard = hear(model, sound)
        missed = training.wrong(text, heard)
        slips += missed
        total += len(training.words(text))
        if missed and shown < show:
            shown += 1
            say(f"   {name}: {heard}")
    model.train(was)
    if was:
        prepare(model)
    say(f"{label}: {slips} wrong of {total} words in {len(data)} sentences")
    return {"wrong": slips, "words": total, "sentences": len(data), "near": None}


def prepare(model) -> None:
    """Ready the model for learning from a few sentences at a time."""
    model.train()
    for part in model.modules():  # running averages made from a handful of sentences would
        if isinstance(part, torch.nn.modules.batchnorm._BatchNorm):  # be worse than its own
            part.eval()
    model.spec_augmentation = None  # no masking of the sound: there is little of it to hide


def loss_of(model, batch, kind: str = "tdt"):
    """The training loss for some sentences: how unlikely their text is, a token. `kind`
    is the sort of model: "tdt" for one that also says how long each token lasts (Parakeet
    v2), "rnnt" for one that doesn't (Parakeet Unified)."""
    longest = max(len(sound) for _, sound, _ in batch)
    signal = torch.zeros(len(batch), longest)
    for at, (_, sound, _) in enumerate(batch):
        signal[at, :len(sound)] = torch.from_numpy(sound)
    lengths = torch.tensor([len(sound) for _, sound, _ in batch])
    tokens = [model.tokenizer.text_to_ids(text) for _, _, text in batch]
    token_lengths = torch.tensor([len(ids) for ids in tokens])
    targets = torch.zeros(len(batch), int(token_lengths.max()), dtype=torch.long)
    for at, ids in enumerate(tokens):
        targets[at, :len(ids)] = torch.tensor(ids)
    encoded, encoded_lengths = model.forward(input_signal=signal, input_signal_length=lengths)
    # No frames past the longest sentence's last: the encoder may hand back one more, and
    # the plain transducer loss won't have it.
    encoded = encoded[:, :, :int(encoded_lengths.max())]
    told, _, _ = model.decoder(targets=targets, target_length=token_lengths)
    # The joint network itself. (Called the usual way, this model's joint wants to work out
    # the loss too, with NeMo's graphics-card version of it.)
    joint = model.joint.joint(encoded.transpose(1, 2), told.transpose(1, 2))
    if kind == "rnnt":
        import torchaudio
        losses = torchaudio.functional.rnnt_loss(
            joint, targets.int(), encoded_lengths.int(), token_lengths.int(),
            blank=model.decoder.blank_idx, reduction="none")
    else:
        losses = tdt_loss(joint, targets, encoded_lengths, token_lengths,
                          blank=model.decoder.blank_idx,
                          durations=list(model.cfg.model_defaults.tdt_durations),
                          sigma=float(model.cfg.loss.tdt_kwargs.sigma))
    return losses.sum() / token_lengths.sum()


@torch.no_grad()
def loss_on(model, data, kind: str = "tdt") -> float:
    """The loss on sentences that are only looked at, a token."""
    model.eval()
    each = [float(loss_of(model, [sentence], kind)) for sentence in data]
    prepare(model)
    return sum(each) / max(1, len(each))


def together(data) -> list:
    """Which sentences are learned from at once: [[place, ...], ...]. Those of about the
    same length go together, so that little of what is worked on is padding, and never
    more sound at once than the memory will bear."""
    made, now, seconds = [], [], 0.0
    for at in sorted(range(len(data)), key=lambda at: len(data[at][1])):
        length = len(data[at][1]) / RATE
        if now and (len(now) == MOST_TOGETHER or seconds + length > MOST_SECONDS):
            made.append(now)
            now, seconds = [], 0.0
        now.append(at)
        seconds += length
    return made + ([now] if now else [])


def keep(model, path: str) -> None:
    """Write what the model has learned to `path`, whole or not at all, and without
    leaving a copy of it in memory that the run would be charged for."""
    with open(path + ".new", "wb") as f:
        torch.save(model.state_dict(), f)
        f.flush()
        os.fsync(f.fileno())
        if hasattr(os, "posix_fadvise"):
            os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    os.replace(path + ".new", path)


def measure(files: dict, test, threads: int, alone=()) -> dict:
    """Words wrong and near misses on the test sentences, for a model in the form the app
    uses, heard the way the app hears. And how many of the single words in `alone`, cut
    from those sentences, it writes right with nothing round them."""
    import sherpa_onnx
    recogniser = sherpa_onnx.OfflineRecognizer.from_transducer(
        **files, num_threads=threads or 4, model_type="nemo_transducer")
    slips = total = 0
    said, phrases = [], []
    for name, sound, text in test:
        stream = recogniser.create_stream()
        stream.accept_waveform(RATE, sound)
        recogniser.decode_stream(stream)
        result = stream.result
        slips += training.wrong(text, result.text)
        total += len(training.words(text))
        said += voicetest.words(text)
        phrases.append(voicetest.word_sureness(list(result.tokens),
                                               getattr(result, "ys_log_probs", None)))
    near = voicetest.near_misses(said, phrases)
    found = {"wrong": slips, "words": total, "sentences": len(test),
             "near": None if near is None else len(near)}
    if alone:
        right = 0
        for name, sound, text in alone:
            stream = recogniser.create_stream()
            stream.accept_waveform(RATE, sound)
            recogniser.decode_stream(stream)
            right += training.words(stream.result.text) == training.words(text)
        found.update(alone=right, alone_of=len(alone))
    return found


def run(args, job: training.Job, base: training.Base) -> None:
    torch.manual_seed(1)
    if args.threads:
        torch.set_num_threads(args.threads)
    last, best_file = os.path.join(job.folder, "last.pt"), os.path.join(job.folder, "best.pt")
    built = os.path.join(job.folder, "export")
    folder = training.model_folder(base, args.name)

    found = training.sentences(args.data)
    if len(found) < training.LEAST:
        raise Failed(f"{len(found)} sentences were found in {args.data}. At least "
                     f"{training.LEAST} are wanted: read some more, or choose another folder.")
    data = [(os.path.join(os.path.basename(os.path.dirname(path)), os.path.basename(path)),
             sound_of(path), text) for path, text in found]
    mine, check, test = ([data[at] for at in part]
                         for part in training.split_of([text for _, _, text in data]))
    minutes = sum(len(sound) for _, sound, _ in mine) / RATE / 60
    say(f"to train on: {len(mine)} sentences, {minutes:.1f} min; to choose by: {len(check)}; "
        f"to test on: {len(test)}")

    # Single words cut from the sentences, each kind from its own sentences: see words.py.
    alone, alone_check, alone_test = [], [], []
    cutter = models.transducer_files(args.models, training.CUTTER)
    if cutter:
        job.note(state="cutting", passes=args.passes, sentences=len(mine))
        alone, alone_check, alone_test = (single.cut(cutter, part, args.threads)
                                          for part in (mine, check, test))
        say(f"single words cut from them: {len(alone)} to train on, {len(alone_check)} to "
            f"choose by, {len(alone_test)} to test on")
    else:
        say(f"no single words: {training.CUTTER}, which finds where each word is, is not installed")
    mine = mine + alone

    job.note(state="fetching", passes=args.passes, sentences=len(mine) - len(alone),
             single_words=len(alone))
    model = load(base)
    odd = model.tokenizer.tokenizer.unk_id() if hasattr(model.tokenizer, "tokenizer") else 0
    odd = [name for name, _, text in data if odd in model.tokenizer.text_to_ids(text)]
    if odd:
        say("text the model has no token for, in:", odd[:10])

    notes = job.status()
    done, best, best_turn = 0, None, 0
    if args.resume and notes.get("finished") and os.path.exists(last):
        done, best, best_turn = notes["finished"], notes.get("best"), notes.get("best_pass", 0)
        model.load_state_dict(torch.load(last, map_location="cpu"))
        gc.collect()
        say(f"carrying on after pass {done} of {args.passes}")
    else:
        for path in (last, best_file):
            if os.path.exists(path):
                os.remove(path)
        job.note(state="listening", finished=0, best=None)
        job.note(heard_before=listen(model, test, "test, before"))
    prepare(model)
    for p in model.parameters():
        p.requires_grad_(False)
    # All of it learns, as a rule. "decoder" leaves out the part that hears, which is nearly
    # all of the model and of the memory a run takes: no use for a voice, but it lets the
    # whole of a run be tried on a computer without the memory for a real one.
    parts = (model.decoder, model.joint) if args.parts == "decoder" else (
        model.encoder, model.decoder, model.joint)
    numbers = [p for part in parts for p in part.parameters()]
    for p in numbers:
        p.requires_grad_(True)
    optimiser = torch.optim.AdamW(numbers, lr=args.rate, weight_decay=0.0)

    batches = together(mine)
    if args.resume and notes.get("trained") and os.path.exists(best_file):
        batches = []  # the learning was done: what is left is making the model and placing it
        say("the training was finished before: carrying on from there")
    order = np.random.default_rng(1)
    for _ in range(done):
        order.permutation(len(batches))  # the passes already done took these
    after_pass = 60.0  # seconds a pass spends on other things than learning: a first guess
    for turn in range(done + 1, args.passes + 1 if batches else 0):
        total, began = 0.0, time.monotonic()
        for count, at in enumerate(order.permutation(len(batches)), 1):
            if os.path.exists(job.stop_file):
                os.remove(job.stop_file)
                raise Stopped()
            optimiser.zero_grad(set_to_none=True)
            loss = loss_of(model, [mine[index] for index in batches[at]], base.loss)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(numbers, 1.0)
            optimiser.step()
            total += float(loss)
            del loss
            each = (time.monotonic() - began) / count * len(batches) + after_pass
            job.note(state="training", **{"pass": turn}, batch=count, batches=len(batches),
                     pass_seconds=each)
        learned = time.monotonic()
        optimiser.zero_grad(set_to_none=True)
        gc.collect()
        if check and alone_check:  # sentences and single words count alike
            chosen_by = (loss_on(model, check, base.loss) + loss_on(model, alone_check, base.loss)) / 2
        else:
            chosen_by = loss_on(model, check, base.loss) if check else total / len(batches)
        keep(model, last)
        if best is None or chosen_by < best:
            best, best_turn = chosen_by, turn
            if os.path.exists(best_file):
                os.remove(best_file)
            try:
                os.link(last, best_file)  # the same file under a second name: nothing is copied
            except OSError:
                shutil.copyfile(last, best_file)
        after_pass = time.monotonic() - learned
        say(f"pass {turn}: loss {total / len(batches):.4f} a token, to choose by {chosen_by:.4f}"
            f"{' (the best so far)' if best == chosen_by else ''}; "
            f"{(time.monotonic() - began) / 60:.1f} min, {memory()}")
        job.note(finished=turn, best=best, best_pass=best_turn)
        if check and turn - best_turn >= args.patience:
            # More passes now only learn the sentences by heart: a first run of ten was at
            # its best after two.
            say(f"no better for {args.patience} passes: it stops here, and pass {best_turn} is kept")
            break

    del optimiser, numbers
    gc.collect()
    job.note(state="exporting", trained=True)
    from .export import export
    model.load_state_dict(torch.load(best_file, map_location="cpu"))
    shutil.rmtree(built, ignore_errors=True)
    export(model, built, f"https://huggingface.co/{base.repo}")
    del model
    gc.collect()
    say("made the app's files:", {name: f"{os.path.getsize(os.path.join(built, name)) / 1e6:.0f} MB"
                                  for name in sorted(os.listdir(built))})

    job.note(state="comparing")
    after = measure(models.transducer_files(job.folder, "export"), test, args.threads, alone_test)
    stock = models.transducer_files(args.models, base.folder)
    before = (measure(stock, test, args.threads, alone_test) if stock
              else job.status().get("heard_before"))
    say("on the test sentences, as it comes:", before, "retrained:", after)

    with open(os.path.join(built, training.ABOUT), "w", encoding="utf-8") as f:
        json.dump({"name": args.name, "base": base.key, "made": time.strftime("%Y-%m-%d"),
                   "sentences": len(mine) - len(alone), "single_words": len(alone),
                   "minutes": round(minutes, 1), "passes": best_turn,
                   "before": before, "after": after}, f)
    # Into place among the speech models, all at once: the app never sees half of it.
    target = os.path.join(args.models, folder)
    os.makedirs(args.models, exist_ok=True)
    coming, going = target + ".new" + models.PART, target + ".old" + models.PART
    for path in (coming, going):
        shutil.rmtree(path, ignore_errors=True)
    try:
        if os.path.exists(target):
            os.rename(target, going)
    except OSError:
        # On Windows a model that is in use can't be moved aside. Nothing is lost: the
        # new one waits in the run's folder, and carrying on only does this step again.
        raise Failed(f"\u201c{args.name}\u201d is the model in use for dictation, so the new "
                     "one could not be put in its place. Choose another model for "
                     "dictation in Settings, then press Carry on: the training is kept.")
    shutil.move(built, coming)
    os.rename(coming, target)
    shutil.rmtree(going, ignore_errors=True)
    for path in (last, best_file):  # 2.4 GB that nothing wants any more
        if os.path.exists(path):
            os.remove(path)
    job.note(state="done", before=before, after=after, folder=folder)
    say(f"finished: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m dictation.trainer")
    parser.add_argument("--data", required=True)
    parser.add_argument("--base", required=True, choices=sorted(training.BY_KEY))
    parser.add_argument("--name", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--passes", type=int, default=10)       # at most
    parser.add_argument("--patience", type=int, default=2)      # passes without getting better
    parser.add_argument("--rate", type=float, default=1e-5)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--parts", default=os.environ.get("LS_TRAIN_PARTS", "all"),
                        choices=("all", "decoder"))  # for trying a run: see run()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    job, base = training.Job(args.job), training.BY_KEY[args.base]
    job.note(pid=os.getpid(), state="starting", passes=args.passes, error="", name=args.name,
             base=base.key, data=args.data, folder=training.model_folder(base, args.name))
    say(f"== {'carrying on' if args.resume else 'started'}: {args.name}, from {base.label}, "
        f"on {args.data}")
    try:
        run(args, job, base)
    except Stopped:
        say("stopped, as asked")
        job.note(state="stopped")
        return 3
    except Failed as e:
        say("could not go on:", e)
        job.note(state="failed", error=str(e))
        return 1
    except BaseException as e:  # whatever it is, the window is told
        traceback.print_exc()
        sys.stdout.flush()
        job.note(state="failed", error=f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

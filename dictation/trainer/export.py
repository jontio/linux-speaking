"""Turns a retrained model into the files the app reads, the way the sherpa-onnx project
makes the ones it publishes (its scripts/nemo/parakeet-tdt-0.6b-v2/export_onnx.py). The
notes written into the encoder's file are those of its builds of Parakeet v2 and of
Parakeet Unified, which differ only in what they are worked out from."""
import os

import torch


def _add_meta_data(filename: str, meta_data: dict) -> None:
    import onnx
    model = onnx.load(filename)
    while len(model.metadata_props):
        model.metadata_props.pop()
    for key, value in meta_data.items():
        meta = model.metadata_props.add()
        meta.key = key
        meta.value = str(value)
    onnx.save(model, filename)


@torch.no_grad()
def export(model, out: str, url: str) -> None:
    """Make the 8-bit build of `model` in the folder `out`."""
    from onnxruntime.quantization import QuantType, quantize_dynamic
    model.eval()
    os.makedirs(out, exist_ok=True)
    here = os.getcwd()
    os.chdir(out)  # the parts are written beside one another, by name
    try:
        with open("tokens.txt", "w", encoding="utf-8") as f:
            for i, s in enumerate(model.joint.vocabulary):
                f.write(f"{s} {i}\n")
            f.write(f"<blk> {i + 1}\n")
        model.encoder.export("encoder.onnx")
        model.decoder.export("decoder.onnx")
        model.joint.export("joiner.onnx")
        normalize_type = model.cfg.preprocessor.normalize
        meta_data = {
            "vocab_size": model.decoder.vocab_size,
            "normalize_type": "" if normalize_type == "NA" else normalize_type,
            "pred_rnn_layers": model.decoder.pred_rnn_layers,
            "pred_hidden": model.decoder.pred_hidden,
            "subsampling_factor": 8,
            "model_type": "EncDecRNNTBPEModel",
            "version": "2",
            "model_author": "NeMo",
            "url": url,
            "comment": "Only the transducer branch is exported",
            "feat_dim": 128,
        }
        for part in ("encoder", "decoder", "joiner"):
            quantize_dynamic(model_input=f"{part}.onnx", model_output=f"{part}.int8.onnx",
                             weight_type=QuantType.QUInt8 if part == "encoder" else QuantType.QInt8)
        _add_meta_data("encoder.int8.onnx", meta_data)
        for name in os.listdir("."):  # only the 8-bit build is kept
            if not name.endswith(".int8.onnx") and name != "tokens.txt":
                os.remove(name)
    finally:
        os.chdir(here)

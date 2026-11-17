#!/usr/bin/env bash
# Installs the tools for retraining a speech model to your voice ("Train on my voice" in
# Settings): a Python of their own with PyTorch and NeMo, about 2 GB, all of it in
# ~/linux-speaking/training. Nothing else on the computer is changed, and removing that
# folder removes them. Linux only. The computer wants about 16 GB of memory or more.
#   LS_TRAINING_DIR=/somewhere/else   to keep them in another folder
set -euo pipefail
dir="${LS_TRAINING_DIR:-${LS_INSTALL_DIR:-$HOME/linux-speaking}/training}"
mkdir -p "$dir"
cd "$dir"
export UV_PYTHON_INSTALL_DIR="$dir/python" UV_CACHE_DIR="$dir/cache"
echo "== Installing the training tools into $dir (about 2 GB)"
if [ ! -x boot/bin/uv ]; then
  python3 -m venv boot
  boot/bin/pip install --quiet uv
fi
# NeMo wants a Python older than the newest: this fetches one for it alone.
[ -x venv/bin/python ] || boot/bin/uv venv --python 3.12 venv
boot/bin/uv pip install --python venv/bin/python torch torchaudio \
  --index-url https://download.pytorch.org/whl/cpu
boot/bin/uv pip install --python venv/bin/python "nemo_toolkit[asr]" onnx onnxruntime sherpa-onnx
venv/bin/python -c "import torch, nemo; print('PyTorch', torch.__version__, '| NeMo', nemo.__version__)"
rm -rf "$dir/cache"
echo "== Done. Open Settings and press \"Train on my voice\"."

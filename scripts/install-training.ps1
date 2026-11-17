# Installs the tools for retraining a speech model to your voice ("Train on my voice" in
# Settings): a Python of their own with PyTorch and NeMo, about 2 GB, all of it in the
# "training" folder beside the app. Nothing else on the computer is changed, and removing
# that folder removes them. A run wants about 14 GB of free memory.
#   $env:LS_TRAINING_DIR = 'D:\somewhere'   to keep them in another folder
$ErrorActionPreference = 'Stop'
$install = if ($env:LS_INSTALL_DIR) { $env:LS_INSTALL_DIR } else { Join-Path $env:USERPROFILE 'linux-speaking' }
$dir = if ($env:LS_TRAINING_DIR) { $env:LS_TRAINING_DIR } else { Join-Path $install 'training' }

function Run {
    # A program's failure is this script's failure: nothing is left half done unsaid. What
    # it writes as a warning is not one: Windows PowerShell would take that for an error.
    $program = $args[0]
    $rest = $args[1..($args.Count - 1)]
    $ErrorActionPreference = 'Continue'
    & $program @rest 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw "$program failed ($LASTEXITCODE)" }
}

trap { Write-Output "== The install did not finish: $_"; exit 1 }
New-Item -ItemType Directory -Force $dir | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $dir 'python'
$env:UV_CACHE_DIR = Join-Path $dir 'cache'
Write-Output "== Installing the training tools into $dir (about 2 GB)"
$uv = Join-Path $dir 'boot\Scripts\uv.exe'
if (-not (Test-Path $uv)) {
    Run (Join-Path $install 'venv\Scripts\python.exe') -m venv (Join-Path $dir 'boot')
    Run (Join-Path $dir 'boot\Scripts\python.exe') -m pip install --quiet uv
}
# NeMo wants its own version of Python: this fetches one for it alone.
$python = Join-Path $dir 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { Run $uv venv --python 3.12 (Join-Path $dir 'venv') }
Write-Output '== PyTorch'
Run $uv pip install --python $python torch torchaudio --index-url https://download.pytorch.org/whl/cpu
Write-Output '== NeMo and the rest'
Run $uv pip install --python $python 'nemo_toolkit[asr]' onnx onnxruntime sherpa-onnx
Run $python -c "import torch, nemo; print('PyTorch', torch.__version__, '| NeMo', nemo.__version__)"
Remove-Item -Recurse -Force (Join-Path $dir 'cache') -ErrorAction SilentlyContinue
Write-Output '== Done. Open Settings and press "Train on my voice".'

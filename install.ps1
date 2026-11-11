# Installs or updates Linux Speaking on Windows, for dictating into Microsoft Word,
# classic Outlook and Visual Studio Code.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Everything goes in one folder, %USERPROFILE%\linux-speaking, and nothing needs
# administrator rights. Options, as environment variables:
#   LS_INSTALL_DIR       where to install
#   LS_SKIP_PACKAGES=1   don't install or update the Python packages
#   LS_SKIP_MODELS=1     don't download the speech models
#   LS_NO_AUTOSTART=1    don't start it when you sign in
#   LS_NO_START=1        don't start it now
$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = if ($env:LS_INSTALL_DIR) { $env:LS_INSTALL_DIR } else { Join-Path $env:USERPROFILE "linux-speaking" }
function Say($text) { Write-Host "`n== $text" }

# ---- Python --------------------------------------------------------------------------
$python = $null
foreach ($try in @(@("py", "-3"), @("python"), @("python3"))) {
    try {
        $version = & $try[0] $try[1..9] -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
        if ($version -eq "True") { $python = $try; break }
    } catch { }
}
if (-not $python) {
    Write-Host "Python 3.9 or newer is needed. Install it from the Microsoft Store or python.org, then run this again."
    exit 1
}

# ---- the program ---------------------------------------------------------------------
Say "Installing into $dir"
# Stop a copy that is running, so its files can be replaced.
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*dictation.tray*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $dir, "$dir\app", "$dir\models" | Out-Null
foreach ($folder in "dictation", "scripts", "vscode") {
    robocopy (Join-Path $source $folder) "$dir\app\$folder" /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "could not copy $folder" }
}
Copy-Item (Join-Path $source "LICENSE") "$dir\app\LICENSE" -Force
$py = "$dir\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { & $python[0] $python[1..9] -m venv "$dir\venv" }
if ($env:LS_SKIP_PACKAGES -ne "1") {
    Say "Installing the Python packages (the first time, this downloads about 200 MB)"
    & $py -m pip install --quiet --disable-pip-version-check --upgrade faster-whisper numpy PyQt6 sounddevice pywin32 comtypes
    if ($LASTEXITCODE -ne 0) { throw "pip could not install the packages" }
}

# ---- the speech models -----------------------------------------------------------------
if ($env:LS_SKIP_MODELS -ne "1") {
    Say "Downloading the speech models (about 650 MB, once)"
    $fetch = @'
import os, sys
from huggingface_hub import snapshot_download
for name in ("base.en", "small.en"):
    target = os.path.join(sys.argv[1], name)
    if os.path.exists(os.path.join(target, "model.bin")):
        continue
    print("  " + name, flush=True)
    snapshot_download("Systran/faster-whisper-" + name, local_dir=target,
                      allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"])
'@
    $fetch | & $py - "$dir\models"
    if ($LASTEXITCODE -ne 0) { throw "the speech models could not be downloaded" }
}

# ---- shortcuts ---------------------------------------------------------------------------
Say "Adding Linux Speaking to the Start menu"
$env:LS_INSTALL_DIR = $dir
Push-Location "$dir\app"
& $py -m dictation.tray --write-icon "$dir\linux-speaking.ico"
Pop-Location
$shell = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath("Programs")
$startup = [Environment]::GetFolderPath("Startup")
$places = @("$programs\Linux Speaking.lnk")
if ($env:LS_NO_AUTOSTART -ne "1") { $places += "$startup\Linux Speaking.lnk" }
else { Remove-Item "$startup\Linux Speaking.lnk" -ErrorAction SilentlyContinue }
foreach ($place in $places) {
    $link = $shell.CreateShortcut($place)
    $link.TargetPath = "$dir\venv\Scripts\pythonw.exe"
    $link.Arguments = "-m dictation.tray"
    $link.WorkingDirectory = "$dir\app"
    $link.IconLocation = "$dir\linux-speaking.ico"
    $link.Description = "Voice dictation"
    $link.Save()
}

# ---- Visual Studio Code --------------------------------------------------------------------
& $py "$dir\app\scripts\build_vsix.py" "$dir\linux-speaking.vsix" | Out-Null
$code = Get-Command code -ErrorAction SilentlyContinue
if ($code) {
    Say "Adding the Visual Studio Code extension"
    & $code.Source --install-extension "$dir\linux-speaking.vsix" --force | Out-Null
    Write-Host "Restart Visual Studio Code, or run 'Developer: Reload Window' in it, to load the extension."
} else {
    Write-Host "Visual Studio Code wasn't found. To add it later: code --install-extension $dir\linux-speaking.vsix"
}

if ($env:LS_NO_START -ne "1") {
    Say "Starting Linux Speaking"
    Start-Process "$dir\venv\Scripts\pythonw.exe" -ArgumentList "-m", "dictation.tray" -WorkingDirectory "$dir\app"
}
Write-Host @"

Done. Look for the microphone icon near the clock. Windows may tuck it behind the
little arrow there: drag it out onto the taskbar to keep it in view.

It is purple while the speech models load, then orange: asleep. Click into a Word
document, an Outlook message you are writing, or a file in Visual Studio Code, say
"wake up", and talk. Say "go to sleep" to stop. Right-click the icon for Settings.
"@

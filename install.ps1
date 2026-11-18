# Installs or updates Linux Speaking on Windows 10 and 11, for dictating into Microsoft
# Word, classic Outlook, Visual Studio Code and, with a setting, any other program's text
# boxes. Dictation and its commands are in English only.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# It wants a 64-bit Python, 3.10 to 3.14, already installed (python.org or the Microsoft
# Store). Everything goes in one folder, %USERPROFILE%\linux-speaking, and nothing needs
# administrator rights. To update, get the new version and run this again. To remove it,
# use "Uninstall Linux Speaking" in the Start menu, which runs the uninstall.ps1 that is
# copied into that folder.
#
# Options, as environment variables. In PowerShell one is set like this, before the line
# above:    $env:LS_NO_AUTOSTART = "1"
#   LS_INSTALL_DIR       where to install: a folder of its own
#   LS_PYTHON            the Python to build on: the full path of its python.exe, or a
#                        version for the "py" launcher, such as 3.12
#   LS_SKIP_PACKAGES=1   don't install or update the Python packages
#   LS_SKIP_MODELS=1     don't download the speech models
#   LS_NO_AUTOSTART=1    don't start it when you sign in (0 puts that back; left unset, an
#                        update keeps what was chosen before)
#   LS_NO_START=1        don't start it now
$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = if ($env:LS_INSTALL_DIR) { $env:LS_INSTALL_DIR } else { Join-Path $env:USERPROFILE "linux-speaking" }
function Say($text) { Write-Host "`n== $text" }
function Stop-Here {
    # The lines it is given, and no more: nothing is left half done unsaid.
    foreach ($line in $args) { Write-Host $line }
    exit 1
}

if ($ExecutionContext.SessionState.LanguageMode -ne "FullLanguage") {
    Stop-Here "This PC lets PowerShell run only in a restricted mode, which its administrator has" `
        "set. The installer can't make its shortcuts in that mode, so it has stopped before" `
        "changing anything."
}

# ---- where it goes -------------------------------------------------------------------------
$dir = [IO.Path]::GetFullPath($dir).TrimEnd('\')
$source = [IO.Path]::GetFullPath($source).TrimEnd('\')
$ownCopy = ($source -eq "$dir\app")    # run again from the copy an install keeps
# A download or clone made in the user folder under the project's own name is the very
# folder this installs into: the program would be copied into itself.
if (-not $ownCopy -and ($source -eq $dir -or
        $source.StartsWith($dir + "\", [StringComparison]::OrdinalIgnoreCase))) {
    Stop-Here "This folder is $source," `
        "and Linux Speaking installs itself into $dir." `
        "Installing from here would copy the program into itself. Rename or move this folder" `
        "(to linux-speaking-source, say) and run the installer again from there. Or install" `
        "into another folder of its own, by typing this first:" `
        "  `$env:LS_INSTALL_DIR = `"$env:USERPROFILE\apps\linux-speaking`""
}
# A folder that already holds other things is not taken over: the program wants one to
# itself. (What an install of its own leaves there is no such thing.)
$ours = @("app", "venv", "models", "training", "dictionaries", "state", "settings.json",
          "settings.json.new", "mail-key", "linux-speaking.ico", "linux-speaking.vsix", "uninstall.ps1")
if ((Test-Path -LiteralPath $dir) -and -not (Test-Path -LiteralPath "$dir\app\dictation")) {
    $others = @(Get-ChildItem -LiteralPath $dir -Force | Where-Object { $ours -notcontains $_.Name })
    if ($others.Count -gt 0) {
        Stop-Here "$dir is a folder with other things in it, and not an earlier install." `
            "Linux Speaking wants a folder of its own. Name one that doesn't exist yet, by typing" `
            "this first:" `
            "  `$env:LS_INSTALL_DIR = `"$dir\linux-speaking`""
    }
}

# ---- Python --------------------------------------------------------------------------
# The packages it runs on are made for 64-bit Intel and AMD processors, and for a few
# versions of Python at a time. Anything else ends in a wall of errors from pip, so it is
# turned away here, in plain words.
$oldest = 10
$newest = 14
function Probe($command) {
    # What a Python says of itself: "3;12;win-amd64;C:\...\python.exe". Nothing if it doesn't run.
    $code = "import sys, sysconfig; print(sys.version_info[0], sys.version_info[1], sysconfig.get_platform(), sys.executable, sep=';')"
    $command = @($command)
    $program = $command[0]
    $rest = @()
    if ($command.Count -gt 1) { $rest = @($command[1..($command.Count - 1)]) }
    $said = $null
    $before = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $said = & $program @rest -c $code 2>$null
        if ($LASTEXITCODE -ne 0) { $said = $null }
    } catch { $said = $null }
    $ErrorActionPreference = $before
    foreach ($line in @($said)) {
        if ("$line" -match '^\d+;\d+;[^;]+;.') { return "$line" }
    }
    return $null
}
function Wrong($parts) {
    # Why this Python won't do, or nothing if it will.
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($parts[2] -eq "win32") { return "it is a 32-bit Python" }
    if ($parts[2] -eq "win-arm64") { return "it is a Python for ARM processors" }
    if ($parts[2] -ne "win-amd64") { return "it is not a 64-bit Python for Windows on Intel and AMD processors (it calls itself $($parts[2]))" }
    if ($major -ne 3 -or $minor -lt $oldest) { return "it is too old" }
    if ($minor -gt $newest) { return "it is newer than Linux Speaking has been tried with" }
    return $null
}
$candidates = @()
if ($env:LS_PYTHON) {
    if ($env:LS_PYTHON -match '^\d+(\.\d+)?$') { $candidates += , @("py", "-$($env:LS_PYTHON)") }
    else { $candidates += , @($env:LS_PYTHON) }
} else {
    # The newest that has been tried comes first; "py -3" alone would take the newest
    # there is, which may be newer than the packages are made for.
    foreach ($minor in $newest..$oldest) { $candidates += , @("py", "-3.$minor") }
    $candidates += , @("py", "-3")
    $candidates += , @("python")
    $candidates += , @("python3")
}
$python = $null
$turnedAway = @()
foreach ($candidate in $candidates) {
    $said = Probe $candidate
    if (-not $said) { continue }
    $parts = $said -split ';', 4
    $why = Wrong $parts
    if (-not $why) {
        $python = $parts[3]
        Write-Host "Using Python $($parts[0]).$($parts[1]) ($python)"
        break
    }
    $line = "  Python $($parts[0]).$($parts[1]) at $($parts[3]): $why"
    if ($turnedAway -notcontains $line) { $turnedAway += $line }
}
if (-not $python) {
    $wanted = "a 64-bit Python (for Intel and AMD processors), version 3.$oldest to 3.$newest"
    if ($env:LS_PYTHON -and $turnedAway.Count -eq 0) {
        Stop-Here "LS_PYTHON is set to $($env:LS_PYTHON), and no Python answers there." `
            "Give the full path of a python.exe, or a version for the py launcher, such as 3.12."
    }
    if ($turnedAway.Count -eq 0) {
        Stop-Here "Python wasn't found. Linux Speaking needs $wanted." `
            "Install one from python.org (the `"Windows installer (64-bit)`") or from the Microsoft" `
            "Store, then run this again. Nothing has been changed."
    }
    Write-Host "No Python on this PC will do. Found:"
    foreach ($line in $turnedAway) { Write-Host $line }
    Stop-Here "Linux Speaking needs $wanted." `
        "Install one from python.org (the `"Windows installer (64-bit)`") beside what is here, then" `
        "run this again. If there is one this didn't find, say where, by typing this first:" `
        "  `$env:LS_PYTHON = `"C:\path\to\python.exe`"" `
        "Nothing has been changed."
}

# ---- the program ---------------------------------------------------------------------
Say "Installing into $dir"
$update = Test-Path -LiteralPath "$dir\app\dictation"
# Stop a copy that is running, so its files can be replaced, and wait until it has gone.
$running = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*dictation.tray*" })
foreach ($one in $running) { Stop-Process -Id $one.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($one in $running) { Wait-Process -Id $one.ProcessId -Timeout 15 -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $dir, "$dir\app", "$dir\models" | Out-Null

# Outside your own user folder, a new folder takes its permissions from the drive, and
# those usually let the PC's other accounts read what is in it, and often change it. In
# it are your settings (with the keys for another computer), your recordings and the
# program itself, and a changed program would run as you. So it is closed to them.
$userFolder = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
if (-not $dir.StartsWith($userFolder + "\", [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "This folder is outside your own user folder, so it is being closed to the other"
    Write-Host "accounts on this PC: only you, and the PC's administrators, will be able to open it."
    $closed = $false
    try {
        $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        # By their numbers, which are the same in every language of Windows: you, the
        # system, the administrators. Then: authenticated users, users, everyone.
        & icacls.exe $dir /inheritance:r /grant:r "*${me}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & icacls.exe $dir /remove:g "*S-1-5-11" "*S-1-5-32-545" "*S-1-1-0" | Out-Null
            $closed = ($LASTEXITCODE -eq 0)
        }
    } catch { $closed = $false }
    if (-not $closed) {
        Write-Host ""
        Write-Host "WARNING: the folder could not be closed to other accounts. (A drive such as a USB"
        Write-Host "stick keeps no permissions at all.) Anyone else who uses this PC may be able to read"
        Write-Host "your settings and recordings there, and to change the program that runs as you."
        Write-Host "To be safe, install into your user folder instead: stop this with Ctrl+C, and run"
        Write-Host "it again without LS_INSTALL_DIR."
        Write-Host ""
    }
}

if (-not $ownCopy) {
    foreach ($folder in "dictation", "scripts", "vscode") {
        robocopy (Join-Path $source $folder) "$dir\app\$folder" /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "could not copy $folder" }
    }
    Copy-Item -LiteralPath (Join-Path $source "LICENSE") -Destination "$dir\app\LICENSE" -Force
    Copy-Item -LiteralPath (Join-Path $source "requirements.txt") -Destination "$dir\app\requirements.txt" -Force
}
# The uninstaller stays with the install, so that it is still there when the folder this
# was installed from has long been deleted.
if (Test-Path -LiteralPath (Join-Path $source "uninstall.ps1")) {
    Copy-Item -LiteralPath (Join-Path $source "uninstall.ps1") -Destination "$dir\uninstall.ps1" -Force
}

# The install's own Python. One that no longer runs (the Python it was made from has been
# removed or replaced), or that would be turned away above, is made again from nothing.
$py = "$dir\venv\Scripts\python.exe"
if (Test-Path -LiteralPath "$dir\venv") {
    $said = Probe @($py)
    $why = "it no longer runs"
    if ($said) { $why = Wrong ($said -split ';', 4) }
    if ($why) {
        Write-Host "The Python this install was set up with won't do any more ($why)."
        Write-Host "Setting it up again from nothing."
        Remove-Item -LiteralPath "$dir\venv" -Recurse -Force
    }
}
if (-not (Test-Path -LiteralPath $py)) {
    & $python -m venv "$dir\venv"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $py)) {
        Stop-Here "Python could not make the install's own copy of itself in $dir\venv." `
            "The lines above say why."
    }
}
if ($env:LS_SKIP_PACKAGES -ne "1") {
    Say "Installing the Python packages (the first time, this downloads about 200 MB)"
    # The list of packages and versions is requirements.txt, which install.sh uses too.
    & $py -m pip install --disable-pip-version-check --upgrade -r "$dir\app\requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        Stop-Here "" `
            "The Python packages could not be installed: the lines above say why. If it was the" `
            "connection, run this again and it carries on. If a package `"could not be found`" or" `
            "`"failed to build`", there may be none made yet for this version of Python: install" `
            "Python 3.12 beside it and run this again, or open an issue with those lines."
    }
}

# ---- the speech models -----------------------------------------------------------------
# Fetched with the app's own downloader, which goes through Windows' proxy settings and
# certificates, checks what arrives, and carries on from where it stopped.
if ($env:LS_SKIP_MODELS -ne "1") {
    Say "Downloading the speech models (about 650 MB, once)"
    & $py "$dir\app\scripts\fetch_models.py" "$dir\models"
    if ($LASTEXITCODE -ne 0) { exit 1 }    # it has said why, and what to do
}

$env:LS_INSTALL_DIR = $dir
Push-Location -LiteralPath "$dir\app"
Say "Checking that speech recognition loads (ten seconds or so)"
& $py "scripts\check_install.py"
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }    # it has said what is wrong

# ---- shortcuts ---------------------------------------------------------------------------
Say "Adding Linux Speaking to the Start menu"
& $py -m dictation.tray --write-icon "$dir\linux-speaking.ico"

# Windows has no dictionary of its own that the program can read. It uses one to tell a
# name from an ordinary word, so that "Feeling" in the middle of a sentence loses its capital.
New-Item -ItemType Directory -Force -Path "$dir\dictionaries" | Out-Null
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
foreach ($name in "en_GB.dic", "en_US.dic") {
    if (-not (Test-Path -LiteralPath "$dir\dictionaries\$name")) {
        try {
            Invoke-WebRequest -UseBasicParsing -OutFile "$dir\dictionaries\$name" `
                "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/$name"
        } catch {
            Write-Host "Could not fetch the $name dictionary. Capitals in the middle of a sentence will be less well judged."
        }
    }
}
Pop-Location
$shell = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath("Programs")
$startup = [Environment]::GetFolderPath("Startup")
$menuLink = "$programs\Linux Speaking.lnk"
$startLink = "$startup\Linux Speaking.lnk"
$removeLink = "$programs\Uninstall Linux Speaking.lnk"
# Starting at sign-in is a shortcut in the Startup folder, which "Start when I sign in"
# in Settings adds and removes too. A new install gets it. An update leaves the choice as
# it finds it: a shortcut that was taken away is not put back.
$autostart = "yes"
if ($env:LS_NO_AUTOSTART -eq "1") { $autostart = "no" }
elseif ($env:LS_NO_AUTOSTART -eq "0") { $autostart = "yes" }
elseif ((Test-Path -LiteralPath $menuLink) -and -not (Test-Path -LiteralPath $startLink)) { $autostart = "kept off" }
$places = @($menuLink)
if ($autostart -eq "yes") { $places += $startLink }
else { Remove-Item -LiteralPath $startLink -ErrorAction SilentlyContinue }
foreach ($place in $places) {
    $link = $shell.CreateShortcut($place)
    $link.TargetPath = "$dir\venv\Scripts\pythonw.exe"
    $link.Arguments = "-m dictation.tray"
    $link.WorkingDirectory = "$dir\app"
    $link.IconLocation = "$dir\linux-speaking.ico"
    $link.Description = "Voice dictation"
    $link.Save()
}
if (Test-Path -LiteralPath "$dir\uninstall.ps1") {
    $link = $shell.CreateShortcut($removeLink)
    $link.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$dir\uninstall.ps1`" -Pause"
    $link.WorkingDirectory = $env:USERPROFILE
    $link.IconLocation = "$dir\linux-speaking.ico"
    $link.Description = "Remove Linux Speaking from this PC"
    $link.Save()
}

# ---- Visual Studio Code --------------------------------------------------------------------
& $py "$dir\app\scripts\build_vsix.py" "$dir\linux-speaking.vsix" | Out-Null
$vsix = "$dir\linux-speaking.vsix"
$editors = @()
$editorsFailed = @()
foreach ($name in "code", "code-insiders", "codium") {
    $editor = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $editor) { continue }
    Say "Adding the Visual Studio Code extension ($name)"
    $said = ""
    $worked = $false
    $before = $ErrorActionPreference
    $ErrorActionPreference = "Continue"    # what it writes as a warning is not a failure
    try {
        $said = (& $editor.Source --install-extension $vsix --force 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $worked = ($LASTEXITCODE -eq 0)
    } catch { $said = "$_" }
    $ErrorActionPreference = $before
    if ($worked) {
        $editors += $name
        Write-Host "Added. If it is open, restart it, or run `"Developer: Reload Window`" in it."
    } else {
        $editorsFailed += $name
        Write-Host "The extension could not be added to ${name}:"
        Write-Host $said
        Write-Host "To try by hand:  $name --install-extension `"$vsix`""
    }
}
if ($editors.Count -eq 0 -and $editorsFailed.Count -eq 0) {
    Write-Host "Visual Studio Code wasn't found. To add its extension later:"
    Write-Host "  code --install-extension `"$vsix`""
}

$started = $false
if ($env:LS_NO_START -ne "1") {
    Say "Starting Linux Speaking"
    Start-Process "$dir\venv\Scripts\pythonw.exe" -ArgumentList "-m", "dictation.tray" -WorkingDirectory "$dir\app"
    $started = $true
}

# ---- what was done, and what to do next ------------------------------------------------------
Write-Host ""
Write-Host "Done. Linux Speaking is installed in $dir."
Write-Host ""
if ($started) {
    Write-Host "It is running: look for the microphone icon near the clock. Windows may tuck it"
    Write-Host "behind the little arrow there: drag it out onto the taskbar to keep it in view."
    Write-Host "It is purple while the speech models load, then orange: asleep, and listening only"
    Write-Host "for `"wake up`"."
    if (-not $update) {
        Write-Host ""
        Write-Host "A welcome window opens this first time. It shows whether the microphone hears you,"
        Write-Host "has a box to try dictating into, a button that fetches Parakeet Unified (the"
        Write-Host "recommended speech model), and asks which key, if any, should switch dictation on"
        Write-Host "and off, and whether to start when you sign in."
    }
} else {
    Write-Host "It has not been started. Start it from the Start menu: Linux Speaking."
    if ($running.Count -gt 0) { Write-Host "(It was running, and was stopped so that it could be updated.)" }
}
if ($autostart -eq "yes") { Write-Host "It will start by itself when you sign in. `"Start when I sign in`" in Settings changes that." }
elseif ($autostart -eq "no") { Write-Host "It will not start when you sign in. `"Start when I sign in`" in Settings changes that." }
else {
    Write-Host "It was set not to start when you sign in, and that has been kept. `"Start when I"
    Write-Host "sign in`" in Settings changes it."
}
Write-Host ""
Write-Host "To dictate, click into a Word document, an Outlook message you are writing (classic"
Write-Host "Outlook), or a file in Visual Studio Code. Say `"wake up`", and talk. Say `"go to sleep`""
Write-Host "to stop. Dictation and its commands are in English only."
Write-Host ""
Write-Host "For any other program (Notepad, a box in a web page, the new Outlook), tick `"Dictate"
Write-Host "into other programs' text boxes`" in Settings first. Without it, nothing is typed there."
if ($editors.Count -gt 0) { Write-Host "Visual Studio Code ($($editors -join ', ')): restart it before the first try." }
if ($editorsFailed.Count -gt 0) { Write-Host "Visual Studio Code ($($editorsFailed -join ', ')) is NOT set up: its extension could not be added (see above)." }
Write-Host ""
Write-Host "Right-click the icon for `"What can I say?`", the microphone level, and Settings."
Write-Host "To remove it all later: `"Uninstall Linux Speaking`" in the Start menu."

# Installs or updates Linux Speaking on Windows 10 and 11, for dictating into Microsoft
# Word, classic Outlook, Visual Studio Code and, with a setting, any other program's text
# boxes. Dictation and its commands are in English only.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# It runs on a 64-bit Python, 3.10 to 3.14 (from python.org or the Microsoft Store). On a
# PC that has none that will do, it offers to fetch one for itself alone, into its own
# folder. Everything goes in one folder, %USERPROFILE%\linux-speaking, and nothing needs
# administrator rights. To update, get the new version and run this again. To remove it,
# use "Uninstall Linux Speaking" in the Start menu, which runs the uninstall.ps1 that is
# copied into that folder.
#
# Options, as environment variables. In PowerShell one is set like this, before the line
# above:    $env:LS_NO_AUTOSTART = "1"
#   LS_INSTALL_DIR       where to install: a folder of its own
#   LS_PYTHON            the Python to build on: the full path of its python.exe, or a
#                        version for the "py" launcher, such as 3.12
#   LS_FETCH_PYTHON=1    if no Python on the PC will do, fetch one for Linux Speaking alone,
#                        and don't ask (0: don't fetch one, and don't ask)
#   LS_SKIP_PACKAGES=1   don't install or update the Python packages
#   LS_SKIP_MODELS=1     don't download the speech models, and don't ask: for a small
#                        computer that leaves the recognising to another one (0: download
#                        them, and don't ask)
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
$ours = @("app", "venv", "python", "python.new", "models", "training", "dictionaries", "state", "settings.json",
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

# ---- the speech models: to fetch them, or not ----------------------------------------------
# Recognising speech on this computer needs speech models, about 650 MB of them. A PC that
# is short of space, or slow, can do without and leave the recognising to another one. So
# a new install asks, here at the start, before the long steps. What was answered is kept,
# in a note in the models folder, so that an update doesn't ask again. LS_SKIP_MODELS
# answers for somebody who isn't there to be asked: 1 for no, 0 for yes.
$leftOut = "$dir\models\left-out.txt"
function Ask-AboutModels {
    Write-Host ""
    Write-Host "== Speech models"
    Write-Host "To recognise speech, this PC needs speech models. Two are downloaded now:"
    Write-Host "about 650 MB."
    Write-Host ""
    Write-Host "A PC that is short of disk space, or slow, can do without them, and have another"
    Write-Host "computer of yours do the recognising. Models can also be added later, from"
    Write-Host "Settings."
    Write-Host ""
    while ($true) {
        $answer = ([string](Read-Host "Download the speech models now? [Y/n]")).Trim().ToLower()
        if ($answer -eq "" -or $answer -eq "y" -or $answer -eq "yes") { return $true }
        if ($answer -eq "n" -or $answer -eq "no") { return $false }
        Write-Host "Please answer y for yes, or n for no."
    }
}
$someoneToAsk = $false
try { $someoneToAsk = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected } catch { }
if ($env:LS_SKIP_MODELS -eq "1") { $skipModels = $true }             # said outright
elseif ($env:LS_SKIP_MODELS -eq "0") { $skipModels = $false }
elseif (Test-Path -LiteralPath "$dir\models\small.en\model.bin") { $skipModels = $false }   # here already
elseif (Test-Path -LiteralPath $leftOut) {
    $skipModels = $true
    Write-Host "No speech models are downloaded: that is what was chosen when this was installed."
    Write-Host "(To have them after all: `"Install or remove models`" in Settings.)"
}
elseif ($someoneToAsk) {
    $skipModels = -not (Ask-AboutModels)
    if ($skipModels) { Write-Host "They are left out. The end of this says what to do next." }
}
else { $skipModels = $false }                                         # nobody to ask: as it always was

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

# A PC with no Python that will do can be given one for Linux Speaking alone: the Python
# Software Foundation's own plain-files build, which it publishes as the "python" package
# on nuget.org. It is unpacked into the install folder and nothing else on the PC is
# touched: no registry, no PATH, no "py" launcher. A Python that is already here stays as
# it is, which running python.org's installer beside an old one doesn't promise. The
# uninstaller takes it away with the rest.
$ownPython = "$dir\python"
$fetchMinor = 14    # the newest that the packages have been tried with: it is still given fixes
$pythonFeed = "https://api.nuget.org/v3-flatcontainer/python"
function Open-Web($url) {
    # Through Windows' own proxy settings, as whoever is signed in. Only the request is sent.
    $request = [Net.WebRequest]::Create($url)
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 60000
    try { if ($request.Proxy) { $request.Proxy.Credentials = [Net.CredentialCache]::DefaultCredentials } } catch { }
    return $request.GetResponse()
}
function Get-OwnPython {
    # Fetches it into $ownPython. If it can't, it throws the reason in plain words, having
    # left nothing of its own behind: one that was there before is still there.
    $new = "$ownPython.new"
    $package = Join-Path $env:TEMP "linux-speaking-python-$PID.zip"
    $doing = "The list of Python versions could not be read from nuget.org"
    try {
        if (Test-Path -LiteralPath $new) { Remove-Item -LiteralPath $new -Recurse -Force }
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
        # Which one: the newest 3.$fetchMinor that is finished. (An alpha, a beta or a
        # release candidate has more after its number, and is passed over.)
        $response = Open-Web "$pythonFeed/index.json"
        try {
            $reader = New-Object IO.StreamReader($response.GetResponseStream())
            $listed = ($reader.ReadToEnd() | ConvertFrom-Json).versions
        } finally { $response.Close() }
        $patch = -1
        foreach ($one in @($listed)) {
            if ("$one" -match "^3\.$fetchMinor\.(\d+)$") { $patch = [Math]::Max($patch, [int]$Matches[1]) }
        }
        if ($patch -lt 0) { throw "it lists no Python 3.$fetchMinor" }
        $version = "3.$fetchMinor.$patch"

        $doing = "Python $version could not be downloaded from nuget.org"
        Write-Host "Downloading Python $version"
        $response = Open-Web "$pythonFeed/$version/python.$version.nupkg"
        try {
            $length = $response.ContentLength
            $from = $response.GetResponseStream()
            $to = [IO.File]::Create($package)
            try {
                $buffer = New-Object byte[] 262144
                $got = 0
                $shown = [DateTime]::UtcNow
                while (($count = $from.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $to.Write($buffer, 0, $count)
                    $got += $count
                    if (([DateTime]::UtcNow - $shown).TotalSeconds -ge 2) {
                        $shown = [DateTime]::UtcNow
                        if ($length -gt 0) { Write-Host ("  {0:N0} of {1:N0} MB" -f ($got / 1MB), ($length / 1MB)) }
                        else { Write-Host ("  {0:N0} MB" -f ($got / 1MB)) }
                    }
                }
            } finally { $to.Close() }
        } finally { $response.Close() }
        if ($length -gt 0 -and $got -ne $length) { throw "the download was cut short ($got of $length bytes arrived)" }

        # The package is a ZIP, and Python is its "tools" folder.
        $doing = "The Python that was downloaded could not be unpacked into $new"
        Write-Host "Unpacking it"
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($package)
        try {
            foreach ($entry in $zip.Entries) {
                if (-not $entry.FullName.StartsWith("tools/")) { continue }
                $name = [Uri]::UnescapeDataString($entry.FullName.Substring(6)).Replace("/", "\")
                if ($name -eq "" -or $name.EndsWith("\")) { continue }
                $file = [IO.Path]::GetFullPath((Join-Path $new $name))
                if (-not $file.StartsWith($new + "\", [StringComparison]::OrdinalIgnoreCase)) {
                    throw "it holds a file that would land outside its folder ($name)"
                }
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($file)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $file, $true)
            }
        } finally { $zip.Dispose() }

        # Is it what it says it is? Python itself (its two programs, and the libraries
        # that are Python) carries the Python Software Foundation's signature, which
        # Windows checks. Then it has to run, and be one that would not be turned away.
        $doing = "What was downloaded is not the Python that was asked for, and has been removed"
        $signed = @(Get-ChildItem -LiteralPath $new -Force |
            Where-Object { -not $_.PSIsContainer -and ($_.Name -like "python*.exe" -or $_.Name -like "python*.dll") })
        foreach ($name in "python.exe", "pythonw.exe") {
            if (@($signed | Where-Object { $_.Name -eq $name }).Count -eq 0) { throw "there is no $name in it" }
        }
        foreach ($file in $signed) {
            $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
            $signer = ""
            if ($signature.SignerCertificate) { $signer = "$($signature.SignerCertificate.Subject)" }
            if ("$($signature.Status)" -ne "Valid") { throw "$($file.Name) has no signature that Windows accepts ($($signature.Status))" }
            if ($signer -notmatch '(^|,\s*)O=Python Software Foundation(,|$)') { throw "$($file.Name) is signed by somebody else ($signer)" }
        }
        $doing = "The Python that was downloaded won't do, and has been removed"
        $said = Probe @("$new\python.exe")
        if (-not $said) { throw "it does not run on this PC (a PC set up by an employer may not allow it)" }
        $why = Wrong ($said -split ';', 4)
        if ($why) { throw $why }

        $doing = "The new Python could not be put in place, in $ownPython"
        if (Test-Path -LiteralPath $ownPython) { Remove-Item -LiteralPath $ownPython -Recurse -Force }
        Rename-Item -LiteralPath $new -NewName (Split-Path -Leaf $ownPython)
        Write-Host "Python $version is in $ownPython, and its signature is the Python Software Foundation's."
    } catch {
        $problem = $_.Exception
        while ($problem.InnerException) { $problem = $problem.InnerException }
        Remove-Item -LiteralPath $new -Recurse -Force -ErrorAction SilentlyContinue
        throw "${doing}: $($problem.Message)"
    } finally {
        Remove-Item -LiteralPath $package -Force -ErrorAction SilentlyContinue
    }
}
function Ask-AboutPython($found) {
    Write-Host ""
    Write-Host "== Python"
    if (@($found).Count -eq 0) {
        Write-Host "Linux Speaking runs on Python, and none was found on this PC."
    } else {
        Write-Host "Linux Speaking runs on Python, and none on this PC will do. Found:"
        foreach ($line in $found) { Write-Host $line }
    }
    Write-Host ""
    Write-Host "The installer can fetch one for Linux Speaking alone: Python 3.$fetchMinor, as the Python"
    Write-Host "Software Foundation publishes it, a download of about 15 MB that takes about 50 MB of"
    Write-Host "disk. It goes inside Linux Speaking's folder and is removed with it. Nothing else on"
    Write-Host "this PC is changed: a Python that is already here stays as it is."
    Write-Host ""
    while ($true) {
        $answer = ([string](Read-Host "Fetch it now? [Y/n]")).Trim().ToLower()
        if ($answer -eq "" -or $answer -eq "y" -or $answer -eq "yes") { return $true }
        if ($answer -eq "n" -or $answer -eq "no") { return $false }
        Write-Host "Please answer y for yes, or n for no."
    }
}

$candidates = @()
if ($env:LS_PYTHON) {
    if ($env:LS_PYTHON -match '^\d+(\.\d+)?$') { $candidates += , @("py", "-$($env:LS_PYTHON)") }
    else { $candidates += , @($env:LS_PYTHON) }
} else {
    # One that was fetched for this install before is the one it goes on with.
    if (Test-Path -LiteralPath "$ownPython\python.exe") { $candidates += , @("$ownPython\python.exe") }
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
$fetchPython = $false
if (-not $python) {
    $wanted = "a 64-bit Python (for Intel and AMD processors), version 3.$oldest to 3.$newest"
    if ($env:LS_PYTHON -and $turnedAway.Count -eq 0) {
        Stop-Here "LS_PYTHON is set to $($env:LS_PYTHON), and no Python answers there." `
            "Give the full path of a python.exe, or a version for the py launcher, such as 3.12."
    }
    # A Python is only wanted to make the install's own copy of it from. Where that copy
    # still runs, none is needed: nothing is asked, and nothing is fetched.
    $ownStillRuns = $false
    if (-not $env:LS_PYTHON -and (Test-Path -LiteralPath "$dir\venv\Scripts\python.exe")) {
        $said = Probe @("$dir\venv\Scripts\python.exe")
        if ($said -and -not (Wrong ($said -split ';', 4))) { $ownStillRuns = $true }
    }
    if ($ownStillRuns) {
        Write-Host "No Python was found to build on, and none is needed: this install's own still runs."
    } else {
        # One can be fetched for 64-bit Windows on an Intel or AMD processor, and for no
        # other. Whoever named a Python with LS_PYTHON is told about that one instead.
        $processor = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
        $canFetch = (-not $env:LS_PYTHON) -and ($processor -eq "AMD64")
        $asked = $false
        if ($canFetch) {
            # LS_FETCH_PYTHON answers for somebody who isn't there to be asked: 1 for yes, 0 for no.
            if ($env:LS_FETCH_PYTHON -eq "1") { $fetchPython = $true }
            elseif ($env:LS_FETCH_PYTHON -eq "0") { }
            elseif ($someoneToAsk) {
                $asked = $true
                $fetchPython = Ask-AboutPython $turnedAway
            }
        }
        if ($fetchPython -and -not $asked) {
            if ($turnedAway.Count -eq 0) { Write-Host "Python wasn't found on this PC." }
            else {
                Write-Host "No Python on this PC will do. Found:"
                foreach ($line in $turnedAway) { Write-Host $line }
            }
            Write-Host "One is fetched for Linux Speaking alone, as LS_FETCH_PYTHON says."
        }
        if (-not $fetchPython) {
            $offer = @()
            if ($canFetch -and -not $asked -and $env:LS_FETCH_PYTHON -ne "0") {
                $offer = @("(Run in a PowerShell window, this offers to fetch one itself. Or type first:  `$env:LS_FETCH_PYTHON = `"1`")")
            }
            if ($asked) { Write-Host "None is fetched." }
            if ($turnedAway.Count -eq 0) {
                $lead = "Python wasn't found. Linux Speaking needs $wanted."
                if ($asked) { $lead = "Linux Speaking needs $wanted." }
                Stop-Here $lead `
                    "Install one from python.org (the `"Windows installer (64-bit)`") or from the Microsoft" `
                    "Store, then run this again. Nothing has been changed." @offer
            }
            if (-not $asked) {
                Write-Host "No Python on this PC will do. Found:"
                foreach ($line in $turnedAway) { Write-Host $line }
            }
            Stop-Here "Linux Speaking needs $wanted." `
                "Install one from python.org (the `"Windows installer (64-bit)`") beside what is here, then" `
                "run this again. If there is one this didn't find, say where, by typing this first:" `
                "  `$env:LS_PYTHON = `"C:\path\to\python.exe`"" `
                "Nothing has been changed." @offer
        }
    }
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

# The Python that was offered above, if it was wanted. It is fetched here: into a folder
# that is by now closed to other accounts, and before anything of an install that is
# already here is replaced.
if ($fetchPython) {
    Say "Fetching Python for Linux Speaking alone"
    try { Get-OwnPython }
    catch {
        $why = "$_"
        $left = @("The install that is here has not been touched.")
        if (-not $update) {
            # A new install: the folders made a moment ago go again, if nothing is in them.
            foreach ($made in "$dir\app", "$dir\models", $dir) {
                if ((Test-Path -LiteralPath $made -PathType Container) -and
                        @(Get-ChildItem -LiteralPath $made -Force).Count -eq 0) {
                    Remove-Item -LiteralPath $made -Force -ErrorAction SilentlyContinue
                }
            }
            $left = @("Nothing has been changed.")
        }
        if ($running.Count -gt 0) { $left += "(Linux Speaking was running, and was stopped for this. Start it from the Start menu.)" }
        Stop-Here "" $why `
            "If it was the connection, run this again. Or install one yourself, from python.org (the" `
            "`"Windows installer (64-bit)`") or from the Microsoft Store, and run this again: it is" `
            "then found by itself." @left
    }
    $python = "$ownPython\python.exe"
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
    # One made from a Python that has just been replaced holds packages made for the old one.
    if (-not $why -and $fetchPython) { $why = "the Python it was made from has been replaced" }
    if ($why) {
        Write-Host "The Python this install was set up with won't do any more ($why)."
        Write-Host "Setting it up again from nothing."
        Remove-Item -LiteralPath "$dir\venv" -Recurse -Force
    }
}
if (-not (Test-Path -LiteralPath $py)) {
    if (-not $python) {
        Stop-Here "The install's own Python stopped running while this was at work, and there is no" `
            "other to make it from. Run this again."
    }
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
if (-not $skipModels) {
    Remove-Item -LiteralPath $leftOut -Force -ErrorAction SilentlyContinue
    Say "Downloading the speech models (about 650 MB, once)"
    & $py "$dir\app\scripts\fetch_models.py" "$dir\models"
    if ($LASTEXITCODE -ne 0) { exit 1 }    # it has said why, and what to do
} else {
    # The choice is kept, so that an update doesn't ask again.
    Set-Content -LiteralPath $leftOut -Encoding UTF8 -Value @(
        "The installer was asked not to download speech models to this PC, and doesn't ask",
        "again while this note is here.",
        "To have them after all: `"Install or remove models`" in Linux Speaking's Settings.")
}

$env:LS_INSTALL_DIR = $dir
Push-Location -LiteralPath "$dir\app"
Say "Checking that speech recognition loads (ten seconds or so)"
# The check goes by the same answer. (Set for it alone: a choice made here is not left
# lying in this PowerShell window to answer for the next run.)
$saidBefore = $env:LS_SKIP_MODELS
$env:LS_SKIP_MODELS = if ($skipModels) { "1" } else { "0" }
& $py "scripts\check_install.py"
$checked = $LASTEXITCODE
$env:LS_SKIP_MODELS = $saidBefore
if ($checked -ne 0) { Pop-Location; exit 1 }    # it has said what is wrong
# Whether there is a speech model to recognise with: without one, another computer has to.
& $py -c "import sys; from dictation import config; from dictation.settings import available_models; sys.exit(0 if available_models(config.MODEL_DIR) else 3)"
$nomodel = $LASTEXITCODE -ne 0
function Say-NoModel {
    Write-Host "No speech model was installed, as chosen, so this PC can't recognise speech by"
    Write-Host "itself. Its icon says `"No speech model`" until you do one of these:"
    Write-Host "  - Have another computer do the recognising. On that one, open Settings and tick"
    Write-Host "    `"Let other computers use this one for speech recognition`": it shows an address"
    Write-Host "    and a key. On this one, open Settings, and under `"Another computer`" tick `"Use"
    Write-Host "    another computer for speech recognition`", type those in and press Connect."
    Write-Host "    `"Wake up`" is then listened for there as well: see docs\OTHER-COMPUTER.md."
    Write-Host "  - Or install a model after all: `"Install or remove models`" in Settings. It is"
    Write-Host "    put to use as soon as it has arrived."
}

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
if ($started -and $nomodel) {
    Write-Host "It is running: look for the microphone icon near the clock. Windows may tuck it"
    Write-Host "behind the little arrow there: drag it out onto the taskbar to keep it in view."
    Say-NoModel
} elseif ($started) {
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
    if ($nomodel) { Say-NoModel }
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

# Removes Linux Speaking from Windows: the program, its Python packages, the speech models,
# your settings, its shortcuts and its Visual Studio Code extension.
#
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1           asks before removing what
#                                                                    you recorded and what was trained
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1 -Purge    removes those too, without asking
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1 -Keep     keeps them, without asking
#
# (Or set LS_PURGE or LS_KEEP to 1.) The installer copies this file into the install
# folder and adds "Uninstall Linux Speaking" to the Start menu, which runs it from there.
#
# It finds the install folder by itself: from where this file is, or from the Start menu
# shortcut. LS_INSTALL_DIR names it if it has to be told. Only what the installer and the
# app put in that folder is taken out of it, and the folder goes if it is then empty.
param([switch]$Purge, [switch]$Keep, [switch]$Pause)

function Finish($code) {
    # Started from the Start menu, the window would close before anything could be read.
    if ($Pause) { try { Read-Host "`nPress Enter to close this window" | Out-Null } catch { } }
    exit $code
}

if ($env:LS_PURGE -eq "1") { $Purge = $true }
if ($env:LS_KEEP -eq "1") { $Keep = $true }
if ($Purge -and $Keep) {
    Write-Host "Both -Purge and -Keep were asked for (or LS_PURGE and LS_KEEP). Choose one."
    Finish 2
}

$programs = [Environment]::GetFolderPath("Programs")
$startup = [Environment]::GetFolderPath("Startup")
$menuLink = "$programs\Linux Speaking.lnk"
$startLink = "$startup\Linux Speaking.lnk"
$removeLink = "$programs\Uninstall Linux Speaking.lnk"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---- which folder --------------------------------------------------------------------------
$dir = $null
$foundBy = ""
if ($env:LS_INSTALL_DIR) {
    $dir = $env:LS_INSTALL_DIR
    $foundBy = "LS_INSTALL_DIR"
} elseif (Test-Path -LiteralPath (Join-Path $here "app\dictation")) {
    $dir = $here
    $foundBy = "where this file is"
} elseif (Test-Path -LiteralPath $menuLink) {
    # The shortcut starts the program in <folder>\app.
    try {
        $shell = New-Object -ComObject WScript.Shell
        $app = $shell.CreateShortcut($menuLink).WorkingDirectory
        if ($app -and ((Split-Path -Leaf $app) -eq "app")) {
            $dir = Split-Path -Parent $app
            $foundBy = "the Start menu shortcut"
        }
    } catch { }
}
if (-not $dir) {
    $dir = Join-Path $env:USERPROFILE "linux-speaking"
    $foundBy = "the usual place"
}
$dir = [IO.Path]::GetFullPath($dir).TrimEnd('\')

$installed = Test-Path -LiteralPath $dir
# The program itself is the one sure sign. A folder that merely has a "models" or a "venv"
# in it, as many a folder of somebody's own does, is not taken for an install.
if ($installed -and -not (Test-Path -LiteralPath "$dir\app\dictation")) {
    # A folder named by mistake is not emptied.
    Write-Host "$dir (from $foundBy) doesn't look like Linux Speaking's folder:"
    Write-Host "the program isn't in it (there is no app\dictation). Nothing has been removed."
    Write-Host "If it is installed somewhere else, say where by typing this first:"
    Write-Host "  `$env:LS_INSTALL_DIR = `"C:\that\folder`""
    Finish 1
}
if ($installed) {
    Write-Host "Removing Linux Speaking from $dir (found from $foundBy)."
} else {
    Write-Host "There is no folder $dir (looked for from $foundBy),"
    Write-Host "so only Linux Speaking's shortcuts and its Visual Studio Code extension are being"
    Write-Host "removed. If the program is installed somewhere else, run this again, having typed"
    Write-Host "this first:  `$env:LS_INSTALL_DIR = `"C:\that\folder`""
}

# ---- what is yours -------------------------------------------------------------------------
function Size($path) {
    $bytes = 0
    $files = @(Get-ChildItem -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer })
    foreach ($file in $files) { $bytes += $file.Length }
    if ($bytes -ge 1GB) { return ("{0:N1} GB" -f ($bytes / 1GB)) }
    return ("{0:N0} MB" -f [math]::Ceiling($bytes / 1MB))
}
function Sounds($path) {
    return @(Get-ChildItem -LiteralPath $path -Recurse -Force -Filter "*.wav" -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer }).Count
}
function Many($count, $word) { if ($count -eq 1) { return "1 $word" } else { return "$count ${word}s" } }
$state = "$dir\state"
$yours = @()
if (Test-Path -LiteralPath "$state\training") {
    $count = Sounds "$state\training"
    $size = Size "$state\training"
    $what = Many $count "sentence"
    if ($count -gt 0) { $yours += "$what read aloud for training ($size), in $state\training" }
}
if (Test-Path -LiteralPath "$state\voice-test.wav") {
    $size = Size "$state\voice-test.wav"
    $yours += "the recording made for the voice test ($size), $state\voice-test.wav"
}
if (Test-Path -LiteralPath "$state\noises") {
    $count = Sounds "$state\noises"
    $size = Size "$state\noises"
    $what = Many $count "sound"
    if ($count -gt 0) { $yours += "$what marked `"that was a noise`" ($size), in $state\noises" }
}
$retrained = @()    # models retrained to your voice: each has a trained.json in its folder
if (Test-Path -LiteralPath "$dir\models") {
    foreach ($model in @(Get-ChildItem -LiteralPath "$dir\models" -Force | Where-Object { $_.PSIsContainer })) {
        if (Test-Path -LiteralPath (Join-Path $model.FullName "trained.json")) {
            $retrained += $model.FullName
            $size = Size $model.FullName
            $name = $model.Name
            $yours += "the retrained model `"$name`" ($size), in $dir\models"
        }
    }
}
if ($yours.Count -gt 0 -and -not $Purge -and -not $Keep) {
    Write-Host ""
    Write-Host "These are yours, and can't be got back once they are removed:"
    foreach ($line in $yours) { Write-Host "  - $line" }
    $answer = $null
    try { $answer = Read-Host "Remove them as well? Type yes to remove them; anything else keeps them" } catch { $answer = $null }
    if ($null -eq $answer) {
        Write-Host "Nobody is here to ask, so they are kept. (-Purge removes them without asking.)"
        $Keep = $true
    } elseif (@("yes", "y") -contains $answer.Trim().ToLower()) {
        $Purge = $true
    } else {
        $Keep = $true
    }
}
$keeping = ($Keep -and $yours.Count -gt 0)

# ---- stop it ---------------------------------------------------------------------------------
# Everything of it that is running: the app, and a training run or an install of the
# training tools, which go on by themselves and have no window to close.
$mine = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and (
        ($_.Name -like "python*" -and ($_.CommandLine -like "*dictation.tray*" -or $_.CommandLine -like "*dictation.trainer*")) -or
        ($_.Name -like "powershell*" -and $_.CommandLine -like "*install-training.ps1*") -or
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir + "\", [StringComparison]::OrdinalIgnoreCase)))
})
foreach ($one in $mine) { Stop-Process -Id $one.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($one in $mine) { Wait-Process -Id $one.ProcessId -Timeout 15 -ErrorAction SilentlyContinue }

# ---- shortcuts, and the Visual Studio Code extension ---------------------------------------
foreach ($link in $menuLink, $startLink, $removeLink) {
    Remove-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
}
$left = @()    # what is still there, to be said at the end
$editors = 0
foreach ($name in "code", "code-insiders", "codium") {
    $editor = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $editor) { continue }
    $editors += 1
    try { & $editor.Source --uninstall-extension jontio.linux-speaking 2>$null | Out-Null } catch { }
}
if ($editors -eq 0) {
    $left += "Visual Studio Code wasn't found. If it is installed and has the Linux Speaking extension, remove that in its Extensions list."
}

# ---- the files -------------------------------------------------------------------------------
Set-Location -LiteralPath $env:TEMP    # not in the folder that is going
function Remove-It($path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { return }
    # Folders with very long paths inside, as the training tools have, can defeat the
    # line above. Two older ways that don't mind them.
    & cmd.exe /c rd /s /q "$path" 2>$null | Out-Null
    if (-not (Test-Path -LiteralPath $path)) { return }
    $empty = Join-Path $env:TEMP ("linux-speaking-empty-" + $PID)
    New-Item -ItemType Directory -Force -Path $empty | Out-Null
    robocopy $empty $path /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    Remove-Item -LiteralPath $empty -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
}
function Remove-IfEmpty($path) {
    if ((Test-Path -LiteralPath $path -PathType Container) -and
            @(Get-ChildItem -LiteralPath $path -Force).Count -eq 0) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}
# A Python that the installer fetched for Linux Speaking alone lives in the folder, and goes
# with it. One that you installed yourself is somewhere else, and is not touched.
$ownPython = $installed -and (Test-Path -LiteralPath "$dir\python\python.exe")
if ($installed) {
    foreach ($name in "app", "venv", "python", "python.new", "training", "dictionaries", "settings.json",
                      "settings.json.new", "mail-key", "linux-speaking.ico", "linux-speaking.vsix") {
        Remove-It "$dir\$name"
    }
    if ($keeping) {
        if (Test-Path -LiteralPath $state) {
            foreach ($item in @(Get-ChildItem -LiteralPath $state -Force)) {
                if (@("training", "noises", "voice-test.wav", "voice-test.json") -notcontains $item.Name) { Remove-It $item.FullName }
            }
        }
        if (Test-Path -LiteralPath "$dir\models") {
            foreach ($item in @(Get-ChildItem -LiteralPath "$dir\models" -Force)) {
                if ($retrained -notcontains $item.FullName) { Remove-It $item.FullName }
            }
        }
    } else {
        Remove-It $state
        Remove-It "$dir\models"
    }
    # The training tools, if they were put somewhere else and this was told where.
    if ($env:LS_TRAINING_DIR -and (Test-Path -LiteralPath (Join-Path $env:LS_TRAINING_DIR "boot"))) {
        foreach ($name in "boot", "venv", "python", "cache") { Remove-It (Join-Path $env:LS_TRAINING_DIR $name) }
        Remove-IfEmpty $env:LS_TRAINING_DIR
    }
    # This file itself goes last, and then the folder, if nothing else is in it.
    $failed = (Test-Path -LiteralPath "$dir\app") -or (Test-Path -LiteralPath "$dir\venv") -or
        (Test-Path -LiteralPath "$dir\python")
    if (-not $failed) { Remove-It "$dir\uninstall.ps1" }
    Remove-IfEmpty $state
    Remove-IfEmpty "$dir\models"
    Remove-IfEmpty $dir
} else {
    $failed = $false
}

# ---- what happened ---------------------------------------------------------------------------
Write-Host ""
if ($failed) {
    Write-Host "NOT ALL OF IT COULD BE REMOVED. The program is still in ${dir}:"
    Write-Host "something still has a file in it open. Close that (a restart of Windows will, if"
    Write-Host "nothing else does) and run this again, or delete the folder yourself. The shortcuts"
    Write-Host "have gone, so run it as:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$dir\uninstall.ps1`""
} elseif ($installed) {
    Write-Host "Linux Speaking has been removed: the program, its Python packages, the speech models,"
    Write-Host "your settings and its shortcuts."
} else {
    Write-Host "Linux Speaking's shortcuts have been removed. No program folder was found at"
    Write-Host "$dir, so none was removed."
}
if ($keeping -and -not $failed) {
    Write-Host ""
    Write-Host "Kept, as they were:"
    foreach ($line in $yours) { Write-Host "  - $line" }
    Write-Host "A later install into the same folder finds them again. To be rid of them, delete"
    Write-Host "$dir."
} elseif ((Test-Path -LiteralPath $dir) -and -not $failed) {
    $left += "$dir is still there, because it holds other things than Linux Speaking's. They have not been touched."
}
if ($left.Count -gt 0) {
    Write-Host ""
    Write-Host "Left for you:"
    foreach ($line in $left) { Write-Host "  - $line" }
}
Write-Host ""
if ($ownPython) {
    if (-not $failed) {
        Write-Host "The Python that the installer fetched for Linux Speaking alone has gone with it. Any"
        Write-Host "other Python on this PC has not been touched. The folder you installed from is still"
        Write-Host "here, if you kept it."
    }
} else {
    Write-Host "Python itself, which you installed, is still on this PC, and so is the folder you"
    Write-Host "installed from, if you kept it."
}
if ($failed) { Finish 1 }
Finish 0

# Removes Linux Speaking from Windows: the program, its shortcuts, its Visual Studio Code
# extension and the speech models. Your settings file is deleted with the rest.
#
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
$dir = if ($env:LS_INSTALL_DIR) { $env:LS_INSTALL_DIR } else { Join-Path $env:USERPROFILE "linux-speaking" }
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*dictation.tray*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item ([Environment]::GetFolderPath("Programs") + "\Linux Speaking.lnk") -ErrorAction SilentlyContinue
Remove-Item ([Environment]::GetFolderPath("Startup") + "\Linux Speaking.lnk") -ErrorAction SilentlyContinue
$code = Get-Command code -ErrorAction SilentlyContinue
if ($code) { & $code.Source --uninstall-extension jontio.linux-speaking 2>$null | Out-Null }
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
Write-Host "Linux Speaking has been removed."

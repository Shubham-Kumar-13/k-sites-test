# K-Sites Windows auto-start setup script
# Run this in PowerShell to create a Startup shortcut and optionally set NGROK_PATH

$projectDir = "C:\Users\HP\Desktop\Work\K-Sites"
$batchFile = Join-Path $projectDir "start_ksites_windows.bat"
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "K-Sites Auto Start.lnk"
$oldBatchFile = Join-Path $startupDir "start_ksites_backend.bat"

if (-not (Test-Path $batchFile)) {
    Write-Host "ERROR: $batchFile not found" -ForegroundColor Red
    exit 1
}

# Remove the old startup script if it exists
if (Test-Path $oldBatchFile) {
    Remove-Item $oldBatchFile -Force
    Write-Host "Removed old startup script: $oldBatchFile" -ForegroundColor Green
}

# Remove any old shortcut with the same name if it exists
if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)
$Shortcut.TargetPath = $batchFile
$Shortcut.WorkingDirectory = $projectDir
$Shortcut.WindowStyle = 7  # Minimized
$Shortcut.Save()

Write-Host "Shortcut created at: $shortcutPath" -ForegroundColor Green
Write-Host "K-Sites will now auto-start when you log in." -ForegroundColor Green

# Optional: ask to set NGROK_PATH if ngrok is not in PATH
$ngrokInPath = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokInPath) {
    Write-Host ""
    Write-Host "ngrok was not found in your system PATH." -ForegroundColor Yellow
    $ngrokExe = Read-Host "Enter the full path to ngrok.exe (or press Enter to skip)"
    if ($ngrokExe -and (Test-Path $ngrokExe)) {
        [Environment]::SetEnvironmentVariable("NGROK_PATH", $ngrokExe, "User")
        Write-Host "NGROK_PATH set to: $ngrokExe" -ForegroundColor Green
        Write-Host "You may need to restart your terminal for this to take effect." -ForegroundColor Yellow
    } else {
        Write-Host "Skipped. If ngrok is not found at runtime, set NGROK_PATH manually." -ForegroundColor Yellow
    }
} else {
    Write-Host "ngrok found in PATH: $($ngrokInPath.Source)" -ForegroundColor Green
}

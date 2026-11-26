# Prompt Archive for AI Chats - installer (per user, no admin rights needed)
# Developed by Rahil Qureshi. Based on Chat Export by Trifall (MIT License).
#
# What it does:
#   1. finds Python 3.8+ on this PC
#   2. copies the extension and the archive helper to %LOCALAPPDATA%\PromptArchive
#   3. registers the helper with Microsoft Edge and Google Chrome (native messaging, HKCU only)
#   4. creates your archive folder (%USERPROFILE%\prompt_archive)
# Nothing is downloaded and nothing is sent over the network.
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'PromptArchive'),
    [string]$ExtensionId = 'jlomggbfdidocpemnppbjhfobbjfdlac'
)
$ErrorActionPreference = 'Stop'
$HostName = 'com.prompt_archive.host'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Utf8 = New-Object System.Text.UTF8Encoding $false

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

function Find-Python {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $candidates += , @($py.Source, '-3') }
    foreach ($c in (Get-Command python, python3 -All -ErrorAction SilentlyContinue)) {
        if ($c.Source -notlike '*\WindowsApps\*') { $candidates += , @($c.Source) }  # skip the Store stub
    }
    foreach ($cand in $candidates) {
        $exe = $cand[0]
        $args_ = @($cand | Select-Object -Skip 1) + @('-c', 'import sys; print(sys.executable); print(sys.version_info >= (3, 8))')
        try {
            $out = & $exe @args_ 2>$null
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq 'True' -and (Test-Path $out[0])) {
                return $out[0]
            }
        } catch { }
    }
    return $null
}

Write-Host ''
Write-Host 'Prompt Archive for AI Chats - installer' -ForegroundColor Green
Write-Host 'Developed by Rahil Qureshi - based on Chat Export by Trifall (MIT)'
Write-Host ''

Write-Step 'Looking for Python 3.8 or newer'
$Python = Find-Python
if (-not $Python) {
    Write-Host 'Python 3.8+ was not found. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this installer again.' -ForegroundColor Red
    exit 1
}
Write-Host "    using $Python"

foreach ($required in 'extension\manifest.json', 'host\export_prompt_history.py', 'host\ai_chat_host.py') {
    if (-not (Test-Path (Join-Path $Here $required))) {
        Write-Host "Missing $required next to install.ps1. Extract the whole release zip first." -ForegroundColor Red
        exit 1
    }
}

Write-Step "Copying files to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$ExtDir = Join-Path $InstallDir 'extension'
if (Test-Path $ExtDir) { Remove-Item -Recurse -Force $ExtDir }
Copy-Item -Recurse (Join-Path $Here 'extension') $ExtDir
Copy-Item (Join-Path $Here 'host\export_prompt_history.py') $InstallDir -Force
Copy-Item (Join-Path $Here 'host\ai_chat_host.py') $InstallDir -Force

$HostScript = Join-Path $InstallDir 'ai_chat_host.py'
$Bat = Join-Path $InstallDir 'ai_chat_host.bat'
[IO.File]::WriteAllText($Bat, "@echo off`r`n`"$Python`" -u `"$HostScript`" %*`r`n", $Utf8)

$Manifest = Join-Path $InstallDir "$HostName.json"
$manifestJson = [ordered]@{
    name            = $HostName
    description     = 'Prompt Archive for AI Chats: saves your prompts to %USERPROFILE%\prompt_archive'
    path            = $Bat
    type            = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
} | ConvertTo-Json
[IO.File]::WriteAllText($Manifest, $manifestJson, $Utf8)

Write-Step 'Registering the helper with Edge and Chrome (current user only)'
foreach ($key in "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$HostName",
                 "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName") {
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name '(default)' -Value $Manifest
}

Write-Step 'Setting up the archive folder'
$ErrorActionPreference = 'Continue'  # a Python warning on stderr must not abort the install
$output = & $Python (Join-Path $InstallDir 'export_prompt_history.py') --no-scan 2>&1
$ErrorActionPreference = 'Stop'
if ($LASTEXITCODE -ne 0) {
    Write-Host ($output | Out-String) -ForegroundColor Red
    Write-Host 'The archive could not be created; see the error above.' -ForegroundColor Red
    exit 1
}
$Archive = Join-Path $env:USERPROFILE 'prompt_archive'
Write-Host "    archive: $Archive"

Write-Host ''
Write-Host 'Installed. One step left - load the extension in your browser:' -ForegroundColor Green
Write-Host '  1. Open edge://extensions (or chrome://extensions)'
Write-Host '  2. Turn on "Developer mode"'
Write-Host '  3. Click "Load unpacked" and choose:'
Write-Host "       $ExtDir" -ForegroundColor Yellow
Write-Host "  4. Check the extension ID is $ExtensionId"
Write-Host '  5. Reload any open ChatGPT / Claude.ai / Gemini / AI Studio tabs'
Write-Host ''
Write-Host "Your prompts will appear in $Archive\projects\<site>\<year-month>.md"
Write-Host ''

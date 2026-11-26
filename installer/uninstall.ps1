# Prompt Archive for AI Chats - uninstaller (per user)
# Removes the helper and its browser registration. Your archive (%USERPROFILE%\prompt_archive)
# is kept; delete that folder yourself if you no longer want your saved prompts.
[CmdletBinding()]
param([string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'PromptArchive'))
$ErrorActionPreference = 'Stop'
$HostName = 'com.prompt_archive.host'

foreach ($key in "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$HostName",
                 "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName") {
    if (Test-Path $key) { Remove-Item -Path $key -Force; Write-Host "Removed $key" }
}
if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir; Write-Host "Removed $InstallDir" }

Write-Host ''
Write-Host 'Done. Also remove "Prompt Archive for AI Chats" in edge://extensions or chrome://extensions.' -ForegroundColor Green
Write-Host "Your saved prompts are still in $(Join-Path $env:USERPROFILE 'prompt_archive')."

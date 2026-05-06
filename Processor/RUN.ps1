$env:PATH += ";$(Get-Location)"

$FFMPEG = Join-Path (Get-Location) 'ffmpeg'
$env:PATH += ";$FFMPEG"

$CONTENT_DIR = (New-Object -ComObject Shell.Application).Namespace('shell:Downloads').Self.Path
$CONTENT_DIR += "\WidevineMedia"

$env:CONTENT_DIR = $CONTENT_DIR

Write-Host "[RUN.ps1][INFO] Decrypted content will be stored in: `"$CONTENT_DIR`""
Write-Host "[RUN.ps1][INFO] Starting Firefox..."
Write-Host ""

$env:MOZ_DISABLE_GMP_SANDBOX = 1

Start-Process .\x64\Release\injector.exe `
  -NoNewWindow `
  -Wait `
  -ArgumentList "`"C:\Program Files\Mozilla Firefox\firefox.exe`"", `
  "about:debugging#/runtime/this-firefox", `
  "https://integration.widevine.com/player/"

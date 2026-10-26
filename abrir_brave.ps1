$ErrorActionPreference = 'Stop'
$candidates = @(
    (Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\Application\brave.exe'),
    (Join-Path $env:ProgramFiles 'BraveSoftware\Brave-Browser\Application\brave.exe')
)
$brave = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $brave) { throw 'Brave nao encontrado. Consulte o README para informar o executavel manualmente.' }
$profile = Join-Path $PSScriptRoot '.brave_perfil'
# Janela visivel necessaria para login/MFA manual.
& $brave --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="$profile"

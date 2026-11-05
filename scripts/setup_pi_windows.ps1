# Explicitly invoked installation helper. No credentials, profiles, execution
# policy, administrator access, engine or network settings are changed.
[CmdletBinding()]
param(
    [string]$Prefix = (Join-Path $env:APPDATA 'npm'),
    [switch]$ReplaceExistingVersion
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$required = '0.85.1'
$node = Get-Command node.exe -ErrorAction Stop
$nodeVersion = (& $node.Source --version).Trim().TrimStart('v')
if ([version]$nodeVersion -lt [version]'22.19.0') {
    throw 'BLOCKED: installed Node.js 22.19.0 or newer is required'
}
$npmCli = Join-Path (Split-Path $node.Source) 'node_modules\npm\bin\npm-cli.js'
if (-not (Test-Path $npmCli)) { throw 'BLOCKED: installed npm CLI is missing' }
$package = Join-Path $Prefix 'node_modules\@earendil-works\pi-coding-agent'
$metadataPath = Join-Path $package 'package.json'
$existing = $null
if (Test-Path $metadataPath) {
    $existing = Get-Content $metadataPath -Raw | ConvertFrom-Json
    if ($existing.version -ne $required -and -not $ReplaceExistingVersion) {
        throw 'BLOCKED: a different Pi version exists; use an isolated prefix or explicitly request replacement'
    }
}
$logDir = Join-Path $env:TEMP ('teobench-pi-setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $logDir | Out-Null
function Invoke-NodeLogged([string[]]$Arguments, [string]$Name) {
    # Start-Process redirects native stderr directly to a file. PowerShell 5's
    # native-command stderr adapter otherwise turns npm warnings into exceptions
    # under ErrorActionPreference=Stop, even when npm succeeds.
    $quoted = @($Arguments | ForEach-Object {
        if ($_ -match '["\r\n]') { throw 'Unsupported quote/newline in setup argument' }
        '"' + $_ + '"'
    })
    $stdout = Join-Path $logDir ($Name + '.stdout.log')
    $stderr = Join-Path $logDir ($Name + '.stderr.log')
    $process = Start-Process -FilePath $node.Source -ArgumentList $quoted -Wait -PassThru -NoNewWindow `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if ($process.ExitCode -ne 0) {
        throw ('BLOCKED: ' + $Name + ' failed with exit ' + $process.ExitCode + '; logs: ' + $logDir)
    }
    return (Get-Content $stdout -Raw).Trim()
}
if (-not $existing -or -not (Test-Path (Join-Path $package 'dist\index.js'))) {
    $null = Invoke-NodeLogged @($npmCli,'install','--global','--prefix',$Prefix,
        '--registry=https://registry.npmjs.org','--ignore-scripts','--no-audit','--no-fund',
        ('@earendil-works/pi-coding-agent@' + $required)) 'install'
}
$metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
if ($metadata.name -ne '@earendil-works/pi-coding-agent' -or $metadata.version -ne $required) {
    throw 'BLOCKED: installed package identity/version does not match'
}
$version = Invoke-NodeLogged @((Join-Path $package 'dist\bundle\cli.js'),'--version') 'version'
if ($version -ne $required) { throw 'BLOCKED: installed Pi did not report the required version' }
[ordered]@{
    status = 'PI_READY'
    pi_version = $version
    node_version = $nodeVersion
    package = $package
    launcher = (Join-Path $Prefix 'pi.cmd')
    launcher_on_path = [bool](Get-Command pi.cmd -ErrorAction SilentlyContinue)
    personal_profile_changed = $false
    logs = $logDir
} | ConvertTo-Json -Compress

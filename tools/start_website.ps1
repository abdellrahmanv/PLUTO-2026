param(
    [string]$HostName = "0.0.0.0",
    [int]$Port = 8080,
    [int]$Baud = 115200,
    [switch]$SkipValidation,
    [switch]$ForceValidation,
    [switch]$UiOnly,
    [switch]$CameraDisabled,
    [switch]$WavePoseDisabled,
    [switch]$OpenBrowser,
    [switch]$ValidateOnly,
    [string]$Python
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[PLUTO] $Message"
}

function Resolve-RepoRoot {
    $scriptPath = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptPath "..")).Path
}

function Find-Python {
    param([string]$Requested)

    if ($Requested) {
        if (-not (Test-Path $Requested)) {
            throw "Requested Python was not found: $Requested"
        }
        return (Resolve-Path $Requested).Path
    }

    $candidates = @(
        "/home/pi/yolo/env/bin/python",
        "/home/pi/yolo/venv/bin/python"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    foreach ($name in @("python3", "python", "py")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "Python was not found. Install Python or pass -Python <path>."
}

function Get-FileSha256 {
    param([string]$Path)

    $hashCommand = Get-Command Get-FileHash -ErrorAction SilentlyContinue
    if ($hashCommand) {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
    }

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $bytes = $sha.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes) -replace "-", "")
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function Get-ValidationFingerprint {
    param([string]$Root)

    $paths = @(
        "pluto_runtime/web_shell.py",
        "pluto_runtime/stm32_link.py",
        "tools/web_shell_smoke.py",
        "tools/validate_features.py"
    )

    $parts = foreach ($path in $paths) {
        $full = Join-Path $Root $path
        if (Test-Path $full) {
            Get-FileSha256 -Path $full
        }
    }
    return ($parts -join "")
}

function Test-WebsiteRunning {
    param([int]$Port)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Run-Validation {
    param(
        [string]$Root,
        [string]$PythonPath,
        [switch]$Force
    )

    $cacheDir = Join-Path $Root ".pluto"
    $cacheFile = Join-Path $cacheDir "website_validation.json"
    $fingerprint = Get-ValidationFingerprint -Root $Root

    if (-not $Force -and (Test-Path $cacheFile)) {
        try {
            $cached = Get-Content -LiteralPath $cacheFile -Raw | ConvertFrom-Json
            if ($cached.fingerprint -eq $fingerprint -and $cached.status -eq "PASS") {
                Write-Step "Website validation already passed for this code."
                return
            }
        } catch {
            Write-Step "Validation cache unreadable; running validation again."
        }
    }

    Write-Step "Running safe website smoke test."
    & $PythonPath "tools/web_shell_smoke.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Website smoke test failed. The website was not started."
    }

    if (-not (Test-Path $cacheDir)) {
        New-Item -ItemType Directory -Path $cacheDir | Out-Null
    }

    [pscustomobject]@{
        status = "PASS"
        fingerprint = $fingerprint
        validated_at = (Get-Date).ToString("o")
        hardware = $false
    } | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $cacheFile
}

function Run-HardwareFastTest {
    param(
        [string]$PythonPath,
        [int]$BaudRate
    )

    Write-Step "Detecting STM32 motor controller."
    & $PythonPath "tools/stm32_probe.py" "--baud" ([string]$BaudRate)
    if ($LASTEXITCODE -ne 0) {
        throw "STM32 fast test failed. The website was not started."
    }

    Write-Step "Checking persistent STM32 heartbeat runtime."
    & $PythonPath "tools/idle_runtime_smoke.py" "--baud" ([string]$BaudRate) "--require-hardware"
    if ($LASTEXITCODE -ne 0) {
        throw "STM32 runtime heartbeat failed. The website was not started."
    }
}

$root = Resolve-RepoRoot
Set-Location $root

$pythonPath = Find-Python -Requested $Python
Write-Step "Repository: $root"
Write-Step "Python: $pythonPath"

if (-not $SkipValidation) {
    Run-Validation -Root $root -PythonPath $pythonPath -Force:$ForceValidation
} else {
    Write-Step "Website smoke validation skipped by operator request."
}

if (-not $UiOnly) {
    Run-HardwareFastTest -PythonPath $pythonPath -BaudRate $Baud
} else {
    Write-Step "Hardware fast test skipped; UI-only mode."
}

if ($ValidateOnly) {
    Write-Step "Validation-only mode complete."
    exit 0
}

if (Test-WebsiteRunning -Port $Port) {
    Write-Step "Website is already running."
    Write-Host "Open http://127.0.0.1:$Port"
    if ($OpenBrowser) {
        Start-Process "http://127.0.0.1:$Port"
    }
    exit 0
}

$serverArgs = @(
    "-m", "pluto_runtime.web_shell",
    "--host", $HostName,
    "--port", [string]$Port,
    "--baud", [string]$Baud
)

if ($CameraDisabled) {
    $serverArgs += "--camera-disabled"
}
if ($WavePoseDisabled) {
    $serverArgs += "--wave-pose-disabled"
}

$localUrl = "http://127.0.0.1:$Port"
Write-Step "Starting PLUTO website."
Write-Host "Open $localUrl"
if ($HostName -eq "0.0.0.0") {
    Write-Host "On another device, open http://<PI_IP>:$Port"
}
if ($OpenBrowser) {
    Start-Process $localUrl
}

& $pythonPath @serverArgs

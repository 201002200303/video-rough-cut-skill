param(
    [switch]$SkipPythonDeps
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host "== Video Rough Cut Skill Windows setup =="
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path ".venv")) {
    $PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PythonLauncher) {
        $PythonCmd = @("py", "-3.12")
        $pyVersionOutput = & py -3.12 --version 2>$null
        if ($LASTEXITCODE -ne 0) {
            $PythonCmd = @("py", "-3")
        }
    } else {
        $Python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $Python) {
            throw "Python was not found. Install Python 3.10-3.12, then rerun this script."
        }
        $PythonCmd = @("python")
    }

    Write-Host "Creating virtual environment: .venv"
    $PythonExe = $PythonCmd[0]
    if ($PythonCmd.Length -gt 1) {
        $PythonArgs = $PythonCmd[1..($PythonCmd.Length - 1)]
        & $PythonExe @PythonArgs -m venv .venv
    } else {
        & $PythonExe -m venv .venv
    }
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python not found: $VenvPython"
}

if (-not $SkipPythonDeps) {
    & $VenvPython -m pip install --upgrade pip
}

$ArgsList = @("scripts\setup_environment.py", "--install-system-deps", "--yes")
if (-not $SkipPythonDeps) {
    $ArgsList += "--install-python-deps"
}

& $VenvPython @ArgsList
if ($LASTEXITCODE -ne 0) {
    throw "Environment setup failed with exit code $LASTEXITCODE"
}

function Normalize-PathValue {
    param([string]$Value)
    return [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Value)).TrimEnd('\').ToLowerInvariant()
}

function Add-CurrentSessionPath {
    param([string]$BinDir)
    $normalizedTarget = Normalize-PathValue $BinDir
    $currentEntries = $env:Path -split ';' | Where-Object { $_ -and $_.Trim() }
    $hasEntry = $false
    foreach ($entry in $currentEntries) {
        try {
            if ((Normalize-PathValue $entry) -eq $normalizedTarget) {
                $hasEntry = $true
                break
            }
        } catch {
            continue
        }
    }
    if (-not $hasEntry) {
        $env:Path = "$BinDir;$env:Path"
        Write-Host "Current session PATH: added $BinDir"
    }
}

function Write-CommandShim {
    param(
        [string]$ShimPath,
        [string]$TargetExe
    )
    $content = @"
@echo off
"$TargetExe" %*
"@
    Set-Content -Path $ShimPath -Value $content -Encoding ASCII
    Write-Host "Command shim: wrote $ShimPath"
}

function Find-FfmpegBin {
    $ffmpegCmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($ffmpegCmd) {
        return Split-Path -Parent $ffmpegCmd.Source
    }

    $pathScopes = @(
        [Environment]::GetEnvironmentVariable("Path", "User"),
        [Environment]::GetEnvironmentVariable("Path", "Machine")
    )
    foreach ($pathValue in $pathScopes) {
        if (-not $pathValue) {
            continue
        }
        foreach ($entry in ($pathValue -split ';')) {
            if (-not $entry.Trim()) {
                continue
            }
            $expanded = [Environment]::ExpandEnvironmentVariables($entry.Trim())
            $candidate = Join-Path $expanded "ffmpeg.exe"
            $probe = Join-Path $expanded "ffprobe.exe"
            if ((Test-Path $candidate) -and (Test-Path $probe)) {
                return $expanded
            }
        }
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"),
        $env:LOCALAPPDATA,
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        $match = Get-ChildItem -Path $root -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
            Sort-Object { $_.FullName.Length } |
            Select-Object -First 1
        if ($match) {
            return Split-Path -Parent $match.FullName
        }
    }
    return $null
}

$FfmpegBin = Find-FfmpegBin
if ($FfmpegBin) {
    Add-CurrentSessionPath $FfmpegBin
    $FfmpegExe = Join-Path $FfmpegBin "ffmpeg.exe"
    $FfprobeExe = Join-Path $FfmpegBin "ffprobe.exe"
    if ((Test-Path $FfmpegExe) -and (Test-Path $FfprobeExe)) {
        $VenvScripts = Join-Path $ProjectRoot ".venv\Scripts"
        Write-CommandShim (Join-Path $VenvScripts "ffmpeg.cmd") $FfmpegExe
        Write-CommandShim (Join-Path $VenvScripts "ffprobe.cmd") $FfprobeExe
    }
    $ffmpegNow = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    $ffprobeNow = Get-Command ffprobe.exe -ErrorAction SilentlyContinue
    if ($ffmpegNow -and $ffprobeNow) {
        Write-Host "Current session FFmpeg: $($ffmpegNow.Source)"
        Write-Host "Current session FFprobe: $($ffprobeNow.Source)"
    } else {
        Write-Host "FFmpeg bin was found, but ffmpeg/ffprobe is not visible in this session yet."
    }
} else {
    throw "FFmpeg was not found after setup. Install FFmpeg with winget or add ffmpeg.exe to PATH, then rerun this script."
}

Write-Host ""
Write-Host "Setup finished. This PowerShell session has been refreshed when FFmpeg was found."
Write-Host "If another terminal still cannot find ffmpeg, reopen PowerShell/CMD/Codex terminal."
Write-Host "Activate later with: .\.venv\Scripts\Activate.ps1"

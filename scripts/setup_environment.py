"""Prepare local runtime dependencies for the video rough-cut skill.

This script is intentionally practical rather than clever: it checks FFmpeg,
tries to install it when requested, fixes the Windows user PATH for winget
installs, optionally installs Python packages, and creates a starter .env file.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
ENV_PATH = PROJECT_ROOT / ".env"


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up the video rough-cut skill runtime.")
    parser.add_argument(
        "--install-system-deps",
        action="store_true",
        help="Install missing system tools such as FFmpeg when a supported package manager is available.",
    )
    parser.add_argument(
        "--install-python-deps",
        action="store_true",
        help="Install Python dependencies from requirements.txt into the current Python environment.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Run package-manager commands non-interactively where supported.",
    )
    args = parser.parse_args()

    print("== Video Rough Cut Skill setup ==")
    print(f"Project: {PROJECT_ROOT}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")

    ensure_env_file()
    ensure_ffmpeg(install=args.install_system_deps, yes=args.yes)

    if args.install_python_deps:
        install_python_deps()
    else:
        print("Python dependencies: skipped (use --install-python-deps to install requirements.txt)")

    print("\nSetup check complete.")
    print("If PATH was updated, close and reopen PowerShell/CMD/Codex terminal before running the pipeline.")
    return 0


def ensure_env_file() -> None:
    if ENV_PATH.exists():
        print(".env: already exists")
        return
    if ENV_EXAMPLE_PATH.exists():
        shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
        print(".env: created from .env.example")
        print(".env: please fill DASHSCOPE_API_KEY before running semantic cleanup/subtitle correction")
    else:
        print(".env: .env.example not found, skipped")


def ensure_ffmpeg(install: bool, yes: bool) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        print(f"FFmpeg: found {ffmpeg}")
        print(f"FFprobe: found {ffprobe}")
        return

    system = platform.system().lower()
    if system == "windows":
        ensure_ffmpeg_windows(install=install, yes=yes)
    elif system == "linux":
        ensure_ffmpeg_linux(install=install, yes=yes)
    elif system == "darwin":
        ensure_ffmpeg_macos(install=install, yes=yes)
    else:
        print("FFmpeg: not found")
        print("Unsupported OS for automatic install. Install ffmpeg and ffprobe manually, then rerun setup.")

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not (ffmpeg and ffprobe):
        local_bin = PROJECT_ROOT / ".venv" / ("Scripts" if platform.system().lower() == "windows" else "bin")
        ffmpeg_candidates = [local_bin / "ffmpeg.exe", local_bin / "ffmpeg.cmd", local_bin / "ffmpeg"]
        ffprobe_candidates = [local_bin / "ffprobe.exe", local_bin / "ffprobe.cmd", local_bin / "ffprobe"]
        if not (any(path.exists() for path in ffmpeg_candidates) and any(path.exists() for path in ffprobe_candidates)):
            raise SystemExit("FFmpeg setup failed: ffmpeg and ffprobe are not available.")


def ensure_ffmpeg_windows(install: bool, yes: bool) -> None:
    if install:
        if not shutil.which("winget"):
            print("FFmpeg: winget is not available. Install FFmpeg manually or install winget first.")
        else:
            cmd = ["winget", "install", "--id", "Gyan.FFmpeg", "-e"]
            if yes:
                cmd += ["--accept-package-agreements", "--accept-source-agreements"]
            run(cmd, "winget install Gyan.FFmpeg", check=False)

    ffmpeg_path = find_windows_tool("ffmpeg.exe")
    ffprobe_path = find_windows_tool("ffprobe.exe")
    if not ffmpeg_path or not ffprobe_path:
        print("FFmpeg: not found after install attempt.")
        print(r"Try rerunning: winget install --id Gyan.FFmpeg -e")
        return

    bin_dir = ffmpeg_path.parent
    add_user_path_windows(bin_dir)
    prepend_process_path(bin_dir)
    print(f"FFmpeg: found {ffmpeg_path}")
    print(f"FFprobe: found {ffprobe_path}")


def find_windows_tool(executable_name: str) -> Path | None:
    existing = shutil.which(executable_name)
    if existing:
        return Path(existing)

    candidates: list[Path] = []
    env_roots = [
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for raw_root in env_roots:
        if not raw_root:
            continue
        root = Path(raw_root)
        candidates.extend(
            [
                root / "Microsoft" / "WinGet" / "Links",
                root / "Microsoft" / "WinGet" / "Packages",
                root,
            ]
        )

    for root in candidates:
        try:
            if not root.exists():
                continue
        except (OSError, PermissionError):
            continue
        direct = root / executable_name
        if direct.exists():
            return direct
        try:
            matches = sorted(root.rglob(executable_name), key=lambda item: len(str(item)))
        except (OSError, PermissionError):
            continue
        if matches:
            return matches[0]
    return None


def add_user_path_windows(bin_dir: Path) -> None:
    import winreg

    path_value = str(bin_dir)
    key_path = "Environment"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, value_type = "", winreg.REG_EXPAND_SZ

        entries = [entry.strip() for entry in str(current).split(";") if entry.strip()]
        normalized = {normalize_path(entry) for entry in entries}
        if normalize_path(path_value) in normalized:
            print(f"PATH: already contains {path_value}")
            return

        updated = ";".join(entries + [path_value])
        winreg.SetValueEx(key, "Path", 0, value_type, updated)
        print(f"PATH: added to current user PATH: {path_value}")


def normalize_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(value))).rstrip("\\/")


def prepend_process_path(bin_dir: Path) -> None:
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def ensure_ffmpeg_linux(install: bool, yes: bool) -> None:
    if install:
        if shutil.which("apt"):
            apt = ["sudo", "apt", "install"]
            if yes:
                apt.append("-y")
            run(["sudo", "apt", "update"], "apt update", check=False)
            run(apt + ["ffmpeg"], "apt install ffmpeg", check=False)
        elif shutil.which("dnf"):
            cmd = ["sudo", "dnf", "install"]
            if yes:
                cmd.append("-y")
            run(cmd + ["ffmpeg"], "dnf install ffmpeg", check=False)
        elif shutil.which("yum"):
            cmd = ["sudo", "yum", "install"]
            if yes:
                cmd.append("-y")
            run(cmd + ["ffmpeg"], "yum install ffmpeg", check=False)
        elif shutil.which("pacman"):
            cmd = ["sudo", "pacman", "-S"]
            if yes:
                cmd.append("--noconfirm")
            run(cmd + ["ffmpeg"], "pacman install ffmpeg", check=False)
        else:
            print("FFmpeg: no supported Linux package manager found.")

    report_tools()


def ensure_ffmpeg_macos(install: bool, yes: bool) -> None:
    if install and shutil.which("brew"):
        run(["brew", "install", "ffmpeg"], "brew install ffmpeg", check=False)
    elif install:
        print("FFmpeg: Homebrew not found. Install Homebrew or FFmpeg manually.")
    report_tools()


def report_tools() -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        print(f"FFmpeg: found {ffmpeg}")
        print(f"FFprobe: found {ffprobe}")
    else:
        print("FFmpeg/FFprobe: not available on PATH yet.")


def install_python_deps() -> None:
    if not REQUIREMENTS_PATH.exists():
        print(f"Python dependencies: requirements not found: {REQUIREMENTS_PATH}")
        return
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], "upgrade pip", check=True)
    run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)], "install requirements", check=True)


def run(cmd: list[str], label: str, check: bool) -> subprocess.CompletedProcess[str]:
    print(f"Running: {label}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

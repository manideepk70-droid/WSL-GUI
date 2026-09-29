# WSL-GUI

A Windows desktop app to manage WSL distributions and run Linux desktops/apps through WSLg (Wayland/X11) — no terminal needed.

## Features
- **Distros**: install from the official online list, set default, stop, export/import, delete, update WSL.
- **UI layers**: install and launch XFCE, KDE Plasma, GNOME, LXQt, a nested Weston (Wayland) compositor, or plain WSLg app integration. The package manager (apt/dnf/pacman/zypper/apk) is auto-detected.
- **Add your own layer**: import a `.json` file (or drop it in `%APPDATA%\WSL-GUI\layers`). See `wsl_gui/layers.py` and `wsl_gui/builtin_layers/*.json` for the format.
- **Apps & Terminal**: launch any Linux GUI app, run a command with live output, open a terminal, browse files in Explorer.

## Requirements
Windows 10/11 with WSL 2 (`wsl --install`). WSLg is needed for GUI (Windows 11 or recent Windows 10 + `wsl --update`).

## Run / build
```
pip install -r requirements.txt
python -m wsl_gui          # run from source
build.bat                  # produces dist\WSL-GUI.exe
python -m pytest tests     # tests (no WSL needed)
```
Tagged pushes (`v*`) build the `.exe` in GitHub Actions and attach it to a GitHub Release.

## Custom layer example
```json
{"id": "sway", "name": "Sway", "mode": "nested",
 "launch": "weston --socket=s0 & sleep 1; WAYLAND_DISPLAY=s0 sway",
 "install": {"apt": "apt-get install -y sway weston"}}
```

@echo off
rem Builds dist\WSL-GUI.exe (requires Python 3.10+)
pip install -r requirements.txt pyinstaller || exit /b 1
pyinstaller --noconfirm --onefile --windowed --name WSL-GUI ^
  --add-data "wsl_gui/builtin_layers;wsl_gui/builtin_layers" run_wsl_gui.py

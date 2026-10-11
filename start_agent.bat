@echo off
cd /d "%~dp0"
echo [GSuite] Checking Python dependencies...
python -m pip install -q websockets numpy opencv-python-headless 2>nul
echo [GSuite] Starting Animation Editor and AI Copilot...
python run_agent.py
pause

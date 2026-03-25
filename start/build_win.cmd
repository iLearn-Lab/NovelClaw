@echo off
echo ==========================================
echo  Building Launcher for Windows (EXE)
echo ==========================================

echo [*] Installing required dependencies...
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo [*] Starting build process...
python build.py

pause

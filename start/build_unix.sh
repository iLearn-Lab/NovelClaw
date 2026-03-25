#!/bin/bash
echo "=========================================="
echo " Building Launcher for macOS / Linux"
echo "=========================================="

# Check if python3 is available
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: python3 or python not found."
    exit 1
fi

echo "[*] Installing required dependencies..."
$PYTHON_CMD -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo ""
echo "[*] Starting build process..."
$PYTHON_CMD build.py

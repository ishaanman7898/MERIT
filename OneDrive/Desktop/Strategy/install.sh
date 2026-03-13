#!/usr/bin/env bash
set -e

echo "============================================"
echo "  Heikin Ashi Signal Bot - Installer (Mac/Linux)"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "[!] Python 3 not found."
    echo "    Mac:   brew install python3"
    echo "    Linux: sudo apt install python3 python3-pip"
    exit 1
fi

echo "[OK] Python found: $(python3 --version)"
echo

echo "[*] Installing required packages..."
python3 -m pip install --upgrade pip --quiet
python3 -m pip install -r requirements.txt

echo
echo "============================================"
echo "  Done! Run the bot with:"
echo "    python3 bot.py"
echo "============================================"

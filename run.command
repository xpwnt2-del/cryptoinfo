#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.command  –  CryptoInfo Trading Bot Launcher (macOS)
# Double-click this file in Finder to open the bot launcher.
#
# If macOS blocks the file: right-click → Open → Open (first time only)
# ─────────────────────────────────────────────────────────────────────────────

# Move to the directory containing this script so relative paths work
cd "$(dirname "$0")" || exit 1

echo ""
echo " ==================================================="
echo "  CryptoInfo Trading Bot Launcher"
echo " ==================================================="
echo ""

# Check for python3
if ! command -v python3 &>/dev/null; then
    osascript -e 'display alert "Python 3 Not Found" message "Please install Python 3.9+ from https://www.python.org/downloads/ and try again." as critical' 2>/dev/null \
        || echo "ERROR: Python 3 is not installed. Please install it from https://www.python.org/downloads/"
    exit 1
fi

python3 launcher.py

# Keep terminal open if launched by double-click and an error occurred
if [ $? -ne 0 ]; then
    echo ""
    echo "The launcher exited with an error. See the output above."
    read -r -p "Press Enter to close…"
fi

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.sh  –  CryptoInfo Trading Bot Launcher (Linux)
#
# Usage:
#   chmod +x run.sh   (only needed once)
#   ./run.sh          (from a terminal)
#
# Many desktop environments (GNOME, KDE, XFCE) also allow double-clicking
# this file in a file manager to launch it.  If prompted, choose "Run" or
# "Execute in Terminal".
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
    echo "ERROR: Python 3 is not installed."
    echo ""
    echo "Install it with your package manager, for example:"
    echo "  Ubuntu/Debian : sudo apt  install python3 python3-tk"
    echo "  Fedora/RHEL   : sudo dnf  install python3 python3-tkinter"
    echo "  Arch Linux    : sudo pacman -S python tk"
    echo ""
    read -r -p "Press Enter to exit…"
    exit 1
fi

# tkinter hint (common omission on headless installs)
python3 -c "import tkinter" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: The tkinter module is not available."
    echo ""
    echo "Install it with your package manager, for example:"
    echo "  Ubuntu/Debian : sudo apt install python3-tk"
    echo "  Fedora/RHEL   : sudo dnf install python3-tkinter"
    echo "  Arch Linux    : sudo pacman -S tk"
    echo ""
    read -r -p "Press Enter to exit…"
    exit 1
fi

python3 launcher.py

if [ $? -ne 0 ]; then
    echo ""
    echo "The launcher exited with an error. See the output above."
    read -r -p "Press Enter to close…"
fi

#!/bin/bash
# One-time setup on macOS / Linux:  ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "Installing Python and dependencies..."
uv sync

echo "Installing the browser used to fill HRStop..."
uv run playwright install chromium

chmod +x start.command
echo
echo "Done. Double-click start.command (or run ./start.command) to open Timesheet Filler."

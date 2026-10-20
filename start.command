#!/bin/bash
# Double-click to open Timesheet Filler (macOS).
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
exec uv run --quiet python app.py

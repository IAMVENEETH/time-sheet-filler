"""
Per-person settings and files, kept OUTSIDE the project folder so nothing
personal (HRStop login, API key, screenshots) can end up in git.

    ~/.timesheet-filler/
        config.json     settings + Gemini API key (owner-only permissions)
        auth.json       HRStop login session from save_login.py
        screenshots/    preview_YYYYMMDD.png / saved_YYYYMMDD.png
        runs/           the entries each run was given

Override the location with the TIMESHEET_HOME environment variable.
"""

import json
import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TIMESHEET_HOME") or Path.home() / ".timesheet-filler")
CONFIG_FILE = DATA_DIR / "config.json"
AUTH_FILE = DATA_DIR / "auth.json"
SHOTS_DIR = DATA_DIR / "screenshots"
RUNS_DIR = DATA_DIR / "runs"

DEFAULT_RULES = """\
- Every working day must add up to exactly the target hours.
- Start every day with an "Internal Meeting" entry of 45 minutes titled "Daily Standup",
  with a one-line description of what was discussed, based on that day's work.
- Use 5 to 7 entries per day. Durations in 15-minute steps, each between 45 minutes and 2 hours.
- Spread the work across Analysis, Designing, Development, Testing and Documentation as the
  notes suggest. Stay close to the notes: expand them realistically (investigation, review,
  testing, PR preparation) but don't invent unrelated work.
- If the notes say a day was leave or a holiday, return that day with no entries.
- Titles: 3 to 6 words, Title Case. Descriptions: one sentence, past tense, professional tone.
"""

DEFAULTS = {
    "name": "",
    "hrstop_url": "https://imaginnovate.hrstop.com",
    "project": "",
    "target_hours": 9,
    "gemini_api_key": "",
    "gemini_model": "",
    "rules": DEFAULT_RULES,
}


def private(path):
    """Owner-only permissions (no-op on Windows, where the home folder is already private)."""
    try:
        os.chmod(path, 0o700 if Path(path).is_dir() else 0o600)
    except OSError:
        pass


def ensure_dirs():
    for d in (DATA_DIR, SHOTS_DIR, RUNS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    private(DATA_DIR)
    # One-time move of a login saved by the old single-folder version.
    legacy = HERE / "auth.json"
    if legacy.exists() and not AUTH_FILE.exists():
        shutil.copy2(legacy, AUTH_FILE)
    if AUTH_FILE.exists():
        private(AUTH_FILE)


def load():
    ensure_dirs()
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return cfg


def save(updates):
    cfg = load()
    cfg.update({k: v for k, v in updates.items() if k in DEFAULTS})
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    private(tmp)   # API key inside
    os.replace(tmp, CONFIG_FILE)
    return cfg


def target_minutes(cfg=None):
    cfg = cfg or load()
    try:
        return max(1, int(round(float(cfg.get("target_hours") or 9) * 60)))
    except (TypeError, ValueError):
        return 9 * 60

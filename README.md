# Timesheet Filler

Write rough notes about your week, let Gemini turn them into proper HRStop
entries following **your own rules**, review them, and have them filled into
HRStop as **drafts** automatically. You still click "Submit for Approval"
yourself.

Everything runs on your own computer. Your HRStop login, Gemini API key and
rules never leave it. The only thing sent anywhere is your notes, which go to
Google Gemini.

## Install (once)

You need access to this GitHub repo.

**Mac**

```bash
git clone <repo-url> ~/timesheet-filler
cd ~/timesheet-filler
./install.sh
```

**Windows**

1. Download the repo: green **Code** button → **Download ZIP**, then unzip it
   (or use `git clone`).
2. Double-click **install.bat**.

The installer sets up Python, the dependencies and the browser it uses to fill
HRStop. It takes a few minutes the first time.

## Open it

- **Mac:** double-click `start.command`. The first time, macOS may block it:
  right-click → **Open** → **Open**.
- **Windows:** double-click `start.bat`.

It opens http://127.0.0.1:8765 in your browser. Keep the window that opens
running while you use it, and close it when you're done.

## First-time setup

The page shows a checklist until these are done:

1. **Gemini API key.** Get a free one at <https://aistudio.google.com/apikey>,
   paste it under **Settings**, click **Test key**, pick a model (a Flash
   model is fine), and click **Save settings**.
2. **Log in to HRStop.** Click the button at the top right. A browser window
   opens. Log in (including 2FA) and wait for the dashboard, then click
   **I've logged in**. Do this again whenever the page says the login expired
   (roughly weekly).
3. **Project.** In **Settings**, click **Load from HRStop** and choose the
   project your work is filed under.

While you're in Settings, edit **How your entries should be written**. These
are plain-English rules for the AI, for example "45 min standup every day",
"5 to 7 entries", or "titles in Title Case". Also set **Hours per day** if it
isn't 9.

## Every week

1. **Generate:** pick the week and the days, write rough notes, and click
   **Generate entries**.
2. Check the **Preview**. To change anything, edit the JSON under
   **Paste / edit**, and the preview updates as you type.
3. **Dry run** fills HRStop without saving, so you can check the screenshots.
4. **Save as drafts** (click twice to confirm).
5. In HRStop, open each day and click **Submit for Approval**.

You can skip the AI and paste entries yourself under **Paste / edit**, either
as JSON or in the plain-text format (`Monday — 21 Sep`, then
`Category — 1 hr 45 min`, `Title: ...`, `Description: ...`).

## Update

```bash
git pull
./install.sh        # Windows: install.bat
```

## Where your data lives

`~/.timesheet-filler/` (on Windows `C:\Users\<you>\.timesheet-filler\`):

| File | What |
| --- | --- |
| `config.json` | your settings and Gemini key |
| `auth.json` | your HRStop login session |
| `screenshots/` | dry-run and save screenshots |
| `runs/` | the entries each run filled |

Delete the folder to reset everything. None of it is inside the project
folder, so it can't end up in git.

## Troubleshooting

- **"Session expired" / "Log in to HRStop first"**: click **Log in to HRStop**
  and log in again.
- **"Project … isn't in the project dropdown"**: open Settings, click
  **Load from HRStop** and choose again.
- **Gemini quota or rate limit**: free keys have per-minute limits. Wait a
  minute, or pick another model.
- **A category is filed differently than you wrote it**: HRStop has fixed task
  types, and the preview shows the mapping (for example
  Designing → Analysis & Design). Mappings live in `categories.py`.
- **Command line**: `uv run python fill_timesheet.py --help`

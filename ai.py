"""
Generates timesheet entries from rough notes with Google Gemini.

Uses the REST API directly (no SDK to install). The model is forced to return
JSON matching RESPONSE_SCHEMA, then the result is checked in code - models are
unreliable at arithmetic, so a day that doesn't add up, an unknown category or
an odd duration is sent back to the model to fix (up to MAX_REPAIRS rounds).
Anything still wrong is returned as a warning; nothing here touches HRStop.
"""

import json
import re
import urllib.error
import urllib.request
from datetime import datetime

from categories import AI_CATEGORIES

API = "https://generativelanguage.googleapis.com/v1beta"
MAX_REPAIRS = 2
TIMEOUT = 90


class AIError(RuntimeError):
    pass


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "days": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "date": {"type": "STRING", "description": "YYYY-MM-DD"},
                    "entries": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "category": {"type": "STRING", "enum": AI_CATEGORIES},
                                "minutes": {"type": "INTEGER"},
                                "title": {"type": "STRING"},
                                "description": {"type": "STRING"},
                            },
                            "required": ["category", "minutes", "title", "description"],
                            "propertyOrdering": ["category", "minutes", "title", "description"],
                        },
                    },
                },
                "required": ["date", "entries"],
                "propertyOrdering": ["date", "entries"],
            },
        },
    },
    "required": ["days"],
}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _request(method, path, key, body=None):
    if not key:
        raise AIError("No Gemini API key set. Add one in Settings.")
    req = urllib.request.Request(
        f"{API}/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        if e.code in (400, 403) and "API key" in msg:
            raise AIError("Gemini rejected the API key. Check it in Settings.")
        if e.code == 429:
            raise AIError("Gemini quota or rate limit hit. Wait a minute and try again, "
                          "or pick another model in Settings.")
        if e.code == 404:
            raise AIError("That Gemini model isn't available. Pick another one in Settings.")
        raise AIError(f"Gemini error {e.code}: {msg or e.reason}")
    except urllib.error.URLError as e:
        raise AIError(f"Couldn't reach Gemini: {e.reason}")
    except TimeoutError:
        raise AIError("Gemini took too long to answer. Try again.")


def list_models(key):
    """Text-generation Gemini models this key can use, best default first."""
    data = _request("GET", "models?pageSize=200", key)
    names = []
    for m in data.get("models", []):
        name = m.get("name", "").removeprefix("models/")
        if ("generateContent" in m.get("supportedGenerationMethods", [])
                and name.startswith("gemini")
                and not re.search(r"image|tts|audio|live|embedding|vision|robotics|computer", name)):
            names.append(name)
    return sorted(set(names), key=_rank)


def _rank(name):
    """Prefer stable Flash models with the highest version (cheap, fast, good enough)."""
    version = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    v = float(version.group(1)) if version else 0
    return (
        "flash" not in name,
        "lite" in name,
        bool(re.search(r"preview|exp|latest", name)),
        -v,
        len(name),
        name,
    )


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------
def _system_prompt(rules, target_minutes, name):
    who = f" for {name}" if name else ""
    return f"""You write daily timesheet entries{who} for HRStop from rough work notes.

Follow the user's rules exactly:
{rules.strip()}

Hard requirements (checked by software, the response is rejected otherwise):
- Return one item in "days" for every date you are asked for, using that exact YYYY-MM-DD date.
- Each working day's entry minutes must add up to exactly {target_minutes} minutes
  ({target_minutes // 60}h{target_minutes % 60:02d}). A leave/holiday day has an empty entries list.
- "minutes" is a whole number of minutes, a multiple of 15, greater than 0.
- "category" must be one of: {", ".join(AI_CATEGORIES)}.
- Never invent ticket numbers, people's names or tools that aren't in the notes.
"""


def _user_prompt(dates, notes):
    lines = [f"- {d:%Y-%m-%d} ({d:%A})" for d in dates]
    return ("Write timesheet entries for these dates:\n" + "\n".join(lines)
            + "\n\nMy notes for the week:\n" + notes.strip())


# --------------------------------------------------------------------------
# checking
# --------------------------------------------------------------------------
def _fix_minutes(days, target_minutes):
    """Snap minutes to 15-min steps and rebalance each day to the target in code,
    so arithmetic slips don't cost a full re-generation round trip."""
    if target_minutes % 15:
        return   # can't hit a non-15 target in 15-min steps; let _check report it
    for day in days:
        entries = [e for e in day.get("entries") or [] if isinstance(e.get("minutes"), (int, float))]
        if not entries:
            continue
        for e in entries:
            e["minutes"] = max(15, int(round(e["minutes"] / 15)) * 15)
        diff = target_minutes - sum(e["minutes"] for e in entries)
        # 15 at a time: grow the shortest entry / shrink the longest, keeping durations even.
        while diff > 0:
            min(entries, key=lambda e: e["minutes"])["minutes"] += 15
            diff -= 15
        while diff < 0:
            longest = max(entries, key=lambda e: e["minutes"])
            if longest["minutes"] <= 15:
                break
            longest["minutes"] -= 15
            diff += 15


def _check(days, dates, target_minutes):
    """Return a list of problems with the model's answer (empty = good)."""
    problems = []
    wanted = {d.strftime("%Y-%m-%d") for d in dates}
    got = {}
    for day in days:
        got[day.get("date")] = day.get("entries") or []

    for d in sorted(wanted - set(got)):
        problems.append(f"{d} is missing.")
    for d in sorted(set(got) - wanted):
        problems.append(f"{d} was not asked for; remove it.")

    for d in sorted(wanted & set(got)):
        entries = got[d]
        if not entries:
            continue   # leave / holiday
        total = 0
        for i, e in enumerate(entries, 1):
            m = e.get("minutes")
            if isinstance(m, int):
                total += m
            if not isinstance(m, int) or m <= 0 or m % 15:
                problems.append(f"{d} entry {i}: minutes must be a positive multiple of 15 (got {m!r}).")
            if e.get("category") not in AI_CATEGORIES:
                problems.append(f"{d} entry {i}: category {e.get('category')!r} is not allowed.")
            if not (e.get("title") or "").strip():
                problems.append(f"{d} entry {i}: title is empty.")
        if total != target_minutes:
            problems.append(f"{d} adds up to {total} minutes; it must be exactly {target_minutes}.")
    return problems


def _ask(key, model, system, contents):
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0.4,
        },
    }
    data = _request("POST", f"models/{model}:generateContent", key, body)
    cands = data.get("candidates") or []
    if not cands:
        reason = data.get("promptFeedback", {}).get("blockReason", "no answer")
        raise AIError(f"Gemini didn't answer ({reason}).")
    parts = cands[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise AIError(f"Gemini returned nothing (finish reason {cands[0].get('finishReason')}).")
    try:
        return text, json.loads(text).get("days", [])
    except ValueError:
        raise AIError("Gemini returned malformed JSON. Try again.")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def generate(cfg, dates, notes, target_minutes):
    """Return (entries_json_text, warnings). dates: list of datetime.date."""
    if not notes.strip():
        raise AIError("Write some notes about the week first.")
    if not dates:
        raise AIError("Pick at least one day.")
    model = cfg.get("gemini_model") or "gemini-2.5-flash"
    system = _system_prompt(cfg.get("rules") or "", target_minutes, cfg.get("name", ""))
    contents = [{"role": "user", "parts": [{"text": _user_prompt(dates, notes)}]}]

    for attempt in range(MAX_REPAIRS + 1):
        try:
            raw, days = _ask(cfg.get("gemini_api_key"), model, system, contents)
        except AIError:
            if not attempt:
                raise
            break   # a repair call failed (timeout/quota): keep the last answer, report its problems
        _fix_minutes(days, target_minutes)
        problems = _check(days, dates, target_minutes)
        if not problems:
            break
        if attempt < MAX_REPAIRS:
            contents += [
                {"role": "model", "parts": [{"text": raw}]},
                {"role": "user", "parts": [{"text":
                    "Fix these problems and return the complete corrected JSON:\n- "
                    + "\n- ".join(problems)}]},
            ]

    warnings = [f"Still wrong, please fix by hand: {p}" for p in problems]

    # Shape it like the paste box expects: {"YYYY-MM-DD": [entries]}, sorted, no empty days.
    out = {}
    for day in sorted(days, key=lambda d: d.get("date", "")):
        entries = day.get("entries") or []
        try:
            datetime.strptime(day.get("date", ""), "%Y-%m-%d")
        except ValueError:
            continue
        if entries:
            out[day["date"]] = [
                {k: e.get(k) for k in ("category", "minutes", "title", "description")}
                for e in entries
            ]
        else:
            warnings.append(f"{day['date']}: no entries (leave/holiday) - skipped.")
    return json.dumps(out, indent=2, ensure_ascii=False), warnings

"""
Turns pasted work updates into {YYYYMMDD: [entry, ...]} for fill_timesheet.py.

Accepts either JSON:

    {
      "2026-09-21": [
        {"category": "Development", "duration": "1 hr 45 min",
         "title": "...", "description": "..."}
      ]
    }

(date keys may be 2026-09-21 / 20260921 / "21 Sep 2026"; duration may be
"minutes": 105, "hours": "1:45", or "duration": "1 hr 45 min"; a list of
{"date": ..., "entries": [...]} also works)

...or the plain-text weekly format:

    Monday — 21 Sep
    Internal Meeting — 45 min
    Title: Daily Standup
    Description: Discussed ...
"""

import json
import re
from datetime import date, datetime

import config
from categories import CATEGORY_ALIASES, DEFAULT_CATEGORY, SITE_CATEGORIES


class ParseError(ValueError):
    pass


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def parse_duration(value):
    """45 / "45 min" / "1 hr 45 min" / "2 hrs" / "1:45" / "1.5h" -> minutes."""
    if isinstance(value, (int, float)):
        return int(round(value))
    s = str(value).strip().lower()
    m = re.fullmatch(r"(\d+):(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    if re.fullmatch(r"\d+", s):
        return int(s)
    h = re.search(r"(\d+(?:\.\d+)?)\s*h", s)
    mi = re.search(r"(\d+)\s*m", s)
    if not h and not mi:
        raise ParseError(f"Can't read duration {value!r}")
    return int(round(float(h.group(1)) * 60)) + (int(mi.group(1)) if mi else 0) if h \
        else int(mi.group(1))


def parse_date(value, year=None):
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(value).strip())
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    for fmt in ("%d %b", "%d %B"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(year=year or date.today().year).date()
        except ValueError:
            pass
    raise ParseError(f"Can't read date {value!r}")


def normalise_entry(raw, where):
    if not isinstance(raw, dict):
        raise ParseError(f"{where}: each entry must be an object")
    category = (raw.get("category") or raw.get("type") or "").strip()
    title = (raw.get("title") or "").strip()
    if not category:
        raise ParseError(f"{where}: missing category")
    if not title:
        raise ParseError(f"{where}: missing title")
    for key in ("minutes", "hours", "duration", "time"):
        if raw.get(key) not in (None, ""):
            value = raw[key]
            # a bare number under "hours" means hours, not minutes
            if key == "hours" and isinstance(value, (int, float)):
                value = value * 60
            minutes = parse_duration(value)
            break
    else:
        raise ParseError(f"{where}: missing duration (minutes / hours / duration)")
    if minutes <= 0:
        raise ParseError(f"{where}: duration must be positive")
    return {
        "category": category,
        "minutes": minutes,
        "title": title,
        "description": (raw.get("description") or title).strip(),
    }


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------
def from_json(data):
    if isinstance(data, dict) and isinstance(data.get("days"), list):
        data = data["days"]
    if isinstance(data, list):
        pairs = [(d.get("date"), d.get("entries")) for d in data if isinstance(d, dict)]
    elif isinstance(data, dict):
        pairs = list(data.items())
    else:
        raise ParseError("JSON must be an object keyed by date, or a list of days")

    out = {}
    for raw_date, entries in pairs:
        d = parse_date(raw_date)
        if not isinstance(entries, list) or not entries:
            raise ParseError(f"{d}: entries must be a non-empty list")
        key = d.strftime("%Y%m%d")
        out[key] = [normalise_entry(e, f"{d} entry {i + 1}") for i, e in enumerate(entries)]
    return out


# --------------------------------------------------------------------------
# plain text
# --------------------------------------------------------------------------
DAY_RE = re.compile(
    r"^(?:mon|tues|wednes|thurs|fri|satur|sun)day\b\s*[—–\-,:]?\s*"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?)",
    re.I,
)
ENTRY_RE = re.compile(r"^(.+?)\s+[—–\-]\s+(.+)$")
FIELD_RE = re.compile(r"^(title|description)\s*:\s*(.*)$", re.I)


def from_text(text):
    year_m = re.search(r"\b(20\d\d)\b", text)
    year = int(year_m.group(1)) if year_m else None

    out, day, entry, field = {}, None, None, None

    def close_entry():
        nonlocal entry
        if entry is not None:
            out[day].append(normalise_entry(entry, f"{day} entry {len(out[day]) + 1}"))
        entry = None

    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            field = None
            continue

        m = DAY_RE.match(line)
        if m:
            if day:
                close_entry()
            day = parse_date(m.group(1), year).strftime("%Y%m%d")
            out.setdefault(day, [])
            field = None
            continue

        if day is None or line.lower().startswith("total"):
            continue   # header/title lines, daily totals

        m = FIELD_RE.match(line)
        if m and entry is not None:
            field = m.group(1).lower()
            entry[field] = m.group(2).strip()
            continue

        m = ENTRY_RE.match(line)
        if m:
            try:
                minutes = parse_duration(m.group(2))
            except ParseError:
                minutes = None
            if minutes is not None:
                close_entry()
                entry = {"category": m.group(1).strip(), "minutes": minutes}
                field = None
                continue

        if entry is not None and field:
            entry[field] += " " + line   # wrapped title/description
            continue

        raise ParseError(f"Line {line_no}: don't know what to do with {line!r}")

    if day:
        close_entry()
    out = {d: e for d, e in out.items() if e}
    if not out:
        raise ParseError("No days found. Expected lines like 'Monday — 21 Sep'.")
    return out


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def resolve_category(name):
    for alias in CATEGORY_ALIASES.get(name, [name]):
        if alias in SITE_CATEGORIES:
            return alias, False
    for label in SITE_CATEGORIES:
        if label.lower() == name.lower():
            return label, False
    return DEFAULT_CATEGORY, True


def parse(text):
    """Return (entries_by_date, warnings, summary). Raises ParseError."""
    target = config.target_minutes()
    text = (text or "").strip()
    if not text:
        raise ParseError("Nothing pasted.")
    if text[0] in "{[":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON: {e.msg} (line {e.lineno}, column {e.colno})")
        entries = from_json(data)
    else:
        entries = from_text(text)

    entries = dict(sorted(entries.items()))
    warnings, summary = [], []
    for d, rows in entries.items():
        when = datetime.strptime(d, "%Y%m%d").date()
        total = sum(r["minutes"] for r in rows)
        if when.weekday() >= 5:
            warnings.append(f"{when:%a %d %b} is a weekend.")
        if total < target:
            warnings.append(f"{when:%a %d %b} totals {total // 60}h{total % 60:02d} - "
                            f"under the {target // 60}h{target % 60:02d} target.")
        for r in rows:
            site, fallback = resolve_category(r["category"])
            r["site_category"] = site
            if fallback:
                warnings.append(f"{when:%a %d %b}: unknown category {r['category']!r} "
                                f"will be filed as {site!r}.")
        summary.append({"date": d, "label": f"{when:%a %d %b %Y}",
                        "total": total, "entries": rows})
    return entries, warnings, {"days": summary, "target": target}

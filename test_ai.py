"""Run: python test_ai.py (or pytest)."""

from datetime import date

from ai import _check, _fix_minutes


def test_fix_minutes():
    days = [
        {"date": "2026-10-26", "entries": [
            {"category": "Development", "minutes": 50, "title": "A", "description": ""},
            {"category": "Testing", "minutes": 120, "title": "B", "description": ""},
        ]},                                                     # 165 -> must reach 540
        {"date": "2026-10-27", "entries": [
            {"category": "Development", "minutes": 390, "title": "C", "description": ""},
            {"category": "Testing", "minutes": 210, "title": "D", "description": ""},
        ]},                                                     # 600 -> must drop to 540
        {"date": "2026-10-28", "entries": []},                  # leave day untouched
    ]
    _fix_minutes(days, 540)
    assert _check(days, [date(2026, 10, d) for d in (26, 27, 28)], 540) == []
    assert days[1]["entries"][0]["minutes"] == 330   # shrinks the longest first
    assert days[2]["entries"] == []


if __name__ == "__main__":
    test_fix_minutes()
    print("ok")

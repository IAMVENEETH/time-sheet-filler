"""
Fills the HRStop daily timesheet.

    python fill_timesheet.py --list-tasks          # just print the real dropdown options
    python fill_timesheet.py --list-projects       # print your project options as JSON
    python fill_timesheet.py                       # dry run, saves nothing
    python fill_timesheet.py --save                # fill + click Save (draft) for every date in timesheet_data.py
    python fill_timesheet.py --date 20260903 --save
    python fill_timesheet.py --entries week.json --save   # entries from JSON instead of timesheet_data.py

This only ever clicks the "Save" button (keeps the day as a draft). It never
touches "Submit for Approval" - review on the site and submit that yourself.

Category resolution: whatever the dropdown actually contains wins. Anything
that can't be matched falls back to DEFAULT_CATEGORY. Every substitution is
printed. Selectors below were captured from the live page via inspect_form.py.

HRStop URL, project, login file and screenshot folder come from config.py
(~/.timesheet-filler/), set through the web UI's Settings tab.
"""

import argparse
import json
import re
from datetime import date

from playwright.sync_api import sync_playwright, expect

import config
from categories import CATEGORY_ALIASES, DEFAULT_CATEGORY

CFG = config.load()
BASE = CFG["hrstop_url"].rstrip("/") + "/TimeSheet/FillDaily"
STATE_FILE = str(config.AUTH_FILE)
SHOTS = config.SHOTS_DIR

MIN_MINUTES = config.target_minutes(CFG)   # floor, not a target - days may run longer

SELECTORS = {
    # tbody's last <tr> is a utility row (attach-document + add-row button),
    # not a data row - :has(select.ddlProject) excludes it.
    "row": "table#tbFillTimesheet tbody tr:visible:has(select.ddlProject)",
    "category": "select.ddlProjectTask",
    "project": "select.ddlProject",
    "hours": "input[name^='tblProjectHour_']",
    "title": "input[name^='tblProjectTitle_']",
    "description": "input[name^='tblProjectDescription_']",
    # label varies: "+ Add Row" on a blank day, plain "Add Row" once a row exists.
    "add_row": "input[type=button][value*='Add Row']",
    "save": "button[name='Command'][value='Save']:visible",
}

PROJECT = CFG["project"]   # e.g. "DS-DTS Email Auto"; other options are Leave/Holiday


# --------------------------------------------------------------------------
# category resolution
# --------------------------------------------------------------------------
def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read_options(page):
    """Return [(value, visible_text)] from the first category dropdown on the page."""
    sel = page.locator(SELECTORS["category"]).first
    if not sel.count():
        return []
    return sel.evaluate(
        "el => [...el.options].map(o => [o.value, o.textContent.trim()])"
    )


def build_resolver(options, wanted=()):
    """Map each wanted category onto an option label that actually exists."""
    by_norm = {norm(text): text for _value, text in options if text}
    resolved, notes = {}, []

    for want in set(CATEGORY_ALIASES) | {DEFAULT_CATEGORY} | set(wanted):
        for alias in CATEGORY_ALIASES.get(want, [want]):
            hit = by_norm.get(norm(alias))
            if hit:
                resolved[want] = hit
                if norm(alias) != norm(want):
                    notes.append(f"  {want!r} -> {hit!r}")
                break
        else:
            fallback = next(
                (by_norm[norm(a)] for a in CATEGORY_ALIASES.get(DEFAULT_CATEGORY, [DEFAULT_CATEGORY])
                 if norm(a) in by_norm),
                None,
            ) or next((t for _v, t in options if "analysis" in norm(t)), None)

            if not fallback:
                raise SystemExit(
                    f"Cannot resolve {want!r}, and no fallback matching "
                    f"{DEFAULT_CATEGORY!r} exists in the dropdown. "
                    f"Run --list-tasks and fix CATEGORY_ALIASES in timesheet_data.py."
                )
            resolved[want] = fallback
            notes.append(f"  {want!r} -> {fallback!r}   (FALLBACK - not in dropdown)")

    if notes:
        print("Category substitutions:")
        print("\n".join(sorted(set(notes))))
    return resolved


# --------------------------------------------------------------------------
# duration formatting
# --------------------------------------------------------------------------
# Confirmed via inspect_form.py against real saved entries (Sep 1-3): the
# Hours field always displays "H:MM" (e.g. "0:45", "1:30"), never decimal -
# regardless of what the page's help note claims. A blank row has no value
# to sniff a format from, so this is hardcoded rather than auto-detected.
def format_duration(minutes):
    return f"{minutes // 60}:{minutes % 60:02d}"


# --------------------------------------------------------------------------
# filling
# --------------------------------------------------------------------------
def set_text(row, key, value):
    box = row.locator(SELECTORS[key]).first
    if not box.count() or value is None:
        return
    box.fill("")
    box.type(str(value), delay=25)
    box.dispatch_event("change")   # JS-bound grids ignore a plain fill()


def set_project(page, row):
    """Select the project and wait for the category dropdown to populate.

    The category dropdown (ddlProjectTask) is a cascading dropdown filled
    via AJAX only after a project is chosen - on a blank row it starts out
    with just a "Select Task" placeholder.
    """
    if not PROJECT:
        return
    sel = row.locator(SELECTORS["project"]).first
    if not sel.count():
        return
    try:
        sel.select_option(label=PROJECT, timeout=5000)
    except Exception:
        raise SystemExit(f"Project {PROJECT!r} isn't in the project dropdown. "
                         f"Pick your project again in Settings.")
    sel.dispatch_event("change")

    cat = row.locator(SELECTORS["category"]).first
    if cat.count():
        try:
            page.wait_for_function(
                "el => el.options.length > 1", arg=cat.element_handle(), timeout=5000
            )
        except Exception:
            pass


def fill_row(row, entry, resolver):
    sel = row.locator(SELECTORS["category"]).first
    if sel.count():
        sel.select_option(label=resolver[entry["category"]])
        sel.dispatch_event("change")

    set_text(row, "hours", format_duration(entry["minutes"]))
    set_text(row, "title", entry["title"])
    set_text(row, "description", entry["description"])


def ensure_rows(page, count):
    rows = page.locator(SELECTORS["row"])
    while rows.count() < count:
        add = page.locator(SELECTORS["add_row"]).first
        if not add.count():
            raise SystemExit(f"Need {count} rows, only {rows.count()} available.")
        add.click()
        page.wait_for_timeout(600)
    return rows


def dismiss_cookie_banner(page):
    accept = page.locator("a#accept")
    if accept.count() and accept.first.is_visible():
        accept.first.click()
        page.wait_for_timeout(300)


def open_day(page, date):
    page.goto(f"{BASE}?StartDate={date}#", wait_until="networkidle")
    if "login" in page.url.lower():
        raise SystemExit("Session expired - log in to HRStop again")
    dismiss_cookie_banner(page)


def list_projects(page, date):
    open_day(page, date)
    ensure_rows(page, 1)
    sel = page.locator(SELECTORS["row"]).first.locator(SELECTORS["project"]).first
    opts = sel.evaluate(
        "el => [...el.options].filter(o => o.value && o.value !== '0')"
        ".map(o => o.textContent.trim())"
    )
    # stdout line the web UI looks for
    print("PROJECTS_JSON " + json.dumps([o for o in opts if o and not o.lower().startswith("select")]))


def fill_day(page, date, entries, save):
    open_day(page, date)

    rows = ensure_rows(page, len(entries))
    expect(rows.first).to_be_visible(timeout=15000)

    # Project must be chosen before the category dropdown has real options.
    for i in range(len(entries)):
        set_project(page, rows.nth(i))

    resolver = build_resolver(read_options(page), {e["category"] for e in entries})
    total = sum(e["minutes"] for e in entries)
    flag = "" if total >= MIN_MINUTES else f"  << UNDER {MIN_MINUTES // 60}h MINIMUM"
    print(f"\n=== {date} | {len(entries)} entries | {total // 60}h{total % 60:02d} ==={flag}")

    for i, entry in enumerate(entries):
        fill_row(rows.nth(i), entry, resolver)
        print(f"  [{i}] {resolver[entry['category']]:<22}"
              f"{format_duration(entry['minutes']):>7}  {entry['title']}")

    page.screenshot(path=str(SHOTS / f"preview_{date}.png"), full_page=True)

    if save:
        page.locator(SELECTORS["save"]).first.click()
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SHOTS / f"saved_{date}.png"), full_page=True)
        print(f"  saved (draft) -> saved_{date}.png")
    else:
        print(f"  dry run -> preview_{date}.png")
        page.wait_for_timeout(4000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="fill only this date (YYYYMMDD)")
    ap.add_argument("--save", action="store_true",
                    help="click Save (keeps it a draft) - without this, dry run only")
    ap.add_argument("--list-tasks", action="store_true",
                    help="print the real dropdown options and exit")
    ap.add_argument("--list-projects", action="store_true",
                    help="print the project dropdown options as JSON and exit")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--entries", help="JSON file of {YYYYMMDD: [entries]} - default is timesheet_data.py")
    args = ap.parse_args()

    if not config.AUTH_FILE.exists():
        raise SystemExit("Session expired - log in to HRStop first")

    if args.list_projects:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args.headless)
            page = browser.new_context(storage_state=STATE_FILE).new_page()
            list_projects(page, args.date or date.today().strftime("%Y%m%d"))
            browser.close()
        return

    if not PROJECT:
        raise SystemExit("No HRStop project set. Choose one in Settings first.")

    if args.entries:
        with open(args.entries, encoding="utf-8") as f:
            entries_by_date = json.load(f)
    else:
        from timesheet_data import ENTRIES   # personal, not in git
        entries_by_date = ENTRIES

    dates = [args.date] if args.date else sorted(entries_by_date)
    for d in dates:
        if d not in entries_by_date:
            raise SystemExit(f"No entries defined for {d}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=120)
        ctx = browser.new_context(storage_state=STATE_FILE)
        page = ctx.new_page()

        if args.list_tasks:
            page.goto(f"{BASE}?StartDate={dates[0]}#", wait_until="networkidle")
            opts = read_options(page)
            if not opts:
                print("No category dropdown matched. Widen SELECTORS['category'] "
                      "using inspect_form.py output.")
            for value, text in opts:
                print(f"  {text!r}   (value={value!r})")
            print("\nHow your categories resolve against those options:")
            build_resolver(opts)
            browser.close()
            return

        for d in dates:
            fill_day(page, d, entries_by_date[d], args.save)

        browser.close()
        if not args.save:
            print(f"\nNothing was saved. Check the preview_*.png files in {SHOTS}, then add --save.")
        else:
            print("\nSaved as drafts. Review and click 'Submit for Approval' on the site yourself.")


if __name__ == "__main__":
    main()

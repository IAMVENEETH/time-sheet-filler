"""
Prints every input / select / textarea on the timesheet page, plus the
structure of any grid rows. Paste the output back to me and I'll finalize
the fill script with real selectors.

    python inspect_form.py
"""

import json
from playwright.sync_api import sync_playwright

import config

URL = config.load()["hrstop_url"].rstrip("/") + "/TimeSheet/FillDaily?StartDate=20260901#"
STATE_FILE = str(config.AUTH_FILE)

JS = """
() => {
  const out = [];
  document.querySelectorAll('input, select, textarea').forEach(el => {
    if (el.type === 'hidden') return;
    const rec = {
      tag: el.tagName.toLowerCase(),
      type: el.type || null,
      name: el.name || null,
      id: el.id || null,
      placeholder: el.placeholder || null,
      class: el.className || null,
      value: el.value ? String(el.value).slice(0, 40) : null,
    };
    if (el.tagName === 'SELECT') {
      rec.options = [...el.options].slice(0, 15).map(o => ({
        value: o.value, text: o.textContent.trim()
      }));
    }
    // nearest label-ish text
    const lbl = el.labels && el.labels[0];
    rec.label = lbl ? lbl.textContent.trim() : null;
    out.push(rec);
  });
  return out;
}
"""

TABLES_JS = """
() => [...document.querySelectorAll('table')].map((t, i) => ({
  index: i,
  id: t.id || null,
  class: t.className || null,
  headers: [...t.querySelectorAll('th')].map(h => h.textContent.trim()),
  rowCount: t.querySelectorAll('tbody tr').length,
}))
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=STATE_FILE)
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")

        print("=== FORM CONTROLS ===")
        print(json.dumps(page.evaluate(JS), indent=2))

        print("\n=== TABLES ===")
        print(json.dumps(page.evaluate(TABLES_JS), indent=2))

        print("\n=== BUTTONS ===")
        for b in page.locator("button, input[type=submit], a.btn").all():
            try:
                print(f"  {b.evaluate('e => e.outerHTML').strip()[:160]}")
            except Exception:
                pass

        page.screenshot(path="timesheet_page.png", full_page=True)
        print("\nScreenshot saved to timesheet_page.png")
        browser.close()


if __name__ == "__main__":
    main()

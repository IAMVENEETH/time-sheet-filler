"""
Opens a real browser, you log in by hand (including 2FA), then it saves the
session to ~/.timesheet-filler/auth.json so the filler can reuse it.

The web UI runs this for you ("Log in to HRStop"). From a terminal:

    python save_login.py
"""

from playwright.sync_api import sync_playwright

import config


def main():
    cfg = config.load()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(cfg["hrstop_url"].rstrip("/") + "/")

        print("Log in in the browser window (finish any 2FA too).")
        input("Press Enter here once you're on the dashboard... ")

        ctx.storage_state(path=str(config.AUTH_FILE))
        config.private(config.AUTH_FILE)   # session cookies
        print("Saved HRStop login.")
        browser.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Instagram Bulk Unfollow Script
-------------------------------
Uses Playwright to automate unfollowing in your browser.
YOU log in manually — no credentials are stored.

Setup:
    pip install playwright
    playwright install chromium

Run:
    python instagram_unfollow.py

Options (edit the CONFIG block below):
    UNFOLLOW_LIMIT   - max users to unfollow in one session (0 = no limit)
    DELAY_BETWEEN    - seconds to wait between each unfollow (recommended: 3-6)
    BATCH_SIZE       - pause after this many unfollows
    BATCH_PAUSE      - seconds to pause between batches

WARNING: Automating Instagram actions may violate their Terms of Service
and can result in temporary action blocks or account restrictions.
Run in small batches and use realistic delays to reduce this risk.
"""

import asyncio
import random
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ─── CONFIG ───────────────────────────────────────────────────────────────────
INSTAGRAM_USERNAME = "iammahendrarao"   # your Instagram handle (no @)
UNFOLLOW_LIMIT     = 50                 # unfollows per session (0 = unlimited)
DELAY_BETWEEN      = 4                  # seconds between each unfollow
DELAY_JITTER       = 2                  # random ±jitter added to DELAY_BETWEEN
BATCH_SIZE         = 10                 # pause after every N unfollows
BATCH_PAUSE        = 30                 # seconds to pause between batches
PROGRESS_FILE      = "unfollow_progress.txt"  # tracks who was already unfollowed
# ──────────────────────────────────────────────────────────────────────────────


def load_progress() -> set:
    p = Path(PROGRESS_FILE)
    if p.exists():
        return set(p.read_text().splitlines())
    return set()


def save_progress(skipped: set) -> None:
    Path(PROGRESS_FILE).write_text("\n".join(skipped))


async def wait(base: float, jitter: float = 0) -> None:
    delay = base + random.uniform(0, jitter)
    await asyncio.sleep(delay)


async def login_and_wait(page) -> None:
    print("\n[*] Opening Instagram login page...")
    await page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
    print("[*] Please log in manually in the browser window.")
    print("[*] Waiting up to 90 seconds for you to complete login...")
    try:
        # Wait until we're redirected away from the login page
        await page.wait_for_url(
            lambda url: "login" not in url and "instagram.com" in url,
            timeout=90_000,
        )
        await wait(3, 2)
        print("[+] Logged in successfully.")
    except PlaywrightTimeout:
        print("[-] Timed out waiting for login. Exiting.")
        sys.exit(1)


async def open_following_list(page) -> None:
    profile_url = f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"
    print(f"\n[*] Navigating to profile: {profile_url}")
    await page.goto(profile_url, wait_until="networkidle")
    await wait(2, 1)

    # Click the "Following" count link
    try:
        following_link = page.get_by_role("link", name=lambda n: "following" in n.lower())
        await following_link.first.click()
        await wait(2, 1)
        print("[+] Opened Following list.")
    except Exception:
        # Fallback: find anchor whose href ends in /following/
        following_link = page.locator(f'a[href="/{INSTAGRAM_USERNAME}/following/"]')
        await following_link.click()
        await wait(2, 1)
        print("[+] Opened Following list (fallback).")


async def scroll_dialog_to_load(page, dialog) -> None:
    """Scroll the following list dialog to trigger lazy loading."""
    for _ in range(3):
        await dialog.evaluate("el => el.scrollTop += 600")
        await wait(1.5, 0.5)


async def unfollow_all(page) -> None:
    already_done = load_progress()
    unfollowed_count = 0

    print("\n[*] Starting unfollow loop. Press Ctrl+C to stop safely.\n")

    while True:
        if UNFOLLOW_LIMIT > 0 and unfollowed_count >= UNFOLLOW_LIMIT:
            print(f"\n[+] Reached session limit of {UNFOLLOW_LIMIT} unfollows.")
            break

        # The following-list dialog
        try:
            dialog = page.locator('div[role="dialog"]').last
            await dialog.wait_for(state="visible", timeout=8_000)
        except PlaywrightTimeout:
            print("[-] Following dialog not visible. Re-opening...")
            await open_following_list(page)
            await wait(2)
            continue

        # Collect all visible "Following" buttons (the blue/grey button next to each user)
        buttons = await dialog.locator('button:has-text("Following")').all()

        if not buttons:
            # Try scrolling to load more
            await scroll_dialog_to_load(page, dialog)
            buttons = await dialog.locator('button:has-text("Following")').all()

        if not buttons:
            print("\n[+] No more 'Following' buttons found — you may have unfollowed everyone!")
            break

        clicked_any = False
        for btn in buttons:
            if UNFOLLOW_LIMIT > 0 and unfollowed_count >= UNFOLLOW_LIMIT:
                break

            # Try to grab the username from the nearby row
            try:
                row = btn.locator("xpath=ancestor::div[@role='button' or contains(@class,'x')]").first
                username_el = row.locator("span").first
                username = (await username_el.inner_text()).strip()
            except Exception:
                username = f"user_{unfollowed_count + 1}"

            if username in already_done:
                continue

            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await wait(1, 0.5)

                # Confirm the "Unfollow" in the confirmation dialog
                confirm = page.get_by_role("button", name="Unfollow")
                if await confirm.count() > 0:
                    await confirm.click()
                    await wait(0.5)

                unfollowed_count += 1
                already_done.add(username)
                save_progress(already_done)
                clicked_any = True
                print(f"  [{unfollowed_count}] Unfollowed: {username}")

                # Delay between unfollows
                await wait(DELAY_BETWEEN, DELAY_JITTER)

                # Batch pause
                if unfollowed_count % BATCH_SIZE == 0:
                    print(f"\n[~] Batch pause: waiting {BATCH_PAUSE}s after {unfollowed_count} unfollows...\n")
                    await wait(BATCH_PAUSE)

            except Exception as e:
                print(f"  [!] Could not unfollow {username}: {e}")
                continue

        if not clicked_any:
            # Scroll to load more entries
            await scroll_dialog_to_load(page, dialog)
            await wait(1)

    print(f"\n[+] Done. Total unfollowed this session: {unfollowed_count}")


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await login_and_wait(page)
            await open_following_list(page)
            await unfollow_all(page)
        except KeyboardInterrupt:
            print("\n[!] Interrupted by user. Progress saved.")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

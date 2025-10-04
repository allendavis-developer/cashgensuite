import argparse
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = Path(__file__).parent / "playwright_user_data"

async def main():
    parser = argparse.ArgumentParser(description='Automate item listing')
    parser.add_argument('--item_name', required=True, help='Item name')
    parser.add_argument('--description', required=True, help='Item description')
    parser.add_argument('--price', required=True, help='Item price')
    parser.add_argument('--serial_number', required=False, help='Item serial number')

    args = parser.parse_args()

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            slow_mo=500
        )

        try:
            page = await browser.new_page()
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })

            print(f"Starting automation for item: {args.item_name}", flush=True)
            print(f"Description: {args.description}", flush=True)
            print(f"Price: £{args.price}", flush=True)

            print("Opening WebEpos login page...", flush=True)
            await page.goto("https://webepos.cashgenerator.co.uk")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_url("https://webepos.cashgenerator.co.uk/")

            print("[OK] Logged in or existing session detected!", flush=True)

            print("Navigating to the New Product page...", flush=True)
            await page.goto("https://webepos.cashgenerator.co.uk/products/new")
            await page.wait_for_load_state("networkidle")

            print("[OK] New Product page opened.", flush=True)

            # Toggle switch OFF
            await page.wait_for_selector("#normal-switch")
            await page.evaluate("""
            () => {
                const handle = document.querySelector('#normal-switch');
                const bg = handle.parentElement.querySelector('.react-switch-bg');
                const checkIcon = bg.children[0];
                const crossIcon = bg.children[1];

                if (handle.getAttribute('aria-checked') === 'true') {
                    handle.setAttribute('aria-checked', 'false');
                    handle.style.transform = 'translateX(0px)';
                    bg.style.background = '#ccc';
                    checkIcon.style.opacity = '0';
                    crossIcon.style.opacity = '1';
                }
            }
            """)


            # Fill Product Name
            await page.fill("#title", args.item_name)

            # Set Store to Warrington
            await page.select_option("#storeId", "4157a468-0220-45a4-bd51-e3dffe2ce7f0")

            # Fill Product Description
            await page.fill('textarea[name="intro"]', args.description)

            # Fill Price
            if args.price.replace('.', '', 1).isdigit():
                await page.fill("#price", args.price)
            else:
                print(f"[WARN] Skipping price field, invalid value: {args.price}", flush=True)

            if args.serial_number:
                await page.fill("#barcode", args.serial_number)
                print("[OK] Barcode entered and grade set to B.", flush=True)


            await page.select_option("#fulfilmentOption", "anyfulfilment")
            await page.select_option("#condition", "used")

            await page.wait_for_selector("#grade", state="visible")
            await page.select_option("#grade", "B")

            print("[OK] Fulfilment method and condition set.", flush=True)


            print("[OK] Form fields filled.", flush=True)

           # Wait for the Save Product button to appear
            await page.wait_for_selector("button:has-text('Save Product')")

            await page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button.btn'));
                const saveButton = buttons.find(b => b.textContent.trim() === 'Save Product');
                if (saveButton) saveButton.scrollIntoView({block: 'center', inline: 'center'});
            }
            """)

            await asyncio.sleep(3)

            # Click the button
            await page.click("button:has-text('Save Product')", force=True)

            print("[OK] Clicked Save button with force click (fallback).", flush=True)

            # Wait for the user to close the browser
            print("[INFO] Browser is open. Please close it manually to continue...", flush=True)
            await browser.wait_for_event("close")

            # Final message after browser is closed
            print("Automation finished successfully.", flush=True)


        except Exception as e:
            print(f" Error during automation: {e}", flush=True)
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

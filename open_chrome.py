from playwright.sync_api import sync_playwright

print("Starting...")

with sync_playwright() as p:
    print("Connecting to Chrome...")
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    print("Connected.")

    print(f"Contexts found: {len(browser.contexts)}")
    if not browser.contexts:
        raise Exception("No browser context found")

    context = browser.contexts[0]
    print(f"Pages found: {len(context.pages)}")

    page = context.pages[0] if context.pages else context.new_page()
    print("Opening Teams...")
    page.goto("https://teams.microsoft.com/v2/", wait_until="domcontentloaded", timeout=60000)
    print("Page opened:", page.url)

    input("Press Enter to close...")
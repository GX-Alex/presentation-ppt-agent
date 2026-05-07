from playwright.sync_api import sync_playwright
import json


def check_page(browser, url: str):
    page = browser.new_page()
    console_messages = []
    page_errors = []
    page.on("console", lambda msg: console_messages.append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    response = page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    title = page.title()
    result = {
        "url": url,
        "status": response.status if response else None,
        "title": title,
        "pageErrors": page_errors,
        "severeConsole": [item for item in console_messages if item["type"] == "error"],
    }
    page.close()
    return result


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        results = [
            check_page(browser, "http://localhost:3002/"),
            check_page(browser, "http://localhost:3002/chat/new"),
        ]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        browser.close()

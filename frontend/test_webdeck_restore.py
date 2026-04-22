"""
Web Deck Restore Test
Tests: create plan-ready webdeck outline -> leave conversation -> re-enter same task -> outline and workspace manifest are restored
"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def run_test() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})

        try:
            print("1. Opening frontend...")
            page.goto("http://localhost:3000", wait_until="networkidle")
            page.wait_for_timeout(2000)

            print("2. Creating a webdeck outline...")
            input_box = page.locator("textarea").first
            input_box.fill("帮我生成一个关于 AI 发展趋势的 PPT，给管理层汇报")
            input_box.press("Enter")

            page.wait_for_selector("text=填写高质量 Brief", timeout=30000)
            page.get_by_role("button", name="填写高质量 Brief").click()
            page.locator('input[placeholder*="AI 客服改造方案"]').first.fill("AI 发展趋势管理层汇报")
            page.get_by_role("button", name="确认并提交 Brief").click()

            page.wait_for_selector("text=Web Deck 大纲已生成", timeout=120000)
            page.wait_for_selector("text=受众:", timeout=120000)

            task_url = page.url
            print(f"   Task URL: {task_url}")
            if task_url.endswith("/chat/new"):
                print("   ✗ Task URL did not switch to a concrete chat route")
                return 1

            print("3. Leaving and re-entering the same conversation...")
            page.goto("http://localhost:3000/gallery", wait_until="networkidle")
            page.wait_for_timeout(1000)
            page.goto(task_url, wait_until="networkidle")

            print("4. Verifying outline restoration...")
            page.wait_for_selector("text=Web Deck 大纲已生成", timeout=60000)
            page.wait_for_selector("text=受众:", timeout=60000)

            confirm_buttons = page.get_by_role("button", name="确认并开始生成")
            if confirm_buttons.count() < 2:
                print("   ✗ Expected both chat-side and workspace-side confirm buttons after restore")
                return 1

            print("   ✓ Web Deck outline and workspace manifest were restored")
            return 0
        except PlaywrightTimeoutError as exc:
            print(f"   ✗ Timed out: {exc}")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(run_test())
"""
Web Deck Chat Flow Test
Tests: zero-to-one request -> quality brief -> webdeck manifest -> chat-side approval -> webdeck runtime starts
"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def run_test() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})

        console_logs: list[str] = []
        websocket_frames: list[str] = []
        failed_requests: list[str] = []
        failed_responses: list[str] = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.failure or 'requestfailed'} {req.url}"))
        page.on("response", lambda resp: failed_responses.append(f"{resp.status} {resp.url}") if resp.status >= 400 else None)

        def handle_websocket(ws) -> None:
            websocket_frames.append(f"[open] {ws.url}")
            ws.on("framesent", lambda payload: websocket_frames.append(f"[sent] {payload}"))
            ws.on("framereceived", lambda payload: websocket_frames.append(f"[recv] {payload}"))

        page.on("websocket", handle_websocket)

        try:
            print("1. Opening frontend...")
            page.goto("http://localhost:3000", wait_until="networkidle")
            page.wait_for_timeout(2000)

            if page.locator("text=连接已断开").count() == 0:
                print("   ✓ WebSocket connected")
            else:
                print("   ✗ WebSocket not connected")
                return 1

            print("2. Sending zero-to-one deck request...")
            input_box = page.locator("textarea").first
            input_box.fill("帮我生成一个关于 AI 发展趋势的 PPT，给管理层汇报")
            input_box.press("Enter")

            print("3. Opening quality brief dialog...")
            page.wait_for_selector("text=填写高质量 Brief", timeout=30000)
            page.get_by_role("button", name="填写高质量 Brief").click()

            topic_input = page.locator('input[placeholder*="AI 客服改造方案"]').first
            topic_input.fill("AI 发展趋势管理层汇报")
            page.get_by_role("button", name="确认并提交 Brief").click()

            print("4. Waiting for Web Deck manifest...")
            page.wait_for_selector("text=Web Deck 大纲已生成", timeout=120000)
            chat_confirm = page.locator(
                "xpath=//span[contains(., 'Web Deck 规划预览')]/ancestor::div[contains(@class,'bento-card')][1]//button[contains(., '确认并开始生成')]"
            ).first
            chat_confirm.wait_for(state="visible", timeout=120000)
            print("   ✓ Web Deck manifest received")

            print("5. Approving from chat-side outline card...")
            if chat_confirm.count() == 0:
                print("   ✗ Chat-side confirm button not found")
                return 1
            chat_confirm.click()

            print("6. Verifying Web Deck runtime starts...")
            page.wait_for_selector("text=页面目录", timeout=60000)
            print("   ✓ Web Deck generation entered runtime view")

            legacy_status = page.locator("text=已确认大纲，开始生成幻灯片").count()
            if legacy_status > 0:
                print("   ✗ Legacy PPT confirmation status appeared")
                return 1

            page.screenshot(path="/tmp/webdeck_chat_flow.png", full_page=True)
            print("   Screenshot saved to /tmp/webdeck_chat_flow.png")

            errors = [line for line in console_logs if "error" in line.lower()]
            if errors:
                print(f"\nConsole errors ({len(errors)}):")
                for err in errors[:5]:
                    print(f"  {err}")

            if failed_responses or failed_requests:
                print("\nFailed resources:")
                for item in (failed_responses + failed_requests)[:10]:
                    print(f"  {item}")

            print("\nTest completed!")
            return 0
        except PlaywrightTimeoutError as exc:
            print(f"   ✗ Timed out: {exc}")
            try:
                page.screenshot(path="/tmp/webdeck_chat_flow_failure.png", full_page=True)
                print("   Failure screenshot saved to /tmp/webdeck_chat_flow_failure.png")
            except Exception:
                pass

            print("\nVisible text snapshot:")
            try:
                body_text = page.locator("body").inner_text()
                for line in body_text.splitlines()[:120]:
                    print(f"  {line}")
            except Exception as snapshot_exc:
                print(f"  <failed to read page text: {snapshot_exc}>")

            if websocket_frames:
                print(f"\nWebSocket frames ({len(websocket_frames)}):")
                for frame in websocket_frames[-30:]:
                    print(f"  {frame}")

            if console_logs:
                print(f"\nConsole tail ({min(len(console_logs), 20)}):")
                for line in console_logs[-20:]:
                    print(f"  {line}")

            if failed_responses or failed_requests:
                print("\nFailed resources:")
                for item in (failed_responses + failed_requests)[:20]:
                    print(f"  {item}")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(run_test())
from __future__ import annotations

import json
import pathlib
import urllib.request
from playwright.sync_api import sync_playwright

PROJECT_ID = "b667d88b-ea00-417a-a2d6-98c402bc00c4"
PUBLISH_URL = f"http://localhost:8002/api/webdeck/projects/{PROJECT_ID}/publish"
OUTPUT_HTML = pathlib.Path("/Users/guoguo/quantlearn/generalagent/tmp/webdeck-export-e2e.html")
SCREENSHOT = pathlib.Path("/Users/guoguo/quantlearn/generalagent/tmp/webdeck-export-e2e-p08.png")

req = urllib.request.Request(PUBLISH_URL, method="POST")
with urllib.request.urlopen(req, timeout=60) as resp:
    payload = json.loads(resp.read().decode("utf-8"))

html = payload["html"]
OUTPUT_HTML.write_text(html, encoding="utf-8")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    console_messages = []
    page_errors = []
    page.on("console", lambda msg: console_messages.append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    page.goto(OUTPUT_HTML.as_uri(), wait_until="load", timeout=60000)
    page.wait_for_function("() => !!window.echarts", timeout=30000)
    page.evaluate("() => { if (typeof window.goToPage === 'function') window.goToPage(7); }")
    page.wait_for_function(
        """() => {
          const el = document.getElementById('p08_chart_1');
          return !!(window.echarts && el && window.echarts.getInstanceByDom && window.echarts.getInstanceByDom(el));
        }""",
        timeout=30000,
    )
    page.wait_for_timeout(1200)
    snapshot = page.evaluate(
        """() => {
          const el = document.getElementById('p08_chart_1');
          const instance = window.echarts && el && window.echarts.getInstanceByDom ? window.echarts.getInstanceByDom(el) : null;
          const rect = el ? el.getBoundingClientRect() : null;
          return {
            currentPage: typeof window.currentPage === 'number' ? window.currentPage : null,
            hasEcharts: !!window.echarts,
            hasInstance: !!instance,
            width: rect ? rect.width : 0,
            height: rect ? rect.height : 0,
            executedScripts: document.querySelectorAll('script[data-webdeck-executed="true"]').length,
            activeSlideCount: document.querySelectorAll('.deck-slide.active').length,
          };
        }"""
    )
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    browser.close()

result = {
    "publish_version": payload.get("version"),
    "output_html": str(OUTPUT_HTML),
    "screenshot": str(SCREENSHOT),
    "snapshot": snapshot,
    "pageErrors": page_errors,
    "severeConsole": [item for item in console_messages if item["type"] == "error"],
}
print(json.dumps(result, ensure_ascii=False, indent=2))

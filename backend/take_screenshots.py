"""Take screenshots of the generated WebDeck for visual quality review."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        await page.goto("file:///tmp/webdeck_test_AI客服改造方案.html", wait_until="commit")
        await page.wait_for_timeout(2000)  # Wait for any animations
        
        # Screenshot page 1 (cover)
        await page.screenshot(path="/tmp/webdeck_p01_cover.png")
        print("✅ Screenshot 1: Cover page")
        
        # Navigate to page 3 (summary)
        await page.evaluate("goToPage(2)")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="/tmp/webdeck_p03_summary.png")
        print("✅ Screenshot 3: Executive Summary")
        
        # Navigate to page 7 (architecture)
        await page.evaluate("goToPage(6)")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="/tmp/webdeck_p07_architecture.png")
        print("✅ Screenshot 7: Architecture")
        
        # Navigate to page 9 (roadmap)
        await page.evaluate("goToPage(8)")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="/tmp/webdeck_p09_roadmap.png")
        print("✅ Screenshot 9: Roadmap")
        
        # Navigate to page 10 (chart)
        await page.evaluate("goToPage(9)")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="/tmp/webdeck_p10_chart.png")
        print("✅ Screenshot 10: Chart Analysis")
        
        # Navigate to closing page
        await page.evaluate("goToPage(11)")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="/tmp/webdeck_p12_closing.png")
        print("✅ Screenshot 12: Closing")
        
        await browser.close()
        print("\nAll screenshots saved to /tmp/webdeck_p*.png")


asyncio.run(main())

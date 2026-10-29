import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

ARTIFACT_DIR = Path(r"C:\Users\trung\.gemini\antigravity\brain\efa61927-da36-40cc-ae4a-cb20bb3d2d3c")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        page.on("console", lambda msg: print(f"[Browser Console] {msg.type}: {msg.text}"))
        page.on("pageerror", lambda err: print(f"[Browser Error] {err}"))
        
        print("Navigating to http://127.0.0.1:8006...")
        await page.goto("http://127.0.0.1:8006", wait_until="domcontentloaded")
        
        # In các element trên trang
        btn = await page.query_selector("#btnAnalyze")
        print("btnAnalyze found:", btn is not None)
        
        input_el = await page.query_selector("#productUrl")
        print("productUrl input found:", input_el is not None)
        
        await page.fill("#productUrl", "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html")
        await page.click("#btnAnalyze")
        
        # Đợi 3s và chụp màn hình xem trạng thái đang loading hay lỗi gì
        await asyncio.sleep(3)
        out_debug = ARTIFACT_DIR / "debug_browser_state.png"
        await page.screenshot(path=str(out_debug))
        print("Debug screenshot saved.")
        
        is_loading = await page.is_visible("#loading")
        is_result = await page.is_visible("#resultCard")
        print(f"Is loading: {is_loading}, Is result visible: {is_result}")
        
        if is_loading:
            # Đợi thêm nếu đang loading
            await asyncio.sleep(4)
            is_result = await page.is_visible("#resultCard")
            print(f"After wait, is result visible: {is_result}")

        out_final = ARTIFACT_DIR / "soi_review_high_concurrency_verified.png"
        await page.screenshot(path=str(out_final), full_page=True)
        print("Final screenshot saved.")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

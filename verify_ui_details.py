import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

ARTIFACT_DIR = Path(r"C:\Users\trung\.gemini\antigravity\brain\efa61927-da36-40cc-ae4a-cb20bb3d2d3c")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1100})
        
        await page.goto("http://127.0.0.1:8006", wait_until="domcontentloaded")
        await page.fill("#productUrl", "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html")
        await page.click("#btnAnalyze")
        
        await page.wait_for_selector("#resultCard:not(.hidden)", timeout=10000)
        await asyncio.sleep(1)
        
        name = await page.inner_text("#resProductName")
        score = await page.inner_text("#scoreValue")
        verdict = await page.inner_text("#verdictBadge")
        speed_badge = await page.inner_text("#certSpeedBadge")
        is_speed_visible = await page.is_visible("#certSpeedBadge")
        pool = await page.inner_text("#poolText")
        
        # Lấy các tiêu chí bóc tách lỗi
        flaw_titles = await page.eval_on_selector_all(".flaw-title", "els => els.map(e => e.textContent.trim())")
        
        print(f"Product: {name}")
        print(f"Score: {score}/100 | Verdict: {verdict}")
        print(f"Speed badge: '{speed_badge}' (Visible: {is_speed_visible})")
        print(f"Pool status text: {pool}")
        print(f"Flaw titles: {flaw_titles}")
        
        # Chụp riêng khu vực certificate
        result_el = await page.query_selector("#resultCard")
        if result_el:
            cert_path = ARTIFACT_DIR / "soi_review_high_concurrency_cert.png"
            await result_el.screenshot(path=str(cert_path))
            print(f"Cert screenshot saved to: {cert_path}")
            
        full_path = ARTIFACT_DIR / "soi_review_high_concurrency_full.png"
        await page.screenshot(path=str(full_path), full_page=True)
        print(f"Full page screenshot saved to: {full_path}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

import httpx
import urllib.parse

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://beecost.vn/",
    "Origin": "https://beecost.vn"
}

url = "https://shopee.vn/Tinh-ch%E1%BA%A5t-d%C6%B0%E1%BB%A1ng-s%C3%A1ng-da-m%E1%BB%9D-th%C3%A2m-Innisfree-Vitamin-C-Green-Tea-Enzyme-Brightening-Serum-30ml-i.304005953.22070119859"
ep = f"https://apiv3.beecost.vn/search/product?product_url={urllib.parse.quote(url)}"

try:
    with httpx.Client(headers=headers, timeout=6.0) as client:
        r = client.get(ep)
        print("Status:", r.status_code)
        if r.status_code == 200:
            print(r.text[:500])
        else:
            print("Response:", r.text[:200])
except Exception as e:
    print("Error:", e)

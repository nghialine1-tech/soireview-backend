import httpx
import urllib.parse
import re

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://beecost.vn/",
    "Origin": "https://beecost.vn"
}

# Test different query parameter formats
url = "https://shopee.vn/product/304005953/22070119859"
endpoints = [
    f"https://apiv3.beecost.vn/search/product?product_url={urllib.parse.quote(url, safe='')}",
    f"https://apiv3.beecost.vn/search/product?url={urllib.parse.quote(url, safe='')}",
    f"https://apiv3.beecost.vn/product/search?product_url={urllib.parse.quote(url, safe='')}",
]

with httpx.Client(headers=headers, timeout=5.0) as client:
    for ep in endpoints:
        try:
            r = client.get(ep)
            print(f"URL: {ep[:50]}... => Status: {r.status_code}")
            if r.status_code == 200:
                print("Body:", r.text[:200])
        except Exception as e:
            print(f"Error {ep}: {e}")

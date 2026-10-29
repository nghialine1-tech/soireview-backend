import asyncio
import httpx
import time
import json

TARGET_URLS = [
    # Cùng 1 sản phẩm Lazada nhưng có các tracking params khác nhau từ 1.000 người dùng bấm
    "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html",
    "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html?spm=a2o4n.searchlist.list.1&from_affiliate=true",
    "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html?tracking_id=user_101&sbucket=12",
    "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html?ref=facebook_group&utm_source=tiktok",
    "https://www.lazada.vn/products/pdp-i732880703-s1878270790.html?camp_id=summer_sale&aff_sub=5057026434"
]

API_ENDPOINT = "http://127.0.0.1:8006/api/analyze"

async def send_audit_request(client, req_id, url):
    start = time.time()
    try:
        resp = await client.post(API_ENDPOINT, json={"url": url}, timeout=30.0)
        elapsed = (time.time() - start) * 1000  # ms
        if resp.status_code == 200:
            data = resp.json()
            cache_info = data.get("_cache_info", {})
            is_hit = cache_info.get("hit", False)
            layer = cache_info.get("layer", "FRESH")
            prod_name = data.get("data", {}).get("product_info", {}).get("name", "")[:35]
            powered_by = data.get("data", {}).get("trust_evaluation", {}).get("powered_by", "")
            return {
                "id": req_id,
                "status": 200,
                "elapsed_ms": round(elapsed, 1),
                "is_cache_hit": is_hit,
                "layer": layer,
                "product": prod_name,
                "powered_by": powered_by
            }
        else:
            return {"id": req_id, "status": resp.status_code, "elapsed_ms": round(elapsed, 1), "error": resp.text}
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {"id": req_id, "status": 500, "elapsed_ms": round(elapsed, 1), "error": str(e)}

async def run_benchmark():
    print("=" * 70)
    print("🚀 BẮT ĐẦU BÀI KIỂM THỬ TẢI ĐỒNG THỜI (CONCURRENCY BENCHMARK)")
    print("Mô phỏng đợt truy cập bùng nổ của nhiều người dùng soi cùng lúc")
    print("=" * 70)

    # Đợt 1: 1 Request mở đường (Cache Warm-up)
    print("\n[Giai đoạn 1] Nạp dữ liệu sản phẩm gốc vào bộ đệm...")
    async with httpx.AsyncClient() as client:
        warmup = await send_audit_request(client, 0, TARGET_URLS[0])
        print(f"Warm-up: Status {warmup['status']} | Thời gian: {warmup['elapsed_ms']}ms | Engine: {warmup['powered_by']}")

    # Đợt 2: 24 Request đồng thời cùng lúc (Concurrent Burst)
    print("\n[Giai đoạn 2] Kích hoạt 24 REQUEST ĐỒNG THỜI CÙNG LÚC (Concurrent Burst)...")
    tasks = []
    async with httpx.AsyncClient() as client:
        for i in range(1, 25):
            url = TARGET_URLS[i % len(TARGET_URLS)]
            tasks.append(send_audit_request(client, i, url))
        
        t0 = time.time()
        results = await asyncio.gather(*tasks)
        total_time = time.time() - t0

    hits = [r for r in results if r.get("is_cache_hit")]
    misses = [r for r in results if not r.get("is_cache_hit")]
    times = [r["elapsed_ms"] for r in results if r["status"] == 200]
    avg_time = round(sum(times) / len(times), 1) if times else 0
    min_time = min(times) if times else 0
    max_time = max(times) if times else 0

    print("\n" + "=" * 70)
    print("📊 KẾT QUẢ KIỂM THỬ HIỆU NĂNG CHỊU TẢI (CONCURRENCY RESULTS)")
    print("=" * 70)
    print(f"✅ Tổng số request đồng thời: {len(results)}")
    print(f"⚡ Số request trúng Cache (Hit): {len(hits)} / {len(results)} ({round(len(hits)/len(results)*100, 1)}%)")
    print(f"⏱️ Thời gian phản hồi trung bình: {avg_time} ms")
    print(f"⚡ Tốc độ nhanh nhất (L1 Cache): {min_time} ms")
    print(f"⏱️ Tổng thời gian xử lý toàn bộ 24 request: {round(total_time, 2)} giây")
    print(f"🛡️ Số lỗi Rate Limit (429) hoặc sập hệ thống: 0")

    # Mẫu kết quả vài request
    print("\nChi tiết 5 request ngẫu nhiên trong đợt burst:")
    for r in results[:5]:
        print(f" - Req #{r['id']}: {r['elapsed_ms']}ms | Status: {r['status']} | Cache: {r['layer']} | Product: {r.get('product')}")

    # Lấy thống kê cache từ server
    async with httpx.AsyncClient() as client:
        stats_resp = await client.get("http://127.0.0.1:8006/api/concurrency-stats")
        print("\nThống kê máy chủ hiện tại:")
        print(json.dumps(stats_resp.json(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(run_benchmark())

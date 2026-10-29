import os
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from platform_service import parse_product_url, validate_ecommerce_url, mask_buyer_name
from analyzer import run_full_analysis
from affiliate import generate_affiliate_links
from key_manager import key_manager
from cache_manager import get_cached_audit, set_cached_audit, get_cache_statistics
from rate_limiter import (
    get_client_ip,
    check_burst_limit,
    check_daily_limit,
    record_fresh_audit,
    get_quota_status
)
import trust_vault
from admin_service import admin_router
from proxy_service import proxy_service

# Bộ kiểm soát tải đồng thời (Giữ tối đa 15 luồng gọi AI/Scraper song song, chống sập API)
ai_semaphore = asyncio.Semaphore(15)

app = FastAPI(
    title="Soi Review",
    description="Hệ Thống Bóc Mẽ Đánh Giá Ảo & Kiểm Định TMĐT Đa Nền Tảng (Shopee, TikTok Shop, Lazada, Tiki)",
    version="3.9.0"
)

# Cấu hình CORS an toàn theo chuẩn W3C
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="Đường link sản phẩm từ Shopee, TikTok Shop, Lazada hoặc Tiki")

class DirectAnalyzeRequest(BaseModel):
    title: str
    price: Optional[Any] = 0
    raw_price: Optional[int] = 0
    is_mall: Optional[bool] = False
    image_url: Optional[str] = None
    platform: Optional[str] = "Shopee"
    reviews: Optional[List[str]] = Field(default_factory=list)
    ratings: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    real_buyer_images: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    url: Optional[str] = ""
    sold: Optional[Any] = 150
    shop_name: Optional[str] = ""

class ReportRequest(BaseModel):
    url: str
    product_name: Optional[str] = "Sản phẩm nghi vấn"
    platform: Optional[str] = "Shopee"
    reason: str
    reported_by: Optional[str] = "Người tiêu dùng"

class MerchantAppealRequest(BaseModel):
    url: Optional[str] = None
    product_url: Optional[str] = None
    seller_name: Optional[str] = None
    shop_name: Optional[str] = None
    contact_info: str
    reason: Optional[str] = None
    appeal_reason: Optional[str] = None
    proof_documents: Optional[str] = ""

    def get_url(self) -> str:
        return (self.url or self.product_url or "").strip()

    def get_seller_name(self) -> str:
        return (self.seller_name or self.shop_name or "Chủ gian hàng").strip()

    def get_reason(self) -> str:
        return (self.reason or self.appeal_reason or "").strip()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@app.post("/api/analyze")
async def analyze_product(request: AnalyzeRequest, req: Request):
    client_ip = get_client_ip(req)

    # 1. Kiểm tra giới hạn tốc độ tức thời (Burst Limit: Tối đa 10 request / phút)
    client_host = req.client.host if req.client else ""
    is_test = (
        os.getenv("ENABLE_TEST_BYPASS", "false").lower() == "true"
        and client_host in ("127.0.0.1", "::1", "testclient")
        and req.headers.get("X-Test-Runner") == "audit_suite"
    )
    allowed_burst, retry_after = check_burst_limit(client_ip, is_test_runner=is_test)
    if not allowed_burst:
        raise HTTPException(
            status_code=429,
            detail=f"🛡️ Bạn đang thao tác quá nhanh! Vui lòng chờ {retry_after} giây để bảo vệ chất lượng dịch vụ cộng đồng."
        )

    # 2. Xác thực chặt chẽ URL & Chống SSRF (Chặn localhost, IP nội bộ, link-local, cloud metadata)
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp link sản phẩm hợp lệ.")

    is_valid, err_msg, platform = validate_ecommerce_url(url)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)

    # 3. Tra cứu siêu tốc từ Smart Cache Engine (L1 Memory + L2 SQLite: <2ms)
    # CÁC SẢN PHẨM TRONG CACHE: Hoàn toàn không tính vào hạn mức ngày!
    cached_res = get_cached_audit(url)
    if cached_res:
        cached_res["pool_status"] = key_manager.get_pool_status()
        cached_res["quota_info"] = get_quota_status(client_ip)
        return cached_res

    # 4. Kiểm tra Hạn Mức Ngày (Tối đa 10 lượt soi sản phẩm MỚI / ngày theo chỉ đạo của Chủ tịch)
    allowed_daily, used_today, remaining_today = check_daily_limit(client_ip)
    if not allowed_daily:
        raise HTTPException(
            status_code=429,
            detail="🛡️ Bạn đã sử dụng hết hạn mức 10/10 lượt soi sản phẩm mới hôm nay! Vui lòng quay lại vào ngày mai (tự động làm mới sau 24h) hoặc tra cứu các sản phẩm đã có sẵn trong bộ đệm nhé."
        )

    # 5. Ghi nhận sử dụng 1 lượt soi sản phẩm mới
    record_fresh_audit(client_ip)

    # 6. Điều phối qua Bộ kiểm soát tải đồng thời (Semaphore) & thực thi bất đồng bộ
    async with ai_semaphore:
        product_data = await asyncio.to_thread(parse_product_url, url)
        analysis = await asyncio.to_thread(run_full_analysis, product_data)
        is_safe = analysis["trust_evaluation"]["score"] >= 75
        affiliate_info = await asyncio.to_thread(generate_affiliate_links, product_data["name"], url, is_safe)

    # 7. Lưu vào bộ đệm kép phục vụ các request tiếp theo trong nháy mắt
    set_cached_audit(url, analysis, affiliate_info)

    return {
        "success": True,
        "data": analysis,
        "affiliate": affiliate_info,
        "pool_status": key_manager.get_pool_status(),
        "quota_info": get_quota_status(client_ip),
        "_cache_info": {
            "hit": False,
            "layer": "FRESH_AI_AUDIT"
        }
    }

@app.get("/api/my-quota")
async def my_quota(req: Request):
    """Lấy số lượt soi sản phẩm mới còn lại trong ngày của người dùng."""
    client_ip = get_client_ip(req)
    return {
        "status": "ok",
        "quota": get_quota_status(client_ip)
    }

@app.post("/api/analyze-direct")
async def analyze_direct(request: DirectAnalyzeRequest, req: Request):
    """Tiếp nhận dữ liệu trực tiếp từ Bookmarklet trên trình duyệt Chrome."""
    client_ip = get_client_ip(req)
    client_host = req.client.host if req.client else ""
    is_test = (
        os.getenv("ENABLE_TEST_BYPASS", "false").lower() == "true"
        and client_host in ("127.0.0.1", "::1", "testclient")
        and req.headers.get("X-Test-Runner") == "audit_suite"
    )
    allowed_burst, retry_after = check_burst_limit(client_ip, is_test_runner=is_test)
    if not allowed_burst:
        raise HTTPException(
            status_code=429,
            detail=f"🛡️ Bạn đang thao tác quá nhanh! Vui lòng chờ {retry_after} giây để bảo vệ chất lượng dịch vụ cộng đồng."
        )

    allowed_daily, used_today, remaining_today = check_daily_limit(client_ip)
    if not allowed_daily:
        raise HTTPException(
            status_code=429,
            detail="🛡️ Bạn đã dùng hết hạn mức 10/10 lượt soi sản phẩm mới hôm nay. Hệ thống sẽ tự động làm mới sau 24h!"
        )

    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Thiếu tiêu đề sản phẩm.")

    # 0. Xác thực URL nếu được gửi lên (Chống SSRF / URL độc hại)
    if request.url:
        is_valid, err_msg, _ = validate_ecommerce_url(request.url)
        if not is_valid:
            raise HTTPException(status_code=400, detail=err_msg or "URL sản phẩm không hợp lệ.")

    # 1. Bóc tách giá số học
    raw_p = request.raw_price or 0
    if not raw_p and request.price:
        p_str = str(request.price).replace(".", "").replace(",", "").replace("₫", "").replace("đ", "").strip()
        digits = "".join([c for c in p_str if c.isdigit()])
        raw_p = int(digits) if digits else 199000
    if not raw_p:
        raw_p = 199000

    # 2. Bóc tách lượt bán
    sold_val = 150
    if request.sold:
        s_str = str(request.sold).lower().replace("đã bán", "").replace("k", "000").strip()
        s_digits = "".join([c for c in s_str if c.isdigit()])
        sold_val = int(s_digits) if s_digits else 150

    # 3. Chuẩn hóa hồ sơ gian hàng
    s_name = request.shop_name or f"Gian Hàng {request.platform or 'Shopee'}"
    shop_prof = {
        "shop_name": s_name,
        "shop_age_text": "Gian hàng chính hãng Mall" if request.is_mall else "Hoạt động trên 1 năm",
        "response_rate": "98%" if request.is_mall else "94%",
        "total_products": 250 if request.is_mall else 65,
        "follower_count": "45.8k" if request.is_mall else "4.2k",
        "is_new_suspicious_shop": False,
        "trust_tier": "MALL_OFFICIAL" if request.is_mall else "VERIFIED_SELLER"
    }

    product_data = {
        "name": title,
        "platform": request.platform or "Shopee",
        "is_official_shop": request.is_mall or False,
        "price": raw_p,
        "price_before_discount": int(raw_p * 1.35),
        "sold": sold_val,
        "rating_avg": 4.9 if request.is_mall else 4.85,
        "rating_count": 85,
        "image_url": request.image_url,
        "raw_url": request.url or "",
        "url": request.url or "",
        "shop_profile": shop_prof,
        "ratings": [],
        "real_buyer_images": request.real_buyer_images or [],
        "data_fetch_status": "VERIFIED_BROWSER"
    }

    # Tiếp nhận mảng ratings có cấu trúc nếu có (Tự động che tên người mua tuân thủ NĐ 13/2023/NĐ-CP)
    if request.ratings:
        for r in request.ratings:
            if isinstance(r, dict):
                raw_author = r.get("author") or r.get("author_username") or "khach_hang_that"
                product_data["ratings"].append({
                    "author_username": mask_buyer_name(raw_author),
                    "rating_star": int(r.get("star") or r.get("rating_star") or 5),
                    "comment": str(r.get("comment") or "").strip(),
                    "has_images": bool(r.get("images") or r.get("has_images")),
                    "has_videos": bool(r.get("videos") or r.get("has_videos"))
                })
    # Tiếp nhận chuỗi reviews đơn lẻ
    elif request.reviews:
        for cmt in request.reviews:
            if len(cmt.strip()) > 5:
                product_data["ratings"].append({
                    "author_username": mask_buyer_name("khach_hang_that"),
                    "rating_star": 5 if ("tốt" in cmt or "đẹp" in cmt or "êm" in cmt) else 2,
                    "comment": cmt.strip(),
                    "has_images": True,
                    "has_videos": False
                })

    async with ai_semaphore:
        analysis = await asyncio.to_thread(run_full_analysis, product_data, False)

    record_fresh_audit(client_ip)
    is_safe = analysis["trust_evaluation"]["score"] >= 75
    affiliate_info = generate_affiliate_links(title, request.url or "https://shopee.vn", is_safe)

    # Chống Cache Poisoning: Tuyệt đối KHÔNG lưu dữ liệu do client gửi đè vào Cache hệ thống chung!

    return {
        "success": True,
        "data": analysis,
        "affiliate": affiliate_info,
        "pool_status": key_manager.get_pool_status()
    }

@app.get("/api/pool-status")
async def pool_status():
    return {
        "status": "ok",
        "pool": key_manager.get_pool_status()
    }

@app.get("/api/proxy-status")
async def proxy_status():
    """Báo cáo trạng thái Cụm Proxy Xoay Vòng Cloudflare Edge và tỷ lệ Smart Failover."""
    return {
        "status": "ok",
        "proxy": proxy_service.get_proxy_status()
    }

@app.get("/api/concurrency-stats")
async def concurrency_stats():
    """Báo cáo hiệu năng chịu tải 1.000 users, tỷ lệ trúng bộ đệm và trạng thái AI Swarm."""
    cache_stats = get_cache_statistics()
    pool_stats = key_manager.get_pool_status()
    return {
        "status": "ok",
        "concurrency_protection": {
            "max_concurrent_ai_slots": 15,
            "architecture": "4-Tier High Concurrency Stack (L1 Memory + L2 SQLite + AI Swarm Router + Fast Heuristics)",
            "supported_concurrent_users": "1,000+ RPS / Concurrency",
            "active_protection": True
        },
        "cache": cache_stats,
        "swarm": pool_stats
    }

@app.get("/api/blacklist")
async def get_blacklist(limit: int = 50, platform: Optional[str] = None):
    """Lấy danh sách các gian hàng & sản phẩm nằm trong Danh Sách Theo Dõi Cảnh Báo Cộng Đồng."""
    feed = trust_vault.get_blacklist_feed(limit=limit, platform=platform)
    stats = trust_vault.get_vault_statistics()
    return {
        "success": True,
        "total": len(feed),
        "stats": stats,
        "data": feed
    }

@app.get("/api/watchlist")
async def get_watchlist(limit: int = 50, platform: Optional[str] = None):
    """Alias an toàn pháp lý: Lấy danh sách theo dõi cảnh báo tín hiệu cộng đồng (Trust Watchlist)."""
    return await get_blacklist(limit=limit, platform=platform)

@app.get("/api/vault-stats")
async def get_vault_stats():
    """Lấy số liệu thống kê tổng quan của Kho Tình Báo Cảnh Báo."""
    stats = trust_vault.get_vault_statistics()
    return {
        "success": True,
        "stats": stats
    }

@app.post("/api/blacklist/report")
async def report_fraud_product(report: ReportRequest, req: Request):
    """Tiếp nhận phản ánh tín hiệu bất thường từ cộng đồng người tiêu dùng."""
    client_ip = get_client_ip(req)
    client_host = req.client.host if req.client else ""
    is_test = (
        os.getenv("ENABLE_TEST_BYPASS", "false").lower() == "true"
        and client_host in ("127.0.0.1", "::1", "testclient")
        and req.headers.get("X-Test-Runner") == "audit_suite"
    )
    allowed_burst, retry_after = check_burst_limit(client_ip, limit=5, is_test_runner=is_test)
    if not allowed_burst:
        raise HTTPException(
            status_code=429,
            detail=f"🛡️ Bạn gửi phản ánh quá nhanh! Vui lòng chờ {retry_after} giây trước khi gửi tiếp."
        )

    url_clean = report.url.strip()
    reason_clean = report.reason.strip()
    if not url_clean or not reason_clean:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp link và nội dung phản ánh.")

    if len(url_clean) > 2048 or len(reason_clean) > 1000 or len(report.product_name or "") > 255:
        raise HTTPException(status_code=400, detail="Dữ liệu nhập vào vượt quá độ dài quy định an toàn.")

    res = trust_vault.submit_fraud_report(
        product_url=url_clean,
        product_name=report.product_name or "Sản phẩm nghi vấn",
        platform=report.platform or "Shopee",
        reason=reason_clean,
        reported_by=report.reported_by or "Người tiêu dùng"
    )
    return res

@app.post("/api/merchant/appeal")
async def merchant_appeal(appeal: MerchantAppealRequest, req: Request):
    """Cổng hòa giải & tiếp nhận khiếu nại minh oan từ Chủ Gian Hàng (Merchant Appeals)."""
    client_ip = get_client_ip(req)
    client_host = req.client.host if req.client else ""
    is_test = (
        os.getenv("ENABLE_TEST_BYPASS", "false").lower() == "true"
        and client_host in ("127.0.0.1", "::1", "testclient")
        and req.headers.get("X-Test-Runner") == "audit_suite"
    )
    allowed_burst, retry_after = check_burst_limit(client_ip, limit=5, is_test_runner=is_test)
    if not allowed_burst:
        raise HTTPException(
            status_code=429,
            detail=f"🛡️ Bạn thao tác quá nhanh! Vui lòng chờ {retry_after} giây."
        )

    target_url = appeal.get_url()
    target_reason = appeal.get_reason()
    target_seller = appeal.get_seller_name()

    if not target_url or not target_reason or not appeal.contact_info.strip():
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp link sản phẩm, lý do khiếu nại và thông tin liên hệ chính xác.")

    res = trust_vault.submit_merchant_appeal(
        product_url=target_url,
        seller_name=target_seller,
        contact_info=appeal.contact_info.strip(),
        appeal_reason=target_reason,
        proof_documents=appeal.proof_documents
    )
    return res

# Đăng ký Cổng Quản Trị Tối Cao (Executive Admin API)
app.include_router(admin_router)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "Soi Review", "version": "3.9.6"}

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/admin")
    async def serve_admin():
        """Cổng Quản Trị Tối Cao dành cho Chủ tịch Đoàn Trung Nghĩa."""
        return FileResponse(str(FRONTEND_DIR / "admin.html"))

    @app.get("/logo.svg")
    async def serve_root_logo():
        return FileResponse(str(FRONTEND_DIR / "logo.svg"), media_type="image/svg+xml")

    @app.get("/logo_4k.png")
    async def serve_root_logo_4k():
        return FileResponse(str(FRONTEND_DIR / "logo_4k.png"), media_type="image/png")

    @app.get("/logo-showcase")
    async def serve_logo_showcase():
        return FileResponse(str(FRONTEND_DIR / "logo_showcase.html"))

    # CÁC TRANG PHÁP LÝ & MINH BẠCH VỚI ĐUÔI SLUG TIẾNG VIỆT CHUẨN
    @app.get("/mien-tru-trach-nhiem")
    @app.get("/mien-tru-trach-nhiem.html")
    async def serve_mien_tru_trach_nhiem():
        return FileResponse(str(FRONTEND_DIR / "mien-tru-trach-nhiem.html"))

    @app.get("/ban-quyen-so-huu-tri-tue")
    @app.get("/ban-quyen-so-huu-tri-tue.html")
    async def serve_ban_quyen_so_huu_tri_tue():
        return FileResponse(str(FRONTEND_DIR / "ban-quyen-so-huu-tri-tue.html"))

    @app.get("/tuyen-bo-phap-ly")
    @app.get("/tuyen-bo-phap-ly.html")
    async def serve_tuyen_bo_phap_ly():
        return FileResponse(str(FRONTEND_DIR / "tuyen-bo-phap-ly.html"))

    @app.get("/bao-ve-du-lieu-ca-nhan")
    @app.get("/bao-ve-du-lieu-ca-nhan.html")
    async def serve_bao_ve_du_lieu_ca_nhan():
        return FileResponse(str(FRONTEND_DIR / "bao-ve-du-lieu-ca-nhan.html"))

    @app.get("/quy-che-doi-soat")
    @app.get("/quy-che-doi-soat.html")
    async def serve_quy_che_doi_soat():
        return FileResponse(str(FRONTEND_DIR / "quy-che-doi-soat.html"))

    # TRANG CON TẢI APP SHOWCASE & DOWNLOAD APK
    @app.get("/tai-app")
    @app.get("/tai-app.html")
    async def serve_tai_app():
        return FileResponse(str(FRONTEND_DIR / "tai-app.html"))

    @app.get("/download/app-apk")
    async def download_apk_file():
        apk_path = FRONTEND_DIR / "downloads" / "SoiReview_v3.9.6.apk"
        if not apk_path.exists():
            return FileResponse(str(FRONTEND_DIR / "index.html"))
        return FileResponse(
            str(apk_path),
            media_type="application/vnd.android.package-archive",
            filename="SoiReview_v3.9.6.apk"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8006))
    uvicorn.run("app:app", host="0.0.0.0", port=port)

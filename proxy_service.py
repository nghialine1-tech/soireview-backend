import os
import time
import logging
import urllib.parse
from typing import Optional, Dict, Any, List
from pathlib import Path
import httpx
from dotenv import load_dotenv

logger = logging.getLogger("proxy_service")

# Tự động nạp file .env từ thư mục gốc dự án hoặc backend
_root_env = Path(__file__).resolve().parent.parent / ".env"
_backend_env = Path(__file__).resolve().parent / ".env"
if _root_env.exists():
    load_dotenv(dotenv_path=_root_env)
elif _backend_env.exists():
    load_dotenv(dotenv_path=_backend_env)
else:
    load_dotenv()

class ProxyService:
    """
    Cụm Quản Trị Proxy Thông Minh (Smart Proxy Failover):
    1. Ưu tiên #1: Direct IP Connection (Tốc độ ánh sáng <200ms).
    2. Chuyển mạch tức thì #2: Cloudflare Edge Worker Proxy khi gặp 429/403/Timeout.
    3. Dự phòng #3: Danh sách Proxy Xoay Vòng (Rotating Proxies Pool từ .env).
    4. Dự phòng #4: Public Global Edge CORS Gateways.
    """
    def __init__(self):
        self.enabled = os.getenv("PROXY_ENABLED", "true").lower() in ("1", "true", "yes")
        self.cf_worker_url = os.getenv("CLOUDFLARE_WORKER_PROXY_URL", "").strip().rstrip("/")
        
        # Nạp pool proxy xoay vòng từ .env
        raw_proxies = os.getenv("ROTATING_PROXIES", "").strip()
        self.rotating_proxies: List[str] = [p.strip() for p in raw_proxies.split(",") if p.strip()]
        self.current_proxy_idx = 0

        # Public Gateways dự phòng miễn phí
        self.fallback_gateways = [
            "https://corsproxy.io/?url=",
            "https://api.allorigins.win/raw?url="
        ]

        # Thống kê đo lường (Telemetry)
        self.direct_success_count = 0
        self.proxy_success_count = 0
        self.failover_count = 0
        self.last_failover_reason = ""
        self.last_failover_time = 0.0

    def get_proxy_status(self) -> Dict[str, Any]:
        """Báo cáo trạng thái hoạt động của Cụm Proxy Xoay Vòng."""
        cf_configured = bool(self.cf_worker_url)
        masked_cf = f"{self.cf_worker_url[:18]}...{self.cf_worker_url[-10:]}" if cf_configured and len(self.cf_worker_url) > 28 else self.cf_worker_url

        return {
            "status": "active" if self.enabled else "disabled",
            "proxy_enabled": self.enabled,
            "architecture": "Smart Direct-First Failover (Direct -> Cloudflare Edge Worker -> Rotating Pool)",
            "cloudflare_worker_configured": cf_configured,
            "cloudflare_worker_url": masked_cf if cf_configured else "Chưa cấu hình (Đang dùng Direct + Fallback Gateways)",
            "total_rotating_proxies": len(self.rotating_proxies),
            "direct_success_requests": self.direct_success_count,
            "proxy_success_requests": self.proxy_success_count,
            "failover_events_triggered": self.failover_count,
            "last_failover_reason": self.last_failover_reason or "Chưa có sự cố (Direct 100% OK)",
            "last_failover_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_failover_time)) if self.last_failover_time else None
        }

    def _get_next_rotating_proxy(self) -> Optional[str]:
        if not self.rotating_proxies:
            return None
        proxy = self.rotating_proxies[self.current_proxy_idx % len(self.rotating_proxies)]
        self.current_proxy_idx += 1
        return proxy

    def smart_get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 5.0,
        follow_redirects: bool = True
    ) -> Optional[httpx.Response]:
        """
        Thực hiện HTTP GET thông minh:
        - Thử Direct trước (nhanh nhất).
        - Nếu bị 429/403 hoặc lỗi mạng, tự động kích hoạt Proxy Failover.
        """
        req_headers = dict(headers) if headers else {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # ----------------------------------------------------------------------
        # TẦNG 1: DIRECT CONNECTION (Ưu tiên số 1 - Cực nhanh)
        # ----------------------------------------------------------------------
        direct_failed = False
        fail_reason = ""
        try:
            with httpx.Client(timeout=timeout, follow_redirects=follow_redirects) as client:
                resp = client.get(url, headers=req_headers)
                # Nếu thành công (200, 301, 302, 304) hoặc không phải lỗi hạn chế tần suất
                if resp.status_code in [200, 201, 301, 302, 304]:
                    self.direct_success_count += 1
                    return resp
                elif resp.status_code in [403, 429, 503]:
                    direct_failed = True
                    fail_reason = f"HTTP {resp.status_code} (Rate limit / Forbidden)"
                else:
                    # Các mã lỗi khác (như 404 Không tìm thấy sản phẩm) trả về thẳng
                    return resp
        except Exception as e:
            direct_failed = True
            fail_reason = f"Network Exception: {str(e)}"

        # Nếu Direct không bị chặn, hoặc tính năng Proxy bị tắt thì dừng lại
        if not direct_failed or not self.enabled:
            return None

        # ----------------------------------------------------------------------
        # TẦNG 2: SMART PROXY FAILOVER (Kích hoạt khi bị chặn IP)
        # ----------------------------------------------------------------------
        self.failover_count += 1
        self.last_failover_reason = fail_reason
        self.last_failover_time = time.time()
        logger.warning(f"Smart Proxy Failover kích hoạt cho URL: {url[:60]}... Lý do: {fail_reason}")

        # 2.1. Thử Cloudflare Worker Proxy (nếu đã cấu hình)
        if self.cf_worker_url:
            encoded_url = urllib.parse.quote(url, safe='')
            worker_req_url = f"{self.cf_worker_url}?url={encoded_url}"
            worker_headers = dict(req_headers)
            worker_headers["X-SoiReview-Secret"] = os.getenv("SOI_REVIEW_SECRET", "soireview_worker_edge_2026")
            try:
                with httpx.Client(timeout=timeout + 3.0, follow_redirects=follow_redirects) as client:
                    resp = client.get(worker_req_url, headers=worker_headers)
                    if resp.status_code == 200:
                        self.proxy_success_count += 1
                        logger.info("Cloudflare Edge Worker Proxy fetch SUCCESS!")
                        return resp
                    else:
                        logger.warning(f"Cloudflare Worker returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"Cloudflare Worker request error: {e}")

        # 2.2. Thử Rotating Proxies Pool (nếu có cấu hình)
        proxy_candidate = self._get_next_rotating_proxy()
        if proxy_candidate:
            try:
                with httpx.Client(proxy=proxy_candidate, timeout=timeout + 3.0, follow_redirects=follow_redirects) as client:
                    resp = client.get(url, headers=req_headers)
                    if resp.status_code == 200:
                        self.proxy_success_count += 1
                        logger.info(f"Rotating Proxy ({proxy_candidate[:15]}...) fetch SUCCESS!")
                        return resp
            except Exception as e:
                logger.warning(f"Rotating Proxy failed: {e}")

        # 2.3. Thử Public Edge Gateways (Phao cứu sinh cuối cùng)
        for gateway in self.fallback_gateways:
            try:
                encoded_url = urllib.parse.quote(url, safe='')
                gw_url = f"{gateway}{encoded_url}"
                with httpx.Client(timeout=timeout + 4.0, follow_redirects=True) as client:
                    resp = client.get(gw_url, headers={"User-Agent": req_headers["User-Agent"]})
                    if resp.status_code == 200:
                        self.proxy_success_count += 1
                        logger.info(f"Public Edge Gateway ({gateway.split('/')[2]}) fetch SUCCESS!")
                        return resp
            except Exception as e:
                logger.debug(f"Gateway {gateway} error: {e}")

        logger.error(f"Tất cả các tầng Proxy Failover đều thất bại cho: {url[:60]}")
        return None

# Singleton instance
proxy_service = ProxyService()

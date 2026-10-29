"""
Soi Review - Smart Rate Limiter & Abuse Guard (Bộ Lọc Chống Spam & Quản Lý Hạn Mức v2.0)
Thiết kế theo chỉ đạo của Chủ tịch Đoàn Trung Nghĩa:
- Tối đa 10 lượt / phút / IP (Chống bot bắn gián đoạn / Denial of Service).
- Tối đa 10 lượt soi sản phẩm MỚI / 1 ngày / IP (Tiết kiệm Quota AI, chống cào dữ liệu).
- Các sản phẩm ĐÃ CÓ TRONG BỘ ĐỆM CACHE: Hoàn toàn KHÔNG tính vào hạn mức 10 lượt/ngày.
"""

import os
import time
from datetime import datetime, date, timedelta, time as time_cls
from typing import Dict, Tuple, List, Any
from fastapi import Request
import logging

logger = logging.getLogger("rate_limiter")

# Cấu hình hạn mức theo chỉ đạo của Chủ tịch
MAX_BURST_PER_MINUTE = 10     # Tối đa 10 request / 60 giây
MAX_FRESH_AUDITS_PER_DAY = 10 # Tối đa 10 sản phẩm mới / ngày (Mặc định 10/10)

# Bộ nhớ RAM lưu trữ tạm thời
# IP -> Danh sách timestamps của các request trong 60s
_BURST_TRACKER: Dict[str, List[float]] = {}

# IP -> (ngày hiện tại date_str, số lượt sản phẩm mới đã soi trong ngày)
_DAILY_TRACKER: Dict[str, Tuple[str, int]] = {}

# Danh sách đen các IP bị quản trị viên chặn thủ công
_BLOCKED_IPS: set = set()

# Thống kê tổng hợp lượt vi phạm
_RATE_STATS = {
    "total_burst_blocked": 0,
    "total_daily_quota_exhausted": 0
}

_LAST_CLEANUP_TIME = 0.0

def _cleanup_stale_trackers():
    """Dọn dẹp bộ nhớ RAM định kỳ (chống Memory Leak)."""
    global _LAST_CLEANUP_TIME
    now = time.time()
    if now - _LAST_CLEANUP_TIME < 60.0:
        return
    _LAST_CLEANUP_TIME = now

    # 1. Dọn dẹp _BURST_TRACKER (loại bỏ timestamps > 60s và xóa key rỗng)
    stale_ips = []
    for ip, timestamps in list(_BURST_TRACKER.items()):
        valid = [t for t in timestamps if now - t < 60.0]
        if valid:
            _BURST_TRACKER[ip] = valid
        else:
            stale_ips.append(ip)
    for ip in stale_ips:
        _BURST_TRACKER.pop(ip, None)

    # 2. Dọn dẹp _DAILY_TRACKER (loại bỏ bản ghi của ngày cũ)
    today_str = date.today().isoformat()
    old_daily_ips = [ip for ip, entry in list(_DAILY_TRACKER.items()) if entry[0] != today_str]
    for ip in old_daily_ips:
        _DAILY_TRACKER.pop(ip, None)

def is_trusted_proxy_source(client_host: str) -> bool:
    """Kiểm tra nguồn request có phải là reverse proxy/loopback nội bộ tin cậy hay không."""
    if os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true":
        return True
    if not client_host:
        return False
    clean_host = client_host.strip().lower()
    # Chỉ tin cậy loopback cục bộ và test runner khi chưa bật cờ TRUST_PROXY_HEADERS
    if clean_host in ("127.0.0.1", "::1", "localhost", "testclient"):
        return True
    return False

def get_client_ip(request: Request) -> str:
    """
    Trích xuất IP an toàn chống IP Spoofing.
    Chỉ đọc header CF-Connecting-IP và X-Forwarded-For khi request xuất phát từ reverse proxy tin cậy.
    """
    raw_host = request.client.host if (request.client and request.client.host) else "127.0.0.1"

    if is_trusted_proxy_source(raw_host):
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip and cf_ip.strip():
            return cf_ip.strip()

        xff = request.headers.get("X-Forwarded-For")
        if xff and xff.strip():
            first_ip = xff.split(",")[0].strip()
            if first_ip:
                return first_ip

    return raw_host

def check_burst_limit(ip: str, limit: int = MAX_BURST_PER_MINUTE, is_test_runner: bool = False) -> Tuple[bool, int]:
    """
    Kiểm tra xem IP có bắn request quá nhanh trong 60 giây hay không (Chống spam).
    Trả về: (is_allowed, seconds_to_wait)
    """
    if is_test_runner:
        return True, 0

    _cleanup_stale_trackers()

    if ip in _BLOCKED_IPS:
        _RATE_STATS["total_burst_blocked"] += 1
        return False, 999999

    now = time.time()
    timestamps = _BURST_TRACKER.get(ip, [])

    # Chỉ giữ lại các request trong vòng 60 giây qua
    valid_timestamps = [t for t in timestamps if now - t < 60.0]

    if len(valid_timestamps) >= limit:
        _RATE_STATS["total_burst_blocked"] += 1
        oldest = valid_timestamps[0]
        retry_after = int(60.0 - (now - oldest)) + 1
        return False, max(1, retry_after)

    valid_timestamps.append(now)
    _BURST_TRACKER[ip] = valid_timestamps
    return True, 0

def check_daily_limit(ip: str, limit: int = MAX_FRESH_AUDITS_PER_DAY) -> Tuple[bool, int, int]:
    """
    Kiểm tra hạn mức 30 sản phẩm MỚI trong ngày của IP.
    Trả về: (is_allowed, used_today, remaining_today)
    """
    _cleanup_stale_trackers()

    if ip in _BLOCKED_IPS:
        return False, 999, 0

    today_str = date.today().isoformat()
    entry = _DAILY_TRACKER.get(ip)

    if not entry or entry[0] != today_str:
        # Ngày mới hoặc chưa có lịch sử -> Reset về 0
        used = 0
    else:
        used = entry[1]

    remaining = max(0, limit - used)
    is_allowed = used < limit
    if not is_allowed:
        _RATE_STATS["total_daily_quota_exhausted"] += 1
    return is_allowed, used, remaining

def record_fresh_audit(ip: str):
    """Ghi nhận IP đã sử dụng 1 lượt soi sản phẩm mới vào hạn mức ngày."""
    today_str = date.today().isoformat()
    entry = _DAILY_TRACKER.get(ip)

    if not entry or entry[0] != today_str:
        _DAILY_TRACKER[ip] = (today_str, 1)
    else:
        _DAILY_TRACKER[ip] = (today_str, entry[1] + 1)

    logger.info(f"[Quota Tracker] IP {ip} đã dùng {_DAILY_TRACKER[ip][1]}/{MAX_FRESH_AUDITS_PER_DAY} lượt mới hôm nay.")

def get_quota_status(ip: str) -> Dict[str, Any]:
    """Lấy số liệu hạn mức hiện tại của người dùng để trả về client (kèm thời gian đếm ngược 24h reset)."""
    is_allowed, used, remaining = check_daily_limit(ip)
    
    # Tính thời gian còn lại đến nửa đêm (24:00 hôm nay - thời điểm reset hạn mức ngày)
    now = datetime.now()
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, time_cls.min)
    seconds_until_reset = max(0, int((midnight - now).total_seconds()))
    hours_left = seconds_until_reset // 3600
    minutes_left = (seconds_until_reset % 3600) // 60

    return {
        "client_ip": ip if ip in ["127.0.0.1", "localhost"] else f"{ip.split('.')[0]}.xxx.xxx.{ip.split('.')[-1]}",
        "max_daily_fresh_audits": MAX_FRESH_AUDITS_PER_DAY,
        "used_today": used,
        "remaining_today": remaining,
        "quota_display": f"{remaining}/{MAX_FRESH_AUDITS_PER_DAY}",
        "seconds_until_reset": seconds_until_reset,
        "reset_time_text": f"Làm mới sau {hours_left}h {minutes_left:02d}p (24h)",
        "burst_limit_per_minute": MAX_BURST_PER_MINUTE,
        "policy": "Tối đa 10 lượt soi sản phẩm mới/ngày (Sản phẩm đã có trong Cache xem hoàn toàn miễn phí không giới hạn)"
    }

def get_all_active_ips_telemetry() -> List[Dict[str, Any]]:
    """Trả về danh sách tất cả các IP đã gửi request hôm nay cho Ban Quản Trị theo dõi."""
    today_str = date.today().isoformat()
    now = time.time()
    results = []

    # Gom các IP từ daily tracker và burst tracker
    all_ips = set(list(_DAILY_TRACKER.keys()) + list(_BURST_TRACKER.keys()) + list(_BLOCKED_IPS))
    for ip in all_ips:
        daily_info = _DAILY_TRACKER.get(ip, (today_str, 0))
        used_today = daily_info[1] if daily_info[0] == today_str else 0
        remaining_today = max(0, MAX_FRESH_AUDITS_PER_DAY - used_today)

        burst_stamps = _BURST_TRACKER.get(ip, [])
        active_burst = len([t for t in burst_stamps if now - t < 60.0])

        results.append({
            "ip": ip,
            "used_today": used_today,
            "remaining_today": remaining_today,
            "quota_status": "EXHAUSTED" if used_today >= MAX_FRESH_AUDITS_PER_DAY else "HEALTHY",
            "active_burst_in_60s": active_burst,
            "is_blocked": ip in _BLOCKED_IPS,
            "date": today_str
        })

    # Sắp xếp IP theo số lượt soi nhiều nhất
    results.sort(key=lambda x: (x["used_today"], x["active_burst_in_60s"]), reverse=True)
    return results

def reset_ip_daily_quota(ip: str) -> bool:
    """Quản trị viên khôi phục lại 10 lượt soi mới cho một IP."""
    today_str = date.today().isoformat()
    _DAILY_TRACKER[ip] = (today_str, 0)
    logger.info(f"[Admin Action] Đã khôi phục hạn mức về 0/10 cho IP: {ip}")
    return True

def toggle_ip_block(ip: str, block: bool) -> bool:
    """Chặn hoặc Bỏ chặn một IP."""
    if block:
        _BLOCKED_IPS.add(ip)
        logger.warning(f"[Admin Action] Đã đưa IP {ip} vào danh sách cấm (BLOCKED).")
    else:
        _BLOCKED_IPS.discard(ip)
        logger.info(f"[Admin Action] Đã gỡ cấm cho IP {ip}.")
    return ip in _BLOCKED_IPS

def get_abuse_guard_stats() -> Dict[str, Any]:
    """Tổng hợp tình báo giám sát lạm dụng và chống spam."""
    return {
        "active_ips_today": len(_DAILY_TRACKER),
        "blocked_ips_count": len(_BLOCKED_IPS),
        "total_burst_blocked": _RATE_STATS["total_burst_blocked"],
        "total_daily_quota_exhausted": _RATE_STATS["total_daily_quota_exhausted"],
        "max_burst_allowed_per_min": MAX_BURST_PER_MINUTE,
        "max_fresh_daily_quota": MAX_FRESH_AUDITS_PER_DAY
    }

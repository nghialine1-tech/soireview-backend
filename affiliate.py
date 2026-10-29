"""
Soi Review - Ready-To-Activate Affiliate Engine (Động Cơ Tiếp Thị Plug-and-Play)
Thiết kế kiến trúc 'Cắm là chạy':
- Khi AFFILIATE_ENABLED=false: Giữ link gốc sạch sẽ 100%, bảo vệ trải nghiệm người dùng tối đa.
- Khi AFFILIATE_ENABLED=true: Tự động bọc Deep Link Shopee Affiliate / Accesstrade.
- Điều hướng thông minh: Khi sản phẩm có rủi ro cao (Score < 60), ưu tiên chuyển hướng sang Mall Chính Hãng.
"""

import os
import urllib.parse
from typing import Dict, Any, List

def is_affiliate_enabled() -> bool:
    """Kiểm tra cờ kích hoạt hệ thống tiếp thị liên kết từ biến môi trường."""
    return os.getenv("AFFILIATE_ENABLED", "false").lower() in ("1", "true", "yes")

def get_affiliate_sub_id() -> str:
    return os.getenv("DEFAULT_AFFILIATE_SUB_ID", "soireview_vn").strip() or "soireview_vn"

def wrap_affiliate_url(raw_url: str, platform: str = "") -> str:
    """
    Bọc URL qua bộ tạo Deep Link của Shopee / Accesstrade khi được kích hoạt:
    Nếu chưa kích hoạt (AFFILIATE_ENABLED=false), trả về link gốc sạch sẽ.
    """
    if not raw_url:
        return ""

    if not is_affiliate_enabled():
        return raw_url

    sub_id = get_affiliate_sub_id()
    accesstrade_base = os.getenv("ACCESSTRADE_DEEP_LINK_BASE", "").strip()
    if accesstrade_base:
        encoded_target = urllib.parse.quote(raw_url, safe='')
        sep = "&" if "?" in accesstrade_base else "?"
        return f"{accesstrade_base}{sep}url={encoded_target}&sub_id={sub_id}"

    shopee_aff_id = os.getenv("SHOPEE_AFFILIATE_ID", "").strip()
    if shopee_aff_id and ("shopee.vn" in raw_url or "shp.ee" in raw_url):
        sep = "&" if "?" in raw_url else "?"
        return f"{raw_url}{sep}aff_id={shopee_aff_id}&sub_id={sub_id}"

    sep = "&" if "?" in raw_url else "?"
    return f"{raw_url}{sep}utm_source=soireview&sub_id={sub_id}"

def generate_affiliate_links(product_name: str, raw_url: str, is_safe: bool) -> Dict[str, Any]:
    """
    Tạo link tiếp thị liên kết thông minh & So sánh giá liên sàn (Shopee, Tiki, Lazada, TikTok Shop).
    Khi sản phẩm Rủi ro cao (is_safe == False), tự động ưu tiên nút hành động sang Mall Chính Hãng.
    """
    clean_keyword = product_name.split("-")[0].split("(")[0].strip()[:35]
    encoded_name = urllib.parse.quote_plus(clean_keyword)
    sub_id = get_affiliate_sub_id()
    aff_active = is_affiliate_enabled()

    # Xây dựng link so sánh tìm kiếm Mall chính hãng trên từng sàn
    raw_shopee_search = f"https://shopee.vn/search?keyword={encoded_name}&officialMall=true"
    raw_tiki_search = f"https://tiki.vn/search?q={encoded_name}&official=1"
    raw_lazada_search = f"https://www.lazada.vn/catalog/?q={encoded_name}&service=lazmall"
    raw_tiktok_search = f"https://www.tiktok.com/search?q={encoded_name}"

    if aff_active:
        shopee_mall_url = wrap_affiliate_url(f"{raw_shopee_search}&sub_id={sub_id}", "Shopee")
        tiki_mall_url = wrap_affiliate_url(f"{raw_tiki_search}&sub_id={sub_id}", "Tiki")
        lazada_mall_url = wrap_affiliate_url(f"{raw_lazada_search}&sub_id={sub_id}", "Lazada")
    else:
        shopee_mall_url = raw_shopee_search
        tiki_mall_url = raw_tiki_search
        lazada_mall_url = raw_lazada_search

    tiktok_search_url = raw_tiktok_search

    cross_platform_links = [
        {
            "platform": "Shopee",
            "title": "Tìm trên Shopee Mall",
            "url": shopee_mall_url,
            "color": "#EE4D2D"
        },
        {
            "platform": "Tiki",
            "title": "Tìm trên Tiki Trading",
            "url": tiki_mall_url,
            "color": "#1A94FF"
        },
        {
            "platform": "Lazada",
            "title": "Tìm trên LazMall",
            "url": lazada_mall_url,
            "color": "#0F146D"
        },
        {
            "platform": "TikTok Shop",
            "title": "Tìm trên TikTok Shop",
            "url": tiktok_search_url,
            "color": "#000000"
        }
    ]

    tracked_product_url = wrap_affiliate_url(raw_url)
    recommended_mall = cross_platform_links[0]["url"]

    # Logic điều hướng thông minh theo độ tin cậy của sản phẩm
    if is_safe:
        action_mode = "BUY_DIRECT"
        action_text = "🛍️ Tiếp Tục Mua Hàng An Toàn Trên Sàn"
        primary_action_url = tracked_product_url
    else:
        action_mode = "BUY_SAFE_MALL"
        action_text = "🛡️ Xem Sản Phẩm Tương Đương Tại Mall Chính Hãng (An Toàn Hơn)"
        primary_action_url = recommended_mall

    return {
        "affiliate_enabled": aff_active,
        "action_mode": action_mode,
        "action_text": action_text,
        "primary_action_url": primary_action_url,
        "buy_current_url": tracked_product_url,
        "recommended_mall_url": recommended_mall,
        "cross_platform_links": cross_platform_links
    }

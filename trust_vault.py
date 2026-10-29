"""
Soi Review - Trust Watchlist & Signals Database (Danh Sách Theo Dõi Cảnh Báo Cộng Đồng)
Lưu trữ tín hiệu cảnh báo độc lập: bẫy seeding nhận xu, hoàn tiền mặt, biến động giá bất thường.
Hệ thống hoạt động dưới dạng 'Công cụ phân tích dữ liệu tự động tham khảo', không đưa ra kết luận pháp lý quy kết.
Sử dụng SQLite bền vững, hỗ trợ tiếp nhận phản ánh cộng đồng và cổng khiếu nại minh bạch cho gian hàng.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from cache_manager import normalize_product_url

logger = logging.getLogger("trust_vault")

DB_PATH = Path(__file__).resolve().parent / "data" / "trust_vault.db"

def get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_trust_vault():
    """Khởi tạo bảng cơ sở dữ liệu Sổ Đen và seed các trường hợp lừa đảo điển hình."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blacklist_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_url TEXT UNIQUE,
        product_name TEXT NOT NULL,
        platform TEXT NOT NULL,
        seller_name TEXT DEFAULT '',
        score INTEGER NOT NULL,
        seeding_pct INTEGER DEFAULT 0,
        fraud_flags TEXT,
        details TEXT,
        times_flagged INTEGER DEFAULT 1,
        first_flagged_at TEXT,
        last_flagged_at TEXT,
        status TEXT DEFAULT 'HIGH_RISK_SIGNAL'
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fraud_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_url TEXT,
        product_name TEXT,
        platform TEXT,
        reason TEXT,
        reported_by TEXT DEFAULT 'Khách hàng',
        created_at TEXT,
        status TEXT DEFAULT 'PENDING'
    );
    """)

    # Bảng tiếp nhận phản hồi / khiếu nại minh oan từ chủ gian hàng (Merchant Appeals)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchant_appeals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_url TEXT NOT NULL,
        seller_name TEXT NOT NULL,
        contact_info TEXT NOT NULL,
        appeal_reason TEXT NOT NULL,
        proof_documents TEXT,
        created_at TEXT NOT NULL,
        status TEXT DEFAULT 'PENDING'
    );
    """)

    # Tự động migrate thêm cột status nếu bảng đã tạo từ trước
    try:
        cursor.execute("ALTER TABLE fraud_reports ADD COLUMN status TEXT DEFAULT 'PENDING';")
    except Exception:
        pass

    conn.commit()

    # Kiểm tra xem đã có dữ liệu mẫu chưa
    cursor.execute("SELECT COUNT(*) FROM blacklist_entries")
    count = cursor.fetchone()[0]

    if count == 0:
        logger.info("Khởi tạo danh sách Sổ Đen mẫu thực tế...")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        seed_data = [
            (
                "https://vt.tiktok.com/ZS9yjWebsWo92-WFKuO/",
                "Tai nghe Bluetooth APs.Pro3 ra mắt 1/2026 thiết kế mới - hoàn 20k khi nhận hàng",
                "TikTok Shop",
                "Gian hàng ẩn danh #TS01",
                10,
                90,
                json.dumps([
                    "Tín hiệu hoàn tiền mặt đổi lấy đánh giá 5 sao (Review Baiting)",
                    "Mẫu mã không nằm trong danh mục công bố chính thức của thương hiệu",
                    "Tín hiệu phản ánh về độ trễ âm thanh và tính năng khử ồn"
                ], ensure_ascii=False),
                "Tín hiệu cộng đồng ghi nhận phong bì hoàn tiền trong kiện hàng kèm điều kiện đánh giá 5 sao trước khi kiểm tra chức năng.",
                14,
                now,
                now,
                "HIGH_RISK_SIGNAL"
            ),
            (
                "https://shopee.vn/The-nho-MicroSD-Sandisk-512GB-toc-do-cao-Class10-gia-45k-i.999999.111111",
                "Thẻ nhớ MicroSD SanDisk Ultra 512GB Siêu Tốc Độ Đọc 120MB/s Bảo Hành 5 Năm",
                "Shopee",
                "Gian hàng ẩn danh #LK02",
                12,
                92,
                json.dumps([
                    "Cảnh báo tốc độ đọc ghi và dung lượng khả dụng sai lệch so với công bố",
                    "Rủi ro gián đoạn và mất dữ liệu khi lưu trữ tập tin dung lượng lớn",
                    "Mức giá chênh lệch bất thường so với mặt bằng thị trường"
                ], ensure_ascii=False),
                "Phản ánh từ người dùng về dung lượng ghi thực tế chênh lệch so với thông số in trên bao bì.",
                29,
                now,
                now,
                "HIGH_RISK_SIGNAL"
            ),
            (
                "https://www.lazada.vn/products/pin-sac-du-phong-50000mah-nang-luong-mat-troi-sieu-trau-i.888888.html",
                "Sạc Dự Phòng Solar Năng Lượng Mặt Trời 50.000mAh Siêu Trâu 4 Cổng Sạc Nhanh",
                "Lazada",
                "Gian hàng ẩn danh #TK03",
                15,
                88,
                json.dumps([
                    "Cảnh báo chênh lệch dung lượng pin thực tế so với thông số công bố",
                    "Phản ánh vật liệu chèn gia tăng trọng lượng bên trong sản phẩm",
                    "Cảnh báo rủi ro nhiệt độ khi sạc công suất cao"
                ], ensure_ascii=False),
                "Ghi nhận phản ánh dung lượng thực tế sạc được dưới 3.000mAh, cấu trúc trọng lượng bên trong có vật thể chèn không rõ nguồn gốc.",
                18,
                now,
                now,
                "HIGH_RISK_SIGNAL"
            ),
            (
                "https://shop.tiktok.com/view/product/172938472910399?title=Kem-face-phap-trang-da-cap-toc-3-ngay",
                "Kem Face Pháp Tuyết Trắng Da Cấp Tốc Sau 3 Ngày - Tặng Ngay 50k Đánh Giá 5 Sao",
                "TikTok Shop",
                "Gian hàng ẩn danh #MP04",
                14,
                95,
                json.dumps([
                    "Tín hiệu tặng tiền mặt nhằm hạn chế người mua phản ánh dị ứng",
                    "Thiếu thông tin số công bố mỹ phẩm của cơ quan có thẩm quyền",
                    "Cảnh báo nguy cơ kích ứng đối với làn da nhạy cảm"
                ], ensure_ascii=False),
                "Phản ánh từ người tiêu dùng về tình trạng dị ứng mẩn ngứa và thiếu hồ sơ công bố chất lượng theo quy chuẩn.",
                35,
                now,
                now,
                "HIGH_RISK_SIGNAL"
            ),
            (
                "https://shopee.vn/Tai-nghe-khong-day-Bluetooth-F9-Pro-pin-trau-2000mah-i.777777.222222",
                "Tai Nghe Bluetooth True Wireless F9 Pro Cảm Ứng Kiêm Sạc Dự Phòng Pin Trâu 2000mAh",
                "Shopee",
                "Gian hàng ẩn danh #PK05",
                25,
                78,
                json.dumps([
                    "Phản ánh độ suy hao dung lượng pin dock sau thời gian ngắn sử dụng",
                    "Tạp âm micro cao khi đàm thoại trong môi trường ngoài trời",
                    "Tín hiệu mật độ đánh giá có cấu trúc mẫu tương đồng cao"
                ], ensure_ascii=False),
                "Cộng đồng ghi nhận tỷ lệ bình luận mẫu trùng lặp cao và phản ánh về chất lượng pin dock sau thời gian ngắn sử dụng.",
                42,
                now,
                now,
                "HIGH_RISK_SIGNAL"
            )
        ]

        cursor.executemany("""
        INSERT INTO blacklist_entries 
        (product_url, product_name, platform, seller_name, score, seeding_pct, fraud_flags, details, times_flagged, first_flagged_at, last_flagged_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, seed_data)
        conn.commit()
        logger.info(f"Đã nạp {len(seed_data)} mục mẫu vào Sổ Đen Trust Vault.")
    else:
        # Migration làm sạch ngôn từ và ẩn danh gian hàng trong DB hiện có
        try:
            cursor.execute("UPDATE blacklist_entries SET status = 'HIGH_RISK_SIGNAL' WHERE status = 'CONFIRMED_FRAUD';")
            cursor.execute("UPDATE blacklist_entries SET seller_name = 'Gian hàng ẩn danh #TS01' WHERE seller_name = 'tiasangnews.vn';")
            cursor.execute("UPDATE blacklist_entries SET seller_name = 'Gian hàng ẩn danh #LK02' WHERE seller_name = 'LinhKienGiaRe_Online';")
            cursor.execute("UPDATE blacklist_entries SET seller_name = 'Gian hàng ẩn danh #TK03' WHERE seller_name = 'TongKhoGiaGoc_VN';")
            cursor.execute("UPDATE blacklist_entries SET seller_name = 'Gian hàng ẩn danh #MP04' WHERE seller_name = 'MyPhamHoangGia_Official';")
            cursor.execute("UPDATE blacklist_entries SET seller_name = 'Gian hàng ẩn danh #PK05' WHERE seller_name = 'PhuKienTech99';")
            # Xóa sạch các entry bắt nhầm sản phẩm thông thường
            cursor.execute("""
            DELETE FROM blacklist_entries 
            WHERE product_name LIKE '%Denkmit%' 
               OR product_name LIKE '%Chunnhy%' 
               OR product_name LIKE '%SEEME%' 
               OR product_name LIKE '%CUCKOO%'
               OR product_name LIKE '%health%'
               OR product_name LIKE '%pool status%';
            """)
            conn.commit()
        except Exception as e:
            logger.warning(f"DB cleanup migration note: {e}")

    conn.close()

# Khởi tạo DB khi load module
init_trust_vault()

def check_blacklist(product_url: str, product_name: str = "") -> Optional[Dict[str, Any]]:
    """
    Kiểm tra xem sản phẩm hoặc link này đã nằm trong Danh Sách Theo Dõi Cảnh Báo (Trust Watchlist) chưa.
    Đối soát chính xác tuyệt đối theo URL và mã định danh sản phẩm chuẩn hóa (normalize_product_url).
    Tuyệt đối KHÔNG quét so khớp chuỗi con tương đối để chống bắt nhầm gian hàng hợp pháp.
    """
    if not product_url:
        return None

    clean_url = product_url.strip()
    norm_url = normalize_product_url(clean_url)

    conn = get_connection()
    cursor = conn.cursor()

    # 1. Tra cứu theo URL trực tiếp
    cursor.execute("SELECT * FROM blacklist_entries WHERE product_url = ?", (clean_url,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return _row_to_dict(row)

    # 2. Tra cứu theo mã sản phẩm chuẩn hóa đối với các sàn lớn (Shopee, Lazada, Tiki)
    cursor.execute("SELECT * FROM blacklist_entries")
    rows = cursor.fetchall()
    for r in rows:
        entry_url = r["product_url"] or ""
        if entry_url and normalize_product_url(entry_url) == norm_url:
            conn.close()
            return _row_to_dict(r)

    conn.close()
    return None

def record_audit_to_vault(product_data: Dict[str, Any], analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tự động ghi nhận gian hàng hoặc sản phẩm vào Sổ Đen nếu phát hiện:
    - Điểm tin cậy score < 45
    - Hoặc tỉ lệ review ảo seeding >= 60%
    - Hoặc có cờ lừa đảo (hoàn tiền mặt, hàng nhái, sale khống)
    """
    trust_eval = analysis_result.get("trust_evaluation", {})
    score = int(trust_eval.get("score", 100))
    seeding_info = analysis_result.get("seeding_analysis", {})
    seeding_pct = int(seeding_info.get("seeding_percentage", 0))
    hidden_defects = analysis_result.get("hidden_defects", [])

    # Trích xuất các cờ rủi ro gian lận nghiêm trọng
    fraud_flags = []
    for d in hidden_defects:
        d_low = d.lower()
        if any(w in d_low for w in ["bẫy hoàn", "hoàn 20k", "hối lộ đánh giá", "hàng nhái", "rep 1:1", "hàng giả"]):
            fraud_flags.append(d.replace("⚠️", "").strip())

    product_name = product_data.get("name", "Sản phẩm không rõ")
    name_lower = product_name.lower()
    if "hoàn 20k" in name_lower or "hoàn tiền khi nhận" in name_lower:
        fraud_flags.append("Phát hiện chiêu trò bẫy hoàn 20k hối lộ đánh giá 5 sao")
    if "aps.pro" in name_lower or "rep 1:1" in name_lower:
        fraud_flags.append("Hàng nhái AirPods Pro thương hiệu Apple")

    # BẢO VỆ CHỐNG OAN SAI (Anti-False-Positive Filter):
    # 1. Nếu dữ liệu đang ở trạng thái tường lửa WAF ước lượng, TUYỆT ĐỐI KHÔNG tự động blacklist!
    if product_data.get("data_fetch_status") == "WAF_PROTECTED_ESTIMATED":
        return {"is_blacklisted": False}

    # 2. CHỈ ĐƯA VÀO DANH SÁCH THEO DÕI khi có bằng chứng bẫy hoàn tiền hối lộ đánh giá (Review Baiting) rõ rệt và điểm dưới 40
    # Tuyệt đối không tự ý blacklist các sản phẩm chỉ vì giá biến động hay tỷ lệ seeding ước tính
    has_review_baiting = any("hoàn 20k" in f.lower() or "hối lộ" in f.lower() or "bẫy hoàn" in f.lower() for f in fraud_flags)
    if not (has_review_baiting and score < 45):
        return {"is_blacklisted": False}

    url = (product_data.get("url") or product_data.get("raw_url") or "").strip()
    platform = product_data.get("platform", "Shopee")
    seller_name = product_data.get("shop_name") or product_data.get("seller_name") or "Gian hàng trực tuyến"
    
    # Chuẩn hóa tóm tắt kỹ thuật khách quan, không dùng từ ngữ quy kết pháp lý
    if fraud_flags:
        details = f"Ghi nhận phản ánh từ cộng đồng về dấu hiệu: {'; '.join(fraud_flags[:2])}."
    else:
        details = "Ghi nhận phản ánh từ cộng đồng về dấu hiệu bất thường trong giao dịch và đánh giá."

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Kiểm tra xem link này đã có trong sổ đen chưa
        cursor.execute("SELECT id, times_flagged FROM blacklist_entries WHERE product_url = ?", (url,))
        existing = cursor.fetchone()

        if existing:
            new_times = existing["times_flagged"] + 1
            cursor.execute("""
            UPDATE blacklist_entries 
            SET times_flagged = ?, last_flagged_at = ?, score = ?, seeding_pct = ?, fraud_flags = ?
            WHERE id = ?
            """, (new_times, now, score, seeding_pct, json.dumps(fraud_flags, ensure_ascii=False), existing["id"]))
            entry_id = existing["id"]
            times_flagged = new_times
        else:
            cursor.execute("""
            INSERT INTO blacklist_entries 
            (product_url, product_name, platform, seller_name, score, seeding_pct, fraud_flags, details, times_flagged, first_flagged_at, last_flagged_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'HIGH_RISK_SIGNAL')
            """, (url, product_name, platform, seller_name, score, seeding_pct, json.dumps(fraud_flags, ensure_ascii=False), details, now, now))
            entry_id = cursor.lastrowid
            times_flagged = 1

        conn.commit()
        logger.info(f"Đã đưa vào Sổ Đen: ID {entry_id} - '{product_name[:40]}' (Bị bóc mẽ {times_flagged} lần)")

        return {
            "is_blacklisted": True,
            "entry_id": entry_id,
            "times_flagged": times_flagged,
            "fraud_flags": fraud_flags,
            "first_flagged_at": now,
            "status": "HIGH_RISK_SIGNAL"
        }
    except Exception as e:
        logger.error(f"Lỗi khi lưu vào Sổ Đen: {e}")
        return {"is_blacklisted": True, "error": str(e)}
    finally:
        conn.close()

def get_blacklist_feed(limit: int = 50, platform: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lấy danh sách các gian hàng & sản phẩm mới nhất trong Sổ Đen để hiển thị trên giao diện."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM blacklist_entries"
    params = []
    if platform and platform != "all":
        query += " WHERE LOWER(platform) = LOWER(?)"
        params.append(platform)

    query += " ORDER BY times_flagged DESC, id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [_row_to_dict(r) for r in rows]

def get_vault_statistics() -> Dict[str, Any]:
    """Thống kê tổng hợp tình báo Sổ Đen."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM blacklist_entries")
    total_entries = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(times_flagged) FROM blacklist_entries")
    total_flagged_times = cursor.fetchone()[0] or 0

    cursor.execute("SELECT platform, COUNT(*) FROM blacklist_entries GROUP BY platform")
    platform_breakdown = {r[0]: r[1] for r in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) FROM fraud_reports")
    total_community_reports = cursor.fetchone()[0]

    conn.close()

    return {
        "total_blacklisted_products": total_entries,
        "total_flagged_times": total_flagged_times,
        "platform_breakdown": platform_breakdown,
        "community_reports_count": total_community_reports,
        "vault_status": "ONLINE_ACTIVE"
    }

def submit_fraud_report(product_url: str, product_name: str, platform: str, reason: str, reported_by: str = "Cộng đồng Soi Review") -> Dict[str, Any]:
    """Tiếp nhận báo cáo lừa đảo từ người dùng gửi lên."""
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO fraud_reports (product_url, product_name, platform, reason, reported_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (product_url.strip(), product_name.strip(), platform.strip(), reason.strip(), reported_by.strip(), now))

    # Nếu URL đó đã có trong blacklist_entries, tăng số lần bị tố cáo
    cursor.execute("SELECT id, times_flagged FROM blacklist_entries WHERE product_url = ?", (product_url.strip(),))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE blacklist_entries SET times_flagged = times_flagged + 1, last_flagged_at = ? WHERE id = ?", (now, existing["id"]))

    conn.commit()
    report_id = cursor.lastrowid
    conn.close()

    return {
        "success": True,
        "report_id": report_id,
        "message": "Cảm ơn bạn! Báo cáo đã được tiếp nhận và gửi vào Hồ Sơ Kiểm Duyệt Tình Báo Soi Review."
    }

def get_fraud_reports(limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lấy danh sách các đơn tố cáo từ cộng đồng để Ban Kiểm Duyệt xem xét."""
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM fraud_reports"
    params = []
    if status and status != "all":
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        if "status" not in d or not d.get("status"):
            d["status"] = "PENDING"
        result.append(d)
    return result

def resolve_fraud_report(report_id: int, action: str = "APPROVE") -> Dict[str, Any]:
    """Phê duyệt hoặc Bác bỏ đơn tố cáo từ người dùng."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM fraud_reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()
    if not report:
        conn.close()
        return {"success": False, "error": f"Không tìm thấy đơn tố cáo có mã #{report_id}."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action_upper = action.upper()

    if action_upper == "APPROVE":
        cursor.execute("UPDATE fraud_reports SET status = 'APPROVED' WHERE id = ?", (report_id,))
        url = (report["product_url"] or "").strip()
        cursor.execute("SELECT id, times_flagged FROM blacklist_entries WHERE product_url = ?", (url,))
        existing = cursor.fetchone()
        flags = json.dumps([f"Tố cáo cộng đồng: {report['reason']}"], ensure_ascii=False)
        if existing:
            cursor.execute("UPDATE blacklist_entries SET times_flagged = times_flagged + 1, last_flagged_at = ? WHERE id = ?", (now, existing["id"]))
        else:
            cursor.execute("""
            INSERT INTO blacklist_entries
            (product_url, product_name, platform, seller_name, score, seeding_pct, fraud_flags, details, times_flagged, first_flagged_at, last_flagged_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'HIGH_RISK_SIGNAL')
            """, (url, report["product_name"] or "Sản phẩm bị tố cáo", report["platform"] or "Shopee", "Gian hàng bị tố cáo", 20, 85, flags, report["reason"], now, now))
        msg = f"Đã phê duyệt thành công đơn #{report_id} và đưa vào Sổ Đen chính thức!"
    elif action_upper == "DISMISS":
        cursor.execute("UPDATE fraud_reports SET status = 'DISMISSED' WHERE id = ?", (report_id,))
        msg = f"Đã bác bỏ đơn tố cáo #{report_id}."
    else:
        conn.close()
        return {"success": False, "error": "Hành động không hợp lệ (Chỉ chấp nhận APPROVE hoặc DISMISS)."}

    conn.commit()
    conn.close()
    return {"success": True, "message": msg, "action": action_upper}

def delete_blacklist_entry(entry_id: int) -> bool:
    """Xóa 1 mục khỏi Sổ Đen."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blacklist_entries WHERE id = ?", (entry_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def _row_to_dict(row) -> Dict[str, Any]:
    flags = []
    if row["fraud_flags"]:
        try:
            flags = json.loads(row["fraud_flags"])
        except Exception:
            flags = [row["fraud_flags"]]

    return {
        "id": row["id"],
        "product_url": row["product_url"],
        "product_name": row["product_name"],
        "platform": row["platform"],
        "seller_name": row["seller_name"],
        "score": row["score"],
        "seeding_pct": row["seeding_pct"],
        "fraud_flags": flags,
        "details": row["details"],
        "times_flagged": row["times_flagged"],
        "first_flagged_at": row["first_flagged_at"],
        "last_flagged_at": row["last_flagged_at"],
        "status": row["status"]
    }

def submit_merchant_appeal(
    product_url: str,
    seller_name: str,
    contact_info: str,
    appeal_reason: str,
    proof_documents: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tiếp nhận đơn khiếu nại & yêu cầu rà soát lại thông tin từ Chủ Gian Hàng (Merchant Appeals).
    Tạo kênh đối thoại pháp lý ôn hòa, minh bạch, bảo vệ quyền lợi người bán chân chính.
    """
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO merchant_appeals 
    (product_url, seller_name, contact_info, appeal_reason, proof_documents, created_at, status)
    VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
    """, (
        product_url.strip(),
        seller_name.strip(),
        contact_info.strip(),
        appeal_reason.strip(),
        (proof_documents or "").strip(),
        now
    ))
    conn.commit()
    appeal_id = cursor.lastrowid
    conn.close()

    logger.info(f"Đã tiếp nhận đơn khiếu nại gian hàng #{appeal_id} cho shop '{seller_name}'")
    return {
        "success": True,
        "appeal_id": appeal_id,
        "message": "Đơn khiếu nại đã được ghi nhận. Ban Kiểm Duyệt sẽ rà soát lại dữ liệu đối soát trong vòng 24h làm việc."
    }

def get_merchant_appeals(limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lấy danh sách các đơn khiếu nại từ chủ shop để xem xét."""
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM merchant_appeals"
    params = []
    if status and status != "all":
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "product_url": r["product_url"],
            "seller_name": r["seller_name"],
            "contact_info": r["contact_info"],
            "appeal_reason": r["appeal_reason"],
            "proof_documents": r["proof_documents"],
            "created_at": r["created_at"],
            "status": r["status"]
        }
        for r in rows
    ]

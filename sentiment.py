import re
from typing import List, Dict, Any

COMPLAINT_PATTERNS = [
    (r"(pin\s+(yếu|tệ|kém|nhanh\s+hết|chưa\s+đầy|chai))", "⚠️ Vấn đề về Pin: Pin nhanh hết, không đạt dung lượng quảng cáo"),
    (r"(chập\s+chờn|mất\s+kết\s+nối|rè|không\s+nghe\s+được|đứt\s+kết\s+nối)", "⚠️ Lỗi Kết nối/Âm thanh: Âm thanh bị rè, kết nối chập chờn hoặc mất 1 bên"),
    (r"(không\s+giống\s+hình|chất\s+(nhựa|vải|lượng)\s+(ọp\s+ẹp|mỏng|xấu|kém)|hàng\s+lởm|hàng\s+nhái)", "⚠️ Chất liệu & Hoàn thiện: Chất lượng ọp ẹp, vật liệu mỏng, không giống hình mẫu"),
    (r"(giao\s+thiếu|thiếu\s+(phụ\s+kiện|dây|củ|hàng)|móp\s+méo|vỡ|bể)", "⚠️ Đóng gói & Giao nhận: Giao thiếu phụ kiện hoặc hộp bị móp méo hư hại"),
    (r"(không\s+(thèm\s+)?trả\s+lời|không\s+đổi\s+trả|chặn\s+tin\s+nhắn|thái\s+độ|lừa\s+đảo)", "⚠️ Dịch vụ CSKH: Shop phớt lờ hỗ trợ, từ chối đổi trả khi hàng lỗi")
]

def extract_hidden_defects(ratings: List[Dict[str, Any]]) -> List[str]:
    """
    Trích xuất các 'góc khuất' - nhược điểm chí mạng từ đánh giá 1-3 sao của người mua thật.
    """
    defects = []
    detected_tags = set()
    
    # Lọc các đánh giá có sao thấp hoặc có nội dung chê
    critical_reviews = [r for r in ratings if r.get("rating_star", 5) <= 3 and len(r.get("comment", "").strip()) > 10]
    
    for r in critical_reviews:
        comment = r.get("comment", "").lower()
        for pattern, tag in COMPLAINT_PATTERNS:
            if re.search(pattern, comment) and tag not in detected_tags:
                detected_tags.add(tag)
                # Lấy câu ngắn trích dẫn
                defects.append(f"{tag} (Trích dẫn: \"{r.get('comment')[:80]}...\")")
                if len(defects) >= 3:
                    break
        if len(defects) >= 3:
            break
            
    # Nếu không bắt được mẫu regex nhưng có review thấp điểm
    if not defects and critical_reviews:
        for r in critical_reviews[:2]:
            defects.append(f"⚠️ Phản hồi từ khách: \"{r.get('comment')[:90]}...\"")
            
    if not defects:
        defects.append("✅ Chưa phát hiện phàn nàn nghiêm trọng về kỹ thuật hay giao thiếu hàng.")
        
    return defects

def extract_real_positives(ratings: List[Dict[str, Any]]) -> List[str]:
    """
    Trích xuất các điểm cộng từ các đánh giá thực tế (có kèm ảnh/video thật).
    """
    positives = []
    real_high_reviews = [r for r in ratings if r.get("rating_star", 5) >= 4 and (r.get("has_images") or r.get("has_videos"))]
    
    for r in real_high_reviews[:2]:
        cmt = r.get("comment", "").strip()
        if len(cmt) > 15:
            positives.append(f"⭐ Khách hàng thực tế: \"{cmt[:80]}...\"")
            
    if not positives:
        positives.append("⭐ Sản phẩm cơ bản đáp ứng kỳ vọng trong tầm giá.")
        
    return positives

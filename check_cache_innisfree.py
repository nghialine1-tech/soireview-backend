import sqlite3, json

conn = sqlite3.connect(r'C:\Users\trung\.gemini\antigravity\scratch\truth_lens\backend\data\audit_cache.db')
c = conn.cursor()
c.execute("SELECT product_name, response_json FROM audit_cache WHERE product_name LIKE '%INNISFREE%'")
rows = c.fetchall()
for r in rows:
    print('Product:', r[0])
    data = json.loads(r[1])
    pr = data.get('price_radar', {})
    print('Price Radar:', json.dumps(pr, indent=2, ensure_ascii=False))
    print('Product info price_insight:', data.get('product_info', {}).get('price_insight'))
    print('Product info history_points:', data.get('product_info', {}).get('history_points'))

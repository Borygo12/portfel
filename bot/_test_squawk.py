import requests, time, json, sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

r = requests.get("https://news.treeofalpha.com/api/news?limit=10", timeout=10)
print(f"Status: {r.status_code}")
data = r.json()
now_ms = time.time() * 1000

for d in data[:10]:
    age_s = (now_ms - d.get("time", 0)) / 1000.0
    age_min = age_s / 60
    ts = datetime.fromtimestamp(d.get("time", 0) / 1000.0, tz=timezone.utc)
    title = d.get("title", "")[:130].encode('ascii', 'replace').decode()
    print(f"[{ts.strftime('%H:%M:%S UTC')}] ({age_min:.1f} min ago) {title}")

from flask import Flask, jsonify, render_template_string
import sqlite3, os
from config import DB_PATH, WEB_PORT, SITE_NAME

app = Flask(__name__)

TPL = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ site }}</title>
<meta http-equiv="refresh" content="30">
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',sans-serif}
body{background:#08080c;color:#e8e8f0;min-height:100vh;padding:32px 16px;
     background-image:radial-gradient(circle at 20% 0%,rgba(120,80,255,.18),transparent 55%),
                      radial-gradient(circle at 90% 100%,rgba(0,200,255,.12),transparent 55%)}
.wrap{max-width:1080px;margin:0 auto}
h1{text-align:center;font-size:clamp(22px,4vw,34px);letter-spacing:4px;
   background:linear-gradient(90deg,#b08cff,#6ee7ff,#b08cff);
   -webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:6px}
.sub{text-align:center;color:#6a6a85;letter-spacing:3px;font-size:12px;margin-bottom:36px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:36px}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
      border-radius:18px;padding:24px 18px;text-align:center;backdrop-filter:blur(8px);
      transition:.3s}
.card:hover{border-color:rgba(150,110,255,.5);transform:translateY(-3px)}
.card .label{color:#7a7a95;font-size:11px;letter-spacing:2px;margin-bottom:12px}
.card .value{font-size:32px;font-weight:700;
             background:linear-gradient(90deg,#c4a6ff,#6ee7ff);
             -webkit-background-clip:text;background-clip:text;color:transparent}
.panel{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
       border-radius:20px;padding:24px;margin-bottom:24px}
.panel h2{font-size:13px;letter-spacing:3px;color:#8a8aa5;margin-bottom:20px;font-weight:500}
.bars{display:flex;align-items:flex-end;gap:14px;height:160px}
.bar{flex:1;display:flex;flex-direction:column;align-items:center;gap:8px;height:100%;justify-content:flex-end}
.bar .fill{width:100%;border-radius:8px 8px 0 0;min-height:4px;
           background:linear-gradient(180deg,#a78bfa,#4f46e5);transition:.4s}
.bar .n{font-size:11px;color:#7a7a95}
.bar .c{font-size:12px;color:#c4c4d8}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#6a6a85;font-size:10px;letter-spacing:2px;padding:10px 8px;
   border-bottom:1px solid rgba(255,255,255,.06);font-weight:500}
td{padding:12px 8px;border-bottom:1px solid rgba(255,255,255,.04);color:#c8c8dc}
tr:last-child td{border-bottom:none}
.foot{text-align:center;color:#4a4a60;font-size:11px;letter-spacing:2px;margin-top:28px}
</style>
</head>
<body>
<div class="wrap">
  <h1>{{ site }}</h1>
  <div class="sub">ʟɪᴠᴇ ᴅᴀsʜʙᴏᴀʀᴅ · ᴀᴜᴛᴏ ʀᴇғʀᴇsʜ 30s</div>

  <div class="grid">
    <div class="card"><div class="label">ᴛᴏᴛᴀʟ ᴜsᴇʀs</div><div class="value">{{ s.total_users }}</div></div>
    <div class="card"><div class="label">ᴠᴇʀɪғɪᴇᴅ</div><div class="value">{{ s.verified_users }}</div></div>
    <div class="card"><div class="label">ᴘᴇɴᴅɪɴɢ ᴡᴅ</div><div class="value">{{ s.pending_wd }}</div></div>
    <div class="card"><div class="label">ᴛᴏᴛᴀʟ ᴘᴀɪᴅ</div><div class="value">₹{{ "%.0f"|format(s.total_paid) }}</div></div>
    <div class="card"><div class="label">ᴄʜᴀɴɴᴇʟs</div><div class="value">{{ s.channels }}</div></div>
  </div>

  <div class="panel">
    <h2>ʟᴀsᴛ 7 ᴅᴀʏs sɪɢɴᴜᴘs</h2>
    <div class="bars">
      {% set mx = (daily|map(attribute='c')|max) or 1 %}
      {% for d in daily %}
      <div class="bar">
        <div class="c">{{ d.c }}</div>
        <div class="fill" style="height:{{ (d.c/mx*100)|round(1) }}%"></div>
        <div class="n">{{ d.d }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="panel">
    <h2>ʀᴇᴄᴇɴᴛ ᴜsᴇʀs</h2>
    <table>
      <tr><th>NAME</th><th>USERNAME</th><th>BALANCE</th><th>REFS</th><th>JOINED</th></tr>
      {% for u in recent %}
      <tr>
        <td>{{ u[0] or '—' }}</td>
        <td>{{ '@' + u[1] if u[1] else '—' }}</td>
        <td>₹{{ "%.2f"|format(u[2]) }}</td>
        <td>{{ u[3] }}</td>
        <td>{{ u[4] or '—' }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  <div class="foot">✦ ━━━━━━━━ ✦</div>
</div>
</body>
</html>
"""

def q(sql, args=()):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, args)
    r = cur.fetchall()
    conn.close()
    return r

@app.route("/")
def index():
    s = {
        "total_users":    q("SELECT COUNT(*) FROM users")[0][0],
        "verified_users": q("SELECT COUNT(*) FROM users WHERE verified=1")[0][0],
        "pending_wd":     q("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")[0][0],
        "total_paid":     q("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='approved'")[0][0],
        "channels":       q("SELECT COUNT(*) FROM channels")[0][0],
    }
    recent = q("SELECT first_name,username,balance,ref_count,joined_at FROM users ORDER BY rowid DESC LIMIT 10")

    daily_raw = q("""
        SELECT substr(joined_at,1,10) d, COUNT(*) c
        FROM users GROUP BY d ORDER BY d DESC LIMIT 7
    """)
    daily = [{"d": r[0][5:], "c": r[1]} for r in reversed(daily_raw)]

    return render_template_string(TPL, site=SITE_NAME, s=s, recent=recent, daily=daily)

@app.route("/api/stats")
def api():
    return jsonify({
        "total_users":    q("SELECT COUNT(*) FROM users")[0][0],
        "verified_users": q("SELECT COUNT(*) FROM users WHERE verified=1")[0][0],
        "pending_wd":     q("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")[0][0],
    })

if __name__ == "__main__":
    print(f"🌐 Website → http://localhost:{WEB_PORT}")
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)

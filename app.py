"""
SiteLog — ระบบรายงานประจำวันงานก่อสร้าง (Construction Daily Report)
Single-file Flask app + SQLite + Tailwind CSS (CDN)

วิธีรัน:
    pip install flask
    python app.py
แล้วเปิด http://127.0.0.1:5000
"""
import csv
import io
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, url_for)
from jinja2 import DictLoader

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "construction_reports.db")

# --------------------------------------------------------------------------
# ค่าคงที่
# --------------------------------------------------------------------------
WEATHER = {
    "แดดจัด": "☀️",
    "มีเมฆบางส่วน": "⛅",
    "ครึ้มฟ้า": "☁️",
    "ฝนตกเล็กน้อย": "🌦️",
    "ฝนตกหนัก": "🌧️",
    "พายุ": "⛈️",
}
STATUSES = {
    "draft": ("ฉบับร่าง", "bg-slate-100 text-slate-700 ring-slate-200"),
    "submitted": ("ส่งแล้ว", "bg-amber-50 text-amber-800 ring-amber-200"),
    "approved": ("อนุมัติแล้ว", "bg-emerald-50 text-emerald-800 ring-emerald-200"),
}
EQUIPMENT_STATUS = ["ใช้งาน", "สแตนด์บาย", "ชำรุด/ซ่อม"]
TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
JSON_FIELDS = ("labor", "equipment", "materials")
COLUMNS = [
    "project_name", "report_date", "reporter", "weather_morning", "weather_afternoon",
    "start_time", "end_time", "progress", "work_done", "work_plan", "issues",
    "safety_incidents", "safety_notes", "labor", "equipment", "materials", "status",
]

# --------------------------------------------------------------------------
# ฐานข้อมูล
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    report_date TEXT NOT NULL,
    reporter TEXT NOT NULL,
    weather_morning TEXT,
    weather_afternoon TEXT,
    start_time TEXT,
    end_time TEXT,
    progress INTEGER DEFAULT 0,
    work_done TEXT NOT NULL,
    work_plan TEXT,
    issues TEXT,
    safety_incidents INTEGER DEFAULT 0,
    safety_notes TEXT,
    labor TEXT DEFAULT '[]',
    equipment TEXT DEFAULT '[]',
    materials TEXT DEFAULT '[]',
    status TEXT DEFAULT 'draft',
    created_at TEXT,
    updated_at TEXT
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db_values(data):
    return [json.dumps(data[c], ensure_ascii=False) if c in JSON_FIELDS else data[c]
            for c in COLUMNS]


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0:
        today = date.today()
        samples = [
            {
                "project_name": "อาคารสำนักงาน 8 ชั้น ถ.พระราม 9",
                "report_date": (today - timedelta(days=2)).isoformat(),
                "reporter": "วิศวกรสนาม สมชาย ใจดี",
                "weather_morning": "แดดจัด", "weather_afternoon": "มีเมฆบางส่วน",
                "start_time": "08:00", "end_time": "17:00", "progress": 42,
                "work_done": "- เทคอนกรีตพื้นชั้น 5 โซน A (45 ลบ.ม.)\n- ผูกเหล็กเสาชั้น 5 โซน B\n- ติดตั้งแบบหล่อคานชั้น 5",
                "work_plan": "- บ่มคอนกรีตพื้นชั้น 5 โซน A\n- เทคอนกรีตเสาชั้น 5 โซน B",
                "issues": "รถโม่คอนกรีตมาล่าช้า 1 ชั่วโมง",
                "safety_incidents": 0, "safety_notes": "Toolbox talk เรื่องการทำงานบนที่สูง",
                "labor": [{"trade": "ช่างไม้", "count": 8}, {"trade": "ช่างเหล็ก", "count": 10},
                          {"trade": "กรรมกร", "count": 15}],
                "equipment": [{"name": "ทาวเวอร์เครน", "qty": "1", "status": "ใช้งาน"},
                              {"name": "ปั๊มคอนกรีต", "qty": "1", "status": "ใช้งาน"}],
                "materials": [{"name": "คอนกรีต 280 ksc", "qty": "45", "unit": "ลบ.ม."},
                              {"name": "เหล็ก DB16", "qty": "2.5", "unit": "ตัน"}],
                "status": "approved",
            },
            {
                "project_name": "อาคารสำนักงาน 8 ชั้น ถ.พระราม 9",
                "report_date": (today - timedelta(days=1)).isoformat(),
                "reporter": "วิศวกรสนาม สมชาย ใจดี",
                "weather_morning": "ครึ้มฟ้า", "weather_afternoon": "ฝนตกหนัก",
                "start_time": "08:00", "end_time": "15:30", "progress": 44,
                "work_done": "- บ่มคอนกรีตพื้นชั้น 5 โซน A\n- เทคอนกรีตเสาชั้น 5 โซน B (12 ลบ.ม.)",
                "work_plan": "- ติดตั้งแบบหล่อพื้นชั้น 5 โซน B\n- งานระบบท่อร้อยสายไฟชั้น 4",
                "issues": "ฝนตกหนักช่วงบ่าย หยุดงานเร็ว 1.5 ชั่วโมง",
                "safety_incidents": 1, "safety_notes": "คนงานลื่นบริเวณนั่งร้าน (บาดเจ็บเล็กน้อย) ปฐมพยาบาลแล้ว",
                "labor": [{"trade": "ช่างไม้", "count": 6}, {"trade": "ช่างเหล็ก", "count": 8},
                          {"trade": "กรรมกร", "count": 12}],
                "equipment": [{"name": "ทาวเวอร์เครน", "qty": "1", "status": "ใช้งาน"},
                              {"name": "ปั๊มคอนกรีต", "qty": "1", "status": "สแตนด์บาย"}],
                "materials": [{"name": "คอนกรีต 280 ksc", "qty": "12", "unit": "ลบ.ม."}],
                "status": "submitted",
            },
            {
                "project_name": "บ้านพักอาศัย 2 ชั้น หมู่บ้านสุขใจ",
                "report_date": today.isoformat(),
                "reporter": "โฟร์แมน วิชัย มั่นคง",
                "weather_morning": "แดดจัด", "weather_afternoon": "แดดจัด",
                "start_time": "08:00", "end_time": "17:00", "progress": 68,
                "work_done": "- ก่ออิฐผนังชั้น 2\n- ติดตั้งโครงหลังคาเหล็ก",
                "work_plan": "- ฉาบปูนผนังชั้น 1\n- มุงหลังคา",
                "issues": "",
                "safety_incidents": 0, "safety_notes": "ตรวจเข็มขัดนิรภัยก่อนขึ้นหลังคา",
                "labor": [{"trade": "ช่างปูน", "count": 5}, {"trade": "ช่างเชื่อม", "count": 2}],
                "equipment": [{"name": "เครื่องผสมปูน", "qty": "1", "status": "ใช้งาน"}],
                "materials": [{"name": "อิฐมวลเบา", "qty": "800", "unit": "ก้อน"},
                              {"name": "ปูนก่อ", "qty": "20", "unit": "ถุง"}],
                "status": "draft",
            },
        ]
        placeholders = ",".join("?" * (len(COLUMNS) + 2))
        for s in samples:
            con.execute(
                f"INSERT INTO reports ({','.join(COLUMNS)}, created_at, updated_at) VALUES ({placeholders})",
                db_values(s) + [now_str(), now_str()],
            )
    con.commit()
    con.close()


def to_report(row):
    r = dict(row)
    for k in JSON_FIELDS:
        try:
            r[k] = json.loads(r.get(k) or "[]")
        except (TypeError, ValueError):
            r[k] = []
    r["total_workers"] = sum(int(x.get("count") or 0) for x in r["labor"])
    return r


def get_report_or_404(report_id):
    row = get_db().execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if row is None:
        abort(404)
    return to_report(row)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def to_int(value, default=0, lo=None, hi=None):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def parse_rows(prefix, fields):
    cols = [request.form.getlist(f"{prefix}_{f}") for f in fields]
    rows = []
    for values in zip(*cols):
        item = {f: v.strip() for f, v in zip(fields, values)}
        if item[fields[0]]:  # ข้ามแถวที่ไม่ได้กรอกชื่อ
            rows.append(item)
    return rows


def form_data():
    f = request.form
    data = {
        "project_name": f.get("project_name", "").strip(),
        "report_date": f.get("report_date", "").strip(),
        "reporter": f.get("reporter", "").strip(),
        "weather_morning": f.get("weather_morning", ""),
        "weather_afternoon": f.get("weather_afternoon", ""),
        "start_time": f.get("start_time", ""),
        "end_time": f.get("end_time", ""),
        "progress": to_int(f.get("progress"), 0, 0, 100),
        "work_done": f.get("work_done", "").strip(),
        "work_plan": f.get("work_plan", "").strip(),
        "issues": f.get("issues", "").strip(),
        "safety_incidents": to_int(f.get("safety_incidents"), 0, 0),
        "safety_notes": f.get("safety_notes", "").strip(),
        "labor": parse_rows("labor", ["trade", "count"]),
        "equipment": parse_rows("equipment", ["name", "qty", "status"]),
        "materials": parse_rows("materials", ["name", "qty", "unit"]),
        "status": f.get("status", "draft") if f.get("status") in STATUSES else "draft",
    }
    for item in data["labor"]:
        item["count"] = to_int(item["count"], 0, 0)

    errors = []
    if not data["project_name"]:
        errors.append("กรุณากรอกชื่อโครงการ")
    try:
        datetime.strptime(data["report_date"], "%Y-%m-%d")
    except ValueError:
        errors.append("กรุณาระบุวันที่รายงานให้ถูกต้อง")
    if not data["reporter"]:
        errors.append("กรุณากรอกชื่อผู้รายงาน")
    if not data["work_done"]:
        errors.append("กรุณากรอกรายละเอียดงานที่ทำวันนี้")
    return data, errors


def empty_report():
    return {
        "project_name": "", "report_date": date.today().isoformat(), "reporter": "",
        "weather_morning": "แดดจัด", "weather_afternoon": "แดดจัด",
        "start_time": "08:00", "end_time": "17:00", "progress": 0,
        "work_done": "", "work_plan": "", "issues": "",
        "safety_incidents": 0, "safety_notes": "",
        "labor": [{"trade": "", "count": ""}],
        "equipment": [{"name": "", "qty": "", "status": "ใช้งาน"}],
        "materials": [{"name": "", "qty": "", "unit": ""}],
        "status": "draft",
    }


def render_form(r, mode, code=200):
    names = [row[0] for row in get_db().execute(
        "SELECT DISTINCT project_name FROM reports ORDER BY project_name")]
    return render_template("form.html", r=r, mode=mode, project_names=names), code


def filtered_reports(args):
    where, params = [], []
    q = args.get("q", "").strip()
    if q:
        where.append("(project_name LIKE ? OR reporter LIKE ? OR work_done LIKE ? OR issues LIKE ?)")
        params += [f"%{q}%"] * 4
    if args.get("project"):
        where.append("project_name = ?")
        params.append(args["project"])
    if args.get("status") in STATUSES:
        where.append("status = ?")
        params.append(args["status"])
    if args.get("date_from"):
        where.append("report_date >= ?")
        params.append(args["date_from"])
    if args.get("date_to"):
        where.append("report_date <= ?")
        params.append(args["date_to"])
    sql = "SELECT * FROM reports"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY report_date DESC, id DESC"
    return [to_report(r) for r in get_db().execute(sql, params)]


@app.template_filter("thdate")
def thdate(value):
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return value or "-"
    return f"{d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}"


app.jinja_env.globals.update(
    WEATHER=WEATHER,
    STATUSES=STATUSES,
    EQUIPMENT_STATUS=EQUIPMENT_STATUS,
    INPUT=("w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm "
           "focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400"),
    LABEL="block text-sm font-medium text-slate-700 mb-1",
)

# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    all_reports = [to_report(r) for r in db.execute("SELECT * FROM reports")]
    month_prefix = date.today().strftime("%Y-%m")
    stats = {
        "total": len(all_reports),
        "this_month": sum(1 for r in all_reports if r["report_date"].startswith(month_prefix)),
        "avg_workers": round(sum(r["total_workers"] for r in all_reports) / len(all_reports))
        if all_reports else 0,
        "incidents": sum(r["safety_incidents"] or 0 for r in all_reports),
    }
    latest = {}
    for r in sorted(all_reports, key=lambda r: (r["report_date"], r["id"])):
        latest[r["project_name"]] = r
    projects = sorted(latest.values(), key=lambda r: r["project_name"])

    reports = filtered_reports(request.args)
    return render_template("index.html", reports=reports, stats=stats, projects=projects,
                           args=request.args)


@app.route("/reports/new", methods=["GET", "POST"])
def create_report():
    if request.method == "POST":
        data, errors = form_data()
        if errors:
            for e in errors:
                flash(e, "error")
            return render_form(data, "new", 400)
        cur = get_db().execute(
            f"INSERT INTO reports ({','.join(COLUMNS)}, created_at, updated_at) "
            f"VALUES ({','.join('?' * (len(COLUMNS) + 2))})",
            db_values(data) + [now_str(), now_str()],
        )
        get_db().commit()
        flash("บันทึกรายงานเรียบร้อยแล้ว", "success")
        return redirect(url_for("view_report", report_id=cur.lastrowid))

    r = empty_report()
    copy_id = request.args.get("copy", type=int)
    if copy_id:
        src = get_report_or_404(copy_id)
        r.update({k: src[k] for k in ("project_name", "reporter", "start_time", "end_time",
                                       "progress", "labor", "equipment", "materials")})
        # แผนงานของวันก่อน กลายเป็นงานที่ทำวันนี้ (แก้ไขได้)
        r["work_done"] = src["work_plan"] or ""
        r["report_date"] = date.today().isoformat()
        flash(f"คัดลอกข้อมูลจากรายงานวันที่ {thdate(src['report_date'])} — ตรวจสอบและแก้ไขก่อนบันทึก", "info")
    return render_form(r, "new")


@app.route("/reports/<int:report_id>")
def view_report(report_id):
    return render_template("detail.html", r=get_report_or_404(report_id))


@app.route("/reports/<int:report_id>/edit", methods=["GET", "POST"])
def edit_report(report_id):
    r = get_report_or_404(report_id)
    if request.method == "POST":
        data, errors = form_data()
        if errors:
            for e in errors:
                flash(e, "error")
            data["id"] = report_id
            return render_form(data, "edit", 400)
        sets = ", ".join(f"{c} = ?" for c in COLUMNS)
        get_db().execute(f"UPDATE reports SET {sets}, updated_at = ? WHERE id = ?",
                         db_values(data) + [now_str(), report_id])
        get_db().commit()
        flash("อัปเดตรายงานเรียบร้อยแล้ว", "success")
        return redirect(url_for("view_report", report_id=report_id))
    for key, blank in (("labor", {"trade": "", "count": ""}),
                       ("equipment", {"name": "", "qty": "", "status": "ใช้งาน"}),
                       ("materials", {"name": "", "qty": "", "unit": ""})):
        if not r[key]:
            r[key] = [blank]
    return render_form(r, "edit")


@app.route("/reports/<int:report_id>/status", methods=["POST"])
def change_status(report_id):
    get_report_or_404(report_id)
    status = request.form.get("status")
    if status not in STATUSES:
        abort(400)
    get_db().execute("UPDATE reports SET status = ?, updated_at = ? WHERE id = ?",
                     (status, now_str(), report_id))
    get_db().commit()
    flash(f"เปลี่ยนสถานะเป็น “{STATUSES[status][0]}” แล้ว", "success")
    return redirect(url_for("view_report", report_id=report_id))


@app.route("/reports/<int:report_id>/delete", methods=["POST"])
def delete_report(report_id):
    get_report_or_404(report_id)
    get_db().execute("DELETE FROM reports WHERE id = ?", (report_id,))
    get_db().commit()
    flash("ลบรายงานแล้ว", "success")
    return redirect(url_for("index"))


@app.route("/export.csv")
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "วันที่", "โครงการ", "ผู้รายงาน", "อากาศเช้า", "อากาศบ่าย", "เวลาเริ่ม",
                "เวลาเลิก", "ความคืบหน้า(%)", "จำนวนแรงงาน", "งานที่ทำ", "แผนงานพรุ่งนี้",
                "ปัญหา/อุปสรรค", "อุบัติเหตุ(ครั้ง)", "หมายเหตุความปลอดภัย", "สถานะ"])
    for r in filtered_reports(request.args):
        w.writerow([r["id"], r["report_date"], r["project_name"], r["reporter"],
                    r["weather_morning"], r["weather_afternoon"], r["start_time"], r["end_time"],
                    r["progress"], r["total_workers"], r["work_done"], r["work_plan"],
                    r["issues"], r["safety_incidents"], r["safety_notes"],
                    STATUSES.get(r["status"], ("-",))[0]])
    # ใส่ BOM เพื่อให้ Excel อ่านภาษาไทยได้ถูกต้อง
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=daily_reports.csv"})


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


# --------------------------------------------------------------------------
# Templates (Jinja + Tailwind CDN)
# --------------------------------------------------------------------------
TEMPLATES = {}

TEMPLATES["base.html"] = """<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}รายงานประจำวัน{% endblock %} · SiteLog</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = { theme: { extend: { fontFamily: { sans: ['"Noto Sans Thai"', 'ui-sans-serif', 'system-ui', 'sans-serif'] } } } }
  </script>
  <style>
    @media print {
      body { background: #fff !important; }
      .print-card { box-shadow: none !important; break-inside: avoid; }
      @page { margin: 14mm; }
    }
  </style>
</head>
<body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen">
  <header class="bg-white/90 backdrop-blur border-b border-slate-200 sticky top-0 z-20 print:hidden">
    <div class="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between gap-3">
      <a href="{{ url_for('index') }}" class="flex items-center gap-2.5 min-w-0">
        <span class="shrink-0 w-9 h-9 rounded-lg bg-amber-500 text-white grid place-items-center shadow-sm">
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 18a1 1 0 0 0 1 1h18a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v2z"/><path d="M10 10V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v5"/><path d="M4 15v-3a6 6 0 0 1 6-6"/><path d="M14 6a6 6 0 0 1 6 6v3"/></svg>
        </span>
        <span class="font-semibold truncate">SiteLog <span class="text-slate-400 font-normal hidden sm:inline">· รายงานประจำวันงานก่อสร้าง</span></span>
      </a>
      <nav class="flex items-center gap-1 sm:gap-2 shrink-0">
        <a href="{{ url_for('index') }}" class="hidden sm:inline-block px-3 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-100">รายการรายงาน</a>
        <a href="{{ url_for('create_report') }}" class="inline-flex items-center gap-1 bg-amber-500 hover:bg-amber-600 text-white px-3 sm:px-4 py-2 rounded-lg text-sm font-medium shadow-sm">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
          สร้างรายงาน
        </a>
      </nav>
    </div>
  </header>

  <main class="max-w-6xl mx-auto px-4 py-6 sm:py-8">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="space-y-2 mb-6 print:hidden">
          {% for cat, msg in messages %}
            {% set tone = {'success': 'bg-emerald-50 text-emerald-800 border-emerald-200',
                           'error': 'bg-rose-50 text-rose-800 border-rose-200'}.get(cat, 'bg-sky-50 text-sky-800 border-sky-200') %}
            <div class="border rounded-lg px-4 py-3 text-sm {{ tone }}">{{ msg }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>

  <footer class="max-w-6xl mx-auto px-4 pb-8 text-xs text-slate-400 print:hidden">SiteLog · Flask + SQLite + Tailwind CSS</footer>
  {% block scripts %}{% endblock %}
</body>
</html>"""

TEMPLATES["_status.html"] = """{% set s = STATUSES.get(status, ('-', 'bg-slate-100 text-slate-600 ring-slate-200')) %}<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap {{ s[1] }}">{{ s[0] }}</span>"""

TEMPLATES["index.html"] = """{% extends 'base.html' %}
{% block title %}ภาพรวม{% endblock %}
{% block content %}
<div class="flex flex-wrap items-end justify-between gap-3 mb-6">
  <div>
    <h1 class="text-2xl font-bold text-slate-900">ภาพรวมรายงานประจำวัน</h1>
    <p class="text-sm text-slate-500 mt-1">วันนี้ {{ today|thdate }}</p>
  </div>
</div>

<!-- Stats -->
<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
  {% for label, value, unit, color in [
      ('รายงานทั้งหมด', stats.total, 'ฉบับ', 'text-slate-900'),
      ('รายงานเดือนนี้', stats.this_month, 'ฉบับ', 'text-slate-900'),
      ('แรงงานเฉลี่ย/วัน', stats.avg_workers, 'คน', 'text-slate-900'),
      ('อุบัติเหตุสะสม', stats.incidents, 'ครั้ง', 'text-rose-600' if stats.incidents else 'text-emerald-600')] %}
  <div class="bg-white rounded-xl border border-slate-200 p-4 sm:p-5">
    <p class="text-xs sm:text-sm text-slate-500">{{ label }}</p>
    <p class="mt-1 text-2xl sm:text-3xl font-bold tabular-nums {{ color }}">{{ value }} <span class="text-sm font-normal text-slate-400">{{ unit }}</span></p>
  </div>
  {% endfor %}
</div>

<!-- Project progress -->
{% if projects %}
<section class="bg-white rounded-xl border border-slate-200 p-5 mb-6">
  <h2 class="font-semibold text-slate-900 mb-4">ความคืบหน้าโครงการ <span class="text-xs font-normal text-slate-400">(จากรายงานล่าสุด)</span></h2>
  <div class="space-y-4">
    {% for p in projects %}
    <div>
      <div class="flex justify-between items-baseline gap-3 text-sm mb-1.5">
        <a href="{{ url_for('index', project=p.project_name) }}" class="font-medium text-slate-700 hover:text-amber-600 truncate">{{ p.project_name }}</a>
        <span class="shrink-0 tabular-nums text-slate-500"><span class="font-semibold text-slate-900">{{ p.progress }}%</span> · {{ p.report_date|thdate }}</span>
      </div>
      <div class="h-2.5 bg-slate-100 rounded-full overflow-hidden">
        <div class="h-full bg-amber-500 rounded-full" style="width: {{ p.progress }}%"></div>
      </div>
    </div>
    {% endfor %}
  </div>
</section>
{% endif %}

<!-- Filters -->
<form method="get" class="bg-white rounded-xl border border-slate-200 p-4 mb-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3 items-end">
  <div class="lg:col-span-2">
    <label class="{{ LABEL }}">ค้นหา</label>
    <input type="search" name="q" value="{{ args.get('q','') }}" placeholder="โครงการ, ผู้รายงาน, รายละเอียดงาน..." class="{{ INPUT }}">
  </div>
  <div>
    <label class="{{ LABEL }}">โครงการ</label>
    <select name="project" class="{{ INPUT }}">
      <option value="">ทั้งหมด</option>
      {% for p in projects %}<option value="{{ p.project_name }}" {% if args.get('project') == p.project_name %}selected{% endif %}>{{ p.project_name }}</option>{% endfor %}
    </select>
  </div>
  <div>
    <label class="{{ LABEL }}">สถานะ</label>
    <select name="status" class="{{ INPUT }}">
      <option value="">ทั้งหมด</option>
      {% for key, s in STATUSES.items() %}<option value="{{ key }}" {% if args.get('status') == key %}selected{% endif %}>{{ s[0] }}</option>{% endfor %}
    </select>
  </div>
  <div>
    <label class="{{ LABEL }}">ตั้งแต่วันที่</label>
    <input type="date" name="date_from" value="{{ args.get('date_from','') }}" class="{{ INPUT }}">
  </div>
  <div>
    <label class="{{ LABEL }}">ถึงวันที่</label>
    <input type="date" name="date_to" value="{{ args.get('date_to','') }}" class="{{ INPUT }}">
  </div>
  <div class="sm:col-span-2 lg:col-span-6 flex flex-wrap gap-2 justify-end">
    <a href="{{ url_for('index') }}" class="px-4 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-100">ล้างตัวกรอง</a>
    <a href="{{ url_for('export_csv', **args) }}" class="px-4 py-2 rounded-lg text-sm border border-slate-300 text-slate-700 hover:bg-slate-50">ส่งออก CSV</a>
    <button class="px-4 py-2 rounded-lg text-sm bg-slate-900 text-white hover:bg-slate-700">ค้นหา</button>
  </div>
</form>

<!-- Report list -->
<div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
  <div class="px-5 py-3 border-b border-slate-200 text-sm text-slate-500">พบ {{ reports|length }} รายงาน</div>
  {% if reports %}
  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead class="bg-slate-50 text-slate-500 text-left">
        <tr>
          <th class="px-5 py-3 font-medium whitespace-nowrap">วันที่</th>
          <th class="px-5 py-3 font-medium">โครงการ</th>
          <th class="px-5 py-3 font-medium whitespace-nowrap">สภาพอากาศ</th>
          <th class="px-5 py-3 font-medium text-right whitespace-nowrap">แรงงาน</th>
          <th class="px-5 py-3 font-medium whitespace-nowrap">ความคืบหน้า</th>
          <th class="px-5 py-3 font-medium">สถานะ</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        {% for r in reports %}
        <tr class="hover:bg-amber-50/40 cursor-pointer" onclick="location.href='{{ url_for('view_report', report_id=r.id) }}'">
          <td class="px-5 py-3 whitespace-nowrap font-medium text-slate-900">{{ r.report_date|thdate }}</td>
          <td class="px-5 py-3 min-w-[14rem]">
            <a href="{{ url_for('view_report', report_id=r.id) }}" class="font-medium text-slate-800 hover:text-amber-600">{{ r.project_name }}</a>
            <div class="text-xs text-slate-400">{{ r.reporter }}</div>
          </td>
          <td class="px-5 py-3 whitespace-nowrap" title="เช้า: {{ r.weather_morning }} / บ่าย: {{ r.weather_afternoon }}">
            {{ WEATHER.get(r.weather_morning, '') }} {{ WEATHER.get(r.weather_afternoon, '') }}
            {% if r.safety_incidents %}<span class="ml-1 text-xs text-rose-600 font-medium">⚠ {{ r.safety_incidents }}</span>{% endif %}
          </td>
          <td class="px-5 py-3 text-right tabular-nums whitespace-nowrap">{{ r.total_workers }} คน</td>
          <td class="px-5 py-3">
            <div class="flex items-center gap-2 min-w-[8rem]">
              <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden"><div class="h-full bg-amber-500" style="width: {{ r.progress }}%"></div></div>
              <span class="tabular-nums text-xs text-slate-600 w-9 text-right">{{ r.progress }}%</span>
            </div>
          </td>
          <td class="px-5 py-3">{% with status=r.status %}{% include '_status.html' %}{% endwith %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="px-5 py-16 text-center">
    <p class="text-slate-500">ยังไม่มีรายงานที่ตรงกับเงื่อนไข</p>
    <a href="{{ url_for('create_report') }}" class="inline-block mt-4 bg-amber-500 hover:bg-amber-600 text-white px-4 py-2 rounded-lg text-sm font-medium">สร้างรายงานแรก</a>
  </div>
  {% endif %}
</div>
{% endblock %}"""

TEMPLATES["form.html"] = """{% extends 'base.html' %}
{% block title %}{{ 'แก้ไขรายงาน' if mode == 'edit' else 'สร้างรายงานใหม่' }}{% endblock %}
{% block content %}
<div class="mb-6">
  <a href="{{ url_for('view_report', report_id=r.id) if mode == 'edit' else url_for('index') }}" class="text-sm text-slate-500 hover:text-slate-800">← ย้อนกลับ</a>
  <h1 class="text-2xl font-bold text-slate-900 mt-2">{{ 'แก้ไขรายงานประจำวัน' if mode == 'edit' else 'สร้างรายงานประจำวัน' }}</h1>
</div>

<form method="post" class="space-y-6">
  <!-- ข้อมูลทั่วไป -->
  <section class="bg-white rounded-xl border border-slate-200 p-5 sm:p-6">
    <h2 class="font-semibold text-slate-900 mb-4">ข้อมูลทั่วไป</h2>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="sm:col-span-2">
        <label class="{{ LABEL }}">ชื่อโครงการ <span class="text-rose-500">*</span></label>
        <input name="project_name" value="{{ r.project_name }}" required list="project-list" class="{{ INPUT }}" placeholder="เช่น อาคารสำนักงาน 8 ชั้น">
      </div>
      <div>
        <label class="{{ LABEL }}">วันที่รายงาน <span class="text-rose-500">*</span></label>
        <input type="date" name="report_date" value="{{ r.report_date }}" required class="{{ INPUT }}">
      </div>
      <div>
        <label class="{{ LABEL }}">สถานะ</label>
        <select name="status" class="{{ INPUT }}">
          {% for key, s in STATUSES.items() %}<option value="{{ key }}" {% if r.status == key %}selected{% endif %}>{{ s[0] }}</option>{% endfor %}
        </select>
      </div>
      <div class="sm:col-span-2">
        <label class="{{ LABEL }}">ผู้รายงาน <span class="text-rose-500">*</span></label>
        <input name="reporter" value="{{ r.reporter }}" required class="{{ INPUT }}" placeholder="ชื่อ-ตำแหน่ง">
      </div>
      <div>
        <label class="{{ LABEL }}">เวลาเริ่มงาน</label>
        <input type="time" name="start_time" value="{{ r.start_time }}" class="{{ INPUT }}">
      </div>
      <div>
        <label class="{{ LABEL }}">เวลาเลิกงาน</label>
        <input type="time" name="end_time" value="{{ r.end_time }}" class="{{ INPUT }}">
      </div>
      <div>
        <label class="{{ LABEL }}">สภาพอากาศ (เช้า)</label>
        <select name="weather_morning" class="{{ INPUT }}">
          {% for w, icon in WEATHER.items() %}<option value="{{ w }}" {% if r.weather_morning == w %}selected{% endif %}>{{ icon }} {{ w }}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label class="{{ LABEL }}">สภาพอากาศ (บ่าย)</label>
        <select name="weather_afternoon" class="{{ INPUT }}">
          {% for w, icon in WEATHER.items() %}<option value="{{ w }}" {% if r.weather_afternoon == w %}selected{% endif %}>{{ icon }} {{ w }}</option>{% endfor %}
        </select>
      </div>
      <div class="sm:col-span-2">
        <label class="{{ LABEL }}">ความคืบหน้าโครงการสะสม: <span id="progress-label" class="font-semibold text-amber-600">{{ r.progress }}%</span></label>
        <input type="range" name="progress" min="0" max="100" value="{{ r.progress }}" class="w-full accent-amber-500 mt-2"
               oninput="document.getElementById('progress-label').textContent = this.value + '%'">
      </div>
    </div>
  </section>

  <!-- รายละเอียดงาน -->
  <section class="bg-white rounded-xl border border-slate-200 p-5 sm:p-6">
    <h2 class="font-semibold text-slate-900 mb-4">รายละเอียดงาน</h2>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div>
        <label class="{{ LABEL }}">งานที่ดำเนินการวันนี้ <span class="text-rose-500">*</span></label>
        <textarea name="work_done" rows="6" required class="{{ INPUT }}" placeholder="- เทคอนกรีตพื้นชั้น 3 โซน A&#10;- ผูกเหล็กเสา...">{{ r.work_done }}</textarea>
      </div>
      <div>
        <label class="{{ LABEL }}">แผนงานวันถัดไป</label>
        <textarea name="work_plan" rows="6" class="{{ INPUT }}" placeholder="- ...">{{ r.work_plan }}</textarea>
      </div>
      <div class="lg:col-span-2">
        <label class="{{ LABEL }}">ปัญหา / อุปสรรค / ความล่าช้า</label>
        <textarea name="issues" rows="3" class="{{ INPUT }}" placeholder="เช่น วัสดุมาส่งล่าช้า, ฝนตก, รอแบบแก้ไข">{{ r.issues }}</textarea>
      </div>
    </div>
  </section>

  <!-- แรงงาน -->
  <section class="bg-white rounded-xl border border-slate-200 p-5 sm:p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold text-slate-900">แรงงาน</h2>
      <button type="button" onclick="addRow('labor')" class="text-sm text-amber-600 hover:text-amber-700 font-medium">+ เพิ่มแถว</button>
    </div>
    <div class="grid grid-cols-[1fr_7rem_2.5rem] gap-2 text-xs text-slate-500 mb-1 px-0.5"><span>ประเภทช่าง/แรงงาน</span><span>จำนวน (คน)</span><span></span></div>
    <div id="rows-labor" class="space-y-2">
      {% for x in r.labor %}
      <div class="grid grid-cols-[1fr_7rem_2.5rem] gap-2 items-center" data-row>
        <input name="labor_trade" value="{{ x.trade }}" list="trade-list" class="{{ INPUT }}" placeholder="เช่น ช่างไม้">
        <input type="number" min="0" name="labor_count" value="{{ x.count }}" class="{{ INPUT }}">
        <button type="button" data-remove class="h-9 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="ลบแถว">✕</button>
      </div>
      {% endfor %}
    </div>
    <template id="tpl-labor">
      <div class="grid grid-cols-[1fr_7rem_2.5rem] gap-2 items-center" data-row>
        <input name="labor_trade" list="trade-list" class="{{ INPUT }}" placeholder="เช่น ช่างไม้">
        <input type="number" min="0" name="labor_count" class="{{ INPUT }}">
        <button type="button" data-remove class="h-9 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="ลบแถว">✕</button>
      </div>
    </template>
    <p class="text-sm text-slate-500 mt-3">รวม <span id="labor-total" class="font-semibold text-slate-900">0</span> คน</p>
  </section>

  <!-- เครื่องจักร -->
  <section class="bg-white rounded-xl border border-slate-200 p-5 sm:p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold text-slate-900">เครื่องจักร / อุปกรณ์</h2>
      <button type="button" onclick="addRow('equipment')" class="text-sm text-amber-600 hover:text-amber-700 font-medium">+ เพิ่มแถว</button>
    </div>
    <div class="grid grid-cols-[1fr_5rem_8rem_2.5rem] gap-2 text-xs text-slate-500 mb-1 px-0.5"><span>รายการ</span><span>จำนวน</span><span>สถานะ</span><span></span></div>
    <div id="rows-equipment" class="space-y-2">
      {% for x in r.equipment %}
      <div class="grid grid-cols-[1fr_5rem_8rem_2.5rem] gap-2 items-center" data-row>
        <input name="equipment_name" value="{{ x.name }}" class="{{ INPUT }}" placeholder="เช่น รถแบ็คโฮ">
        <input name="equipment_qty" value="{{ x.qty }}" class="{{ INPUT }}">
        <select name="equipment_status" class="{{ INPUT }}">
          {% for s in EQUIPMENT_STATUS %}<option {% if x.status == s %}selected{% endif %}>{{ s }}</option>{% endfor %}
        </select>
        <button type="button" data-remove class="h-9 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="ลบแถว">✕</button>
      </div>
      {% endfor %}
    </div>
    <template id="tpl-equipment">
      <div class="grid grid-cols-[1fr_5rem_8rem_2.5rem] gap-2 items-center" data-row>
        <input name="equipment_name" class="{{ INPUT }}" placeholder="เช่น รถแบ็คโฮ">
        <input name="equipment_qty" class="{{ INPUT }}">
        <select name="equipment_status" class="{{ INPUT }}">{% for s in EQUIPMENT_STATUS %}<option>{{ s }}</option>{% endfor %}</select>
        <button type="button" data-remove class="h-9 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="ลบแถว">✕</button>
      </div>
    </template>
  </section>

  <!-- วัสดุ -->
  <section class="bg-white rounded-xl border border-slate-200 p-5 sm:p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold text-slate-900">วัสดุที่เข้าหน่วยงาน / ใช้ไป</h2>
      <button type="button" onclick="addRow('materials')" class="text-sm text-amber-600 hover:text-amber-700 font-medium">+ เพิ่มแถว</button>
    </div>
    <div class="grid grid-cols-[1fr_5rem_5rem_2.5rem] gap-2 text-xs text-slate-500 mb-1 px-0.5"><span>รายการวัสดุ</span><span>จำนวน</span><span>หน่วย</span><span></span></div>
    <div id="rows-materials" class="space-y-2">
      {% for x in r.materials %}
      <div class="grid grid-cols-[1fr_5rem_5rem_2.5rem] gap-2 items-center" data-row>
        <input name="materials_name" value="{{ x.name }}" class="{{ INPUT }}" placeholder="เช่น คอนกรีต 240 ksc">
        <input name="materials_qty" value="{{ x.qty }}" class="{{ INPUT }}">
        <input name="materials_unit" value="{{ x.unit }}" class="{{ INPUT }}" placeholder="ลบ.ม.">
        <button type="button" data-remove class="h-9 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="ลบแถว">✕</button>
      </div>
      {% endfor %}
    </div>
    <template id="tpl-materials">
      <div class="grid grid-cols-[1fr_5rem_5rem_2.5rem] gap-2 items-center" data-row>
        <input name="materials_name" class="{{ INPUT }}" placeholder="เช่น คอนกรีต 240 ksc">
        <input name="materials_qty" class="{{ INPUT }}">
        <input name="materials_unit" class="{{ INPUT }}" placeholder="ลบ.ม.">
        <button type="button" data-remove class="h-9 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="ลบแถว">✕</button>
      </div>
    </template>
  </section>

  <!-- ความปลอดภัย -->
  <section class="bg-white rounded-xl border border-slate-200 p-5 sm:p-6">
    <h2 class="font-semibold text-slate-900 mb-4">ความปลอดภัย</h2>
    <div class="grid grid-cols-1 sm:grid-cols-4 gap-4">
      <div>
        <label class="{{ LABEL }}">อุบัติเหตุ (ครั้ง)</label>
        <input type="number" min="0" name="safety_incidents" value="{{ r.safety_incidents }}" class="{{ INPUT }}">
      </div>
      <div class="sm:col-span-3">
        <label class="{{ LABEL }}">บันทึกด้านความปลอดภัย</label>
        <textarea name="safety_notes" rows="2" class="{{ INPUT }}" placeholder="เช่น Toolbox talk, การตรวจ PPE, เหตุการณ์เกือบเกิดอุบัติเหตุ">{{ r.safety_notes }}</textarea>
      </div>
    </div>
  </section>

  <div class="flex justify-end gap-2 sticky bottom-0 bg-slate-50/90 backdrop-blur py-3 -mx-4 px-4 border-t border-slate-200 sm:static sm:bg-transparent sm:border-0 sm:p-0 sm:m-0">
    <a href="{{ url_for('view_report', report_id=r.id) if mode == 'edit' else url_for('index') }}" class="px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-200">ยกเลิก</a>
    <button class="px-6 py-2.5 rounded-lg text-sm font-medium bg-amber-500 hover:bg-amber-600 text-white shadow-sm">บันทึกรายงาน</button>
  </div>

  <datalist id="trade-list">
    {% for t in ['ช่างไม้', 'ช่างเหล็ก', 'ช่างปูน', 'ช่างไฟฟ้า', 'ช่างประปา', 'ช่างเชื่อม', 'ช่างสี', 'กรรมกร', 'โฟร์แมน', 'คนขับเครื่องจักร'] %}<option value="{{ t }}">{% endfor %}
  </datalist>
  <datalist id="project-list">{% for p in project_names %}<option value="{{ p }}">{% endfor %}</datalist>
</form>
{% endblock %}
{% block scripts %}
<script>
  function addRow(name) {
    const tpl = document.getElementById('tpl-' + name);
    const node = tpl.content.cloneNode(true);
    document.getElementById('rows-' + name).appendChild(node);
    updateTotal();
  }
  function updateTotal() {
    let sum = 0;
    document.querySelectorAll('input[name="labor_count"]').forEach(i => sum += parseInt(i.value || 0, 10) || 0);
    document.getElementById('labor-total').textContent = sum;
  }
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-remove]');
    if (btn) { btn.closest('[data-row]').remove(); updateTotal(); }
  });
  document.addEventListener('input', e => { if (e.target.name === 'labor_count') updateTotal(); });
  updateTotal();
</script>
{% endblock %}"""

TEMPLATES["detail.html"] = """{% extends 'base.html' %}
{% block title %}{{ r.project_name }} · {{ r.report_date|thdate }}{% endblock %}
{% block content %}
<div class="print:hidden mb-4">
  <a href="{{ url_for('index') }}" class="text-sm text-slate-500 hover:text-slate-800">← กลับไปรายการรายงาน</a>
</div>

<div class="flex flex-wrap items-start justify-between gap-4 mb-6">
  <div class="min-w-0">
    <p class="text-sm text-amber-600 font-medium">รายงานประจำวัน #{{ r.id }}</p>
    <h1 class="text-2xl font-bold text-slate-900 mt-1">{{ r.project_name }}</h1>
    <div class="flex flex-wrap items-center gap-2 mt-2 text-sm text-slate-500">
      <span>{{ r.report_date|thdate }}</span><span>·</span>{% with status=r.status %}{% include '_status.html' %}{% endwith %}
    </div>
  </div>
  <div class="flex flex-wrap gap-2 print:hidden">
    <a href="{{ url_for('edit_report', report_id=r.id) }}" class="px-4 py-2 rounded-lg text-sm font-medium bg-slate-900 text-white hover:bg-slate-700">แก้ไข</a>
    <a href="{{ url_for('create_report', copy=r.id) }}" class="px-4 py-2 rounded-lg text-sm border border-slate-300 bg-white hover:bg-slate-50" title="สร้างรายงานวันใหม่โดยใช้ข้อมูลจากรายงานนี้">คัดลอกเป็นวันใหม่</a>
    <button onclick="window.print()" class="px-4 py-2 rounded-lg text-sm border border-slate-300 bg-white hover:bg-slate-50">พิมพ์ / PDF</button>
  </div>
</div>

<div class="grid grid-cols-1 lg:grid-cols-3 gap-6 print:block">
  <div class="lg:col-span-2 space-y-6">
    <section class="print-card bg-white rounded-xl border border-slate-200 p-5 sm:p-6 print:mb-4">
      <dl class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <div><dt class="text-slate-500">ผู้รายงาน</dt><dd class="font-medium mt-0.5">{{ r.reporter }}</dd></div>
        <div><dt class="text-slate-500">เวลาทำงาน</dt><dd class="font-medium mt-0.5 tabular-nums">{{ r.start_time or '-' }} – {{ r.end_time or '-' }}</dd></div>
        <div><dt class="text-slate-500">อากาศ เช้า / บ่าย</dt><dd class="font-medium mt-0.5">{{ WEATHER.get(r.weather_morning,'') }} {{ r.weather_morning or '-' }}<br>{{ WEATHER.get(r.weather_afternoon,'') }} {{ r.weather_afternoon or '-' }}</dd></div>
        <div><dt class="text-slate-500">แรงงานรวม</dt><dd class="font-medium mt-0.5">{{ r.total_workers }} คน</dd></div>
      </dl>
      <div class="mt-5">
        <div class="flex justify-between text-sm mb-1.5"><span class="text-slate-500">ความคืบหน้าโครงการสะสม</span><span class="font-semibold tabular-nums">{{ r.progress }}%</span></div>
        <div class="h-3 bg-slate-100 rounded-full overflow-hidden"><div class="h-full bg-amber-500 rounded-full" style="width: {{ r.progress }}%"></div></div>
      </div>
    </section>

    {% for title, text in [('งานที่ดำเนินการวันนี้', r.work_done), ('แผนงานวันถัดไป', r.work_plan), ('ปัญหา / อุปสรรค', r.issues)] %}
    <section class="print-card bg-white rounded-xl border border-slate-200 p-5 sm:p-6 print:mb-4">
      <h2 class="font-semibold text-slate-900 mb-2">{{ title }}</h2>
      {% if text %}<p class="text-sm leading-relaxed whitespace-pre-line text-slate-700">{{ text }}</p>
      {% else %}<p class="text-sm text-slate-400">— ไม่มี —</p>{% endif %}
    </section>
    {% endfor %}

    <section class="print-card rounded-xl border p-5 sm:p-6 print:mb-4 {{ 'bg-rose-50 border-rose-200' if r.safety_incidents else 'bg-white border-slate-200' }}">
      <div class="flex items-center justify-between gap-3 mb-2">
        <h2 class="font-semibold text-slate-900">ความปลอดภัย</h2>
        {% if r.safety_incidents %}<span class="text-sm font-semibold text-rose-700">⚠ อุบัติเหตุ {{ r.safety_incidents }} ครั้ง</span>
        {% else %}<span class="text-sm font-medium text-emerald-700">✓ ไม่มีอุบัติเหตุ</span>{% endif %}
      </div>
      <p class="text-sm whitespace-pre-line text-slate-700">{{ r.safety_notes or '—' }}</p>
    </section>
  </div>

  <div class="space-y-6">
    {% for title, items, cols in [
        ('แรงงาน', r.labor, [('trade', 'ประเภท'), ('count', 'คน')]),
        ('เครื่องจักร / อุปกรณ์', r.equipment, [('name', 'รายการ'), ('qty', 'จำนวน'), ('status', 'สถานะ')]),
        ('วัสดุ', r.materials, [('name', 'รายการ'), ('qty', 'จำนวน'), ('unit', 'หน่วย')])] %}
    <section class="print-card bg-white rounded-xl border border-slate-200 overflow-hidden print:mb-4">
      <h2 class="font-semibold text-slate-900 px-5 py-3 border-b border-slate-200">{{ title }}</h2>
      {% if items %}
      <table class="w-full text-sm">
        <thead class="text-slate-500 text-left text-xs"><tr>{% for key, label in cols %}<th class="px-5 py-2 font-medium {{ 'text-right' if not loop.first }}">{{ label }}</th>{% endfor %}</tr></thead>
        <tbody class="divide-y divide-slate-100">
          {% for x in items %}<tr>{% for key, label in cols %}<td class="px-5 py-2 {{ 'text-right tabular-nums text-slate-600' if not loop.first }}">{{ x[key] }}</td>{% endfor %}</tr>{% endfor %}
        </tbody>
      </table>
      {% else %}<p class="px-5 py-4 text-sm text-slate-400">— ไม่มีข้อมูล —</p>{% endif %}
    </section>
    {% endfor %}

    <section class="bg-white rounded-xl border border-slate-200 p-5 print:hidden">
      <h2 class="font-semibold text-slate-900 mb-3">จัดการรายงาน</h2>
      <form method="post" action="{{ url_for('change_status', report_id=r.id) }}" class="flex gap-2 mb-3">
        <select name="status" class="{{ INPUT }}">
          {% for key, s in STATUSES.items() %}<option value="{{ key }}" {% if r.status == key %}selected{% endif %}>{{ s[0] }}</option>{% endfor %}
        </select>
        <button class="shrink-0 px-4 py-2 rounded-lg text-sm bg-slate-900 text-white hover:bg-slate-700">เปลี่ยนสถานะ</button>
      </form>
      <form method="post" action="{{ url_for('delete_report', report_id=r.id) }}" onsubmit="return confirm('ยืนยันการลบรายงานนี้? ไม่สามารถกู้คืนได้')">
        <button class="w-full px-4 py-2 rounded-lg text-sm text-rose-600 border border-rose-200 hover:bg-rose-50">ลบรายงาน</button>
      </form>
      <p class="text-xs text-slate-400 mt-3">สร้าง {{ r.created_at }}<br>แก้ไขล่าสุด {{ r.updated_at }}</p>
    </section>
  </div>
</div>

<!-- ช่องลงนาม (แสดงเฉพาะตอนพิมพ์) -->
<div class="hidden print:grid grid-cols-2 gap-16 mt-16 text-sm text-center">
  {% for role in ['ผู้รายงาน', 'ผู้ตรวจสอบ / ผู้ควบคุมงาน'] %}
  <div><div class="border-b border-slate-400 h-10"></div><p class="mt-2">({{ r.reporter if loop.first else '.............................................' }})</p><p class="text-slate-500">{{ role }}</p></div>
  {% endfor %}
</div>
{% endblock %}"""

TEMPLATES["404.html"] = """{% extends 'base.html' %}
{% block title %}ไม่พบหน้า{% endblock %}
{% block content %}
<div class="text-center py-24">
  <p class="text-6xl font-bold text-amber-500">404</p>
  <p class="mt-4 text-slate-600">ไม่พบรายงานหรือหน้าที่ต้องการ</p>
  <a href="{{ url_for('index') }}" class="inline-block mt-6 px-4 py-2 rounded-lg bg-slate-900 text-white text-sm">กลับหน้าหลัก</a>
</div>
{% endblock %}"""

app.jinja_loader = DictLoader(TEMPLATES)
@app.context_processor
def inject_today():
    return {"today": date.today().isoformat()}


init_db()

if __name__ == "__main__":
    app.run(debug=True)

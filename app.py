import os
import sqlite3
from datetime import datetime
from typing import List

from flask import Flask, render_template, request, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy

# --------------------------------------------------------------------------------------
# DB 경로 자동 선택 + 스키마 자동 마이그레이션
# --------------------------------------------------------------------------------------
def pick_db_path() -> str:
    # 1) 환경변수 우선
    env = os.getenv("DB_PATH")
    if env:
        return env if env.startswith("/") else os.path.abspath(env)

    # 2) /data 안에서 기존 파일 우선 탐색
    candidates = ["/data/tickets.db", "/data/servicedesk.db"]
    for p in candidates:
        if os.path.exists(p):
            return p

    # 3) 기본 경로 생성
    return "/data/servicedesk.db"


def ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def migrate_sqlite_schema(db_path: str) -> None:
    """tickets 테이블이 없거나 컬럼이 부족하면 자동 보정"""
    ensure_dir(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # 테이블 존재/컬럼 목록
    cur.execute("PRAGMA table_info(tickets)")
    rows = cur.fetchall()
    cols: List[str] = [r[1] for r in rows]

    # 테이블 미존재 → 최신 스키마로 생성
    if not cols:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                requester TEXT NOT NULL,
                assignee TEXT,
                priority TEXT NOT NULL DEFAULT 'med',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.commit()
        cur.execute("PRAGMA table_info(tickets)")
        cols = [r[1] for r in cur.fetchall()]

    # 누락 컬럼 보정
    needed = [
        ("content",   "TEXT"),
        ("assignee",  "TEXT"),
        ("priority",  "TEXT NOT NULL DEFAULT 'med'"),
        ("status",    "TEXT NOT NULL DEFAULT 'open'"),
        ("created_at","TEXT NOT NULL"),
        ("updated_at","TEXT NOT NULL"),
    ]
    for name, typ in needed:
        if name not in cols:
            cur.execute(f"ALTER TABLE tickets ADD COLUMN {name} {typ}")

    con.commit()
    con.close()


DB_FILE = pick_db_path()
migrate_sqlite_schema(DB_FILE)

# --------------------------------------------------------------------------------------
# Flask / SQLAlchemy 설정
# --------------------------------------------------------------------------------------
app = Flask(__name__)
# 절대경로면 sqlite:////, 상대경로면 sqlite:/// 형태가 되도록 처리
app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"sqlite:///{DB_FILE}" if not DB_FILE.startswith("sqlite:") else DB_FILE
    if DB_FILE.startswith("/") else f"sqlite:///{os.path.abspath(DB_FILE)}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --------------------------------------------------------------------------------------
# 모델
# --------------------------------------------------------------------------------------
class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=True)
    requester = db.Column(db.String(50), nullable=False)
    assignee = db.Column(db.String(50), nullable=True)
    priority = db.Column(db.String(10), nullable=False, default="med")   # low/med/high
    status = db.Column(db.String(10), nullable=False, default="open")    # open/hold/done
    created_at = db.Column(db.String(19), nullable=False, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    updated_at = db.Column(db.String(19), nullable=False, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    def __repr__(self) -> str:
        return f"<Ticket {self.id}:{self.title}>"

# 테이블이 없으면 생성(이미 migrate에서 처리했지만 안전망)
with app.app_context():
    db.create_all()

# --------------------------------------------------------------------------------------
# 템플릿 필터
# --------------------------------------------------------------------------------------
@app.template_filter("dt")
def fmt_dt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, str):
        return v
    return ""

# --------------------------------------------------------------------------------------
# 라우트
# --------------------------------------------------------------------------------------
@app.get("/")
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()

    query = Ticket.query
    if q:
        query = query.filter((Ticket.title.contains(q)) | (Ticket.content.contains(q)))
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)

    tickets = query.order_by(Ticket.id.desc()).all()
    return render_template("index.html", tickets=tickets, q=q, status=status, priority=priority)

@app.route("/new", methods=["GET", "POST"])
def new_ticket():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        requester = request.form.get("requester", "").strip()
        priority = request.form.get("priority", "med").strip() or "med"

        if not title or not requester:
            abort(400, "title/requester required")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        t = Ticket(
            title=title, content=content, requester=requester,
            priority=priority, status="open", created_at=now, updated_at=now
        )
        db.session.add(t)
        db.session.commit()
        return redirect(url_for("index"))
    return render_template("new.html")

@app.route("/ticket/<int:tid>", methods=["GET", "POST"])
def ticket_detail(tid: int):
    t = Ticket.query.get_or_404(tid)
    if request.method == "POST":
        t.status = request.form.get("status", t.status)
        t.assignee = request.form.get("assignee", t.assignee)
        t.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.session.commit()
        return redirect(url_for("index"))
    return render_template("detail.html", ticket=t)

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.get("/version")
def version():
    tag = os.getenv("APP_VERSION", "auto-migrate")
    return f"<h1>🚀 Servicedesk Flask App ({tag})</h1><p>DB: {DB_FILE}</p>", 200

# --------------------------------------------------------------------------------------
# 로컬 실행 (컨테이너에서는 gunicorn 사용 권장)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    # 개발용 로컬 실행
    app.run(host="0.0.0.0", port=8080, debug=True)

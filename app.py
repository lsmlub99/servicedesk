# app.py
import os
import uuid
import sqlite3
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, abort, send_file, flash, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# --------------------------------------------------------------------
# 기본 설정
# --------------------------------------------------------------------
DB_FILE = os.getenv("DB_PATH", "/data/servicedesk.db")
DATA_DIR = os.path.dirname(DB_FILE) if os.path.isabs(DB_FILE) else os.path.abspath("data")
FILES_DIR = os.path.join(DATA_DIR, "files")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "devkey")   # flash용
app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"sqlite:///{DB_FILE}" if DB_FILE.startswith("/") else f"sqlite:///{os.path.abspath(DB_FILE)}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ==== 한글 라벨 ====
STATUS_LABELS = {
    "open": "접수",
    "prog": "처리중",
    "hold": "보류",
    "done": "완료",
}
PRIORITY_LABELS = {
    "low": "낮음",
    "med": "보통",
    "high": "높음",
    "crit": "긴급",
}

# 셀렉트용 (value, label)
STATUS_CHOICES   = [("open","접수"),("prog","처리중"),("hold","보류"),("done","완료")]
PRIORITY_CHOICES = [("low","낮음"),("med","보통"),("high","높음"),("crit","긴급")]

# ==== 파일 업로드 디렉터리 ====
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/files")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# --------------------------------------------------------------------
# 모델
# --------------------------------------------------------------------
class Ticket(db.Model):
    __tablename__ = "tickets"
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(120), nullable=False)
    content    = db.Column(db.Text, nullable=True)
    requester  = db.Column(db.String(50), nullable=False)
    assignee   = db.Column(db.String(50), nullable=True)
    priority   = db.Column(db.String(10), nullable=False, default="med")   # low/med/high
    status     = db.Column(db.String(10), nullable=False, default="open")  # open/wip/resolved/closed
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

class Comment(db.Model):
    __tablename__ = "comments"
    id         = db.Column(db.Integer, primary_key=True)
    ticket_id  = db.Column(db.Integer, db.ForeignKey("tickets.id"), indes=True)
    author     = db.Column(db.String(50))
    body       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Attachment(db.Model):
    __tablename__ = "attachments"
    id         = db.Column(db.Integer, primary_key=True)
    ticket_id  = db.Column(db.Integer, db.ForeignKey("tickets.id"), indes=True)
    filename   = db.Column(db.String(200))    # 원본 파일명
    stored_path= db.Column(db.String(300))    # 실제 저장 경로
    size       = db.Column(db.Integer)
    mimetype   = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

class Event(db.Model):
    __tablename__ = "events"
    id         = db.Column(db.Integer, primary_key=True)
    ticket_id  = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    actor      = db.Column(db.String(50), nullable=False)
    action     = db.Column(db.String(50), nullable=False)     # created/comment/attach/status/assignee/priority 등
    from_value = db.Column(db.String(100))
    to_value   = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

# --------------------------------------------------------------------
# 스키마 생성 + 마이그레이션(부족 컬럼 자동 추가)
# --------------------------------------------------------------------
def ensure_schema():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # 1) 기본 tickets 테이블 생성
    cur.execute("""
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
    """)

    # 2) 부족 컬럼 자동 추가 (기존 DB가 오래된 경우)
    existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(tickets)").fetchall()]
    need_cols = [
        ("content",   "TEXT"),
        ("assignee",  "TEXT"),
        ("priority",  "TEXT DEFAULT 'med'"),
        ("status",    "TEXT DEFAULT 'open'"),
        ("created_at","TEXT"),
        ("updated_at","TEXT"),
    ]
    for name, typ in need_cols:
        if name not in existing_cols:
            cur.execute(f"ALTER TABLE tickets ADD COLUMN {name} {typ}")

    # 3) comments/attachments/events 테이블 생성
    cur.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            size INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            from_value TEXT,
            to_value TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id)
        )
    """)
    conn.commit()
    conn.close()

with app.app_context():
    db.create_all()
    ensure_schema()

# --------------------------------------------------------------------
# 공용 유틸/필터
# --------------------------------------------------------------------
   @app.template_filter("dt")
    def fmt_dt(v: datetime):
    return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else (v or "")

    def add_event(ticket_id: int, actor: str, action: str, from_value=None, to_value=None):
    ev = Event(ticket_id=ticket_id, actor=actor, action=action,
               from_value=from_value, to_value=to_value)
    db.session.add(ev)
    db.session.commit()

   @app.template_filter("k_status") 
    def k_status(v):
    return STATUS_LABELS.get(v, v or "")

   @app.template_filter("k_priority")
    def k_priority(v):
    return PRIORITY_LABELS.get(v, v or "")

   @app.template_filter("filesize")
    def filesize(n):
    try:
        n = int(n or 0)
    except:
        return "-"
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} PB"


    # --------------------------------------------------------------------
    # 라우트
    # --------------------------------------------------------------------
   @app.get("/")
    def index():
    q        = request.args.get("q", "").strip()
    status   = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()

    query = Ticket.query
    if q:
        query = query.filter((Ticket.title.contains(q)) | (Ticket.content.contains(q)))
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)

    tickets = query.order_by(Ticket.updated_at.desc()).all()
    return render_template("index.html", tickets=tickets, q=q, status=status, priority=priority, STATUS_CHOICES=STATUS_CHOICES, PRIORITY_CHOICES=PRIORITY_CHOICES)

   @app.route("/new", methods=["GET", "POST"])
    def new_ticket():
    if request.method == "POST":
        title     = request.form.get("title", "").strip()
        content   = request.form.get("content", "").strip()
        requester = request.form.get("requester", "").strip()
        priority  = request.form.get("priority", "med").strip() or "med"
        if not title or not requester:
            abort(400, "title/requester required")

        t = Ticket(title=title, content=content, requester=requester, priority=priority)
        db.session.add(t); db.session.commit()
        add_event(t.id, requester or "user", "created", None, None)
        return redirect(url_for("ticket_detail", tid=t.id))
    return render_template("new.html")

   # 상세
   @app.route("/ticket/<int:tid>", methods=["GET", "POST"])
    def ticket_detail(tid: int):
    t = Ticket.query.get_or_404(tid)

    if request.method == "POST":
        # 상태/담당자 저장
        t.status = request.form.get("status", t.status)
        t.assignee = request.form.get("assignee", t.assignee)
        db.session.commit()
        add_event(t.id, request.form.get("author", "user") or "user",
                  "update", None, f"{t.status}/{t.assignee or '-'}")
        return redirect(url_for("ticket_detail", tid=tid))

    # 목록들 조회
    comments = Comment.query.filter_by(ticket_id=tid)\
        .order_by(Comment.id.desc()).all()
    files = Attachment.query.filter_by(ticket_id=tid)\
        .order_by(Attachment.id.desc()).all()
    events = Event.query.filter_by(ticket_id=tid)\
        .order_by(Event.id.desc()).all()

    # → 템플릿으로 넘길 이름을 'attachments' 로 고정
    return render_template(
        "detail.html",
        ticket=t,
        comments=comments,
        attachments=files,   # ★ 여기 이름!
        events=events
    )

   @app.post("/ticket/<int:tid>/attach")
def upload_attach(tid: int):
    t = Ticket.query.get_or_404(tid)
    f = request.files.get("file")
    if not f or f.filename == "":
        return redirect(url_for("ticket_detail", tid=tid))

    safe_name = secure_filename(f.filename)
    leaf = f"{uuid.uuid4().hex}__{safe_name or 'file'}"
    tdir = os.path.join(FILES_DIR, str(t.id))
    os.makedirs(tdir, exist_ok=True)

    save_path = os.path.join(tdir, leaf)
    f.save(save_path)
    size = os.path.getsize(save_path)

    att = Attachment(
        ticket_id=t.id,
        filename=safe_name,
        stored_path=save_path,
        size=size,
    )
    db.session.add(att); db.session.commit()
    add_event(t.id, "user", "attach", None, safe_name)
    return redirect(url_for("ticket_detail", tid=t.id))

   
    @app.get("/files/<int:aid>")
    def download_file(aid: int):
    a = Attachment.query.get_or_404(aid)
    return send_file(a.stored_path, as_attachment=True, download_name=a.filename)

	# 헬스/버전
	@app.get("/healthz")
	def healthz():
	    return "ok", 200

	@app.get("/version")
	def version():
	    tag = os.getenv("APP_VERSION", "v1")
	    return f"<h1>Service Desk ({tag})</h1>", 200

	if __name__ == "__main__":
	    # 개발 로컬 실행용(도커에선 gunicorn 사용)
	    app.run(host="0.0.0.0", port=8080, debug=True)

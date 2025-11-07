import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------
DB_FILE = os.getenv("DB_PATH", "/data/servicedesk.db")  # 컨테이너 볼륨 경로
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

app = Flask(__name__)
# 절대 경로는 슬래시 4개 사용
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_FILE}" if DB_FILE.startswith("/") else f"sqlite:///{os.path.abspath(DB_FILE)}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --------------------------------------------------------------------------------------
# Models
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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def __repr__(self) -> str:
        return f"<Ticket {self.id}:{self.title}>"


with app.app_context():
    db.create_all()


# --------------------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------------------
@app.template_filter("dt")
def fmt_dt(v: datetime):
    return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else ""


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------
@app.get("/")
def index():
    """요청 목록 + 필터"""
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

    tickets = query.order_by(Ticket.updated_at.desc()).all()
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

        t = Ticket(title=title, content=content, requester=requester, priority=priority)
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
        db.session.commit()
        return redirect(url_for("index"))
    return render_template("detail.html", ticket=t)


# --- 운영 편의 ---
@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/version")
def version():
    # 배포 확인용 간단 엔드포인트
    tag = os.getenv("APP_VERSION", "v2 Test")
    return f"<h1>🚀 Servicedesk Flask App ({tag})</h1>", 200


# --------------------------------------------------------------------------------------
# Local run (컨테이너에서는 gunicorn이 사용함)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    # 개발 로컬 실행용
    app.run(host="0.0.0.0", port=8080, debug=True)

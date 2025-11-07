from flask import Flask, render_template, request, redirect, url_for, abort
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, Text, String, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
import os

DB_PATH = os.getenv("DB_PATH", "/data/tickets.db")      # ← 파일 기반 SQLite
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")      # ← 상태/담당 변경 보호용 토큰

app = Flask(__name__)
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    priority = Column(String(10), default="med")   # low/med/high
    status = Column(String(10), default="open")    # open/wip/done
    requester = Column(String(100), nullable=False)
    assignee = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    comments = relationship("Comment", back_populates="ticket",
                            cascade="all, delete-orphan",
                            order_by="Comment.created_at.desc()")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    author = Column(String(100), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    ticket = relationship("Ticket", back_populates="comments")

Base.metadata.create_all(engine)

@app.template_filter("dt")
def fmt_dt(v): return v.strftime("%Y-%m-%d %H:%M")

@app.get("/")
def index():
    q_status = request.args.get("status", "")
    q_priority = request.args.get("priority", "")
    q = request.args.get("q", "")
    with Session() as s:
        query = s.query(Ticket)
        if q_status:   query = query.filter(Ticket.status == q_status)
        if q_priority: query = query.filter(Ticket.priority == q_priority)
        if q:
            like = f"%{q}%"
            query = query.filter((Ticket.title.like(like)) | (Ticket.body.like(like)))
        tickets = query.order_by(Ticket.updated_at.desc()).all()
    return render_template("index.html", tickets=tickets,
                           q_status=q_status, q_priority=q_priority, q=q)

@app.get("/new")
def new_ticket_form(): return render_template("new.html")

@app.post("/new")
def new_ticket():
    f = request.form
    if not f.get("title") or not f.get("body") or not f.get("requester"):
        abort(400, "필수 항목 누락")
    t = Ticket(title=f["title"], body=f["body"], requester=f["requester"],
               priority=f.get("priority","med"))
    with Session() as s:
        s.add(t); s.commit()
    return redirect(url_for("index"))

@app.get("/t/<int:tid>")
def ticket_detail(tid):
    with Session() as s:
        t = s.get(Ticket, tid)
        if not t: abort(404)
        return render_template("detail.html", t=t)

@app.post("/t/<int:tid>/comment")
def add_comment(tid):
    f = request.form
    with Session() as s:
        t = s.get(Ticket, tid)
        if not t: abort(404)
        c = Comment(ticket_id=tid, author=f.get("author","user"), body=f["body"])
        t.updated_at = datetime.utcnow()
        s.add(c); s.commit()
    return redirect(url_for("ticket_detail", tid=tid))

@app.post("/t/<int:tid>/update")
def update_ticket(tid):
    if request.form.get("token","") != ADMIN_TOKEN:
        abort(403, "관리자 토큰이 올바르지 않습니다.")
    f = request.form
    with Session() as s:
        t = s.get(Ticket, tid)
        if not t: abort(404)
        if f.get("status"):   t.status = f["status"]
        if f.get("assignee") is not None: t.assignee = f["assignee"]
        t.updated_at = datetime.utcnow()
        s.commit()
    return redirect(url_for("ticket_detail", tid=tid))

@app.get("/healthz")
def health(): return {"ok": True, "time": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

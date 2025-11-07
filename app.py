from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

app = Flask(__name__)

# === DB 설정 ===
DATABASE_URL = "sqlite:///data/servicedesk.db"
engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    title = Column(String(200))
    description = Column(Text)
    status = Column(String(20), default="open")
    priority = Column(String(10), default="med")
    requester = Column(String(50))
    assignee = Column(String(50), default="-")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)
session = Session()

# === 라우트 ===
@app.route('/')
def index():
    q = request.args.get("q", "")
    status = request.args.get("status", "")
    priority = request.args.get("priority", "")

    tickets = session.query(Ticket)
    if q:
        tickets = tickets.filter(Ticket.title.contains(q) | Ticket.description.contains(q))
    if status:
        tickets = tickets.filter(Ticket.status == status)
    if priority:
        tickets = tickets.filter(Ticket.priority == priority)

    tickets = tickets.order_by(Ticket.updated_at.desc()).all()
    return render_template("index.html", tickets=tickets, q=q, status=status, priority=priority)

@app.route('/new', methods=['GET', 'POST'])
def new_ticket():
    if request.method == 'POST':
        t = Ticket(
            title=request.form['title'],
            description=request.form['description'],
            priority=request.form['priority'],
            requester=request.form['requester']
        )
        session.add(t)
        session.commit()
        return redirect(url_for('index'))
    return render_template('new.html')

@app.route('/ticket/<int:id>')
def ticket_detail(id):
    t = session.query(Ticket).get(id)
    return render_template('detail.html', ticket=t)

@app.route('/version')
def version():
    return "<h1>🚀 Servicedesk Flask App (v2 Test)</h1>"

@app.template_filter("dt")
def fmt_dt(v):
    return v.strftime("%Y-%m-%d %H:%M")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

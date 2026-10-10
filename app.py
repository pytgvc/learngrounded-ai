"""LearnGrounded AI: a source-grounded study companion (Track D prototype).

Run:  python app.py   then open http://127.0.0.1:5000
"""
import base64
import io
import json
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402

from core import auth, evaluate, figures, kb, learner, llm, quiz, store, tutor  # noqa: E402

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)
ALLOWED = {".pdf", ".pptx", ".vtt", ".srt", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


# ---------- sign-in settings ----------
def _load_secret_key():
    """Signs the login cookie. Uses LG_SECRET_KEY if set, otherwise a key saved in data/."""
    if os.environ.get("LG_SECRET_KEY"):
        return os.environ["LG_SECRET_KEY"]
    key_file = BASE / "data" / "secret_key.txt"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


app.secret_key = _load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)  # used when "Remember me" is ticked

PUBLIC_ENDPOINTS = {"login_page", "signup_page", "logout", "static"}


@app.before_request
def require_login():
    """Every page and API call needs a logged-in student, except the login pages."""
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if session.get("user_id"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Please log in first."}), 401
    return redirect(url_for("login_page", next=request.path))


def _start_session(user, remember):
    session.clear()
    session.permanent = remember
    session["user_id"] = user["id"]
    session["name"] = user["full_name"]


def _safe_next(target):
    """Only allow redirects to pages inside this app."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


# ---------- sign-in pages ----------
@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user_id"):
        return redirect("/")
    error, values = None, {}
    if request.method == "POST":
        login_name = (request.form.get("login") or "").strip()
        password = request.form.get("password") or ""
        values = {"login": login_name}
        key = f"{login_name.lower()}|{request.remote_addr}"
        if not login_name or not password:
            error = "Please enter your username or email and your password."
        elif auth.too_many_attempts(key):
            error = "Too many failed attempts. Please wait 15 minutes and try again."
        else:
            user = auth.verify_login(login_name, password)
            if user:
                auth.clear_failures(key)
                _start_session(user, bool(request.form.get("remember")))
                return redirect(_safe_next(request.form.get("next")))
            auth.record_failure(key)
            # Same message for "no such user" and "wrong password", so it reveals nothing.
            error = "Wrong username/email or password."
    return render_template("auth.html", mode="login", error=error, values=values,
                           next=request.values.get("next", ""))


@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if session.get("user_id"):
        return redirect("/")
    error, values = None, {}
    if request.method == "POST":
        values = {k: (request.form.get(k) or "").strip() for k in ("full_name", "username", "email")}
        password = request.form.get("password") or ""
        error = auth.validate_signup(values["full_name"], values["username"], values["email"], password)
        if not error:
            ok, error = auth.create_user(values["full_name"], values["username"],
                                         values["email"], password)
            if ok:
                user = auth.verify_login(values["username"], password)
                _start_session(user, False)
                return redirect("/")
    return render_template("auth.html", mode="signup", error=error, values=values, next="")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ---------- pages ----------
@app.route("/")
def home():
    return render_template("index.html", stats=kb.stats(), active="home")


@app.route("/chat")
def chat_page():
    stats = kb.stats()
    return render_template("chat.html", active="chat", history=store.recent_chat(40),
                           topics=stats["topics"], docs=stats["documents"])


@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html", active="quiz", topics=kb.stats()["topics"])


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html", active="dashboard", charts=build_charts(),
                           report=learner.report(), stats=kb.stats(),
                           last_eval=store.get_meta("last_eval"),
                           last_sim=store.get_meta("last_sim"))


@app.route("/evaluate")
def evaluate_page():
    return render_template("evaluate.html", active="evaluate",
                           last_eval=store.get_meta("last_eval"),
                           last_sim=store.get_meta("last_sim"))


# ---------- knowledge base ----------
@app.route("/api/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    added, errors = [], []
    for f in files:
        name = secure_filename(f.filename or "")
        if Path(name).suffix.lower() not in ALLOWED:
            errors.append(f"{f.filename}: unsupported type")
            continue
        dest = UPLOADS / f"{int(time.time()*1000)}_{name}"
        f.save(dest)
        try:
            res = kb.add_file(dest, name)
            added.append({"name": name, **res})
        except Exception as e:  # keep the app running on a bad file
            errors.append(f"{name}: {e}")
    return jsonify({"added": added, "errors": errors, "stats": kb.stats()})


@app.route("/api/figures/process", methods=["POST"])
def process_figures():
    return jsonify({**kb.process_figures(), "stats": kb.stats()})


@app.route("/figure/<int:fig_id>")
def figure_image(fig_id):
    fig = figures.get_figure(fig_id)
    if not fig:
        return ("not found", 404)
    return send_file(fig["path"], mimetype=fig["mime"])


@app.route("/files")
def files_page():
    items = []
    for p in sorted(UPLOADS.iterdir()):
        if p.is_file():
            name = p.name.split("_", 1)[1] if "_" in p.name else p.name
            items.append({"url": f"/uploads/{p.name}", "name": name,
                          "kb": round(p.stat().st_size / 1024)})
    for p in sorted(kb.SAMPLE_DIR.iterdir()):
        if p.is_file():
            items.append({"url": f"/sample/{p.name}", "name": f"{p.name} (sample course)",
                          "kb": round(p.stat().st_size / 1024)})
    return render_template("files.html", active="files", items=items,
                           figs=figures.all_figures(), llm_ready=llm.available())


@app.route("/uploads/<path:stored>")
def open_upload(stored):
    return send_from_directory(UPLOADS, stored)


@app.route("/sample/<path:name>")
def open_sample(name):
    return send_from_directory(kb.SAMPLE_DIR, name)


@app.route("/api/load-sample", methods=["POST"])
def load_sample():
    if store.all_chunks():
        return jsonify({"ok": True, "message": "Knowledge base already has material.",
                        "stats": kb.stats()})
    n = kb.load_sample()
    return jsonify({"ok": True, "units": n, "stats": kb.stats()})


@app.route("/api/reset", methods=["POST"])
def reset():
    kb.reset()
    return jsonify({"ok": True})


@app.route("/api/source/<int:chunk_id>")
def source(chunk_id):
    c = store.get_chunk(chunk_id)
    if not c:
        return jsonify({"error": "not found"}), 404
    fig = figures.figure_for_chunk(chunk_id)
    return jsonify({"id": c["id"], "source": c["source"], "location": c["location"],
                    "kind": c["kind"], "topic": c["topic"], "text": c["text"],
                    "image_url": f"/figure/{fig['id']}" if fig else None})


@app.route("/api/stats")
def stats():
    return jsonify(kb.stats())


# ---------- tutor ----------
@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.json or {}
    msg = (body.get("message") or "").strip()
    lang = "hi" if body.get("lang") == "hi" else "en"
    source = body.get("source") or None
    if not msg:
        return jsonify({"error": "empty message"}), 400
    index = kb.index()
    store.add_chat("student", msg)
    result = tutor.answer(index, msg, lang=lang, source=source)
    for cit in result["citations"]:  # show the figures from any cited page or slide
        cit["figures"] = [{"id": f["id"], "url": f"/figure/{f['id']}", "location": f["location"]}
                          for f in figures.for_location(cit["source"], cit["location"])]
    store.add_chat("tutor", result["answer"], result["citations"], result["status"])
    mastery = {}
    if result["status"] == "grounded":
        for topic in {c["topic"] for c in result["citations"][:1]}:
            mastery[topic] = learner.exposure(topic)
    return jsonify({**result, "mastery_updates": mastery})


# ---------- assessment ----------
@app.route("/api/quiz/new", methods=["POST"])
def quiz_new():
    body = request.json or {}
    mode = body.get("mode", "quiz")
    index = kb.index()
    chunks = store.all_chunks()
    if not index:
        return jsonify({"error": "Upload material first.", "questions": []}), 400
    if mode == "diagnostic":
        questions = quiz.generate(index, chunks, None, n=6, qtypes=("mcq",))
    else:
        topics = body.get("topics") or None
        qtypes = tuple(body.get("qtypes") or ["mcq", "short", "numerical"])
        questions = quiz.generate(index, chunks, topics, n=int(body.get("n", 5)),
                                  qtypes=qtypes, seed=int(time.time()))
    public = []
    for q in questions:
        opts = q["options"] if isinstance(q["options"], list) else json.loads(q["options"] or "null")
        public.append({"id": q["id"], "qtype": q["qtype"], "prompt": q["prompt"],
                       "options": opts, "topic": q["topic"], "source": q["source"],
                       "location": q["location"], "difficulty": q["difficulty"]})
    return jsonify({"mode": mode, "questions": public,
                    "note": "" if public else "No new questions left for this scope. Try another topic."})


@app.route("/api/quiz/answer", methods=["POST"])
def quiz_answer():
    body = request.json or {}
    with store.connect() as con:
        row = con.execute("SELECT * FROM questions WHERE id=?", (body.get("question_id"),)).fetchone()
    if not row:
        return jsonify({"error": "unknown question"}), 404
    given = (body.get("given") or "").strip()
    result = quiz.record_attempt(dict(row), given, mode=body.get("mode", "quiz"))
    return jsonify(result)


@app.route("/api/quiz/diagnostic/finish", methods=["POST"])
def diagnostic_finish():
    with store.connect() as con:
        rows = con.execute(
            "SELECT a.topic, a.correct FROM attempts a WHERE a.mode='diagnostic'").fetchall()
    results = [{"topic": r["topic"], "correct": bool(r["correct"])} for r in rows]
    by_topic = quiz.apply_diagnostic_priors(results) if results else {}
    return jsonify({"topics_set": len(by_topic),
                    "message": "Starting mastery set from your diagnostic."})


@app.route("/api/report")
def report():
    return jsonify(learner.report())


# ---------- evaluation ----------
@app.route("/api/evaluate", methods=["POST"])
def run_evaluation():
    index = kb.index()
    chunks = store.all_chunks()
    if not index:
        return jsonify({"error": "Upload material first."}), 400
    retr = evaluate.retrieval_metrics(index, chunks)
    sim = evaluate.simulate(index, chunks)
    store.set_meta("last_eval", retr)
    store.set_meta("last_sim", sim)
    return jsonify({"retrieval": retr, "simulation": sim})


# ---------- charts ----------
def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def build_charts():
    charts = {}
    mastery = learner.all_mastery()
    if mastery:
        topics = [m["topic"] for m in mastery][:12]
        vals = [m["p_known"] for m in mastery][:12]
        fig, ax = plt.subplots(figsize=(7, max(2.5, 0.4 * len(topics))))
        colors = ["#D9534F" if v < 0.5 else "#5CB85C" for v in vals]
        ax.barh(topics, vals, color=colors)
        ax.set_xlim(0, 1)
        ax.set_xlabel("Estimated mastery")
        ax.set_title("Mastery by topic (red = weak)")
        ax.invert_yaxis()
        charts["mastery"] = _png(fig)
    with store.connect() as con:
        rows = con.execute("SELECT mode, correct FROM attempts").fetchall()
    if rows:
        total = len(rows)
        right = sum(r["correct"] for r in rows)
        fig, ax = plt.subplots(figsize=(5, 2.6))
        ax.bar(["Correct", "Incorrect"], [right, total - right], color=["#5CB85C", "#D9534F"])
        ax.set_title(f"Answers so far: {right}/{total} correct")
        charts["accuracy"] = _png(fig)
    return charts


if __name__ == "__main__":
    app.run(debug=True, port=5000)

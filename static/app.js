// LearnGrounded AI front-end. Plain fetch calls, no build step.

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(window._tt);
  window._tt = setTimeout(() => (t.hidden = true), 2600);
}

async function api(url, body, method) {
  const opts = { method: method || (body ? "POST" : "GET"), headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// ---------- source viewer: opens the exact page / slide / timestamp ----------
async function openSource(id) {
  try {
    const s = await api(`/api/source/${id}`);
    document.getElementById("vw-title").textContent = s.source;
    document.getElementById("vw-loc").textContent =
      `${s.location} · ${s.kind === "video" ? "video timestamp" : s.kind === "slide" ? "slide" : s.kind === "diagram" ? "diagram" : "page"} · topic: ${s.topic}`;
    const img = document.getElementById("vw-img");
    if (s.image_url) { img.src = s.image_url; img.hidden = false; } else { img.hidden = true; img.removeAttribute("src"); }
    document.getElementById("vw-body").textContent = s.text;
    document.getElementById("viewer").hidden = false;
  } catch (e) { toast(e.message); }
}

// ---------- figures: describe pending diagrams with Gemini ----------
function initFigures() {
  const btn = document.getElementById("figBtn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true; btn.textContent = "Describing figures...";
    try {
      const res = await api("/api/figures/process", {});
      toast(res.message);
      if (res.described) setTimeout(() => location.reload(), 1200);
      else { btn.disabled = false; btn.textContent = "Describe figures with Gemini"; }
    } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Describe figures with Gemini"; }
  });
}
function closeViewer() { document.getElementById("viewer").hidden = true; }
document.addEventListener("click", e => {
  const c = e.target.closest(".cite");
  if (c) openSource(c.dataset.id);
  if (e.target.id === "viewer") closeViewer();
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closeViewer(); });

// ---------- home: upload, sample, reset ----------
function initHome() {
  const input = document.getElementById("fileInput");
  const dz = document.getElementById("dropzone");
  const log = document.getElementById("ingestLog");
  let pending = [];

  input.addEventListener("change", () => { pending = [...input.files]; log.textContent = `${pending.length} file(s) ready.`; });
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", e => { pending = [...e.dataTransfer.files]; log.textContent = `${pending.length} file(s) ready.`; });

  document.getElementById("uploadBtn").addEventListener("click", async () => {
    if (!pending.length) return toast("Choose files first.");
    const fd = new FormData();
    pending.forEach(f => fd.append("files", f));
    log.textContent = "Ingesting. Extracting pages, slides and caption windows...";
    try {
      const res = await api("/api/upload", fd);
      const added = res.added.map(a => {
        const figs = `, ${a.figures_found ?? 0} figure(s) found` + (a.figures_saved ? ` (${a.figures_saved} saved)` : "");
        const desc = a.figures && a.figures.message ? ` (${a.figures.message})` : "";
        return `<div class="ok">✓ ${esc(a.name)}: ${a.units} text units${figs}${desc}</div>`;
      }).join("");
      const errs = res.errors.map(x => `<div class="err">✗ ${esc(x)}</div>`).join("");
      log.innerHTML = added + errs +
        `<div style="margin-top:8px"><button class="primary" onclick="location.reload()">Refresh to see files</button></div>`;
    } catch (e) { log.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  });

  document.getElementById("sampleBtn").addEventListener("click", async () => {
    log.textContent = "Loading sample course...";
    await api("/api/load-sample", {});
    location.reload();
  });

  document.getElementById("resetBtn").addEventListener("click", async () => {
    if (!confirm("Clear the knowledge base and all progress?")) return;
    await api("/api/reset", {});
    location.reload();
  });
}

// ---------- tutor chat ----------
function initChat() {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const box = document.getElementById("messages");
  box.scrollTop = box.scrollHeight;

  function bubble(role, html, status) {
    const div = document.createElement("div");
    div.className = `msg ${role}${status === "refused" ? " refused" : ""}`;
    div.innerHTML = `<div class="bubble">${html}</div>`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
  }

  function ask(text) {
    input.value = text;
    form.requestSubmit();
  }
  document.querySelectorAll(".sugg").forEach(b => b.addEventListener("click", () => ask(b.textContent)));

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    bubble("me", esc(msg));
    const pending = bubble("tutor", "<span class='muted'>Searching your material...</span>");
    const lang = document.getElementById("langSelect")?.value || "en";
    const source = document.getElementById("docSelect")?.value || null;
    try {
      const res = await api("/api/chat", { message: msg, lang, source });
      const cites = res.citations.map(c =>
        `<button class="cite" data-id="${c.chunk_id}">${esc(c.source)} · ${esc(c.location)}${c.kind === "diagram" ? " · diagram" : ""}</button>`).join("");
      const flag = res.status === "refused" ? `<span class="flag">Not in your material</span>` : "";
      const note = res.lang_note ? `<div class="flag">${esc(res.lang_note)}</div>` : "";
      const thumbs = res.citations.flatMap(c => c.figures || [])
        .map(f => `<a href="${f.url}" target="_blank"><img class="thumb" src="${f.url}" alt="${esc(f.location)}"></a>`).join("");
      const body = res.status === "grounded" ?
        `${esc(res.answer)}${note}<div class="cites">${cites}</div>${thumbs}` :
        `${esc(res.answer)}${flag}`;
      pending.outerHTML = "";
      bubble("tutor", body, res.status);
      if (document.getElementById("readAloud")?.checked) speak(res.answer, lang);
    } catch (err) {
      pending.querySelector(".bubble").textContent = err.message;
    }
  });
}

// ---------- voice: speak questions (mic) and read answers aloud ----------
function speechLang(lang) { return lang === "hi" ? "hi-IN" : "en-IN"; }

function speak(text, lang) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/\[\d+\]/g, ""));
  u.lang = speechLang(lang);
  speechSynthesis.speak(u);
}

function initVoice() {
  const mic = document.getElementById("micBtn");
  const status = document.getElementById("voiceStatus");
  const input = document.getElementById("chatInput");
  const form = document.getElementById("chatForm");
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Rec) {
    mic.disabled = true;
    status.textContent = "Voice input works in Chrome or Edge.";
    return;
  }
  const rec = new Rec();
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = e => {
    input.value = e.results[0][0].transcript;
    mic.classList.remove("on");
    status.textContent = "";
    form.requestSubmit();
  };
  rec.onerror = e => { mic.classList.remove("on"); status.textContent = "Mic error: " + e.error; };
  rec.onend = () => mic.classList.remove("on");
  mic.addEventListener("click", () => {
    const lang = document.getElementById("langSelect").value;
    rec.lang = speechLang(lang);
    mic.classList.add("on");
    status.textContent = lang === "hi" ? "सुन रहा हूँ..." : "Listening...";
    try { rec.start(); } catch (e) { mic.classList.remove("on"); }
  });
}

// ---------- quiz ----------
function initQuiz() {
  const area = document.getElementById("quizArea");
  const note = document.getElementById("quizNote");
  let session = { questions: [], answered: 0, correct: 0, mode: "quiz" };

  function types() {
    return [...document.querySelectorAll(".qt:checked")].map(c => c.value);
  }

  async function start(mode) {
    note.textContent = "";
    const scope = document.getElementById("scope").value;
    const body = {
      mode,
      topics: scope && mode !== "diagnostic" ? [scope] : null,
      n: parseInt(document.getElementById("count").value, 10),
      qtypes: mode === "diagnostic" ? ["mcq"] : (types().length ? types() : ["mcq"]),
    };
    area.innerHTML = "<p class='muted'>Generating verified questions...</p>";
    try {
      const res = await api("/api/quiz/new", body);
      session = { questions: res.questions, answered: 0, correct: 0, mode };
      if (!res.questions.length) { area.innerHTML = `<p class="muted">${esc(res.note || "No questions.")}</p>`; return; }
      area.innerHTML = (mode === "diagnostic" ?
        "<p class='muted'>Diagnostic: a few quick questions to set your starting mastery.</p>" : "") +
        res.questions.map((q, i) => renderQ(q, i)).join("") +
        `<div class="row"><button class="primary" id="checkAll">Submit answers</button></div><div id="summary"></div>`;
      area.querySelectorAll(".qcard").forEach(card => {
        card.querySelector(".submitOne")?.addEventListener("click", () => gradeCard(card));
      });
      document.getElementById("checkAll").addEventListener("click", async () => {
        for (const card of area.querySelectorAll(".qcard:not(.done)")) await gradeCard(card);
        summarize();
      });
    } catch (e) { area.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  }

  function renderQ(q, i) {
    let inputHtml;
    if (q.options && q.qtype !== "short") {
      inputHtml = q.options.map(o => {
        const letter = o.split(". ")[0];
        return `<label class="opt"><input type="radio" name="q${q.id}" value="${letter}">${esc(o)}</label>`;
      }).join("");
    } else {
      inputHtml = `<textarea placeholder="Write your answer in your own words"></textarea>`;
    }
    return `<div class="qcard" data-id="${q.id}" data-type="${q.qtype}">
      <div class="qmeta"><span class="tag">${esc(q.topic)}</span><span class="tag">${esc(q.source)} · ${esc(q.location)}</span>
        <span class="tag ${esc(q.difficulty)}">${esc(q.difficulty)}</span></div>
      <div class="qprompt">${i + 1}. ${esc(q.prompt)}</div>
      ${inputHtml}
      <div class="row" style="margin-top:8px"><button class="submitOne">Check</button></div>
      <div class="feedback-slot"></div>
    </div>`;
  }

  async function gradeCard(card) {
    if (card.classList.contains("done")) return;
    const type = card.dataset.type;
    let given = "";
    if (type === "short") given = card.querySelector("textarea").value.trim();
    else {
      const checked = card.querySelector("input[type=radio]:checked");
      given = checked ? checked.value : "";
    }
    if (!given) return toast("Pick an option or write an answer first.");
    const res = await api("/api/quiz/answer", { question_id: parseInt(card.dataset.id, 10), given, mode: session.mode });
    card.classList.add("done");
    card.querySelectorAll("button, textarea, input").forEach(el => (el.disabled = true));
    session.answered++;
    if (res.correct) session.correct++;
    card.querySelector(".feedback-slot").innerHTML =
      `<div class="feedback ${res.correct ? "good" : "bad"}">${esc(res.feedback)}<br><small>Mastery for ${esc(res.topic)}: ${(res.mastery * 100).toFixed(0)}%</small></div>`;
  }

  async function summarize() {
    const s = document.getElementById("summary");
    if (session.mode === "diagnostic") {
      await api("/api/quiz/diagnostic/finish", {});
      s.innerHTML = `<div class="score">Diagnostic saved. Your starting mastery is set for each topic.</div>`;
      return;
    }
    const rep = await api("/api/report");
    const weak = rep.weak_topics.map(w => esc(w.topic)).join(", ") || "none yet";
    s.innerHTML = `<div class="score">Score: ${session.correct} / ${session.answered}</div>
      <p class="muted small">Weak topics to revisit: ${weak}. See the dashboard for the full report.</p>`;
  }

  document.getElementById("startQuiz").addEventListener("click", () => start("quiz"));
  document.getElementById("startDiag").addEventListener("click", () => start("diagnostic"));
}

// ---------- evaluation ----------
function initEval() {
  document.getElementById("runEval").addEventListener("click", async () => {
    const st = document.getElementById("evalStatus");
    st.textContent = "Running retrieval tests and simulated students (this takes a moment)...";
    try {
      await api("/api/evaluate", {});
      location.reload();
    } catch (e) { st.textContent = e.message; }
  });
}

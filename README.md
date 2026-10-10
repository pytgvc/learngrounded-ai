# LearnGrounded AI

# Team Solo
# Team leader jain khusi sushilkumar

A source-grounded study companion for **Multimodal AI Hackathon 2026, Track D: Personalized Tutoring & Adaptive Learning**.

It ingests textbooks (PDF), slide decks (PPTX) and lecture captions (VTT/SRT), builds a source-cited knowledge base, tutors the student only from that material, runs adaptive quizzes, and tracks mastery per topic.

## Run it (about 2 minutes)

```bash
cd learngrounded-ai
pip install -r requirements.txt          # flask, pymupdf, python-pptx, numpy, matplotlib
python make_sample_data.py               # optional: regenerates the demo course in sample_data/
python app.py                            # then open http://127.0.0.1:5000
```

Without PyMuPDF, the app falls back to `pypdf` for reading PDFs and `matplotlib` for writing the sample PDF, so it still runs.

# This project was built with the help of an AI assistant (Claude). I chose the programming languages for each part of the project (Python for the backend and AI logic, HTML/CSS and JavaScript for the pages , SQLite for saving progress .I can explain how each part works, and the dashboard charts are drawn in app.py with matplotlib.

**Demo flow (about 3 minutes):**
1. **Knowledge base:** click *Load sample course*. It ingests 13 source units across a textbook PDF, a slide deck and a lecture caption file, and detects 6 topics.
2. **Tutor:** ask *"What happens during the Calvin cycle?"*. The answer cites `Page 1` and `00:40`. Click a citation chip to open the exact excerpt. Then ask *"What is the recipe for chocolate cake?"* and the tutor refuses, saying the material does not cover it.
3. **New student:** on *Quiz*, click *New student: diagnostic* and answer 6 questions. This sets the starting mastery per topic.
4. **Quiz:** pick a scope and question types, then submit. Each answer gets cited feedback and an updated mastery score.
5. **Dashboard:** mastery bars, accuracy, weak topics, and likely misconceptions with where to revisit.
6. **Evaluation:** click *Run evaluation* to get retrieval and grounding metrics plus simulated-student results.

## How the requirements are covered

| Track D requirement | Where it lives |
|---|---|
| 1a. Ingest without manual preprocessing | `core/ingest.py`: PDF per page, PPTX per slide (title + notes), VTT/SRT captions grouped into 30 s windows |
| 1b. Units linked to origin | Every chunk stores source, page / slide / timestamp (`location`). Opened via `/api/source/<id>` |
| 1c. Topics and concepts tagged | Section headings (chapter / slide title) become topics. Captions inherit the closest topic (`core/retrieval.py: tag_topics`) |
| 1d. Figures and diagrams | PDF pages with images create figure units. Full diagram understanding is **not** implemented (see limits) |
| 2a. Cited excerpts | `core/tutor.py`: answers are built from the best-matching sentences, each cited with its location |
| 2b. Decline uncovered queries | Similarity threshold (`REFUSE_BELOW`). Refusals are flagged in the UI as *Not in your material* |
| 3a. Quizzes tagged to topic, source, difficulty | `core/quiz.py`: MCQ (fill-in-blank), short answer and numerical. Each has topic, location and difficulty |
| 3b. Verification and no repeats | Each MCQ must retrieve its own source chunk when the blank is removed (cross-check). Numerical answers are checked against the source number. Questions a student already answered are excluded |
| 3c. Cited feedback and post-assessment report | Feedback quotes the source location. `/dashboard` lists weak topics and misconceptions (wrong choice vs correct answer, with where to revisit) |
| 4a. Per-topic mastery that updates | `core/learner.py`: Bayesian Knowledge Tracing per topic. Updates on every graded answer and gives a small step on every tutor exchange |
| 4b. New students | Diagnostic quiz sets starting priors per topic (`apply_diagnostic_priors`) |
| 5a/5b. Evaluation metrics | `core/evaluate.py`: faithfulness, answer relevancy, context precision and recall, and off-material refusal accuracy, on a test set with known source locations |
| 5c. Personalization across sessions | `simulate()`: simulated students (fast, average, struggling) across 5 sessions. Compares an adaptive policy with a random baseline on mastery gain and repetition rate |

## Architecture

```
upload / sample  ->  ingest (PDF, PPTX, VTT)  ->  chunks + topics  ->  SQLite (core/store.py)
                                                        |
                              TF-IDF index in NumPy (core/retrieval.py)
                       /               |                 \
                 tutor (cited)    quiz (verified)     evaluate (metrics + simulation)
                       \               |                 /
                          learner (BKT mastery per topic)  ->  dashboard (matplotlib)
```

Flask serves the pages and a small JSON API. The front end is plain HTML, CSS and JavaScript, with no build step.

## Optional: Gemini 2.5 Flash for phrasing

Set `GEMINI_API_KEY` and the tutor will ask Gemini 2.5 Flash to phrase the answer from the retrieved excerpts only. The excerpts are still shown as citations. Without a key, or if the call fails, the tutor uses its extractive answer, so the demo works fully offline.

```bash
export GEMINI_API_KEY=your_key_here   # optional
python app.py
```

## Known limits (be upfront in the demo and the write-up)

- **Diagram understanding:** figure pages are detected and listed, but the content of diagrams is not read. The required visual pipeline (for example, Gemini reading slide images) is future work.
- **Video:** the prototype uses caption files (`.vtt` / `.srt`). It does not transcribe audio. Whisper-style transcription is out of scope for the offline demo.
- **Retrieval:** TF-IDF with NumPy, not embeddings. Paraphrased questions match less well than exact wording does.
- **Metrics:** the RAGAS-style metrics are local proxies, not official RAGAS scores. The test set is generated from the sample course. The 20-question test set and the 25-question simulation runs are small, so treat the numbers as indicative.
- **Simulation:** students are simulated, not real. Adaptive policy reduces repeats to zero and helps most for the struggling profile. For fast and average learners, random selection gains slightly more mastery at the cost of repeats. The report shows this.
- **Not implemented (optional items):** course flow map, revision material, study schedule, Hindi or mixed-language interaction, audio tutoring.

## Files

```
app.py                 Flask routes and charts
core/ingest.py         PDF / PPTX / caption ingestion with origin links
core/retrieval.py      TF-IDF index (NumPy) and topic tagging
core/tutor.py          Grounded answers, citations, refusals, optional Gemini phrasing
core/quiz.py           Question generation, verification, grading, diagnostic priors
core/learner.py        Bayesian Knowledge Tracing, weak topics, misconception report
core/evaluate.py       Retrieval / grounding metrics and simulated students
core/store.py          SQLite schema and helpers (data/learngrounded.db, created on first run)
core/kb.py             Knowledge base manager
make_sample_data.py    Builds the demo course in sample_data/
templates/, static/    Pages, styles and client-side interactions
```

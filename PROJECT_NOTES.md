# LearnGrounded AI: project notes

## Status (2026-10-10)
- Built: PDF / PPTX / caption ingestion, grounded tutor with citations and refusals,
  quizzes (MCQ, short, numerical) with verification and no repeats, diagnostic,
  BKT mastery, dashboard, evaluation (proxy RAGAS metrics + simulated students).
- Built: figure extraction from PDFs and slides, Gemini describes figures once,
  descriptions become citable diagram units.
- Built: Hindi answers (Gemini translation), voice input (mic) and read-aloud (browser).
- Not built: Hindi quizzes, audio file transcription, study schedule, flow map,
  revision cards.
- Tested offline with stubbed Gemini calls. Real Gemini calls and browser voice still need a check on your machine.

## Run it
1. Open PowerShell and go to the project folder: cd learngrounded-ai
2. (Optional, for diagrams and Hindi) set the key once: setx GEMINI_API_KEY "your_key"
   then close and reopen PowerShell.
3. Install (first time only): pip install -r requirements.txt
4. Start: python app.py
5. Open http://127.0.0.1:5000 in Chrome or Edge.
6. Stop: press Ctrl+C in PowerShell.

## First-time checklist
1. Home page: click "Load sample course". Wait for the page to reload.
2. If the key is set: click "Describe figures with Gemini".
3. Tutor: ask "What is photosynthesis?" and click a citation chip.
4. Tutor: ask "What is the recipe for chocolate cake?" (should refuse).
5. Tutor: switch language to Hindi and ask again (needs key).
6. Tutor: click the mic, speak a question.
7. Quiz: click "New student: diagnostic", answer 6 questions, press Submit.
8. Quiz: pick a scope, click "Start quiz", answer, press Submit.
9. Dashboard: check mastery bars and weak topics.
10. Evaluation: click "Run evaluation".

## If something breaks
Tell me: the page you were on, what you clicked, and the red text in PowerShell.

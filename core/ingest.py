"""Ingestion: turns PDFs, PPTX slides and VTT/SRT lecture transcripts into
source-linked chunks. Every chunk keeps its origin (page, slide, timestamp)."""
import re
from pathlib import Path

from pptx import Presentation

try:  # PyMuPDF gives page images too; fall back to pypdf if it is missing
    import fitz
except ImportError:  # pragma: no cover
    fitz = None
    from pypdf import PdfReader

MIN_CHARS = 40


def _pdf_pages(path):
    """Yields (page_number, text, image_count) for every page."""
    if fitz is not None:
        with fitz.open(path) as pdf:
            for i, page in enumerate(pdf, start=1):
                yield i, page.get_text("text"), len(page.get_images(full=True))
    else:
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, start=1):
            try:
                imgs = len(page.images)
            except Exception:
                imgs = 0
            yield i, page.extract_text() or "", imgs


def _split_paragraphs(text):
    parts = re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", text)
    out, buf = [], ""
    for p in parts:
        p = " ".join(p.split())
        if not p:
            continue
        buf = (buf + " " + p).strip()
        if len(buf) >= 200:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return [c for c in out if len(c) >= MIN_CHARS]


FOOTER = re.compile(r"^(page\s+)?\d+$", re.I)
HEADING = re.compile(r"^(chapter|unit|lesson|section)\s+\d+[:.]\s*(.+)$", re.I)


def _split_heading(text):
    """Pulls the section heading (e.g. 'Chapter 3: Photosynthesis') off a page
    and drops page-number footers. Returns (section, body)."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    lines = [l for l in lines if not FOOTER.match(l)]
    section = None
    if lines:
        m = HEADING.match(lines[0])
        if m:
            section, lines = m.group(2).strip(), lines[1:]
        elif len(lines[0]) <= 60 and not lines[0].endswith((".", "!", "?")):
            section, lines = lines[0], lines[1:]
    return section, " ".join(lines)


def ingest_pdf(path, doc_name):
    chunks = []
    for i, text, imgs in _pdf_pages(path):
        section, body = _split_heading(text)
        for c in _split_paragraphs(body):
            chunks.append({"text": c, "source": doc_name, "kind": "textbook",
                           "location": f"Page {i}", "page": i, "topic": section})
        # Diagrams/figures: record image blocks so the UI can show them
        if imgs:
            chunks.append({"text": f"[Figure on page {i}: {imgs} image(s). "
                           "Caption/context from surrounding text.]",
                           "source": doc_name, "kind": "figure",
                           "location": f"Page {i}", "page": i, "topic": section})
    return chunks


def ingest_pptx(path, doc_name):
    chunks = []
    prs = Presentation(path)
    for i, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None else None
        texts = [s.text_frame.text for s in slide.shapes
                 if s.has_text_frame and s is not title_shape]
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        body = " ".join(" ".join(texts + [notes]).split())
        for c in _split_paragraphs(body):
            chunks.append({"text": c, "source": doc_name, "kind": "slide",
                           "location": f"Slide {i}", "slide": i, "topic": title or None})
    return chunks


_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*")


def _to_seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def ingest_transcript(path, doc_name):
    """Parses .vtt / .srt captions. Each caption block becomes a chunk
    whose location is its start time, so answers can jump to the timestamp."""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", raw.replace("\r", ""))
    chunks, buf, start = [], [], None
    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip()]
        for idx, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                t = m.group(0)
                h, mi, s, ms = re.findall(r"\d+", t)[:4]
                start = _to_seconds(h, mi, s, ms)
                text = " ".join(lines[idx + 1:])
                if buf == [] or start is None:
                    buf.append((start, text))
                else:
                    buf.append((start, text))
                break
    # group captions into ~30 second windows
    window, win_start, texts = 30.0, None, []
    for t, text in buf:
        if win_start is None:
            win_start = t
        texts.append(text)
        if t - win_start >= window:
            chunks.append(_video_chunk(texts, doc_name, win_start))
            texts, win_start = [], None
    if texts and win_start is not None:
        chunks.append(_video_chunk(texts, doc_name, win_start))
    return [c for c in chunks if c]


def _video_chunk(texts, doc_name, start):
    body = " ".join(" ".join(texts).split())
    if len(body) < MIN_CHARS:
        return None
    mm, ss = divmod(int(start), 60)
    return {"text": body, "source": doc_name, "kind": "video",
            "location": f"{mm:02d}:{ss:02d}", "timestamp": start}


def ingest_file(path, doc_name=None):
    path = Path(path)
    doc_name = doc_name or path.name
    ext = path.suffix.lower()
    if ext == ".pdf":
        return ingest_pdf(path, doc_name)
    if ext == ".pptx":
        return ingest_pptx(path, doc_name)
    if ext in (".vtt", ".srt"):
        return ingest_transcript(path, doc_name)
    if ext in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        return [{"text": c, "source": doc_name, "kind": "notes",
                 "location": f"Section {i}"} for i, c in enumerate(_split_paragraphs(text), 1)]
    raise ValueError(f"Unsupported file type: {ext}")


def detect_topic(text, topics):
    """Assigns the best-matching topic label to a chunk by keyword overlap."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    best, score = "General", 0
    for topic, keywords in topics.items():
        s = len(words & keywords)
        if s > score:
            best, score = topic, s
    return best

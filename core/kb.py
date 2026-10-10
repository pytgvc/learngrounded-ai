"""Knowledge base manager: ingests files (text and figures), tags topics, describes
figures with Gemini when a key is set, and keeps the search index in sync."""
from pathlib import Path

from . import figures, llm, store
from .ingest import ingest_file
from .retrieval import Index, tag_topics

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"

_state = {"index": None}


def index():
    if _state["index"] is None:
        rebuild()
    return _state["index"]


def rebuild():
    chunks = store.all_chunks()
    _state["index"] = Index(chunks) if chunks else None
    return _state["index"]


def ingest_new(new):
    """Tags topics for new units (using existing units as anchors), stores them,
    and rebuilds the index. Returns the new unit ids."""
    if not new:
        return []
    existing = store.all_chunks()
    combined, _ = tag_topics(existing + new)
    for c, tagged in zip(new, combined[len(existing):]):
        c["topic"] = tagged["topic"]
    ids = store.insert_chunks(new)
    rebuild()
    return ids


def process_figures():
    """Describes every pending figure with Gemini. Each description becomes a
    citable 'diagram' unit at the figure's page or slide. Runs once per figure."""
    if not llm.available():
        return {"described": 0, "errors": [], "message": "Set GEMINI_API_KEY to describe figures."}
    pending = figures.pending_rows()
    if not pending:
        return {"described": 0, "errors": [], "message": "No pending figures."}
    done, errors = 0, []
    for row in pending:
        try:
            data = Path(row["path"]).read_bytes()
            context = f"{row['source']}, {row['location']}"
            if row["section"]:
                context += f", section: {row['section']}"
            desc = llm.describe_image(data, row["mime"], context)
        except (llm.LLMError, OSError) as e:
            errors.append(f"{row['location']}: {e}")
            continue
        chunk = {"text": f"[Figure, {row['location']}] {desc}", "source": row["source"],
                 "kind": "diagram", "location": row["location"], "topic": row["section"]}
        ids = ingest_new([chunk])
        figures.mark_done(row["id"], desc, ids[0])
        done += 1
    if done:
        message = f"Described {done} figure(s)."
    else:
        message = f"Gemini could not describe the figure. First error: {errors[0]}"
    return {"described": done, "errors": errors[:3], "message": message}


IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


def add_file(path, name=None):
    """Ingests one file. Images (png, jpg, webp) become figures. Returns a summary dict."""
    path = Path(path)
    doc = name or path.name
    ext = path.suffix.lower().lstrip(".")
    if ext in IMAGE_MIME:
        data = path.read_bytes()
        saved = figures.save_pending(doc, [{"location": doc, "section": None,
                                            "mime": IMAGE_MIME[ext],
                                            "ext": "jpg" if ext == "jpeg" else ext,
                                            "bytes": data}])
        result = {"units": 0, "figures_found": 1, "figures_saved": saved}
        if llm.available() and saved:
            result["figures"] = process_figures()
        return result
    new = ingest_file(path, doc)
    ingest_new(new)
    found = figures.extract(path)
    saved = figures.save_pending(doc, found)
    result = {"units": len(new), "figures_found": len(found), "figures_saved": saved}
    if llm.available() and saved:
        result["figures"] = process_figures()
    return result


def load_sample():
    total = 0
    for f in sorted(SAMPLE_DIR.iterdir()):
        if f.suffix.lower() in (".pdf", ".pptx", ".vtt", ".srt", ".txt", ".md"):
            total += add_file(f)["units"]
    return total


def stats():
    chunks = store.all_chunks()
    docs = {}
    for c in chunks:
        d = docs.setdefault(c["source"], {"name": c["source"], "kind": c["kind"], "units": 0})
        d["units"] += 1
    topics = sorted({c["topic"] for c in chunks})
    return {
        "documents": list(docs.values()),
        "units": len(chunks),
        "topics": topics,
        "figures": figures.counts(),
        "llm_ready": llm.available(),
    }


def reset():
    store.reset_all()
    _state["index"] = None

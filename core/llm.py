"""Gemini client. Reads GEMINI_API_KEY from the environment (never from code or chat).
Used for three jobs: describing diagrams/images, phrasing answers, and Hindi
translation. Every feature has an offline fallback, so the app still runs without a key."""
import base64
import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_MODEL = "gemini-3.8-flash"
_current = {"model": os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)}


class LLMError(Exception):
    def __init__(self, message, code=None, detail=""):
        super().__init__(message)
        self.code = code
        self.detail = detail


def available():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _call(model, parts, key, timeout):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": parts}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as e:  # Google returns the reason in the body
        detail = e.read().decode(errors="ignore")[:400]
        raise LLMError(f"Gemini HTTP {e.code} ({model}): {detail}", e.code, detail) from e
    except Exception as e:  # network, malformed response
        raise LLMError(f"{type(e).__name__}: {e}") from e


def generate(parts, timeout=90):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY is not set")
    try:
        return _call(_current["model"], parts, key, timeout)
    except LLMError as e:
        # A 404 that names a replacement model: switch to it and retry once.
        if e.code == 404:
            names = [m for m in re.findall(r"models/([A-Za-z0-9.\-]+)", e.detail)
                     if m != _current["model"]]
            if names:
                _current["model"] = names[-1]
                return _call(_current["model"], parts, key, timeout)
        raise


DESCRIBE_PROMPT = (
    "You are helping a student study from course material. This image is a figure, "
    "diagram, table, or textbook/slide page from the course. Describe it accurately for "
    "a learner: name the parts and labels, explain any arrows or steps in order, and list "
    "any values, units, or equations shown. If there is text, transcribe the key parts. "
    "Do not add facts that are not in the image. Use plain sentences, no markdown headers."
)


def describe_image(image_bytes, mime, context=""):
    """Returns a text description of a figure, grounded in what is visible."""
    b64 = base64.b64encode(image_bytes).decode()
    prompt = DESCRIBE_PROMPT + (f"\nContext from the course: {context}" if context else "")
    return generate([{"text": prompt},
                     {"inline_data": {"mime_type": mime, "data": b64}}])


def translate_to_hindi(text):
    """Translates an answer into Hindi (Devanagari). Keeps [n] citation markers."""
    prompt = ("Translate the following study answer into simple Hindi written in Devanagari. "
              "Keep the [1], [2] citation markers exactly as they are. Keep scientific terms "
              "in English in brackets after the Hindi word, for example ऑक्सीजन (oxygen). "
              "Return only the translation.\n\n" + text)
    return generate([{"text": prompt}])

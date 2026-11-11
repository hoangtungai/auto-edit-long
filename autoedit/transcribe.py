"""Transcribe tiếng Việt có timestamp từng từ + sửa theo glossary.json.

Backend mặc định: mlx-whisper (whisper-large-v3-turbo, chạy nhanh trên Apple Silicon,
có word_timestamps). Có thể đổi model bằng biến môi trường AUTOEDIT_WHISPER_MODEL.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from .common import ROOT, extract_wav, load_json, log, save_json

MODEL = os.environ.get("AUTOEDIT_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s.lower())
    return re.sub(r"[^\w\s%]", "", s).strip()


def transcribe(video: Path, out_json: Path, wav: Path) -> dict:
    import mlx_whisper

    extract_wav(video, wav)
    log(f"Whisper ({MODEL}) đang nghe {video.name} ...")
    res = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=MODEL,
        language="vi",
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt="Video hướng dẫn về AI: Claude Code, Claude, ChatGPT, Vibe Coding, HyperFrames, FFmpeg, Whisper.",
    )
    words = []
    for si, seg in enumerate(res["segments"]):
        for w in seg.get("words", []):
            t = w["word"].strip()
            if not t:
                continue
            words.append({"text": t, "start": round(w["start"], 3), "end": round(w["end"], 3),
                          "seg": si, "p": round(w.get("probability", 1.0), 3)})
    words = apply_glossary(words)
    for i, w in enumerate(words):
        w["id"] = f"w{i}"
    data = {"source": str(video), "text": " ".join(w["text"] for w in words), "words": words}
    save_json(out_json, data, one_per_line_key="words")
    log(f"Transcript: {len(words)} từ -> {out_json}")
    return data


def apply_glossary(words: list[dict]) -> list[dict]:
    gpath = ROOT / "glossary.json"
    if not gpath.exists():
        return words
    rules = load_json(gpath).get("replace", {})
    # cụm dài trước để "cloud code" thắng "cloud"
    rules = sorted(((norm(k).split(), v) for k, v in rules.items()), key=lambda r: -len(r[0]))
    out, i = [], 0
    while i < len(words):
        hit = None
        for src, dst in rules:
            n = len(src)
            if [norm(w["text"]) for w in words[i:i + n]] == src:
                hit = (n, dst)
                break
        if not hit:
            out.append(words[i]); i += 1; continue
        n, dst = hit
        chunk = words[i:i + n]
        m = re.search(r"[.,!?;:…]+$", chunk[-1]["text"])
        tail = m.group(0) if m else ""  # giữ dấu câu cuối
        dst_words = dst.split()
        # dồn số từ đích vào số token nguồn, giữ thời gian đầu/cuối
        if len(dst_words) <= n:
            for k, dw in enumerate(dst_words):
                w = dict(chunk[k]); w["text"] = dw
                if k == len(dst_words) - 1:
                    w["end"] = chunk[-1]["end"]; w["text"] += tail
                out.append(w)
        else:
            for k in range(n):
                w = dict(chunk[k])
                w["text"] = " ".join(dst_words[k:]) + tail if k == n - 1 else dst_words[k]
                out.append(w)
        i += n
    return out

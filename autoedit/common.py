"""Tiện ích dùng chung: đường dẫn, chạy lệnh, đọc/ghi JSON, đọc audio."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FPS = 30
W, H = 1920, 1080
SR = 16000  # sample rate cho phân tích audio


def workdir(video: Path) -> Path:
    d = ROOT / "work" / video.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def log(msg: str) -> None:
    print(f"[autoedit] {msg}", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log(" ".join(str(c) for c in cmd)[:300])
    res = subprocess.run([str(c) for c in cmd], text=True, capture_output=True, **kw)
    if res.returncode != 0:
        sys.stderr.write(res.stdout[-3000:] + "\n" + res.stderr[-3000:])
        raise SystemExit(f"Lệnh lỗi: {cmd[0]}")
    return res


def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save_json(p: Path, data, one_per_line_key: str | None = None) -> None:
    """Ghi JSON. Nếu one_per_line_key, mảng đó ghi mỗi phần tử một dòng cho dễ duyệt."""
    p = Path(p)
    if one_per_line_key and isinstance(data, dict) and one_per_line_key in data:
        d = lambda x: json.dumps(x, ensure_ascii=False)
        items = list(data.items())
        out = ["{"]
        for i, (k, v) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            if k == one_per_line_key:
                out.append(f"  {d(k)}: [")
                out.append(",\n".join("    " + d(it) for it in v))
                out.append("  ]" + comma)
            else:
                out.append(f"  {d(k)}: {d(v)}{comma}")
        out.append("}")
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
    else:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(r.stdout.strip())


def extract_wav(video: Path, out: Path) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", SR, "-c:a", "pcm_s16le", out])
    return out


def read_wav(path: Path) -> np.ndarray:
    raw = Path(path).read_bytes()
    # bỏ header WAV 44 byte (ffmpeg pcm_s16le chuẩn); tìm chunk 'data' cho chắc
    i = raw.find(b"data")
    data = raw[i + 8:] if i >= 0 else raw[44:]
    return np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0


def rms_db(samples: np.ndarray, hop: float = 0.01) -> np.ndarray:
    """Năng lượng (dBFS) theo khung 10ms."""
    n = int(SR * hop)
    k = len(samples) // n
    fr = samples[: k * n].reshape(k, n)
    r = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(r)

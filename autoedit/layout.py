"""Bố trí head text nằm sau lưng người mà không bị che mất chữ.

Đọc matte.mp4 (mặt nạ người từ RVM) trong đúng khoảng thời gian head text hiện, có tính zoom,
tìm phần thân/đầu người chiếm trong dải chữ, rồi tách chữ sang hai bên đầu sao cho chỉ mép chữ
phía trong nằm sau người (cảm giác "chữ sau lưng") còn chữ vẫn đọc được.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import ImageFont

from .common import H, ROOT, W

SAMPLE_FPS = 5
MW, MH = 480, 270                 # độ phân giải mặt nạ dùng để đo
ORIGIN = (W * 0.5, H * 0.38)      # transform-origin của camera (khớp CSS .cam)
TOP = 60                          # mép trên dải chữ
SAFE_L, SAFE_R = 96, W - 96       # vùng an toàn ngang
TUCK = 46                         # số px mép chữ được phép lùi vào sau người
FONT = ROOT / "media" / "fonts" / "Montserrat-VF.ttf"          # chữ thường: Montserrat 800
ACC_FONT = ROOT / "media" / "fonts" / "BarlowCondensed-Black.ttf"  # từ nhấn: Barlow Condensed 900, 1.18em
ACC_SCALE = 1.18


def load_matte(matte: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(matte), "-vf", f"fps={SAMPLE_FPS},scale={MW}:{MH}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, MH, MW) > 128


def zoom_at(t: float, zooms: list[dict]) -> float:
    level = 1.0
    for z in sorted(zooms, key=lambda z: z["t"]):
        s, d = z["params"]["scale"], z["params"]["dur"]
        if t < z["t"]:
            break
        if t < z["t"] + d:
            return max(level, s)  # đang chuyển: lấy mức lớn hơn cho an toàn
        level = s
    return level


def person_span(mask: np.ndarray, scale: float, y0: float, y1: float) -> tuple[float, float] | None:
    """Khoảng x (toạ độ màn hình) người chiếm trong dải y0..y1 (toạ độ màn hình) ở mức zoom scale."""
    ox, oy = ORIGIN
    sy0, sy1 = oy + (y0 - oy) / scale, oy + (y1 - oy) / scale   # về toạ độ khung gốc
    r0, r1 = max(0, int(sy0 / H * MH)), min(MH, int(np.ceil(sy1 / H * MH)))
    if r1 <= r0:
        return None
    band = mask[r0:r1]
    cols = band.mean(axis=0) > 0.04
    if not cols.any():
        return None
    xs = np.nonzero(cols)[0]
    x0, x1 = xs[0] / MW * W, (xs[-1] + 1) / MW * W
    return ox + (x0 - ox) * scale, ox + (x1 - ox) * scale


@lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_axes([800])
    return f


@lru_cache(maxsize=64)
def _acc_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ACC_FONT), size)


def text_width(words: tuple[str, ...], fs: int, acc: frozenset = frozenset()) -> float:
    if not words:
        return 0.0
    total = 0.0
    for w in words:
        if w.upper() in acc:
            afs = round(fs * ACC_SCALE)
            total += _acc_font(afs).getlength(w.upper()) + 0.24 * afs
        else:
            total += _font(fs).getlength(w.upper()) + 0.24 * fs + len(w) * 0.02 * fs
    # khớp CSS: margin 0.12em mỗi bên từ, letter-spacing 0.02em, cộng 4% dư
    return total * 1.04


def layout_headtext(text: str, t: float, dur: float, zooms: list[dict], masks: np.ndarray | None,
                    accent: str = "") -> dict:
    acc = frozenset(accent.upper().split())
    brk = None
    if "|" in text:
        a, b = text.split("|", 1)
        brk = len(a.split())
        text = (a + " " + b).replace("|", " ")
    words = tuple(text.split())
    def span_over(y0: float, y1: float):
        if masks is None or not len(masks):
            return None
        spans = []
        for k in range(int(t * SAMPLE_FPS), int((t + dur) * SAMPLE_FPS) + 1):
            if k >= len(masks):
                break
            sp = person_span(masks[k], zoom_at(k / SAMPLE_FPS, zooms), y0, y1)
            if sp:
                spans.append(sp)
        return (min(a for a, _ in spans), max(b for _, b in spans)) if spans else None

    ks = [brk] if brk is not None else list(range(0, len(words) + 1))  # luôn tách đúng chỗ đạo diễn đánh dấu
    # 1) một dòng, hai nửa hai bên đầu
    span = span_over(TOP + 0.15 * 130, TOP + 0.95 * 130)
    if span:
        L, R = span
        left_room, right_room = L + TUCK - SAFE_L, SAFE_R - (R - TUCK)
        best = None
        for fs in range(150, 70, -4):
            for k in ks:
                lw, rw = text_width(words[:k], fs, acc), text_width(words[k:], fs, acc)
                if lw <= left_room and rw <= right_room and (best is None or abs(lw - rw) < best[2]):
                    best = (fs, k, abs(lw - rw))
            if best:
                break
        if best:
            fs, k, _ = best
            return {"mode": "split", "fs": fs, "left": " ".join(words[:k]), "right": " ".join(words[k:]),
                    "xl": round(L + TUCK), "xr": round(R - TUCK), "person": [round(L), round(R)]}

    # 2) không vừa: mỗi bên xuống tối đa 2 dòng
    def two_lines(ws: tuple[str, ...], fs: int) -> tuple[float, str]:
        if len(ws) < 2:
            return text_width(ws, fs, acc), " ".join(ws)
        opts = [(max(text_width(ws[:j], fs, acc), text_width(ws[j:], fs, acc)), " ".join(ws[:j]) + "\n" + " ".join(ws[j:]))
                for j in range(1, len(ws))]
        return min(opts)

    span2 = span_over(TOP, TOP + 2 * 1.12 * 100)
    if span2:
        L, R = span2
        left_room, right_room = L + TUCK - SAFE_L, SAFE_R - (R - TUCK)
        for fs in range(112, 58, -4):
            for k in ks:
                (lw, lt), (rw, rt) = two_lines(words[:k], fs), two_lines(words[k:], fs)
                if lw <= left_room and rw <= right_room:
                    return {"mode": "split", "fs": fs, "left": lt, "right": rt,
                            "xl": round(L + TUCK), "xr": round(R - TUCK), "person": [round(L), round(R)]}
    # 2) dự phòng: căn giữa một dòng vừa khung
    fs = 150
    while fs > 64 and text_width(words, fs, acc) > SAFE_R - SAFE_L:
        fs -= 4
    span = span or span2
    return {"mode": "center", "fs": fs, "person": [round(span[0]), round(span[1])] if span else None}

"""Bước 2: làm đạo diễn -> edit_plan.json (mỗi dòng một sự kiện {t, type, params}).

Đạo diễn chính là Claude Code chạy headless (`claude -p`) đọc transcript đã cắt.
Không có lệnh `claude` thì dùng bộ luật đơn giản. Sau đó luôn qua bước "kiểm luật":
logo đúng công cụ được nhắc, không chồng chéo, và nhịp 2-3 giây có một thay đổi hình ảnh.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .common import ROOT, duration, load_json, log, run, save_json
from .transcribe import norm

MAX_GAP = 3.0       # tối đa 3s không có thay đổi hình ảnh
MIN_GAP = 2.0
LOGO_DUR = 2.6
MG_MIN, MG_MAX = 0.20, 0.30     # motion graphics toàn khung chiếm 20-30% thời lượng
MG_DUR = (2.5, 5.5)
ZOOM_SCALE = (1.0, 1.15)        # zoom nhẹ
ZOOM_DUR = (1.6, 2.8)           # zoom chậm (đang chia sẻ nội dung ứng dụng)
MG_TEMPLATES = ("title", "stat", "list", "compare", "logos")

DIRECTOR_PROMPT = """Bạn là đạo diễn dựng video YouTube 16:9 tiếng Việt (talking head, người ngồi giữa khung).
Đọc transcript (mỗi dòng: thời_gian_bắt_đầu<TAB>từ) và lên kế hoạch hình ảnh.

Trả về DUY NHẤT một JSON object: {{"events": [ ... ]}} — không giải thích, không markdown.
Các loại sự kiện:
1. headtext: chữ tiêu đề lớn nằm SAU lưng người, ngang tầm đầu. Tóm ý chính đoạn đang nói, 2-6 từ, viết HOA, tiếng Việt có dấu.
   Đầu người nằm giữa khung nên chữ được tách làm 2 nửa hai bên đầu: đặt đúng MỘT dấu " | " ở chỗ ngắt tự nhiên
   (không tách giữa từ ghép như "KINH NGHIỆM", "NỘI DUNG"; mỗi nửa tối đa ~12 ký tự). Ví dụ: "TIẾT KIỆM | 90% TOKEN".
   {{"t": giây, "type": "headtext", "params": {{"text": "NỬA TRÁI | NỬA PHẢI", "accent": "1-2 từ trong text cần tô màu nhấn", "dur": 2.5-5}}}}
2. logo: logo công cụ hiện ra đúng lúc nhắc tới. CHỈ dùng các công cụ trong danh sách: {tools}.
   {{"t": thời điểm từ đó bắt đầu, "type": "logo", "params": {{"tool": "Tên", "side": "left"|"right", "dur": 2-3}}}}
3. zoom: đẩy/kéo máy CHẬM và NHẸ (người nói đang chia sẻ nội dung ứng dụng). scale 1.0 = toàn cảnh, tối đa 1.12.
   {{"t": giây, "type": "zoom", "params": {{"scale": 1.0-1.12, "dur": 1.8-2.6}}}}
4. mg: motion graphics THAY TOÀN BỘ KHUNG HÌNH (che người nói, giọng vẫn chạy, phụ đề vẫn hiện), minh hoạ đúng ý đang nói.
   Chọn một mẫu (template) và điền nội dung tiếng Việt có dấu, ngắn gọn:
   - title:   {{"template": "title", "kicker": "nhãn nhỏ", "title": "TIÊU ĐỀ 2-7 TỪ", "accent": "từ nhấn"}}
   - stat:    {{"template": "stat", "value": "90%", "label": "nhãn con số", "sub": "dòng phụ"}}  (dùng khi có con số)
   - list:    {{"template": "list", "title": "...", "items": ["3-5 mục, mỗi mục ≤ 32 ký tự"]}}
   - compare: {{"template": "compare", "left": {{"title": "CÁCH CŨ", "points": ["≤ 3 ý, mỗi ý ≤ 28 ký tự"]}}, "right": {{"title": "CÁCH MỚI", "points": [...]}}}}
   - logos:   {{"template": "logos", "title": "...", "tools": ["chỉ tên trong danh sách công cụ"]}}
   {{"t": giây, "type": "mg", "params": {{"dur": 3-5, "template": ..., ...}}}}

Luật motion graphics: TỔNG thời lượng các mg phải chiếm 20-30% video (khoảng {mg_lo:.0f}-{mg_hi:.0f}s), mỗi cái 3-5s,
rải đều cả video, đặt ở chỗ nói về con số, danh sách/các bước, so sánh cũ-mới, công cụ. Không đặt headtext/logo trong lúc mg đang hiện.

Luật:
- Nhịp 2-3 giây phải có một thay đổi hình ảnh (bất kỳ loại nào). Video dài {dur:.1f}s.
- Đặt sự kiện đúng lúc bắt đầu một cụm ý (dùng thời gian trong transcript), không giữa từ.
- headtext không chồng lên nhau; dùng ở câu mở đầu (hook), lời chào/giới thiệu kênh, con số ấn tượng, lời hứa của video. Khoảng 1 headtext mỗi 6-10s.
- logo không hiện cùng lúc hai cái; mỗi lần nhắc lại một công cụ quá gần (<8s) thì bỏ qua.
- zoom vào (1.06-1.12) thật chậm khi nhấn mạnh, kéo ra (1.0) khi chuyển ý. Dùng ít zoom; nhịp hình ảnh chủ yếu đến từ headtext, logo và mg.

Transcript:
{transcript}
"""


def load_tools() -> list[dict]:
    return load_json(ROOT / "tools.json")["tools"]


def ensure_logo(tool: dict, wd: Path) -> Path | None:
    """Logo chính thức: có sẵn trong media/logos thì dùng; chưa có thì tải qua HyperFrames media-use (theSVG/GitHub/favicon)."""
    logos = ROOT / "media" / "logos"
    logos.mkdir(parents=True, exist_ok=True)
    for ext in ("svg", "png", "webp"):
        p = logos / f"{tool['slug']}.{ext}"
        if p.exists():
            return p
    proj = wd / "logo-fetch"
    proj.mkdir(exist_ok=True)
    env = dict(os.environ, npm_config_cache=str(ROOT / ".npm-cache"))
    r = subprocess.run(["npx", "hyperframes", "media-use", "resolve", "--type", "logo", "--entity", tool["entity"],
                        "--intent", f"{tool['name']} official logo", "--project", str(proj)],
                       cwd=ROOT, text=True, capture_output=True, env=env)
    m = re.search(r"→\s*(\S+)", r.stdout + r.stderr)
    if not m:
        log(f"THIẾU LOGO: {tool['name']} — hãy bỏ file chính thức vào media/logos/{tool['slug']}.svg")
        return None
    src = proj / m.group(1)
    dst = logos / f"{tool['slug']}{src.suffix}"
    txt = src.read_text(encoding="utf-8") if src.suffix == ".svg" else None
    if txt is not None:
        dst.write_text(txt.replace('fill="currentColor"', 'fill="#111111"'), encoding="utf-8")
    else:
        shutil.copy(src, dst)
    log(f"Đã tải logo chính thức {tool['name']} -> {dst}")
    return dst


def find_mentions(words: list[dict], tools: list[dict]) -> list[tuple[float, dict]]:
    toks = [norm(w["text"]) for w in words]
    out = []
    for i in range(len(words)):
        for tool in tools:
            for al in tool["aliases"]:
                parts = al.split()
                if toks[i:i + len(parts)] == parts:
                    out.append((words[i]["start"], tool))
                    break
    return out


def ask_claude(words: list[dict], tools: list[dict], dur: float) -> list[dict] | None:
    if not shutil.which("claude") or os.environ.get("AUTOEDIT_NO_CLAUDE"):
        return None
    transcript = "\n".join(f"{w['start']:.2f}\t{w['text']}" for w in words)
    prompt = DIRECTOR_PROMPT.format(tools=", ".join(t["name"] for t in tools) or "(không có)", dur=dur,
                                    mg_lo=dur * MG_MIN, mg_hi=dur * MG_MAX, transcript=transcript)
    log("Claude đang làm đạo diễn (claude -p) ...")
    try:
        r = subprocess.run(["claude", "-p", "--output-format", "text", "--disallowedTools", "Bash,Edit,Write,Read,WebFetch,WebSearch"],
                           input=prompt, text=True, capture_output=True, timeout=600, cwd="/tmp")
    except subprocess.TimeoutExpired:
        log("Claude quá thời gian, dùng bộ luật dự phòng."); return None
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if r.returncode != 0 or not m:
        log(f"Claude không trả JSON hợp lệ, dùng bộ luật dự phòng. {r.stderr[-300:]}"); return None
    try:
        return json.loads(m.group(0))["events"]
    except (json.JSONDecodeError, KeyError):
        log("JSON của Claude lỗi, dùng bộ luật dự phòng."); return None


def heuristic(words: list[dict], tools: list[dict], dur: float) -> list[dict]:
    """Dự phòng: headtext = 5 từ đầu mỗi câu thứ 2, logo theo lần nhắc, zoom lấp nhịp."""
    from .cut import sentences
    ev = []
    for k, s in enumerate(sentences(words)):
        if k % 2 == 0 and len(s) >= 4:
            text = " ".join(words[i]["text"] for i in s[:5]).strip(".,!?").upper()
            ev.append({"t": words[s[0]]["start"], "type": "headtext", "params": {"text": text, "accent": "", "dur": 3.5}})
    for t, tool in find_mentions(words, tools):
        ev.append({"t": t, "type": "logo", "params": {"tool": tool["name"], "side": "left", "dur": LOGO_DUR}})
    return ev


def word_starts(words: list[dict]) -> list[float]:
    return [w["start"] for w in words]


def snap(t: float, starts: list[float]) -> float:
    return min(starts, key=lambda s: abs(s - t)) if starts else t


def enforce_rules(events: list[dict], words: list[dict], tools: list[dict], dur: float) -> list[dict]:
    names = {t["name"].lower(): t for t in tools}
    starts = word_starts(words)
    mentions = find_mentions(words, tools)
    clean: list[dict] = []
    for e in sorted(events, key=lambda e: float(e.get("t", 0))):
        t, typ, p = float(e.get("t", 0)), e.get("type"), dict(e.get("params", {}))
        if not (0 <= t < dur - 0.3):
            continue
        if typ == "logo":
            tool = names.get(str(p.get("tool", "")).lower())
            # chỉ giữ logo nếu công cụ thật sự được nhắc gần thời điểm đó
            near = [mt for mt, mtool in mentions if tool and mtool is tool and abs(mt - t) < 1.5]
            if not near:
                continue
            t = near[0]; p["tool"] = tool["name"]
            p["dur"] = min(max(float(p.get("dur", LOGO_DUR)), 2.0), 3.2)
            p["side"] = p.get("side") if p.get("side") in ("left", "right") else "left"
        elif typ == "headtext":
            p["text"] = str(p.get("text", "")).strip().upper()
            p["accent"] = str(p.get("accent", "")).strip().upper()
            p["dur"] = min(max(float(p.get("dur", 3.5)), 2.0), 6.0)
            if not p["text"]:
                continue
            t = snap(t, starts)
        elif typ == "zoom":
            p["scale"] = round(min(max(float(p.get("scale", 1.0)), ZOOM_SCALE[0]), ZOOM_SCALE[1]), 3)
            p["dur"] = round(min(max(float(p.get("dur", 2.0)), ZOOM_DUR[0]), ZOOM_DUR[1]), 2)
            t = snap(t, starts)
        elif typ == "mg":
            if p.get("template") not in MG_TEMPLATES:
                p["template"] = "title"
            if p["template"] == "logos":
                p["tools"] = [names[x.lower()]["name"] for x in p.get("tools", []) if str(x).lower() in names]
                if not p["tools"]:
                    p["template"] = "title"; p.setdefault("title", "CÔNG CỤ")
            p["dur"] = round(min(max(float(p.get("dur", 4.0)), MG_DUR[0]), MG_DUR[1]), 2)
            t = snap(t, starts)
        else:
            continue
        clean.append({"t": round(t, 2), "type": typ, "params": p})
    # motion graphics: không chồng nhau, cách nhau >= 2s, tổng 20-30% thời lượng
    mgs = fit_mg_coverage([e for e in clean if e["type"] == "mg"], [e for e in clean if e["type"] == "headtext"], dur, starts)
    inside = lambda t0, t1: any(t0 < m["t"] + m["params"]["dur"] and m["t"] - 0.2 < t1 for m in mgs)
    rest = [e for e in clean if e["type"] != "mg"
            and not inside(e["t"], e["t"] + e["params"].get("dur", 0.1))]
    # bỏ chồng chéo cùng loại (headtext với headtext, logo với logo)
    out, busy = list(mgs), {"headtext": -1.0, "logo": -1.0, "zoom": -1.0}
    for e in rest:
        typ = e["type"]
        if e["t"] < busy[typ]:
            continue
        end = e["t"] + e["params"].get("dur", 0) + (0.5 if typ == "zoom" else 0)
        busy[typ] = min(end, dur)
        e["params"]["dur"] = round(min(e["params"]["dur"], dur - e["t"] - 0.05), 2)
        out.append(e)
    # nhịp: thêm zoom vào chỗ trống > 3s, xen kẽ vào/ra
    level = 1.0
    filled: list[dict] = []
    marks = sorted(out, key=lambda e: e["t"])
    times = [0.0] + [e["t"] for e in marks] + [dur]
    zoom_levels = [e["params"]["scale"] for e in marks if e["type"] == "zoom"]
    level = zoom_levels[0] if zoom_levels else 1.0
    cur = 0.0
    for e in marks + [None]:
        nxt = e["t"] if e else dur
        while nxt - cur > MAX_GAP:
            target = cur + 2.5
            t = snap(target, [s for s in starts if cur + MIN_GAP <= s <= cur + MAX_GAP]) if any(
                cur + MIN_GAP <= s <= cur + MAX_GAP for s in starts) else target
            level = 1.0 if level > 1.03 else (1.06 if len(filled) % 2 else 1.1)
            filled.append({"t": round(t, 2), "type": "zoom", "params": {"scale": level, "dur": 2.2, "auto": True}})
            cur = t
        if e:
            filled.append(e)
            if e["type"] == "zoom":
                level = e["params"]["scale"]
            # trong lúc motion graphics hiện, khung hình đã thay đổi liên tục
            cur = e["t"] + e["params"]["dur"] if e["type"] == "mg" else e["t"]
    return sorted(filled, key=lambda e: e["t"])


def fit_mg_coverage(mgs: list[dict], heads: list[dict], dur: float, starts: list[float]) -> list[dict]:
    lo, hi = dur * MG_MIN, dur * MG_MAX
    kept: list[dict] = []
    for m in sorted(mgs, key=lambda m: m["t"]):
        if kept and m["t"] < kept[-1]["t"] + kept[-1]["params"]["dur"] + 2.0:
            continue
        m["params"]["dur"] = round(min(m["params"]["dur"], dur - m["t"] - 0.3), 2)
        if m["params"]["dur"] >= MG_DUR[0]:
            kept.append(m)
    total = lambda: sum(m["params"]["dur"] for m in kept)

    def room_after(i: int) -> float:
        nxt = kept[i + 1]["t"] - 2.0 if i + 1 < len(kept) else dur - 0.3
        return nxt - (kept[i]["t"] + kept[i]["params"]["dur"])

    # thiếu: kéo dài các mg sẵn có, rồi biến headtext thành mg tiêu đề toàn khung
    for i in range(len(kept)):
        if total() >= lo + 0.5:
            break
        add = min(MG_DUR[1] - kept[i]["params"]["dur"], room_after(i), lo + 0.5 - total())
        if add > 0:
            kept[i]["params"]["dur"] = round(kept[i]["params"]["dur"] + add, 2)
    for h in sorted(heads, key=lambda h: -len(h["params"]["text"])):
        if total() >= lo + 0.5:
            break
        t0, d = h["t"], 4.0
        if t0 + d > dur - 0.3 or any(t0 < m["t"] + m["params"]["dur"] + 2.0 and m["t"] < t0 + d + 2.0 for m in kept):
            continue
        text = h["params"]["text"].replace("|", " ")
        kept.append({"t": t0, "type": "mg", "params": {"dur": d, "template": "title", "kicker": "",
                                                      "title": " ".join(text.split()), "accent": h["params"].get("accent", ""),
                                                      "auto": True}})
        kept.sort(key=lambda m: m["t"])
    # thừa: rút ngắn đều, rồi bỏ cái ngắn nhất
    while total() > hi and kept:
        over = total() - hi
        for m in kept:
            cut = min(over * m["params"]["dur"] / total(), m["params"]["dur"] - MG_DUR[0])
            m["params"]["dur"] = round(m["params"]["dur"] - max(0, cut), 2)
        if total() > hi + 0.01:
            kept.remove(min(kept, key=lambda m: m["params"]["dur"]))
    return kept


def make_plan(wd: Path) -> Path:
    tr = load_json(wd / "transcript.json")
    words = tr["words"]
    dur = duration(wd / "cut.mp4")
    tools = load_tools()
    mentioned = {tool["name"]: tool for _, tool in find_mentions(words, tools)}
    for tool in mentioned.values():
        ensure_logo(tool, wd)
    tools_ok = [t for t in tools if t["name"] in mentioned]
    events = ask_claude(words, tools_ok, dur)
    source = "claude"
    if events is None:
        events, source = heuristic(words, tools_ok, dur), "heuristic"
    events = enforce_rules(events, words, tools_ok, dur)
    out = wd / "edit_plan.json"
    save_json(out, {"source": source, "duration": round(dur, 3), "events": events}, one_per_line_key="events")
    gaps = [b["t"] - a["t"] for a, b in zip(events, events[1:])]
    mg_total = sum(e["params"]["dur"] for e in events if e["type"] == "mg")
    log(f"edit_plan ({source}): {len(events)} sự kiện, motion graphics {mg_total:.1f}s = {100 * mg_total / dur:.0f}% video, "
        f"nhịp TB {sum(gaps) / max(1, len(gaps)):.2f}s -> {out}")
    return out

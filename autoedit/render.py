"""Bước 4: render 1920x1080 H.264 + AAC, chuẩn hoá -14 LUFS, rồi tự kiểm tra và tự sửa.

Tự kiểm tra:
  1. Thông số file: 1920x1080, h264, aac, độ dài khớp bản cắt, độ to ~ -14 LUFS.
  2. Từng điểm cắt (và đầu/cuối video): trích khung hình trước/tại/sau điểm cắt; đo năng lượng âm ngay
     tại điểm nối và tìm từ bị cụt (transcribe lại bản cuối, từ quá ngắn hoặc mất từ quanh điểm nối).
  3. Caption: không tràn khung title-safe, không đè lên logo / head text; head text không bị người che quá mức.
Sai thì tự sửa (nới đoạn cắt, chia nhỏ nhóm caption, bố trí lại head text) rồi render lại (tối đa 2 vòng).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import ImageFont

from .common import FPS, H, ROOT, SR, W, duration, load_json, log, read_wav, rms_db, run, save_json

LUFS = -14.0
MAX_ROUNDS = 2
CAP_FONT = ROOT / "media" / "fonts" / "BarlowCondensed-ExtraBold.ttf"


# ------------------------------------------------------------------ render
def hf_render(hf: Path, out: Path) -> Path:
    env = dict(os.environ, npm_config_cache=str(ROOT / ".npm-cache"))
    cmd = [str(ROOT / "node_modules" / ".bin" / "hyperframes"), "render", str(hf), "-o", str(out),
           "--quality", "delivery", "--fps", str(FPS), "--workers", "3", "--skill", "hyperframes", "--quiet"]
    log("HyperFrames đang render ...")
    r = subprocess.run(cmd, text=True, capture_output=True, env=env, cwd=ROOT)
    if r.returncode != 0 or not out.exists():
        raise SystemExit(f"Render lỗi:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    (out.parent / "render.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    return out


def loudnorm(src: Path, dst: Path, length: float) -> dict:
    """Chuẩn hoá -14 LUFS hai lượt (đo rồi áp), xuất H.264 + AAC 1920x1080."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-vn", "-af",
                        f"loudnorm=I={LUFS}:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"],
                       text=True, capture_output=True)
    m = json.loads(re.findall(r"\{[^{}]+\}", r.stderr)[-1])
    af = (f"loudnorm=I={LUFS}:TP=-1.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", af + ",aresample=48000",
         "-vf", f"scale={W}:{H}:flags=lanczos,setsar=1", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", FPS, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{length:.3f}", "-movflags", "+faststart", dst])
    return m


def measure_lufs(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
                       text=True, capture_output=True)
    vals = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(vals[-1]) if vals else float("nan")


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
             "-of", "json", path])
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next(s for s in d["streams"] if s["codec_type"] == "audio")
    return {"w": v["width"], "h": v["height"], "vcodec": v["codec_name"], "acodec": a["codec_name"],
            "fps": v["r_frame_rate"], "duration": float(d["format"]["duration"])}


# ------------------------------------------------------------------ checks
def frame_strip(video: Path, t: float, out: Path) -> Path:
    """3 khung hình (t-0.2, t, t+0.2) ghép ngang để xem điểm cắt."""
    ts = [max(0, t - 0.2), t, t + 0.2]
    inputs = []
    for x in ts:
        inputs += ["-ss", f"{x:.3f}", "-i", str(video)]
    flt = "".join(f"[{i}:v]scale=640:360,trim=end_frame=1[f{i}];" for i in range(3)) + "[f0][f1][f2]hstack=3"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", flt, "-frames:v", "1", out])
    return out


def check_cut_points(final: Path, wd: Path, chk: Path) -> list[dict]:
    from .transcribe import transcribe
    issues = []
    cmap = load_json(wd / "cut_map.json")
    joins = cmap["joins"]
    total = duration(final)
    wav = chk / "final.wav"
    tr = transcribe(final, chk / "transcript_final.json", wav)
    words = tr["words"]
    db = rms_db(read_wav(wav), 0.01)
    floor = np.percentile(db, 10)
    ref_words = load_json(wd / "transcript.json")["words"]
    for k, t in enumerate(joins):
        strip = frame_strip(final, t, chk / f"cut_{k:02d}_{t:.2f}s.jpg")
        i = int(t / 0.01)
        win = db[max(0, i - 3): i + 4]
        loud = float(win.max()) if len(win) else -99
        near = [w for w in words if w["start"] - 0.25 < t < w["end"] + 0.25]
        short = [w for w in near if w["end"] - w["start"] < 0.07]
        # năng lượng tại điểm nối cao gần mức thoại => có thể cắt vào giữa chữ
        if loud > floor + 0.75 * (np.median(db) - floor) + 6 or short:
            issues.append({"kind": "cut_word", "t": t, "join": k, "loud_db": round(loud, 1),
                           "words": [w["text"] for w in near], "frames": strip.name})
    # đầu / cuối video: chữ đầu tiên/cuối cùng không được sát mép
    if words and words[0]["start"] < 0.04 and db[:4].max() > floor + 15:
        issues.append({"kind": "head_clipped", "t": 0.0, "words": [words[0]["text"]]})
    if words and total - words[-1]["end"] < 0.04:
        issues.append({"kind": "tail_clipped", "t": total, "words": [words[-1]["text"]]})
    # mất từ so với bản cắt (đơn giản: lệch số từ > 3%)
    if abs(len(words) - len(ref_words)) > max(3, 0.03 * len(ref_words)):
        issues.append({"kind": "word_count", "final": len(words), "expected": len(ref_words)})
    frame_strip(final, min(0.3, total / 2), chk / "start.jpg")
    frame_strip(final, max(0.3, total - 0.5), chk / "end.jpg")
    return issues


def caption_width(words: list[str], fs: int) -> float:
    f = ImageFont.truetype(str(CAP_FONT), fs)
    return sum(f.getlength(w.upper()) for w in words) + len(words) * 0.22 * fs + 24


def check_layout(wd: Path) -> list[dict]:
    from .compose import CAP_BOTTOM, CAP_FS, LOGO_POS, caption_groups, clean_word
    issues = []
    plan = load_json(wd / "edit_plan.json")
    words = load_json(wd / "transcript.json")["words"]
    dur = plan["duration"]
    cap_top, cap_bottom = H - CAP_BOTTOM - CAP_FS * 1.2, H - CAP_BOTTOM
    safe_w = W * 0.8
    groups = caption_groups(words, dur, size=plan.get("caption_words", 3))
    for k, g in enumerate(groups):
        cw = caption_width([clean_word(w["text"]) for w in g["words"]], CAP_FS)
        if cw > safe_w:
            issues.append({"kind": "caption_overflow", "group": k, "t": g["start"], "width": round(cw),
                           "text": " ".join(w["text"] for w in g["words"])})
        x0, x1 = (W - cw) / 2, (W + cw) / 2
        for e in plan["events"]:
            if e["type"] != "logo" or not (e["t"] < g["end"] and g["start"] < e["t"] + e["params"]["dur"]):
                continue
            lx, ly = LOGO_POS[e["params"].get("side", "left")]
            if lx < x1 and x0 < lx + 280 and ly < cap_bottom and cap_top < ly + 300:
                issues.append({"kind": "caption_covered_by_logo", "group": k, "t": g["start"], "tool": e["params"]["tool"]})
    # head text: chữ không được lùi sau người quá phần cho phép
    lay_p = wd / "headtext_layout.json"
    if lay_p.exists():
        for l in load_json(lay_p)["layouts"]:
            if l["mode"] == "center" and l.get("person"):
                issues.append({"kind": "headtext_occluded", "t": l["t"], "text": l["text"]})
    return issues


def hf_check(hf: Path, chk: Path) -> list[dict]:
    env = dict(os.environ, npm_config_cache=str(ROOT / ".npm-cache"))
    r = subprocess.run([str(ROOT / "node_modules" / ".bin" / "hyperframes"), "check", str(hf), "--json"],
                       text=True, capture_output=True, env=env, cwd=ROOT)
    (chk / "hyperframes_check.json").write_text(r.stdout, encoding="utf-8")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return [{"kind": "hf_check_failed", "detail": r.stderr[-400:]}]
    out = []

    def walk(x):
        if isinstance(x, dict):
            if "code" in x and x.get("severity") == "error":
                out.append({"kind": "hf_" + x["code"], "detail": x.get("message", "")[:200]})
            elif x.get("code") in ("text_occluded", "caption_occluded", "text_clipped"):
                out.append({"kind": "hf_" + x["code"], "detail": x.get("message", "")[:200]})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(d)
    return out


# ------------------------------------------------------------------ fixes
def fix(issues: list[dict], wd: Path) -> list[str]:
    """Tự sửa. Trả về danh sách bước cần chạy lại: 'cut' | 'compose'."""
    redo, notes = set(), []
    cl_p = wd / "cut_list.json"
    for it in issues:
        k = it["kind"]
        if k in ("cut_word", "head_clipped", "tail_clipped") and cl_p.exists():
            cl = load_json(cl_p)
            before = json.dumps(cl["cuts"])
            segs = load_json(wd / "cut_map.json")["segments"]
            if k == "cut_word":
                seg_before, seg_after = segs[it["join"]], segs[it["join"] + 1]
                for c in cl["cuts"]:
                    if abs(c["start"] - seg_before["src_end"]) < 0.02:
                        c["start"] = round(c["start"] + 0.08, 3)  # chừa thêm đuôi chữ
                    if abs(c["end"] - seg_after["src_start"]) < 0.02:
                        c["end"] = round(c["end"] - 0.08, 3)      # chừa thêm đầu chữ
                cl["cuts"] = [c for c in cl["cuts"] if c["end"] - c["start"] > 0.05]
            elif k == "head_clipped":
                for c in cl["cuts"]:
                    if c["start"] == 0:
                        c["end"] = round(max(0, c["end"] - 0.1), 3)
            else:
                for c in cl["cuts"]:
                    if abs(c["end"] - cl["duration"]) < 0.05:
                        c["start"] = round(c["start"] + 0.15, 3)
            if json.dumps(cl["cuts"]) == before:
                continue  # không có đoạn cắt nào để nới: lỗi nằm ở bản gốc, để người xem lại
            save_json(cl_p, cl, one_per_line_key="cuts")
            redo.add("cut"); notes.append(f"nới điểm cắt ({k}) tại {it.get('t', 0):.2f}s")
        elif k == "caption_overflow":
            plan = load_json(wd / "edit_plan.json")
            plan["caption_words"] = 2
            save_json(wd / "edit_plan.json", plan, one_per_line_key="events")
            redo.add("compose"); notes.append("caption tràn khung -> nhóm 2 từ")
        elif k == "caption_covered_by_logo":
            plan = load_json(wd / "edit_plan.json")
            for e in plan["events"]:
                if e["type"] == "logo" and e["params"]["tool"] == it["tool"]:
                    e["params"]["side"] = "right" if e["params"].get("side") == "left" else "left"
            save_json(wd / "edit_plan.json", plan, one_per_line_key="events")
            redo.add("compose"); notes.append(f"logo {it['tool']} che caption -> đổi bên")
        elif k == "headtext_occluded":
            plan = load_json(wd / "edit_plan.json")
            for e in plan["events"]:
                if e["type"] == "headtext" and abs(e["t"] - it["t"]) < 0.01 and "|" not in e["params"]["text"]:
                    ws = e["params"]["text"].split()
                    e["params"]["text"] = " ".join(ws[: len(ws) // 2]) + " | " + " ".join(ws[len(ws) // 2:])
            save_json(wd / "edit_plan.json", plan, one_per_line_key="events")
            redo.add("compose"); notes.append(f"head text bị che tại {it['t']:.2f}s -> tách hai bên")
    return sorted(redo), notes


# ------------------------------------------------------------------ main
def render_and_check(video: Path, wd: Path, out_dir: Path) -> Path:
    from .compose import compose
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{video.stem}_edited.mp4"
    chk = wd / "check"
    history = []
    for rnd in range(1, MAX_ROUNDS + 2):
        if chk.exists():
            shutil.rmtree(chk)
        chk.mkdir(parents=True)
        pre = check_layout(wd) + hf_check(wd / "hf", chk)
        if pre and rnd <= MAX_ROUNDS:
            redo, notes = fix(pre, wd)
            if redo:
                history.append({"round": rnd, "stage": "trước render", "issues": pre, "fixes": notes})
                log(f"Vòng {rnd}: sửa trước render: {notes}")
                if "cut" in redo:
                    _redo_cut(video, wd)
                compose(wd)
                continue
        raw = hf_render(wd / "hf", wd / "render_raw.mp4")
        expect = duration(wd / "cut.mp4")
        m = loudnorm(raw, final, expect)
        info = probe(final)
        info["lufs"] = measure_lufs(final)
        info["lufs_before"] = float(m["input_i"])
        issues = list(pre)
        if (info["w"], info["h"]) != (W, H) or info["vcodec"] != "h264" or info["acodec"] != "aac":
            issues.append({"kind": "format", "detail": info})
        if abs(info["duration"] - expect) > 1.5 / FPS:
            issues.append({"kind": "duration", "final": info["duration"], "expected": expect})
        if abs(info["lufs"] - LUFS) > 1.0:
            issues.append({"kind": "loudness", "lufs": info["lufs"]})
        issues += check_cut_points(final, wd, chk)
        history.append({"round": rnd, "stage": "sau render", "info": info, "issues": issues})
        redo, notes = fix(issues, wd) if issues and rnd <= MAX_ROUNDS else ([], [])
        if not redo:
            break
        history[-1]["fixes"] = notes
        log(f"Vòng {rnd}: phát hiện lỗi, tự sửa: {notes}")
        if "cut" in redo:
            _redo_cut(video, wd)
        compose(wd)
    write_report(final, wd, chk, history)
    log(f"XONG -> {final}")
    return final


def _redo_cut(video: Path, wd: Path) -> None:
    from .cut import apply_cuts
    from .plan import make_plan
    from .transcribe import transcribe
    cut = apply_cuts(video, wd)
    transcribe(cut, wd / "transcript.json", wd / "audio_cut.wav")
    make_plan(wd)


def write_report(final: Path, wd: Path, chk: Path, history: list[dict]) -> None:
    last = history[-1]
    info = last.get("info", {})
    lines = [f"# Báo cáo tự kiểm tra — {final.name}", "",
             f"- File: `{final}`",
             f"- Khung hình: {info.get('w')}x{info.get('h')} @ {info.get('fps')} — video {info.get('vcodec')}, audio {info.get('acodec')}",
             f"- Độ dài: {info.get('duration', 0):.2f}s",
             f"- Âm lượng: {info.get('lufs_before', 0):.1f} LUFS → {info.get('lufs', 0):.1f} LUFS (mục tiêu {LUFS})",
             f"- Số vòng render: {sum(1 for h in history if h['stage'] == 'sau render')}", ""]
    cmap = load_json(wd / "cut_map.json")
    lines.append(f"## Điểm cắt ({len(cmap['joins'])})")
    if not cmap["joins"]:
        lines.append("Không có điểm cắt giữa video (bản gốc là một take sạch). Đã kiểm tra đầu và cuối video: `check/start.jpg`, `check/end.jpg`.")
    for k, t in enumerate(cmap["joins"]):
        lines.append(f"- #{k} tại {t:.2f}s — khung hình `check/cut_{k:02d}_{t:.2f}s.jpg`")
    lines += ["", "## Lịch sử kiểm tra"]
    for h in history:
        iss = h.get("issues", [])
        lines.append(f"- Vòng {h['round']} ({h['stage']}): {len(iss)} lỗi" +
                     (f" → đã sửa: {'; '.join(h['fixes'])}" if h.get("fixes") else ""))
        for it in iss:
            lines.append(f"  - `{it['kind']}` {json.dumps({k: v for k, v in it.items() if k != 'kind'}, ensure_ascii=False)[:200]}")
    remaining = last.get("issues", [])
    lines += ["", "## Kết luận", "Đạt: không còn lỗi." if not remaining else
              f"Còn {len(remaining)} lỗi cần người xem lại (xem ở trên)."]
    (wd / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.copy(wd / "report.md", final.with_suffix(".report.md"))

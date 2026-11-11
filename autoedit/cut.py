"""Bước 1: đánh dấu từ đệm / take lặp / khoảng lặng -> cut_list.json, rồi cắt bằng FFmpeg."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from .common import FPS, H, W, duration, load_json, log, read_wav, rms_db, run, save_json
from .transcribe import norm

PAD = 0.15          # chừa đệm mỗi đầu
FADE = 0.03         # fade âm 30ms
SIM = 70            # câu giống > 70% coi là nói lại
MIN_SILENCE = 0.6   # khoảng lặng dài hơn mức này thì rút ngắn
FILLERS = {"ừm", "ừ", "ờ", "ờm", "ơ", "à", "ah", "uh", "um", "hmm", "hừm", "ứm", "ầm", "ừa"}
HOP = 0.01


class Audio:
    def __init__(self, wav: Path):
        self.db = rms_db(read_wav(wav), HOP)
        med, p10 = np.median(self.db), np.percentile(self.db, 10)
        self.thr = p10 + 0.35 * (med - p10)   # ngưỡng im lặng tự thích ứng theo từng video

    def silent(self, t: float) -> bool:
        i = int(t / HOP)
        return i < 0 or i >= len(self.db) or self.db[i] < self.thr

    def silences(self, min_len: float) -> list[tuple[float, float]]:
        out, start = [], None
        for i, v in enumerate(self.db):
            if v < self.thr and start is None:
                start = i
            elif v >= self.thr and start is not None:
                if (i - start) * HOP >= min_len:
                    out.append((start * HOP, i * HOP))
                start = None
        if start is not None and (len(self.db) - start) * HOP >= min_len:
            out.append((start * HOP, len(self.db) * HOP))
        return out

    def quietest(self, t: float, win: float = 0.06) -> float:
        a, b = max(0, int((t - win) / HOP)), min(len(self.db), int((t + win) / HOP) + 1)
        if b <= a:
            return t
        return (a + int(np.argmin(self.db[a:b]))) * HOP


def sentences(words: list[dict]) -> list[list[int]]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["text"][-1:] in ".?!" or nxt is None or nxt["seg"] != w["seg"] and w["text"][-1:] in ",;:":
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def find_marks(words: list[dict], audio: Audio) -> dict[int, str]:
    """Trả về {index từ: lý do} cho các từ cần bỏ."""
    marks: dict[int, str] = {}
    # 1) từ đệm đứng riêng (có ngắt nghỉ trước hoặc sau)
    for i, w in enumerate(words):
        if norm(w["text"]) in FILLERS:
            before = audio.silent(w["start"] - 0.08)
            after = audio.silent(w["end"] + 0.08)
            if before or after or w["p"] < 0.6:
                marks[i] = "từ đệm"
    # 2) câu nói lại: giống > 70% với câu ngay sau (trong 2 câu tới) -> bỏ câu trước, giữ take sau
    sents = sentences(words)
    txt = [norm(" ".join(words[i]["text"] for i in s)) for s in sents]
    for a in range(len(sents)):
        if len(sents[a]) < 2:
            continue
        for b in range(a + 1, min(a + 3, len(sents))):
            full = fuzz.ratio(txt[a], txt[b])
            # nói dở rồi nói lại từ đầu: câu trước ngắn hơn và khớp phần đầu câu sau
            head = fuzz.ratio(txt[a], txt[b][: len(txt[a])]) if len(txt[a]) < 0.85 * len(txt[b]) else 0
            if full > SIM or (head > 85 and len(sents[a]) >= 3):
                for i in sents[a]:
                    marks.setdefault(i, f"nói lại (giống {max(full, head):.0f}%)")
                break
    # 3) lặp cụm từ liền nhau trong cùng câu: "trong cái video trong cái video ngày hôm nay"
    n_words = [norm(w["text"]) for w in words]
    for n in range(6, 1, -1):
        for i in range(len(words) - 2 * n + 1):
            if any(k in marks for k in range(i, i + 2 * n)):
                continue
            a, b = " ".join(n_words[i:i + n]), " ".join(n_words[i + n:i + 2 * n])
            if len(a) >= 6 and fuzz.ratio(a, b) >= 90:
                for k in range(i, i + n):
                    marks[k] = f"lặp cụm từ (giống {fuzz.ratio(a, b):.0f}%)"
    return marks


def build_cut_list(words: list[dict], wav: Path, total: float) -> list[dict]:
    audio = Audio(wav)
    marks = find_marks(words, audio)
    cuts = []
    # cắt theo từ bị đánh dấu (gom các từ liền nhau)
    i = 0
    while i < len(words):
        if i not in marks:
            i += 1; continue
        j = i
        while j + 1 < len(words) and j + 1 in marks:
            j += 1
        s, e = words[i]["start"], words[j]["end"]
        # nở ra hai bên nếu là khoảng lặng
        s0, e0 = s, e
        while s > 0 and audio.silent(s - HOP) and s0 - s < 1.5:
            s -= HOP
        while e < total and audio.silent(e) and e - e0 < 1.5:
            e += HOP
        s = s + PAD if s0 - s > 2 * PAD else audio.quietest(s0)
        e = e - PAD if e - e0 > 2 * PAD else audio.quietest(e0)
        if i == 0:
            s = 0.0
        if j == len(words) - 1:
            e = total
        cuts.append({"start": s, "end": e, "reason": marks[i],
                     "text": " ".join(words[k]["text"] for k in range(i, j + 1))})
        i = j + 1
    # khoảng lặng dài -> rút còn 2 x PAD
    first, last = words[0]["start"], words[-1]["end"]
    for a, b in audio.silences(MIN_SILENCE):
        if b <= first + 0.05:          # lặng đầu video
            cuts.append({"start": 0.0, "end": max(0.0, b - PAD), "reason": "lặng đầu video", "text": ""})
        elif a >= last - 0.05:         # lặng cuối video
            cuts.append({"start": a + PAD, "end": total, "reason": "lặng cuối video", "text": ""})
        else:
            cuts.append({"start": a + PAD, "end": b - PAD, "reason": f"khoảng lặng {b - a:.2f}s", "text": ""})
    # gộp, làm tròn theo khung hình
    cuts = [c for c in cuts if c["end"] - c["start"] >= 0.1]
    cuts.sort(key=lambda c: c["start"])
    merged: list[dict] = []
    for c in cuts:
        if merged and c["start"] <= merged[-1]["end"] + 0.05:
            m = merged[-1]
            m["end"] = max(m["end"], c["end"])
            if c["reason"] not in m["reason"]:
                m["reason"] += " + " + c["reason"]
            m["text"] = (m["text"] + " " + c["text"]).strip()
        else:
            merged.append(dict(c))
    fr = lambda t: round(round(t * FPS) / FPS, 3)
    for c in merged:
        c["start"], c["end"] = fr(c["start"]), fr(min(c["end"], total))
        c["len"] = round(c["end"] - c["start"], 2)
    return [c for c in merged if c["end"] > c["start"]]


def make_cut_list(video: Path, wd: Path) -> Path:
    tr = load_json(wd / "transcript_raw.json")
    total = duration(video)
    cuts = build_cut_list(tr["words"], wd / "audio_raw.wav", total)
    out = wd / "cut_list.json"
    save_json(out, {
        "_huong_dan": "Xoá dòng nào trong 'cuts' để GIỮ lại đoạn đó. Sửa start/end nếu cần. "
                      "Duyệt xong chạy: python -m autoedit cut --apply",
        "source": str(video), "duration": total, "padding": PAD, "fade_ms": int(FADE * 1000),
        "removed_seconds": round(sum(c["len"] for c in cuts), 2), "cuts": cuts,
    }, one_per_line_key="cuts")
    log(f"{len(cuts)} đoạn cắt, bỏ {sum(c['len'] for c in cuts):.2f}s -> {out}")
    return out


def keep_segments(cut_list: dict) -> list[tuple[float, float]]:
    total = cut_list["duration"]
    keep, t = [], 0.0
    for c in sorted(cut_list["cuts"], key=lambda c: c["start"]):
        if c["start"] > t + 0.05:
            keep.append((t, c["start"]))
        t = max(t, c["end"])
    if total - t > 0.05:
        keep.append((t, total))
    return keep


def apply_cuts(video: Path, wd: Path) -> Path:
    cl = load_json(wd / "cut_list.json")
    keep = keep_segments(cl)
    fade = cl.get("fade_ms", 30) / 1000
    n = len(keep)
    f = [f"[0:v]scale={W}:{H}:flags=lanczos,fps={FPS},setsar=1,split={n}" + "".join(f"[vs{i}]" for i in range(n)),
         f"[0:a]aresample=48000,asplit={n}" + "".join(f"[as{i}]" for i in range(n))]
    for i, (a, b) in enumerate(keep):
        L = b - a
        f.append(f"[vs{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        f.append(f"[as{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                 f"afade=t=in:d={fade},afade=t=out:st={max(0, L - fade):.3f}:d={fade}[a{i}]")
    # chừa đệm đầu/cuối video: nếu bản gốc nói ngay từ khung đầu (hoặc tới tận khung cuối) thì thêm
    # khoảng lặng + giữ khung hình để chữ đầu/cuối không sát mép (đủ PAD)
    audio = Audio(wd / "audio_raw.wav")
    loud = np.nonzero(audio.db >= audio.thr)[0]
    onset = loud[0] * HOP if len(loud) else 0.0
    offset = (loud[-1] + 1) * HOP if len(loud) else keep[-1][1]
    lead = round(round(max(0.0, PAD - (onset - keep[0][0])) * FPS) / FPS, 3)
    trail = round(round(max(0.0, PAD - (keep[-1][1] - offset)) * FPS) / FPS, 3)
    vpad = []
    if lead:
        vpad.append(f"start_duration={lead}:start_mode=clone")
    if trail:
        vpad.append(f"stop_duration={trail}:stop_mode=clone")
    concat_out = "[vc][ac]" if (lead or trail) else "[v][a]"
    f.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1{concat_out}")
    if lead or trail:
        f.append(f"[vc]tpad={':'.join(vpad)}[v]")
        f.append(f"[ac]adelay={int(lead * 1000)}:all=1" + (f",apad=pad_dur={trail}" if trail else "") + "[a]")
    script = wd / "cut_filter.txt"
    script.write_text(";\n".join(f), encoding="utf-8")
    out = wd / "cut.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-filter_complex_script", script,
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-g", FPS, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    # bản đồ thời gian: đoạn giữ lại nằm ở đâu trong video mới (dùng để tự kiểm tra điểm cắt)
    segs, t = [], lead
    for a, b in keep:
        segs.append({"src_start": round(a, 3), "src_end": round(b, 3), "dst_start": round(t, 3)})
        t += b - a
    t += trail
    save_json(wd / "cut_map.json", {"segments": segs, "joins": [s["dst_start"] for s in segs[1:]],
                                    "lead_pad": lead, "tail_pad": trail})
    log(f"Đã cắt: {n} đoạn giữ lại, đệm đầu {lead}s / cuối {trail}s, còn {t:.2f}s -> {out}")
    return out

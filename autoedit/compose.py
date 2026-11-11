"""Bước 3: dựng hình bằng HyperFrames theo edit_plan.json.

Lớp (dưới -> trên):  nền studio  <  head text (sau lưng người)  <  người (RVM cutout)  <  logo
                     <  motion graphics toàn khung  <  caption
Zoom chậm, áp dụng đồng thời cho lớp nền và lớp người (như đẩy máy).
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from .common import FPS, H, ROOT, W, duration, load_json, log, run, save_json
from .matte import run_matting

SFX_DIR = ROOT / "media" / "sfx"
GSAP = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>'
FONT_FACE = """
@font-face { font-family: 'Be Vietnam Pro'; font-weight: 800; src: url('assets/fonts/BeVietnamPro-ExtraBold.ttf'); }
@font-face { font-family: 'Montserrat VN'; font-weight: 100 900; src: url('assets/fonts/Montserrat-VF.ttf'); }
@font-face { font-family: 'Barlow Condensed'; font-weight: 800; src: url('assets/fonts/BarlowCondensed-ExtraBold.ttf'); }
@font-face { font-family: 'Barlow Condensed'; font-weight: 900; src: url('assets/fonts/BarlowCondensed-Black.ttf'); }"""

ACCENT = "#38D43A"      # màu nhấn head text (xanh lá như "$10K")
HILITE = "#FFE600"      # màu vàng từ đang nói
BG_IMAGE = ROOT / "media" / "backgrounds" / "studio.jpg"
ZOOM_EASE = "sine.inOut"
LOGO_POS = {"left": (150, 300), "right": (1490, 300)}   # góc trên-trái thẻ logo 280x300
CAP_FS = 96              # cỡ chữ phụ đề (Barlow Condensed ExtraBold, như ảnh tham chiếu)
CAP_BOTTOM = 120


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ---------------------------------------------------------------- caption groups
def caption_groups(words: list[dict], dur: float, size: int = 3) -> list[dict]:
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = (len(cur) >= size or w["text"][-1:] in ".?!,;:" or nxt is None
               or nxt["start"] - w["end"] >= 0.15)
        if brk:
            groups.append(cur); cur = []
    out = []
    for k, g in enumerate(groups):
        start = max(0.1 if k == 0 else 0.0, g[0]["start"] - 0.05)
        nxt_start = groups[k + 1][0]["start"] - 0.05 if k + 1 < len(groups) else dur
        end = min(nxt_start, g[-1]["end"] + 0.4, dur - 0.02)
        end = max(end, g[-1]["end"]) if end < dur else end
        out.append({"start": round(start, 3), "end": round(min(end, dur - 0.02), 3), "words": g})
    # không chồng nhau
    for a, b in zip(out, out[1:]):
        a["end"] = min(a["end"], b["start"])
    return out


def clean_word(t: str) -> str:
    return re.sub(r"[.,!?;:…\"“”]+$", "", t).strip()


# ---------------------------------------------------------------- scenes
def scene(cid: str, css: str, body: str, js: str) -> str:
    return f"""<template>
  <style>{FONT_FACE}
    #root {{ position: absolute; inset: 0; overflow: visible; }}
{css}
  </style>
  <div id="root" data-composition-id="{cid}" data-width="{W}" data-height="{H}" data-layout-allow-overflow>
{body}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
{js}
    window.__timelines["{cid}"] = tl;
  </script>
</template>
"""


def headtext_scene(events: list[dict], layouts: list[dict]) -> str:
    css = f"""
    .ht {{ position: absolute; left: 0; top: 0; width: {W}px; height: {H}px; }}
    .ht-g {{ position: absolute; top: 60px; white-space: nowrap; font-family: 'Montserrat VN'; font-weight: 800;
      line-height: 1.12; letter-spacing: 0.02em; text-transform: uppercase;
      filter: drop-shadow(0 5px 6px rgba(0,0,0,.38)) drop-shadow(0 14px 22px rgba(0,0,0,.22)); }}
    .ht-c {{ left: 0; width: {W}px; text-align: center; }}
    .ht-w {{ display: inline-block; margin: -0.26em 0.1em; padding: 0.26em 0.02em; will-change: transform; color: transparent;
      background: linear-gradient(180deg, #FFFFFF 0%, #F4F4F4 55%, #D9D9D9 100%);
      -webkit-background-clip: text; background-clip: text; }}
    .ht-w.acc {{ font-family: 'Barlow Condensed'; font-weight: 900; font-size: 1.18em; letter-spacing: 0;
      background: linear-gradient(180deg, #6BF06B 0%, {ACCENT} 50%, #1FA824 100%);
      -webkit-background-clip: text; background-clip: text; }}"""
    body, js = [], []
    for i, (e, lay) in enumerate(zip(events, layouts)):
        p, t, d = e["params"], e["t"], e["params"]["dur"]
        acc = set(p.get("accent", "").upper().split())
        fs = lay["fs"]
        span = lambda ws: "<br>".join("".join(f'<span class="ht-w{" acc" if w.upper() in acc else ""}">{esc(w)}</span>'
                                              for w in line.split()) for line in ws.split("\n"))
        if lay["mode"] == "split":
            groups = []
            if lay["left"]:
                groups.append(f'<div class="ht-g" id="ht{i}-l" style="font-size:{fs}px; right:{W - lay["xl"]}px; text-align:right">{span(lay["left"])}</div>')
            if lay["right"]:
                groups.append(f'<div class="ht-g" id="ht{i}-r" style="font-size:{fs}px; left:{lay["xr"]}px">{span(lay["right"])}</div>')
            inner = "".join(groups)
        else:
            inner = f'<div class="ht-g ht-c" id="ht{i}-c" style="font-size:{fs}px">{span(p["text"].replace("|", " "))}</div>'
        body.append(f'    <div id="ht{i}" class="clip ht" data-start="{t}" data-duration="{d}" data-track-index="1" '
                    f'data-layout-allow-overlap>{inner}</div>')
        js.append(f'    tl.fromTo("#ht{i} .ht-w", {{ yPercent: 70, opacity: 0, filter: "blur(12px)" }}, '
                  f'{{ yPercent: 0, opacity: 1, filter: "blur(0px)", duration: 0.5, stagger: 0.07, ease: "power3.out" }}, {t});')
        drift = max(0.5, d - 0.3)
        if lay["mode"] == "split":
            if lay["left"]:
                js.append(f'    tl.fromTo("#ht{i}-l", {{ x: 0 }}, {{ x: -14, duration: {drift:.2f}, ease: "none" }}, {t});')
            if lay["right"]:
                js.append(f'    tl.fromTo("#ht{i}-r", {{ x: 0 }}, {{ x: 14, duration: {drift:.2f}, ease: "none" }}, {t});')
        js.append(f'    tl.to("#ht{i} .ht-g", {{ opacity: 0, y: -24, duration: 0.3, ease: "power2.in" }}, {t + d - 0.32:.2f});')
    return scene("headtext", css, "\n".join(body), "\n".join(js))


def logos_scene(events: list[dict], logo_files: dict[str, str]) -> str:
    css = """
    .lg { position: absolute; width: 280px; height: 300px; }
    .lg-card { width: 280px; display: flex; flex-direction: column; align-items: center; gap: 18px; }
    .lg-box { width: 220px; height: 220px; border-radius: 48px; background: #fff; display: flex;
      align-items: center; justify-content: center; box-shadow: 0 24px 60px rgba(0,0,0,.45), 0 0 0 6px rgba(255,255,255,.18); }
    .lg-box img { width: 140px; height: 140px; object-fit: contain; }
    .lg-name { font-family: 'Montserrat VN'; font-weight: 800; font-size: 40px; color: #fff; padding: 6px 22px;
      border-radius: 999px; background: rgba(10,14,28,.78); }"""
    body, js = [], []
    for i, e in enumerate(events):
        p, t, d = e["params"], e["t"], e["params"]["dur"]
        x, y = LOGO_POS[p.get("side", "left")]
        src = logo_files.get(p["tool"])
        if not src:
            continue
        body.append(f'    <div id="lg{i}" class="clip lg" data-start="{t}" data-duration="{d}" data-track-index="2" '
                    f'style="left:{x}px; top:{y}px"><div class="lg-card" id="lg{i}-c"><div class="lg-box">'
                    f'<img src="{src}" alt="{esc(p["tool"])}"></div><div class="lg-name">{esc(p["tool"])}</div></div></div>')
        js.append(f'    tl.fromTo("#lg{i}-c", {{ scale: 0.4, opacity: 0, y: 40, rotation: -8 }}, '
                  f'{{ scale: 1, opacity: 1, y: 0, rotation: 0, duration: 0.55, ease: "back.out(1.8)" }}, {t});')
        js.append(f'    tl.to("#lg{i}-c", {{ y: -12, duration: {max(0.4, d - 0.9):.2f}, ease: "sine.inOut" }}, {t + 0.55:.2f});')
        js.append(f'    tl.to("#lg{i}-c", {{ scale: 0.7, opacity: 0, duration: 0.3, ease: "power2.in" }}, {t + d - 0.32:.2f});')
    return scene("logos", css, "\n".join(body), "\n".join(js))


def captions_scene(groups: list[dict]) -> str:
    css = f"""
    .cg {{ position: absolute; left: 0; bottom: {CAP_BOTTOM}px; width: {W}px; text-align: center; }}
    .cg-line {{ display: inline-block; font-family: 'Barlow Condensed'; font-weight: 800; font-size: {CAP_FS}px;
      line-height: 1.2; color: #fff; text-transform: uppercase; letter-spacing: 0.005em;
      text-shadow: 0 0 2px rgba(0,0,0,.55), 0 3px 6px rgba(0,0,0,.45), 0 8px 26px rgba(0,0,0,.55); }}
    .cw {{ display: inline-block; margin: 0 0.11em; }}"""
    body, js = [], []
    n = 0
    for k, g in enumerate(groups):
        spans = []
        for j, w in enumerate(g["words"]):
            spans.append(f'<span class="cw" id="cw{n}">{esc(clean_word(w["text"]))}</span>')
            nxt_t = g["words"][j + 1]["start"] if j + 1 < len(g["words"]) else g["end"]
            js.append(f'    tl.set("#cw{n}", {{ color: "{HILITE}" }}, {w["start"]:.3f});')
            if nxt_t < g["end"] - 0.01:
                js.append(f'    tl.set("#cw{n}", {{ color: "#ffffff" }}, {nxt_t:.3f});')
            n += 1
        s, e = g["start"], g["end"]
        body.append(f'    <div id="cg{k}" class="clip cg" data-start="{s}" data-duration="{round(e - s, 3)}" '
                    f'data-track-index="3"><div class="cg-line" id="cg{k}-l">{"".join(spans)}</div></div>')
        js.append(f'    tl.fromTo("#cg{k}-l", {{ opacity: 0, scale: 0.92 }}, {{ opacity: 1, scale: 1, duration: 0.1, ease: "power2.out" }}, {s:.3f});')
        if e - s > 0.3:
            js.append(f'    tl.to("#cg{k}-l", {{ opacity: 0, duration: 0.1, ease: "power2.in" }}, {e - 0.1:.3f});')
        js.append(f'    tl.set("#cg{k}-l", {{ opacity: 0 }}, {e:.3f});')
    return scene("captions", css, "\n".join(body), "\n".join(js))


def index_html(dur: float, zooms: list[dict], sfx: list[dict], mgs: list[dict]) -> str:
    zjs, level = [], 1.0
    for z in zooms:
        s = z["params"]["scale"]
        zjs.append(f'      tl.fromTo(cam, {{ scale: {level} }}, {{ scale: {s}, duration: {z["params"]["dur"]}, '
                   f'ease: "{ZOOM_EASE}" }}, {z["t"]});')
        level = s
    audios = "\n".join(
        f'      <audio id="sfx{i}" class="clip" src="assets/sfx/{a["file"]}" data-start="{a["t"]}" '
        f'data-duration="{a["dur"]}" data-track-index="{10 + i % 2}" data-volume="{a["vol"]}"></audio>' for i, a in enumerate(sfx))
    mg_hosts = "\n".join(
        f'      <div id="mg{i}" data-composition-id="mg{i}" data-composition-src="compositions/mg{i}.html" '
        f'data-start="{m["t"]}" data-duration="{m["params"]["dur"]}" data-track-index="7" data-track-kind="graphics" '
        f'data-width="{W}" data-height="{H}" style="z-index:5"></div>' for i, m in enumerate(mgs))
    return f"""<!doctype html>
<html lang="vi" data-composition-variables='[{{"id":"accent","type":"color","label":"Màu nhấn","default":"{ACCENT}"}}]'>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    {GSAP}
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {W}px; height: {H}px; overflow: hidden; background: #0b1020; }}
      #root {{ position: relative; width: 100%; height: 100%; }}
      .cam {{ position: absolute; inset: 0; transform-origin: 50% 38%; }}
      #bg {{ position: absolute; inset: 0; background: #e9e6e0 url('assets/bg/studio.jpg') center / cover no-repeat; }}
      #person {{ position: absolute; left: 0; top: 0; width: {W}px; height: {H}px; object-fit: cover; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{W}" data-height="{H}">
      <div id="cam-bg" class="cam" style="z-index:1">
        <div id="bg"></div>
      </div>
      <div id="headtext" data-composition-id="headtext" data-composition-src="compositions/headtext.html"
        data-start="0" data-duration="{dur}" data-track-index="1" data-track-kind="graphics"
        data-width="{W}" data-height="{H}" style="z-index:2"></div>
      <div id="cam-fg" class="cam" style="z-index:3">
        <video id="person" class="clip" src="assets/person.webm" muted playsinline data-start="0"
          data-duration="{dur}" data-track-index="4" data-layout-allow-occlusion></video>
      </div>
      <div id="logos" data-composition-id="logos" data-composition-src="compositions/logos.html"
        data-start="0" data-duration="{dur}" data-track-index="5" data-track-kind="graphics"
        data-width="{W}" data-height="{H}" style="z-index:4"></div>
      <div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html"
        data-start="0" data-duration="{dur}" data-track-index="6" data-track-kind="captions"
        data-width="{W}" data-height="{H}" style="z-index:6"></div>
{mg_hosts}
      <audio id="voice" class="clip" src="assets/voice.m4a" data-start="0" data-duration="{dur}"
        data-track-index="9" data-volume="1"></audio>
{audios}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      const cam = ["#cam-bg", "#cam-fg"];
{chr(10).join(zjs)}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


# ---------------------------------------------------------------- main
def prepare_background(dst: Path) -> None:
    """Ảnh studio -> 1920x1080, mờ nhẹ (như xoá phông) và tối nhẹ phần rìa để chữ trắng nổi."""
    run(["ffmpeg", "-y", "-v", "error", "-i", BG_IMAGE, "-vf",
         f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=5,"
         "vignette=angle=0.55,eq=brightness=-0.035:saturation=0.95", "-q:v", "2", dst])



def compose(wd: Path) -> Path:
    cut = wd / "cut.mp4"
    dur = round(duration(cut), 3)
    plan = load_json(wd / "edit_plan.json")
    words = load_json(wd / "transcript.json")["words"]
    events = plan["events"]

    if not (wd / "person.webm").exists() or (wd / "person.webm").stat().st_mtime < cut.stat().st_mtime:
        run_matting(cut, wd)

    hf = wd / "hf"
    (hf / "compositions").mkdir(parents=True, exist_ok=True)
    for sub in ("fonts", "logos", "sfx", "bg"):
        (hf / "assets" / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(wd / "person.webm", hf / "assets" / "person.webm")
    run(["ffmpeg", "-y", "-v", "error", "-i", cut, "-vn", "-c:a", "copy", hf / "assets" / "voice.m4a"])
    for f in (ROOT / "media" / "fonts").glob("*.ttf"):
        shutil.copy(f, hf / "assets" / "fonts" / f.name)
    prepare_background(hf / "assets" / "bg" / "studio.jpg")

    from .plan import load_tools
    tools = {t["name"]: t for t in load_tools()}
    logo_files = {}
    wanted = {e["params"]["tool"] for e in events if e["type"] == "logo"}
    wanted |= {t for e in events if e["type"] == "mg" for t in e["params"].get("tools", [])}
    for name in wanted:
        if name not in tools:
            continue
        for ext in ("svg", "png", "webp"):
            src = ROOT / "media" / "logos" / f"{tools[name]['slug']}.{ext}"
            if src.exists():
                shutil.copy(src, hf / "assets" / "logos" / src.name)
                logo_files[name] = f"assets/logos/{src.name}"
                break

    heads = [e for e in events if e["type"] == "headtext"]
    logos = [e for e in events if e["type"] == "logo"]
    zooms = [e for e in events if e["type"] == "zoom"]
    mgs = [e for e in events if e["type"] == "mg"]
    sfx = [{"t": e["t"], "file": "whoosh-short.mp3", "vol": 0.3} for e in mgs]
    for e in heads:
        sfx.append({"t": round(max(0, e["t"] - 0.05), 2), "file": "whoosh-short.mp3", "vol": 0.22})
    for e in logos:
        sfx.append({"t": e["t"], "file": "pop.mp3", "vol": 0.35})
    for f in {s["file"] for s in sfx}:
        if (SFX_DIR / f).exists():
            shutil.copy(SFX_DIR / f, hf / "assets" / "sfx" / f)
    sfx = [s for s in sfx if (hf / "assets" / "sfx" / s["file"]).exists()]
    lens = {f: duration(hf / "assets" / "sfx" / f) for f in {s["file"] for s in sfx}}
    for s in sfx:
        s["dur"] = round(min(lens[s["file"]], dur - s["t"] - 0.01), 2)

    groups = caption_groups(words, dur, size=plan.get("caption_words", 3))
    from .layout import layout_headtext, load_matte
    masks = load_matte(wd / "matte.mp4") if (wd / "matte.mp4").exists() else None
    layouts = [layout_headtext(e["params"]["text"], e["t"], e["params"]["dur"], zooms, masks,
                               e["params"].get("accent", "")) for e in heads]
    save_json(wd / "headtext_layout.json", {"layouts": [dict(l, t=e["t"], text=e["params"]["text"])
                                                         for l, e in zip(layouts, heads)]}, one_per_line_key="layouts")
    (hf / "compositions" / "headtext.html").write_text(headtext_scene(heads, layouts), encoding="utf-8")
    (hf / "compositions" / "logos.html").write_text(logos_scene(logos, logo_files), encoding="utf-8")
    (hf / "compositions" / "captions.html").write_text(captions_scene(groups), encoding="utf-8")
    from .mg import mg_scene
    for old in (hf / "compositions").glob("mg*.html"):
        old.unlink()
    for i, m in enumerate(mgs):
        (hf / "compositions" / f"mg{i}.html").write_text(mg_scene(f"mg{i}", f"m{i}", m, logo_files), encoding="utf-8")
    (hf / "index.html").write_text(index_html(dur, zooms, sfx, mgs), encoding="utf-8")
    (hf / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}, "authoringSkill": "hyperframes"}, indent=2), encoding="utf-8")
    (hf / "meta.json").write_text(json.dumps({"id": f"autoedit-{wd.name}", "name": wd.name}), encoding="utf-8")
    log(f"Dựng xong project HyperFrames: {len(heads)} head text, {len(logos)} logo, {len(zooms)} zoom, {len(mgs)} motion graphic, "
        f"{len(groups)} nhóm caption -> {hf}")
    return hf

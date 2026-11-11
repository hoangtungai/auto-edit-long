"""Motion graphics thay toàn bộ khung hình (người nói bị che, giọng vẫn chạy, caption vẫn hiện).

Mỗi sự kiện mg là một sub-composition riêng. Các mẫu:
  title   {kicker, title, accent}
  stat    {value: "90%", label, sub}
  list    {title, items: [..]}
  compare {left: {title, points}, right: {title, points}}
  logos   {title, tools: [tên công cụ]}
Nội dung nằm trong dải y 70-800 để chừa chỗ cho caption ở đáy.
"""
from __future__ import annotations

import html
import re

from .common import H, W

BG = "#0F1117"
INK = "#FFFFFF"
MUTED = "#9AA3B5"
YELLOW = "#FFE600"
GREEN = "#36D35A"
RED = "#FF5A5A"

FONTS = """
@font-face { font-family: 'Montserrat VN'; font-weight: 100 900; src: url('assets/fonts/Montserrat-VF.ttf'); }
@font-face { font-family: 'Barlow Condensed'; font-weight: 800; src: url('assets/fonts/BarlowCondensed-ExtraBold.ttf'); }
@font-face { font-family: 'Barlow Condensed'; font-weight: 900; src: url('assets/fonts/BarlowCondensed-Black.ttf'); }"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _accent_words(text: str, accent: str, cls: str) -> str:
    acc = set(accent.upper().split())
    return "".join(f'<span class="{cls}{" acc" if w.upper() in acc else ""}">{esc(w)}</span>' for w in text.split())


def scene(cid: str, p: str, d: float, css: str, body: str, js: list[str]) -> str:
    """Khung chung: nền tối + lưới + quầng sáng, wipe vào/ra."""
    return f"""<template>
  <style>{FONTS}
    #root {{ position: absolute; inset: 0; }}
    #{p}-wrap {{ position: absolute; inset: 0; background: {BG}; overflow: hidden; }}
    #{p}-grid {{ position: absolute; inset: -60px; opacity: .08;
      background-image: linear-gradient(rgba(255,255,255,.7) 1px, transparent 1px),
                        linear-gradient(90deg, rgba(255,255,255,.7) 1px, transparent 1px);
      background-size: 80px 80px; }}
    #{p}-glow {{ position: absolute; left: 1060px; top: -260px; width: 1100px; height: 1100px; border-radius: 50%;
      background: radial-gradient(circle, rgba(255,230,0,.20) 0%, rgba(255,230,0,0) 65%); }}
    .{p}-c {{ position: absolute; left: 0; width: {W}px; text-align: center; color: {INK}; }}
{css}
  </style>
  <div id="root" data-composition-id="{cid}" data-width="{W}" data-height="{H}">
    <div id="{p}-wrap">
      <div id="{p}-grid"></div>
      <div id="{p}-glow"></div>
{body}
    </div>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.fromTo("#{p}-wrap", {{ clipPath: "inset(0% 0% 100% 0%)" }}, {{ clipPath: "inset(0% 0% 0% 0%)", duration: 0.45, ease: "power3.inOut" }}, 0);
    tl.fromTo("#{p}-grid", {{ x: 0, y: 0 }}, {{ x: -80, y: -40, duration: {d:.2f}, ease: "none" }}, 0);
    tl.fromTo("#{p}-glow", {{ scale: 0.85 }}, {{ scale: 1.1, duration: {d:.2f}, ease: "sine.inOut" }}, 0);
{chr(10).join(js)}
    tl.to("#{p}-wrap", {{ clipPath: "inset(100% 0% 0% 0%)", duration: 0.4, ease: "power3.inOut" }}, {d - 0.42:.2f});
    window.__timelines["{cid}"] = tl;
  </script>
</template>
"""


def mg_title(cid: str, p: str, d: float, a: dict) -> str:
    title = str(a.get("title", "")).upper()
    n = len(title)
    fs = 150 if n <= 16 else 124 if n <= 26 else 104 if n <= 36 else 88
    css = f"""
    #{p}-k {{ top: 250px; font-family: 'Montserrat VN'; font-weight: 700; font-size: 38px; letter-spacing: .22em; color: {YELLOW}; }}
    #{p}-t {{ top: 320px; padding: 0 140px; font-family: 'Montserrat VN'; font-weight: 900; font-size: {fs}px; line-height: 1.08;
      text-transform: uppercase; }}
    .{p}-w {{ display: inline-block; margin: 0 .14em; }}
    .{p}-w.acc {{ color: {YELLOW}; }}
    #{p}-bar {{ position: absolute; left: 760px; top: 720px; width: 400px; height: 10px; border-radius: 5px; background: {YELLOW}; }}"""
    body = (f'      <div class="{p}-c" id="{p}-k">{esc(str(a.get("kicker", "")).upper())}</div>\n'
            f'      <div class="{p}-c" id="{p}-t">{_accent_words(title, str(a.get("accent", "")), p + "-w")}</div>\n'
            f'      <div id="{p}-bar"></div>')
    js = [f'    tl.fromTo("#{p}-k", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }}, 0.35);',
          f'    tl.fromTo("#{p}-t .{p}-w", {{ opacity: 0, yPercent: 60, scale: 1.25 }}, {{ opacity: 1, yPercent: 0, scale: 1, duration: 0.45, stagger: 0.08, ease: "back.out(1.6)" }}, 0.45);',
          f'    tl.fromTo("#{p}-bar", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.6, ease: "power3.out" }}, 0.9);',
          f'    tl.fromTo("#{p}-t", {{ scale: 1 }}, {{ scale: 1.04, duration: {max(0.5, d - 1):.2f}, ease: "none" }}, 0.5);']
    return scene(cid, p, d, css, body, js)


def mg_stat(cid: str, p: str, d: float, a: dict) -> str:
    value = str(a.get("value", "100%"))
    m = re.match(r"^(\D*?)([\d.,]+)(.*)$", value)
    pre, num, suf = (m.group(1), m.group(2), m.group(3)) if m else ("", "", value)
    target = float(num.replace(",", ".")) if num else 0
    pct = min(100.0, target) if "%" in suf else 100.0
    css = f"""
    #{p}-n {{ top: 120px; font-family: 'Barlow Condensed'; font-weight: 900; font-size: 330px; line-height: 1; color: {YELLOW};
      text-shadow: 0 18px 60px rgba(255,230,0,.25); }}
    #{p}-l {{ top: 480px; font-family: 'Montserrat VN'; font-weight: 800; font-size: 66px; text-transform: uppercase; }}
    #{p}-s {{ top: 572px; font-family: 'Montserrat VN'; font-weight: 600; font-size: 36px; color: {MUTED}; }}
    #{p}-track {{ position: absolute; left: 410px; top: 690px; width: 1100px; height: 26px; border-radius: 13px; background: rgba(255,255,255,.12); }}
    #{p}-fill {{ position: absolute; left: 0; top: 0; height: 26px; width: {pct * 11:.0f}px; border-radius: 13px;
      background: linear-gradient(90deg, {YELLOW}, #FFB800); transform-origin: 0 50%; }}"""
    start = f"{pre}0{suf}" if num else value
    body = (f'      <div class="{p}-c" id="{p}-n">{esc(start)}</div>\n'
            f'      <div class="{p}-c" id="{p}-l">{esc(a.get("label", ""))}</div>\n'
            f'      <div class="{p}-c" id="{p}-s">{esc(a.get("sub", ""))}</div>\n'
            f'      <div id="{p}-track"><div id="{p}-fill"></div></div>')
    js = [f'    tl.fromTo("#{p}-n", {{ opacity: 0, scale: 0.6 }}, {{ opacity: 1, scale: 1, duration: 0.5, ease: "back.out(1.8)" }}, 0.35);',
          f'    tl.fromTo("#{p}-l", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }}, 0.6);',
          f'    tl.fromTo("#{p}-s", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }}, 0.8);',
          f'    tl.fromTo("#{p}-fill", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 1.3, ease: "power2.out" }}, 0.6);']
    if num:
        dec = len(num.split(".")[1]) if "." in num else 0
        js.append(f'    {{ const el = document.querySelector("#{p}-n"); const o = {{ v: 0 }};\n'
                  f'      tl.fromTo(o, {{ v: 0 }}, {{ v: {target}, duration: 1.3, ease: "power2.out", '
                  f'onUpdate: () => {{ el.textContent = {pre!r} + o.v.toFixed({dec}) + {suf!r}; }} }}, 0.4); }}')
    return scene(cid, p, d, css, body, js)


def mg_list(cid: str, p: str, d: float, a: dict) -> str:
    items = [str(x) for x in a.get("items", [])][:5] or ["..."]
    n = len(items)
    row_h = 112 if n <= 4 else 96
    top0 = 250 + (5 - n) * 22
    css = f"""
    #{p}-t {{ top: 110px; font-family: 'Montserrat VN'; font-weight: 900; font-size: 78px; text-transform: uppercase; }}
    .{p}-row {{ position: absolute; left: 420px; width: 1080px; height: {row_h - 16}px; display: flex; align-items: center; gap: 34px;
      padding: 0 34px; border-radius: 24px; background: rgba(255,255,255,.06); border: 2px solid rgba(255,255,255,.08); }}
    .{p}-num {{ flex: none; width: 66px; height: 66px; border-radius: 50%; background: {YELLOW}; color: #111;
      font-family: 'Barlow Condensed'; font-weight: 900; font-size: 46px; display: flex; align-items: center; justify-content: center; }}
    .{p}-txt {{ font-family: 'Montserrat VN'; font-weight: 700; font-size: 44px; color: {INK}; white-space: nowrap; }}"""
    rows = [f'      <div class="{p}-c" id="{p}-t">{esc(a.get("title", ""))}</div>']
    js = [f'    tl.fromTo("#{p}-t", {{ opacity: 0, y: -30 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }}, 0.35);']
    step = min(0.55, max(0.2, (d - 1.6) / n))
    for i, it in enumerate(items):
        rows.append(f'      <div class="{p}-row" id="{p}-r{i}" style="top:{top0 + i * row_h}px"><div class="{p}-num">{i + 1}</div>'
                    f'<div class="{p}-txt">{esc(it)}</div></div>')
        js.append(f'    tl.fromTo("#{p}-r{i}", {{ opacity: 0, x: -80 }}, {{ opacity: 1, x: 0, duration: 0.45, ease: "power3.out" }}, {0.6 + i * step:.2f});')
    return scene(cid, p, d, css, "\n".join(rows), js)


def mg_compare(cid: str, p: str, d: float, a: dict) -> str:
    L, R = a.get("left", {}), a.get("right", {})
    css = f"""
    .{p}-card {{ position: absolute; top: 170px; width: 700px; height: 560px; border-radius: 36px; padding: 48px 52px; }}
    #{p}-L {{ left: 190px; background: rgba(255,255,255,.06); border: 2px solid rgba(255,255,255,.10); }}
    #{p}-R {{ left: 1030px; background: rgba(255,230,0,.08); border: 3px solid {YELLOW}; box-shadow: 0 30px 80px rgba(255,230,0,.15); }}
    .{p}-h {{ font-family: 'Montserrat VN'; font-weight: 900; font-size: 58px; text-transform: uppercase; color: {INK}; margin-bottom: 38px; }}
    #{p}-R .{p}-h {{ color: {YELLOW}; }}
    .{p}-pt {{ display: flex; gap: 20px; align-items: flex-start; font-family: 'Montserrat VN'; font-weight: 600; font-size: 44px;
      line-height: 1.25; color: {INK}; margin-bottom: 26px; }}
    .{p}-ic {{ flex: none; width: 50px; height: 50px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
      font-family: 'Montserrat VN'; font-weight: 900; font-size: 30px; color: #111; margin-top: -2px; }}
    #{p}-L .{p}-ic {{ background: {RED}; }}
    #{p}-R .{p}-ic {{ background: {GREEN}; }}
    #{p}-vs {{ position: absolute; left: 900px; top: 400px; width: 120px; height: 120px; border-radius: 50%; background: {YELLOW};
      color: #111; font-family: 'Barlow Condensed'; font-weight: 900; font-size: 60px; display: flex; align-items: center; justify-content: center; }}"""

    def card(side: str, c: dict, icon: str) -> str:
        pts = "".join(f'<div class="{p}-pt"><div class="{p}-ic">{icon}</div><div>{esc(x)}</div></div>' for x in c.get("points", [])[:3])
        return f'      <div class="{p}-card" id="{p}-{side}"><div class="{p}-h">{esc(c.get("title", ""))}</div>{pts}</div>'

    body = "\n".join([card("L", L, "✕"), card("R", R, "✓"), f'      <div id="{p}-vs">VS</div>'])
    js = [f'    tl.fromTo("#{p}-L", {{ opacity: 0, x: -120 }}, {{ opacity: 1, x: 0, duration: 0.5, ease: "power3.out" }}, 0.35);',
          f'    tl.fromTo("#{p}-vs", {{ opacity: 0, scale: 0 }}, {{ opacity: 1, scale: 1, duration: 0.4, ease: "back.out(2)" }}, 0.7);',
          f'    tl.fromTo("#{p}-R", {{ opacity: 0, x: 120 }}, {{ opacity: 1, x: 0, duration: 0.5, ease: "power3.out" }}, {min(1.2, d * 0.3):.2f});',
          f'    tl.fromTo("#{p}-L .{p}-pt", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.3, stagger: 0.12 }}, 0.6);',
          f'    tl.fromTo("#{p}-R .{p}-pt", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.3, stagger: 0.12 }}, {min(1.4, d * 0.3 + 0.25):.2f});']
    return scene(cid, p, d, css, body, js)


def mg_logos(cid: str, p: str, d: float, a: dict, logo_files: dict[str, str]) -> str:
    tools = [t for t in a.get("tools", []) if t in logo_files][:4]
    n = max(1, len(tools))
    gap, card = 80, 260
    x0 = (W - (n * card + (n - 1) * gap)) / 2
    css = f"""
    #{p}-t {{ top: 150px; font-family: 'Montserrat VN'; font-weight: 900; font-size: 76px; text-transform: uppercase; }}
    .{p}-card {{ position: absolute; top: 330px; width: {card}px; display: flex; flex-direction: column; align-items: center; gap: 26px; }}
    .{p}-box {{ width: {card}px; height: {card}px; border-radius: 56px; background: #fff; display: flex; align-items: center;
      justify-content: center; box-shadow: 0 30px 80px rgba(0,0,0,.5); }}
    .{p}-box img {{ width: 160px; height: 160px; object-fit: contain; }}
    .{p}-name {{ font-family: 'Montserrat VN'; font-weight: 800; font-size: 44px; color: {INK}; }}"""
    body = [f'      <div class="{p}-c" id="{p}-t">{esc(a.get("title", ""))}</div>']
    js = [f'    tl.fromTo("#{p}-t", {{ opacity: 0, y: -30 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }}, 0.35);']
    for i, t in enumerate(tools):
        body.append(f'      <div class="{p}-card" id="{p}-g{i}" style="left:{x0 + i * (card + gap):.0f}px"><div class="{p}-box">'
                    f'<img src="{logo_files[t]}" alt="{esc(t)}"></div><div class="{p}-name">{esc(t)}</div></div>')
        js.append(f'    tl.fromTo("#{p}-g{i}", {{ opacity: 0, scale: 0.4, y: 60 }}, {{ opacity: 1, scale: 1, y: 0, duration: 0.55, ease: "back.out(1.7)" }}, {0.6 + i * 0.25:.2f});')
    return scene(cid, p, d, css, "\n".join(body), js)


def mg_scene(cid: str, p: str, e: dict, logo_files: dict[str, str]) -> str:
    a, d = e["params"], e["params"]["dur"]
    kind = a.get("template", "title")
    if kind == "stat":
        return mg_stat(cid, p, d, a)
    if kind == "list":
        return mg_list(cid, p, d, a)
    if kind == "compare":
        return mg_compare(cid, p, d, a)
    if kind == "logos" and any(t in logo_files for t in a.get("tools", [])):
        return mg_logos(cid, p, d, a, logo_files)
    return mg_title(cid, p, d, a)

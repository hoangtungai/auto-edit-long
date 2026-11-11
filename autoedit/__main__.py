"""CLI: python -m autoedit <cut|plan|compose|render|all> input/video.mp4"""
from __future__ import annotations

import argparse
from pathlib import Path

from .common import ROOT, log, workdir


def step_cut(video: Path, apply: bool) -> None:
    from .cut import apply_cuts, make_cut_list
    from .transcribe import transcribe
    wd = workdir(video)
    if not apply:
        transcribe(video, wd / "transcript_raw.json", wd / "audio_raw.wav")
        p = make_cut_list(video, wd)
        log(f"DỪNG: mở {p} để duyệt. Duyệt xong chạy: python -m autoedit cut --apply {video}")
        return
    if not (wd / "cut_list.json").exists():
        raise SystemExit("Chưa có cut_list.json - chạy 'cut' trước (không có --apply).")
    cut = apply_cuts(video, wd)
    transcribe(cut, wd / "transcript.json", wd / "audio_cut.wav")  # transcribe lại sau khi cắt


def step_plan(video: Path) -> None:
    from .plan import make_plan
    make_plan(workdir(video))


def step_compose(video: Path) -> None:
    from .compose import compose
    compose(workdir(video))


def step_render(video: Path, out_dir: Path) -> None:
    from .render import render_and_check
    render_and_check(video, workdir(video), out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(prog="autoedit", description="Tự động edit video dài 16:9 tiếng Việt")
    ap.add_argument("step", choices=["cut", "plan", "compose", "render", "all"])
    ap.add_argument("video", type=Path)
    ap.add_argument("--apply", action="store_true", help="cut: cắt theo cut_list.json đã duyệt")
    ap.add_argument("--yes", action="store_true", help="all: bỏ qua bước dừng duyệt cut_list")
    ap.add_argument("--out", type=Path, default=ROOT / "output", help="thư mục xuất video")
    a = ap.parse_args()
    video = a.video.resolve()
    if a.step == "cut":
        step_cut(video, a.apply)
    elif a.step == "plan":
        step_plan(video)
    elif a.step == "compose":
        step_compose(video)
    elif a.step == "render":
        step_render(video, a.out)
    else:
        wd = workdir(video)
        if not (wd / "cut.mp4").exists():
            if not (wd / "cut_list.json").exists():
                step_cut(video, apply=False)
                if not a.yes:
                    return
            step_cut(video, apply=True)
        step_plan(video)
        step_compose(video)
        step_render(video, a.out)


if __name__ == "__main__":
    main()

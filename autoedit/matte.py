"""Tách người khỏi nền bằng Robust Video Matting (PeterL1n/RobustVideoMatting, mobilenetv3).

Ra 2 file:
- person.webm : người + kênh alpha (VP9 yuva420p) để đặt chữ nằm sau lưng người
- matte.mp4   : mặt nạ trắng/đen (dùng để tự kiểm tra caption/chữ bị che)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .common import FPS, H, W, log


def run_matting(src: Path, wd: Path, downsample: float = 0.25) -> tuple[Path, Path]:
    import torch

    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    log(f"Robust Video Matting trên {dev} ...")
    model = torch.hub.load("PeterL1n/RobustVideoMatting", "mobilenetv3", trust_repo=True).eval().to(dev)

    person, matte = wd / "person.webm", wd / "matte.mp4"
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                            "-b:v", "6M", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1",
                            "-g", str(FPS), "-auto-alt-ref", "0", str(person)], stdin=subprocess.PIPE)
    menc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                             str(matte)], stdin=subprocess.PIPE)
    rec = [None] * 4
    n, size = 0, W * H * 3
    with torch.no_grad():
        while True:
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            rgb = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            x = torch.from_numpy(rgb.copy()).to(dev).permute(2, 0, 1)[None].float() / 255
            fgr, pha, *rec = model(x, *rec, downsample_ratio=downsample)
            a = (pha[0, 0].clamp(0, 1) * 255).byte().cpu().numpy()
            enc.stdin.write(np.dstack([rgb, a]).tobytes())
            menc.stdin.write(a.tobytes())
            n += 1
            if n % 150 == 0:
                log(f"  matting {n} khung hình")
    for p in (enc, menc):
        p.stdin.close(); p.wait()
    dec.wait()
    log(f"Matting xong {n} khung -> {person.name}, {matte.name}")
    return person, matte

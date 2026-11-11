# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này.

## Dự án

`auto-edit-long` là pipeline tự động edit video dài 16:9 tiếng Việt (talking head) của **Hoang Tung AI** (kênh Hoàng Tùng AI). Tác giả có 15 năm kinh nghiệm IT phần mềm và Vibe Coding công cụ này bằng Claude Code để edit toàn bộ nội dung kênh. Trao đổi với người dùng bằng tiếng Việt.

## Lệnh

```bash
.venv/bin/python -m autoedit cut input/<video>.mp4          # transcribe + cut_list.json, dừng để duyệt
.venv/bin/python -m autoedit cut --apply input/<video>.mp4  # cắt theo cut_list đã duyệt
.venv/bin/python -m autoedit plan input/<video>.mp4         # Claude làm đạo diễn -> edit_plan.json
.venv/bin/python -m autoedit compose input/<video>.mp4      # RVM + project HyperFrames
.venv/bin/python -m autoedit render input/<video>.mp4       # render + -14 LUFS + tự kiểm tra -> output/
.venv/bin/python -m autoedit all input/<video>.mp4 [--yes]
```

Chạy HyperFrames bằng `node_modules/.bin/hyperframes` với `npm_config_cache="$PWD/.npm-cache"` (npm cache toàn máy bị lỗi quyền).

## Cấu trúc

- `autoedit/transcribe.py`: mlx-whisper (timestamp từng từ) + `glossary.json`
- `autoedit/cut.py`: từ đệm, câu nói lại > 70%, khoảng lặng → `cut_list.json`; cắt bằng FFmpeg (đệm 0.15s, fade 30ms)
- `autoedit/plan.py`: prompt đạo diễn (`claude -p`) và kiểm luật (MG 20-30%, zoom chậm, nhịp ≤ 3s)
- `autoedit/matte.py`: Robust Video Matting → `person.webm` (alpha) + `matte.mp4`
- `autoedit/layout.py`: bố trí head text hai bên đầu theo mặt nạ người và mức zoom
- `autoedit/compose.py`: sinh project HyperFrames (nền, head text, người, logo, MG, phụ đề)
- `autoedit/mg.py`: mẫu motion graphics toàn khung (title, stat, list, compare, logos)
- `autoedit/render.py`: render, loudnorm, tự kiểm tra và tự sửa, báo cáo

## Quy ước

- Video đầu vào ở `input/`, video xuất ra ở `output/`, file trung gian ở `work/<tên>/`. Cả ba không commit.
- Logo chỉ dùng bản chính thức trong `media/logos/` (thiếu thì tải qua `hyperframes media-use resolve --type logo`), không tự vẽ.
- Font phải đủ dấu tiếng Việt; kiểm tra glyph bằng fontTools trước khi thêm font mới.
- Không commit media riêng của người dùng (`media/*.mp4`, `media/*.png`).
- Sau khi đổi giao diện: `compose`, rồi `hyperframes snapshot` để xem khung hình trước khi render.

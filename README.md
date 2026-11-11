# auto-edit-long

Tự động edit video dài 16:9 tiếng Việt (talking head): cắt take hỏng → Claude làm đạo diễn → dựng hình bằng HyperFrames → render và tự kiểm tra.

Dự án của **Hoang Tung AI** (kênh Hoàng Tùng AI). Ứng dụng được Vibe Coding hoàn toàn bằng Claude Code. Chỉ tốn token một lần để tạo ra công cụ, sau đó dùng lâu dài cho mọi video, thay vì lần edit nào cũng tốn token điều khiển phần mềm bên thứ ba.

## Cài đặt (macOS, Apple Silicon)

```bash
brew install ffmpeg node
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm_config_cache="$PWD/.npm-cache" npm install
```

- Whisper: `mlx-community/whisper-large-v3-turbo` (tự tải lần đầu, có timestamp từng từ). Đổi model: `AUTOEDIT_WHISPER_MODEL=...`
- Robust Video Matting: tự tải từ `PeterL1n/RobustVideoMatting` qua `torch.hub` ở lần chạy đầu.
- Đạo diễn: dùng lệnh `claude` (Claude Code) chạy headless. Không có lệnh này (hoặc đặt `AUTOEDIT_NO_CLAUDE=1`) thì chương trình dùng bộ luật đơn giản.

## Chạy

```bash
# Bước 1: transcribe + đánh dấu chỗ cắt -> work/<tên>/cut_list.json (DỪNG để duyệt)
.venv/bin/python -m autoedit cut input/intro.mp4
# duyệt xong:
.venv/bin/python -m autoedit cut --apply input/intro.mp4

# Bước 2: đạo diễn -> work/<tên>/edit_plan.json
.venv/bin/python -m autoedit plan input/intro.mp4

# Bước 3: tách nền RVM + dựng project HyperFrames -> work/<tên>/hf/
.venv/bin/python -m autoedit compose input/intro.mp4

# Bước 4: render + chuẩn hoá -14 LUFS + tự kiểm tra -> output/<tên>_edited.mp4
.venv/bin/python -m autoedit render input/intro.mp4

# Chạy cả 4 bước (vẫn dừng ở bước duyệt cut_list; thêm --yes để bỏ qua)
.venv/bin/python -m autoedit all input/intro.mp4
```

Muốn chỉnh tay trước khi render: sửa `edit_plan.json` rồi chạy lại `compose` + `render`. Hoặc mở project trong HyperFrames:
`npx hyperframes preview work/<tên>/hf`.

## File cấu hình

| File | Dùng để |
| --- | --- |
| `glossary.json` | Sửa từ Whisper hay nghe sai ("Cloud Code" → "Claude Code", "CupCut" → "CapCut") |
| `tools.json` | Công cụ có logo: tên, cách gọi, tên tra logo chính thức |
| `media/logos/` | Logo chính thức (thiếu thì tự tải qua `hyperframes media-use` từ theSVG / GitHub / favicon, không tự vẽ) |
| `media/fonts/` | Barlow Condensed (phụ đề, từ nhấn), Montserrat (head text, motion graphics), Be Vietnam Pro. Cả ba đều đủ dấu tiếng Việt, giấy phép OFL |
| `media/backgrounds/` | Ảnh nền studio (Unsplash License, ghi công trong `CREDITS.md`) |
| `media/sfx/` | Âm thanh pop/whoosh (Pixabay License) |

## Từng bước làm gì

1. **Cắt**: FFmpeg tách audio → Whisper ra từng từ + timestamp → sửa theo glossary → đánh dấu từ đệm (ừm, à, ờ...), câu nói lại giống > 70% (giữ take sau), cụm từ lặp liền nhau, khoảng lặng > 0.6s → `cut_list.json`. Khi cắt: chừa đệm 0.15s, fade âm 30ms, điểm cắt dời về chỗ im nhất để không cụt chữ, rồi transcribe lại.
2. **Đạo diễn**: Claude đọc transcript, ra `edit_plan.json` (mỗi dòng `{t, type, params}`: headtext / logo / zoom / mg). Sau đó chương trình kiểm luật: logo phải đúng lúc công cụ được nhắc; không chồng chéo; motion graphics toàn khung chiếm 20-30% thời lượng; zoom chậm và nhẹ (1.6-2.8s, tối đa 1.15x); nhịp tối đa 3s có một thay đổi hình ảnh.
3. **Dựng**: RVM tách người (`person.webm` có alpha + `matte.mp4`), thay bằng nền studio sáng. Head text (Montserrat, gradient trắng, từ nhấn xanh lá) nằm sau lưng người, tự bố trí hai bên đầu dựa trên mặt nạ người và mức zoom tại thời điểm đó. Logo bật ra đúng lúc nhắc tới. Motion graphics toàn khung có 5 mẫu: tiêu đề, con số, danh sách, so sánh, logo. Phụ đề Barlow Condensed nhóm 3 từ, tô vàng từ đang nói.
4. **Render**: HyperFrames render → FFmpeg loudnorm 2 lượt (-14 LUFS), H.264 + AAC 1920x1080. Tự kiểm tra thông số, độ to, khung hình và âm thanh ở từng điểm cắt, chữ bị cụt, caption tràn khung hoặc bị logo che, head text bị người che. Lỗi thì tự sửa và render lại (tối đa 2 vòng). Báo cáo ghi ra `output/<tên>_edited.report.md`.

## Về Hoang Tung AI

- **Hoang Tung AI** (kênh YouTube Hoàng Tùng AI) chia sẻ cách dùng AI, Claude Code và Vibe Coding để tự động hoá công việc, đặc biệt là sản xuất và edit video.
- Tác giả có 15 năm kinh nghiệm trong lĩnh vực IT phần mềm, tự Vibe Coding công cụ này để edit toàn bộ nội dung trên kênh.
- GitHub: [github.com/hoangtungai](https://github.com/hoangtungai)

Bạn có thể dùng repo này làm điểm xuất phát rồi Vibe Coding tiếp theo phong cách riêng của mình: đổi font, màu, mẫu motion graphics, hoặc luật đạo diễn trong `autoedit/plan.py`.

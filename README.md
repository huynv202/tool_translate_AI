# Viet Transform Studio

Web studio bien video **ma ban co quyen su dung** thanh video review tieng Viet: lay nguon, nhan
dang loi thoai Trung, viet lai kich ban, tao voice-over, phu de va render bang FFmpeg.
Thay doi hinh/nhac khong tu dong tao ra quyen su dung; hay dam bao giay phep nguon, nhac va tuan thu
chinh sach YouTube truoc khi dang.

## Cai dat

Yeu cau Python 3.11+, FFmpeg co `libass`, va mot 9Router endpoint tuong thich OpenAI API.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
mkdir -p music output work
```

## Chay giao dien web

```bash
source .venv/bin/activate
viet-transform-web
```

Mo `http://127.0.0.1:8000`, bam **9ROUTER CONFIG** va dien API key, Base URL, text model, sau do
chon kich thuoc Whisper local. Tool khong can API key truc tiep cua OpenAI/Gemini. Lan dau su dung,
`faster-whisper` se tai model STT ve may va cac lan sau se dung cache local.
API key chi nam trong session cua trinh duyet va bo nho job, khong duoc ghi vao artifact.

Tren giao dien ban co the upload video/dan URL, chon khung Shorts hoac Long-form, zoom/crop, trim,
lat hinh, giong doc, toc do, font phu de, nhac nen va theo doi truc tiep 7 cong doan xu ly. Khi hoan
tat, video co the xem va tai ngay tren trang.

File lon duoc upload theo chunk 8 MB, moi chunk tu retry khi ket noi chap chon va server chi tao job
sau khi da ghep, kiem tra dung kich thuoc file. Truoc khi upload, studio kiem tra dung luong trong
cho source, artifact trung gian va video render; video 2 GB nen co toi thieu khoang 8 GB trong.

Co the chon toi da 10 video trong mot lan. Studio xu ly tuan tu tung video, retry job loi toi da 5
lan va dung hang doi tai video van loi. Tren Chrome/Edge, chon **Thu muc ban nhap** de moi video da
hoan tat duoc stream thang ve may truoc khi studio chay video ke tiep; ket qua tren server van duoc
giu lai trong `work/web-jobs`.

Studio ho tro upload logo PNG/WebP/JPEG, chon vi tri, kich thuoc va do trong suot. Am thanh duoc
chuan hoa loudness va tu dong ha nhac nen khi voice-over vang len. Sau khi render, khu hau ky cho
phep sua kich ban va tao lai voice, subtitle, video ma khong phai chay lai download/STT.

Che do mac dinh la dich long tieng theo tung segment hoi thoai: Whisper giu timestamp tieng Trung,
AI dich ngan gon tung cau, TTS duoc co toc do va dat vao dung slot, subtitle sinh truc tiep tu ban
dich. Moi dong trong editor tuong ung mot segment, vi vay can giu nguyen so dong khi sua noi dung.

Neu video co subtitle track dang text (SRT/ASS/WebVTT/mov_text), studio se trich xuat track nay truoc
va giu nguyen moc `from -> to`. Neu subtitle da burn vao hinh hoac khong co track, studio fallback
sang Whisper de tao cue. Tren UI, chon model Gemini da auth trong 9Router va ngôn ngu dich dich;
voice Edge TTS se duoc loc theo ngôn ngu do.

AI duoc tach thanh hai vai tro: Gemini dich subtitle tho theo tung cue; GPT bien tap ban dich thanh
loi thoai tu nhien va co the them chat hai nhe, nhung bat buoc giu nguyen ID, thu tu, y nghia va
duration. Voi OAuth 9Router, uu tien `gc/` hoac `ag/` cho Gemini va `cx/` hoac `gh/` cho GPT.

Khu hau ky dung layout editor: preview trung tam, toolbar tab, inspector ben phai va timeline o duoi.
Cue subtitle nam dung theo ty le timestamp; bam cue de seek video va chon dong ban dich. Tab Subtitle,
Brand va Audio co the render lai style/logo/nhac ma khong chay lai download, STT, Gemini hay TTS.

Voi video dai, TTS khong goi Edge theo tung cue. Cac cue lien tiep duoc gom thanh block toi da 25
giay/650 ky tu. Che do `auto` dung Edge cho clip ngan va Piper local cho job tieng Viet co tren 8
block. Piper voice model duoc cache tai `work/models/piper`, khong bi rate-limit va chay offline sau
lan tai dau. Moi block co cache rieng; nut retry tiep tuc tu block dang do thay vi lam lai tu dau.
UI co nut nghe thu giọng. `Van Anh`, `Minh Chau` va `Hai Nam` la cac voice Piper local phu hop video
dai; `Hoai My` va `Nam Minh` la Edge online tu nhien hon nhung co nguy co rate-limit.

Che do mac dinh `Tu dong chat luong cao` uu tien XTTS v2 tren NVIDIA GPU, ho tro clone giong tu file
mau sach 10-30 giay va tu fallback Piper neu XTTS/model/GPU gap loi. Cai tuy chon XTTS bang
`pip install -e ".[xtts]"`; model XTTS duoc tai va cache o lan chay dau. May CPU-only mac dinh dung
Piper de tranh xu ly qua cham; co the dat `XTTS_ALLOW_CPU=1` neu van muon chay XTTS bang CPU. XTTS
chi duoc bat khi nguoi dung da doc dieu khoan Coqui va tu dat `COQUI_TOS_AGREED=1`; can kiem tra
giay phep model/voice truoc khi dung cho noi dung thuong mai hoac YouTube co kiem tien.

## Chay bang CLI (tuy chon)

Neu muon dung CLI, dien `9ROUTER_API_KEY`, `9ROUTER_BASE_URL` va model trong `.env`, sau do:

```bash
viet-transform ./input.mp4 -o output/final.mp4 --work-dir work/job-01
viet-transform 'https://example.com/video' -o output/final.mp4 --seed 42
```

Moi cong viec nen co `--work-dir` rieng. Pipeline giu lai tung artifact va tu bo qua cac buoc da
hoan thanh. Dung `--no-resume` de chay lai toan bo, `--music track.mp3` de chon nhac, `--no-flip`
de giu huong hinh, hoac `-v` de xem lenh chi tiet.

Artifacts gom `source.mp4`, `source.wav`, `dialogue.source.json`, `dialogue.translated.json`,
`script.translated.txt`, `voiceover.mp3` va `voiceover.srt`. Ban co the sua ban dich trong khu hau ky
va tao lai voice/subtitle/video ma khong chay lai cac buoc lay nguon.

## Gioi han hien tai

- Downloader chi su dung `yt-dlp`; khong tich hop dich vu ben thu ba de vuot watermark/bao ve.
- Khung 9:16 dung scale/crop trung tam. Video co chu the lech tam nen duoc can chinh thu cong.
- Voice-over dai hon video se bi cat theo video. Hay rut gon kich ban hoac dung video dai hon.
- 9Router chi can route duoc Chat Completions. STT tieng Trung va phu de tieng Viet chay local;
  model `medium` chinh xac hon nhung cham va ton RAM hon `small`/`base`.

## Kiem tra

```bash
pytest -q
ruff check src tests
viet-transform --help
```

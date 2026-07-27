# Viet Transform Studio - Production Roadmap

## Muc tieu

Thu tu uu tien bat buoc:

1. Dung timeline va khong mat ket qua khi loi.
2. Khong goi lai AI/TTS cho du lieu khong thay doi.
3. Tao ban preview nhanh truoc khi render master.
4. Mo rong editor sau khi pipeline da co resume va cache chac chan.

## Giai doan 1 - Nen tang on dinh

- Luu manifest cho moi job, fingerprint dau vao va trang thai tung stage.
- Khoi phuc job sau khi server restart ma khong luu API key.
- Ghi log FFmpeg day du vao tung thu muc job.
- Kiem tra dung luong dia truoc STT, TTS va render.
- Gioi han va don dep artifact tam theo chinh sach retention.

Tieu chi dat: restart server khong lam mat job; retry chi chay lai stage loi.

## Giai doan 2 - Timeline chinh xac

- Uu tien subtitle text nhung trong video.
- Neu khong co, chia STT theo khoang lang quanh 20 giay va cong offset tuyet doi.
- Luu confidence cua tung cue va danh dau cue can nguoi dung kiem tra.
- Them waveform/proxy audio de can chinh cue trong editor.
- Sau cung moi nghien cuu OCR subtitle chay tren hinh cho video co hard-sub.

Tieu chi dat: sai lech khong tang theo do dai video; cue cuoi van khop trong sai so cho phep.

## Giai doan 3 - Giam token AI

- Cache tung batch theo hash cua model, prompt va payload.
- Khong gui source goc sang model bien tap khi da co ban dich du thong tin.
- Them che do Economy mot luot: mot model vua dich vua viet lai.
- Che do Quality hai luot chi dung khi nguoi dung chon.
- Chi goi lai AI cho cue da sua hoac batch bi vo hieu hoa.
- Ghi usage token cua tung request de co bao cao chi phi/job.

Tieu chi dat: retry khong phat sinh token cho batch da thanh cong; Economy giam gan mot nua so request.

## Giai doan 4 - Preview nhanh

- Tao proxy 540x960 de preview editor.
- Render tung doan thay doi thay vi render lai ca video.
- Ghep cac segment da cache bang concat khi xuat master.
- Dung hardware encoder NVENC/QSV/AMF khi may ho tro.
- Cau hinh CPU mac dinh: libx264 veryfast, CRF 23, AAC 128k.

Tieu chi dat: thay mot cue co preview trong vai giay; master khong encode lai segment khong doi.

## Giai doan 5 - Editor CapCut don gian

- Multi-track video, voice, music, subtitle va overlay.
- Split, trim, ripple delete, freeze/extend, transition co gioi han.
- Voice rieng tung cue va waveform snapping.
- Undo/redo va autosave project JSON.
- Export preset 720p nhanh, 1080p master va social 9:16.

Tieu chi dat: moi thao tac editor la mot thay doi project JSON co the undo va render lai co chon loc.

## Chi so can do

- Thoi gian tung stage va tong thoi gian/job.
- So request, input/output token va cache hit cua AI.
- So clip TTS tao moi va tai su dung.
- Real-time factor cua STT, TTS va render.
- Dung luong artifact tam, proxy va file master.
- Sai lech timestamp tai 25%, 50%, 75% va cuoi video.

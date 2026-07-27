# Cai dat va chay tren Windows

## 1. Yeu cau

- Windows 10/11 64-bit.
- Python 3.11 hoac 3.12. Khuyen dung Python 3.11 neu muon cai XTTS v2.
- FFmpeg co filter `subtitles`/`libass`.
- 9Router dang chay va da auth tai khoan Gemini/GPT.
- Toi thieu 8 GB RAM. Video dai nen co 16-32 GB RAM va 30 GB o dia trong.

## 2. Cai Python va FFmpeg

Mo PowerShell bang quyen nguoi dung binh thuong:

```powershell
winget install --id Python.Python.3.11 -e
winget install --id Gyan.FFmpeg -e
```

Dong PowerShell, mo lai va kiem tra:

```powershell
py -3.11 --version
ffmpeg -version
ffmpeg -filters | Select-String subtitles
```

Neu khong thay filter `subtitles`, hay cai ban FFmpeg full build va them thu muc `bin` vao PATH.

## 3. Cai tool tu dong

Giai nen source vao mot duong dan ngan, khong dau, vi du:

```text
D:\VietTransformStudio
```

Mo PowerShell tai thu muc project:

```powershell
cd D:\VietTransformStudio
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows.ps1
```

Script se tao `.venv`, cai dependencies va tao cac thu muc `music`, `output`, `work`.

Neu may co NVIDIA GPU va muon cai XTTS v2:

```powershell
.\setup-windows.ps1 -WithXTTS
```

XTTS co dieu khoan model rieng. Chi sau khi da doc va chap thuan, dat bien moi truong:

```powershell
[Environment]::SetEnvironmentVariable("COQUI_TOS_AGREED", "1", "User")
```

Dong terminal va mo lai sau khi dat bien moi truong.

## 4. Chay giao dien

Double-click file:

```text
run-windows.bat
```

Hoac chay trong PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
viet-transform-web
```

Mo trinh duyet tai:

```text
http://127.0.0.1:8000
```

Khong dong cua so terminal trong khi dang render.

## 5. Cau hinh 9Router

Trong giao dien, bam `9ROUTER CONFIG`:

1. Dien API key cua 9Router.
2. Base URL thuong la `http://localhost:20128/v1`.
3. Bam tai danh sach model.
4. Chon route Gemini da auth (`gc/...` hoac `ag/...`) de dich.
5. Chon route GPT da auth (`cx/...` hoac `gh/...`) de bien tap loi thoai.
6. Test ca hai model va luu.

Tool khong can API key Gemini/OpenAI truc tiep.

## 6. Chon giọng doc

- `Tu dong - XTTS -> Piper`: lua chon mac dinh.
- Co NVIDIA GPU, XTTS da cai va da chap thuan license: dung XTTS.
- Khong co XTTS/GPU hoac XTTS loi: tu dong fallback Piper.
- Co the upload mau giong sach 10-30 giay de clone bang XTTS.
- Piper phu hop video dai, khong gioi han so phut va khong can API.

Kiem tra NVIDIA GPU:

```powershell
nvidia-smi
```

## 7. Render nhieu video

Trong hop chon file, giu `Ctrl` hoac `Shift` de chon toi da 10 video. Tool se:

1. Upload tung video theo chunk.
2. Render lan luot, khong chay dong thoi.
3. Retry video loi toi da 5 lan.
4. Dung hang doi tai video van loi.
5. Giu cac video da hoan thanh trong `work\web-jobs`.

Tren Chrome/Edge, bam `CHON THU MUC BAN NHAP` de tu dong luu ket qua ve may.

## 8. Cap nhat source

Sau khi source thay doi, chay lai:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows.ps1
```

Script su dung lai `.venv` hien co va cap nhat package.

## 9. Loi thuong gap

### PowerShell chan script

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### Khong tim thay FFmpeg

Dong terminal, mo lai va chay:

```powershell
where.exe ffmpeg
ffmpeg -version
```

### Port 8000 dang duoc su dung

```powershell
Get-NetTCPConnection -LocalPort 8000
```

Dong phien tool cu truoc khi chay lai.

### XTTS khong chay

Tool se fallback Piper. Kiem tra:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```

Neu tra ve `False`, XTTS se khong dung GPU.

### Video dai

- Khong de may sleep trong luc render.
- Dung Piper neu can do on dinh cao.
- Video 2 GB nen co toi thieu 8 GB trong.
- Video nhieu gio nen co 30 GB trong tro len.

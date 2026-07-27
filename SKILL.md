Bạn là một Kỹ sư phần mềm Senior chuyên về Automation, Processing Video (FFmpeg/OpenCV), và AI Integration.
Hãy lập trình một công cụ (Tool Script bằng Python) tự động hóa quy trình biến một video phim ngắn Trung Quốc thành video Shorts/Long-form chuẩn chính sách "Transformative Content" của YouTube.

### NGUYÊN LÝ HOẠT ĐỘNG (INPUT -> OUTPUT):
- INPUT: 01 đường link video/file video gốc (.mp4) từ Douyin/Kuaishou.
- OUTPUT: 01 video hoàn chỉnh (.mp4) đã qua chỉnh sửa, có giọng đọc Voiceover tiếng Việt, nhạc nền mới, phụ đề tự động và hiệu ứng tránh bản quyền.

### CÁC MÔ-ĐUN KỸ THUẬT CẦN THIẾT CỦA TOOL:

1. MÔ-ĐUN 1: TẢI & LÀM SẠCH WATERMARK (Download & Watermark Removal)
   - Tự động tải video gốc không dán watermark bằng API/Library (ví dụ: yt-dlp hoặc tích hợp API SnapTik/Douyin).
   - Nếu video vẫn còn logo góc: Sử dụng OpenCV hoặc FFmpeg áp dụng mặt nạ (blur mask) hoặc tự động Crop viền nhẹ để che/xóa hẳn logo.

2. MÔ-ĐUN 2: TRÍCH XUẤT NỘI DUNG & TẠO KỊCH BẢN (STT & AI Scriptwriting)
   - Trích xuất âm thanh từ video gốc -> Dùng Whisper (OpenAI Whisper API) để chuyển thoại tiếng Trung thành văn bản (Speech-to-Text).
   - Gửi bản dịch/tóm tắt tiếng Trung qua Gemini/GPT API với System Prompt: "Hãy tóm tắt và viết lại nội dung này thành kịch bản Voiceover review kịch tính bằng Tiếng Việt (130-150 từ, dạng Shorts), có câu Hook 3 giây đầu và CTA kết bài."
   - Chế độ mặc định phải dịch theo từng câu thoại nhân vật và giữ timestamp nguồn; không tóm tắt
     thành review. Có thể thêm sắc thái hài hước ngắn nhưng không thay đổi tình tiết.
   - TTS được tạo theo từng segment, co tốc độ vừa slot thời gian và đặt lại đúng timeline gốc.
   - Phụ đề Việt sinh trực tiếp từ bản dịch có timestamp, không STT lại toàn bộ voice-over.

3. MÔ-ĐUN 3: TẠO GIỌNG ĐỌC AI (Text-to-Speech - TTS)
   - Chuyển kịch bản Tiếng Việt thành file âm thanh (.mp3) bằng API (ElevenLabs / Edge-TTS / CapCut TTS).
   - Tăng tốc độ file âm thanh TTS lên 1.05x - 1.1x để tạo nhịp điệu dồn dập.

4. MÔ-ĐUN 4: XỬ LÝ VIDEO & ÂM THANH (FFmpeg Core - Anti-Copyright)
   - Mute (tắt) 100% audio gốc của video.
   - Crop khung hình về chuẩn 9:16 (Phóng to 5-10% để xóa viền và thay đổi góc quay).
   - Cắt bỏ 0.5 giây đầu và 0.5 giây cuối của video gốc để thay đổi timeline.
   - Thực hiện Lật ngược video (Flip Horizontal).
   - Ghép file Voiceover (Âm lượng 100%) + Nhạc nền lấy ngẫu nhiên từ kho nhạc miễn phí local (Âm lượng 12%).

5. MÔ-ĐUN 5: CHÈN PHỤ ĐỀ TỰ ĐỘNG (Auto-Subtitles)
   - Sử dụng Whisper để tạo file phụ đề (.srt) từ file Voiceover tiếng Việt.
   - Burn (chèn) phụ đề trực tiếp vào video bằng FFmpeg với style: Chữ màu vàng/trắng, viền đen, font chữ đậm dễ đọc (như Montserrat/Impact).

### MÔ-ĐUN 6: WEB APP & TRẢI NGHIỆM SỬ DỤNG
   - Sản phẩm chính là web app responsive, không yêu cầu người dùng thao tác bằng CLI.
   - Có khu vực upload video hoặc nhập URL, cấu hình kết nối 9Router, chọn model text/Whisper.
   - Có bảng điều khiển chất lượng: tỷ lệ khung hình, độ phân giải, crop/zoom, lật hình,
     cắt timeline, âm lượng nhạc, giọng đọc, tốc độ TTS và font phụ đề.
   - Hiển thị trạng thái từng công đoạn theo thời gian thực, lỗi dễ hiểu, kịch bản/transcript,
     video preview và nút tải kết quả.
   - API key chỉ tồn tại trong bộ nhớ của job, không ghi vào artifact hoặc trả về trình duyệt.

Hãy viết mã nguồn Python hoàn chỉnh, module hóa rõ ràng, có xử lý lỗi (Error Handling), web UI/UX
chất lượng sản phẩm và hướng dẫn thiết lập/chạy ứng dụng. Kết nối AI thông qua 9Router tương thích
OpenAI API; người dùng chỉ cung cấp API key 9Router.

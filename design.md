# Hệ thống thiết kế Viet Transform Studio

## 1. Mục tiêu

Viet Transform Studio phải mang cảm giác của một bàn dựng video dễ sử dụng, không phải bảng điều
khiển kỹ thuật. Người dùng luôn cần biết:

1. Mình đang ở đâu trong quy trình.
2. Có thể thực hiện hành động nào tiếp theo.
3. Thao tác hiện tại có ảnh hưởng hoặc làm mất dữ liệu hay không.

Mỗi màn hình chỉ có một hành động chính. Các tùy chọn nâng cao được nhóm theo ngữ cảnh và không
hiển thị đồng loạt.

## 2. Nguyên tắc bắt buộc

- Tạo project không tự động render video.
- Project dừng lại ngay khi video nguồn và các cue đã sẵn sàng.
- Chỉ tạo MP4 khi người dùng bấm `XUẤT VIDEO` trong editor.
- Editor luôn preview từ video nguồn và các lớp chỉnh sửa trực tiếp.
- Mỗi project chỉ nhận một video cho đến khi chế độ batch được thiết kế lại.
- Không hiển thị nút tải khi chưa có bản xuất hợp lệ.
- Không che lỗi trong log; lỗi phải có nguyên nhân và hành động khắc phục.
- Không sử dụng màu sắc làm cách duy nhất để truyền đạt trạng thái.
- Thay đổi trong editor không tự động khởi động FFmpeg.

## 3. Cấu trúc sản phẩm

Sản phẩm có ba không gian chính.

### 3.1. Tạo project

Thứ tự nội dung cố định:

1. Thanh trên cùng: logo, trạng thái hệ thống và cấu hình 9Router.
2. Tiêu đề giải thích project sẽ được đưa vào editor, chưa xuất video.
3. Nguồn video: upload hoặc URL, chỉ một video.
4. Định dạng hình ảnh: tỷ lệ, độ phân giải, crop và logo.
5. DNA biên tập: chế độ nội dung, luận điểm, góc nhìn Việt Nam và nguồn nghiên cứu.
6. Ngôn ngữ và giọng kể.
7. Thanh hành động cuối với nút `TẠO PROJECT CHỈNH SỬA`.

Các giá trị thông thường được giữ cho project tiếp theo. API key chỉ được giữ trong session.

### 3.2. Chuẩn bị project

Màn hình này chỉ hiển thị trong lúc:

- Lấy video nguồn.
- Trích xuất âm thanh.
- Nhận dạng nội dung.
- Dịch, biên tập và tạo cue.

Khi cue sẵn sàng, hệ thống tự mở editor. Tạo voice, phụ đề cuối và xuất MP4 không nằm trong giai
đoạn này.

Nếu một bước thất bại, phải giữ lại artifact của các bước đã hoàn thành. Nút thử lại cần ghi rõ bước
được chạy lại, ví dụ `THỬ LẠI BƯỚC TẠO CUE`.

### 3.3. Video Editor

Editor sử dụng cấu trúc cố định:

```text
+------------------------------------------------------------------+
| Tên project | Trạng thái | Undo/Redo | Xem trước | XUẤT VIDEO    |
+--------+--------------------------------------+-------------------+
| Tools  |            Preview canvas            | Inspector         |
+--------+--------------------------------------+-------------------+
| Timeline: V1 | PIP | CC | A1 Voice | A2 Music                    |
+------------------------------------------------------------------+
```

#### Thanh project

- Bên trái: tên project.
- Ở giữa: trạng thái preview, lưu và xuất video.
- Bên phải: xem trước và `XUẤT VIDEO`.
- Không dùng cụm từ “render lại” trong trải nghiệm người dùng.

#### Thanh công cụ

Thứ tự cố định:

1. Nội dung.
2. Phụ đề.
3. Hình ảnh và hiệu ứng.
4. PIP và lớp phủ.
5. Âm thanh.
6. Thương hiệu.
7. YouTube Readiness.
8. Xuất video.

Mỗi công cụ chỉ mở một inspector. Không hiển thị nhiều nhóm thiết lập cạnh tranh cùng lúc.

#### Preview canvas

- Luôn sử dụng video nguồn, không dùng video đã burn phụ đề làm project preview.
- Giữ đúng tỷ lệ đầu ra.
- Màu, blur, vignette và phụ đề phải cập nhật trực tiếp trong trình duyệt.
- Chỉ hiển thị một lớp phụ đề tiếng Việt ở vùng an toàn phía dưới.
- Click cue trên timeline phải đưa playhead đến đúng vị trí.
- Preview là bản mô phỏng; MP4 cuối chỉ được tạo khi xuất video.

#### Inspector

- Hiển thị tên nhóm đang chỉnh sửa.
- Thuộc tính quan trọng nằm trước, tùy chọn nâng cao được thu gọn.
- Slider luôn có giá trị số và giá trị mặc định rõ ràng.
- Thay đổi có hiệu lực ngay trên preview.
- Những thay đổi cần tạo lại voice được ghi rõ `Sẽ tạo khi xuất video`.

#### Timeline

Thứ tự track:

1. `V1`: video chính.
2. `PIP`: video, ảnh chèn và lớp phủ.
3. `CC`: cue phụ đề.
4. `A1`: voice theo cue.
5. `A2`: nhạc nền.

Cue được chọn phải nổi bật bằng cả màu nền và đường viền. Track trống vẫn giữ vị trí để người dùng
hiểu cấu trúc project.

## 4. Luồng thao tác chuẩn

```text
Chọn một video
    → Nhập luận điểm và nguồn nghiên cứu
    → Tạo project
    → Nhận dạng và tạo cue
    → Mở editor
    → Chỉnh nội dung, màu, hiệu ứng, PIP và âm thanh
    → Kiểm tra YouTube Readiness
    → Xuất video
    → Xem lại và tải MP4
```

Sau khi xuất, người dùng vẫn ở editor và tiếp tục làm việc trên video nguồn. Bản xuất cũ chỉ được
thay thế khi bản mới hoàn thành thành công.

## 5. Định hướng thị giác

Phong cách là `editorial production desk`: chắc chắn, có cá tính và tập trung vào nội dung. Tránh
giao diện dashboard doanh nghiệp, gradient tím và các card bo tròn quá mức.

### Màu sắc

```css
:root {
  --paper: #f2f0e8;
  --panel: #fbfaf5;
  --ink: #171713;
  --muted: #6f706b;
  --line: #cbc9bf;
  --canvas: #202225;
  --accent: #ff5a36;
  --accent-soft: #ffd7cd;
  --ready: #5e9d36;
  --working: #e7b52c;
  --danger: #c9362b;
  --focus: #1677d2;
}
```

- Màu nhấn chỉ dành cho hành động chính, playhead và cue đang chọn.
- Xanh lá biểu thị hoàn thành hoặc đã lưu.
- Đỏ chỉ dùng cho lỗi, blocker hoặc thao tác nguy hiểm.

### Typography

- Giao diện: `Be Vietnam Pro`.
- Thời gian và metadata: `IBM Plex Mono`.
- Tiêu đề trang: 40–64 px trên desktop, 32–40 px trên mobile.
- Nội dung: 14–16 px, line-height tối thiểu 1.5.
- Metadata không nhỏ hơn 11 px.

### Khoảng cách

Sử dụng hệ spacing: `4, 8, 12, 16, 24, 32, 48, 64` px.

- Nút chính cao tối thiểu 48 px.
- Vùng bấm trên mobile tối thiểu 44 × 44 px.
- Panel có padding 24–32 px trên desktop và 16–20 px trên mobile.
- Border radius trong khoảng 4–8 px.

## 6. Phân cấp hành động

- Primary: màu nhấn, chỉ có một nút chính trong mỗi khu vực.
- Secondary: nền trong, viền đậm.
- Tertiary: text button cho thao tác nhẹ.
- Danger: màu đỏ và chỉ xuất hiện trong ngữ cảnh nguy hiểm.

Nhãn nút bắt đầu bằng động từ và mô tả kết quả rõ ràng:

- Tốt: `TẠO PROJECT`, `KIỂM TRA PROJECT`, `XUẤT VIDEO`.
- Không tốt: `OK`, `ÁP DỤNG`, `TIẾP TỤC` khi thiếu ngữ cảnh.

## 7. Trạng thái hệ thống

### Preview đã thay đổi

Hiển thị: `Preview đã cập nhật · cần xuất để tạo MP4`.

### Đang xuất video

Editor vẫn hiển thị preview. Nút xuất bị khóa và hiển thị phần trăm. Người dùng không bị chuyển sang
một màn hình chờ trống.

### Xuất thành công

- Giữ video nguồn trong preview editor.
- Bật nút tải bản MP4 mới.
- Hiển thị thông tin độ phân giải, thời lượng và kích thước file khi có dữ liệu.

### Lỗi

Thông báo lỗi gồm:

1. Tiêu đề dễ hiểu.
2. Nguyên nhân ngắn gọn.
3. Một hành động khắc phục cụ thể.

Chi tiết kỹ thuật nằm trong `Xem chi tiết lỗi`, không hiển thị stack trace trên giao diện chính.

## 8. YouTube Readiness

Editor có một đường kiểm tra riêng:

1. Quyền sử dụng.
2. Giá trị chuyển hóa.
3. Chất lượng biên tập.
4. Sẵn sàng xuất bản.

Thiếu quyền sử dụng, bằng chứng giấy phép hoặc lời bình riêng là blocker. Điểm readiness không phải
lời bảo đảm về YPP, fair use hoặc Content ID.

## 9. Responsive

### Desktop từ 1200 px

- Editor ba cột, timeline ở dưới.
- Inspector rộng 320–380 px.
- Toolbar rộng 64–80 px.

### Tablet 768–1199 px

- Toolbar chuyển thành hàng ngang.
- Inspector nằm dưới preview hoặc mở dạng drawer.
- Timeline cuộn ngang.

### Mobile dưới 768 px

- Ưu tiên preview và cue đang chọn.
- Toolbar cuộn ngang.
- Inspector mở dạng bottom sheet.
- Timeline có thể chuyển thành danh sách cue.
- Nút xuất video sticky nhưng không che nội dung.

## 10. Khả năng tiếp cận

- Độ tương phản đạt WCAG AA.
- Input luôn có label hiển thị.
- Có focus ring rõ ràng khi dùng bàn phím.
- Tab, cue và dialog thao tác được bằng bàn phím.
- Toast quan trọng sử dụng `aria-live`.
- Tôn trọng `prefers-reduced-motion`.

## 11. Checklist nghiệm thu

- Người dùng mới xác định được hành động chính trong 5 giây.
- Tạo project không tự động xuất video.
- Editor mở ngay khi cue sẵn sàng.
- Chỉnh màu, hiệu ứng và phụ đề có preview trực tiếp.
- Chỉ nút `XUẤT VIDEO` tạo MP4.
- Retry không làm mất artifact đã hoàn thành.
- Có trạng thái loading, empty, error và completed.
- Hoạt động ở 360 px, 768 px, 1280 px và 1440 px.
- Không có text nhỏ hơn 11 px hoặc vùng bấm nhỏ hơn 44 px trên mobile.
- Không có lỗi JavaScript, overflow ngoài ý muốn hoặc layout shift lớn.
- Giao diện tuân theo màu sắc, spacing và typography trong tài liệu này.

Mọi thay đổi cấu trúc lớn phải cập nhật `design.md` trước khi sửa giao diện.

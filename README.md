# AZURAI — Creative Studio

Ứng dụng tạo ảnh SD1.5 trên máy, với giao diện web, Creative Director dùng Ollama, tài khoản và dự án lưu trong PostgreSQL.

## Cài đặt và chạy

Cần **Python 3.12**, **Docker Desktop** (hoặc PostgreSQL riêng) và **Ollama** với model đã tải. Mở PowerShell tại thư mục AZURAI:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
Copy-Item .env.example .env
```

Sửa `.env`: thay **cả hai mật khẩu mẫu** bằng cùng một mật khẩu và đặt `AZURAI_DIRECTOR_MODEL` đúng tên trong `ollama list`. Mật khẩu có ký tự đặc biệt cần URL-encode trong `AZURAI_DATABASE_URL`. Nếu đã có `.env`, giữ file hiện tại.

```powershell
docker compose up -d --wait
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Mở **http://127.0.0.1:7860**, chọn **Đăng nhập → Tạo tài khoản**. Dừng bằng **Ctrl+C**. Ứng dụng chỉ sử dụng PostgreSQL để lưu dữ liệu.

Máy hiện có thể dùng PostgreSQL portable: binary ở `.cache/postgresql/pgsql/`, dữ liệu ở `data/postgresql/`. `run.ps1` kiểm tra kết nối và tự khởi động bản portable nếu database local chưa chạy. Dữ liệu này không nằm trong ZIP; backup bằng `scripts/backup.py`. Nếu dùng Docker hoặc PostgreSQL riêng, script dùng database đã cấu hình trong `.env`.

## Sử dụng

- **Trang chủ:** lối tắt, số liệu và tác phẩm gần đây.
- **Tính năng:** tìm kiếm nhóm mô hình; hiện hỗ trợ SD1.5 Text to Image, chưa hỗ trợ Text to Video.
- **Studio:** nhập ý tưởng → chọn concept từ LLM → sửa brief → tạo ảnh. Mỗi lần tạo đều qua Creative Director; Ollama phải chạy và có model phù hợp.
- **Thư viện:** prompt nổi bật theo tính năng, có tìm kiếm, sao chép và dùng prompt để tạo dự án.
- **Dự án:** quản lý ảnh đã tạo, tải PNG và dùng lại thông số.
- **Cài đặt:** GPU, bộ nhớ, offline, chuẩn bị mô hình và lưu mặc định. **Phong cách của tôi** và phản hồi ảnh giúp cá nhân hóa Director, không huấn luyện lại model.

Đặt checkpoint tại `models/text2img/v1-5-pruned-emaonly.safetensors` hoặc khai báo trong `config/models.json`; đường dẫn tính từ gốc dự án. Trong Cài đặt, tắt offline và bấm **Chuẩn bị** để tải các thành phần còn thiếu. Sau đó có thể bật offline:

```powershell
.\run.ps1 --offline
```

Ứng dụng kiểm tra phần cứng **máy chạy Python**. GPU ít VRAM nên bắt đầu với 384×384 hoặc 512×512; hết bộ nhớ thì giảm kích thước và chọn chế độ tiết kiệm VRAM. CPU dùng FP32.

## Cấu trúc và dữ liệu

```text
azurai/             API, inference, Director, tài khoản và database
frontend/           HTML, CSS, JavaScript
config/models.json  Danh sách mô hình
models/             Checkpoint: text2img/, text2vid/
scripts/            Cài đặt, chạy, đóng gói, migration và backup
tests/              Kiểm thử
outputs/            Bản xuất PNG và metadata
data/               Backup PostgreSQL
.cache/             Cache mô hình
```

PostgreSQL lưu tài khoản, phiên, dự án, cấu hình, brief, phản hồi và ảnh. Ảnh được quản lý riêng theo tài khoản trong Dự án; Thư viện chỉ chứa prompt mẫu. `outputs/` là bản xuất, không phải nguồn dữ liệu chính. Giữ volume PostgreSQL và backup khi cập nhật; **`docker compose down -v` xóa volume dữ liệu**. Không commit `.env`.

## Backup và phục hồi
**Backup:** cần `pg_dump` trong PATH, phiên bản cùng major với server hoặc mới hơn. Đích phải là file mới:

```powershell
.\.venv\Scripts\python.exe scripts/backup.py data/backups/azurai-backup.dump
```

Phục hồi khi AZURAI đã dừng, vào **database mới trống** bằng `pg_restore --no-owner --no-acl --exit-on-error -h HOST -U USER -d NEW_DATABASE data/backups/azurai-backup.dump`, rồi cập nhật `AZURAI_DATABASE_URL`. Giữ database và backup gốc.

## Kiểm thử và đóng gói

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
python scripts/package.py --without-models --output AZURAI-source.zip
```

Test tích hợp cần `AZURAI_TEST_DATABASE_URL` trỏ tới PostgreSQL kiểm thử riêng; thiếu URL sẽ skip. Role kiểm thử cần quyền tạo/xóa schema. Test không thay thế việc kiểm tra inference thật với checkpoint và Ollama.

Đóng gói kèm checkpoint: `python scripts/package.py`; thêm cache bằng `--include-cache`. ZIP loại ảnh xuất, tài khoản, `.env`, `.venv` và backup.

**Lỗi thường gặp:**

- `Not Found` sau cập nhật: khởi động lại `run.ps1`, rồi **Ctrl+F5**.
- Cổng bận: chạy `.\run.ps1 --port 7861`.
- `No pyvenv.cfg file`: dừng UI, chạy lại `setup.ps1`.
- Thiếu cấu hình PostgreSQL hoặc Ollama: kiểm tra `.env` và dịch vụ đang chạy.
- Thiếu tokenizer/config: tắt offline và chuẩn bị mô hình lại.

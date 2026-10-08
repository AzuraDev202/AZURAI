# AZURAI — Creative Studio

Ứng dụng tạo ảnh SD1.5 hoặc FLUX.2 Klein Base 4B trên máy, với giao diện web, Creative Director dùng Ollama, tài khoản và dự án lưu trong PostgreSQL.

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
- **Tính năng:** tìm kiếm nhóm mô hình; hiện hỗ trợ SD1.5 và FLUX.2 Klein Text to Image, chưa hỗ trợ Text to Video.
- **Studio:** nhập ý tưởng → chọn concept từ LLM → sửa brief → tạo ảnh. Mỗi lần tạo đều qua Creative Director; Ollama phải chạy và có model phù hợp.
- **Thư viện:** prompt nổi bật theo tính năng, có tìm kiếm, sao chép và dùng prompt để tạo dự án.
- **Dự án:** quản lý ảnh đã tạo, tải PNG và dùng lại thông số.
- **Cài đặt:** GPU, bộ nhớ, offline, chuẩn bị mô hình và lưu mặc định. **Phong cách của tôi** và phản hồi ảnh giúp cá nhân hóa Director, không huấn luyện lại model.

Đặt checkpoint tại `models/text2img/v1-5-pruned-emaonly.safetensors` hoặc khai báo trong `config/models.json`; đường dẫn tính từ gốc dự án. Trong Cài đặt, tắt offline và bấm **Chuẩn bị** để tải các thành phần còn thiếu. Sau đó có thể bật offline:

```powershell
.\run.ps1 --offline
```

Ứng dụng kiểm tra phần cứng **máy chạy Python**. GPU ít VRAM nên bắt đầu với 384×384 hoặc 512×512; hết bộ nhớ thì giảm kích thước và chọn chế độ tiết kiệm VRAM. CPU dùng FP32.


## FLUX.2 Klein Base 4B

Sau khi cập nhật code, chạy lại `setup.ps1` để cài Diffusers 0.37.1 và Transformers từ 4.57. Trong **Cài đặt → Mô hình**, chọn **FLUX.2 Klein Base 4B**, tắt offline, bấm **Tải checkpoint**, rồi **Chuẩn bị mô hình**. Trọn bộ transformer, VAE, Qwen3 text encoder và tokenizer được tải vào `models/text2img/flux2-klein-base-4b/`; không dùng bộ nạp checkpoint SD1.5. Không đưa trọng số model vào Git.

Model gốc: [black-forest-labs/FLUX.2-klein-base-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B), Apache 2.0. Phiên bản tải được cố định tại commit `a3b4f4849157f664bdbc776fd7453c2783562f4d`; chỉ tải bộ Diffusers, tránh tải trùng file checkpoint tổng. Cần nhiều GB đĩa và bộ nhớ: chọn model mới không khiến mọi máy đều chạy được. Bản này chưa tích hợp quantization hoặc train/nạp LoRA.

Khi đổi sang Klein, Studio gợi ý **50 steps, guidance 4**; bạn vẫn có thể chỉnh. Bắt đầu ở 512×512 nếu cần tiết kiệm bộ nhớ, chọn preset cao hoặc tùy chỉnh 1024×1024 khi đủ tài nguyên. Klein dùng FlowMatch scheduler riêng. Nội dung “Chi tiết muốn tránh” được mã hóa thành negative embeddings khi guidance > 1; không truyền tham số `negative_prompt` của SD1.5 sang Klein.

Chọn precision **Tự động**: Klein dùng BF16 trên CUDA compute capability từ 8.0, FP32 trên CPU/GPU cũ. BF16 thủ công bị từ chối trên CUDA không hỗ trợ; FP16 vẫn có thể chọn nhưng không phải mặc định Klein. CPU chạy được về mặt code nhưng có thể rất chậm và cần nhiều RAM. Chế độ offload vẫn dùng RAM máy xử lý.

Klein không có bộ lọc đầu ra đi kèm pipeline. AZURAI nạp riêng bộ kiểm tra ảnh hiện có từ snapshot SD1.5 đã cố định, chạy trên CPU sau khi giải mã và chặn ảnh trước khi lưu. **Chuẩn bị mô hình** tải thành phần này; offline chỉ sẵn sàng khi có cả bộ Klein lẫn bộ lọc. Sau đó có thể chạy `run.ps1 --offline`.

Metadata ảnh ghi backend, revision, fingerprint SHA-256 tổng hợp từ tất cả thành phần model, thông số và precision. Các shard trong bộ Klein chỉ tính là một model, không hiện thành checkpoint SD1.5 riêng. ZIP kèm model chứa các model đã cài, kể cả bộ Klein đầy đủ; không yêu cầu phải tải SD1.5 nếu chỉ dùng Klein. Bộ model chưa tải được bỏ qua. Muốn ZIP offline đầy đủ, dùng thêm `--include-cache` để có bộ lọc đầu ra.

Kiểm thử có pipeline Klein thực với trọng số ngẫu nhiên rất nhỏ trên CPU, kiểm tra denoising/giải mã, seed, routing, negative embeddings, bộ lọc, download/rollback và metadata. Chưa kiểm chứng chất lượng/tốc độ của checkpoint 4B đầy đủ trên GPU. Creative Director vẫn dùng Ollama như trước; FLUX thay phần tạo ảnh.

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


## App desktop Windows

App mở Studio trong cửa sổ AZURAI riêng, giữ luồng Creative Director và FLUX.2 Klein.
Có hai bộ cài Windows x64: **cuda** cho GPU NVIDIA tương thích CUDA 11.8 và **cpu** cho máy không có NVIDIA (tạo ảnh bằng CPU sẽ chậm). Bộ cài đã chứa Python và thư viện; người dùng không cần cài Python.

1. Mở tab **Actions → Windows desktop**, chọn lần build thành công mới nhất và tải artifact `AZURAI-Windows-cuda` hoặc `AZURAI-Windows-cpu`.
2. Giải nén artifact, chạy `AZURAI-Setup-cuda.exe` hoặc `AZURAI-Setup-cpu.exe`.
3. Mở AZURAI từ Desktop hoặc Start Menu. Nhập URL PostgreSQL đang chạy và tên model Ollama trong màn hình thiết lập đầu tiên.
4. Đăng nhập/đăng ký trong Studio, chọn FLUX.2 Klein, tắt offline, bấm **Tải checkpoint → Chuẩn bị mô hình**.

App cần Microsoft **[WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)** và PostgreSQL/Ollama đã chạy (như bản web hiện tại). Bộ cài không chứa PostgreSQL server, Ollama hoặc trọng số model. Kết nối tới database cũ sẽ giữ tài khoản, dự án và lịch sử cũ. Tên model Ollama phải khớp model đã tải trên máy.

Dữ liệu desktop nằm ở `%LOCALAPPDATA%\AZURAI`: `.env`, `config`, `models`, `outputs`, `.cache`, `logs`. Cập nhật/gỡ app không xóa thư mục này. Để sử dụng model đã tải ở bản mã nguồn, sao chép thư mục model vào `models` tại đây hoặc chỉnh `config/models.json` thành đường dẫn tuyệt đối. Shortcut **Thiết lập AZURAI** mở lại màn hình chỉnh kết nối; có thể sửa `.env` để cấu hình thêm `AZURAI_DIRECTOR_URL`. `AZURAI_DATA_DIR` cho phép chọn vị trí dữ liệu khác trước khi khởi động app.

Build trên Windows với Python 3.12 x64:

```powershell
.\build-desktop.ps1 -Flavor cuda
# Hoặc: .\build-desktop.ps1 -Flavor cpu
```

Kết quả: `dist\AZURAI\AZURAI.exe` cùng toàn bộ thư mục `_internal`; giữ nguyên cả thư mục nếu dùng portable. Khi có **Inno Setup 6** (`ISCC.exe` trong PATH), script tạo thêm bộ cài `dist\AZURAI-Setup-<flavor>.exe`. CI build cả hai phiên bản, chạy smoke test trên executable để kiểm tra resource và import thực tế FLUX/Qwen/safety checker. Smoke test không xác nhận chất lượng ảnh với trọng số 4B hoặc giao diện hiển thị trên máy người dùng. Bộ cài chưa ký chứng chỉ số.

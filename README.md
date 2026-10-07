# AZURAI — Image Studio

Giao diện HTML/CSS/JavaScript theo ảnh tham chiếu: nền xanh đen, sidebar bên trái, logo chữ A, nút gradient cyan và vùng ảnh lớn bên phải, hỗ trợ màn hình nhỏ. `frontend/index.html`, `frontend/assets/css/studio.css`, `frontend/assets/js/studio.js` là frontend; `azurai/api.py` phục vụ giao diện và API FastAPI; `azurai/backend.py` giữ logic SD1.5. Python 3.12; CUDA NVIDIA hoặc CPU.

## Cấu trúc dự án

```text
AZURAI/
├── azurai/                 # Package Python
│   ├── __main__.py         # Điểm chạy: python -m azurai
│   ├── api.py              # FastAPI và phục vụ giao diện
│   ├── auth.py             # Tài khoản cục bộ và phiên đăng nhập
│   ├── backend.py          # Nạp mô hình và tạo ảnh
│   └── paths.py            # Đường dẫn chung của dự án
├── frontend/
│   ├── index.html
│   └── assets/
│       ├── css/studio.css
│       └── js/studio.js
├── config/models.json      # Danh sách và cấu hình mô hình
├── scripts/                # Cài đặt, chạy và đóng gói
│   ├── setup.ps1
│   ├── run.ps1
│   └── package.py
├── tests/                  # Kiểm thử API và backend
├── models/                 # Checkpoint, bao gồm các thư mục con
├── outputs/                # Ảnh và metadata được tạo
├── data/                   # SQLite tài khoản (không đưa vào ZIP)
├── .cache/                 # Cache mô hình (không đóng gói mặc định)
├── .venv/                  # Môi trường Python cục bộ
├── setup.ps1               # Lệnh tắt gọi scripts/setup.ps1
├── run.ps1                 # Lệnh tắt gọi scripts/run.ps1
├── requirements.txt
├── README.md
└── LICENSE
```

Đường dẫn checkpoint trong `config/models.json` được tính từ thư mục gốc AZURAI, ví dụ `models/text2img/v1-5-pruned-emaonly.safetensors`. Cache và ảnh đã tạo vẫn dùng các thư mục hiện có. Khi sửa UI, mở các file trong `frontend/`; khi sửa logic tạo ảnh, mở `azurai/backend.py`.

## Cài đặt và chạy

Mở PowerShell trong thư mục đã giải nén:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Mở **http://127.0.0.1:7860**. Dừng bằng Ctrl+C. Script tạo `.venv` riêng và cài PyTorch CUDA 11.8 để hỗ trợ cả GPU Turing; cần mạng và vài GB dung lượng đĩa. Ảnh được lưu trong `outputs/`.

## Trang chủ và tài khoản

Thanh bên có 5 trang riêng: **Trang chủ** (lối tắt, số liệu thật, quy trình sáng tạo), **Tính năng** (nhóm mô hình), **Thư viện** (tìm kiếm, sắp xếp, tải PNG, dùng lại mô tả và thông số), **Dự án** (tạo/sửa/xóa bộ sưu tập, thêm/gỡ ảnh), **Cài đặt** (GPU, bộ nhớ, offline, chuẩn bị mô hình và cấu hình mặc định). Dự án và cấu hình mặc định lưu theo tài khoản trong SQLite; ảnh vẫn dùng chung trên máy. Xóa dự án hoặc gỡ ảnh khỏi dự án không xóa file PNG.

Giao diện dashboard dùng nền tối, thanh bên rộng và thẻ màu lấy cảm hứng từ ảnh tham chiếu. Các công cụ giọng nói, nhạc và xuất bản video trong ảnh mẫu chưa có backend ở dự án này. Text to Video hiển thị trạng thái chưa hỗ trợ.

Trang chủ có nút mở Studio, giới thiệu chức năng và tối đa 4 ảnh gần đây lấy từ thư viện trên máy. Bấm **Đăng nhập → Tạo tài khoản** trong lần sử dụng đầu tiên; tên đăng nhập gồm 3–32 chữ cái, chữ số hoặc dấu `_`, mật khẩu dài 8–128 ký tự. Sau đó dùng tên và mật khẩu để đăng nhập. Bấm biểu tượng tài khoản ở góc phải → **Đăng xuất** để kết thúc phiên.

Studio và các API xử lý ảnh yêu cầu đăng nhập. Tài khoản được lưu trong `data/accounts.sqlite3`; mật khẩu băm bằng scrypt, mã phiên được băm trong cơ sở dữ liệu, cookie HttpOnly/SameSite Strict hết hạn sau 7 ngày và bị thu hồi khi đăng xuất. Dữ liệu tài khoản không được đưa vào Git hay ZIP. Không cần dịch vụ đăng nhập bên ngoài hoặc kết nối mạng để dùng tài khoản.

Đây là tài khoản cho ứng dụng cục bộ: các tài khoản dùng chung mô hình, máy xử lý và thư viện `outputs/`. Đăng xuất không hủy tác vụ tạo ảnh đang chạy trên máy. Giữ file cơ sở dữ liệu nếu muốn giữ tài khoản khi cập nhật dự án.

## Tự chọn mô hình và cấu hình

Mọi phép kiểm tra RAM/CUDA/VRAM đều chạy trên **máy chạy Python**. Nếu đặt AZURAI trên GPU server, đó là cấu hình server; trình duyệt không cung cấp thông số GPU cho quyết định inference.

1. Đọc RAM và VRAM còn trống tại thời điểm chuẩn bị/tạo ảnh.
2. Kiểm tra checkpoint Safetensors, kiến trúc SD1.5 có VAE và các file bổ trợ local.
3. Ưu tiên checkpoint hợp lệ có thành phần đã cache. Hiện dự án có một mô hình SD1.5 chính thức; thêm checkpoint SD1.5 trong `models/` rồi bấm **Kiểm tra lại máy và mô hình**. SDXL/SD2 không được hỗ trợ và không được coi là SD1.5.
4. Chọn cấu hình bộ nhớ và precision, hiển thị tên mô hình và lý do. Có thể đổi mô hình/bộ nhớ/precision thủ công giữa các lần tạo ảnh; pipeline cũ được giải phóng khi cấu hình thay đổi.
5. Khi OOM, giải phóng pipeline và đề nghị giảm xuống 384×384 hoặc 256×256, dùng chế độ tiết kiệm VRAM, đóng tiến trình khác hoặc chọn mô hình nhẹ hơn nếu đã có. Không tự tải/đổi sang mô hình khác sau OOM.

Mặc định chọn offload từng phần nếu VRAM còn trống dưới 6 GB ở FP16 hoặc 8 GB ở FP32; trên ngưỡng đó dùng offload theo mô-đun. CPU luôn dùng FP32. RAM còn trống dưới 2 GB hoặc VRAM dưới 2 GB được gợi ý 384×384. Bấm **Dùng kích thước gợi ý** để áp dụng; ứng dụng giữ kích thước bạn đã chọn nếu không bấm nút này. Đây là quy tắc thận trọng, không đảm bảo mọi prompt/kích thước sẽ vừa bộ nhớ.

Precision mặc định dựa trên khả năng CUDA, không dựa trên tên card. Compute capability 7.5 dùng FP32 thận trọng vì đã gặp ảnh đen/NaN khi chạy FP16 trên GTX 1650 Ti; vẫn có lựa chọn FP16 thủ công. Quyết định bộ nhớ dựa vào RAM/VRAM còn trống. Các checkpoint SD1.5 có cùng kiến trúc, nên kích thước file nhỏ hơn không đồng nghĩa dùng ít VRAM hơn.

## Chuẩn bị lần đầu và offline

Trong mục **Máy xử lý & chuẩn bị mô hình**:

- Chọn **Stable Diffusion 1.5** để xem vị trí checkpoint. File mặc định nằm tại `models/text2img/v1-5-pruned-emaonly.safetensors` (~4 GB). Khi tạo lại ZIP bằng `scripts/package.py`, cấu trúc thư mục này được giữ nguyên.
- Nếu chưa có file, đặt checkpoint đúng vị trí hoặc bấm **Tải checkpoint**. Nút này tải checkpoint chính thức, hiển thị tiến độ theo MB, kiểm tra cấu trúc, tính SHA-256 và chỉ chuyển file tạm thành checkpoint sau khi tải hoàn tất. Không ghi đè checkpoint đang có.
- Tắt offline và bấm **Chuẩn bị mô hình** để tải cấu hình, tokenizer và bộ lọc an toàn vào `.cache/huggingface`, rồi nạp thử pipeline. Tiến độ chuẩn bị được hiển thị theo giai đoạn; tiến độ tải các thành phần Hugging Face chi tiết xuất hiện ở terminal.
- Sau khi chuẩn bị thành công, bật **Chỉ dùng file offline**. Bảng trạng thái liệt kê file thiếu nếu chưa đủ. Kiểm tra file sẵn sàng không thay thế kiểm tra nạp thực tế bằng nút chuẩn bị.

Chạy với offline bật sẵn hoặc dùng checkpoint/cấu hình riêng:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 --offline
.\.venv\Scripts\python.exe -m azurai --model "E:\AZURAI\models\custom.safetensors" --config "thu-muc-cau-hinh-diffusers" --offline --port 7861
```

Danh sách mô hình nằm trong `config/models.json`; bản SD1.5 chính thức ghim revision cấu hình. Nếu biết SHA-256 tin cậy của checkpoint, thêm trường `sha256` để từ chối file có hash khác. Hash được tính từ file chưa có giá trị đối chiếu chỉ xác định file, không chứng minh nguồn gốc file.

Tất cả checkpoint đặt trong `models/`; ứng dụng tìm cả các thư mục con như `models/text2img/`. Mô hình mặc định được tải về vị trí trong `config/models.json`. Thư mục `models/text2vid/` có thể dùng để tổ chức file, nhưng ứng dụng hiện chỉ hỗ trợ SD1.5 text-to-image, không có tính năng tạo video.

## Kích thước và độ phân giải

Mục **Tính năng** đọc các nhóm trong `models/`: `text2img` tương ứng **Text to Image**, `text2vid` tương ứng **Text to Video**. Mỗi nhóm hiển thị các file `.safetensors` đã có; mở lại mục **Tính năng** sau khi thêm file để cập nhật danh sách. Trường `task` trong `config/models.json` dùng `text-to-image` hoặc `text-to-video` (mặc định là `text-to-image` cho cấu hình cũ). Backend hiện chỉ chạy SD1.5 Text to Image; nhóm video hiển thị trạng thái chưa hỗ trợ và không được đưa vào danh sách mô hình tạo ảnh.

Sidebar có Trang chủ, Tạo hình ảnh, Thư viện và Cài đặt. Thư viện đọc ảnh PNG và thông số thực tế trong `outputs/`, cho phép xem lại và tải ảnh. Cài đặt mở nhóm tùy chỉnh nâng cao; nút chuông hiển thị trạng thái xử lý, nút phiên làm việc hiển thị thông tin máy xử lý. Badge GPU và tên mô hình luôn dùng dữ liệu thực tế. Ảnh xem gần nhất được giữ khi tải lại trang; file đã xóa sẽ trở về khung trống.

Trong bảng nhập bên trái, chọn bố cục vuông 1:1, ngang 4:3, dọc 3:4, rộng ≈16:9 hoặc dọc ≈9:16; chọn mức **Nhẹ**, **Tiêu chuẩn** hoặc **Cao** để áp dụng kích thước có sẵn. Ví dụ ảnh vuông lần lượt 384×384, 512×512 và 768×768; ảnh ngang 4:3 lần lượt 512×384, 768×576 và 1024×768.

Ô chiều rộng/chiều cao cho phép tùy chỉnh từ 256 đến 1024 px, bước 64 px. Dòng độ phân giải thực tế luôn hiển thị kích thước cuối cùng và số megapixel, kể cả khi chỉnh tay hoặc áp dụng gợi ý bộ nhớ. Kích thước lớn tăng nhu cầu bộ nhớ; mức Cao là tạo ảnh trực tiếp, không phải upscale. Với GPU 4 GB, nên bắt đầu bằng 512×512 hoặc mức Nhẹ. Các tỉ lệ có dấu ≈ được làm tròn để kích thước là bội số của 64.

## Metadata và tái tạo ảnh

PNG chứa metadata; JSON cạnh ảnh lưu prompt, negative prompt, seed, steps, CFG, kích thước, SHA-256 checkpoint, cấu hình scheduler đầy đủ, revision/hash các thành phần bổ trợ, phiên bản thư viện, thiết bị, precision và chế độ bộ nhớ. SHA checkpoint được cache trong phiên theo đường dẫn, kích thước và thời gian thay đổi file; nội dung file không nên bị sửa trong khi đang tạo ảnh.

Metadata giúp xác định môi trường cần dùng lại. Cùng seed không bảo đảm ảnh giống từng pixel giữa phần cứng, precision hay phiên bản thư viện khác nhau. Prompt dài có thể bị CLIP cắt ở giới hạn token; xem cảnh báo terminal.

## Kết nối giao diện AZURAI khác

Backend độc lập với giao diện. Giao diện khác có thể gọi service này trong tiến trình xử lý GPU của server; giữ một service dùng chung để tuần tự hóa tải mô hình/inference:

```python
from azurai.backend import InferenceService

service = InferenceService()
report, suggested_size = service.inspect(offline=True)
image_path, download_path, status = service.generate(
    prompt="A cozy cabin in a forest", negative="blurry",
    width=512, height=512, steps=20, guidance=7, seed=42,
    offline=True, progress=lambda fraction, message: print(message),
)
```

Frontend riêng trong `frontend/index.html`/`frontend/assets/css/studio.css`/`frontend/assets/js/studio.js` gọi API FastAPI của `azurai/api.py`. `/api/options` và `/api/device` trả về mô hình, kích thước và cấu hình máy xử lý; `/api/generate`, `/api/prepare`, `/api/checkpoint` bắt đầu công việc nền; `/api/jobs/{id}` trả tiến độ và `/api/images/{id}` tải PNG. Chỉ xử lý một công việc tại một thời điểm. UI giữ mã công việc trong trình duyệt để nối lại tiến độ khi tải lại trang. Máy chủ chỉ lắng nghe tại `127.0.0.1`. Bộ lọc an toàn được nạp rõ ràng.

## Đóng gói ZIP

Script dùng danh sách file cho phép, không phụ thuộc `.gitignore`. Mặc định ZIP gồm mã nguồn, tài liệu, tests và checkpoint; loại `outputs`, `.venv`, `.git`, cache và ZIP khác. Có manifest SHA-256 từng file và kiểm tra CRC ZIP sau khi ghi.

```powershell
python scripts/package.py
python scripts/package.py --without-models --output AZURAI-source.zip
python scripts/package.py --include-cache --output AZURAI-offline.zip
```

`--include-cache` thêm snapshot/refs đã cache để mang sang máy khác; hãy chuẩn bị mô hình hoàn tất trước. `.venv` vẫn không được đóng gói, nên máy mới phải cài thư viện bằng `setup.ps1` trước khi sử dụng. Nếu cần cài thư viện hoàn toàn offline, phải chuẩn bị thêm bộ wheel riêng. Bản ZIP source không chứa checkpoint và cần đặt/tải mô hình qua mục chuẩn bị mô hình.

## Kiểm tra và xử lý lỗi

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```

- Thiếu tokenizer/config: tắt offline, kiểm tra kết nối Hugging Face và bấm Chuẩn bị mô hình.
- File checkpoint hỏng hoặc sai kiến trúc: thay file SD1.5 hợp lệ; nút tải không ghi đè file đang có.
- Cổng 7860 bận: thêm `--port 7861` khi chạy `run.ps1`.
- Ảnh lỗi số học khi ép FP16: chọn FP32 và thử lại.
- Lỗi `No pyvenv.cfg file`: `.venv` bị thiếu hoặc hỏng. Dừng UI đang chạy bằng Ctrl+C rồi chạy lại `setup.ps1`; script kiểm tra môi trường, phục hồi cấu hình và bootstrap pip trước khi cài thư viện. Không cần xóa checkpoint hoặc ảnh đã tạo.


Tham khảo: [Diffusers single-file loading](https://huggingface.co/docs/diffusers/v0.36.0/en/api/loaders/single_file), [FastAPI](https://fastapi.tiangolo.com/).

## Creative Director V1

Bật **✨ Creative Director** trong Studio để đi từ ý tưởng → 3 concept → brief có thể sửa → prompt → Text2Img. Chọn concept, chỉnh chủ thể/bối cảnh/camera/ánh sáng/phong cách và bấm **Tạo hình ảnh**. Prompt được biên dịch trên máy chủ từ brief đã lưu; chế độ nhập prompt trực tiếp vẫn hoạt động khi tắt Creative Director.

### Bật LLM cục bộ (Ollama)

Cài và chạy [Ollama](https://ollama.com/), tải một model có khả năng hiểu tiếng Việt và xuất JSON có cấu trúc. Ví dụ với model đã cài `qwen2.5:3b`, chạy trong PowerShell tại thư mục AZURAI:

```powershell
$env:AZURAI_DIRECTOR_MODEL = "qwen2.5:3b"
$env:AZURAI_DIRECTOR_URL = "http://127.0.0.1:11434"
.\run.ps1
```

Tên model phải khớp với `ollama list`. `AZURAI_DIRECTOR_URL` là tùy chọn, mặc định là địa chỉ trên; chỉ hỗ trợ Ollama HTTP trên localhost. Không cần API key. Cấu hình được đọc từ biến môi trường phía máy chủ, không từ trình duyệt. Gỡ biến model để quay về gợi ý mẫu:

```powershell
Remove-Item Env:AZURAI_DIRECTOR_MODEL -ErrorAction SilentlyContinue
.\run.ps1
```

Khi không cấu hình LLM, UI ghi rõ **Gợi ý mẫu**: các hướng sáng tạo được dựng từ preset, giữ nguyên câu nhập làm chủ thể và chưa tự hiểu/dịch ý tưởng tiếng Việt. Khi đã cấu hình LLM nhưng Ollama mất kết nối hoặc trả JSON sai, AZURAI báo lỗi để thử lại. Không âm thầm chuyển sang mẫu.

LLM tạo ba brief khác nhau, dùng tiêu đề tiếng Việt và trường hình ảnh tiếng Anh. Dữ liệu được kiểm tra bằng Pydantic trước khi hiển thị. API Ollama dùng [structured output](https://docs.ollama.com/api/chat) và `keep_alive: 0` để yêu cầu giải phóng model sau khi trả lời. Yêu cầu phát triển concept và job ảnh được chạy lần lượt để hạn chế tranh VRAM. Chất lượng hiểu ý tưởng phụ thuộc LLM đã chọn; cần kiểm tra concept trước khi tạo ảnh.

### Lưu và phát triển tiếp

- Mỗi tài khoản có một brief nháp lưu trong SQLite, phục hồi qua **Mở lại brief đã lưu**. Bản nháp có phiên bản; sửa đồng thời ở tab khác sẽ báo xung đột thay vì ghi đè.
- Mỗi ảnh từ Director lưu snapshot `creative: {version, brief}` trong JSON cạnh ảnh. Mở ảnh từ thư viện và dùng lại để chỉnh tiếp. Thư viện ảnh vẫn dùng chung trên máy như phiên bản trước, bao gồm brief đính kèm; brief nháp riêng theo tài khoản.
- **Biến thể mới** giữ brief và đặt seed `-1`; đổi camera/style/ánh sáng/bối cảnh mở đúng trường brief để bạn sửa trước khi tạo lại.
- Text2Img tạo ảnh mới, chưa có image-to-image hay cơ chế khóa danh tính nhân vật. Chưa có bước tự chấm điểm ảnh bằng vision model.
- Prompt ưu tiên chủ thể/hành động/bối cảnh. SD1.5 có ngữ cảnh CLIP ngắn; UI nhắc rút gọn khi prompt dài. Tỷ lệ ảnh tuân theo preset kích thước hiện có (xấp xỉ 16:9 và 9:16 do bội số 64).

API có xác thực: `POST /api/director/concepts`, `POST /api/director/compile`, `GET/PUT /api/director/draft`, `POST /api/director/generate`, `GET /api/director/config`. Generate nhận phiên bản brief và thông số inference; không nhận prompt từ trình duyệt.

Kiểm thử (không tải checkpoint):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

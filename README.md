# AZURAI — SD 1.5 Text to Image

Giao diện Python/Gradio tiếng Việt sử dụng checkpoint `v1-5-pruned-emaonly.safetensors` trong thư mục này. Python 3.12 và GPU NVIDIA được hỗ trợ; khi không có CUDA, chương trình dùng CPU.

## Cài đặt và chạy trên Windows

Mở PowerShell trong thư mục dự án:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Mở **http://127.0.0.1:7860** trong trình duyệt. Nhập prompt và bấm **Tạo ảnh**. Dừng ứng dụng bằng Ctrl+C trong terminal.

Script tạo `.venv` riêng. PyTorch CUDA 11.8 được chọn để hỗ trợ GPU GTX 1650 Ti (Turing). Thư viện cần vài GB dung lượng đĩa và mạng để cài đặt. Dòng GTX 16xx tự dùng FP32 để tránh ảnh đen do lỗi số học FP16; các GPU CUDA khác dùng FP16.

## Cách sử dụng

- Mặc định 512×512, 20 bước, CFG 7, chế độ tiết kiệm VRAM cho GPU 4 GB.
- Prompt tiếng Anh thường hiệu quả hơn. Negative prompt mô tả các chi tiết muốn tránh.
- Seed `-1` tạo ngẫu nhiên; dùng lại seed và các thông số để tái tạo ảnh trên cùng môi trường.
- Mỗi lần tạo một ảnh. Ảnh PNG chứa metadata; file JSON bên cạnh lưu thông số trong `outputs/`.
- Chọn chế độ bộ nhớ trước lần tạo đầu tiên. Muốn đổi chế độ sau đó cần khởi động lại ứng dụng.
- Chế độ 4 GB chuyển từng phần mô hình giữa CPU và GPU, tiết kiệm VRAM nhưng chậm hơn. Nếu thiếu bộ nhớ, khởi động lại và giảm xuống 384×384.

Checkpoint không chứa toàn bộ tokenizer/cấu hình của pipeline. Lần tạo ảnh đầu tiên tải các thành phần bổ trợ từ `stable-diffusion-v1-5/stable-diffusion-v1-5` trên Hugging Face vào `.cache/huggingface`, bao gồm thành phần bộ lọc an toàn nếu cấu hình yêu cầu; trọng số tạo ảnh chính được đọc từ file local. Không tải lại checkpoint SD 1.5 để thay thế file đang có. Quá trình nạp lần đầu có thể mất vài phút và cần RAM hệ thống đáng kể.

Sau khi đã tải đủ dữ liệu, có thể chạy offline:

```powershell
.\.venv\Scripts\python.exe app.py --offline
```

Chọn checkpoint hoặc thư mục cấu hình khác:

```powershell
.\.venv\Scripts\python.exe app.py --model "E:\AZURAI\v1-5-pruned-emaonly.safetensors" --config "duong-dan-cau-hinh-diffusers" --offline --port 7861
```

Ứng dụng chỉ lắng nghe tại `127.0.0.1`, không tạo link Gradio công khai. Bộ lọc an toàn của pipeline được giữ theo cấu hình gốc.

## Xử lý lỗi

- Không tải được tokenizer/config: kiểm tra kết nối Hugging Face; không dùng `--offline` ở lần đầu.
- Không có CUDA: kiểm tra driver NVIDIA và chạy `.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"`.
- Cổng 7860 đang được dùng: thêm `--port 7861` khi chạy `run.ps1`.

Tham khảo: [Diffusers single-file loading](https://huggingface.co/docs/diffusers/v0.36.0/en/api/loaders/single_file), [Gradio Blocks](https://gradio.app/docs/gradio/blocks).

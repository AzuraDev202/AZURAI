"""Windows desktop shell. Configure storage before importing the inference API."""
import argparse
import json
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path


def initialize_data(root, resources):
    root.mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(exist_ok=True)
    for name in ("models.json", "prompts.json"):
        target = root / "config" / name
        if not target.exists():
            shutil.copyfile(resources / "config" / name, target)
    for name in ("models/text2img", "outputs", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)


def save_settings(root, database_url, director_model):
    from psycopg.conninfo import conninfo_to_dict
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Nhập URL PostgreSQL bắt đầu bằng postgresql://")
    conninfo_to_dict(database_url)
    if not director_model.strip():
        raise ValueError("Nhập tên model Creative Director trong Ollama.")
    # JSON double-quoted values are supported by python-dotenv, including escapes.
    text = "AZURAI_DATABASE_URL=" + json.dumps(database_url) + "\n"
    text += "AZURAI_DIRECTOR_MODEL=" + json.dumps(director_model.strip()) + "\n"
    temporary = root / ".env.part"
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(root / ".env")


def configure(root):
    import tkinter as tk
    from tkinter import messagebox
    from dotenv import dotenv_values
    settings = dotenv_values(root / ".env")
    window = tk.Tk()
    window.title("Thiết lập AZURAI")
    window.resizable(False, False)
    tk.Label(window, text="Kết nối PostgreSQL đang chạy trên máy hoặc server của bạn.\n"
             "Creative Director cần Ollama và model đã tải.", justify="left").pack(padx=24, pady=16)
    tk.Label(window, text="URL PostgreSQL").pack(anchor="w", padx=24)
    database = tk.Entry(window, width=70, show="*")
    database.insert(0, settings.get("AZURAI_DATABASE_URL") or
                    "postgresql://azurai:YOUR_PASSWORD@127.0.0.1:5432/azurai")
    database.pack(padx=24, pady=6)
    tk.Label(window, text="Model Creative Director (Ollama)").pack(anchor="w", padx=24)
    model = tk.Entry(window, width=70)
    model.insert(0, settings.get("AZURAI_DIRECTOR_MODEL") or "qwen2.5:7b")
    model.pack(padx=24, pady=6)
    tk.Label(window, text=f"Dữ liệu và cấu hình: {root}", wraplength=510, justify="left").pack(padx=24, pady=8)
    accepted = []
    def save():
        try:
            save_settings(root, database.get().strip(), model.get())
        except (ValueError, OSError):
            messagebox.showerror("Cấu hình chưa hợp lệ", "Kiểm tra URL PostgreSQL, tên model và quyền ghi thư mục.")
            return
        accepted.append(True)
        window.destroy()
    tk.Button(window, text="Lưu và mở AZURAI", command=save).pack(pady=16)
    window.mainloop()
    return bool(accepted)


class LocalServer:
    """Bind before starting, so another process cannot steal the selected port."""
    def __init__(self, app):
        import uvicorn
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                    log_config=None, access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def start(self, timeout=60):
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                self.close()
                raise RuntimeError("Backend AZURAI không thể khởi động.")
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.should_exit = True
        if self.thread.ident:
            self.thread.join(timeout=10)
        self.socket.close()


def smoke_test():
    # Executed on the frozen Windows binary by CI; no weights or DB required.
    from . import api, backend, flux
    from diffusers import Flux2KleinPipeline
    from transformers import Qwen3ForCausalLM
    from diffusers.pipelines.stable_diffusion.safety_checker import StableDiffusionSafetyChecker
    import webview
    if sys.platform == "win32":
        import webview.platforms.winforms
    import psycopg_binary
    from .paths import FRONTEND_DIR, CONFIG_DIR
    assert (FRONTEND_DIR / "index.html").is_file()
    assert json.loads((CONFIG_DIR / "models.json").read_text(encoding="utf-8"))
    assert Flux2KleinPipeline and Qwen3ForCausalLM and StableDiffusionSafetyChecker and webview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    from .paths import ROOT, RESOURCE_ROOT
    initialize_data(ROOT, RESOURCE_ROOT)
    if args.smoke_test:
        smoke_test()
        return
    from dotenv import load_dotenv, dotenv_values
    if args.configure or not (os.environ.get("AZURAI_DATABASE_URL") or
                              dotenv_values(ROOT / ".env").get("AZURAI_DATABASE_URL")):
        if not configure(ROOT):
            return
    load_dotenv(ROOT / ".env", override=False)
    # CPU Torch avoids demanding a CUDA installation. CUDA builds include their runtime.
    import webview
    from . import api
    server = LocalServer(api.app)
    try:
        url = server.start()
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window("AZURAI — Creative Director", url, width=1360, height=900,
                              min_size=(1000, 680), text_select=True)
        webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(ROOT / ".cache" / "webview"))
    finally:
        server.close()


def entrypoint():
    # A windowed executable has no stdout/stderr; dependencies still write to them.
    from .paths import ROOT
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    with (ROOT / "logs" / "desktop.log").open("a", encoding="utf-8", buffering=1) as log:
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
        try:
            main()
        except Exception as exc:
            # Do not persist connection URLs/passwords in logs or native dialogs.
            print("AZURAI desktop startup failed:", type(exc).__name__, file=log)
            if "--smoke-test" in sys.argv:
                raise SystemExit(1) from None
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk()
            window.withdraw()
            messagebox.showerror("Không thể mở AZURAI",
                "Kiểm tra PostgreSQL đang chạy, URL/mật khẩu trong .env và WebView2 Runtime.\n"
                f"Cấu hình: {ROOT / '.env'}\n"
                "Mở shortcut ‘Thiết lập AZURAI’ để chỉnh kết nối.")
            window.destroy()


if __name__ == "__main__":
    entrypoint()

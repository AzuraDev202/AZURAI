import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import app as studio


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(studio.app, base_url="http://127.0.0.1")
        with studio.GUARD:
            studio.JOBS.clear()
            studio.ACTIVE = None

    def wait_job(self, job):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            data = self.client.get(f"/api/jobs/{job}").json()
            if data["state"] != "running":
                return data
            time.sleep(0.01)
        self.fail("Job did not finish")

    def test_reference_ui_and_assets_are_served_without_cache(self):
        for route in ["/", "/studio.css", "/studio.js"]:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("Creative Studio", self.client.get("/").text)

    def test_prompt_reaches_generation_and_png_download(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cat.png"
            Image.new("RGB", (256, 256), "orange").save(path)
            with patch.object(studio.SERVICE, "generate", return_value=(str(path), str(path), "done")) as generate:
                response = self.client.post("/api/generate", json={"prompt": "Tạo con mèo", "width": 256, "height": 256})
                self.assertEqual(response.status_code, 202)
                job = response.json()["id"]
                self.assertEqual(self.wait_job(job)["state"], "done")
                self.assertEqual(generate.call_args.kwargs["prompt"], "Tạo con mèo")
                image = self.client.get(f"/api/images/{job}")
                self.assertEqual(image.headers["content-type"], "image/png")
                self.assertEqual(image.content, path.read_bytes())
                self.assertNotIn("path", self.client.get(f"/api/jobs/{job}").json())

    def test_invalid_size_or_blank_prompt_does_not_run_inference(self):
        with patch.object(studio.SERVICE, "generate") as generate:
            self.assertEqual(self.client.post("/api/generate", json={"prompt": "cat", "width": 513}).status_code, 422)
            self.assertEqual(self.client.post("/api/generate", json={"prompt": "   "}).status_code, 400)
            generate.assert_not_called()

    def test_only_one_job_runs_and_backend_errors_are_reported(self):
        entered, release = threading.Event(), threading.Event()

        def failing_inference(**kwargs):
            entered.set()
            release.wait(3)
            raise ValueError("Checkpoint thiếu")

        with patch.object(studio.SERVICE, "generate", side_effect=failing_inference):
            first = self.client.post("/api/generate", json={"prompt": "cat"})
            self.assertTrue(entered.wait(2))
            try:
                self.assertEqual(self.client.post("/api/prepare", json={}).status_code, 409)
            finally:
                release.set()
            job = self.wait_job(first.json()["id"])
            self.assertEqual(job["state"], "error")
            self.assertEqual(job["message"], "Checkpoint thiếu")

    def test_prepare_uses_manual_settings(self):
        with patch.object(studio.SERVICE, "prepare", return_value="Ready") as prepare:
            response = self.client.post("/api/prepare", json={"selection": "sd15", "precision": "FP32", "offline": True})
            self.assertEqual(self.wait_job(response.json()["id"])["state"], "done")
            self.assertEqual(prepare.call_args.kwargs["selection"], "sd15")
            self.assertTrue(prepare.call_args.kwargs["offline"])

    def test_all_size_options_and_offline_download_guard(self):
        options = self.client.get("/api/options").json()
        self.assertEqual(sum(len(sizes) for sizes in options["presets"].values()), 15)
        self.assertEqual(self.client.post("/api/checkpoint", json={"offline": True}).status_code, 400)

    def test_cross_origin_request_is_rejected(self):
        self.assertEqual(self.client.post("/api/generate", json={"prompt": "cat"},
                                         headers={"Origin": "https://example.com"}).status_code, 403)

    def test_library_lists_saved_images_and_rejects_paths_outside_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            outputs.mkdir()
            path = outputs / "saved.png"
            Image.new("RGB", (256, 256), "blue").save(path)
            path.with_suffix(".json").write_text('{"prompt":"A blue cat","width":256,"height":256}', encoding="utf-8")
            with patch.object(studio, "ROOT", root):
                data = self.client.get("/api/library").json()
                self.assertEqual(data["images"][0]["prompt"], "A blue cat")
                self.assertEqual(self.client.get("/api/library/saved.png").content, path.read_bytes())
                self.assertEqual(self.client.get("/api/library/missing.png").status_code, 404)
                self.assertEqual(self.client.get("/api/library/..%5csecret.png").status_code, 404)


if __name__ == "__main__":
    unittest.main()

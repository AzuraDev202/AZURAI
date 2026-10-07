import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import azurai.api as studio
import azurai.backend as inference
import azurai.features as feature_catalog


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store_patch = patch.object(studio.auth, "STORE", studio.auth.AccountStore(Path(self.directory.name) / "accounts.sqlite3"))
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.client = TestClient(studio.app, base_url="http://127.0.0.1")
        self.client.post("/api/auth/register", json={"username": "tester", "password": "test-password"})
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
        for route in ["/", "/studio.css", "/studio.js", "/workspace.js", "/dashboard.css"]:
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

    def test_features_follow_model_folders_and_video_is_not_an_image_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir()
            (config / "models.json").write_text("[]", encoding="utf-8")
            images = root / "models" / "text2img"
            video = root / "models" / "text2vid"
            images.mkdir(parents=True)
            video.mkdir()
            (images / "image.safetensors").write_bytes(b"test")
            with patch.object(feature_catalog, "ROOT", root), patch.object(feature_catalog, "CONFIG_DIR", config), \
                    patch.object(inference, "ROOT", root), patch.object(inference, "CONFIG_DIR", config):
                features = self.client.get("/api/features").json()["features"]
                self.assertEqual([item["id"] for item in features], ["text-to-image", "text-to-video"])
                self.assertEqual(features[0]["model_count"], 1)
                self.assertEqual(features[1]["model_count"], 0)
                self.assertFalse(features[1]["supported"])
                (video / "video.safetensors").write_bytes(b"test")
                features = self.client.get("/api/features").json()["features"]
                self.assertEqual(features[1]["model_count"], 1)
                self.assertEqual([entry["name"] for entry in inference.InferenceService().models()], ["image.safetensors"])

    def test_cross_origin_request_is_rejected(self):
        self.assertEqual(self.client.post("/api/generate", json={"prompt": "cat"},
                                         headers={"Origin": "https://example.com"}).status_code, 403)

    def test_projects_crud_membership_and_account_isolation(self):
        project = self.client.post("/api/projects", json={"name": "My collection", "description": "draft"})
        self.assertEqual(project.status_code, 201)
        project_id = project.json()["id"]
        self.assertEqual(self.client.put(f"/api/projects/{project_id}", json={"name": "Updated"}).status_code, 200)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs").mkdir()
            image = root / "outputs" / "saved.png"
            Image.new("RGB", (256, 256)).save(image)
            with patch.object(studio, "ROOT", root):
                for _ in range(2):
                    self.assertEqual(self.client.post(f"/api/projects/{project_id}/images", json={"filename": "saved.png"}).status_code, 200)
                self.assertEqual(self.client.get("/api/projects").json()["projects"][0]["images"], ["saved.png"])
                self.assertEqual(self.client.delete(f"/api/projects/{project_id}/images/saved.png").status_code, 200)
                self.assertTrue(image.is_file())
                self.assertEqual(self.client.post(f"/api/projects/{project_id}/images", json={"filename": "../secret.png"}).status_code, 404)
        other = TestClient(studio.app, base_url="http://127.0.0.1")
        other.post("/api/auth/register", json={"username": "other", "password": "test-password"})
        self.assertEqual(other.get("/api/projects").json()["projects"], [])
        self.assertEqual(other.delete(f"/api/projects/{project_id}").status_code, 404)
        self.assertEqual(other.put(f"/api/projects/{project_id}", json={"name": "stolen"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/projects").json()["projects"], [])

    def test_preferences_persist_per_account_and_validate_dimensions(self):
        self.assertEqual(self.client.put("/api/preferences", json={"width": 513}).status_code, 422)
        self.assertEqual(self.client.put("/api/preferences", json={"width": 640, "seed": 42}).status_code, 200)
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
        saved = self.client.get("/api/preferences").json()["preferences"]
        self.assertEqual((saved["width"], saved["seed"]), (640, 42))
        self.client.post("/api/auth/register", json={"username": "another", "password": "test-password"})
        self.assertEqual(self.client.get("/api/preferences").json()["preferences"]["width"], 512)

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

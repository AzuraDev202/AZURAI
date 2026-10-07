import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from fixtures import brief, concepts, postgres_store
from PIL import Image

import azurai.api as studio
import azurai.backend as inference
import azurai.features as feature_catalog


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store_patch = patch.object(studio.auth, "STORE", postgres_store(self))
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.client = TestClient(studio.app, base_url="http://127.0.0.1")
        self.client.post("/api/auth/register", json={"username": "tester", "password": "test-password"})
        env_patch = patch.dict(os.environ, {"AZURAI_DIRECTOR_MODEL": "test-model"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        def llm_post(url, json):
            payload = __import__("json").loads(json["messages"][1]["content"])
            output = {"concepts": concepts(payload["idea"]["idea"])} if "idea" in payload else payload["approved_brief"]
            return httpx.Response(200, json={"message": {"content": __import__("json").dumps(output)}}, request=httpx.Request("POST", url))
        client_patch = patch("azurai.director.httpx.Client")
        self.llm_client = client_patch.start()
        self.llm_client.return_value.__enter__.return_value.post.side_effect = llm_post
        self.addCleanup(client_patch.stop)
        with studio.GUARD:
            studio.JOBS.clear()
            studio.ACTIVE = None

    def submit_image(self, payload):
        saved = self.client.get("/api/director/draft").json()
        self.client.put("/api/director/draft", json={"version": saved["version"], "brief": brief(payload.get("prompt", "cat")).model_dump()})
        params = {key: value for key, value in payload.items() if key not in {"prompt", "negative"}}
        return self.client.post("/api/director/generate", json={"version": saved["version"] + 1, **params})

    def wait_job(self, job):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            data = self.client.get(f"/api/jobs/{job}").json()
            if data["state"] != "running":
                return data
            time.sleep(0.01)
        self.fail("Job did not finish")

    def test_reference_ui_and_assets_are_served_without_cache(self):
        for route in ["/", "/studio.css", "/studio.js", "/workspace.js", "/dashboard.css", "/director.js", "/director.css"]:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn('id="studioView"', self.client.get("/").text)
        self.assertIn('id="directorPanel"', self.client.get("/").text)

    def test_prompt_reaches_generation_and_png_download(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cat.png"
            Image.new("RGB", (256, 256), "orange").save(path)
            with patch.object(studio.SERVICE, "generate", return_value=(str(path), str(path), "done")) as generate:
                response = self.submit_image({"prompt": "Tạo con mèo", "width": 256, "height": 256})
                self.assertEqual(response.status_code, 202)
                job = response.json()["id"]
                self.assertEqual(self.wait_job(job)["state"], "done")
                self.assertTrue(generate.call_args.kwargs["prompt"].startswith("Tạo con mèo"))
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
            first = self.submit_image({"prompt": "cat"})
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
            user_id = self.client.get("/api/auth/session").json()["user"]["id"]
            studio.storage.store_image(image.name, image.read_bytes(), {}, user_id)
            with self.subTest("project image membership"):
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

    def test_director_draft_isolation_conflicts_and_generation_snapshot(self):
        response = self.client.post("/api/director/concepts", json={"idea": "a red bottle"})
        self.assertEqual(response.status_code, 200)
        brief = response.json()["concepts"][0]
        saved = self.client.put("/api/director/draft", json={"brief": brief, "version": 0})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["version"], 1)
        self.assertEqual(self.client.put("/api/director/draft", json={"brief": brief, "version": 0}).status_code, 409)
        self.assertEqual(self.client.post("/api/director/generate", json={"version": 2}).status_code, 409)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "creative.png"
            Image.new("RGB", (256, 256)).save(image)
            with patch.object(studio.SERVICE, "generate", return_value=(str(image), str(image), "done")) as generate:
                job = self.client.post("/api/director/generate", json={"version": 1, "width": 256, "height": 256, "seed": 42})
                self.assertEqual(job.status_code, 202)
                self.assertEqual(self.wait_job(job.json()["id"])["state"], "done")
                self.assertEqual(generate.call_args.kwargs["prompt"], saved.json()["prompt"])
                self.assertEqual(generate.call_args.kwargs["seed"], 42)
                import json
                metadata = json.loads(image.with_suffix(".json").read_text())
                self.assertEqual(metadata["creative"]["brief"], brief)
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
        self.assertEqual(self.client.get("/api/director/draft").json()["brief"], brief)
        other = TestClient(studio.app, base_url="http://127.0.0.1")
        other.post("/api/auth/register", json={"username": "director2", "password": "test-password"})
        self.assertIsNone(other.get("/api/director/draft").json()["brief"])
        self.assertEqual(other.post("/api/director/generate", json={"version": 1}).status_code, 400)
        outsider = TestClient(studio.app, base_url="http://127.0.0.1")
        self.assertEqual(outsider.post("/api/director/concepts", json={"idea": "cat"}).status_code, 401)

    def test_director_errors_validation_and_exclusion_from_image_jobs(self):
        self.assertEqual(self.client.post("/api/director/concepts", json={"idea": " "}).status_code, 422)
        with patch.object(studio.director, "develop", side_effect=studio.director.DirectorError("LLM unavailable")):
            self.assertEqual(self.client.post("/api/director/concepts", json={"idea": "cat"}).status_code, 502)
        self.assertFalse(studio.DIRECTOR_GUARD.locked())
        with studio.DIRECTOR_GUARD:
            self.assertEqual(self.submit_image({"prompt": "cat"}).status_code, 409)
            self.assertEqual(self.client.post("/api/director/concepts", json={"idea": "cat"}).status_code, 409)

    def test_required_llm_and_raw_prompt_cannot_bypass_director(self):
        with patch.object(studio.SERVICE, "generate") as generate:
            self.assertEqual(self.client.post("/api/generate", json={"prompt": "cat"}).status_code, 409)
            with patch.dict(os.environ, {"AZURAI_DIRECTOR_MODEL": ""}):
                self.assertEqual(self.client.post("/api/director/concepts", json={"idea": "cat"}).status_code, 502)
                self.assertEqual(self.submit_image({"prompt": "cat"}).status_code, 502)
            generate.assert_not_called()
            self.assertEqual(self.client.get("/api/history").json()["jobs"], [])

    def test_personal_context_reaches_llm_and_jobs_images_survive_memory_and_file_loss(self):
        profile = {"style": "watercolor", "palette": "pastel", "purpose": "personal art"}
        self.assertEqual(self.client.put("/api/profile", json=profile).status_code, 200)
        self.client.post("/api/director/concepts", json={"idea": "cat"})
        payload = json.loads(self.llm_client.return_value.__enter__.return_value.post.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(payload["personal_context"]["profile"]["style"], "watercolor")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.png"
            Image.new("RGB", (256, 256)).save(path)
            png = path.read_bytes()
            with patch.object(studio.SERVICE, "generate", return_value=(str(path), str(path), "done")):
                first = self.submit_image({"prompt": "cat"})
                job_id = first.json()["id"]
                self.assertEqual(self.wait_job(job_id)["state"], "done")
            path.unlink()
            with studio.GUARD:
                studio.JOBS.clear()
            self.assertEqual(self.client.get(f"/api/images/{job_id}").content, png)
            self.assertEqual(self.client.get("/api/history").json()["jobs"][0]["id"], job_id)
            self.assertEqual(self.client.put("/api/library/private.png/feedback", json={"rating": 1, "note": "warm light"}).status_code, 200)
            self.client.post("/api/director/concepts", json={"idea": "a mountain"})
            payload = json.loads(self.llm_client.return_value.__enter__.return_value.post.call_args.kwargs["json"]["messages"][1]["content"])
            self.assertEqual(payload["personal_context"]["feedback_examples"][0]["note"], "warm light")
            other = TestClient(studio.app, base_url="http://127.0.0.1")
            other.post("/api/auth/register", json={"username": "private2", "password": "test-password"})
            for route in [f"/api/jobs/{job_id}", f"/api/images/{job_id}", "/api/library/private.png"]:
                self.assertEqual(other.get(route).status_code, 404)
            self.assertEqual(other.put("/api/library/private.png/feedback", json={"rating": -1}).status_code, 404)
            self.assertEqual(other.get("/api/history").json()["jobs"], [])
            self.assertEqual(other.get("/api/profile").json()["profile"]["style"], "")
            self.client.delete("/api/profile/feedback")
            self.client.post("/api/director/concepts", json={"idea": "a mountain"})
            payload = json.loads(self.llm_client.return_value.__enter__.return_value.post.call_args.kwargs["json"]["messages"][1]["content"])
            self.assertEqual(payload["personal_context"]["feedback_examples"], [])

    def test_llm_review_failure_blocks_saved_brief_generation(self):
        invalid = httpx.Response(200, json={"message": {"content": "{}"}}, request=httpx.Request("POST", "http://localhost/api/chat"))
        self.llm_client.return_value.__enter__.return_value.post.side_effect = None
        self.llm_client.return_value.__enter__.return_value.post.return_value = invalid
        with patch.object(studio.SERVICE, "generate") as generate:
            self.assertEqual(self.submit_image({"prompt": "cat"}).status_code, 502)
            generate.assert_not_called()
        self.assertFalse(studio.DIRECTOR_GUARD.locked())

    def test_library_lists_saved_images_and_rejects_paths_outside_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            outputs.mkdir()
            path = outputs / "saved.png"
            Image.new("RGB", (256, 256), "blue").save(path)
            path.with_suffix(".json").write_text('{"prompt":"A blue cat","width":256,"height":256}', encoding="utf-8")
            user_id = self.client.get("/api/auth/session").json()["user"]["id"]
            studio.storage.store_image(path.name, path.read_bytes(), {"prompt": "A blue cat", "width": 256, "height": 256}, user_id)
            data = self.client.get("/api/assets").json()
            self.assertEqual(data["images"][0]["prompt"], "A blue cat")
            self.assertEqual(self.client.get("/api/assets/saved.png").content, path.read_bytes())
            self.assertEqual(self.client.get("/api/assets/missing.png").status_code, 404)
            self.assertEqual(self.client.get("/api/assets/..%5csecret.png").status_code, 404)

    def test_library_contains_only_featured_prompts(self):
        payload = self.client.get("/api/library").json()
        self.assertNotIn("images", payload)
        self.assertGreater(len(payload["prompts"]), 0)
        self.assertEqual({item["feature"] for item in payload["prompts"]}, {"text-to-image", "text-to-video"})
        self.assertTrue(all(item["title"] and item["prompt"] for item in payload["prompts"]))


if __name__ == "__main__":
    unittest.main()

import json
import os
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from azurai import director


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AZURAI_DIRECTOR_MODEL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_templates_are_explicit_and_rotate_without_losing_idea(self):
        idea = director.Idea(idea="Một người đàn ông không bỏ cuộc", aspect="tall")
        result = director.develop(idea)
        self.assertEqual(result["provider"], "templates")
        self.assertEqual(len(result["concepts"]), 3)
        self.assertTrue(all(c["idea"] == idea.idea and c["aspect"] == "tall" for c in result["concepts"]))
        second = director.develop(idea.model_copy(update={"previous_titles": [c["title"] for c in result["concepts"]]}))
        self.assertFalse({c["title"] for c in result["concepts"]} & {c["title"] for c in second["concepts"]})

    def test_compile_camera_edit_preserves_other_semantics(self):
        brief = director.template_concepts(director.Idea(idea="a red perfume bottle"))[0]
        original = director.compile_prompt(brief)
        edited = brief.model_copy(update={"angle": "low angle"})
        output = director.compile_prompt(edited)
        self.assertTrue(output["prompt"].startswith("a red perfume bottle"))
        self.assertEqual(output["prompt"], original["prompt"].replace("eye level", "low angle"))
        self.assertEqual(output["negative"], original["negative"])
        self.assertEqual(brief.angle, "eye level")

    def test_blank_unknown_and_oversized_fields_are_rejected(self):
        for idea in ["", "   ", "x" * 1501]:
            with self.assertRaises(ValidationError):
                director.Idea(idea=idea)
        brief = director.template_concepts(director.Idea(idea="cat"))[0].model_dump()
        for change in [{"camera": "unexpected"}, {"subject": " "}, {"scene": "x" * 301}]:
            with self.assertRaises(ValidationError):
                director.Brief.model_validate({**brief, **change})

    def test_ollama_structured_output_and_server_owned_idea(self):
        idea = director.Idea(idea="một con mèo", aspect="tall")
        concepts = [c.model_dump() for c in director.template_concepts(idea)]
        for c in concepts:
            c["idea"] = "hallucinated idea"
            c["aspect"] = "wide"
        response = httpx.Response(200, json={"message": {"content": json.dumps({"concepts": concepts})}})
        response.request = httpx.Request("POST", "http://localhost/api/chat")
        with patch.dict(os.environ, {"AZURAI_DIRECTOR_MODEL": "test-model"}), patch("azurai.director.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response
            result = director.develop(idea)
            self.assertEqual(result["provider"], "ollama")
            self.assertTrue(all(c["idea"] == idea.idea and c["aspect"] == "tall" for c in result["concepts"]))
            payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
            self.assertEqual(payload["keep_alive"], 0)
            self.assertFalse(payload["stream"])
            self.assertIn("properties", payload["format"])

    def test_invalid_llm_response_is_error_not_silent_template_fallback(self):
        response = httpx.Response(200, json={"message": {"content": '{"concepts": []}'}})
        response.request = httpx.Request("POST", "http://localhost/api/chat")
        with patch.dict(os.environ, {"AZURAI_DIRECTOR_MODEL": "test-model"}), patch("azurai.director.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response
            with self.assertRaises(director.DirectorError):
                director.develop(director.Idea(idea="cat"))

    def test_remote_endpoint_is_rejected(self):
        with patch.dict(os.environ, {"AZURAI_DIRECTOR_MODEL": "test-model", "AZURAI_DIRECTOR_URL": "http://example.com"}):
            with self.assertRaises(director.DirectorError):
                director.develop(director.Idea(idea="cat"))


if __name__ == "__main__":
    unittest.main()

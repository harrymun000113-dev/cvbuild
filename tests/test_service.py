import json
import unittest
from unittest.mock import patch
import httpx2 as httpx
from openai import OpenAI
import service

KEY = "sk-" + "mock-only" * 5

def response_body(status="completed", text="경험을 바탕으로 작성한 테스트 결과입니다."):
    return {"id": "resp_test", "object": "response", "created_at": 1,
            "status": status, "model": "gpt-4.1-mini", "error": None,
            "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
            "output": [{"id": "msg_test", "type": "message", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}

class ServiceTests(unittest.TestCase):
    def client(self, handler):
        return OpenAI(api_key=KEY, base_url="https://api.openai.com/v1", max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    def test_real_sdk_payload_and_usage(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, json=response_body())
        with patch("service.client_for", return_value=self.client(handler)):
            result = service.generate(KEY, "system rules", "user data", 1800)
        self.assertEqual(len(seen), 1)
        payload = json.loads(seen[0].content)
        self.assertEqual(seen[0].url.path, "/v1/responses")
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["max_output_tokens"], 1800)
        self.assertEqual(payload["instructions"], "system rules")
        self.assertNotIn(KEY, seen[0].content.decode())
        self.assertEqual(result.input_tokens, 100)
        self.assertFalse(result.incomplete)
    def test_partial_response(self):
        with patch("service.client_for", return_value=self.client(lambda r: httpx.Response(200, json=response_body("incomplete")))):
            self.assertTrue(service.generate(KEY, "s", "u", 1800).incomplete)
    def test_safe_errors_and_no_retries(self):
        for status in [400, 401, 403, 404, 429, 500]:
            with self.subTest(status=status):
                seen = []
                def handler(req):
                    seen.append(req)
                    return httpx.Response(status, json={"error": {"message": KEY, "type": "error", "code": "insufficient_quota" if status == 429 else "error"}})
                with patch("service.client_for", return_value=self.client(handler)):
                    with self.assertRaises(service.ServiceError) as caught:
                        service.generate(KEY, "s", "u", 1800)
                self.assertNotIn(KEY, str(caught.exception))
                self.assertEqual(len(seen), 1)
    def test_timeout_safe(self):
        def handler(req):
            raise httpx.ReadTimeout(KEY, request=req)
        with patch("service.client_for", return_value=self.client(handler)):
            with self.assertRaisesRegex(service.ServiceError, "시간이 초과"):
                service.generate(KEY, "s", "u", 1800)
    def test_empty_result(self):
        with patch("service.client_for", return_value=self.client(lambda r: httpx.Response(200, json=response_body(text="")))):
            with self.assertRaisesRegex(service.ServiceError, "텍스트 결과"):
                service.generate(KEY, "s", "u", 1800)
    def test_key_validation_uses_only_model_endpoint(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, json={"id": "gpt-4.1-mini", "object": "model", "created": 1, "owned_by": "openai"})
        with patch("service.client_for", return_value=self.client(handler)):
            service.check_key(KEY)
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].url.path, "/v1/models/gpt-4.1-mini")

if __name__ == "__main__": unittest.main()

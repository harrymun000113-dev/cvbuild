import json
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
import httpx2 as httpx
from openai import OpenAI
from streamlit.testing.v1 import AppTest
from pathlib import Path
from feedback import Review, review_prompts, split_sentences, verify_alignment, highlight_html, stats
from service import analyze_review, ReviewResult, ServiceError
from test_service import response_body, KEY

TEXT = "팀원들과 구매 내역을 정리했습니다. 저는 무한한 열정으로 최고의 시너지를 창출하겠습니다."

def report(n=2):
    return Review.model_validate({"summary": "경험의 행동은 명확하지만 마지막 다짐을 구체화하세요.",
        "strengths": ["본인의 행동이 드러납니다."], "priorities": ["추상적 다짐을 구체적으로 쓰세요."],
        "scores": {"clarity": 20, "specificity": 15, "structure": 20, "naturalness": 18},
        "sentences": [{"id": i, "ai_like": i == 2, "awkward": False,
                       "reason": "추상적인 다짐입니다." if i == 2 else "행동이 명확합니다.",
                       "rewrite": "구매 내역을 정리한 경험을 업무에 활용하겠습니다." if i == 2 else ""} for i in range(1, n + 1)]})

class FeedbackTests(unittest.TestCase):
    def test_offsets_duplicates_decimals_and_newlines(self):
        text = '  [경험]\n3.5%를 줄였습니다. 같은 문장입니다. 같은 문장입니다.\n끝'
        parts = split_sentences(text)
        self.assertEqual(len(parts), 5)
        self.assertEqual(parts[1].text, '3.5%를 줄였습니다.')
        self.assertEqual(parts[2].text, parts[3].text)
        self.assertNotEqual(parts[2].start, parts[3].start)
        self.assertTrue(all(text[p.start:p.end] == p.text for p in parts))
    def test_boundaries_and_secrets(self):
        for text in ["", "짧다", "가" * 4001, "문장입니다. " * 41, TEXT + KEY]:
            with self.assertRaises(ValueError): review_prompts(text, {})
        system, user, sentences = review_prompts(TEXT, {})
        self.assertNotIn(TEXT, system)
        self.assertEqual(len(sentences), 2)
    def test_alignment_and_score(self):
        r = report()
        self.assertEqual(stats(r), (73, 50.0, 1))
        verify_alignment(r, split_sentences(TEXT))
        r.sentences[1].id = 1
        with self.assertRaises(ValueError): verify_alignment(r, split_sentences(TEXT))
    def test_safe_highlight_preserves_original(self):
        text = '<script>alert("x")</script> 테스트 문장입니다. 두 번째 문장입니다.'
        r = report()
        r.sentences[1].reason = '\" onmouseover=\"alert(1)'
        result = highlight_html(text, split_sentences(text), r)
        self.assertNotIn('<script>', result)
        self.assertIn('&lt;script&gt;', result)
        class Parser(HTMLParser):
            def __init__(self): super().__init__(); self.text = ''; self.attrs = []
            def handle_data(self, data): self.text += data
            def handle_starttag(self, tag, attrs): self.attrs.extend(k for k,v in attrs)
        p = Parser(); p.feed(result)
        self.assertEqual(p.text, text)
        self.assertNotIn('onmouseover', p.attrs)
    def test_structured_sdk_request_and_incomplete(self):
        for status in ["completed", "incomplete"]:
            requests = []
            def handler(req):
                requests.append(req)
                return httpx.Response(200, json=response_body(status, report().model_dump_json()))
            client = OpenAI(api_key=KEY, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
            with patch('service.client_for', return_value=client):
                if status == "completed":
                    result = analyze_review(KEY, 'rules', 'data', 7000, split_sentences(TEXT))
                    self.assertEqual(stats(result.review)[0], 73)
                else:
                    with self.assertRaises(ServiceError): analyze_review(KEY, 'rules', 'data', 7000, split_sentences(TEXT))
            payload = json.loads(requests[0].content)
            self.assertEqual(payload['text']['format']['type'], 'json_schema')
            self.assertIs(payload['store'], False)
    def test_bad_alignment_fails_closed(self):
        client = OpenAI(api_key=KEY, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response_body(text=report(1).model_dump_json())))))
        with patch('service.client_for', return_value=client):
            with self.assertRaisesRegex(ServiceError, '형식'):
                analyze_review(KEY, 's', 'u', 7000, split_sentences(TEXT))
    def test_ui_submit_stale_and_reset(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
        self.assertFalse(app.exception)
        with patch('feedback_ui.analyze_review', return_value=ReviewResult(report(), 200, 300)) as call:
            app.text_area(key='feedback_text').input(TEXT).run()
            self.assertEqual(call.call_count, 0)
            app.text_input(key='api_key').input(KEY).run()
            app.checkbox(key='feedback_consent').check().run()
            next(b for b in app.button if b.label == '피드백 분석').click().run()
            self.assertEqual(call.call_count, 1)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 3)
            app.text_area(key='feedback_text').input(TEXT + ' 원문을 고쳤습니다.').run()
            self.assertEqual(call.call_count, 1)
            self.assertEqual(len(app.metric), 0)
            self.assertTrue(any('입력이 바뀌었습니다' in w.value for w in app.warning))
            next(b for b in app.button if b.label == '전체 초기화 · 키 삭제').click().run()
            self.assertEqual(app.text_area(key='feedback_text').value, '')
            self.assertEqual(app.session_state['budget'].calls, 1)
            self.assertFalse(app.exception)

if __name__ == '__main__': unittest.main()

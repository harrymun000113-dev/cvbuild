import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from service import Generation, ServiceError

APP = Path(__file__).resolve().parents[1] / "app.py"

def button(app, label):
    return next(b for b in app.button if b.label == label)

class AppTests(unittest.TestCase):
    def start(self):
        app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        return app
    def test_cards_and_validation(self):
        app = self.start()
        button(app, "기업 특성 분석").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(button(app, "분석 시작하기").disabled)
        self.assertEqual(app.session_state["feature"], "company-analysis")
    def test_generate_edit_switch_reset(self):
        app = self.start()
        button(app, "예시 경험 불러오기").click().run()
        app.text_input(key="api_key").input("sk-" + "mock-only" * 5).run()
        app.checkbox(key="consent").check().run()
        with patch("service.generate", return_value=Generation("검증용 결과입니다.", 100, 30, False)) as call:
            button(app, "분석 시작하기").click().run()
            self.assertEqual(call.call_count, 1)
        self.assertFalse(app.exception)
        self.assertIn("ksa-evaluation", app.session_state["results"])
        app.text_area(key="edited_ksa-evaluation").input("수정한 결과").run()
        self.assertIn("수정한 결과", [c.value for c in app.code])
        button(app, "직무 KSA 분석").click().run()
        self.assertEqual(app.text_input(key="role").value, "구매 직무")
        button(app, "KSA 기반 역량평가").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.text_area(key="edited_ksa-evaluation").value, "수정한 결과")
        button(app, "전체 초기화 · 키 삭제").click().run()
        self.assertEqual(app.text_input(key="api_key").value, "")
        self.assertEqual(app.session_state["budget"].calls, 1)
        self.assertEqual(app.session_state["results"], {})
    def test_error_retains_reservation(self):
        app = self.start()
        button(app, "예시 경험 불러오기").click().run()
        app.text_input(key="api_key").input("sk-" + "mock-only" * 5).run()
        app.checkbox(key="consent").check().run()
        with patch("service.generate", side_effect=ServiceError("인증 오류")):
            button(app, "분석 시작하기").click().run()
        self.assertFalse(app.exception)
        self.assertGreater(app.session_state["budget"].charged, 0)
        self.assertFalse(app.session_state["busy"])
        self.assertEqual(app.session_state["results"], {})

if __name__ == "__main__": unittest.main()

import unittest
from core import FEATURES, FIELDS, Budget, build_prompts, validate, validate_key, char_count, reserve_cost

def valid_data():
    return dict(role="구매", company="가상 기업", sources="[공식 자료, 2026-09] 제공된 본문",
                experience="행사 물품 구매를 담당했다.", problem="납기 지연을 줄이기", char_limit=700)

class CoreTests(unittest.TestCase):
    def test_all_templates_build_with_role_and_data_separate(self):
        for f in FEATURES:
            with self.subTest(feature=f.id):
                system, user = build_prompts(f.id, valid_data())
                self.assertIn("[기능별 원문 템플릿]", system)
                self.assertNotIn("행사 물품 구매를 담당했다.", system)
                self.assertIn("행사 물품 구매를 담당했다.", user)
    def test_required_and_unknown(self):
        for feature, data in [("unknown", valid_data()), ("job-ksa", {}),
                              ("company-analysis", dict(role="구매", company="기업")),
                              ("mckinsey-7step", dict(role="구매")),
                              ("growth-story", dict(role="구매"))]:
            with self.assertRaises(ValueError): validate(feature, data)
    def test_limits_and_secret_exclusion(self):
        for changes in [dict(char_limit=0), dict(char_limit=True), dict(role="가" * 101),
                        dict(draft="sk-" + "x" * 30)]:
            with self.assertRaises(ValueError): validate("job-ksa", valid_data() | changes)
        data = {k: "가" * limit for k, (_, limit) in FIELDS.items()}
        with self.assertRaises(ValueError): validate("job-ksa", data)
    def test_key_is_not_in_prompt_even_if_extra_field(self):
        key = "sk-" + "test" * 10
        self.assertEqual(validate_key(" " + key + " "), key)
        for invalid in ["", "abc", "sk-" + "x " * 30]:
            with self.assertRaises(ValueError): validate_key(invalid)
        system, user = build_prompts("job-ksa", valid_data() | {"api_key": key})
        self.assertNotIn(key, system + user)
    def test_budget_failures_do_not_release_reservation(self):
        b = Budget()
        b.reserve(.02, .05, now=10)
        with self.assertRaises(ValueError): b.reserve(.02, .05, now=11)
        with self.assertRaises(ValueError): b.reserve(.04, .05, now=20)
        self.assertEqual(b.calls, 1)
        b.settle(.02, .005)
        self.assertAlmostEqual(b.charged, .005)
        b.calls = 20
        with self.assertRaises(ValueError): b.reserve(.001, .05, now=30)
    def test_count_and_cost(self):
        self.assertEqual(char_count("가 나\n다"), 5)
        self.assertEqual(char_count("가 나\n다", False), 3)
        self.assertGreater(reserve_cost("가" * 100, "", 100), reserve_cost("a" * 100, "", 100))

if __name__ == "__main__": unittest.main()

"""Pure validation, prompt assembly and conservative session spending controls."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import re
import time

ROOT = Path(__file__).resolve().parent
MODEL = "gpt-4.1-mini"
INPUT_PRICE = 0.40  # USD / million tokens; checked 2026-09-16
OUTPUT_PRICE = 1.60
MAX_INPUT_CHARS = 12000
MAX_CALLS = 20
COOLDOWN = 5

@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    description: str
    essay: bool = False

FEATURES = [
    Feature("ksa-evaluation", "KSA 기반 역량평가", "경험을 지식·기술·태도로 해석"),
    Feature("job-ksa", "직무 KSA 분석", "직무에 필요한 역량과 준비 방법"),
    Feature("career-strength", "경험 → 직무 강점", "내 경험을 KPI와 STAR로 연결"),
    Feature("company-analysis", "기업 특성 분석", "출처를 바탕으로 경쟁력 비교"),
    Feature("okr", "OKR · 입사 후 포부", "측정 가능한 목표와 실행 방향"),
    Feature("growth-story", "성장과정", "가치관에서 직무로 이어지는 이야기", True),
    Feature("personality", "성격의 장단점", "강점의 증거와 약점의 보완 노력", True),
    Feature("job-experience", "직무수행 경험", "행동과 기여가 드러나는 경험", True),
    Feature("motivation", "지원동기 및 입사 후 포부", "지원 계기와 실행 가능한 미래", True),
    Feature("mckinsey-7step", "맥킨지 7STEP", "문제 정의부터 실행 계획까지"),
]
BY_ID = {f.id: f for f in FEATURES}
FIELDS = {
    "role": ("지원 직무", 100), "company": ("지원 기업", 100),
    "question": ("자소서 문항", 1000), "url": ("기업 홈페이지 URL", 500),
    "sources": ("기업 자료 · 출처", 5000), "experience": ("추가 경험", 2500),
    "situation": ("상황", 1000), "task": ("과제", 1000),
    "action": ("행동", 2000), "result": ("결과", 1000),
    "contribution": ("나의 기여", 1000), "values": ("가치관", 500),
    "keywords": ("성격 · 핵심 역량 키워드", 500),
    "weakness": ("약점과 보완 노력", 1000), "motivation": ("지원 계기", 1000),
    "goals": ("입사 후 목표", 1000), "problem": ("해결할 문제", 2000),
    "draft": ("기존 자기소개서", 4000),
}

def validate_key(key: str) -> str:
    key = key.strip()
    # No fixed key length: OpenAI key formats can change.
    if not key.startswith("sk-") or not 20 <= len(key) <= 512 or re.search(r"\s", key):
        raise ValueError("sk-로 시작하는 API 키를 공백 없이 입력하세요. 실제 권한은 연결 시 확인합니다.")
    return key

def validate(feature_id: str, data: dict) -> dict:
    if feature_id not in BY_ID:
        raise ValueError("지원하지 않는 기능입니다.")
    clean = {}
    for key, (label, limit) in FIELDS.items():
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{label}: 최대 {limit:,}자까지 입력하세요.")
        if re.search(r"sk-[A-Za-z0-9_-]{16,}", value):
            raise ValueError("본문에 API 키로 보이는 값이 있습니다. 삭제한 후 다시 시도하세요.")
        clean[key] = value.strip()
    if sum(map(len, clean.values())) > MAX_INPUT_CHARS:
        raise ValueError(f"전체 입력은 {MAX_INPUT_CHARS:,}자 이내로 줄여 주세요.")
    n = data.get("char_limit", 700)
    if type(n) is not int or not 200 <= n <= 3000:
        raise ValueError("글자 수는 200~3,000 사이의 정수여야 합니다.")
    if not clean["role"]:
        raise ValueError("지원 직무를 입력하세요.")
    if feature_id in {"company-analysis", "okr", "motivation"} and not clean["company"]:
        raise ValueError("이 기능은 지원 기업을 입력해야 합니다.")
    if feature_id == "company-analysis" and not clean["sources"]:
        raise ValueError("기업 자료 본문과 출처를 붙여 넣으세요. URL만으로는 분석하지 않습니다.")
    if feature_id == "mckinsey-7step" and not clean["problem"]:
        raise ValueError("해결할 문제를 입력하세요.")
    if feature_id in {"ksa-evaluation", "career-strength", "growth-story", "personality", "job-experience", "motivation"}:
        if not any(clean[k] for k in ["experience", "situation", "action", "draft"]):
            raise ValueError("경험, STAR 항목 또는 기존 자기소개서를 입력하세요.")
    clean["char_limit"] = n
    clean["include_spaces"] = bool(data.get("include_spaces", True))
    return clean

def build_prompts(feature_id: str, data: dict) -> tuple[str, str]:
    clean = validate(feature_id, data)
    feature = BY_ID[feature_id]
    common = (ROOT / "prompts/system.md").read_text(encoding="utf-8")
    template = (ROOT / f"prompts/{feature_id}.md").read_text(encoding="utf-8")
    system = common + "\n\n[기능별 원문 템플릿]\n" + template
    payload = {FIELDS[k][0]: v for k, v in clean.items() if k in FIELDS and v}
    payload["글자 수 상한" if feature.essay else "참고 분량"] = clean["char_limit"]
    payload["글자 수 기준"] = "공백·줄바꿈 포함" if clean["include_spaces"] else "모든 공백·줄바꿈 제외"
    user = "아래 JSON의 값으로 템플릿의 예시 자리표시자를 대체해 작성하세요. 빈 정보는 추측하지 마세요.\n" + json.dumps(payload, ensure_ascii=False)
    return system, user

def output_cap(feature_id: str, char_limit: int) -> int:
    return min(6000, max(1800, char_limit * 3)) if BY_ID[feature_id].essay else 4500

def reserve_cost(system: str, user: str, cap: int) -> float:
    # UTF-8 bytes is a deliberately high token estimate, plus message overhead.
    inputs = len((system + user).encode("utf-8")) + 512
    return (inputs * INPUT_PRICE + cap * OUTPUT_PRICE) / 1_000_000

def actual_cost(input_tokens: int, output_tokens: int) -> float:
    # Cached inputs counted at full price: conservative display.
    return (input_tokens * INPUT_PRICE + output_tokens * OUTPUT_PRICE) / 1_000_000

def char_count(text: str, include_spaces: bool = True) -> int:
    return len(text) if include_spaces else len(re.sub(r"\s", "", text))

@dataclass
class Budget:
    charged: float = 0.0
    calls: int = 0
    last_call: float = -100.0
    def reserve(self, amount: float, limit: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.calls >= MAX_CALLS:
            raise ValueError("이번 세션의 생성·검사 합계 20회 한도에 도달했습니다.")
        if now - self.last_call < COOLDOWN:
            raise ValueError("연속 요청을 막기 위해 5초 후 다시 시도하세요.")
        if self.charged + amount > limit:
            raise ValueError("예상 사용량이 세션 예산을 초과합니다. 분량을 줄이거나 예산을 조정하세요.")
        self.charged += amount
        self.calls += 1
        self.last_call = now
    def settle(self, reserved: float, actual: float) -> None:
        self.charged = max(0, self.charged - reserved + actual)

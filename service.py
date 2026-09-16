"""Request-scoped OpenAI client. No credentials, payloads or errors are logged."""
from dataclasses import dataclass
import httpx2 as httpx
from openai import OpenAI, AuthenticationError, PermissionDeniedError, RateLimitError
from openai import APITimeoutError, APIConnectionError, APIStatusError
from core import MODEL, validate_key
from feedback import Review, verify_alignment

@dataclass
class Generation:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    incomplete: bool

class ServiceError(Exception):
    pass

@dataclass
class ReviewResult:
    review: Review
    input_tokens: int | None
    output_tokens: int | None

def analyze_review(key: str, system: str, user: str, cap: int, sentences) -> ReviewResult:
    try:
        with client_for(key) as client:
            response = client.responses.create(
                model=MODEL, instructions=system, input=[{"role": "user", "content": user}],
                max_output_tokens=cap, store=False,
                text={"format": {"type": "json_schema", "name": "essay_review", "strict": True,
                                 "schema": Review.model_json_schema()}},
            )
        if response.status != "completed":
            raise ServiceError("피드백이 끝까지 생성되지 않았습니다. 점수는 표시하지 않습니다. 글을 줄여 다시 검사하세요.")
        if not response.output_text.strip():
            raise ServiceError("피드백을 생성하지 못했습니다. 입력을 확인해 주세요.")
        try:
            review = Review.model_validate_json(response.output_text)
            verify_alignment(review, sentences)
        except ValueError:
            raise ServiceError("문장별 피드백 형식이 올바르지 않습니다. 잘못된 점수나 하이라이트는 표시하지 않습니다.") from None
        usage = response.usage
        return ReviewResult(review, usage.input_tokens if usage else None, usage.output_tokens if usage else None)
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(error_message(exc)) from None

def client_for(key: str):
    return OpenAI(api_key=validate_key(key), base_url="https://api.openai.com/v1",
                  organization="", project="", max_retries=0,
                  timeout=httpx.Timeout(60.0, connect=10.0),
                  http_client=httpx.Client(trust_env=False))

def error_message(exc: Exception) -> str:
    if isinstance(exc, AuthenticationError):
        return "API 키 인증에 실패했습니다. 키가 만료·폐기되었는지 확인하세요."
    if isinstance(exc, PermissionDeniedError):
        return "이 키에 필요한 권한이 없습니다. 모델 및 Responses 권한을 확인하세요."
    if isinstance(exc, RateLimitError):
        if getattr(exc, "code", None) == "insufficient_quota":
            return "API 사용 한도 또는 크레딧이 부족합니다. OpenAI 결제 설정을 확인하세요."
        return "요청 한도 또는 사용 가능 금액을 확인하세요. 잠시 후 직접 다시 시도할 수 있습니다."
    if isinstance(exc, APITimeoutError):
        return "응답 시간이 초과되었습니다. 이미 처리되어 비용이 발생했을 수 있습니다. 자동 재시도하지 않습니다."
    if isinstance(exc, APIConnectionError):
        return "OpenAI에 연결하지 못했습니다. 인터넷 연결을 확인하세요."
    if isinstance(exc, APIStatusError):
        if exc.status_code == 404:
            return "선택 모델을 사용할 수 없습니다. 계정의 모델 접근 권한을 확인하세요."
        if exc.status_code >= 500:
            return "OpenAI 서비스에 일시적인 문제가 있습니다. 잠시 후 다시 시도하세요."
        return "요청이 거절되었습니다. 입력과 계정 설정을 확인하세요."
    if isinstance(exc, ValueError):
        return "API 키 형식을 확인하세요."
    return "처리 중 오류가 발생했습니다. 입력을 확인한 뒤 다시 시도하세요."

def check_key(key: str) -> None:
    try:
        with client_for(key) as client:
            client.models.retrieve(MODEL)
    except Exception as exc:
        raise ServiceError(error_message(exc)) from None

def generate(key: str, system: str, user: str, cap: int) -> Generation:
    try:
        with client_for(key) as client:
            response = client.responses.create(
                model=MODEL, instructions=system,
                input=[{"role": "user", "content": user}],
                max_output_tokens=cap, store=False,
            )
        if response.status not in {"completed", "incomplete"}:
            raise ServiceError("생성이 완료되지 않았습니다. 다시 생성하려면 직접 버튼을 눌러 주세요.")
        content = response.output_text.strip()
        if not content:
            raise ServiceError("텍스트 결과가 없습니다. 입력을 조정한 후 다시 시도하세요.")
        usage = response.usage
        return Generation(content, usage.input_tokens if usage else None,
                          usage.output_tokens if usage else None, response.status == "incomplete")
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(error_message(exc)) from None

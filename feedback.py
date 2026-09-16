"""Post-writing review, sentence alignment, safe highlighting and export."""
from dataclasses import dataclass
from html import escape
import json
import re
from pydantic import BaseModel, ConfigDict, Field
from core import ROOT, FIELDS

MAX_REVIEW_CHARS = 4000
MAX_SENTENCES = 40
REVIEW_CAP = 7000
DISCLAIMER = "AI 문체 비율은 표시된 문장 수의 비율이며, 실제 AI 작성 확률이나 표절률이 아닙니다."

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class Scores(StrictModel):
    clarity: int = Field(ge=0, le=25)
    specificity: int = Field(ge=0, le=25)
    structure: int = Field(ge=0, le=25)
    naturalness: int = Field(ge=0, le=25)

class SentenceReview(StrictModel):
    id: int
    ai_like: bool
    awkward: bool
    reason: str = Field(min_length=1, max_length=300)
    rewrite: str = Field(max_length=1500)

class Review(StrictModel):
    summary: str = Field(min_length=1, max_length=1200)
    strengths: list[str] = Field(min_length=1, max_length=3)
    priorities: list[str] = Field(min_length=1, max_length=3)
    scores: Scores
    sentences: list[SentenceReview] = Field(min_length=1, max_length=MAX_SENTENCES)

@dataclass(frozen=True)
class Sentence:
    id: int
    start: int
    end: int
    text: str

def split_sentences(text: str) -> list[Sentence]:
    # Preserve exact source offsets. Decimals/URLs are not split at internal dots.
    boundary = re.compile(r'[.!?。！？]+["\'”’」)]*(?=\s|$)|\n+')
    spans = []
    cursor = 0
    def add(start, end):
        while start < end and text[start].isspace(): start += 1
        while end > start and text[end - 1].isspace(): end -= 1
        if start < end:
            spans.append(Sentence(len(spans) + 1, start, end, text[start:end]))
    for match in boundary.finditer(text):
        add(cursor, match.end())
        cursor = match.end()
    add(cursor, len(text))
    return spans

def review_prompts(text: str, context: dict) -> tuple[str, str, list[Sentence]]:
    if not isinstance(text, str) or not 30 <= len(text.strip()) <= MAX_REVIEW_CHARS or len(text) > MAX_REVIEW_CHARS:
        raise ValueError("완성한 자소서를 30~4,000자로 입력하세요.")
    clean = {}
    for key in ("role", "company", "question"):
        value = context.get(key, "")
        if not isinstance(value, str) or len(value) > FIELDS[key][1]:
            raise ValueError("직무·기업·문항의 입력 길이를 확인하세요.")
        clean[FIELDS[key][0]] = value
    if re.search(r"sk-[A-Za-z0-9_-]{16,}", text + json.dumps(clean)):
        raise ValueError("본문에 API 키로 보이는 값이 있습니다. 삭제해 주세요.")
    sentences = split_sentences(text)
    if not sentences or len(sentences) > MAX_SENTENCES:
        raise ValueError("한 번에 최대 40개 문장·소제목을 검사할 수 있습니다. 글을 나누어 입력하세요.")
    system = (ROOT / "prompts/feedback.md").read_text(encoding="utf-8")
    user = json.dumps({"맥락": clean, "문장": [{"id": s.id, "text": s.text} for s in sentences]}, ensure_ascii=False)
    return system, user, sentences

def verify_alignment(review: Review, sentences: list[Sentence]) -> None:
    if [s.id for s in review.sentences] != [s.id for s in sentences]:
        raise ValueError("문장별 결과가 원문과 일치하지 않습니다.")
    if any((s.ai_like or s.awkward) and not s.rewrite.strip() for s in review.sentences):
        raise ValueError("수정 제안이 누락되었습니다.")

def stats(review: Review) -> tuple[int, float, int]:
    total = sum(review.scores.model_dump().values())
    ai = sum(s.ai_like for s in review.sentences)
    issues = sum(s.ai_like or s.awkward for s in review.sentences)
    return total, round(ai / len(review.sentences) * 100, 1), issues

def label(item: SentenceReview) -> str:
    if item.ai_like and item.awkward: return "AI 문체 · 어색한 표현"
    if item.ai_like: return "AI 문체"
    if item.awkward: return "어색한 표현"
    return "표시할 문제 없음"

def highlight_html(text: str, sentences: list[Sentence], review: Review) -> str:
    verify_alignment(review, sentences)
    chunks = []
    cursor = 0
    for sentence, item in zip(sentences, review.sentences):
        chunks.append(escape(text[cursor:sentence.start]))
        color = "#EDE1FA" if item.ai_like and item.awkward else "#FFF0BE" if item.ai_like else "#FFDDE1" if item.awkward else "transparent"
        tooltip = escape(f"문장 {sentence.id} · {label(item)}: {item.reason}", quote=True)
        chunks.append(f'<mark style="background:{color};color:#20352D;border-radius:4px;padding:2px 0" title="{tooltip}">{escape(sentence.text)}</mark>')
        cursor = sentence.end
    chunks.append(escape(text[cursor:]))
    return '<div style="white-space:pre-wrap;overflow-wrap:anywhere;line-height:2.2;font-size:16px;padding:22px;border:1px solid #DDE5DC;border-radius:12px;background:#FFF">' + ''.join(chunks) + '</div>'

def export_review(text: str, review: Review, sentences: list[Sentence]) -> str:
    total, ratio, issues = stats(review)
    parts = ["# 자소서 피드백", DISCLAIMER, f"글쓰기 참고 점수: {total}/100 · AI 문체 표시 문장 비율: {ratio}% · 개선 표시: {issues}개", review.summary,
             "## 잘된 점", *review.strengths, "## 우선 개선점", *review.priorities, "## 검토 원문", text, "## 문장별 피드백"]
    for source, item in zip(sentences, review.sentences):
        parts += [f"### 문장 {item.id} · {label(item)}", source.text, f"이유: {item.reason}"]
        if item.rewrite: parts.append(f"수정 제안: {item.rewrite}")
    return '\n\n'.join(parts)

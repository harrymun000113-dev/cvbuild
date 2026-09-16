import json
import streamlit as st
from core import validate_key, reserve_cost, actual_cost
from feedback import Review, REVIEW_CAP, DISCLAIMER, review_prompts, stats, label, highlight_html, export_review
from service import analyze_review, ServiceError

def render_feedback():
    ss = st.session_state
    st.subheader("완성한 자소서, 제출 전에 한 번 더")
    st.write("글을 모두 작성한 뒤 붙여 넣고 **피드백 분석**을 눌러 주세요. 입력 중에는 유료 검사를 실행하지 않습니다.")
    st.info(DISCLAIMER + " 사람이 쓴 글도 표시될 수 있습니다.")
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        def load_text(value):
            ss.feedback_text = value
            ss.pop("feedback_saved", None)
        a, b = st.columns(2)
        a.button("기존 자소서 가져오기", on_click=load_text, args=(ss.get("draft", ""),), disabled=not ss.get("draft"), width="stretch")
        saved = ss.results.get(ss.feature)
        current = ss.get(f"edited_{ss.feature}", saved.get("edited", saved["answer"].text) if saved else "")
        b.button("현재 결과 가져오기", on_click=load_text, args=(current,), disabled=not current, width="stretch")
        text = st.text_area("완성한 자기소개서", key="feedback_text", max_chars=4000, height=350,
                            placeholder="직접 작성했거나 생성 후 수정한 최종 자소서를 여기에 붙여 넣으세요.")
        st.caption(f"{len(text):,} / 4,000자 · 최대 40개 문장·소제목 · 가져오기는 이 입력을 교체합니다.")
        context = {k: ss.get(k, "") for k in ("role", "company", "question")}
        st.caption("작성 탭의 직무·기업·문항을 함께 참고합니다. 비어 있어도 표현 피드백은 가능합니다.")
        system = user = ""
        sentences = []
        error = ""
        try:
            system, user, sentences = review_prompts(text, context)
        except ValueError as exc:
            error = str(exc)
        # Include the schema in the conservative input reservation.
        estimate = reserve_cost(system + json.dumps(Review.model_json_schema()), user, REVIEW_CAP)
        if error:
            st.caption(error)
        else:
            st.caption(f"검토 단위 {len(sentences)}개 · 보수적 예상 비용 ${estimate:.4f} · 생성과 세션 예산 공유")
        st.checkbox("이 자소서의 OpenAI 전송과 유료 피드백에 동의합니다.", key="feedback_consent")
        disabled = bool(error) or not ss.get("api_key") or not ss.get("feedback_consent") or ss.busy
        go, clear = st.columns(2)
        clicked = go.button("피드백 분석", type="primary", disabled=disabled, width="stretch")
        clear.button("피드백 초기화", on_click=load_text, args=("",), width="stretch")
        if clicked:
            reserved = False
            try:
                key = validate_key(ss.api_key)
                ss.budget.reserve(estimate, ss.budget_limit)
                reserved = True
                ss.busy = True
                with st.spinner("문장별 표현과 개선 방향을 검토하고 있어요…"):
                    result = analyze_review(key, system, user, REVIEW_CAP, sentences)
                cost = estimate
                if result.input_tokens is not None and result.output_tokens is not None:
                    cost = actual_cost(result.input_tokens, result.output_tokens)
                    ss.budget.settle(estimate, cost)
                ss.feedback_saved = {"text": text, "context": context, "sentences": sentences, "result": result, "cost": cost}
                ss.busy = False
                st.rerun()
            except (ValueError, ServiceError) as exc:
                st.error(str(exc))
                if reserved:
                    st.caption("이전 피드백은 유지됩니다. 불확실한 요청의 예상 비용은 예산에 남깁니다.")
            finally:
                ss.busy = False
    with right:
        saved = ss.get("feedback_saved")
        if not saved:
            with st.container(border=True):
                st.markdown("### 어디를 고치면 좋을까요?")
                st.write("총평과 글쓰기 점수, 문장별 이유와 수정 제안을 한곳에서 확인하세요.")
                st.caption("노랑: AI 문체 · 분홍: 어색한 표현 · 보라: 두 항목 모두")
            return
        if saved["text"] != text or saved["context"] != context:
            st.warning("검사 후 입력이 바뀌었습니다. 현재 글의 점수·하이라이트는 아직 없습니다. 피드백 분석을 다시 눌러 주세요.")
            with st.expander("이전 검사 보고서 보관"):
                st.download_button("이전 피드백 다운로드", export_review(saved["text"], saved["result"].review, saved["sentences"]), "previous-feedback.md", "text/markdown", on_click="ignore")
            return
        review = saved["result"].review
        score, ratio, issues = stats(review)
        a, b, c = st.columns(3)
        a.metric("글쓰기 참고 점수", f"{score}/100")
        b.metric("AI 문체 문장 비율", f"{ratio:g}%")
        c.metric("개선 표시 문장", f"{issues}/{len(saved['sentences'])}")
        st.caption(f"AI 문체 표시 {sum(s.ai_like for s in review.sentences)}개 ÷ 전체 검토 단위 {len(review.sentences)}개. 소제목도 포함합니다. 채용 점수·AI 작성 확률이 아닙니다.")
        with st.expander("점수 기준 보기"):
            names = {"clarity": "명확성", "specificity": "구체성", "structure": "구조", "naturalness": "자연스러움"}
            for key, value in review.scores.model_dump().items():
                st.write(f"{names[key]}: {value}/25")
            st.caption("각 25점, 합계 100점의 주관적 문장 평가입니다. 재검사 결과는 달라질 수 있습니다.")
        st.text(review.summary)
        a, b = st.columns(2)
        with a:
            st.markdown("**잘된 점**")
            for item in review.strengths: st.text("• " + item)
        with b:
            st.markdown("**우선 개선점**")
            for item in review.priorities: st.text("• " + item)
        st.markdown("#### 문장별 하이라이트")
        st.caption("노랑: AI 문체 · 분홍: 어색한 표현 · 보라: 둘 다 · 무색: 표시할 문제 없음")
        # All original text and model explanations are escaped by highlight_html.
        st.markdown(highlight_html(saved["text"], saved["sentences"], review), unsafe_allow_html=True)
        st.caption("문장 위에 마우스를 올리면 이유가 보입니다. 아래 상세 피드백은 모바일에서도 확인할 수 있습니다.")
        for source, item in zip(saved["sentences"], review.sentences):
            with st.expander(f"문장 {item.id} · {label(item)}", expanded=item.ai_like or item.awkward):
                st.text(source.text)
                st.text("이유: " + item.reason)
                if item.rewrite:
                    st.caption("수정 제안 · 사실관계를 확인한 뒤 직접 반영하세요.")
                    st.code(item.rewrite, language=None, wrap_lines=True)
        st.download_button("피드백 보고서 다운로드 (.md)", export_review(saved["text"], review, saved["sentences"]).encode("utf-8"), "essay-feedback.md", "text/markdown", on_click="ignore", width="stretch")
        st.caption(f"입력 {saved['result'].input_tokens} / 출력 {saved['result'].output_tokens}토큰 · 예상 비용 ${saved['cost']:.4f} · 원문은 자동 수정하지 않습니다.")

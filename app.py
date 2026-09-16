"""Career Note: a local-first, bring-your-own-key Korean writing workspace."""
import time
import streamlit as st
from core import FEATURES, BY_ID, FIELDS, MODEL, MAX_INPUT_CHARS, Budget
from core import validate, validate_key, build_prompts, output_cap, reserve_cost, actual_cost, char_count
from service import check_key, generate, ServiceError

st.set_page_config(page_title="커리어노트 · 내 경험에서 시작하는 자소서", page_icon="🌿", layout="wide")
st.markdown("""<style>
.block-container{max-width:1440px;padding-top:2.6rem;padding-bottom:4rem}
h1{letter-spacing:-.055em;font-weight:750!important} h2,h3{letter-spacing:-.035em}
[data-testid="stSidebar"]{border-right:1px solid #dde5dc}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:14px}
.eyebrow{font-size:12px;letter-spacing:.18em;color:#176c53;font-weight:700}
.hero-sub{color:#647269;font-size:17px;line-height:1.8;margin-bottom:1.8rem}
</style>""", unsafe_allow_html=True)  # Static CSS only; never interpolate user/model text.

ss = st.session_state
for key, value in {"feature": FEATURES[0].id, "budget": Budget(), "results": {},
                   "busy": False, "key_status": "", "key_check_at": -100.0,
                   "key_checks": 0, "char_limit": 700, "include_spaces": True}.items():
    if key not in ss:
        ss[key] = value

def clear_key():
    ss["api_key"] = ""
    ss["key_status"] = ""

def reset_inputs():
    # Preserve spending counters so reset is not a budget bypass.
    for key in FIELDS:
        ss[key] = ""
    for key in list(ss):
        if key.startswith("edited_"):
            del ss[key]
    ss["results"] = {}
    ss["char_limit"] = 700
    ss["include_spaces"] = True
    ss["consent"] = False
    ss["feedback_text"] = ""
    ss["feedback_consent"] = False
    ss.pop("feedback_saved", None)
    clear_key()

def select_feature(feature_id):
    ss["feature"] = feature_id

def sample():
    reset_inputs()
    ss.update({"role": "구매 직무", "company": "지원 기업명 입력",
               "situation": "교내 행사 운영팀에서 물품 구매를 담당했습니다.",
               "task": "정해진 예산 안에서 필요한 물품을 행사 전에 준비해야 했습니다.",
               "action": "품목별 필요 수량을 확인하고 업체별 견적과 납기를 표로 비교했습니다.",
               "result": "예산 범위 안에서 구매를 마쳤고 행사 전에 물품을 받았습니다.",
               "contribution": "견적 비교표를 직접 만들고 팀원들과 구매 우선순위를 정했습니다.",
               "values": "근거를 확인하고 책임 있게 결정하기", "keywords": "꼼꼼함, 비용 의식",
               "question": "지원 직무에 필요한 역량을 갖추기 위해 노력한 경험을 기술하세요."})

with st.sidebar:
    st.markdown("### 🌿 커리어노트")
    st.caption("CAREER NOTE / WRITING STUDIO")
    st.divider()
    st.markdown("**OpenAI 연결**")
    st.text_input("OpenAI API Key", type="password", key="api_key",
                  placeholder="sk-…", on_change=lambda: ss.update(key_status=""))
    st.caption("키는 실행 중 세션 메모리에서 처리하며 파일·DB에 저장하지 않습니다.")
    a, b = st.columns(2)
    if a.button("연결 확인", disabled=ss.busy, width="stretch"):
        try:
            validate_key(ss.api_key)
            if time.monotonic() - ss.key_check_at < 5:
                raise ValueError("5초 후 다시 확인해 주세요.")
            if ss.key_checks >= 20:
                raise ValueError("세션당 연결 확인 20회 한도입니다. 생성 시에도 인증을 확인합니다.")
            ss.key_check_at = time.monotonic()
            ss.key_checks += 1
            with st.spinner("연결 확인 중…"):
                check_key(ss.api_key)
            ss.key_status = "모델 조회 성공. 생성 권한·잔액은 생성 요청 시 확인합니다."
        except (ValueError, ServiceError) as exc:
            ss.key_status = ""
            st.error(str(exc))
    b.button("키 지우기", on_click=clear_key, disabled=ss.busy, width="stretch")
    if ss.key_status:
        st.success(ss.key_status)
    st.caption(f"모델: {MODEL} · 생성은 API 사용료가 발생합니다.")
    st.divider()
    st.number_input("세션 예산 (USD)", min_value=0.05, max_value=2.0,
                    value=0.50, step=0.05, key="budget_limit", disabled=ss.busy)
    st.caption(f"사용·예약 합계 ${ss.budget.charged:.4f} / 생성·검사 {ss.budget.calls}회 · 최대 20회")
    st.caption("참고 예산입니다. 새 세션에서 초기화되며 계정 전체 결제 한도를 보장하지 않습니다.")
    st.divider()
    st.button("예시 경험 불러오기", on_click=sample, disabled=ss.busy, width="stretch")
    st.caption("예시는 가상입니다. 본인 경험으로 바꾸세요. 기존 입력과 결과를 교체합니다.")
    st.button("전체 초기화 · 키 삭제", on_click=reset_inputs, disabled=ss.busy, width="stretch")
    st.caption("사용량 카운터는 유지됩니다. 필요한 결과를 먼저 다운로드하세요.")

st.markdown('<div class="eyebrow">EXPERIENCE → STRENGTH → STORY</div>', unsafe_allow_html=True)
st.title("좋은 자소서는, 내 경험에서 시작됩니다.")
st.markdown('<div class="hero-sub">직무를 이해하고, 경험의 강점을 찾고, 나다운 문장으로 정리하세요.</div>', unsafe_allow_html=True)

writing_tab, feedback_tab = st.tabs(["자소서 작성", "작성 후 검사 · 피드백"])
with writing_tab:
    st.markdown("#### 01 · 어떤 도움이 필요한가요?")
    for start in range(0, len(FEATURES), 5):
        cols = st.columns(5)
        for col, feature in zip(cols, FEATURES[start:start + 5]):
            with col:
                with st.container(border=True):
                    st.button(feature.title, key=f"choose_{feature.id}", width="stretch",
                              type="primary" if ss.feature == feature.id else "secondary",
                              on_click=select_feature, args=(feature.id,), disabled=ss.busy)
                    st.caption(feature.description)

    feature = BY_ID[ss.feature]
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.markdown("#### 02 · 나의 지원 정보")
        st.caption("지원 정보는 기능을 바꿔도 유지됩니다. 생성할 때 현재 입력을 사용합니다.")
        x, y = st.columns(2)
        x.text_input("지원 직무 *", key="role", max_chars=100, placeholder="예: 구매, 해외영업, SCM")
        y.text_input("지원 기업", key="company", max_chars=100, placeholder="예: 지원할 기업명")
        st.text_area("자소서 문항", key="question", max_chars=1000, height=90,
                     placeholder="채용 공고의 질문을 그대로 붙여 넣으세요.")
        x, y = st.columns(2)
        x.number_input("글자 수 상한 / 분석 참고 분량", min_value=200, max_value=3000, step=100, key="char_limit")
        y.checkbox("공백·줄바꿈 포함", key="include_spaces")
        tabs = st.tabs(["나의 경험", "가치관 · 포부", "기업 자료", "기존 자소서 · 문제"])
        def area(key, height=90, placeholder=None):
            label, limit = FIELDS[key]
            return st.text_area(label, key=key, max_chars=limit, height=height, placeholder=placeholder)
        with tabs[0]:
            st.caption("STAR: 상황 → 과제 → 행동 → 결과. 기억나는 항목부터 구체적으로 적으세요.")
            area("situation", placeholder="어떤 환경에서, 어떤 문제가 있었나요?")
            area("task", placeholder="무엇을 해결해야 했나요?")
            area("action", 120, "본인이 직접 한 행동과 판단 근거")
            area("result", placeholder="확인할 수 있는 결과만 적으세요. 숫자가 없어도 괜찮아요.")
            area("contribution")
            area("experience", 100, "다른 경험이나 추가 맥락")
        with tabs[1]:
            area("values")
            area("keywords")
            area("weakness")
            area("motivation")
            area("goals")
        with tabs[2]:
            st.info("웹사이트를 자동 검색하지 않습니다. 공식 자료의 본문·출처·날짜를 함께 붙여 넣어 주세요.")
            st.text_input("기업 홈페이지 URL", key="url", max_chars=500)
            area("sources", 280, "[출처명 / 발표일 / URL]\n핵심 본문…\n\n경쟁사 비교 자료도 함께 넣으면 좋습니다.")
        with tabs[3]:
            area("draft", 240, "기존 자기소개서를 붙여 넣으면 사실을 유지하며 개선합니다.")
            area("problem", 140, "7STEP 분석 대상: 현황, 목표, 기한, 제약, 확보한 데이터")

        data = {k: ss.get(k, "") for k in FIELDS}
        data.update(char_limit=int(ss.char_limit), include_spaces=ss.include_spaces)
        total = sum(len(data[k]) for k in FIELDS)
        st.caption(f"전체 입력 {total:,} / {MAX_INPUT_CHARS:,}자 · 개인정보는 제외하세요.")
        system = user = ""
        input_error = ""
        try:
            system, user = build_prompts(feature.id, data)
        except ValueError as exc:
            input_error = str(exc)
        cap = output_cap(feature.id, int(ss.char_limit))
        estimate = reserve_cost(system, user, cap) if system else 0
        if input_error:
            st.info(input_error)
        else:
            st.caption(f"이번 요청 보수적 비용 예상: ${estimate:.4f} 이하 · 최대 출력 {cap:,}토큰")
        st.checkbox("입력 내용이 OpenAI로 전송되며 API 비용이 발생하는 데 동의합니다.", key="consent")
        go, again = st.columns(2)
        disabled = ss.busy or bool(input_error) or not ss.get("api_key") or not ss.get("consent")
        run = go.button("초안 생성하기" if feature.essay else "분석 시작하기", type="primary", disabled=disabled, width="stretch")
        regen = again.button("현재 입력으로 재생성", disabled=disabled or feature.id not in ss.results, width="stretch")
        if run or regen:
            reserved = False
            try:
                key = validate_key(ss.api_key)
                ss.budget.reserve(estimate, ss.budget_limit)
                reserved = True
                ss.busy = True
                with st.spinner("경험과 직무를 연결해 문장을 정리하고 있어요…"):
                    answer = generate(key, system, user, cap)
                if answer.input_tokens is not None and answer.output_tokens is not None:
                    cost = actual_cost(answer.input_tokens, answer.output_tokens)
                    ss.budget.settle(estimate, cost)
                else:
                    cost = estimate
                ss.results[feature.id] = {"answer": answer, "cost": cost,
                                          "limit": ss.char_limit, "spaces": ss.include_spaces,
                                          "input": dict(data)}
                ss[f"edited_{feature.id}"] = answer.text
                ss.busy = False
                st.rerun()
            except (ValueError, ServiceError) as exc:
                st.error(str(exc))
                if reserved:
                    st.caption("처리 여부가 불확실한 요청도 예상 비용을 예산에 남깁니다. 기존 결과는 유지됩니다.")
            finally:
                ss.busy = False

    with right:
        st.markdown("#### 03 · 나의 결과")
        st.caption(feature.title)
        saved = ss.results.get(feature.id)
        if not saved:
            with st.container(border=True):
                st.markdown("### 경험이 문장이 되는 공간")
                st.write("왼쪽에 지원 정보와 경험을 입력한 후 생성 버튼을 눌러 주세요.")
                st.write("① 직무 분석 → ② 경험 연결 → ③ 자소서 완성")
                st.caption("결과는 이 세션에서만 유지됩니다. 완성한 문장은 다운로드해 보관하세요.")
        else:
            if saved["input"] != data:
                st.info("생성 이후 입력이 바뀌었습니다. 아래는 이전 입력의 결과입니다.")
            answer = saved["answer"]
            if answer.incomplete:
                st.warning("출력 토큰 한도 등으로 결과가 중단되었습니다. 분량을 줄여 재생성하세요.")
            edit_key = f"edited_{feature.id}"
            if edit_key not in ss:
                ss[edit_key] = saved.get("edited", answer.text)
            def persist_edit():
                ss.results[feature.id]["edited"] = ss[edit_key]
            edited = st.text_area("결과 편집", key=edit_key, height=500, max_chars=30000, on_change=persist_edit)
            count = char_count(edited, saved["spaces"])
            st.caption(f"현재 {count:,}자 · 생성 시 기준 {saved['limit']:,}자 · {'공백 포함' if saved['spaces'] else '공백 제외'}")
            if feature.essay and count > saved["limit"]:
                st.warning(f"상한보다 {count - saved['limit']:,}자 많습니다. 직접 줄이거나 입력 분량을 조정해 재생성하세요.")
            st.caption(f"입력 {answer.input_tokens if answer.input_tokens is not None else '미제공'} / 출력 {answer.output_tokens if answer.output_tokens is not None else '미제공'} 토큰 · 예상 비용 ${saved['cost']:.4f}")
            a, b, c = st.columns(3)
            a.download_button(".txt 다운로드", edited.encode("utf-8"), f"{feature.id}.txt", "text/plain", on_click="ignore", width="stretch")
            b.download_button(".md 다운로드", edited.encode("utf-8"), f"{feature.id}.md", "text/markdown", on_click="ignore", width="stretch")
            if c.button("결과 초기화", width="stretch"):
                del ss.results[feature.id]
                st.rerun()
            st.caption("복사: 아래 상자 오른쪽 위의 복사 아이콘을 누르세요.")
            st.code(edited, language=None, wrap_lines=True)
            st.caption("다운로드와 복사는 편집한 결과를 사용합니다. 제출 전 사실·기업 정보·글자 수를 확인하세요.")
        with st.expander("이 기능의 프롬프트 확인"):
            from core import ROOT
            st.code((ROOT / f"prompts/{feature.id}.md").read_text(encoding="utf-8"), language=None, wrap_lines=True)
            st.caption("공통 사실성 규칙을 먼저 적용하고, 입력값을 별도 사용자 메시지로 전달합니다.")

with feedback_tab:
    from feedback_ui import render_feedback
    render_feedback()

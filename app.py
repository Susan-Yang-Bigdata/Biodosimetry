"""
생물학적 선량평가 — 비상 대응용 의사결정 대시보드 (Streamlit, 규칙 기반).

화면 순서: 결정 요약 → 즉시 조치 → 경고·불확실성 → (접기) 상세 설명·PDF·GP.

실행: py -3 -m streamlit run app.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_APP_DIR = Path(__file__).resolve().parent


def _load_sibling_py(name: str):
    path = _APP_DIR / f"{name}.py"
    if not path.is_file():
        raise ImportError(
            f"필수 파일이 없습니다: {path}\n"
            f"app.py 와 같은 폴더에 {name}.py 가 있어야 합니다."
        )
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"모듈 스펙을 만들 수 없습니다: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_pdf = _load_sibling_py("pdf_lookup")
PdfDocumentText = _pdf.PdfDocumentText
is_pdf_blob = _pdf.is_pdf_blob
load_pdf_text = _pdf.load_pdf_text
snippets_for_query = _pdf.snippets_for_query
total_char_count = _pdf.total_char_count

_re = _load_sibling_py("rule_engine")
EvaluationResult = _re.EvaluationResult
default_guidelines_path = _re.default_guidelines_path
default_rules_path = _re.default_rules_path
evaluate = _re.evaluate
load_guidelines_json = _re.load_guidelines_json
load_rules_json = _re.load_rules_json

_rh = _load_sibling_py("recommendation_helpers")


# ---------------------------------------------------------------------------
# 시나리오 입력
# ---------------------------------------------------------------------------


def collect_scenario(*, key_prefix: str | None) -> dict[str, Any]:
    def _k(name: str) -> str:
        return f"{key_prefix}{name}" if key_prefix is not None else f"s_{name}"

    box = st.sidebar if key_prefix is None else st
    box.markdown("### 입력")

    incident_scale = box.selectbox(
        "사고 규모",
        options=["local", "regional", "national", "international"],
        format_func=lambda x: {
            "local": "지역",
            "regional": "광역",
            "national": "국가",
            "international": "국제",
        }[x],
        key=_k("incident_scale"),
    )
    elapsed_hours = box.slider(
        "경과 시간(h)",
        min_value=0.0,
        max_value=336.0,
        value=12.0,
        step=0.5,
        key=_k("elapsed_hours"),
    )
    num_exposed = box.number_input(
        "잠재 노출 인원",
        min_value=0,
        max_value=500_000,
        value=10,
        step=1,
        key=_k("num_exposed"),
    )
    exposure_known = box.toggle("노출 정보 확보", value=False, key=_k("exposure_known"))
    partial_body = box.toggle("부분피폭 의심", value=False, key=_k("partial_body"))
    internal_c = box.toggle("내부 오염 의심", value=False, key=_k("internal_c"))
    symptom_severity = box.select_slider(
        "증상 (임상은 의료기관)",
        options=["none", "mild", "moderate", "severe"],
        value="none",
        format_func=lambda x: {
            "none": "없음/미상",
            "mild": "경미",
            "moderate": "중등도",
            "severe": "중증",
        }[x],
        key=_k("symptom"),
    )
    resource_level = box.selectbox(
        "자원 수준",
        options=["minimal", "moderate", "full"],
        index=1,
        format_func=lambda x: {"minimal": "제한", "moderate": "보통", "full": "충분"}[x],
        key=_k("resource"),
    )

    return {
        "incident_scale": incident_scale,
        "elapsed_hours": float(elapsed_hours),
        "num_exposed": int(num_exposed),
        "exposure_known": bool(exposure_known),
        "partial_body_suspected": bool(partial_body),
        "internal_contamination_suspected": bool(internal_c),
        "symptom_severity": symptom_severity,
        "resource_level": resource_level,
    }


# ---------------------------------------------------------------------------
# 대시보드 본문 (짧은 카드·배지·접기)
# ---------------------------------------------------------------------------


def render_decision_strip(ev: EvaluationResult) -> None:
    """① 결정 결과: 우선순위 + 한 줄 방향 + 검사/주의 요약 카드."""
    st.markdown("### ① 결정 요약")
    left, right = st.columns([1, 2.3])
    with left:
        st.metric(label="응답 우선순위", value=_rh.card_priority_text(ev))
        if _rh.needs_confirmation_any(ev):
            st.markdown(
                '<span style="background:#6b7280;color:#fff;padding:0.15rem 0.5rem;'
                'border-radius:6px;font-size:0.75rem;">문헌 확인 필요</span>',
                unsafe_allow_html=True,
            )
    with right:
        st.caption("권장 방향 (생물학적 선량평가)")
        st.markdown(f"**{_rh.card_direction_text(ev, 200)}**")

    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.caption("검사·절차 옵션")
            st.markdown(_rh.card_assays_text(ev, max_lines=3))
    with c2:
        with st.container(border=True):
            st.caption("핵심 주의")
            st.markdown(_rh.card_cautions_text(ev, max_lines=3))


def render_immediate_actions(scenario: dict[str, Any], ev: EvaluationResult) -> None:
    """② 즉시 다음 조치 — 짧은 번호 리스트."""
    st.markdown("### ② 즉시 검토할 조치")
    st.caption("운영·계획용. 진단·치료 지시 아님.")
    actions = _rh.recommended_next_actions(scenario, ev, max_items=5)
    if not actions:
        st.caption("— 발화 규칙에 연결된 조치 없음 —")
        return
    n = min(len(actions), 5)
    cols = st.columns(n)
    for i, (col, text) in enumerate(zip(cols, actions)):
        with col:
            with st.container(border=True):
                st.markdown(f"**{i + 1}**")
                short = text if len(text) <= 120 else text[:119] + "…"
                st.caption(short)


def render_uncertainty_strip(scenario: dict[str, Any], ev: EvaluationResult) -> None:
    """③ 경고·불확실성: 배지 한 줄 + 접기 상세."""
    st.markdown("### ③ 불확실성 · 한계")
    level, detail = _rh.uncertainty_level(scenario, ev)
    em = _rh.uncertainty_emoji(level)
    st.markdown(f"{em} **{level}** · {detail}")
    factors = _rh.uncertainty_factors(scenario, ev)
    with st.expander("요인 전체 보기", expanded=False):
        for f in factors:
            st.markdown(f"- {f}")


def render_reference_expanders(
    scenario: dict[str, Any],
    ev: EvaluationResult,
    guidelines_data: dict[str, Any],
) -> None:
    """④ 상세 설명·문헌·원칙 — 기본 접힘."""
    st.markdown("### ④ 참고 (펼치기)")
    with st.expander("왜 이 권고인가? — 상황 신호 · 발화 규칙", expanded=False):
        for line in _rh.why_recommendation_bullets(scenario, ev):
            st.markdown(f"- {line}")

    with st.expander("PDF·문헌 검색 키워드", expanded=False):
        en, ko = _rh.suggested_pdf_keywords(scenario, ev)
        st.code(", ".join(en), language="text")
        st.caption(" · ".join(ko))

    with st.expander("설계 원칙 GP01–GP05", expanded=False):
        meta = guidelines_data.get("meta") or {}
        st.warning(str(meta.get("important") or "공식 문서 직접 인용 아님."))
        for p in guidelines_data.get("principles") or []:
            if not isinstance(p, dict):
                continue
            pid = p.get("id", "")
            with st.expander(f"{pid} — {p.get('title', '')}", expanded=False):
                st.markdown(str(p.get("text", "")))


def render_rule_detail_expanders(ev: EvaluationResult) -> None:
    st.caption("규칙 JSON·GP 연결 — 편집·검증용")
    if not ev.triggered:
        st.info("발화 규칙 없음")
        return
    for t in ev.triggered:
        badge = "확인필요" if t.evidence_status == "needs_confirmation" else t.evidence_status
        with st.expander(f"{t.rule_id} · {t.title} · {badge}", expanded=False):
            st.caption(t.source_note)
            st.json({"when": t.when_snapshot, "then": {
                "response_priority": t.response_priority,
                "biodosimetry_direction": t.biodosimetry_direction,
                "assay_options": list(t.assay_options),
                "cautions": list(t.cautions),
            }})


def render_scenario_comparison(
    scenario_a: dict[str, Any],
    scenario_b: dict[str, Any],
    ev_a: EvaluationResult,
    ev_b: EvaluationResult,
) -> None:
    st.markdown("#### 비교")
    la, _ = _rh.uncertainty_level(scenario_a, ev_a)
    lb, _ = _rh.uncertainty_level(scenario_b, ev_b)
    na = _rh.recommended_next_actions(scenario_a, ev_a, max_items=5)
    nb = _rh.recommended_next_actions(scenario_b, ev_b, max_items=5)

    h, ca, cb = st.columns((1, 1, 1))
    with h:
        st.caption("항목")
    with ca:
        st.markdown("**A**")
    with cb:
        st.markdown("**B**")

    def row(label: str, va: str, vb: str) -> None:
        x, ya, yb = st.columns((1, 1, 1))
        with x:
            st.markdown(f"**{label}**")
        with ya:
            with st.container(border=True):
                st.markdown(va)
        with yb:
            with st.container(border=True):
                st.markdown(vb)

    row("우선순위", _rh.card_priority_text(ev_a), _rh.card_priority_text(ev_b))
    row("불확실성", f"{_rh.uncertainty_emoji(la)} {la}", f"{_rh.uncertainty_emoji(lb)} {lb}")
    row("방향(요약)", _rh.card_direction_text(ev_a, 140), _rh.card_direction_text(ev_b, 140))
    row("다음 조치", _rh.next_actions_display_text(na), _rh.next_actions_display_text(nb))
    row("발화 규칙", str(len(ev_a.triggered)), str(len(ev_b.triggered)))


@st.cache_data
def _cached_rules(path_str: str, _mtime: float) -> dict[str, Any]:
    return load_rules_json(Path(path_str))


@st.cache_data
def _cached_guidelines(path_str: str, _mtime: float) -> dict[str, Any]:
    return load_guidelines_json(Path(path_str))


def _render_pdf_lookup_tab(
    scenario_hint: dict[str, Any] | None,
    ev_hint: EvaluationResult | None,
) -> None:
    st.markdown("#### PDF 검색")
    if scenario_hint is not None and ev_hint is not None:
        with st.expander("이 시나리오 추천 검색어", expanded=False):
            en, ko = _rh.suggested_pdf_keywords(scenario_hint, ev_hint)
            st.code(", ".join(en), language="text")
            st.caption(" · ".join(ko))

    uploaded = st.file_uploader(
        "PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader_main",
    )
    if not uploaded:
        st.caption("파일 선택 후 검색")
        return

    docs: list[PdfDocumentText] = []
    for uf in uploaded:
        blob = uf.getvalue()
        if not is_pdf_blob(blob):
            st.error(f"{uf.name}: PDF 아님")
            continue
        doc = load_pdf_text(file_name=uf.name, data=blob)
        docs.append(doc)

    if not docs:
        return

    if scenario_hint is not None and ev_hint is not None:
        en0, _ = _rh.suggested_pdf_keywords(scenario_hint, ev_hint)
        if en0:
            st.caption(f"추천: `{en0[0]}`")

    q = st.text_input("검색어", key="pdf_query_main")
    if not q.strip():
        return
    for doc in docs:
        st.caption(doc.file_name)
        hits = snippets_for_query(doc, q.strip())
        for j, (page_no, snip) in enumerate(hits[:8]):
            with st.expander(f"p.{page_no} #{j + 1}", expanded=False):
                st.write(snip)


def main() -> None:
    st.set_page_config(page_title="생물학적 선량평가 대시보드", layout="wide", initial_sidebar_state="expanded")

    st.title("비상 대응 · 의사결정 보드")
    with st.expander("면책 · 범위 (한 줄)", expanded=False):
        st.caption(
            "규칙 기반·로컬 프로토타입. **의료 진단·치료 지시 아님.** "
            "ML·영상·DB·로그인 없음."
        )

    rules_path = default_rules_path()
    rules_data = _cached_rules(str(rules_path), rules_path.stat().st_mtime)
    guidelines_path = default_guidelines_path(rules_data)
    guidelines_data = _cached_guidelines(str(guidelines_path), guidelines_path.stat().st_mtime)

    st.sidebar.markdown("### 시나리오")
    scenario_sidebar = collect_scenario(key_prefix=None)
    ev_sidebar = evaluate(scenario_sidebar, rules_data, guidelines_data)

    render_decision_strip(ev_sidebar)
    st.divider()
    render_immediate_actions(scenario_sidebar, ev_sidebar)
    st.divider()
    render_uncertainty_strip(scenario_sidebar, ev_sidebar)
    st.divider()
    render_reference_expanders(scenario_sidebar, ev_sidebar, guidelines_data)

    tab_detail, tab_compare, tab_pdf = st.tabs(["근거 상세", "시나리오 비교", "PDF"])

    with tab_detail:
        render_rule_detail_expanders(ev_sidebar)

    with tab_compare:
        st.caption("A/B만 비교. 사이드바는 위 대시보드 기준.")
        u1, u2 = st.columns(2)
        with u1:
            st.markdown("**A**")
            sa = collect_scenario(key_prefix="a_")
        with u2:
            st.markdown("**B**")
            sb = collect_scenario(key_prefix="b_")
        ev_a = evaluate(sa, rules_data, guidelines_data)
        ev_b = evaluate(sb, rules_data, guidelines_data)
        render_scenario_comparison(sa, sb, ev_a, ev_b)

    with tab_pdf:
        _render_pdf_lookup_tab(scenario_sidebar, ev_sidebar)

    st.caption(f"{rules_path.name} · {guidelines_path.name}")


if __name__ == "__main__":
    main()

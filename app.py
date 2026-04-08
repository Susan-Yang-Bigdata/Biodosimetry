"""
생물학적 선량평가 — 비상 대응용 의사결정 대시보드 (Streamlit, 규칙 기반).

화면 순서: 결정 요약 → 즉시 조치 → 경고·불확실성 → (접기) 상세 설명·PDF·GP.

실행: py -3 -m streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime
import html
import importlib.util
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_APP_DIR = Path(__file__).resolve().parent

SINGLE_ANALYSIS_STATE_KEY = "single_analysis_scenario"
COMPARE_ANALYSIS_A_STATE_KEY = "compare_analysis_scenario_a"
COMPARE_ANALYSIS_B_STATE_KEY = "compare_analysis_scenario_b"
FLASH_MESSAGE_STATE_KEY = "ui_flash_message"

SCENARIO_WIDGET_DEFAULTS: dict[str, Any] = {
    "incident_scale": "local",
    "elapsed_hours": 12.0,
    "num_exposed": 10,
    "exposure_known": False,
    "partial_body": False,
    "internal_c": False,
    "symptom": "none",
    "resource": "moderate",
}

SCENARIO_WIDGET_NAME_BY_FIELD = {
    "incident_scale": "incident_scale",
    "elapsed_hours": "elapsed_hours",
    "num_exposed": "num_exposed",
    "exposure_known": "exposure_known",
    "partial_body_suspected": "partial_body",
    "internal_contamination_suspected": "internal_c",
    "symptom_severity": "symptom",
    "resource_level": "resource",
}


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
_store = _load_sibling_py("scenario_store")
default_saved_scenarios_path = _store.default_saved_scenarios_path
load_saved_scenarios = _store.load_saved_scenarios
save_compare_scenario = _store.save_compare_scenario
save_single_scenario = _store.save_single_scenario


# ---------------------------------------------------------------------------
# 시나리오 입력
# ---------------------------------------------------------------------------


def _scenario_widget_key(key_prefix: str | None, name: str) -> str:
    return f"{key_prefix}{name}" if key_prefix is not None else f"s_{name}"


def _reset_scenario_widget_values(key_prefix: str | None) -> None:
    for name, value in SCENARIO_WIDGET_DEFAULTS.items():
        st.session_state[_scenario_widget_key(key_prefix, name)] = value


def _reset_single_analysis_state() -> None:
    _reset_scenario_widget_values(None)
    st.session_state.pop(SINGLE_ANALYSIS_STATE_KEY, None)


def _reset_compare_analysis_state() -> None:
    _reset_scenario_widget_values("a_")
    _reset_scenario_widget_values("b_")
    st.session_state.pop(COMPARE_ANALYSIS_A_STATE_KEY, None)
    st.session_state.pop(COMPARE_ANALYSIS_B_STATE_KEY, None)


def _set_flash_message(level: str, text: str) -> None:
    st.session_state[FLASH_MESSAGE_STATE_KEY] = {"level": level, "text": text}


def _render_flash_message() -> None:
    raw = st.session_state.pop(FLASH_MESSAGE_STATE_KEY, None)
    if not isinstance(raw, dict):
        return
    level = str(raw.get("level", "info"))
    text = str(raw.get("text", "")).strip()
    if not text:
        return
    renderer = getattr(st, level, st.info)
    renderer(text)


def _apply_scenario_to_widgets(key_prefix: str | None, scenario: dict[str, Any]) -> None:
    for field, widget_name in SCENARIO_WIDGET_NAME_BY_FIELD.items():
        widget_key = _scenario_widget_key(key_prefix, widget_name)
        if field in scenario:
            st.session_state[widget_key] = scenario[field]


def _saved_entry_label(entry: dict[str, Any]) -> str:
    saved_at = str(entry.get("saved_at", "")).strip()
    if saved_at:
        return f"{entry['name']} · {saved_at[:16].replace('T', ' ')}"
    return str(entry["name"])


def collect_scenario(
    *,
    key_prefix: str | None,
    container: Any | None = None,
    show_title: bool = True,
) -> dict[str, Any]:
    def _k(name: str) -> str:
        return _scenario_widget_key(key_prefix, name)

    box = container if container is not None else (st.sidebar if key_prefix is None else st)
    if show_title:
        box.markdown("### 시나리오 입력")

    incident_scale = box.selectbox(
        "사고 범위",
        options=["local", "regional", "national", "international"],
        format_func=lambda x: {
            "local": "지역",
            "regional": "광역",
            "national": "국가",
            "international": "국제",
        }[x],
        key=_k("incident_scale"),
        help="사고가 영향을 미치는 조직·지리 범위를 거칠게 나타냅니다.",
    )
    elapsed_hours = box.slider(
        "노출 후 경과 시간 (시간)",
        min_value=0.0,
        max_value=336.0,
        value=12.0,
        step=0.5,
        key=_k("elapsed_hours"),
        help="노출 시각이 정확하지 않다면 가장 그럴듯한 추정값을 입력합니다.",
    )
    num_exposed = box.number_input(
        "잠재 노출 인원 수",
        min_value=0,
        max_value=500_000,
        value=10,
        step=1,
        key=_k("num_exposed"),
        help="확정 인원이 아니어도 됩니다. 현재 대응에서 고려 중인 대상을 입력합니다.",
    )
    exposure_known = box.toggle(
        "노출 정보가 비교적 명확함",
        value=False,
        key=_k("exposure_known"),
        help="노출 시각·경로·관련 정보가 어느 정도 정리되어 있는지 표시합니다.",
    )
    partial_body = box.toggle(
        "부분피폭 가능성",
        value=False,
        key=_k("partial_body"),
        help="전신에 균일하게 피폭되지 않았을 가능성이 있으면 켭니다.",
    )
    internal_c = box.toggle(
        "내부 오염 가능성",
        value=False,
        key=_k("internal_c"),
        help="흡입·섭취 등으로 체내 오염 가능성이 있으면 켭니다.",
    )
    symptom_severity = box.select_slider(
        "증상 수준 (임상 판단 대체 아님)",
        options=["none", "mild", "moderate", "severe"],
        value="none",
        format_func=lambda x: {
            "none": "없음/미상",
            "mild": "경미",
            "moderate": "중등도",
            "severe": "중증",
        }[x],
        key=_k("symptom"),
        help="현장 정보 수준의 거친 입력입니다. 실제 의학적 판단은 의료기관이 담당합니다.",
    )
    resource_level = box.selectbox(
        "가용 자원 수준",
        options=["minimal", "moderate", "full"],
        index=1,
        format_func=lambda x: {"minimal": "제한", "moderate": "보통", "full": "충분"}[x],
        key=_k("resource"),
        help="실험실 처리량, 인력, 장비, 연계기관 가용성을 종합적으로 나타냅니다.",
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
# 목적 중심 대시보드 UI
# ---------------------------------------------------------------------------


PRIORITY_META: dict[str | None, dict[str, str]] = {
    "critical": {"label": "긴급 대응", "tone": "critical", "summary": "의료·응급 연계가 가장 먼저입니다."},
    "high": {"label": "우선 대응", "tone": "high", "summary": "선별과 조정이 빠르게 필요합니다."},
    "medium": {"label": "계획 검토", "tone": "medium", "summary": "상황을 정리하며 대응 방향을 구체화할 단계입니다."},
    "low": {"label": "참고 수준", "tone": "low", "summary": "당장 급박하지 않지만 계획 검토는 필요합니다."},
    None: {"label": "수동 검토 필요", "tone": "neutral", "summary": "자동 규칙만으로는 방향을 정하기 어렵습니다."},
}

SCALE_LABELS = {
    "local": "지역",
    "regional": "광역",
    "national": "국가",
    "international": "국제",
}

RESOURCE_LABELS = {
    "minimal": "제한",
    "moderate": "보통",
    "full": "충분",
}

SYMPTOM_LABELS = {
    "none": "없음/미상",
    "mild": "경미",
    "moderate": "중등도",
    "severe": "중증",
}


def inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        .hero-panel {
            border-radius: 22px;
            padding: 1.2rem 1.3rem;
            border: 1px solid #d9e2ec;
            background: linear-gradient(135deg, #f8fbff 0%, #eef4fb 100%);
            margin-bottom: 1rem;
        }
        .hero-panel.tone-critical {
            background: linear-gradient(135deg, #fff3f0 0%, #ffe1dc 100%);
            border-color: #efb0a6;
        }
        .hero-panel.tone-high {
            background: linear-gradient(135deg, #fff9ef 0%, #ffefcf 100%);
            border-color: #efcf8a;
        }
        .hero-panel.tone-medium {
            background: linear-gradient(135deg, #f6fbf5 0%, #e7f4e4 100%);
            border-color: #bad4b4;
        }
        .hero-panel.tone-low {
            background: linear-gradient(135deg, #f7fbff 0%, #eaf2ff 100%);
            border-color: #c7d8ee;
        }
        .hero-panel.tone-neutral {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border-color: #d7dee7;
        }
        .hero-kicker {
            font-size: 0.82rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #475569;
            margin-bottom: 0.35rem;
        }
        .hero-title {
            font-size: 1.55rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 0.3rem;
        }
        .hero-body {
            color: #334155;
            font-size: 0.98rem;
            line-height: 1.55;
        }
        .chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin-top: 0.75rem;
        }
        .chip {
            display: inline-block;
            border-radius: 999px;
            padding: 0.28rem 0.7rem;
            border: 1px solid #d8e0ea;
            background: rgba(255, 255, 255, 0.78);
            color: #334155;
            font-size: 0.82rem;
        }
        .metric-card {
            border-radius: 18px;
            padding: 0.95rem 1rem;
            border: 1px solid #dce4ee;
            background: #ffffff;
            min-height: 124px;
        }
        .metric-card.tone-critical { border-color: #efb0a6; background: #fff7f5; }
        .metric-card.tone-high { border-color: #efd78f; background: #fffaf1; }
        .metric-card.tone-medium { border-color: #bfd6bb; background: #f7fbf6; }
        .metric-card.tone-low { border-color: #c7d8ee; background: #f7fbff; }
        .metric-card.tone-neutral { border-color: #dce4ee; background: #fafbfc; }
        .metric-label {
            font-size: 0.8rem;
            color: #64748b;
            margin-bottom: 0.25rem;
        }
        .metric-value {
            font-size: 1.15rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 0.32rem;
        }
        .metric-detail {
            font-size: 0.88rem;
            color: #475569;
            line-height: 1.45;
        }
        .compare-callout {
            border-left: 5px solid #0f766e;
            padding: 0.95rem 1rem;
            background: #f0fdfa;
            border-radius: 12px;
            color: #134e4a;
            margin-bottom: 0.8rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _priority_meta(priority: str | None) -> dict[str, str]:
    return PRIORITY_META.get(priority, PRIORITY_META[None])


def _priority_rank(priority: str | None) -> int:
    order = ["critical", "high", "medium", "low", None]
    return order.index(priority) if priority in order else len(order)


def _resource_pressure(scenario: dict[str, Any], ev: EvaluationResult) -> tuple[str, str, str]:
    score = 0
    reasons: list[str] = []
    priority = ev.synthesized_priority
    if priority == "critical":
        score += 3
        reasons.append("의료 우선 상황")
    elif priority == "high":
        score += 2
        reasons.append("빠른 조정 필요")
    elif priority == "medium":
        score += 1

    n = int(scenario.get("num_exposed", 0))
    if n >= 100:
        score += 2
        reasons.append("대상 인원 많음")
    elif n >= 30:
        score += 1
        reasons.append("다수 대상")

    scale = str(scenario.get("incident_scale", "local"))
    if scale in ("national", "international"):
        score += 2
        reasons.append("범위가 넓음")
    elif scale == "regional":
        score += 1
        reasons.append("광역 대응")

    resource = str(scenario.get("resource_level", "moderate"))
    if resource == "minimal":
        score += 2
        reasons.append("자원 제한")
    elif resource == "moderate":
        score += 1

    if scenario.get("internal_contamination_suspected") is True:
        score += 1
        reasons.append("내부 오염 가능성")
    if scenario.get("partial_body_suspected") is True:
        score += 1
        reasons.append("부분피폭 가능성")

    if score >= 7:
        return "매우 높음", "critical", "광역 조정과 단계적 배분을 먼저 설계해야 합니다."
    if score >= 5:
        return "높음", "high", "검사 처리량과 연계기관 배분을 서둘러 점검해야 합니다."
    if score >= 3:
        return "보통", "medium", "핵심 자원과 협력 경로를 정리해 두는 편이 안전합니다."
    return "낮음", "low", "현재 입력만 보면 기관 내부 계획 검토 중심으로도 시작할 수 있습니다."


def _dominant_strategy(ev: EvaluationResult) -> str:
    ids = {t.rule_id for t in _rh.active_triggered_rules(ev)}
    if not ids:
        return "자동 규칙 대신 수동 검토"
    if "R005" in ids:
        return "의료 우선 안정화"
    if "R003" in ids and "R004" in ids:
        return "복합 노출 경로 검토"
    if "R003" in ids:
        return "내부 오염 경로 병행"
    if "R004" in ids:
        return "부분피폭 해석 주의"
    if {"R001", "R006", "R009"} & ids:
        return "선별·처리량 중심 운영"
    if "R008" in ids:
        return "정밀 검사 계획 검토"
    return "상황 맞춤 계획 검토"


def _decision_takeaway(scenario: dict[str, Any], ev: EvaluationResult) -> str:
    if not ev.triggered:
        return "현재 입력만으로는 자동 권고를 확정하기 어렵습니다. 공식 지침과 기관 SOP를 함께 보며 수동 검토가 필요합니다."
    if ev.synthesized_priority == "critical":
        return "지금은 생물학적 선량평가 자체보다 의료 연계와 상태 확인이 먼저여야 하는 상황입니다."
    if scenario.get("internal_contamination_suspected") is True:
        return "혈액 기반 해석만으로 판단하지 말고 내부 오염 평가 경로를 함께 보는 구성이 적절합니다."
    if scenario.get("resource_level") == "minimal" or int(scenario.get("num_exposed", 0)) >= 30:
        return "대상자 수와 처리량 제약을 고려해 전원 동일 검사보다 선별과 단계적 접근이 더 현실적입니다."
    return _rh.card_direction_text(ev, 170)


def _scenario_badges(scenario: dict[str, Any]) -> list[str]:
    badges = [
        f"사고 범위: {SCALE_LABELS[str(scenario.get('incident_scale', 'local'))]}",
        f"자원 수준: {RESOURCE_LABELS[str(scenario.get('resource_level', 'moderate'))]}",
        f"대상 인원: {int(scenario.get('num_exposed', 0))}명",
        f"경과 시간: {float(scenario.get('elapsed_hours', 0)):.1f}시간",
    ]
    if scenario.get("exposure_known") is True:
        badges.append("노출 정보 비교적 명확")
    else:
        badges.append("노출 정보 불명")
    if scenario.get("internal_contamination_suspected") is True:
        badges.append("내부 오염 가능성")
    if scenario.get("partial_body_suspected") is True:
        badges.append("부분피폭 가능성")
    return badges


def _render_chip_row(items: list[str]) -> None:
    body = "".join(f'<span class="chip">{html.escape(text)}</span>' for text in items if text)
    if body:
        st.markdown(f'<div class="chip-row">{body}</div>', unsafe_allow_html=True)


def _render_stat_card(label: str, value: str, detail: str, tone: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card tone-{html.escape(tone)}">
            <div class="metric-label">{html.escape(label)}</div>
            <div class="metric-value">{html.escape(value)}</div>
            <div class="metric-detail">{html.escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _resource_allocation_bullets(scenario: dict[str, Any], ev: EvaluationResult) -> list[str]:
    items: list[str] = []
    if ev.synthesized_priority == "critical":
        items.append("의료기관 연계와 환자 분류를 먼저 확보하고, 생물학적 선량평가는 보조 계획으로 뒤에 둡니다.")
    elif int(scenario.get("num_exposed", 0)) >= 30 or scenario.get("resource_level") == "minimal":
        items.append("전원 동일 검사보다 선별 후 확인 검사로 이어지는 2단계 운영을 우선 설계합니다.")
    else:
        items.append("대상자 수가 많지 않다면 정밀 검사 일정과 품질관리 계획을 함께 검토할 수 있습니다.")

    if scenario.get("resource_level") == "minimal":
        items.append("검체 운송, 저장, 협력 실험실 확보처럼 병목이 생길 지점을 먼저 점검합니다.")
    elif scenario.get("resource_level") == "moderate":
        items.append("핵심 검사와 외부 연계 검사를 분리해 역할을 배정하는 편이 안정적입니다.")
    else:
        items.append("가용 자원이 충분해도 검사 리드타임과 품질관리 부담을 함께 계산해야 합니다.")

    if scenario.get("incident_scale") in ("regional", "national", "international"):
        items.append("기관 간 문진 양식, 대상자 분류 기준, 데이터 전달 형식을 먼저 맞추는 것이 중요합니다.")
    if scenario.get("internal_contamination_suspected") is True:
        items.append("내부 오염 경로 평가는 혈액 기반 결과와 별도로 병행할 수 있게 자원을 나눠야 합니다.")
    if scenario.get("partial_body_suspected") is True:
        items.append("부분피폭 가능성이 있으면 물리 정보와 임상 해석 지원 자원을 따로 고려합니다.")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:4]


def render_project_header() -> None:
    st.title("방사선 비상 대응 의사결정 지원 프로토타입")
    st.caption(
        "시나리오 입력을 바탕으로 대응 우선순위, 생물학적 선량평가 방향, 자원 배분 포인트를 정리하는 연구·교육용 대시보드입니다."
    )
    st.markdown(
        """
        <div class="compare-callout">
            <strong>프로젝트 목표</strong><br>
            대응 우선순위 제시 · 생물학적 선량평가 적용 방향 정리 · 자원 배분 시나리오 검토 · 시나리오 비교와 시각화
        </div>
        """,
        unsafe_allow_html=True,
    )


def _scenario_summary_pairs(scenario: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("사고 범위", SCALE_LABELS[str(scenario.get("incident_scale", "local"))]),
        ("잠재 노출 인원", f"{int(scenario.get('num_exposed', 0))}명"),
        ("노출 후 경과 시간", f"{float(scenario.get('elapsed_hours', 0)):.1f}시간"),
        ("노출 정보", "비교적 명확" if scenario.get("exposure_known") else "불명"),
        ("부분피폭 가능성", "있음" if scenario.get("partial_body_suspected") else "낮음"),
        ("내부 오염 가능성", "있음" if scenario.get("internal_contamination_suspected") else "낮음"),
        ("증상 수준", SYMPTOM_LABELS[str(scenario.get("symptom_severity", "none"))]),
        ("가용 자원 수준", RESOURCE_LABELS[str(scenario.get("resource_level", "moderate"))]),
    ]


def render_single_saved_scenarios_panel(analyzed_single: dict[str, Any] | None, saved_path: Path) -> None:
    store = load_saved_scenarios(saved_path)
    singles = list(store.get("single") or [])
    with st.sidebar.expander("시나리오 저장/불러오기", expanded=False):
        st.caption("현재 조회 결과를 저장하거나 이전에 저장한 시나리오를 불러옵니다.")
        if analyzed_single is not None:
            save_name = st.text_input(
                "저장 이름",
                key="single_save_name",
                placeholder="예: 대규모 자원 제한 시나리오",
            )
            if st.button("현재 조회 저장", key="single_save_button", use_container_width=True):
                clean_name = save_name.strip()
                if not clean_name:
                    st.warning("저장 이름을 먼저 입력해 주세요.")
                else:
                    save_single_scenario(clean_name, analyzed_single, saved_path)
                    _set_flash_message("success", f"`{clean_name}` 시나리오를 저장했습니다.")
                    st.rerun()
        else:
            st.caption("먼저 `분석 실행` 후 저장할 수 있습니다.")

        if singles:
            labels = [_saved_entry_label(entry) for entry in singles]
            selected_label = st.selectbox("저장된 시나리오", options=labels, key="single_saved_select")
            if st.button("선택한 시나리오 불러오기", key="single_load_button", use_container_width=True):
                entry = singles[labels.index(selected_label)]
                scenario = dict(entry["scenario"])
                _apply_scenario_to_widgets(None, scenario)
                st.session_state[SINGLE_ANALYSIS_STATE_KEY] = scenario
                _set_flash_message("success", f"`{entry['name']}` 시나리오를 불러왔습니다.")
                st.rerun()
        else:
            st.caption("저장된 시나리오가 없습니다.")


def render_compare_saved_scenarios_panel(
    analyzed_a: dict[str, Any] | None,
    analyzed_b: dict[str, Any] | None,
    saved_path: Path,
) -> None:
    store = load_saved_scenarios(saved_path)
    compares = list(store.get("compare") or [])
    with st.sidebar.expander("비교 시나리오 저장/불러오기", expanded=False):
        st.caption("마지막으로 실행한 A/B 비교를 저장하거나 다시 불러옵니다.")
        if analyzed_a is not None and analyzed_b is not None:
            save_name = st.text_input(
                "비교 저장 이름",
                key="compare_save_name",
                placeholder="예: 자원 수준 비교",
            )
            if st.button("현재 비교 저장", key="compare_save_button", use_container_width=True):
                clean_name = save_name.strip()
                if not clean_name:
                    st.warning("저장 이름을 먼저 입력해 주세요.")
                else:
                    save_compare_scenario(clean_name, analyzed_a, analyzed_b, saved_path)
                    _set_flash_message("success", f"`{clean_name}` 비교 시나리오를 저장했습니다.")
                    st.rerun()
        else:
            st.caption("먼저 `비교 실행` 후 저장할 수 있습니다.")

        if compares:
            labels = [_saved_entry_label(entry) for entry in compares]
            selected_label = st.selectbox("저장된 비교", options=labels, key="compare_saved_select")
            if st.button("선택한 비교 불러오기", key="compare_load_button", use_container_width=True):
                entry = compares[labels.index(selected_label)]
                scenario_a = dict(entry["scenario_a"])
                scenario_b = dict(entry["scenario_b"])
                _apply_scenario_to_widgets("a_", scenario_a)
                _apply_scenario_to_widgets("b_", scenario_b)
                st.session_state[COMPARE_ANALYSIS_A_STATE_KEY] = scenario_a
                st.session_state[COMPARE_ANALYSIS_B_STATE_KEY] = scenario_b
                _set_flash_message("success", f"`{entry['name']}` 비교 시나리오를 불러왔습니다.")
                st.rerun()
        else:
            st.caption("저장된 비교 시나리오가 없습니다.")


def render_scenario_snapshot(scenario: dict[str, Any]) -> None:
    st.markdown("### 입력 시나리오 요약")
    c1, c2, c3, c4, c5 = st.columns(5)
    cards = [
        ("사고 범위", SCALE_LABELS[str(scenario.get("incident_scale", "local"))], "대응 조직과 범위"),
        ("대상 인원", f"{int(scenario.get('num_exposed', 0))}명", "현재 고려 중인 규모"),
        ("경과 시간", f"{float(scenario.get('elapsed_hours', 0)):.1f}시간", "노출 후 시간 창"),
        ("노출 정보", "명확" if scenario.get("exposure_known") else "불명", "사실관계 정리 정도"),
        ("자원 수준", RESOURCE_LABELS[str(scenario.get("resource_level", "moderate"))], "실험실·인력·장비 여건"),
    ]
    for col, (label, value, detail) in zip((c1, c2, c3, c4, c5), cards):
        with col:
            _render_stat_card(label, value, detail, "neutral")
    _render_chip_row(_scenario_badges(scenario))


def render_decision_overview(scenario: dict[str, Any], ev: EvaluationResult) -> None:
    meta = _priority_meta(ev.synthesized_priority)
    hero_body = _decision_takeaway(scenario, ev)
    st.markdown(
        f"""
        <div class="hero-panel tone-{html.escape(meta['tone'])}">
            <div class="hero-kicker">현재 대응 판단</div>
            <div class="hero-title">{html.escape(meta['label'])}</div>
            <div class="hero-body">{html.escape(hero_body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    uncertainty_level, uncertainty_detail = _rh.uncertainty_level(scenario, ev)
    resource_level, resource_tone, resource_detail = _resource_pressure(scenario, ev)
    evidence_detail = "문헌 대조가 필요한 규칙 포함" if _rh.needs_confirmation_any(ev) else "즉시 검토 가능한 규칙 중심"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _render_stat_card("대응 우선순위", meta["label"], meta["summary"], meta["tone"])
    with c2:
        _render_stat_card("운영 초점", _dominant_strategy(ev), _rh.card_direction_text(ev, 100), meta["tone"])
    with c3:
        _render_stat_card("자원 압력", resource_level, resource_detail, resource_tone)
    with c4:
        _render_stat_card("불확실성", uncertainty_level, uncertainty_detail, "neutral")

    st.caption(evidence_detail)


def render_operational_board(scenario: dict[str, Any], ev: EvaluationResult) -> None:
    st.markdown("### 운영 판단 보드")
    left, right = st.columns((1.15, 1))
    actions = _rh.recommended_next_actions(scenario, ev, max_items=5)
    with left:
        st.markdown("#### 바로 검토할 조치")
        for idx, action in enumerate(actions, start=1):
            with st.container(border=True):
                st.markdown(f"**{idx}. {action}**")
    with right:
        st.markdown("#### 자원 배분 포인트")
        for item in _resource_allocation_bullets(scenario, ev):
            with st.container(border=True):
                st.markdown(item)


def render_reasoning_board(scenario: dict[str, Any], ev: EvaluationResult) -> None:
    st.markdown("### 왜 이런 판단이 나왔나")
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("#### 입력에서 읽힌 신호")
            for line in _rh.why_recommendation_bullets(scenario, ev):
                st.markdown(f"- {line}")
    with right:
        with st.container(border=True):
            st.markdown("#### 이 판단이 조심스러운 이유")
            for line in _rh.uncertainty_factors(scenario, ev):
                st.markdown(f"- {line}")


def render_single_scenario_dashboard(
    scenario: dict[str, Any],
    ev: EvaluationResult,
    guidelines_data: dict[str, Any],
) -> None:
    render_single_export_tools(scenario, ev)
    st.divider()
    render_scenario_snapshot(scenario)
    st.divider()
    render_decision_overview(scenario, ev)
    st.divider()
    render_operational_board(scenario, ev)
    st.divider()
    render_reasoning_board(scenario, ev)
    st.divider()
    tab_detail, tab_reference, tab_pdf = st.tabs(["판단 비교·근거", "전문가용 상세", "PDF 근거 확인"])
    with tab_detail:
        st.markdown("#### 권장 방향")
        st.write(ev.biodosimetry_direction or "자동 권고 없음")
        st.markdown("#### 검사·절차 옵션")
        st.markdown(_rh.card_assays_text(ev, max_lines=8))
        st.markdown("#### 핵심 주의")
        st.markdown(_rh.card_cautions_text(ev, max_lines=8))
    with tab_reference:
        render_reference_expanders(scenario, ev, guidelines_data)
        render_rule_detail_expanders(ev)
    with tab_pdf:
        _render_pdf_lookup_tab(scenario, ev)


def _comparison_takeaway(
    scenario_a: dict[str, Any],
    scenario_b: dict[str, Any],
    ev_a: EvaluationResult,
    ev_b: EvaluationResult,
) -> str:
    pa = ev_a.synthesized_priority
    pb = ev_b.synthesized_priority
    ra, _, _ = _resource_pressure(scenario_a, ev_a)
    rb, _, _ = _resource_pressure(scenario_b, ev_b)
    strategy_a = _dominant_strategy(ev_a)
    strategy_b = _dominant_strategy(ev_b)
    if _priority_rank(pa) < _priority_rank(pb):
        return f"시나리오 A가 더 높은 대응 우선순위를 보입니다. 자원 압력은 A={ra}, B={rb}입니다."
    if _priority_rank(pb) < _priority_rank(pa):
        return f"시나리오 B가 더 높은 대응 우선순위를 보입니다. 자원 압력은 A={ra}, B={rb}입니다."
    if strategy_a == strategy_b:
        return f"두 시나리오의 우선순위는 비슷하며 운영 초점도 동일하게 {strategy_a} 쪽으로 읽힙니다."
    return f"두 시나리오의 우선순위는 비슷하지만 운영 초점은 A={strategy_a}, B={strategy_b}로 다릅니다."


def _hour_window_label(hours: float) -> str:
    if hours <= 6:
        return "초기(6시간 이하)"
    if hours > 72:
        return "지연(72시간 초과)"
    return "중간(6~72시간)"


def _input_difference_bullets(scenario_a: dict[str, Any], scenario_b: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    if scenario_a.get("resource_level") != scenario_b.get("resource_level"):
        bullets.append(
            "가용 자원 수준은 "
            f"A={RESOURCE_LABELS[str(scenario_a.get('resource_level', 'moderate'))]}, "
            f"B={RESOURCE_LABELS[str(scenario_b.get('resource_level', 'moderate'))]}입니다. "
            "자원이 더 제한된 쪽은 선별과 병목 관리 비중이 커집니다."
        )

    num_a = int(scenario_a.get("num_exposed", 0))
    num_b = int(scenario_b.get("num_exposed", 0))
    if (num_a >= 30) != (num_b >= 30) or (num_a >= 100) != (num_b >= 100) or abs(num_a - num_b) >= 20:
        bullets.append(
            f"잠재 노출 인원이 A={num_a}명, B={num_b}명으로 달라 "
            "다수 대상 쪽에서 처리량과 단계적 분류의 중요도가 더 커집니다."
        )

    if scenario_a.get("incident_scale") != scenario_b.get("incident_scale"):
        bullets.append(
            "사고 범위는 "
            f"A={SCALE_LABELS[str(scenario_a.get('incident_scale', 'local'))]}, "
            f"B={SCALE_LABELS[str(scenario_b.get('incident_scale', 'local'))]}입니다. "
            "광역·국가 규모 쪽에서 기관 간 조정 부담이 더 커집니다."
        )

    if scenario_a.get("exposure_known") != scenario_b.get("exposure_known"):
        bullets.append(
            "노출 정보의 명확성이 달라 "
            "정보가 불명확한 쪽은 문진·추적·수동 검토 비중이 더 커집니다."
        )

    if scenario_a.get("internal_contamination_suspected") != scenario_b.get("internal_contamination_suspected"):
        bullets.append("내부 오염 가능성 차이 때문에 내부 평가 경로를 병행해야 하는지 여부가 달라집니다.")

    if scenario_a.get("partial_body_suspected") != scenario_b.get("partial_body_suspected"):
        bullets.append("부분피폭 가능성 차이 때문에 전신선량 해석 전제가 달라질 수 있습니다.")

    if scenario_a.get("symptom_severity") != scenario_b.get("symptom_severity"):
        bullets.append(
            "증상 수준은 "
            f"A={SYMPTOM_LABELS[str(scenario_a.get('symptom_severity', 'none'))]}, "
            f"B={SYMPTOM_LABELS[str(scenario_b.get('symptom_severity', 'none'))]}입니다. "
            "임상 우선 여부와 재평가 강도가 달라질 수 있습니다."
        )

    hour_a = float(scenario_a.get("elapsed_hours", 0))
    hour_b = float(scenario_b.get("elapsed_hours", 0))
    if _hour_window_label(hour_a) != _hour_window_label(hour_b) or abs(hour_a - hour_b) >= 24:
        bullets.append(
            f"시간 창이 A={_hour_window_label(hour_a)}, B={_hour_window_label(hour_b)}로 달라 "
            "재채질 시점과 검사 적합성 해석이 달라질 수 있습니다."
        )

    if not bullets:
        bullets.append("입력 차이는 크지 않으며, 현재 비교에서는 같은 성격의 시나리오를 보고 있습니다.")
    return bullets[:4]


def _decision_difference_bullets(
    scenario_a: dict[str, Any],
    scenario_b: dict[str, Any],
    ev_a: EvaluationResult,
    ev_b: EvaluationResult,
) -> list[str]:
    bullets: list[str] = []
    if ev_a.synthesized_priority != ev_b.synthesized_priority:
        bullets.append(
            "대응 우선순위는 "
            f"A={_priority_meta(ev_a.synthesized_priority)['label']}, "
            f"B={_priority_meta(ev_b.synthesized_priority)['label']}입니다. "
            "먼저 자원을 투입해야 하는 시나리오가 갈립니다."
        )

    strategy_a = _dominant_strategy(ev_a)
    strategy_b = _dominant_strategy(ev_b)
    if strategy_a != strategy_b:
        bullets.append(f"운영 초점이 A={strategy_a}, B={strategy_b}로 갈려 서로 다른 대응 전략이 요구됩니다.")

    resource_a, _, _ = _resource_pressure(scenario_a, ev_a)
    resource_b, _, _ = _resource_pressure(scenario_b, ev_b)
    if resource_a != resource_b:
        bullets.append(
            f"자원 압력은 A={resource_a}, B={resource_b}입니다. "
            "실험실 처리량과 연계기관 조정 강도가 달라집니다."
        )

    uncertainty_a, _ = _rh.uncertainty_level(scenario_a, ev_a)
    uncertainty_b, _ = _rh.uncertainty_level(scenario_b, ev_b)
    if uncertainty_a != uncertainty_b:
        bullets.append(
            f"불확실성 수준은 A={uncertainty_a}, B={uncertainty_b}입니다. "
            "추가 확인과 수동 검토 필요성이 다릅니다."
        )

    rules_a = {f"{t.rule_id}({t.title})" for t in ev_a.triggered}
    rules_b = {f"{t.rule_id}({t.title})" for t in ev_b.triggered}
    only_a = sorted(rules_a - rules_b)
    only_b = sorted(rules_b - rules_a)
    if only_a or only_b:
        pieces: list[str] = []
        if only_a:
            pieces.append("A에만 " + ", ".join(only_a[:2]))
        if only_b:
            pieces.append("B에만 " + ", ".join(only_b[:2]))
        bullets.append("적용 규칙도 다릅니다: " + " / ".join(pieces) + ".")

    if not bullets:
        bullets.append("두 시나리오의 판단 결과는 비슷하며, 차이는 세부 운영 조정 수준에 머뭅니다.")
    return bullets[:4]


def _markdown_bullets(items: list[str]) -> str:
    rows = [f"- {item}" for item in items if str(item).strip()]
    return "\n".join(rows) if rows else "- 없음"


def _markdown_numbered(items: list[str]) -> str:
    rows = [f"{i}. {item}" for i, item in enumerate([x for x in items if str(x).strip()], start=1)]
    return "\n".join(rows) if rows else "1. 없음"


def _build_single_report_markdown(scenario: dict[str, Any], ev: EvaluationResult) -> str:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    priority_meta = _priority_meta(ev.synthesized_priority)
    resource_level, _, resource_detail = _resource_pressure(scenario, ev)
    uncertainty_level, uncertainty_detail = _rh.uncertainty_level(scenario, ev)
    pairs = _scenario_summary_pairs(scenario)
    pair_lines = "\n".join(f"- {label}: {value}" for label, value in pairs)
    actions = _rh.recommended_next_actions(scenario, ev, max_items=5)
    resource_items = _resource_allocation_bullets(scenario, ev)
    rule_lines = [f"{t.rule_id} — {t.title}" for t in ev.triggered] or ["발화 규칙 없음"]
    return f"""# 방사선 비상 대응 시나리오 보고서

- 생성 시각: {generated_at}
- 대응 우선순위: {priority_meta["label"]}
- 운영 초점: {_dominant_strategy(ev)}
- 자원 압력: {resource_level}
- 불확실성: {uncertainty_level} ({uncertainty_detail})

## 입력 시나리오
{pair_lines}

## 현재 대응 판단
{_decision_takeaway(scenario, ev)}

## 권장 방향
{ev.biodosimetry_direction or "자동 권고 없음"}

## 바로 검토할 조치
{_markdown_numbered(actions)}

## 자원 배분 포인트
{_markdown_bullets(resource_items)}

## 왜 이런 판단이 나왔나
{_markdown_bullets(_rh.why_recommendation_bullets(scenario, ev))}

## 불확실성과 주의
{_markdown_bullets(_rh.uncertainty_factors(scenario, ev))}

## 적용 규칙
{_markdown_bullets(rule_lines)}

## 근거 상태
- {'문헌 대조가 필요한 규칙이 포함되어 있습니다.' if _rh.needs_confirmation_any(ev) else '현재 규칙 집합 기준으로 정리된 결과입니다.'}
- 자원 압력 해석: {resource_detail}
"""


def _build_compare_report_markdown(
    scenario_a: dict[str, Any],
    scenario_b: dict[str, Any],
    ev_a: EvaluationResult,
    ev_b: EvaluationResult,
) -> str:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    scenario_a_lines = "\n".join(f"- {label}: {value}" for label, value in _scenario_summary_pairs(scenario_a))
    scenario_b_lines = "\n".join(f"- {label}: {value}" for label, value in _scenario_summary_pairs(scenario_b))
    return f"""# 방사선 비상 대응 A/B 비교 보고서

- 생성 시각: {generated_at}
- 비교 해석: {_comparison_takeaway(scenario_a, scenario_b, ev_a, ev_b)}

## 시나리오 A
{scenario_a_lines}

- 대응 우선순위: {_priority_meta(ev_a.synthesized_priority)['label']}
- 운영 초점: {_dominant_strategy(ev_a)}
- 자원 압력: {_resource_pressure(scenario_a, ev_a)[0]}
- 불확실성: {_rh.uncertainty_level(scenario_a, ev_a)[0]}

## 시나리오 B
{scenario_b_lines}

- 대응 우선순위: {_priority_meta(ev_b.synthesized_priority)['label']}
- 운영 초점: {_dominant_strategy(ev_b)}
- 자원 압력: {_resource_pressure(scenario_b, ev_b)[0]}
- 불확실성: {_rh.uncertainty_level(scenario_b, ev_b)[0]}

## 입력 차이 설명
{_markdown_bullets(_input_difference_bullets(scenario_a, scenario_b))}

## 판단 차이 설명
{_markdown_bullets(_decision_difference_bullets(scenario_a, scenario_b, ev_a, ev_b))}

## 시나리오 A 바로 검토할 조치
{_markdown_numbered(_rh.recommended_next_actions(scenario_a, ev_a, max_items=4))}

## 시나리오 B 바로 검토할 조치
{_markdown_numbered(_rh.recommended_next_actions(scenario_b, ev_b, max_items=4))}
"""


def render_single_export_tools(scenario: dict[str, Any], ev: EvaluationResult) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    report = _build_single_report_markdown(scenario, ev)
    c1, c2 = st.columns((1.2, 2))
    with c1:
        st.download_button(
            "결과 보고서 저장 (.md)",
            data=report,
            file_name=f"single_scenario_report_{stamp}.md",
            mime="text/markdown",
            use_container_width=True,
            key="single_report_download",
        )
    with c2:
        st.caption("현재 조회 결과를 마크다운 보고서로 내려받아 발표 자료나 과제 정리에 그대로 사용할 수 있습니다.")


def render_compare_export_tools(
    scenario_a: dict[str, Any],
    scenario_b: dict[str, Any],
    ev_a: EvaluationResult,
    ev_b: EvaluationResult,
) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    report = _build_compare_report_markdown(scenario_a, scenario_b, ev_a, ev_b)
    c1, c2 = st.columns((1.2, 2))
    with c1:
        st.download_button(
            "비교 보고서 저장 (.md)",
            data=report,
            file_name=f"compare_scenarios_report_{stamp}.md",
            mime="text/markdown",
            use_container_width=True,
            key="compare_report_download",
        )
    with c2:
        st.caption("A/B 비교 결과와 차이 설명을 한 번에 정리한 보고서를 내려받을 수 있습니다.")


def render_reference_expanders(
    scenario: dict[str, Any],
    ev: EvaluationResult,
    guidelines_data: dict[str, Any],
) -> None:
    """전문가용 참고자료."""
    with st.expander("왜 이런 판단이 나왔는가? — 상황 신호와 적용 규칙", expanded=False):
        for line in _rh.why_recommendation_bullets(scenario, ev):
            st.markdown(f"- {line}")

    with st.expander("근거 확인용 PDF 검색 키워드", expanded=False):
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
    st.caption("규칙 JSON 상세 — 편집·검증용")
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
    st.markdown("### 시나리오 비교 보드")
    render_compare_export_tools(scenario_a, scenario_b, ev_a, ev_b)
    st.markdown("")
    st.markdown(
        f"""
        <div class="compare-callout">
            <strong>비교 해석</strong><br>
            {html.escape(_comparison_takeaway(scenario_a, scenario_b, ev_a, ev_b))}
        </div>
        """,
        unsafe_allow_html=True,
    )

    diff_left, diff_right = st.columns(2)
    with diff_left:
        with st.container(border=True):
            st.markdown("#### 판단 차이 설명")
            for line in _decision_difference_bullets(scenario_a, scenario_b, ev_a, ev_b):
                st.markdown(f"- {line}")
    with diff_right:
        with st.container(border=True):
            st.markdown("#### 입력 차이 설명")
            for line in _input_difference_bullets(scenario_a, scenario_b):
                st.markdown(f"- {line}")

    la, da = _rh.uncertainty_level(scenario_a, ev_a)
    lb, db = _rh.uncertainty_level(scenario_b, ev_b)
    ra, _, rda = _resource_pressure(scenario_a, ev_a)
    rb, _, rdb = _resource_pressure(scenario_b, ev_b)
    na = _rh.recommended_next_actions(scenario_a, ev_a, max_items=3)
    nb = _rh.recommended_next_actions(scenario_b, ev_b, max_items=3)

    h, ca, cb = st.columns((0.9, 1, 1))
    with h:
        st.caption("항목")
    with ca:
        st.markdown("**시나리오 A**")
    with cb:
        st.markdown("**시나리오 B**")

    def row(label: str, va: str, vb: str) -> None:
        x, ya, yb = st.columns((0.9, 1, 1))
        with x:
            st.markdown(f"**{label}**")
        with ya:
            with st.container(border=True):
                st.markdown(va)
        with yb:
            with st.container(border=True):
                st.markdown(vb)

    row("우선순위", _priority_meta(ev_a.synthesized_priority)["label"], _priority_meta(ev_b.synthesized_priority)["label"])
    row("운영 초점", _dominant_strategy(ev_a), _dominant_strategy(ev_b))
    row("권장 방향", _rh.card_direction_text(ev_a, 150), _rh.card_direction_text(ev_b, 150))
    row("자원 압력", f"{ra}\n\n{rda}", f"{rb}\n\n{rdb}")
    row("불확실성", f"{la}\n\n{da}", f"{lb}\n\n{db}")
    row("다음 조치", _rh.next_actions_display_text(na), _rh.next_actions_display_text(nb))
    row("발화 규칙 수", str(len(ev_a.triggered)), str(len(ev_b.triggered)))


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
        try:
            doc = load_pdf_text(file_name=uf.name, data=blob)
        except Exception as exc:
            detail = " ".join(str(exc).split()) or exc.__class__.__name__
            st.error(f"{uf.name}: PDF를 읽을 수 없습니다. 파일이 손상되었거나 구조가 올바르지 않을 수 있습니다. ({detail})")
            continue
        if total_char_count(doc) == 0:
            st.warning(f"{uf.name}: 추출된 텍스트가 거의 없습니다. 스캔본이면 OCR 후 검색하세요.")
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
    inject_app_styles()
    render_project_header()
    _render_flash_message()

    with st.expander("면책 및 사용 범위", expanded=False):
        st.caption(
            "규칙 기반·로컬 프로토타입. **의료 진단·치료 지시 아님.** "
            "ML·영상·DB·로그인 없음."
        )

    rules_path = default_rules_path()
    rules_data = _cached_rules(str(rules_path), rules_path.stat().st_mtime)
    guidelines_path = default_guidelines_path(rules_data)
    guidelines_data = _cached_guidelines(str(guidelines_path), guidelines_path.stat().st_mtime)
    saved_scenarios_path = default_saved_scenarios_path()

    mode = st.radio(
        "분석 모드",
        options=["단일 시나리오 평가", "시나리오 비교"],
        horizontal=True,
    )

    if mode == "단일 시나리오 평가":
        st.sidebar.caption("값을 정한 뒤 `분석 실행`을 눌러 오른쪽 대시보드를 갱신합니다.")
        with st.sidebar.form("single_scenario_query_form", clear_on_submit=False):
            scenario_sidebar = collect_scenario(key_prefix=None, container=st, show_title=True)
            b1, b2 = st.columns(2)
            with b1:
                run_clicked = st.form_submit_button("분석 실행", type="primary", use_container_width=True)
            with b2:
                reset_clicked = st.form_submit_button(
                    "초기화",
                    use_container_width=True,
                    on_click=_reset_single_analysis_state,
                )

        if reset_clicked:
            st.rerun()
        if run_clicked:
            st.session_state[SINGLE_ANALYSIS_STATE_KEY] = scenario_sidebar

        analyzed_single = st.session_state.get(SINGLE_ANALYSIS_STATE_KEY)
        render_single_saved_scenarios_panel(analyzed_single, saved_scenarios_path)
        if analyzed_single is None:
            st.info("왼쪽에서 시나리오를 입력한 뒤 `분석 실행`을 눌러주세요. 결과는 마지막으로 조회한 시나리오 기준으로 고정됩니다.")
        else:
            st.caption("현재 화면은 마지막으로 조회한 시나리오 기준입니다.")
            ev_sidebar = evaluate(analyzed_single, rules_data, guidelines_data)
            render_single_scenario_dashboard(analyzed_single, ev_sidebar, guidelines_data)
    else:
        st.sidebar.markdown("### 비교 모드 안내")
        st.sidebar.caption("본문에서 A/B 시나리오를 입력하고 `비교 실행`을 눌러 결과를 고정합니다.")
        st.markdown("### A/B 시나리오 입력")
        st.caption("서로 다른 사고 규모, 자원 수준, 증상 입력을 넣고 `비교 실행`을 눌러 전략 차이를 확인합니다.")
        with st.form("compare_scenario_query_form", clear_on_submit=False):
            u1, u2 = st.columns(2)
            with u1:
                st.markdown("#### 시나리오 A")
                sa = collect_scenario(key_prefix="a_", container=st, show_title=False)
            with u2:
                st.markdown("#### 시나리오 B")
                sb = collect_scenario(key_prefix="b_", container=st, show_title=False)
            b1, b2 = st.columns(2)
            with b1:
                compare_clicked = st.form_submit_button("비교 실행", type="primary", use_container_width=True)
            with b2:
                reset_clicked = st.form_submit_button(
                    "초기화",
                    use_container_width=True,
                    on_click=_reset_compare_analysis_state,
                )

        if reset_clicked:
            st.rerun()
        if compare_clicked:
            st.session_state[COMPARE_ANALYSIS_A_STATE_KEY] = sa
            st.session_state[COMPARE_ANALYSIS_B_STATE_KEY] = sb

        analyzed_a = st.session_state.get(COMPARE_ANALYSIS_A_STATE_KEY)
        analyzed_b = st.session_state.get(COMPARE_ANALYSIS_B_STATE_KEY)
        render_compare_saved_scenarios_panel(analyzed_a, analyzed_b, saved_scenarios_path)
        if analyzed_a is None or analyzed_b is None:
            st.info("시나리오 A와 B를 입력한 뒤 `비교 실행`을 눌러주세요. 결과는 마지막으로 조회한 비교 기준으로 유지됩니다.")
        else:
            st.caption("현재 비교 보드는 마지막으로 실행한 A/B 시나리오 기준입니다.")
            ev_a = evaluate(analyzed_a, rules_data, guidelines_data)
            ev_b = evaluate(analyzed_b, rules_data, guidelines_data)
            st.divider()
            render_scenario_comparison(analyzed_a, analyzed_b, ev_a, ev_b)
            st.divider()
            tab_a, tab_b, tab_pdf = st.tabs(["A 전문가용 상세", "B 전문가용 상세", "PDF 근거 확인"])
            with tab_a:
                render_reference_expanders(analyzed_a, ev_a, guidelines_data)
                render_rule_detail_expanders(ev_a)
            with tab_b:
                render_reference_expanders(analyzed_b, ev_b, guidelines_data)
                render_rule_detail_expanders(ev_b)
            with tab_pdf:
                scenario_hint = analyzed_a if _priority_rank(ev_a.synthesized_priority) <= _priority_rank(ev_b.synthesized_priority) else analyzed_b
                ev_hint = ev_a if scenario_hint is analyzed_a else ev_b
                _render_pdf_lookup_tab(scenario_hint, ev_hint)

    st.caption(f"규칙 파일: {rules_path.name} · 지침 파일: {guidelines_path.name}")


if __name__ == "__main__":
    main()

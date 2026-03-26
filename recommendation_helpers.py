"""
권고 화면용 보조 로직 (Streamlit과 분리).

비프로그래머용 설명:
- 규칙 엔진이 만든 결과(ev)와 사용자가 넣은 시나리오 값을 받아,
  ‘왜 이런 권고인지’, ‘다음에 무엇을 할지’, ‘불확실성은 무엇인지’ 를 짧은 문장으로 만듭니다.
- rules.json 의 규칙 id(R001 …)마다 ‘다음 조치’ 문장을 미리 적어 두었습니다. 규칙을 바꾸면 여기도 맞춰 고치세요.
"""

from __future__ import annotations

from typing import Any, Mapping

from rule_engine import EvaluationResult, TriggeredRuleView

# 규칙 id → (운영·계획 관점의 다음 조치 문장들). rules.json 의 id 와 일치해야 합니다.
NEXT_ACTIONS_BY_RULE: dict[str, tuple[str, ...]] = {
    "R001": (
        "선별(triage) 중심의 생물학적 선량평가 워크플로를 우선 검토합니다.",
        "처리량 병목을 가정하고 핵심·지정 실험실과 일정·역할을 사전 조율합니다.",
    ),
    "R002": (
        "광역·다인원 대응에서 정보·표본·데이터 흐름을 표준화할지 검토합니다.",
        "현장 분류·문진·추적 절차를 문서화하고 책임 기관을 명확히 합니다.",
    ),
    "R003": (
        "내부 오염 가능성을 전제로 체외계측·배설 평가 등 경로를 지침과 대조합니다.",
        "혈액 기반 결과만으로 전체 피폭을 단정하지 않도록 주의합니다.",
    ),
    "R004": (
        "부분피폭을 전제로 물리·임상 정보와 병행한 해석 계획을 둡니다.",
        "전신 동등선량 가정이 성립하는지 전문가 검토를 예약합니다.",
    ),
    "R005": (
        "중증 소견이 있으면 의료기관 응급·임상 경로를 최우선으로 둡니다.",
        "생물학적 선량평가는 임상이 안정된 뒤·병행 가능할 때 계획합니다.",
    ),
    "R006": (
        "노출 정보 공백을 줄이기 위해 문진·식별·우선순위 기준을 합의합니다.",
        "검사 대상을 단계화(선별→확인)하는 전략을 검토합니다.",
    ),
    "R007": (
        "경과 시간이 짧으면 재채질·재평가 시점을 프로토콜과 함께 잡습니다.",
        "노출 시각 불명 시 ‘경과 시간’ 해석 한계를 기록해 둡니다.",
    ),
    "R008": (
        "인원·자원 여건이 맞으면 정밀 검사를 일정에 넣되 품질·리드타임을 확인합니다.",
    ),
    "R009": (
        "광역 사고에서 자원이 낮을 때 운송·통신·검사 병목을 점검합니다.",
        "현장에서 가능한 최소 검사 세트와 원거리 연계를 정합니다.",
    ),
    "R010": (
        "소규모라도 지역 자원이 낮으면 검체 운송·저장·연계 실험실을 미리 확인합니다.",
    ),
}


def scenario_condition_tags(scenario: Mapping[str, Any]) -> list[str]:
    """입력값만 보고 ‘어떤 상황 신호가 켜졌는지’ 짧은 한글 태그로 만듭니다."""
    tags: list[str] = []
    scale = str(scenario.get("incident_scale", ""))
    if scale in ("national", "international"):
        tags.append("국가·국제 규모 사고로 입력됨")
    elif scale == "regional":
        tags.append("광역 규모 사고로 입력됨")

    n = int(scenario.get("num_exposed", 0))
    if n >= 100:
        tags.append("잠재 노출 인원 100명 이상")
    elif n >= 30:
        tags.append("잠재 노출 인원 30명 이상")

    h = float(scenario.get("elapsed_hours", 0))
    if h > 24:
        tags.append("노출 후 경과 24시간 초과")
    if h <= 6:
        tags.append("노출 직후 6시간 이내(초기 구간)")

    if scenario.get("exposure_known") is not True:
        tags.append("노출 정보 불명·미확인")

    if scenario.get("partial_body_suspected") is True:
        tags.append("부분피폭(국소) 의심")

    if scenario.get("internal_contamination_suspected") is True:
        tags.append("내부 오염 의심")

    if scenario.get("resource_level") == "minimal":
        tags.append("실험실·인력 자원이 제한적")

    sev = str(scenario.get("symptom_severity", "none"))
    if sev in ("moderate", "severe"):
        tags.append("증상 심각도 입력: 중등도 이상(임상은 의료기관)")

    return tags


def triggered_rule_tags(triggered: tuple[TriggeredRuleView, ...]) -> list[str]:
    """발화된 규칙을 ‘태그’ 형태로 나열합니다."""
    return [f"규칙 {t.rule_id} 발화: {t.title}" for t in triggered]


def why_recommendation_bullets(scenario: Mapping[str, Any], ev: EvaluationResult) -> list[str]:
    """‘왜 이 권고인가’ 섹션용 불릿: 시나리오 신호 + 발화 규칙(중복 제거)."""
    seen: set[str] = set()
    out: list[str] = []
    for line in scenario_condition_tags(scenario) + triggered_rule_tags(ev.triggered):
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    if not out:
        out.append("현재 입력에서 규칙이 발화하지 않았습니다. rules.json·입력을 확인하세요.")
    return out


def uncertainty_factors(scenario: Mapping[str, Any], ev: EvaluationResult) -> list[str]:
    """불확실성·해석 한계 요인(체크리스트)."""
    factors: list[str] = []
    if scenario.get("exposure_known") is not True:
        factors.append("노출 시각·경로·선량 정보가 불완전할 수 있음")
    if float(scenario.get("elapsed_hours", 0)) > 72:
        factors.append("경과 시간이 길면 일부 검사의 적합성·해석이 달라질 수 있음")
    if float(scenario.get("elapsed_hours", 0)) <= 6:
        factors.append("초기 구간은 채질·지표 가독성에 제한이 있을 수 있음")
    if scenario.get("partial_body_suspected") is True:
        factors.append("부분피폭은 전신 동등선량 가정이 깨질 수 있음")
    if scenario.get("internal_contamination_suspected") is True:
        factors.append("내부 오염이 있으면 혈액 지표만으로 전체 피폭을 설명하기 어려울 수 있음")
    if scenario.get("resource_level") == "minimal":
        factors.append("자원 제한 시 검사 선택·처리량 병목이 커질 수 있음")
    if int(scenario.get("num_exposed", 0)) >= 50:
        factors.append("다수 대상에서는 선별·단계적 접근 오차가 커질 수 있음")
    for c in ev.cautions:
        if c.startswith("[시스템]"):
            continue
        if c not in factors:
            factors.append(c)
    if not ev.triggered:
        factors.append("자동 규칙이 매칭되지 않아 권고 근거가 비어 있음 — 수동 검토 필요")
    return factors


def uncertainty_level(scenario: Mapping[str, Any], ev: EvaluationResult) -> tuple[str, str]:
    """
    비교 탭용 불확실성 수준(높음/중간/낮음)과 한 줄 설명.
    단순 점수 모델이며 임상·물리 평가를 대체하지 않습니다.
    """
    score = 0
    bits: list[str] = []
    if scenario.get("exposure_known") is not True:
        score += 2
        bits.append("노출미확인")
    if scenario.get("internal_contamination_suspected") is True:
        score += 2
        bits.append("내부오염의심")
    if scenario.get("partial_body_suspected") is True:
        score += 1
        bits.append("부분피폭의심")
    if scenario.get("resource_level") == "minimal":
        score += 1
        bits.append("자원제한")
    h = float(scenario.get("elapsed_hours", 0))
    if h > 72 or h <= 6:
        score += 1
        bits.append("시간창")
    if str(scenario.get("symptom_severity")) in ("moderate", "severe"):
        score += 1
        bits.append("증상입력")
    if int(scenario.get("num_exposed", 0)) >= 50:
        score += 1
        bits.append("다인원")
    if not ev.triggered:
        score += 1
        bits.append("규칙미매칭")

    if score >= 6:
        label = "높음"
    elif score >= 3:
        label = "중간"
    else:
        label = "낮음"
    detail = ", ".join(bits) if bits else "입력이 비교적 단순"
    return label, detail


def recommended_next_actions(scenario: Mapping[str, Any], ev: EvaluationResult, *, max_items: int = 5) -> list[str]:
    """운영·계획 관점 다음 조치(의료 처지 지시 아님)."""
    collected: list[str] = []
    for t in ev.triggered:
        extra = NEXT_ACTIONS_BY_RULE.get(t.rule_id)
        if extra:
            collected.extend(extra)

    # 시나리오 기반 일반 조치(중복 제거 전에 의미 있는 것만)
    if scenario.get("exposure_known") is not True:
        collected.append("가능하면 노출 시각·경로·핵종 정보를 추가로 확보합니다.")
    if scenario.get("internal_contamination_suspected") is True:
        collected.append(
            "내부 오염 경로를 과소평가하지 않도록, 생물학적 선량평가 결과를 단독으로 해석하지 않습니다."
        )
    if scenario.get("resource_level") == "minimal" and int(scenario.get("num_exposed", 0)) >= 30:
        collected.append("전원 동일 검사보다 단계적·선별 중심 전략을 우선 검토합니다.")

    seen: set[str] = set()
    out: list[str] = []
    for line in collected:
        s = line.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_items:
            break

    if len(out) < 3 and ev.triggered:
        out.append("발화된 규칙의 `source_note` 를 공식 지침과 대조해 검증합니다.")
    while len(out) < 3:
        out.append("기관 SOP·법규·윤리 가이드에 따라 역할과 의사소통 경로를 확인합니다.")
        if len(out) >= 3:
            break
    return out[:max_items]


def suggested_pdf_keywords(scenario: Mapping[str, Any], ev: EvaluationResult) -> tuple[list[str], list[str]]:
    """
    PDF 검색용 영어 키워드 + 화면용 한글 ‘검토 개념’.
    영문 키워드는 IAEA 등 원문 PDF 검색에 맞춥니다.
    """
    en: set[str] = {
        "triage",
        "biodosimetry",
        "radiation emergency",
        "mass casualty",
    }
    ko: set[str] = {
        "선별(triage)",
        "생물학적 선량평가(biodosimetry)",
        "방사선 비상·대량 피해",
    }

    if scenario.get("internal_contamination_suspected") is True:
        en.update(["internal contamination", "bioassay", "in vivo counting"])
        ko.update(["내부 오염", "체외계측·배설 평가"])
    if scenario.get("partial_body_suspected") is True:
        en.update(["partial body", "heterogeneous exposure"])
        ko.update(["부분피폭·이질적 피폭"])
    if scenario.get("resource_level") == "minimal":
        en.update(["capacity", "laboratory surge"])
        ko.update(["실험실 처리량·역량"])
    if int(scenario.get("num_exposed", 0)) >= 50:
        en.update(["prioritization", "screening"])
        ko.update(["우선순위·선별 검사"])
    if float(scenario.get("elapsed_hours", 0)) > 24:
        en.update(["sampling time", "assay applicability"])
        ko.update(["채집 시점·검사 적합성"])

    for t in ev.triggered:
        if "내부" in t.title or "R003" == t.rule_id:
            en.add("internal contamination")
        if "부분" in t.title or "R004" == t.rule_id:
            en.add("partial body")
        if "다인원" in t.title or "자원" in t.title:
            en.add("triage")

    return sorted(en), sorted(ko)


def _truncate(text: str, max_len: int) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def needs_confirmation_any(ev: EvaluationResult) -> bool:
    """발화 규칙 중 하나라도 문헌 확인 전 상태인지."""
    return any(t.evidence_status == "needs_confirmation" for t in ev.triggered)


def card_priority_text(ev: EvaluationResult) -> str:
    if ev.synthesized_priority is None:
        return "(규칙 미매칭)"
    return ev.synthesized_priority.upper()


def uncertainty_emoji(level: str) -> str:
    return {"높음": "🔴", "중간": "🟠", "낮음": "🟢"}.get(level, "⚪")


def card_direction_text(ev: EvaluationResult, max_len: int = 320) -> str:
    return _truncate(ev.biodosimetry_direction or "(내용 없음)", max_len)


def card_assays_text(ev: EvaluationResult, max_lines: int = 4) -> str:
    if not ev.assay_options:
        return "(없음)"
    lines = list(ev.assay_options[:max_lines])
    if len(ev.assay_options) > max_lines:
        lines.append(f"… 외 {len(ev.assay_options) - max_lines}건")
    return "\n".join(f"• {x}" for x in lines)


def card_cautions_text(ev: EvaluationResult, max_lines: int = 4) -> str:
    if not ev.cautions:
        return "(없음)"
    lines = list(ev.cautions[:max_lines])
    if len(ev.cautions) > max_lines:
        lines.append(f"… 외 {len(ev.cautions) - max_lines}건")
    return "\n".join(f"• {x}" for x in lines)


def next_actions_display_text(actions: list[str]) -> str:
    return "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions))

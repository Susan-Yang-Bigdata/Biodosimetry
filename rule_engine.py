"""
규칙 엔진: rules.json + data/guidelines.json 을 읽어 시나리오에 맞는 권고를 만듭니다.
(화면 용어는 ‘생물학적 선량평가’이며, 규칙 JSON 필드명 `biodosimetry_direction` 은 호환용입니다.)

- 규칙 문장은 ‘사실’이 아니라, 지침 원칙(GP…)과 연결된 **가설적 정리**로 취급합니다.
- evidence_status 가 needs_confirmation 인 규칙은 문헌 대조 전까지 확정적 근거로 쓰지 않습니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class GuidelineSnippet:
    """guidelines.json 의 원칙 한 덩어리(화면에 그대로 보여 주기 좋게)."""

    principle_id: str
    title: str
    text: str
    principle_evidence_status: str
    documentation_hint: str


@dataclass(frozen=True)
class TriggeredRuleView:
    """발화된 규칙 한 건 + 연결된 지침 발췌."""

    rule_id: str
    title: str
    evidence_status: str
    guideline_snippets: tuple[GuidelineSnippet, ...]
    source_note: str
    when_snapshot: dict[str, Any]
    response_priority: str
    biodosimetry_direction: str
    assay_options: tuple[str, ...]
    cautions: tuple[str, ...]


@dataclass
class EvaluationResult:
    """한 시나리오에 대한 최종 요약 + 근거(발화 규칙들)."""

    triggered: tuple[TriggeredRuleView, ...] = ()
    synthesized_priority: str | None = None
    biodosimetry_direction: str = ""
    assay_options: tuple[str, ...] = ()
    cautions: tuple[str, ...] = ()
    reasoning_lines: tuple[str, ...] = ()


def load_rules_json(path: Path) -> dict[str, Any]:
    """rules.json 파일을 읽어 dict 로 만듭니다."""
    if not path.is_file():
        raise FileNotFoundError(f"규칙 파일을 찾을 수 없습니다: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rules.json 최상위는 { ... } 형태여야 합니다.")
    return data


def load_guidelines_json(path: Path) -> dict[str, Any]:
    """data/guidelines.json 을 읽어 dict 로 만듭니다."""
    if not path.is_file():
        raise FileNotFoundError(f"지침 파일을 찾을 수 없습니다: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("guidelines.json 최상위는 { ... } 형태여야 합니다.")
    return data


def default_rules_path() -> Path:
    """프로젝트 루트의 rules.json."""
    return Path(__file__).resolve().parent / "rules.json"


def default_guidelines_path(rules_data: Mapping[str, Any] | None = None) -> Path:
    """
    guidelines.json 위치. rules.json meta.guidelines_file 이 있으면 그 경로(프로젝트 루트 기준)를 씁니다.
    """
    root = Path(__file__).resolve().parent
    if rules_data:
        meta = rules_data.get("meta") or {}
        rel = str(meta.get("guidelines_file") or "data/guidelines.json")
        return (root / rel).resolve()
    return root / "data" / "guidelines.json"


def _principle_index(guidelines_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = guidelines_data.get("principles")
    if not isinstance(rows, list):
        raise ValueError("guidelines.json 에 'principles' 배열이 필요합니다.")
    out: dict[str, dict[str, Any]] = {}
    for p in rows:
        if not isinstance(p, dict):
            raise TypeError("principles[] 항목은 객체여야 합니다.")
        pid = str(p["id"])
        out[pid] = p
    return out


def _resolve_guideline_snippets(
    refs: list[Any],
    index: Mapping[str, dict[str, Any]],
) -> tuple[GuidelineSnippet, ...]:
    snippets: list[GuidelineSnippet] = []
    for raw in refs:
        pid = str(raw)
        if pid not in index:
            continue
        p = index[pid]
        snippets.append(
            GuidelineSnippet(
                principle_id=pid,
                title=str(p.get("title", "")),
                text=str(p.get("text", "")).strip(),
                principle_evidence_status=str(p.get("evidence_status", "unknown")),
                documentation_hint=str(p.get("documentation_hint", "")).strip(),
            )
        )
    return tuple(snippets)


def _scenario_values(scenario: Mapping[str, Any]) -> dict[str, Any]:
    keys = [
        "incident_scale",
        "elapsed_hours",
        "num_exposed",
        "exposure_known",
        "partial_body_suspected",
        "internal_contamination_suspected",
        "symptom_severity",
        "resource_level",
    ]
    missing = [k for k in keys if k not in scenario]
    if missing:
        raise KeyError(f"시나리오에 필수 키가 없습니다: {missing}")
    return {k: scenario[k] for k in keys}


def _matches_when(scenario: Mapping[str, Any], when: Mapping[str, Any]) -> bool:
    sm = _scenario_values(scenario)
    for key, expected in when.items():
        if key.endswith("_in"):
            base = key[: -len("_in")]
            if base not in sm:
                raise KeyError(f"알 수 없는 필드(_in): {base}")
            if not isinstance(expected, list):
                raise TypeError(f"{key} 는 JSON 배열이어야 합니다.")
            if sm[base] not in expected:
                return False
            continue

        if key == "num_exposed_min":
            if int(sm["num_exposed"]) < int(expected):
                return False
            continue
        if key == "num_exposed_max":
            if int(sm["num_exposed"]) > int(expected):
                return False
            continue
        if key == "elapsed_hours_min":
            if float(sm["elapsed_hours"]) < float(expected):
                return False
            continue
        if key == "elapsed_hours_max":
            if float(sm["elapsed_hours"]) > float(expected):
                return False
            continue

        if key not in sm:
            raise KeyError(f"알 수 없는 when 키: {key}")
        if sm[key] != expected:
            return False
    return True


def _priority_rank(order: list[str], priority: str) -> int:
    if priority in order:
        return order.index(priority)
    return len(order)


def _dedupe_texts(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def evaluate(
    scenario: Mapping[str, Any],
    rules_data: Mapping[str, Any],
    guidelines_data: Mapping[str, Any],
) -> EvaluationResult:
    """
    시나리오 한 건을 평가합니다.

    guidelines_data 는 guidelines.json 내용입니다. 규칙의 guideline_refs 가 여기서 텍스트로 풀립니다.
    """
    meta = rules_data.get("meta") or {}
    raw_rules = rules_data.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("rules.json 안에 'rules' 배열이 필요합니다.")

    order = list(meta.get("priority_order") or ["critical", "high", "medium", "low"])
    principle_index = _principle_index(guidelines_data)

    triggered: list[TriggeredRuleView] = []
    missing_guideline_refs: list[str] = []

    for block in raw_rules:
        if not isinstance(block, dict):
            raise TypeError("rules[] 의 각 항목은 { ... } 객체여야 합니다.")
        rule_id = str(block["id"])
        title = str(block.get("title", ""))
        source_note = str(block.get("source_note", ""))
        evidence_status = str(block.get("evidence_status") or "needs_confirmation")
        raw_refs = block.get("guideline_refs") or []
        if not isinstance(raw_refs, list):
            raise TypeError(f"{rule_id}: guideline_refs 는 배열이어야 합니다.")

        for r in raw_refs:
            rid = str(r)
            if rid not in principle_index:
                missing_guideline_refs.append(f"{rule_id}→{rid}")

        when = block.get("when") or {}
        then = block.get("then") or {}
        if not isinstance(when, dict) or not isinstance(then, dict):
            raise TypeError(f"{rule_id}: when/then 은 객체여야 합니다.")

        if not _matches_when(scenario, when):
            continue

        snippets = _resolve_guideline_snippets(raw_refs, principle_index)
        assays = tuple(str(x) for x in (then.get("assay_options") or []))
        cautions = tuple(str(x) for x in (then.get("cautions") or []))
        triggered.append(
            TriggeredRuleView(
                rule_id=rule_id,
                title=title,
                evidence_status=evidence_status,
                guideline_snippets=snippets,
                source_note=source_note,
                when_snapshot=dict(when),
                response_priority=str(then["response_priority"]),
                biodosimetry_direction=str(then.get("biodosimetry_direction", "")).strip(),
                assay_options=assays,
                cautions=cautions,
            )
        )

    system_cautions: list[str] = []
    if missing_guideline_refs:
        system_cautions.append(
            "[시스템] 일부 guideline_refs 가 guidelines.json 에 없습니다: "
            + ", ".join(sorted(set(missing_guideline_refs)))
        )

    if not triggered:
        base = [
            "자동 권고가 없습니다. 공식 지침(IAEA EPR-Biodosimetry 등, 생물학적 선량평가 관련)과 수동 검토가 필요합니다.",
            "설계 원칙 전문은 화면의 ‘지침·설계 원칙’에서 확인할 수 있습니다.",
        ]
        return EvaluationResult(
            triggered=tuple(),
            synthesized_priority=None,
            biodosimetry_direction="조건을 만족하는 규칙이 없습니다. rules.json 을 보완하거나 입력을 바꿔 보세요.",
            assay_options=tuple(),
            cautions=_dedupe_texts(base + system_cautions),
            reasoning_lines=tuple(),
        )

    any_needs_confirmation = any(t.evidence_status == "needs_confirmation" for t in triggered)
    if any_needs_confirmation:
        system_cautions.append(
            "[시스템] 발화된 규칙에 ‘needs_confirmation’이 포함되어 있습니다. "
            "공식 매뉴얼·SOP로 검증하기 전에는 확정 근거로 사용하지 마세요."
        )

    best_priority = min(
        (t.response_priority for t in triggered),
        key=lambda p: _priority_rank(order, p),
    )

    directions: list[str] = []
    assays: list[str] = []
    cautions: list[str] = []
    reasoning_lines: list[str] = []
    for t in triggered:
        if t.biodosimetry_direction:
            directions.append(f"[{t.rule_id}] {t.biodosimetry_direction}")
        assays.extend(t.assay_options)
        cautions.extend(t.cautions)
        tag = "needs_confirmation" if t.evidence_status == "needs_confirmation" else t.evidence_status
        reasoning_lines.append(f"{t.rule_id} — {t.title} ({tag})")

    cautions.extend(system_cautions)

    return EvaluationResult(
        triggered=tuple(triggered),
        synthesized_priority=best_priority,
        biodosimetry_direction="\n\n".join(directions),
        assay_options=_dedupe_texts(list(assays)),
        cautions=_dedupe_texts(list(cautions)),
        reasoning_lines=tuple(reasoning_lines),
    )

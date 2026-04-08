"""
시나리오 저장/불러오기용 간단한 JSON 저장소.

- 단일 시나리오와 A/B 비교 시나리오를 프로젝트 폴더 안에 저장합니다.
- 이름이 같은 항목을 저장하면 최신 값으로 덮어씁니다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def default_saved_scenarios_path(base_dir: Path | None = None) -> Path:
    root = base_dir if base_dir is not None else Path(__file__).resolve().parent
    return root / "data" / "saved_scenarios.json"


def _empty_store() -> dict[str, list[dict[str, Any]]]:
    return {"single": [], "compare": []}


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_single_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    scenario = raw.get("scenario")
    if not name or not isinstance(scenario, dict):
        return None
    return {
        "name": name,
        "scenario": deepcopy(scenario),
        "saved_at": str(raw.get("saved_at", "")).strip(),
    }


def _normalize_compare_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    scenario_a = raw.get("scenario_a")
    scenario_b = raw.get("scenario_b")
    if not name or not isinstance(scenario_a, dict) or not isinstance(scenario_b, dict):
        return None
    return {
        "name": name,
        "scenario_a": deepcopy(scenario_a),
        "scenario_b": deepcopy(scenario_b),
        "saved_at": str(raw.get("saved_at", "")).strip(),
    }


def load_saved_scenarios(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    target = path if path is not None else default_saved_scenarios_path()
    if not target.is_file():
        return _empty_store()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()

    singles_raw = raw.get("single")
    compares_raw = raw.get("compare")
    singles = singles_raw if isinstance(singles_raw, list) else []
    compares = compares_raw if isinstance(compares_raw, list) else []

    normalized_singles = [item for item in (_normalize_single_entry(x) for x in singles) if item is not None]
    normalized_compares = [item for item in (_normalize_compare_entry(x) for x in compares) if item is not None]
    return {"single": normalized_singles, "compare": normalized_compares}


def _write_store(data: Mapping[str, Any], path: Path | None = None) -> None:
    target = path if path is not None else default_saved_scenarios_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_single_scenario(name: str, scenario: Mapping[str, Any], path: Path | None = None) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("시나리오 이름이 비어 있습니다.")
    store = load_saved_scenarios(path)
    entry = {
        "name": clean_name,
        "scenario": deepcopy(dict(scenario)),
        "saved_at": _iso_now(),
    }
    rest = [item for item in store["single"] if item["name"] != clean_name]
    store["single"] = [entry, *rest]
    _write_store(store, path)


def save_compare_scenario(
    name: str,
    scenario_a: Mapping[str, Any],
    scenario_b: Mapping[str, Any],
    path: Path | None = None,
) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("비교 시나리오 이름이 비어 있습니다.")
    store = load_saved_scenarios(path)
    entry = {
        "name": clean_name,
        "scenario_a": deepcopy(dict(scenario_a)),
        "scenario_b": deepcopy(dict(scenario_b)),
        "saved_at": _iso_now(),
    }
    rest = [item for item in store["compare"] if item["name"] != clean_name]
    store["compare"] = [entry, *rest]
    _write_store(store, path)

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .agent.config import get_settings
from .eval_cases import CASES, EvalCase


def _source_revision(root: Path) -> tuple[str | None, bool | None]:
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout
        return revision, not bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        return None, None


def reference_rows(db_path: str, case: EvalCase) -> list[tuple]:
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        return conn.execute(case.reference_sql).fetchall()


def _same_value(expected, actual) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        return abs(Decimal(str(expected)) - Decimal(str(actual))) <= Decimal("0.005")
    return expected == actual


def _same_row(expected: tuple, actual: tuple) -> bool:
    remaining = list(actual)
    for value in expected:
        found = next((i for i, candidate in enumerate(remaining) if _same_value(value, candidate)), None)
        if found is None:
            return False
        remaining.pop(found)
    return True


def compare_rows(expected: list[tuple], actual: list[tuple], mode: str) -> bool:
    if mode != "contains" and len(expected) != len(actual):
        return False
    if mode == "exact":
        return all(_same_row(a, b) for a, b in zip(expected, actual, strict=True))
    remaining = list(actual)
    for row in expected:
        found = next((i for i, candidate in enumerate(remaining) if _same_row(row, candidate)), None)
        if found is None:
            return False
        remaining.pop(found)
    return True


def evaluate(
    agent=None, repeats: int = 1, case_ids: set[str] | None = None,
    db_path: str | None = None,
) -> dict:
    settings = get_settings() if agent is not None else None
    root = Path(__file__).resolve().parents[1]
    database = Path(db_path or (settings.db_abspath if settings else
                                  root / "data" / "anexo_desafio_1.db"))
    revision, clean = _source_revision(root)
    lock = root / "requirements.lock"
    selected = [case for case in CASES if case_ids is None or case.id in case_ids]
    if not selected:
        raise ValueError("Nenhuma pergunta corresponde aos IDs informados.")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": settings.model if settings else None,
        "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        "environment": {
            "python": platform.python_version(),
            "os": platform.system(),
            "architecture": platform.machine(),
            "git_commit": revision,
            "working_tree_clean": clean,
            "requirements_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
            if lock.exists() else None,
        },
        "model_config": {
            "provider": settings.provider,
            "model": settings.model,
            "temperature": settings.temperature,
            "max_model_calls": settings.max_model_calls,
            "requests_per_second": settings.requests_per_second,
            "max_estimated_cost_usd": settings.max_estimated_cost_usd,
            "max_repair_attempts": settings.max_repair_attempts,
            "row_limit": settings.row_limit,
            "sql_timeout_seconds": settings.sql_timeout_s,
        } if settings else None,
        "cases": [],
    }
    for case in selected:
        expected = reference_rows(str(database), case)
        item = {"id": case.id, "question": case.question, "reference_rows": expected, "runs": []}
        for _ in range(repeats if agent is not None else 0):
            started = time.monotonic()
            try:
                state = agent.invoke({"question": case.question, "trace": []})
                actual = state.get("result_rows") or []
                model_steps = [step.get("data") or {} for step in state.get("trace", [])
                               if step.get("step") == "chamada_modelo"]
                item["runs"].append({
                    "passed": state.get("answer_status") in {"confirmed", "assumption"}
                    and compare_rows(expected, actual, case.comparison),
                    "status": state.get("answer_status"),
                    "answer": state.get("answer"),
                    "rows": actual,
                    "sql": state.get("sql"),
                    "review_count": state.get("review_count", 0),
                    "repair_count": state.get("repair_count", 0),
                    "model_calls": len(model_steps),
                    "input_tokens": sum(step.get("input_tokens") or 0 for step in model_steps),
                    "output_tokens": sum(step.get("output_tokens") or 0 for step in model_steps),
                    "model_duration_seconds": round(sum(
                        step.get("duration_ms") or 0 for step in model_steps
                    ) / 1000, 2),
                    "estimated_cost_usd": round(sum(
                        step.get("estimated_cost_usd") or 0 for step in model_steps
                    ), 8) if any(step.get("estimated_cost_usd") is not None
                              for step in model_steps) else None,
                    "caveat": state.get("caveat"),
                    "evidence_issues": state.get("evidence_issues") or [],
                    "duration_seconds": round(time.monotonic() - started, 2),
                    "error": state.get("error"),
                })
            except Exception as exc:
                item["runs"].append({"passed": False, "error": type(exc).__name__,
                                      "duration_seconds": round(time.monotonic() - started, 2)})
        report["cases"].append(item)
    runs = [run for case in report["cases"] for run in case["runs"]]
    report["summary"] = {"cases": len(selected), "runs": len(runs),
                         "passed": sum(bool(run["passed"]) for run in runs)}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Avalia respostas contra SQL independente.")
    parser.add_argument("--live", action="store_true", help="Executa o modelo configurado no .env")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 5:
        parser.error("--repeats deve estar entre 1 e 5")
    agent = None
    if args.live:
        from .agent.graph import build_agent
        agent = build_agent()
    report = evaluate(agent, args.repeats, set(args.cases) if args.cases else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                               encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

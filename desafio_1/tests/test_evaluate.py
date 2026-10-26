from pathlib import Path

from desafio_1.eval_cases import CASES
from desafio_1.evaluate import compare_rows, evaluate, reference_rows

DB = Path(__file__).resolve().parents[2] / "data" / "anexo_desafio_1.db"


def test_reference_suite_covers_official_and_complex_cases():
    cases = {case.id: case for case in CASES}
    assert len(cases) >= 20
    assert reference_rows(str(DB), cases["whatsapp_2024"]) == [(17,)]
    assert reference_rows(str(DB), cases["campanha_lider"]) == [("Black Friday", 32)]
    assert reference_rows(str(DB), cases["reclamacoes_canal"]) == [
        ("Chat", 18), ("E-mail", 14), ("Telefone", 19),
    ]
    for case in CASES:
        assert reference_rows(str(DB), case), case.id


def test_row_comparison_preserves_category_metric_pairs():
    expected = [("Black Friday", 32), ("Volta às Aulas", 30)]
    assert compare_rows(expected, list(reversed(expected)), "unordered")
    assert not compare_rows(expected, [("Black Friday", 30), ("Volta às Aulas", 32)], "unordered")
    assert not compare_rows(expected, list(reversed(expected)), "exact")


def test_reference_only_needs_no_model():
    report = evaluate(case_ids={"whatsapp_2024"}, db_path=str(DB))
    assert report["summary"] == {"cases": 1, "runs": 0, "passed": 0}
    assert report["cases"][0]["reference_rows"] == [(17,)]
    assert len(report["database_sha256"]) == 64
    assert report["environment"]["python"]
    assert len(report["environment"]["requirements_lock_sha256"]) == 64
    assert report["model_config"] is None

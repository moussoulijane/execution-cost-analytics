"""Le rapport doit distinguer une analyse confirmatoire d'une confrontation descriptive."""

from types import SimpleNamespace

import pandas as pd
import pytest

from execution_cost_analytics import study_reporting


@pytest.mark.parametrize(
    ("data_type", "is_primary", "expected_scope"),
    [
        ("public_historical", False, "Cette confrontation historique ne comporte aucun test"),
        ("synthetic", False, "Cette sortie exploratoire ne comporte aucun test"),
        ("synthetic", True, "Le contraste principal est le seul test prévu comme principal"),
    ],
)
def test_report_inference_scope_matches_experiment_metadata(
    tmp_path, monkeypatch, data_type, is_primary, expected_scope
):
    monkeypatch.setattr(study_reporting, "_figures", lambda *args: None)
    comparisons = pd.DataFrame(
        [
            {
                "scenario": "low_volume",
                "strategy": "ADAPTIVE",
                "baseline": "VWAP",
                "impact_model": "sqrt",
                "deadline_mode": "common_deadline",
                "quantity_adv_ratio": 0.10,
                "is_primary": is_primary,
                "n_pairs": 17,
                "saving_bps": 0.1,
                "saving_ci_low": -0.1,
                "saving_ci_high": 0.3,
                "completion_delta_pp": 0.0,
                "completion_noninferiority_bound_pp": -1.0,
                "evidence": "uncertain_or_no_economic_saving",
            }
        ]
    )
    result = SimpleNamespace(
        summary=pd.DataFrame({"reconciliation_error": [0.0]}),
        aggregate=pd.DataFrame(),
        comparisons=comparisons,
        forecast_metrics=pd.DataFrame(),
        grid_check=pd.DataFrame({"passed": [True]}),
        sample_fills=pd.DataFrame(),
        metadata={"data_type": data_type},
    )

    report = study_reporting.write_study_report(result, tmp_path).read_text(encoding="utf-8")

    assert expected_scope in report
    if not is_primary:
        assert "Aucun contraste confirmatoire" in report
        assert "Le contraste principal est le seul test prévu comme principal" not in report

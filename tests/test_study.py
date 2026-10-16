"""Tests des unités d'inférence, du protocole et des transformations de stress."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics.data import generate_market_data
from execution_cost_analytics.study import (
    _design,
    default_protocol,
    grid_invariance_check,
    load_protocol,
    paired_comparison,
    run_study,
    transform_scenario,
)


def test_documented_protocol_matches_embedded_design():
    root = Path(__file__).resolve().parents[1]
    documented = json.loads((root / "docs/PROTOCOLE_V2.json").read_text(encoding="utf-8"))
    assert _design(documented) == default_protocol()
    training = {documented["training"]["seed"]}
    dev, test = set(documented["development_seeds"]), set(documented["test_seeds"])
    assert not training & dev and not training & test and not dev & test


def test_protocol_rejects_test_seed_reused_for_training(tmp_path):
    protocol = default_protocol()
    protocol["test_seeds"][0] = protocol["training"]["seed"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(ValueError, match="disjointes"):
        load_protocol(path)


def test_stress_changes_liquidity_without_revealing_future_or_changing_base():
    base = generate_market_data(n_days=1, n_buckets=26, seed=123)
    original = base.copy(deep=True)
    scenarios = default_protocol()["scenarios"]
    low = transform_scenario(base, scenarios["low_volume"])
    late = transform_scenario(base, scenarios["late_shift"])
    shutdown = transform_scenario(base, scenarios["midday_shutdown"])
    pd.testing.assert_frame_equal(base, original)
    np.testing.assert_allclose(low["mid_price"], base["mid_price"])
    np.testing.assert_array_equal(low["market_volume"], np.floor(base["market_volume"] * 0.55))
    assert late["market_volume"].sum() == base["market_volume"].sum()
    assert late["market_volume"].iloc[-5:].sum() > base["market_volume"].iloc[-5:].sum()
    assert shutdown["market_volume"].iloc[26 // 3 : 2 * 26 // 3].sum() == 0
    outside = np.r_[0 : 26 // 3, 2 * 26 // 3 : 26]
    np.testing.assert_array_equal(
        shutdown["market_volume"].iloc[outside], base["market_volume"].iloc[outside]
    )


def paired_frame():
    # De très grandes variations de marché communes : le gain apparié reste 1 bp.
    rows = []
    for path, market_cost in enumerate([-100.0, 0.0, 150.0]):
        rows.extend(
            [
                {
                    "path_id": path,
                    "strategy": "TWAP",
                    "total_cost_bps": market_cost,
                    "fill_rate": 1.0,
                    "completed": True,
                },
                {
                    "path_id": path,
                    "strategy": "VWAP",
                    "total_cost_bps": market_cost - 1,
                    "fill_rate": 1.0,
                    "completed": True,
                },
            ]
        )
    return pd.DataFrame(rows)


def test_bootstrap_preserves_pairing_and_sign_instead_of_resampling_bars():
    result = paired_comparison(paired_frame(), "VWAP", "TWAP", replications=200)
    assert result["n_pairs"] == 3
    assert result["saving_bps"] == result["saving_ci_low"] == result["saving_ci_high"] == 1.0
    assert result["fill_delta_pp"] == 0
    assert result["fill_bootstrap_degenerate"]
    assert result["completion_bootstrap_degenerate"]
    assert result["completion_noninferiority_bound_pp"] < -1


def test_paired_inference_rejects_duplicate_and_unmatched_paths():
    frame = paired_frame()
    with pytest.raises(ValueError, match="exactement une observation"):
        paired_comparison(pd.concat([frame, frame.iloc[[0]]]), "VWAP", "TWAP")
    with pytest.raises(ValueError, match="mêmes chemins"):
        paired_comparison(frame.iloc[1:], "VWAP", "TWAP")


def test_eighty_complete_pairs_do_not_prove_one_percentage_point_noninferiority():
    frame = pd.DataFrame(
        [
            {
                "path_id": path,
                "strategy": strategy,
                "total_cost_bps": cost,
                "fill_rate": 1.0,
                "completed": True,
            }
            for path in range(80)
            for strategy, cost in [("TWAP", 2.0), ("VWAP", 1.0)]
        ]
    )
    result = paired_comparison(frame, "VWAP", "TWAP", replications=100)
    assert result["completion_delta_ci_low"] == result["completion_delta_ci_high"] == 0
    assert -5 < result["completion_noninferiority_bound_pp"] < -4


def test_controlled_subdivision_preserves_cost_in_both_impact_models():
    checks = grid_invariance_check()
    assert len(checks) == 6
    assert checks["passed"].all()
    for _, group in checks.groupby("impact_model"):
        np.testing.assert_allclose(group["max_participation"], 0.1)
        np.testing.assert_allclose(
            group["impact_cost_bps"], group["impact_cost_bps"].iloc[0], atol=1e-12
        )
    # La normalisation rend les deux formes égales à 10 % de participation.
    np.testing.assert_allclose(checks["impact_cost_bps"], checks["impact_cost_bps"].iloc[0])


@pytest.fixture(scope="module")
def small_study():
    return run_study(paths=2, bootstrap_reps=100)


def test_complete_pipeline_does_not_inflate_independent_sample_count(small_study):
    result = small_study
    assert len(result.summary) == 2 * 5 * 2 * 2 * 2 * 4
    assert result.aggregate["n_paths"].eq(2).all()
    assert result.comparisons["n_pairs"].eq(2).all()
    assert result.summary["expected_daily_volume"].nunique() == 1
    assert result.forecast_metrics.groupby("scenario").size().eq(2).all()
    assert result.metadata["executed_seeds"] == [51000, 51001]
    assert result.summary["reconciliation_error"].abs().max() < 1e-6


def test_overrides_are_exploratory_and_cannot_silently_replace_primary(small_study):
    assert small_study.metadata["analysis_status"] == "exploratory"
    assert not small_study.comparisons["is_primary"].any()
    assert small_study.metadata["design_unchanged"]
    assert len(small_study.metadata["protocol_sha256"]) == 64
    assert small_study.grid_check["passed"].all()


def test_terminal_accounting_reports_actual_paid_actions_only(small_study):
    soft = small_study.summary.loc[small_study.summary["deadline_mode"].eq("soft")]
    assert soft["terminal_quantity"].eq(0).all()
    assert soft["terminal_explicit_cost_bps"].eq(0).all()
    fills = small_study.sample_fills
    assert fills.loc[fills["market_volume"].eq(0), "executed_quantity"].eq(0).all()
    ordinary = fills.loc[~fills["is_terminal"]]
    terminal = fills.loc[fills["is_terminal"]]
    assert ordinary["participation"].le(0.15 + 1e-12).all()
    assert terminal["participation"].le(0.4 + 1e-12).all()


@pytest.mark.parametrize(
    "kwargs", [{"paths": 81}, {"paths": 0}, {"bootstrap_reps": 0}, {"split": "all"}]
)
def test_invalid_experiment_overrides_fail_before_calculation(kwargs):
    with pytest.raises(ValueError):
        run_study(**kwargs)

"""Causalité, rattrapage des vrais fills et contraintes communes."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics.analytics import summarize_execution
from execution_cost_analytics.policies import ExecutionPolicy
from execution_cost_analytics.simulation import SimulationConfig, simulate_policy


def market_frame(volumes=(100, 1000, 1000, 1000)):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-05 09:00", periods=4, freq="30min"),
            "session": ["2026-01-05"] * 4,
            "bucket": [0, 1, 2, 3],
            "mid_price": [100.0] * 4,
            "market_volume": list(volumes),
            "spread_bps": [2.0] * 4,
        }
    )


def test_adaptive_catches_up_real_execution_deficit():
    market = market_frame()
    fixed = simulate_policy(market, 100, ExecutionPolicy("VWAP"), SimulationConfig())
    adaptive = simulate_policy(market, 100, ExecutionPolicy("ADAPTIVE"), SimulationConfig())
    assert list(fixed["requested_quantity"]) == [25, 25, 25, 25]
    assert list(fixed["executed_quantity"]) == [15, 25, 25, 25]
    # Le moteur communique les 15 vraiment remplies, pas les 25 demandées.
    assert list(adaptive["requested_quantity"]) == [25, 35, 25, 25]
    assert list(adaptive["executed_quantity"]) == [15, 35, 25, 25]
    assert adaptive["executed_quantity"].sum() == 100


def test_zero_catchup_gain_reproduces_fixed_vwap():
    market = market_frame()
    weights = [0.4, 0.3, 0.2, 0.1]
    fixed = simulate_policy(market, 100, ExecutionPolicy("VWAP", weights), SimulationConfig())
    adaptive = simulate_policy(
        market, 100, ExecutionPolicy("ADAPTIVE", weights, catchup_gain=0), SimulationConfig()
    )
    pd.testing.assert_frame_equal(fixed, adaptive)


@pytest.mark.parametrize("kind", ["TWAP", "VWAP", "POV", "ADAPTIVE"])
@pytest.mark.parametrize("mode", ["soft", "common_deadline"])
def test_future_market_changes_do_not_change_past_decisions_or_costs(kind, mode):
    market = market_frame()
    policy = ExecutionPolicy(kind, weights=[0.4, 0.1, 0.2, 0.3])
    config = SimulationConfig(deadline_mode=mode)
    initial = simulate_policy(market, 100, policy, config)
    future_changed = market.copy()
    future_changed.loc[2:, "market_volume"] = [1, 50_000]
    future_changed.loc[2:, "mid_price"] = [110.0, 90.0]
    future_changed.loc[2:, "spread_bps"] = [20.0, 10.0]
    changed = simulate_policy(future_changed, 100, policy, config)
    pd.testing.assert_frame_equal(initial.iloc[:2], changed.iloc[:2])


def test_pov_follows_contemporary_flux_and_actual_remaining_quantity():
    policy = ExecutionPolicy("POV", participation_rate=0.3)
    fills = simulate_policy(
        market_frame((100, 0, 100, 1000)), 100, policy, SimulationConfig(max_participation=0.1)
    )
    assert list(fills["requested_quantity"]) == [30, 0, 30, 80]
    assert list(fills["executed_quantity"]) == [10, 0, 10, 80]
    assert fills["executed_quantity"].sum() == 100


@pytest.mark.parametrize("kind", ["TWAP", "VWAP", "POV", "ADAPTIVE"])
def test_same_terminal_rule_overrides_all_policies(kind):
    market = market_frame((0, 0, 100, 100))
    fills = simulate_policy(
        market,
        60,
        ExecutionPolicy(kind),
        SimulationConfig(deadline_mode="common_deadline", terminal_fraction=0.5),
    )
    assert list(fills["is_terminal"]) == [False, False, True, True]
    assert list(fills["requested_quantity"].iloc[2:]) == [60, 20]
    assert list(fills["executed_quantity"].iloc[2:]) == [40, 20]
    assert fills["terminal_quantity"].sum() == 60


@pytest.mark.parametrize("kind", ["TWAP", "VWAP", "POV", "ADAPTIVE"])
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_policy_fills_reconcile_and_respect_capacity(kind, side):
    market = market_frame((0, 50, 500, 1000))
    config = SimulationConfig(side=side, deadline_mode="common_deadline")
    fills = simulate_policy(market, 100, ExecutionPolicy(kind), config)
    caps = np.where(fills["is_terminal"], config.terminal_max_participation, 0.15)
    assert (fills["executed_quantity"] <= caps * market["market_volume"]).all()
    assert fills["executed_quantity"].sum() <= 100
    summary = summarize_execution(fills, 100, 100, 100, side)
    assert summary["reconciliation_error"] == pytest.approx(0, abs=1e-8)
    assert summary["filled_quantity"] + summary["unfilled_quantity"] == 100


def test_policy_has_no_mutable_weights_or_state_between_simulations():
    weights = [1, 2, 3, 4]
    policy = ExecutionPolicy("ADAPTIVE", weights)
    weights[0] = 1000
    assert policy.weights == (1, 2, 3, 4)
    config = SimulationConfig()
    first = simulate_policy(market_frame(), 100, policy, config)
    simulate_policy(market_frame((1, 1, 1, 1)), 100, policy, config)
    again = simulate_policy(market_frame(), 100, policy, config)
    pd.testing.assert_frame_equal(first, again)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "ORACLE"},
        {"participation_rate": 0},
        {"participation_rate": 1.1},
        {"participation_rate": True},
        {"catchup_gain": -1},
        {"catchup_gain": np.inf},
        {"weights": [0, 0]},
        {"weights": [1, -1]},
    ],
)
def test_invalid_policies_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ExecutionPolicy(**kwargs)


def test_policy_rejects_wrong_weight_dimension_and_wrong_instance():
    with pytest.raises(ValueError):
        simulate_policy(market_frame(), 100, ExecutionPolicy(weights=[1, 2]), SimulationConfig())
    with pytest.raises(ValueError):
        simulate_policy(market_frame(), 100, "ADAPTIVE", SimulationConfig())


def test_higher_urgency_cannot_create_an_overfill_even_with_extreme_gain():
    config = SimulationConfig()
    policy = ExecutionPolicy("ADAPTIVE", catchup_gain=1e308)
    fills = simulate_policy(market_frame(), 100, policy, config)
    assert list(fills["executed_quantity"]) == [15, 85, 0, 0]
    assert fills["executed_quantity"].sum() == 100
    deadline = simulate_policy(
        market_frame(), 100, policy, replace(config, deadline_mode="common_deadline")
    )
    assert deadline["executed_quantity"].sum() == 100

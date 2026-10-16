"""Exécution : prix, limites de liquidité et lignes sans transaction."""

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics.simulation import SimulationConfig, simulate_execution


def market_frame():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-05 09:00", "2026-01-05 09:30", "2026-01-05 10:00"]
            ),
            "session": ["2026-01-05"] * 3,
            "bucket": [0, 1, 2],
            "mid_price": [100.0, 100.0, 100.0],
            "market_volume": [100, 0, 1000],
            "spread_bps": [20.0, 20.0, 20.0],
        }
    )


@pytest.mark.parametrize("side,first_price", [("buy", 101.1), ("sell", 98.9)])
def test_execution_price_has_correct_side_and_separate_costs(side, first_price):
    config = SimulationConfig(
        side=side,
        daily_volatility=0.02,
        impact_coefficient=0.5,
        expected_daily_volume=10000,
        fee_bps=1.0,
        max_participation=1.0,
    )
    fills = simulate_execution(market_frame(), [100, 0, 0], total_quantity=100, config=config)
    first = fills.iloc[0]
    # Demi-spread = 0,10 ; impact = 100 × 0,5 × 0,02 × sqrt(100/100 réalisé) = 1.
    assert first["executed_quantity"] == 100
    assert first["half_spread_per_share"] == pytest.approx(0.1)
    assert first["impact_per_share"] == pytest.approx(1.0)
    assert first["execution_price"] == pytest.approx(first_price)
    assert first["fee"] == pytest.approx(100 * first_price / 10000)


def test_liquidity_limit_does_not_move_unfilled_plan_to_next_bucket():
    config = SimulationConfig(max_participation=0.15)
    fills = simulate_execution(market_frame(), [20, 20, 10], total_quantity=50, config=config)
    # 15 actions au premier créneau ; zéro au second ; uniquement les 10 prévues au dernier.
    assert list(fills["planned_quantity"]) == [20, 20, 10]
    assert list(fills["executed_quantity"]) == [15, 0, 10]
    assert len(fills) == 3


def test_zero_fill_has_no_transaction_price_or_cost():
    fills = simulate_execution(
        market_frame(), [0, 20, 0], total_quantity=20, config=SimulationConfig()
    )
    assert fills["executed_quantity"].sum() == 0
    assert fills["execution_price"].isna().all()
    assert (fills[["half_spread_per_share", "impact_per_share", "fee"]] == 0).all().all()


def test_simulation_does_not_mutate_market_or_schedule():
    market = market_frame()
    before = market.copy(deep=True)
    schedule = np.array([10, 10, 10])
    simulate_execution(market, schedule, total_quantity=30, config=SimulationConfig())
    pd.testing.assert_frame_equal(market, before)
    np.testing.assert_array_equal(schedule, [10, 10, 10])


@pytest.mark.parametrize(
    "schedule,total", [([1, 2], 10), ([10, 10, 10], 20), ([1.5, 0, 0], 10), ([-1, 1, 0], 10)]
)
def test_simulation_rejects_inconsistent_orders(schedule, total):
    with pytest.raises((TypeError, ValueError)):
        simulate_execution(
            market_frame(), schedule, total_quantity=total, config=SimulationConfig()
        )


@pytest.mark.parametrize(
    "field,value",
    [("mid_price", 0), ("mid_price", np.nan), ("market_volume", -1), ("spread_bps", -1)],
)
def test_simulation_rejects_invalid_market_values(field, value):
    market = market_frame()
    market.loc[0, field] = value
    with pytest.raises((TypeError, ValueError)):
        simulate_execution(market, [1, 0, 0], total_quantity=1, config=SimulationConfig())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"side": "hold"},
        {"max_participation": 1.1},
        {"max_participation": -0.1},
        {"expected_daily_volume": 0},
        {"fee_bps": -1},
        {"daily_volatility": np.nan},
        {"impact_coefficient": -1},
        {"impact_exponent": 0.75},
        {"impact_exponent": True},
        {"deadline_mode": "force"},
        {"terminal_fraction": 0},
        {"terminal_fraction": 1.01},
        {"terminal_max_participation": 1.01},
    ],
)
def test_simulation_rejects_invalid_configuration(kwargs):
    with pytest.raises((TypeError, ValueError)):
        config = SimulationConfig(**kwargs)
        simulate_execution(market_frame(), [1, 0, 0], total_quantity=1, config=config)


def constant_market(n_buckets, daily_volume=1_040_000):
    """Même journée physique, débit/liquidité constants et quantités divisibles."""
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-01-05 09:00", "2026-01-05 15:30", periods=n_buckets + 1
            )[:-1],
            "session": ["2026-01-05"] * n_buckets,
            "bucket": np.arange(n_buckets),
            "mid_price": np.full(n_buckets, 100.0),
            "market_volume": np.full(n_buckets, daily_volume // n_buckets),
            "spread_bps": np.full(n_buckets, 2.0),
        }
    )


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("exponent", [0.5, 1.0])
def test_proportional_subdivision_preserves_cost(side, exponent):
    from execution_cost_analytics.analytics import summarize_execution

    costs = []
    for n_buckets in [26, 52, 104]:
        fills = simulate_execution(
            constant_market(n_buckets),
            np.full(n_buckets, 10400 // n_buckets),
            10400,
            SimulationConfig(side=side, impact_exponent=exponent),
        )
        summary = summarize_execution(fills, 10400, 100, 100, side)
        assert summary["fill_rate"] == 1
        assert summary["reconciliation_error"] == pytest.approx(0, abs=1e-7)
        costs.append(summary["total_cost"])
    assert costs == pytest.approx([costs[0]] * 3)


@pytest.mark.parametrize("exponent", [0.5, 1.0])
def test_integer_rounding_keeps_grid_error_below_one_ten_thousandth_bp(exponent):
    from execution_cost_analytics.strategies import twap_schedule

    quantity = 10403  # Pas divisible par les trois grilles.
    notional = quantity * 100
    continuous_impact = quantity * 100 * 0.05 * 0.02 * (quantity / 1_040_000) ** exponent
    for n_buckets in (26, 52, 104):
        fills = simulate_execution(
            constant_market(n_buckets),
            twap_schedule(quantity, n_buckets),
            quantity,
            SimulationConfig(impact_exponent=exponent),
        )
        discrete_impact = np.dot(fills["executed_quantity"], fills["impact_per_share"])
        assert abs(discrete_impact - continuous_impact) / notional * 10_000 < 0.0001


def test_forecast_daily_volume_does_not_determine_realized_impact():
    from dataclasses import replace

    config = SimulationConfig()
    market = constant_market(4)
    first = simulate_execution(market, [100] * 4, 400, config)
    second = simulate_execution(
        market, [100] * 4, 400, replace(config, expected_daily_volume=10_000)
    )
    pd.testing.assert_frame_equal(first, second)
    market["market_volume"] //= 2
    scarce = simulate_execution(market, [100] * 4, 400, config)
    np.testing.assert_allclose(scarce["impact_per_share"], first["impact_per_share"] * np.sqrt(2))


def test_common_deadline_can_fail_without_available_capacity():
    market = market_frame()
    market["market_volume"] = [0, 0, 10]
    fills = simulate_execution(
        market,
        [10, 10, 10],
        30,
        SimulationConfig(deadline_mode="common_deadline", terminal_fraction=1 / 3),
    )
    assert list(fills["requested_quantity"]) == [10, 10, 30]
    assert list(fills["executed_quantity"]) == [0, 0, 4]
    assert list(fills["terminal_quantity"]) == [0, 0, 4]
    assert fills["participation"].iloc[-1] == pytest.approx(0.4)

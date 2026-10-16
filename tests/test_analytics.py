"""Comptabilité du coût : exemples calculés à la main, achats et ventes."""

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics.analytics import summarize_execution


def manual_fills(side):
    # Cible : 8 actions, dont 5 exécutées et 3 laissées au prix final de 102.
    prices = [100.3, 102.4] if side == "buy" else [99.7, 101.6]
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-05 09:00", "2026-01-05 09:30"]),
            "session": ["2026-01-05"] * 2,
            "bucket": [0, 1],
            "mid_price": [100.0, 102.0],
            "market_volume": [100, 300],
            "spread_bps": [20.0, 20.0],
            "planned_quantity": [3, 2],
            "executed_quantity": [3, 2],
            "execution_price": prices,
            "half_spread_per_share": [0.1, 0.1],
            "impact_per_share": [0.2, 0.3],
            "fee": [0.5, 0.7],
        }
    )


@pytest.mark.parametrize(
    "side,expected",
    [
        (
            "buy",
            {
                "delay_cost": 5.0,
                "timing_cost": 4.0,
                "opportunity_cost": 9.0,
                "total_cost": 20.9,
                "average_execution_price": 101.14,
            },
        ),
        (
            "sell",
            {
                "delay_cost": -5.0,
                "timing_cost": -4.0,
                "opportunity_cost": -9.0,
                "total_cost": -15.1,
                "average_execution_price": 100.46,
            },
        ),
    ],
)
def test_shortfall_decomposition_matches_manual_cash_accounting(side, expected):
    result = summarize_execution(
        manual_fills(side), total_quantity=8, decision_price=99, arrival_price=100, side=side
    )
    for name, value in expected.items():
        assert result[name] == pytest.approx(value), name
    assert result["filled_quantity"] == 5
    assert result["unfilled_quantity"] == 3
    assert result["fill_rate"] == pytest.approx(5 / 8)
    assert result["spread_cost"] == pytest.approx(0.5)
    assert result["impact_cost"] == pytest.approx(1.2)
    assert result["fee_cost"] == pytest.approx(1.2)
    assert result["market_vwap"] == pytest.approx(101.5)
    assert result["total_cost_bps"] == pytest.approx(expected["total_cost"] / (8 * 99) * 10000)
    assert result["reconciliation_error"] == pytest.approx(0, abs=1e-10)
    direction = 1 if side == "buy" else -1
    assert result["vwap_slippage_bps"] == pytest.approx(
        direction * (expected["average_execution_price"] / 101.5 - 1) * 10000
    )


@pytest.mark.parametrize("side,expected_opportunity", [("buy", 24), ("sell", -24)])
def test_no_fill_keeps_opportunity_cost_and_undefined_average(side, expected_opportunity):
    fills = manual_fills(side)
    fills["executed_quantity"] = 0
    fills["execution_price"] = np.nan
    fills[["half_spread_per_share", "impact_per_share", "fee"]] = 0.0
    result = summarize_execution(
        fills, total_quantity=8, decision_price=99, arrival_price=100, side=side
    )
    assert result["filled_quantity"] == 0
    assert result["unfilled_quantity"] == 8
    assert result["fill_rate"] == 0
    assert result["average_execution_price"] is None or np.isnan(result["average_execution_price"])
    assert result["vwap_slippage_bps"] is None or np.isnan(result["vwap_slippage_bps"])
    assert result["opportunity_cost"] == expected_opportunity
    assert result["total_cost"] == expected_opportunity
    assert result["reconciliation_error"] == pytest.approx(0)


def test_fully_filled_order_has_zero_opportunity_cost():
    result = summarize_execution(
        manual_fills("buy"), total_quantity=5, decision_price=99, arrival_price=100, side="buy"
    )
    assert result["fill_rate"] == 1
    assert result["unfilled_quantity"] == 0
    assert result["opportunity_cost"] == 0
    assert result["total_cost"] == pytest.approx(11.9)


@pytest.mark.parametrize("side,sign", [("buy", 1), ("sell", -1)])
def test_explicit_terminal_price_values_only_remaining_quantity_and_reconciles(side, sign):
    fills = manual_fills(side)
    default = summarize_execution(fills, 8, 99, 100, side)
    explicit = summarize_execution(fills, 8, 99, 100, side, terminal_price=105)
    # Trois actions restent ouvertes ; référence terminale105, dernier VWAP de barre102.
    assert fills["mid_price"].iloc[-1] == 102
    assert explicit["unfilled_quantity"] == 3
    assert explicit["opportunity_cost"] == pytest.approx(sign * 3 * (105 - 99))
    assert explicit["total_cost"] - default["total_cost"] == pytest.approx(sign * 3 * (105 - 102))
    assert explicit["average_execution_price"] == default["average_execution_price"]
    assert explicit["market_vwap"] == default["market_vwap"]
    assert explicit["reconciliation_error"] == pytest.approx(0, abs=1e-10)
    cash_cost = (
        sign * (np.dot(fills["executed_quantity"], fills["execution_price"]) - 5 * 99)
        + fills["fee"].sum()
        + sign * 3 * (105 - 99)
    )
    assert explicit["total_cost"] == pytest.approx(cash_cost)


@pytest.mark.parametrize(
    "decision,arrival,side,total",
    [(0, 100, "buy", 8), (99, np.inf, "buy", 8), (99, 100, "hold", 8), (99, 100, "buy", 4)],
)
def test_analytics_rejects_invalid_references_or_overfills(decision, arrival, side, total):
    with pytest.raises((TypeError, ValueError)):
        summarize_execution(
            manual_fills("buy"),
            total_quantity=total,
            decision_price=decision,
            arrival_price=arrival,
            side=side,
        )

"""Garanties temporelles au niveau du parcours complet."""

import pandas as pd
import pytest

from execution_cost_analytics.data import generate_market_data
from execution_cost_analytics.experiment import run_experiment


def test_future_session_changes_do_not_change_an_earlier_evaluation():
    market = generate_market_data(n_days=4, n_buckets=4, seed=11)
    sessions = sorted(market["session"].unique())
    baseline = run_experiment(market, quantity=1000, train_days=2, lookback=2)
    changed = market.copy()
    future = changed["session"].eq(sessions[-1])
    changed.loc[future, "mid_price"] *= 2
    changed.loc[future, "market_volume"] *= 3
    modified = run_experiment(changed, quantity=1000, train_days=2, lookback=2)
    previous = baseline.summary.loc[baseline.summary["session"].eq(sessions[2])].reset_index(
        drop=True
    )
    repeated = modified.summary.loc[modified.summary["session"].eq(sessions[2])].reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(previous, repeated)


def test_vwap_plan_is_fixed_before_current_volume_is_observed():
    market = generate_market_data(n_days=3, n_buckets=4, seed=11)
    current_session = sorted(market["session"].unique())[-1]
    baseline = run_experiment(market, quantity=1000, train_days=2, lookback=2)
    changed = market.copy()
    current = changed["session"].eq(current_session)
    changed.loc[current, "market_volume"] = [1, 100000, 100000, 1000000]
    modified = run_experiment(changed, quantity=1000, train_days=2, lookback=2)
    before = baseline.fills.loc[baseline.fills["strategy"].eq("VWAP"), "planned_quantity"].tolist()
    after = modified.fills.loc[modified.fills["strategy"].eq("VWAP"), "planned_quantity"].tolist()
    assert before == after
    assert sum(before) == 1000


def test_reversed_buckets_in_training_session_are_rejected():
    market = generate_market_data(n_days=3, n_buckets=4, seed=11)
    first_session = market["session"].iloc[0]
    training = market["session"].eq(first_session)
    # Les heures restent croissantes : seules les étiquettes historiques sont inversées.
    market.loc[training, "bucket"] = [3, 2, 1, 0]
    with pytest.raises(ValueError, match="buckets"):
        run_experiment(market, quantity=1000, train_days=2, lookback=2)


def test_irregular_timestamps_in_training_session_are_rejected():
    market = generate_market_data(n_days=3, n_buckets=4, seed=11)
    # Décaler une seule barre de l'historique conserve l'ordre, mais casse la régularité.
    market.loc[1, "timestamp"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="régulièrement"):
        run_experiment(market, quantity=1000, train_days=2, lookback=2)


def test_regular_but_different_training_session_grid_is_rejected():
    market = generate_market_data(n_days=3, n_buckets=4, seed=11)
    first_session = market["session"].iloc[0]
    training = market["session"].eq(first_session)
    # Chaque séance reste régulière ; la première démarre cinq minutes plus tard.
    market.loc[training, "timestamp"] += pd.Timedelta(minutes=5)
    with pytest.raises(ValueError, match="même grille"):
        run_experiment(market, quantity=1000, train_days=2, lookback=2)

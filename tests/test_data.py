"""La prévision apprend uniquement des séances déjà terminées."""

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics.data import forecast_volume_profile, generate_market_data


def historical_market():
    rows = []
    for session, volumes in [
        ("2026-01-05", [100, 300]),
        ("2026-01-06", [300, 100]),
        ("2026-01-07", [9000, 1000]),
        ("2026-01-08", [1, 9999]),
    ]:
        for bucket, volume in enumerate(volumes):
            rows.append(
                {
                    "timestamp": pd.Timestamp(session) + pd.Timedelta(hours=9, minutes=30 * bucket),
                    "session": session,
                    "bucket": bucket,
                    "mid_price": 100.0,
                    "market_volume": volume,
                    "spread_bps": 2.0,
                }
            )
    return pd.DataFrame(rows)


def test_synthetic_market_is_reproducible_and_well_formed():
    first = generate_market_data(n_days=4, n_buckets=6, seed=7)
    repeated = generate_market_data(n_days=4, n_buckets=6, seed=7)
    pd.testing.assert_frame_equal(first, repeated)
    assert len(first) == 24
    assert first["session"].nunique() == 4
    assert pd.api.types.is_datetime64_any_dtype(first["timestamp"])
    assert first["timestamp"].is_monotonic_increasing
    assert not first.duplicated(["session", "bucket"]).any()
    for _, day in first.groupby("session"):
        assert list(day["bucket"]) == list(range(6))
    assert np.isfinite(first[["mid_price", "market_volume", "spread_bps"]]).all().all()
    assert (first["mid_price"] > 0).all()
    assert (first["market_volume"] >= 0).all()
    assert (first["spread_bps"] >= 0).all()
    assert pd.api.types.is_integer_dtype(first["market_volume"])


def test_forecast_averages_daily_profiles_and_excludes_as_of_session():
    forecast = forecast_volume_profile(historical_market(), as_of="2026-01-07", lookback=20)
    # Les deux séances passées ont des profils 25/75 et 75/25.
    np.testing.assert_allclose(forecast.weights, [0.5, 0.5])
    assert forecast.expected_daily_volume == pytest.approx(400)
    assert list(forecast.training_sessions) == ["2026-01-05", "2026-01-06"]


def test_forecast_uses_mean_of_daily_profiles_not_pooled_volume():
    forecast = forecast_volume_profile(historical_market(), as_of="2026-01-08", lookback=2)
    # Moyenne de (75/25) et (90/10), indépendamment de leur volume total.
    np.testing.assert_allclose(forecast.weights, [0.825, 0.175])
    assert forecast.expected_daily_volume == pytest.approx(5200)
    assert list(forecast.training_sessions) == ["2026-01-06", "2026-01-07"]


def test_forecast_is_unchanged_if_current_and_future_volumes_change():
    history = historical_market()
    baseline = forecast_volume_profile(history, as_of="2026-01-07", lookback=2)
    history.loc[history["session"] >= "2026-01-07", "market_volume"] = [1, 1000000, 1000000, 1]
    modified = forecast_volume_profile(history, as_of="2026-01-07", lookback=2)
    np.testing.assert_array_equal(baseline.weights, modified.weights)
    assert baseline.expected_daily_volume == modified.expected_daily_volume
    assert list(baseline.training_sessions) == list(modified.training_sessions)


def test_forecast_rejects_an_incomplete_session_in_training_window():
    history = historical_market()
    history = history.loc[~((history["session"] == "2026-01-07") & (history["bucket"] == 1))]
    with pytest.raises(ValueError):
        forecast_volume_profile(history, as_of="2026-01-08", lookback=2)


def test_forecast_requires_at_least_one_past_complete_session():
    with pytest.raises(ValueError):
        forecast_volume_profile(historical_market(), as_of="2026-01-05")


@pytest.mark.parametrize("days,buckets", [(0, 3), (3, 0), (-1, 3), (3, 2.5)])
def test_generator_rejects_invalid_dimensions(days, buckets):
    with pytest.raises((TypeError, ValueError)):
        generate_market_data(n_days=days, n_buckets=buckets)

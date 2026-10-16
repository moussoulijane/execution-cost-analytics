"""Exemples à la main et invariants des trois règles de découpage."""

import numpy as np
import pytest

from execution_cost_analytics.strategies import (
    pov_schedule,
    twap_schedule,
    vwap_schedule,
)


def test_twap_example_and_integer_remainder():
    assert list(twap_schedule(100, 4)) == [25, 25, 25, 25]
    assert list(twap_schedule(10, 3)) == [4, 3, 3]
    assert list(twap_schedule(2, 5)) == [1, 1, 0, 0, 0]


@pytest.mark.parametrize("quantity,n_buckets", [(1, 1), (1, 7), (23, 8), (1001, 26)])
def test_twap_conserves_integer_shares(quantity, n_buckets):
    schedule = np.asarray(twap_schedule(quantity, n_buckets))
    assert len(schedule) == n_buckets
    assert np.issubdtype(schedule.dtype, np.integer)
    assert schedule.sum() == quantity
    assert schedule.min() >= 0
    assert schedule.max() - schedule.min() <= 1


def test_vwap_uses_largest_remainders_and_preserves_zero_weights():
    # Quotas exacts : 1,2 ; 1,8 ; 3 ; 0. Le reliquat revient au deuxième.
    assert list(vwap_schedule(6, [2, 3, 5, 0])) == [1, 2, 3, 0]
    assert list(vwap_schedule(2, [1, 1, 1])) == [1, 1, 0]


def test_vwap_weights_are_relative_not_percentages():
    original = np.asarray(vwap_schedule(101, [1, 2, 0, 7]))
    scaled = np.asarray(vwap_schedule(101, [10, 20, 0, 70]))
    np.testing.assert_array_equal(original, scaled)
    assert original.sum() == 101
    assert original[2] == 0
    assert np.issubdtype(original.dtype, np.integer)


def test_vwap_conserves_shares_near_int64_limit():
    quantity = int(np.iinfo(np.int64).max)
    schedule = vwap_schedule(quantity, [1, 2, 7])
    # Un total Python évite de masquer un dépassement avec une somme int64.
    assert sum(int(value) for value in schedule) == quantity
    assert (schedule >= 0).all()


def test_pov_uses_observed_volume_without_forcing_completion():
    # 10 % des volumes donne 10, 0, 4 actions. Il reste 86 actions.
    assert list(pov_schedule(100, [100, 0, 49], 0.1)) == [10, 0, 4]


def test_pov_stops_when_order_is_complete():
    assert list(pov_schedule(12, [100, 100, 100], 0.1)) == [10, 2, 0]


def test_decimal_participation_does_not_lose_an_exact_share():
    # 0,29 × 100 = 29 ; une représentation binaire flottante peut donner 28,999…
    assert list(pov_schedule(100, [100, 100], 0.29)) == [29, 29]


def test_pov_never_reads_future_volumes_for_a_past_decision():
    first = pov_schedule(1000, [100, 59, 100, 100], 0.1)
    changed_future = pov_schedule(1000, [100, 59, 9999, 0], 0.1)
    assert list(first[:2]) == list(changed_future[:2]) == [10, 5]


@pytest.mark.parametrize(
    "quantity,n_buckets", [(-1, 4), (1.5, 4), (True, 4), (10, 0), (10, 2.5), (10, True)]
)
def test_twap_rejects_invalid_inputs(quantity, n_buckets):
    with pytest.raises((TypeError, ValueError)):
        twap_schedule(quantity, n_buckets)


@pytest.mark.parametrize("weights", [[], [0, 0], [-1, 2], [1, np.nan], [1, np.inf]])
def test_vwap_rejects_invalid_profiles(weights):
    with pytest.raises((TypeError, ValueError)):
        vwap_schedule(10, weights)


@pytest.mark.parametrize(
    "volumes,rate",
    [([10, -1], 0.1), ([np.nan], 0.1), ([np.inf], 0.1), ([10], -0.1), ([10], 1.1), ([10], np.nan)],
)
def test_pov_rejects_invalid_inputs(volumes, rate):
    with pytest.raises((TypeError, ValueError)):
        pov_schedule(10, volumes, rate)

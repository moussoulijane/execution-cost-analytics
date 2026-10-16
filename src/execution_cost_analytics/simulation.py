"""Exécutions causales et impact temporaire sur la liquidité locale réalisée.

Le coefficient n'est pas calibré empiriquement. La formule de participation est
un scénario de coût : elle ne représente ni carnet d'ordres ni impact permanent.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import ceil
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd

from .policies import ExecutionPolicy
from .strategies import _integer_vector, _positive_integer


@dataclass(frozen=True)
class SimulationConfig:
    """Hypothèses explicites du modèle ; les taux sont des fractions sauf fee_bps."""

    side: Literal["buy", "sell"] = "buy"
    daily_volatility: float = 0.02
    impact_coefficient: float = 0.05
    expected_daily_volume: float = 1_000_000.0
    fee_bps: float = 0.5
    max_participation: float = 0.15
    impact_exponent: float = 0.5
    deadline_mode: Literal["soft", "common_deadline"] = "soft"
    terminal_fraction: float = 0.20
    terminal_max_participation: float = 0.40


def _finite_number(value: float, name: str, strictly_positive: bool = False) -> float:
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, Real)
        or not np.isfinite(value)
        or (value <= 0 if strictly_positive else value < 0)
    ):
        qualifier = "strictement positif" if strictly_positive else "positif ou nul"
        raise ValueError(f"{name} doit être un nombre fini {qualifier}.")
    return float(value)


def _numeric_column(market: pd.DataFrame, column: str, positive: bool) -> np.ndarray:
    values = market[column].tolist()
    return np.asarray(
        [_finite_number(value, column, strictly_positive=positive) for value in values],
        dtype=np.float64,
    )


def simulate_execution(
    market: pd.DataFrame,
    schedule: Sequence[int],
    total_quantity: int,
    config: SimulationConfig,
) -> pd.DataFrame:
    """Exécuter un calendrier fixe ; appliquer la règle terminale si demandée."""
    return _simulate(market, schedule, total_quantity, config, policy=None)


def simulate_policy(
    market: pd.DataFrame,
    total_quantity: int,
    policy: ExecutionPolicy,
    config: SimulationConfig,
) -> pd.DataFrame:
    """Simuler des demandes séquentielles fondées sur les fills réellement passés.

    POV est une instruction de participation au flux contemporain du créneau.
    Son agrégation en barres suppose l'accès à cette liquidité au fil de l'eau ;
    elle n'utilise jamais le volume d'un créneau futur.
    """
    if not isinstance(policy, ExecutionPolicy):
        raise ValueError("policy doit être une instance de ExecutionPolicy.")
    if not isinstance(market, pd.DataFrame) or market.empty:
        raise ValueError("market doit être un DataFrame non vide.")
    schedule = policy.build_schedule(total_quantity, len(market))
    return _simulate(market, schedule, total_quantity, config, policy)


def _simulate(
    market: pd.DataFrame,
    schedule: Sequence[int],
    total_quantity: int,
    config: SimulationConfig,
    policy: ExecutionPolicy | None,
) -> pd.DataFrame:
    total_quantity = _positive_integer(total_quantity, "total_quantity")
    required = {"timestamp", "session", "bucket", "mid_price", "market_volume", "spread_bps"}
    if (
        not isinstance(market, pd.DataFrame)
        or market.empty
        or not required.issubset(market.columns)
    ):
        raise ValueError(
            "market doit contenir une séance non vide avec les six colonnes attendues."
        )
    if not isinstance(config, SimulationConfig):
        raise ValueError("config doit être une instance de SimulationConfig.")
    if config.side not in ("buy", "sell"):
        raise ValueError("side doit valoir 'buy' ou 'sell'.")
    sigma = _finite_number(config.daily_volatility, "daily_volatility")
    eta = _finite_number(config.impact_coefficient, "impact_coefficient")
    # Compatibilité V1 seulement : une prévision ne détermine jamais le coût réel.
    _finite_number(config.expected_daily_volume, "expected_daily_volume", True)
    fee_bps = _finite_number(config.fee_bps, "fee_bps")
    participation = _finite_number(config.max_participation, "max_participation", True)
    if participation > 1:
        raise ValueError("max_participation ne doit pas dépasser 1.")
    exponent = _finite_number(config.impact_exponent, "impact_exponent", True)
    if exponent not in (0.5, 1.0):
        raise ValueError("impact_exponent doit valoir 0.5 ou 1.0.")
    if config.deadline_mode not in ("soft", "common_deadline"):
        raise ValueError("deadline_mode doit valoir soft ou common_deadline.")
    terminal_fraction = _finite_number(config.terminal_fraction, "terminal_fraction", True)
    terminal_rate = _finite_number(
        config.terminal_max_participation, "terminal_max_participation", True
    )
    if terminal_fraction > 1 or terminal_rate > 1:
        raise ValueError("terminal_fraction et terminal_max_participation ne dépassent pas 1.")
    planned = _integer_vector(schedule, "schedule")
    if len(planned) != len(market):
        raise ValueError("schedule doit contenir une quantité par ligne de market.")
    if sum(int(value) for value in planned) > total_quantity:
        raise ValueError("La quantité planifiée ne doit pas dépasser total_quantity.")
    if market["session"].isna().any() or market["session"].nunique() != 1:
        raise ValueError("market doit contenir une seule séance.")
    timestamps = market["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(timestamps.dtype):
        raise ValueError("timestamp doit avoir un type datetime.")
    if (
        timestamps.isna().any()
        or timestamps.duplicated().any()
        or not timestamps.is_monotonic_increasing
        or timestamps.dt.tz is not None
    ):
        raise ValueError("Les timestamps doivent être naïfs, uniques et strictement croissants.")
    session = market["session"].iloc[0]
    if not isinstance(session, str) or not timestamps.dt.strftime("%Y-%m-%d").eq(session).all():
        raise ValueError("session doit correspondre à la date YYYY-MM-DD de chaque timestamp.")
    buckets = _integer_vector(market["bucket"].tolist(), "bucket")
    if not np.array_equal(buckets, np.arange(len(market), dtype=np.int64)):
        raise ValueError("bucket doit suivre exactement 0, 1, ..., n-1.")
    mid = _numeric_column(market, "mid_price", positive=True)
    spread_bps = _numeric_column(market, "spread_bps", positive=False)
    volumes = _integer_vector(market["market_volume"].tolist(), "market_volume")
    # 0,30 × 100 vaut exactement 30 : un arrondi flottant ne doit pas retirer une action.
    exact_rate = Fraction(str(participation))
    terminal_exact = Fraction(str(terminal_rate))
    pov_exact = Fraction(str(policy.participation_rate)) if policy is not None else None
    n_buckets = len(market)
    terminal_start = n_buckets - ceil(n_buckets * terminal_fraction)
    requests = np.zeros(n_buckets, dtype=np.int64)
    executed = np.zeros(n_buckets, dtype=np.int64)
    terminal = np.zeros(n_buckets, dtype=bool)
    executed_so_far = 0
    for index, volume in enumerate(volumes):
        remaining = total_quantity - executed_so_far
        terminal[index] = config.deadline_mode == "common_deadline" and index >= terminal_start
        rate = terminal_exact if terminal[index] else exact_rate
        capacity = rate.numerator * int(volume) // rate.denominator
        if terminal[index]:
            request = remaining
        elif policy is None:
            request = int(planned[index])
        elif policy.kind == "POV":
            request = min(remaining, pov_exact.numerator * int(volume) // pov_exact.denominator)
        else:
            request = policy.request_quantity(index, planned, executed_so_far, total_quantity)
        requests[index] = min(request, remaining)
        executed[index] = min(int(requests[index]), capacity)
        executed_so_far += int(executed[index])
    filled = executed > 0
    local_participation = np.divide(
        executed, volumes, out=np.zeros(n_buckets, dtype=float), where=volumes > 0
    )
    # q/V reste identique lorsqu'un créneau est divisé proportionnellement.
    with np.errstate(over="ignore", invalid="ignore"):
        half_spread = np.where(filled, mid * spread_bps / 20_000, 0.0)
        impact = np.where(filled, mid * eta * sigma * local_participation**exponent, 0.0)
        side_sign = 1 if config.side == "buy" else -1
        prices = np.where(filled, mid + side_sign * (half_spread + impact), np.nan)
        fees = np.where(filled, executed * prices * fee_bps / 10_000, 0.0)
    if (
        not np.all(np.isfinite(half_spread))
        or not np.all(np.isfinite(impact))
        or not np.all(np.isfinite(prices[filled]))
        or np.any(prices[filled] <= 0)
        or not np.all(np.isfinite(fees))
    ):
        raise ValueError(
            "Les hypothèses produisent des prix ou coûts non finis ou des prix non positifs."
        )
    result = market.copy()
    result["planned_quantity"] = requests
    result["requested_quantity"] = requests
    result["executed_quantity"] = executed
    result["participation"] = local_participation
    result["is_terminal"] = terminal
    result["terminal_quantity"] = np.where(terminal, executed, 0)
    result["execution_price"] = prices
    result["half_spread_per_share"] = half_spread
    result["impact_per_share"] = impact
    result["fee"] = fees
    return result

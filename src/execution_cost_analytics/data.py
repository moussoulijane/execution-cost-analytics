"""Données fictives reproductibles et prévision de volume sans connaissance du futur."""

from dataclasses import dataclass
from numbers import Integral

import numpy as np
import pandas as pd

from .strategies import _integer_vector, _positive_integer


@dataclass(frozen=True)
class VolumeForecast:
    """Profil estimé uniquement à partir de séances antérieures à la séance cible."""

    weights: np.ndarray
    expected_daily_volume: float
    training_sessions: tuple[str, ...]


def generate_market_data(n_days: int = 40, n_buckets: int = 26, seed: int = 42) -> pd.DataFrame:
    """Simuler des séances ouvrées dès le 5 janvier 2026, sans données réelles."""
    n_days = _positive_integer(n_days, "n_days")
    n_buckets = _positive_integer(n_buckets, "n_buckets")
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, Integral) or seed < 0:
        raise ValueError("seed doit être un entier positif ou nul.")
    rng = np.random.default_rng(int(seed))
    sessions = pd.bdate_range("2026-01-05", periods=n_days)
    position = np.linspace(-1, 1, n_buckets) if n_buckets > 1 else np.array([0.0])
    volume_shape = 0.65 + 0.90 * np.abs(position) ** 1.7
    rows: list[pd.DataFrame] = []
    previous_close = 100.0
    for day in sessions:
        daily_volume = 1_000_000 * rng.lognormal(mean=-0.5 * 0.18**2, sigma=0.18)
        noisy_shape = volume_shape * rng.lognormal(mean=0.0, sigma=0.12, size=n_buckets)
        volumes = rng.poisson(daily_volume * noisy_shape / noisy_shape.sum()).astype(np.int64)
        opening = previous_close * np.exp(rng.normal(0.0, 0.003))
        returns = rng.normal(0.0, 0.02 / np.sqrt(n_buckets), size=n_buckets)
        returns[0] = 0.0
        prices = opening * np.exp(np.cumsum(returns))
        previous_close = float(prices[-1])
        spreads = 1.2 + 1.8 * volume_shape / volume_shape.max() + rng.uniform(0.0, 0.5, n_buckets)
        # 26 créneaux représentent 6 h 30 ; l'horloge est purement pédagogique.
        # Un pas entier en nanosecondes conserve un espacement strictement régulier.
        step_ns = pd.Timedelta(hours=6, minutes=30).value // n_buckets
        timestamps = (
            day
            + pd.Timedelta(hours=9, minutes=30)
            + pd.to_timedelta(np.arange(n_buckets) * step_ns, unit="ns")
        )
        rows.append(
            pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "session": day.strftime("%Y-%m-%d"),
                    "bucket": np.arange(n_buckets, dtype=np.int64),
                    "mid_price": prices,
                    "market_volume": volumes,
                    "spread_bps": spreads,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def forecast_volume_profile(
    history: pd.DataFrame, as_of: str, lookback: int = 20
) -> VolumeForecast:
    """Moyenner les profils des dernières séances complètes strictement antérieures."""
    lookback = _positive_integer(lookback, "lookback")
    required = {"session", "bucket", "market_volume"}
    if not isinstance(history, pd.DataFrame) or not required.issubset(history.columns):
        raise ValueError("history doit contenir session, bucket et market_volume.")
    try:
        target = pd.Timestamp(as_of)
    except (ValueError, TypeError) as error:
        raise ValueError("as_of doit être une date au format YYYY-MM-DD.") from error
    if (
        not isinstance(as_of, str)
        or pd.isna(target)
        or target.tzinfo is not None
        or target.strftime("%Y-%m-%d") != as_of
    ):
        raise ValueError("as_of doit être une date au format YYYY-MM-DD.")
    if history.empty:
        raise ValueError("Aucune séance historique disponible.")
    if not history["session"].map(lambda value: isinstance(value, str) and len(value) == 10).all():
        raise ValueError("session doit contenir des dates au format YYYY-MM-DD.")
    try:
        dates = pd.to_datetime(history["session"], format="%Y-%m-%d", errors="raise")
    except (ValueError, TypeError) as error:
        raise ValueError("session doit contenir des dates valides au format YYYY-MM-DD.") from error
    if not (dates.dt.strftime("%Y-%m-%d").to_numpy() == history["session"].to_numpy()).all():
        raise ValueError("session doit contenir des dates au format YYYY-MM-DD.")

    # Filtrer avant toute estimation : aucune valeur de la séance cible ne sert au profil.
    prior = history.loc[dates < target].copy()
    if prior.empty:
        raise ValueError("Aucune séance strictement antérieure à as_of.")
    sessions = sorted(prior["session"].unique())[-lookback:]
    selected = prior.loc[prior["session"].isin(sessions)]
    profiles: list[np.ndarray] = []
    totals: list[int] = []
    expected_buckets: np.ndarray | None = None
    # Une grille connue dans l'historique permet de détecter aussi une séance tronquée en fin.
    all_buckets = _integer_vector(prior["bucket"].tolist(), "bucket")
    if int(all_buckets.max()) >= len(prior):
        raise ValueError("Les numéros de créneaux ne correspondent pas à une grille contiguë.")
    complete_grid = np.arange(int(all_buckets.max()) + 1, dtype=np.int64)
    for session in sessions:
        group = selected.loc[selected["session"] == session].sort_values("bucket")
        buckets = _integer_vector(group["bucket"].tolist(), "bucket")
        if not np.array_equal(buckets, complete_grid):
            raise ValueError(f"Séance incomplète ou créneaux dupliqués : {session}.")
        if expected_buckets is not None and not np.array_equal(buckets, expected_buckets):
            raise ValueError("Les séances historiques doivent partager les mêmes créneaux.")
        expected_buckets = buckets
        volumes = _integer_vector(group["market_volume"].tolist(), "market_volume")
        total = sum(int(value) for value in volumes)
        if total <= 0:
            raise ValueError(f"Le volume total de la séance {session} doit être positif.")
        profiles.append(volumes.astype(np.float64) / total)
        totals.append(total)
    weights = np.mean(np.vstack(profiles), axis=0)
    weights /= weights.sum()
    return VolumeForecast(
        weights=weights,
        expected_daily_volume=float(np.mean(totals)),
        training_sessions=tuple(sessions),
    )

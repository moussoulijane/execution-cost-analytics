"""Construire des calendriers d'ordres entiers et explicables."""

from collections.abc import Sequence
from fractions import Fraction
from numbers import Integral, Real

import numpy as np


def _positive_integer(value: int, name: str) -> int:
    """Refuser les booléens, même si Python les considère comme des entiers."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} doit être un entier strictement positif.")
    if value <= 0 or value > np.iinfo(np.int64).max:
        raise ValueError(f"{name} doit être compris entre 1 et {np.iinfo(np.int64).max}.")
    return int(value)


def _integer_vector(values: Sequence[int], name: str) -> np.ndarray:
    """Vérifier les quantités sans tronquer silencieusement des décimales."""
    try:
        items = list(values)
    except TypeError as error:
        raise ValueError(f"{name} doit être une séquence d'entiers.") from error
    if not items:
        raise ValueError(f"{name} ne doit pas être vide.")
    maximum = np.iinfo(np.int64).max
    for value in items:
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Integral)
            or value < 0
            or value > maximum
        ):
            raise ValueError(f"{name} doit contenir des entiers positifs ou nuls en int64.")
    return np.asarray(items, dtype=np.int64)


def twap_schedule(quantity: int, n_buckets: int) -> np.ndarray:
    """Répartir la quantité également, avec le reliquat sur les premiers créneaux."""
    quantity = _positive_integer(quantity, "quantity")
    n_buckets = _positive_integer(n_buckets, "n_buckets")
    base, remainder = divmod(quantity, n_buckets)
    schedule = np.full(n_buckets, base, dtype=np.int64)
    schedule[:remainder] += 1
    return schedule


def vwap_schedule(quantity: int, weights: Sequence[float]) -> np.ndarray:
    """Allouer des actions par la méthode des plus forts restes (Hamilton)."""
    quantity = _positive_integer(quantity, "quantity")
    try:
        items = list(weights)
    except TypeError as error:
        raise ValueError("weights doit être une séquence de nombres.") from error
    if not items or any(
        isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) for value in items
    ):
        raise ValueError("weights doit contenir des nombres réels non négatifs.")
    try:
        values = np.asarray(items, dtype=np.float64)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(
            "weights doit contenir des poids finis représentables en float64."
        ) from error
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("weights doit être un vecteur fini de poids non négatifs.")
    if not np.any(values > 0):
        raise ValueError("La somme des poids doit être strictement positive.")

    # Les fractions conservent le total exact, y compris près de la limite int64.
    exact_weights = [Fraction(str(value)) for value in items]
    weight_sum = sum(exact_weights)
    quotas = [quantity * weight / weight_sum for weight in exact_weights]
    schedule = np.asarray(
        [quota.numerator // quota.denominator for quota in quotas], dtype=np.int64
    )
    remainder = quantity - sum(int(value) for value in schedule)
    fractions = [quota - int(base) for quota, base in zip(quotas, schedule, strict=True)]
    # Le tri Python est stable : les ex aequo gardent l'ordre des créneaux.
    order = sorted(range(len(schedule)), key=lambda index: fractions[index], reverse=True)
    schedule[order[:remainder]] += 1
    return schedule


def pov_schedule(
    quantity: int,
    market_volumes: Sequence[int],
    participation_rate: float,
) -> np.ndarray:
    """Suivre le volume observé, sans forcer l'exécution du solde en fin de séance."""
    quantity = _positive_integer(quantity, "quantity")
    volumes = _integer_vector(market_volumes, "market_volumes")
    if (
        isinstance(participation_rate, (bool, np.bool_))
        or not isinstance(participation_rate, Real)
        or not np.isfinite(participation_rate)
        or not 0 < participation_rate <= 1
    ):
        raise ValueError("participation_rate doit être fini et appartenir à ]0, 1].")
    remaining = quantity
    schedule = np.zeros(len(volumes), dtype=np.int64)
    exact_rate = Fraction(str(participation_rate))
    for index, volume in enumerate(volumes):
        # Chaque tranche utilise seulement le volume du créneau courant.
        capacity = exact_rate.numerator * int(volume) // exact_rate.denominator
        executed = min(remaining, capacity)
        schedule[index] = executed
        remaining -= executed
    return schedule

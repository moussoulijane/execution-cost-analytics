"""Instructions causales : un calendrier prévu et le retard réellement exécuté.

Les politiques n'ont accès à aucun DataFrame de marché. Le moteur applique POV
au flux contemporain du créneau ; il s'agit d'une approximation agrégée d'un
ordre de participation, et non d'une prévision du volume réalisé.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from numbers import Real

import numpy as np

from .strategies import _positive_integer, twap_schedule, vwap_schedule


@dataclass(frozen=True)
class ExecutionPolicy:
    """Politique sans état caché, reconstruite avec les exécutions observées.

    ADAPTIVE ajoute au plan du créneau ``ceil(gain * retard_antérieur)``.
    Un gain nul reproduit exactement VWAP. Les poids sont des prévisions
    disponibles avant la séance, jamais les volumes futurs réalisés.
    """

    kind: str = "VWAP"
    weights: Sequence[float] | None = None
    participation_rate: float = 0.03
    catchup_gain: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in {"TWAP", "VWAP", "POV", "ADAPTIVE"}:
            raise ValueError("kind doit valoir TWAP, VWAP, POV ou ADAPTIVE.")
        for name, value in (
            ("participation_rate", self.participation_rate),
            ("catchup_gain", self.catchup_gain),
        ):
            if (
                isinstance(value, (bool, np.bool_))
                or not isinstance(value, Real)
                or not np.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} doit être un réel fini positif ou nul.")
        if not 0 < self.participation_rate <= 1:
            raise ValueError("participation_rate doit appartenir à ]0, 1].")
        if self.weights is not None:
            # Valider avec la même règle que le calendrier, puis figer une copie.
            copied = tuple(self.weights)
            vwap_schedule(1, copied)
            object.__setattr__(self, "weights", copied)

    def build_schedule(self, quantity: int, n_buckets: int) -> np.ndarray:
        """Construire le plan ex ante ; POV est traité comme instruction de flux."""
        quantity = _positive_integer(quantity, "quantity")
        n_buckets = _positive_integer(n_buckets, "n_buckets")
        if self.weights is not None and len(self.weights) != n_buckets:
            raise ValueError("weights doit contenir un poids par créneau.")
        if self.kind in {"TWAP", "POV"} or self.weights is None:
            return twap_schedule(quantity, n_buckets)
        return vwap_schedule(quantity, self.weights)

    def request_quantity(
        self,
        bucket: int,
        schedule: np.ndarray,
        executed_so_far: int,
        total_quantity: int,
    ) -> int:
        """Décider avant le créneau, uniquement avec plan et fills antérieurs.

        Appelé par le moteur après validation des entiers. POV doit être exécuté
        par le moteur au fil du volume contemporain, pas par cette méthode.
        """
        if self.kind == "POV":
            raise ValueError("POV requiert l'instruction de participation du moteur.")
        remaining = total_quantity - executed_so_far
        base = min(int(schedule[bucket]), remaining)
        if self.kind != "ADAPTIVE" or remaining <= base:
            return base
        target_before = sum(int(value) for value in schedule[:bucket])
        lag = max(0, target_before - executed_so_far)
        if lag == 0 or self.catchup_gain == 0:
            return base
        # Borner avant la multiplication évite un overflow pour un gain extrême.
        room = remaining - base
        catchup = room if self.catchup_gain >= room / lag else ceil(self.catchup_gain * lag)
        return base + catchup

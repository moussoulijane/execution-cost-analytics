"""Mesures ex post : coût signé, reliquat et réconciliation comptable."""

from numbers import Integral

import numpy as np
import pandas as pd


def summarize_execution(
    fills: pd.DataFrame,
    total_quantity: int,
    decision_price: float,
    arrival_price: float,
    side: str,
    terminal_price: float | None = None,
) -> dict[str, float | int | None]:
    """Décomposer l'IS ; un coût positif est défavorable pour les deux côtés.

    Les montants sont dans l'unité monétaire du jeu de données. total_cost_bps
    utilise le dénominateur quantité initiale × prix décision. Le slippage VWAP
    est normalisé par le prix VWAP de référence, hors frais.
    Le reliquat utilise terminal_price si fourni, sinon le dernier mid,
    sans créer d'exécution fictive.
    """
    if isinstance(total_quantity, bool) or not isinstance(total_quantity, Integral):
        raise ValueError("total_quantity doit être un entier positif.")
    if total_quantity <= 0 or side not in {"buy", "sell"}:
        raise ValueError("Quantité positive et side='buy' ou 'sell' requis.")
    if not all(np.isfinite(p) and p > 0 for p in [decision_price, arrival_price]):
        raise ValueError("Les prix de décision et d'arrivée doivent être positifs et finis.")
    if terminal_price is not None and (not np.isfinite(terminal_price) or terminal_price <= 0):
        raise ValueError("Le prix terminal doit être positif et fini.")
    required = {
        "mid_price",
        "market_volume",
        "executed_quantity",
        "execution_price",
        "half_spread_per_share",
        "impact_per_share",
        "fee",
    }
    if fills.empty or not required.issubset(fills.columns):
        raise ValueError(f"Exécutions non vides avec colonnes {sorted(required)} requises.")
    finite_columns = sorted(required - {"execution_price"})
    if not np.isfinite(fills[finite_columns].to_numpy(dtype=float)).all():
        raise ValueError("Les valeurs de marché et de coût doivent être finies.")
    q = fills["executed_quantity"].to_numpy(dtype=float)
    nonnegative = ["market_volume", "half_spread_per_share", "impact_per_share", "fee"]
    if (q < 0).any() or (q != np.floor(q)).any():
        raise ValueError("Les quantités exécutées doivent être des entiers non négatifs.")
    if (fills[nonnegative].to_numpy(dtype=float) < 0).any():
        raise ValueError("Volumes et coûts explicites doivent être non négatifs.")
    if (fills["mid_price"] <= 0).any() or q.sum() > total_quantity:
        raise ValueError("Prix positifs et quantité exécutée <= ordre initial requis.")
    active = q > 0
    executed_prices = fills.loc[active, "execution_price"].to_numpy(dtype=float)
    if not np.isfinite(executed_prices).all() or (executed_prices <= 0).any():
        raise ValueError("Chaque exécution doit avoir un prix positif et fini.")
    if (fills.loc[~active, "fee"] != 0).any():
        raise ValueError("Aucun frais ne doit être imputé à une exécution nulle.")

    sign = 1 if side == "buy" else -1
    executed = int(q.sum())
    remaining = int(total_quantity - executed)
    terminal_price = (
        float(fills["mid_price"].iloc[-1]) if terminal_price is None else float(terminal_price)
    )
    executed_notional = float(np.dot(q[active], executed_prices))
    average_price = executed_notional / executed if executed else None
    volume = fills["market_volume"].to_numpy(dtype=float)
    mids = fills["mid_price"].to_numpy(dtype=float)
    market_vwap = float(np.dot(mids, volume) / volume.sum()) if volume.sum() else None
    components = {
        "delay_cost": float(sign * executed * (arrival_price - decision_price)),
        "timing_cost": float(sign * np.dot(q, mids - arrival_price)),
        "spread_cost": float(np.dot(q, fills["half_spread_per_share"])),
        "impact_cost": float(np.dot(q, fills["impact_per_share"])),
        "fee_cost": float(fills["fee"].sum()),
        "opportunity_cost": float(sign * remaining * (terminal_price - decision_price)),
    }
    total_cost = float(sum(components.values()))
    direct_cost = float(
        sign * (executed_notional - executed * decision_price)
        + components["fee_cost"]
        + components["opportunity_cost"]
    )
    return {
        "filled_quantity": executed,
        "unfilled_quantity": remaining,
        "fill_rate": executed / total_quantity,
        "average_execution_price": average_price,
        "market_vwap": market_vwap,
        # Référence de séance calculée ex post, jamais utilisée pour prévoir les poids.
        "vwap_slippage_bps": (
            float(sign * (average_price / market_vwap - 1) * 10_000)
            if average_price is not None and market_vwap is not None
            else None
        ),
        **components,
        "total_cost": total_cost,
        "total_cost_bps": float(total_cost / (total_quantity * decision_price) * 10_000),
        "reconciliation_error": total_cost - direct_cost,
    }

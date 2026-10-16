"""Expérience commune aux commandes, au notebook et aux rapports."""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from numbers import Integral

import numpy as np
import pandas as pd

from .analytics import summarize_execution
from .data import forecast_volume_profile
from .policies import ExecutionPolicy
from .simulation import SimulationConfig, simulate_policy


@dataclass
class ExperimentResult:
    """Tables produites par une seule expérience reproductible."""

    summary: pd.DataFrame
    aggregate_summary: pd.DataFrame
    fills: pd.DataFrame
    forecast_metrics: pd.DataFrame
    sensitivity: pd.DataFrame
    profiles: pd.DataFrame
    metadata: dict


def run_experiment(
    market: pd.DataFrame,
    quantity: int = 50_000,
    side: str = "buy",
    train_days: int = 30,
    lookback: int = 20,
    participation: float = 0.03,
    max_participation: float = 0.15,
    impact_coefficient: float = 0.05,
    fee_bps: float = 0.5,
    daily_volatility: float = 0.02,
    impact_exponent: float = 0.5,
    deadline_mode: str = "soft",
) -> ExperimentResult:
    """Évaluer chaque journée après un historique initial, sans mélange temporel.

    La décision fictive est prise à la clôture précédente. Les poids VWAP et
    le volume journalier attendu sont figés avant l'arrivée de l'ordre.
    """
    required = {"timestamp", "session", "bucket", "mid_price", "market_volume", "spread_bps"}
    if market.empty or not required.issubset(market.columns):
        raise ValueError(f"Données non vides avec colonnes {sorted(required)} requises.")
    for name, value in [("train_days", train_days), ("lookback", lookback), ("quantity", quantity)]:
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(f"{name} doit être un entier positif.")
    data = market.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="raise")
    if data["timestamp"].dt.tz is not None:
        raise ValueError("Utiliser des horodatages naïfs dans un même fuseau documenté.")
    if data["timestamp"].isna().any() or data["timestamp"].duplicated().any():
        raise ValueError("Horodatages uniques et renseignés requis.")
    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError("Le fichier doit être trié chronologiquement.")
    data["session"] = data["session"].astype(str)
    if not data["session"].eq(data["timestamp"].dt.strftime("%Y-%m-%d")).all():
        raise ValueError("La session doit correspondre à la date de l'horodatage.")
    sessions = sorted(data["session"].unique())
    if train_days >= len(sessions):
        raise ValueError("Il faut au moins une séance d'évaluation après train_days.")
    bucket_counts = data.groupby("session").size()
    if bucket_counts.nunique() != 1:
        raise ValueError("Toutes les séances doivent avoir le même nombre de créneaux.")
    n_buckets = int(bucket_counts.iloc[0])
    numeric = data[["bucket", "mid_price", "market_volume", "spread_bps"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("Les données numériques doivent être finies.")
    if (data["mid_price"] <= 0).any() or (data[["market_volume", "spread_bps"]] < 0).any().any():
        raise ValueError("Prix positifs, volumes et spreads non négatifs requis.")
    if (data["market_volume"] != np.floor(data["market_volume"])).any():
        raise ValueError("Les volumes doivent être des quantités entières.")
    reference_grid = None
    for _, day in data.groupby("session", sort=False):
        if not np.array_equal(day["bucket"].to_numpy(), np.arange(n_buckets)):
            raise ValueError("Chaque séance doit présenter les buckets 0..n-1 dans cet ordre.")
        offsets = day["timestamp"] - day["timestamp"].dt.normalize()
        grid = offsets.to_numpy()
        if len(grid) > 1 and len(np.unique(np.diff(grid))) != 1:
            raise ValueError("Les créneaux d'une séance doivent être régulièrement espacés.")
        if reference_grid is None:
            reference_grid = grid
        elif not np.array_equal(grid, reference_grid):
            raise ValueError("Toutes les séances doivent utiliser la même grille horaire.")
    summaries, all_fills, forecasts, sensitivities, profiles = [], [], [], [], []
    config = SimulationConfig(
        side=side,
        daily_volatility=daily_volatility,
        impact_coefficient=impact_coefficient,
        fee_bps=fee_bps,
        max_participation=max_participation,
        impact_exponent=impact_exponent,
        deadline_mode=deadline_mode,
    )
    for index, session in enumerate(sessions[train_days:], start=train_days):
        current = data.loc[data["session"].eq(session)].reset_index(drop=True)
        deltas = current["timestamp"].diff().dropna()
        if len(deltas) and (deltas.nunique() != 1 or deltas.iloc[0] <= pd.Timedelta(0)):
            raise ValueError("Les créneaux d'une séance doivent être régulièrement espacés.")
        forecast = forecast_volume_profile(data, as_of=session, lookback=lookback)
        if len(forecast.weights) != n_buckets:
            raise ValueError("Le profil historique doit correspondre aux créneaux évalués.")
        day_config = replace(config, expected_daily_volume=forecast.expected_daily_volume)
        previous = data.loc[data["session"].eq(sessions[index - 1])]
        decision = float(previous["mid_price"].iloc[-1])
        arrival = float(current["mid_price"].iloc[0])
        policies = {
            strategy: ExecutionPolicy(
                kind=strategy,
                weights=forecast.weights,
                participation_rate=participation,
            )
            for strategy in ["TWAP", "VWAP", "POV", "ADAPTIVE"]
        }
        volumes = current["market_volume"].to_numpy(dtype=float)
        if volumes.sum() <= 0:
            raise ValueError("Une séance d'évaluation doit avoir un volume total positif.")
        realized_profile = volumes / volumes.sum()
        forecasts.append(
            {
                "session": session,
                "first_training_session": forecast.training_sessions[0],
                "last_training_session": forecast.training_sessions[-1],
                "training_days": len(forecast.training_sessions),
                "profile_mae": float(np.abs(forecast.weights - realized_profile).mean()),
                "uniform_profile_mae": float(np.abs(1 / n_buckets - realized_profile).mean()),
                "expected_daily_volume": forecast.expected_daily_volume,
                "realized_daily_volume": int(volumes.sum()),
                "daily_volume_error_pct": float(
                    (forecast.expected_daily_volume / volumes.sum() - 1) * 100
                ),
            }
        )
        profiles.extend(
            {
                "session": session,
                "bucket": bucket,
                "forecast_weight": float(weight),
                "realized_weight": float(realized_profile[bucket]),
            }
            for bucket, weight in enumerate(forecast.weights)
        )
        for strategy, policy in policies.items():
            fills = simulate_policy(current, quantity, policy, day_config)
            metrics = summarize_execution(fills, quantity, decision, arrival, side)
            if abs(metrics["reconciliation_error"]) > 1e-7 * max(1, quantity * decision):
                raise RuntimeError("Échec de la réconciliation des coûts.")
            summaries.append(
                {
                    "session": session,
                    "strategy": strategy,
                    "side": side,
                    "order_quantity": quantity,
                    "decision_price": decision,
                    "arrival_price": arrival,
                    "completed": int(metrics["filled_quantity"] == quantity),
                    "terminal_quantity": int(fills["terminal_quantity"].sum()),
                    **metrics,
                }
            )
            fills["strategy"] = strategy
            all_fills.append(fills)
            # Même marché, mêmes plans : seule l'hypothèse d'impact change.
            for coefficient in [0.0, 0.025, 0.05, 0.1]:
                scenario_fills = simulate_policy(
                    current,
                    quantity,
                    policy,
                    replace(day_config, impact_coefficient=coefficient),
                )
                scenario = summarize_execution(scenario_fills, quantity, decision, arrival, side)
                sensitivities.append(
                    {
                        "session": session,
                        "strategy": strategy,
                        "impact_coefficient": coefficient,
                        "total_cost_bps": scenario["total_cost_bps"],
                        "fill_rate": scenario["fill_rate"],
                    }
                )
    summary = pd.DataFrame(summaries)
    aggregate = (
        summary.groupby("strategy", sort=False)
        .agg(
            evaluated_sessions=("session", "count"),
            mean_fill_rate=("fill_rate", "mean"),
            completion_probability=("completed", "mean"),
            mean_cost_bps=("total_cost_bps", "mean"),
            std_cost_bps=("total_cost_bps", "std"),
            mean_vwap_slippage_bps=("vwap_slippage_bps", "mean"),
        )
        .reset_index()
    )
    return ExperimentResult(
        summary=summary,
        aggregate_summary=aggregate,
        fills=pd.concat(all_fills, ignore_index=True),
        forecast_metrics=pd.DataFrame(forecasts),
        sensitivity=pd.DataFrame(sensitivities),
        profiles=pd.DataFrame(profiles),
        metadata={
            "data_type": "user_supplied",
            "quantity": int(quantity),
            "side": side,
            "initial_training_days": int(train_days),
            "lookback": int(lookback),
            "evaluated_sessions": sessions[train_days:],
            "n_buckets": n_buckets,
            "participation": participation,
            "config": {
                key: value
                for key, value in asdict(config).items()
                if key != "expected_daily_volume"
            },
            "daily_volume_convention": "forecast_each_session_in_forecast_metrics.csv",
            "decision_convention": "previous_session_last_mid",
            "terminal_convention": "current_session_last_mid",
            "impact_convention": "temporary_realized_local_participation_not_calibrated",
            "input_fingerprint_sha256": sha256(
                data.to_csv(index=False, float_format="%.12g").encode("utf-8")
            ).hexdigest(),
        },
    )

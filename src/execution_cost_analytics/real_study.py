"""Évaluation chronologique sur marchés historiques, sous coûts hypothétiques."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .analytics import summarize_execution
from .data import forecast_volume_profile
from .policies import ExecutionPolicy
from .public_data import TERMS_URL
from .simulation import SimulationConfig, simulate_policy
from .study import StudyResult, grid_invariance_check, load_protocol, summarize_study


def run_public_study(input_dir: str | Path = "data/public") -> StudyResult:
    """Deux actifs prévus à l'avance ; 14 jours initiaux, puis test glissant par actif.

    Les prix de transaction sont observés ; spread et impact ne sont pas mesurés.
    Les cellules sont descriptives et n'héritent d'aucun statut confirmatoire du
    contraste synthétique. Les deux actifs ne sont pas regroupés en faux IID.
    """
    directory = Path(input_dir)
    protocol = load_protocol()
    real_design = {
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "month": "2026-01",
        "training_days": 14,
        "lookback": 14,
        "bar_minutes": 30,
        "quantity_adv_ratios": [0.05, 0.10],
        "spread_bps_assumed": 2.0,
        "models": protocol["models"],
        "deadline_modes": protocol["deadline_modes"],
        "side": "buy",
        "bootstrap_replications": 2000,
        "pov_rate_convention": "quantity_divided_by_forecast_daily_volume",
        "analysis_status": "descriptive_historical_confrontation_not_impact_calibration",
    }
    # Le design et les actifs sont définis avant la première lecture des résultats.
    design_hash = hashlib.sha256(json.dumps(real_design, sort_keys=True).encode()).hexdigest()
    rows, forecast_rows, sample_frames, sources = [], [], [], []
    input_hash = hashlib.sha256()
    for symbol in real_design["symbols"]:
        path = directory / f"{symbol}-{real_design['month']}-market.csv"
        source_path = path.with_suffix(".json")
        if not path.exists() or not source_path.exists():
            raise ValueError(
                "Données publiques absentes : lancer fetch-public-data avant real-study."
            )
        manifest = json.loads(source_path.read_text(encoding="utf-8"))
        if manifest.get("symbol") != symbol or manifest.get("month") != real_design["month"]:
            raise ValueError("La provenance du fichier ne correspond pas au protocole réel.")
        if manifest.get("missing_minutes") != 0 or manifest.get("duplicate_minutes") != 0:
            raise ValueError("Une archive complète et sans doublon est requise.")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest.get("market_csv_sha256"):
            raise ValueError(
                "Le CSV préparé ne correspond pas à son empreinte vérifiée : relancer fetch-public-data."
            )
        input_hash.update(payload)
        market = pd.read_csv(path, parse_dates=["timestamp"])
        required = {
            "timestamp",
            "session",
            "bucket",
            "mid_price",
            "market_volume",
            "spread_bps",
            "open_price",
            "close_price",
        }
        if not required.issubset(market.columns):
            raise ValueError("CSV préparé incomplet : régénérer avec fetch-public-data.")
        if (
            not market["timestamp"].is_monotonic_increasing
            or market["timestamp"].duplicated().any()
        ):
            raise ValueError("Données historiques non triées ou dupliquées.")
        sessions = sorted(market["session"].unique())
        expected_grid = pd.date_range("2026-01-01", "2026-02-01", freq="30min", inclusive="left")
        if (
            not pd.DatetimeIndex(market["timestamp"]).equals(expected_grid)
            or not market["session"].eq(market["timestamp"].dt.strftime("%Y-%m-%d")).all()
            or not np.array_equal(market["bucket"].to_numpy(), np.tile(np.arange(48), 31))
        ):
            raise ValueError("Le protocole réel attend janvier 2026 complet, 48 barres par jour.")
        sources.append(manifest)
        for index, session in enumerate(sessions[14:]):
            current = market.loc[market["session"].eq(session)].reset_index(drop=True)
            forecast = forecast_volume_profile(market, as_of=session, lookback=14)
            if not all(day < session for day in forecast.training_sessions):
                raise RuntimeError("Fuite temporelle dans la prévision historique.")
            realized_volume = float(current["market_volume"].sum())
            profile = current["market_volume"].to_numpy(dtype=float) / realized_volume
            forecast_rows.append(
                {
                    "path_id": session,
                    "seed": -1,
                    "session": session,
                    "split": "real_holdout",
                    "scenario": symbol,
                    "first_training_session": forecast.training_sessions[0],
                    "last_training_session": forecast.training_sessions[-1],
                    "expected_daily_volume": forecast.expected_daily_volume,
                    "realized_daily_volume": realized_volume,
                    "daily_volume_error_pct": (forecast.expected_daily_volume / realized_volume - 1)
                    * 100,
                    "profile_mae": float(np.abs(forecast.weights - profile).mean()),
                    "uniform_profile_mae": float(np.abs(1 / 48 - profile).mean()),
                }
            )
            decision = float(current["open_price"].iloc[0])
            terminal = float(current["close_price"].iloc[-1])
            for model, model_values in protocol["models"].items():
                for mode in real_design["deadline_modes"]:
                    config = SimulationConfig(
                        side="buy",
                        daily_volatility=0.02,
                        fee_bps=0.5,
                        impact_coefficient=model_values["impact_coefficient"],
                        impact_exponent=model_values["impact_exponent"],
                        deadline_mode=mode,
                        max_participation=0.15,
                        terminal_fraction=0.2,
                        terminal_max_participation=0.4,
                    )
                    for ratio in real_design["quantity_adv_ratios"]:
                        quantity = max(1, int(round(forecast.expected_daily_volume * ratio)))
                        denominator = quantity * decision / 10_000
                        for strategy in protocol["strategies"]:
                            policy = ExecutionPolicy(
                                kind=strategy,
                                weights=forecast.weights,
                                participation_rate=quantity / forecast.expected_daily_volume,
                            )
                            fills = simulate_policy(current, quantity, policy, config)
                            metrics = summarize_execution(
                                fills, quantity, decision, decision, "buy", terminal_price=terminal
                            )
                            cash_cost = (
                                fills["executed_quantity"]
                                * (fills["half_spread_per_share"] + fills["impact_per_share"])
                                + fills["fee"]
                            )
                            identifiers = {
                                "path_id": session,
                                "seed": -1,
                                "session": session,
                                "split": "real_holdout",
                                "scenario": symbol,
                                "impact_model": model,
                                "deadline_mode": mode,
                                "quantity_adv_ratio": ratio,
                                "strategy": strategy,
                            }
                            rows.append(
                                {
                                    **identifiers,
                                    "order_quantity": quantity,
                                    "expected_daily_volume": forecast.expected_daily_volume,
                                    "realized_daily_volume": realized_volume,
                                    "total_cost_bps": metrics["total_cost_bps"],
                                    "explicit_cost_bps": float(cash_cost.sum() / denominator),
                                    "opportunity_cost_bps": metrics["opportunity_cost"]
                                    / denominator,
                                    "fill_rate": metrics["fill_rate"],
                                    "completed": metrics["unfilled_quantity"] == 0,
                                    "terminal_quantity": int(fills["terminal_quantity"].sum()),
                                    "terminal_explicit_cost_bps": float(
                                        cash_cost.loc[fills["is_terminal"]].sum() / denominator
                                    ),
                                    "max_realized_participation": float(
                                        fills["participation"].max()
                                    ),
                                    "reconciliation_error": metrics["reconciliation_error"],
                                }
                            )
                            if index == 0:
                                sample_frames.append(
                                    fills.assign(
                                        **{
                                            key: value
                                            for key, value in identifiers.items()
                                            if key != "session"
                                        }
                                    )
                                )
    summary = pd.DataFrame(rows)
    aggregate, comparisons = summarize_study(
        summary, protocol, split="real_holdout", bootstrap_reps=2000
    )
    return StudyResult(
        summary=summary,
        aggregate=aggregate,
        comparisons=comparisons,
        forecast_metrics=pd.DataFrame(forecast_rows),
        grid_check=grid_invariance_check(protocol),
        sample_fills=pd.concat(sample_frames, ignore_index=True),
        metadata={
            "study_version": "2.0.0",
            "data_type": "public_historical",
            "analysis_status": real_design["analysis_status"],
            "real_design": real_design,
            "design_sha256": design_hash,
            "input_fingerprint_sha256": input_hash.hexdigest(),
            "sources": sources,
            "terms_url": TERMS_URL,
            "data_and_derived_results_license": "CC BY-NC-SA 4.0",
            "code_license": "MIT",
            "price_proxy": "bar_trade_vwap_not_bid_ask_mid",
            "decision_convention": "first_bar_first_transaction_open",
            "arrival_convention": "first_bar_first_transaction_open",
            "terminal_convention": "last_bar_last_transaction_close",
            "uncertainty_scope": "paired_days_per_asset_conditional_on_hypothetical_execution_model",
            "bootstrap_unit": "UTC_day_per_asset_no_cross_asset_pooling",
            "volatility_assumption": "fixed_daily_volatility_0.02_not_estimated_from_holdout",
            "impact_calibration": "none",
            "protocol": protocol,
        },
    )

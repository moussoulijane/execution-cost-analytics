"""Étude annoncée avant évaluation, avec chemins communs et bootstrap apparié.

Les IC décrivent l'incertitude Monte-Carlo dans un générateur synthétique. Ils
ne mesurent pas l'erreur du modèle d'impact ni une performance réelle de marché.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from numbers import Integral
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from .analytics import summarize_execution
from .data import forecast_volume_profile, generate_market_data
from .policies import ExecutionPolicy
from .simulation import SimulationConfig, simulate_policy
from .strategies import vwap_schedule

CELL_KEYS = ["scenario", "impact_model", "deadline_mode", "quantity_adv_ratio"]


@dataclass
class StudyResult:
    """Résultats et preuve des paramètres effectivement exécutés."""

    summary: pd.DataFrame
    aggregate: pd.DataFrame
    comparisons: pd.DataFrame
    forecast_metrics: pd.DataFrame
    grid_check: pd.DataFrame
    metadata: dict
    sample_fills: pd.DataFrame


def default_protocol() -> dict:
    """Design embarqué, aussi disponible dans docs/PROTOCOLE_V2.json.

    Le fallback permet une installation wheel sans le répertoire docs. Les
    champs narratifs sont dans le document ; les paramètres numériques restent
    disponibles sans accès réseau et sans fichier externe.
    """
    return {
        "version": "2.0.0",
        "frozen_on": "2026-10-15",
        "n_buckets": 26,
        "training": {"seed": 31000, "n_days": 30, "lookback": 20},
        "development_seeds": list(range(41000, 41012)),
        "test_seeds": list(range(51000, 51080)),
        "quantity_adv_ratios": [0.05, 0.1],
        "strategies": ["TWAP", "VWAP", "POV", "ADAPTIVE"],
        "deadline_modes": ["soft", "common_deadline"],
        "side": "buy",
        "scenarios": {
            "normal": {
                "volume_multiplier": 1.0,
                "volatility_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "profile": "unchanged",
            },
            "low_volume": {
                "volume_multiplier": 0.55,
                "volatility_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "profile": "unchanged",
            },
            "midday_shutdown": {
                "volume_multiplier": 1.0,
                "volatility_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "profile": "middle_third_zero",
            },
            "late_shift": {
                "volume_multiplier": 1.0,
                "volatility_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "profile": "linear_tilt_0.2_to_2.0_preserve_total",
            },
            "stressed": {
                "volume_multiplier": 0.55,
                "volatility_multiplier": 2.0,
                "spread_multiplier": 2.0,
                "profile": "unchanged",
            },
        },
        "models": {
            "sqrt": {"impact_exponent": 0.5, "impact_coefficient": 0.05},
            "linear": {"impact_exponent": 1.0, "impact_coefficient": 0.15811388300841897},
        },
        "execution": {
            "daily_volatility": 0.02,
            "fee_bps": 0.5,
            "max_participation": 0.15,
            "terminal_fraction": 0.2,
            "terminal_max_participation": 0.4,
            "catchup_gain": 1.0,
        },
        "bootstrap": {
            "replications": 2000,
            "confidence_level": 0.95,
            "seed": 61000,
            "unit": "independent_path_with_paired_strategies",
        },
        "primary_contrast": {
            "strategy": "ADAPTIVE",
            "baseline": "VWAP",
            "scenario": "low_volume",
            "quantity_adv_ratio": 0.1,
            "deadline_mode": "common_deadline",
            "impact_model": "sqrt",
        },
        "decision_thresholds": {
            "minimum_saving_bps": 0.5,
            "fill_noninferiority_pp": 1.0,
            "completion_noninferiority_pp": 1.0,
            "q95_cost_margin_bps": 2.0,
            "illustrative_completion_probability_target": 0.95,
        },
        "grid_check": {
            "n_buckets": [26, 52, 104],
            "total_quantity": 10400,
            "total_market_volume": 104000,
            "mid_price": 100.0,
            "spread_bps": 2.0,
        },
    }


def _design(protocol: dict) -> dict:
    """Ignorer seulement les explications textuelles pour identifier le design."""
    return {
        key: value for key, value in protocol.items() if key not in {"question", "interpretation"}
    }


def _fingerprint(protocol: dict) -> str:
    canonical = json.dumps(protocol, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def load_protocol(path: str | Path | None = None) -> dict:
    """Charger et vérifier notamment la séparation des graines et les tailles."""
    candidate = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parents[2] / ("docs/PROTOCOLE_V2.json")
    )
    protocol = (
        json.loads(candidate.read_text(encoding="utf-8"))
        if candidate.exists()
        else (default_protocol() if path is None else None)
    )
    if protocol is None:
        raise ValueError(f"Protocole introuvable : {candidate}")
    expected = default_protocol()
    missing = set(expected) - set(protocol)
    if missing:
        raise ValueError(f"Paramètres de protocole manquants : {sorted(missing)}")
    train = protocol["training"]
    for name, value in [
        ("n_buckets", protocol["n_buckets"]),
        ("n_days", train["n_days"]),
        ("lookback", train["lookback"]),
        ("replications", protocol["bootstrap"]["replications"]),
    ]:
        _positive_count(value, name)
    if protocol["n_buckets"] < 3 or train["lookback"] > train["n_days"]:
        raise ValueError("Au moins 3 créneaux et lookback <= n_days sont requis.")
    seed_groups = [[train["seed"]], protocol["development_seeds"], protocol["test_seeds"]]
    for seeds in seed_groups:
        if not seeds or len(set(seeds)) != len(seeds):
            raise ValueError("Les groupes de graines doivent être non vides et sans doublons.")
        if any(
            isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0 for seed in seeds
        ):
            raise ValueError("Les graines doivent être des entiers positifs ou nuls.")
    sets = list(map(set, seed_groups))
    if any(sets[i] & sets[j] for i in range(3) for j in range(i)):
        raise ValueError("Les graines entraînement, développement et test doivent être disjointes.")
    ratios = protocol["quantity_adv_ratios"]
    if not ratios or any(
        not isinstance(ratio, (int, float))
        or isinstance(ratio, bool)
        or not np.isfinite(ratio)
        or not 0 < ratio <= 1
        for ratio in ratios
    ):
        raise ValueError("quantity_adv_ratios doit contenir des fractions dans ]0, 1].")
    if len(set(ratios)) != len(ratios):
        raise ValueError("Les tailles d'ordre ne doivent pas être dupliquées.")
    if protocol["strategies"] != expected["strategies"]:
        raise ValueError("Les quatre stratégies communes TWAP, VWAP, POV, ADAPTIVE sont requises.")
    if not 0 < protocol["bootstrap"]["confidence_level"] < 1:
        raise ValueError("confidence_level doit appartenir à ]0, 1[.")
    if protocol["side"] not in {"buy", "sell"}:
        raise ValueError("side doit valoir buy ou sell.")
    return deepcopy(protocol)


def _positive_count(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} doit être un entier strictement positif.")
    return int(value)


def transform_scenario(base: pd.DataFrame, parameters: dict) -> pd.DataFrame:
    """Transformer un chemin réalisé sans modifier le forecast ni le tirage de base."""
    market = base.copy()
    volumes = np.floor(
        market["market_volume"].to_numpy(dtype=float) * parameters["volume_multiplier"]
    ).astype(np.int64)
    profile = parameters["profile"]
    if profile == "middle_third_zero":
        volumes[len(volumes) // 3 : 2 * len(volumes) // 3] = 0
    elif profile == "linear_tilt_0.2_to_2.0_preserve_total":
        total = int(volumes.sum())
        if total > 0:
            volumes = vwap_schedule(total, volumes * np.linspace(0.2, 2.0, len(volumes)))
    elif profile != "unchanged":
        raise ValueError(f"Profil de scénario inconnu : {profile}")
    market["market_volume"] = volumes
    opening = float(market["mid_price"].iloc[0])
    log_moves = np.log(market["mid_price"].to_numpy(dtype=float) / opening)
    market["mid_price"] = opening * np.exp(log_moves * parameters["volatility_multiplier"])
    market["spread_bps"] *= parameters["spread_multiplier"]
    return market


def paired_comparison(
    frame: pd.DataFrame,
    strategy: str,
    baseline: str,
    replications: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 61000,
) -> dict:
    """Bootstrap de différences, une unité indépendante = un chemin apparié."""
    replications = _positive_count(replications, "replications")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level doit appartenir à ]0, 1[.")
    columns = ["path_id", "total_cost_bps", "fill_rate", "completed"]
    selected = frame.loc[frame["strategy"].eq(strategy), columns].set_index("path_id")
    reference = frame.loc[frame["strategy"].eq(baseline), columns].set_index("path_id")
    if selected.empty or selected.index.has_duplicates or reference.index.has_duplicates:
        raise ValueError("Chaque méthode doit avoir exactement une observation par chemin.")
    if set(selected.index) != set(reference.index):
        raise ValueError("Les méthodes doivent partager exactement les mêmes chemins.")
    selected = selected.sort_index()
    reference = reference.reindex(selected.index)
    a = selected.to_numpy(dtype=float)
    b = reference.to_numpy(dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Les observations appariées doivent être finies.")
    # Les deux méthodes restent ensemble dans chaque chemin rééchantillonné.
    deltas = np.column_stack(
        (b[:, 0] - a[:, 0], 100 * (a[:, 1] - b[:, 1]), 100 * (a[:, 2] - b[:, 2]))
    )
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(a), size=(replications, len(a)))
    draws = deltas[indices].mean(axis=1)
    alpha = (1 - confidence_level) / 2
    lower, upper = np.quantile(draws, [alpha, 1 - alpha], axis=0)
    means = deltas.mean(axis=0)
    completion_lower, completion_upper = _wilson_bounds(
        np.array([a[:, 2].mean(), b[:, 2].mean()]),
        np.array([len(a), len(b)], dtype=float),
        confidence_level,
    )
    return {
        "strategy": strategy,
        "baseline": baseline,
        "n_pairs": len(a),
        "saving_bps": means[0],
        "saving_ci_low": lower[0],
        "saving_ci_high": upper[0],
        "fill_delta_pp": means[1],
        "fill_delta_ci_low": lower[1],
        "fill_delta_ci_high": upper[1],
        "completion_delta_pp": means[2],
        "completion_delta_ci_low": lower[2],
        "completion_delta_ci_high": upper[2],
        "q95_cost_delta_bps": float(np.quantile(a[:, 0], 0.95) - np.quantile(b[:, 0], 0.95)),
        "fill_bootstrap_degenerate": bool(np.ptp(deltas[:, 1]) == 0),
        "completion_bootstrap_degenerate": bool(np.ptp(deltas[:, 2]) == 0),
        "completion_noninferiority_bound_pp": float(
            100 * (completion_lower[0] - completion_upper[1])
        ),
    }


def _wilson_bounds(
    p: np.ndarray,
    n: np.ndarray,
    confidence_level: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Bornes marginales approximatives, conservatrices si soustraites en paire."""
    z = NormalDist().inv_cdf((1 + confidence_level) / 2)
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return np.maximum(0, center - half), np.minimum(1, center + half)


def summarize_study(
    summary: pd.DataFrame,
    protocol: dict,
    split: str = "test",
    bootstrap_reps: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthèse commune aux chemins synthétiques et à un vrai holdout documenté.

    Les groupes scenario/modèle/mode/taille sont analysés séparément. Pour des
    données historiques, l'indépendance entre journées est une hypothèse à
    discuter ; ce helper ne transforme pas des données corrélées en IID.
    """
    if summary.empty:
        raise ValueError("L'étude doit contenir des observations.")
    if summary.duplicated([*CELL_KEYS, "strategy", "path_id"]).any():
        raise ValueError("Une seule observation par chemin, méthode et cellule est requise.")
    grouped = summary.groupby([*CELL_KEYS, "strategy"], sort=False)
    aggregate = grouped.agg(
        n_paths=("path_id", "count"),
        mean_cost_bps=("total_cost_bps", "mean"),
        std_cost_bps=("total_cost_bps", "std"),
        q95_cost_bps=("total_cost_bps", lambda values: values.quantile(0.95)),
        mean_explicit_cost_bps=("explicit_cost_bps", "mean"),
        mean_opportunity_cost_bps=("opportunity_cost_bps", "mean"),
        mean_fill_rate=("fill_rate", "mean"),
        completion_probability=("completed", "mean"),
        mean_terminal_quantity=("terminal_quantity", "mean"),
        mean_terminal_cost_bps=("terminal_explicit_cost_bps", "mean"),
    ).reset_index()
    # Intervalle de Wilson : 80 succès ne signifient pas une probabilité connue de 100 %.
    n = aggregate["n_paths"].to_numpy(dtype=float)
    p = aggregate["completion_probability"].to_numpy(dtype=float)
    lower, upper = _wilson_bounds(p, n, protocol["bootstrap"]["confidence_level"])
    aggregate["completion_probability_ci_low"] = lower
    aggregate["completion_probability_ci_high"] = upper
    replications = (
        protocol["bootstrap"]["replications"] if bootstrap_reps is None else bootstrap_reps
    )
    primary = protocol["primary_contrast"]
    thresholds = protocol["decision_thresholds"]
    comparisons = []
    for key, frame in summary.groupby(CELL_KEYS, sort=False):
        cell = dict(zip(CELL_KEYS, key, strict=True))
        contrasts = [(name, "TWAP") for name in protocol["strategies"] if name != "TWAP"]
        contrasts.append(("ADAPTIVE", "VWAP"))
        for strategy, baseline in contrasts:
            result = paired_comparison(
                frame,
                strategy,
                baseline,
                replications,
                protocol["bootstrap"]["confidence_level"],
                protocol["bootstrap"]["seed"],
            )
            is_primary = split == "test" and all(
                {**cell, "strategy": strategy, "baseline": baseline}[name] == value
                for name, value in primary.items()
            )
            economical = result["saving_ci_low"] > thresholds["minimum_saving_bps"]
            comparable = result["fill_delta_ci_low"] > -thresholds["fill_noninferiority_pp"]
            completion_comparable = result["completion_noninferiority_bound_pp"] >= (
                -thresholds.get(
                    "completion_noninferiority_pp", thresholds["fill_noninferiority_pp"]
                )
            )
            risk_guard = result["q95_cost_delta_bps"] <= thresholds["q95_cost_margin_bps"]
            if economical and comparable and completion_comparable and risk_guard:
                evidence = "conditional_saving"
            elif result["completion_delta_pp"] > 0 and result["saving_bps"] < 0:
                evidence = "observed_completion_cost_tradeoff"
            else:
                evidence = "uncertain_or_no_economic_saving"
            comparisons.append(
                {
                    **cell,
                    **result,
                    "is_primary": is_primary,
                    "analysis_status": "primary" if is_primary else "descriptive",
                    "evidence": evidence,
                }
            )
    return aggregate, pd.DataFrame(comparisons)


def grid_invariance_check(protocol: dict | None = None) -> pd.DataFrame:
    """Même participation physique, trois discrétisations sans arrondi de Q/V."""
    protocol = default_protocol() if protocol is None else protocol
    settings = protocol["grid_check"]
    rows = []
    for model, parameters in protocol["models"].items():
        for buckets in settings["n_buckets"]:
            if settings["total_quantity"] % buckets or settings["total_market_volume"] % buckets:
                raise ValueError("Le contrôle de grille requiert Q et V divisibles exactement.")
            session = pd.Timestamp("2026-03-02")
            market = pd.DataFrame(
                {
                    "timestamp": session
                    + pd.to_timedelta(
                        np.arange(buckets) * (pd.Timedelta(minutes=390).value // buckets), unit="ns"
                    ),
                    "session": session.strftime("%Y-%m-%d"),
                    "bucket": np.arange(buckets),
                    "mid_price": settings["mid_price"],
                    "market_volume": settings["total_market_volume"] // buckets,
                    "spread_bps": settings["spread_bps"],
                }
            )
            config = SimulationConfig(**parameters, fee_bps=protocol["execution"]["fee_bps"])
            fills = simulate_policy(
                market, settings["total_quantity"], ExecutionPolicy("TWAP"), config
            )
            metrics = summarize_execution(
                fills,
                settings["total_quantity"],
                settings["mid_price"],
                settings["mid_price"],
                "buy",
            )
            denominator = settings["total_quantity"] * settings["mid_price"] / 10000
            rows.append(
                {
                    "impact_model": model,
                    "n_buckets": buckets,
                    "total_quantity": settings["total_quantity"],
                    "total_market_volume": settings["total_market_volume"],
                    "total_cost_bps": metrics["total_cost_bps"],
                    "impact_cost_bps": metrics["impact_cost"] / denominator,
                    "max_participation": float(fills["participation"].max()),
                }
            )
    result = pd.DataFrame(rows)
    reference = result.groupby("impact_model")["total_cost_bps"].transform("first")
    result["passed"] = np.isclose(result["total_cost_bps"], reference, atol=1e-10, rtol=0)
    return result


def run_study(
    protocol_path: str | Path | None = None,
    split: str = "test",
    paths: int | None = None,
    bootstrap_reps: int | None = None,
) -> StudyResult:
    """Exécuter le design annoncé ; les overrides sont explicitement exploratoires."""
    protocol = load_protocol(protocol_path)
    if split not in {"test", "development"}:
        raise ValueError("split doit valoir test ou development.")
    seeds = protocol["test_seeds" if split == "test" else "development_seeds"]
    if paths is not None:
        paths = _positive_count(paths, "paths")
        if paths > len(seeds):
            raise ValueError("paths ne peut pas dépasser la liste de graines du split.")
        seeds = seeds[:paths]
    if bootstrap_reps is not None:
        bootstrap_reps = _positive_count(bootstrap_reps, "bootstrap_reps")
    design_unchanged = _design(protocol) == default_protocol()
    confirmatory = split == "test" and paths is None and bootstrap_reps is None and design_unchanged
    history = generate_market_data(
        protocol["training"]["n_days"], protocol["n_buckets"], protocol["training"]["seed"]
    )
    target = pd.Timestamp(history["session"].max()) + pd.offsets.BDay(1)
    forecast = forecast_volume_profile(
        history, target.strftime("%Y-%m-%d"), protocol["training"]["lookback"]
    )
    summaries, forecast_rows, samples = [], [], []
    input_hash = sha256()
    for path_index, seed in enumerate(seeds):
        base = generate_market_data(1, protocol["n_buckets"], seed)
        session = target + pd.offsets.BDay(path_index)
        base["timestamp"] += session - base["timestamp"].iloc[0].normalize()
        base["session"] = session.strftime("%Y-%m-%d")
        path_id = f"{split}_{seed}"
        input_hash.update(base.to_csv(index=False, float_format="%.12g").encode("utf-8"))
        for scenario, scenario_parameters in protocol["scenarios"].items():
            market = transform_scenario(base, scenario_parameters)
            volumes = market["market_volume"].to_numpy(dtype=float)
            total_volume = int(volumes.sum())
            if total_volume == 0:
                raise ValueError("Le protocole doit conserver un volume journalier positif.")
            profile = volumes / total_volume
            forecast_rows.append(
                {
                    "path_id": path_id,
                    "seed": seed,
                    "session": session.strftime("%Y-%m-%d"),
                    "split": split,
                    "scenario": scenario,
                    "expected_daily_volume": forecast.expected_daily_volume,
                    "realized_daily_volume": total_volume,
                    "daily_volume_error_pct": 100
                    * (forecast.expected_daily_volume / total_volume - 1),
                    "profile_mae": float(np.abs(profile - forecast.weights).mean()),
                    "uniform_profile_mae": float(np.abs(profile - 1 / len(profile)).mean()),
                }
            )
            for ratio in protocol["quantity_adv_ratios"]:
                quantity = max(1, int(round(ratio * forecast.expected_daily_volume)))
                for model, model_parameters in protocol["models"].items():
                    for deadline_mode in protocol["deadline_modes"]:
                        parameters = protocol["execution"]
                        config = SimulationConfig(
                            side=protocol["side"],
                            **model_parameters,
                            deadline_mode=deadline_mode,
                            expected_daily_volume=forecast.expected_daily_volume,
                            daily_volatility=parameters["daily_volatility"]
                            * scenario_parameters["volatility_multiplier"],
                            **{
                                name: parameters[name]
                                for name in (
                                    "fee_bps",
                                    "max_participation",
                                    "terminal_fraction",
                                    "terminal_max_participation",
                                )
                            },
                        )
                        for strategy in protocol["strategies"]:
                            policy = ExecutionPolicy(
                                strategy,
                                forecast.weights,
                                participation_rate=quantity / forecast.expected_daily_volume,
                                catchup_gain=parameters["catchup_gain"],
                            )
                            fills = simulate_policy(market, quantity, policy, config)
                            arrival = float(market["mid_price"].iloc[0])
                            metrics = summarize_execution(
                                fills, quantity, arrival, arrival, protocol["side"]
                            )
                            if abs(metrics["reconciliation_error"]) > 1e-7 * quantity * arrival:
                                raise RuntimeError("Échec de réconciliation de l'étude.")
                            denominator = quantity * arrival / 10000
                            explicit = (
                                metrics["spread_cost"]
                                + metrics["impact_cost"]
                                + metrics["fee_cost"]
                            )
                            q = fills["executed_quantity"].to_numpy(dtype=float)
                            costs = q * (
                                fills["half_spread_per_share"].to_numpy(dtype=float)
                                + fills["impact_per_share"].to_numpy(dtype=float)
                            )
                            costs += fills["fee"].to_numpy(dtype=float)
                            terminal_cost = costs[fills["is_terminal"].to_numpy(dtype=bool)].sum()
                            identifiers = {
                                "path_id": path_id,
                                "seed": seed,
                                "session": session.strftime("%Y-%m-%d"),
                                "split": split,
                                "scenario": scenario,
                                "impact_model": model,
                                "deadline_mode": deadline_mode,
                                "quantity_adv_ratio": ratio,
                                "strategy": strategy,
                            }
                            summaries.append(
                                {
                                    **identifiers,
                                    "order_quantity": quantity,
                                    "expected_daily_volume": forecast.expected_daily_volume,
                                    "realized_daily_volume": total_volume,
                                    "total_cost_bps": metrics["total_cost_bps"],
                                    "explicit_cost_bps": explicit / denominator,
                                    "opportunity_cost_bps": metrics["opportunity_cost"]
                                    / denominator,
                                    "fill_rate": metrics["fill_rate"],
                                    "completed": metrics["unfilled_quantity"] == 0,
                                    "terminal_quantity": int(fills["terminal_quantity"].sum()),
                                    "terminal_explicit_cost_bps": float(
                                        terminal_cost / denominator
                                    ),
                                    "max_realized_participation": float(
                                        fills["participation"].max()
                                    ),
                                    "reconciliation_error": metrics["reconciliation_error"],
                                }
                            )
                            if path_index == 0:
                                samples.append(
                                    fills.assign(
                                        **{
                                            name: value
                                            for name, value in identifiers.items()
                                            if name not in {"session"}
                                        }
                                    )
                                )
    summary = pd.DataFrame(summaries)
    aggregate, comparisons = summarize_study(
        summary,
        protocol,
        split if confirmatory else "exploratory",
        bootstrap_reps,
    )
    grid_check = grid_invariance_check(protocol)
    if not grid_check["passed"].all():
        raise RuntimeError("Échec du contrôle de subdivision temporelle.")
    return StudyResult(
        summary,
        aggregate,
        comparisons,
        pd.DataFrame(forecast_rows),
        grid_check,
        {
            "study_version": "2.0.0",
            "data_type": "synthetic",
            "split": split,
            "analysis_status": "pre_specified_test" if confirmatory else "exploratory",
            "protocol": protocol,
            "protocol_sha256": _fingerprint(protocol),
            "design_sha256": _fingerprint(_design(protocol)),
            "design_unchanged": design_unchanged,
            "executed_seeds": seeds,
            "n_paths": len(seeds),
            "paths_override": paths,
            "bootstrap_replications": protocol["bootstrap"]["replications"]
            if bootstrap_reps is None
            else bootstrap_reps,
            "bootstrap_override": bootstrap_reps,
            "forecast_training_sessions": list(forecast.training_sessions),
            "input_fingerprint_sha256": input_hash.hexdigest(),
            "decision_convention": "arrival_mid",
            "terminal_convention": "mark_unfilled_at_last_mid",
            "impact_convention": "temporary_local_realized_participation_not_calibrated",
            "bootstrap_unit": "path_paired_within_each_scenario_no_bar_resampling",
            "uncertainty_scope": "Monte_Carlo_conditional_on_fixed_synthetic_generator_and_model",
            "multiple_comparisons": "single_primary_contrast_other_intervals_descriptive",
            "real_data_validation": "not_performed_by_synthetic_study",
        },
        pd.concat(samples, ignore_index=True),
    )

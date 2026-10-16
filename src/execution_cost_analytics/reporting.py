"""Exporter les tables et des figures lisibles à partir des calculs exécutés."""

import json
from importlib.metadata import version
from pathlib import Path
from platform import python_version

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .experiment import ExperimentResult

matplotlib.use("Agg")
COLORS = {"TWAP": "#2563a6", "VWAP": "#b55b14", "POV": "#20816a", "ADAPTIVE": "#8846a6"}


def _save(figure: plt.Figure, path: Path) -> None:
    figure.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _figures(result: ExperimentResult, directory: Path) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.18,
        }
    )
    session = result.metadata["evaluated_sessions"][0]
    day = result.fills.loc[result.fills["session"].eq(session)]
    market = day.loc[day["strategy"].eq("TWAP")]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
    axes[0].plot(market["bucket"], market["mid_price"], color="#384454", linewidth=1.8)
    label = (
        "Séance fictive" if result.metadata.get("data_type") == "synthetic" else "Séance fournie"
    )
    axes[0].set(ylabel="Prix mid (unité du jeu de données)", title=f"{label} — {session}")
    for strategy, group in day.groupby("strategy", sort=False):
        axes[1].step(
            group["bucket"],
            group["executed_quantity"].cumsum(),
            where="mid",
            label=strategy,
            color=COLORS[strategy],
            linewidth=2,
        )
    axes[1].axhline(
        result.metadata["quantity"], color="#68717c", linestyle="--", label="Ordre initial"
    )
    axes[1].set(
        xlabel="Créneau intrajournalier (indice)", ylabel="Quantité exécutée cumulée (actions)"
    )
    axes[1].legend(ncol=4, loc="upper left")
    _save(fig, directory / "execution_paths.png")

    components = [
        "delay_cost",
        "timing_cost",
        "spread_cost",
        "impact_cost",
        "fee_cost",
        "opportunity_cost",
    ]
    labels = ["Délai", "Timing", "Demi-spread", "Impact", "Frais", "Opportunité"]
    summary = result.summary.copy()
    for column in components:
        summary[column] = (
            summary[column] / (summary["order_quantity"] * summary["decision_price"]) * 10_000
        )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    x = np.arange(len(components))
    for offset, strategy in enumerate(COLORS):
        mean = summary.loc[summary["strategy"].eq(strategy), components].mean()
        axes[0].bar(
            x + (offset - 1.5) * 0.18, mean, width=0.18, label=strategy, color=COLORS[strategy]
        )
    axes[0].axhline(0, color="#68717c", linewidth=0.8)
    axes[0].set(
        xticks=x,
        xticklabels=labels,
        ylabel="Contribution moyenne (bp de l'ordre initial)",
        title="Décomposition de l'implementation shortfall",
    )
    axes[0].tick_params(axis="x", rotation=25)
    axes[0].legend(ncol=2)
    agg = result.aggregate_summary
    axes[1].bar(
        agg["strategy"], agg["mean_fill_rate"] * 100, color=[COLORS[s] for s in agg["strategy"]]
    )
    axes[1].set(
        ylim=(0, 110),
        ylabel="Part de l'ordre initial exécutée (%)",
        title="Complétion moyenne sur les séances évaluées",
    )
    for i, value in enumerate(agg["mean_fill_rate"] * 100):
        axes[1].text(i, value + 2, f"{value:.1f} %", ha="center")
    _save(fig, directory / "cost_decomposition.png")

    profile = result.profiles.loc[result.profiles["session"].eq(session)]
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    ax.plot(
        profile["bucket"],
        profile["realized_weight"] * 100,
        label="Réalisé (connu après la séance)",
        color="#68717c",
        marker="o",
        markersize=3,
    )
    ax.plot(
        profile["bucket"],
        profile["forecast_weight"] * 100,
        label="Prévision issue des séances précédentes",
        color=COLORS["VWAP"],
        linewidth=2,
    )
    ax.axhline(100 / len(profile), color=COLORS["TWAP"], linestyle="--", label="Profil uniforme")
    ax.set(
        xlabel="Créneau intrajournalier (indice)",
        ylabel="Part du volume journalier (%)",
        title=f"Prévision du profil de volume — {session}",
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=1)
    _save(fig, directory / "volume_forecast.png")

    sensitivity = (
        result.sensitivity.groupby(["strategy", "impact_coefficient"], sort=False)["total_cost_bps"]
        .mean()
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
    for strategy, group in sensitivity.groupby("strategy", sort=False):
        ax.plot(
            group["impact_coefficient"],
            group["total_cost_bps"],
            marker="o",
            color=COLORS[strategy],
            label=strategy,
        )
    ax.set(
        xlabel="Coefficient d'impact hypothétique η (sans unité)",
        ylabel="Implementation shortfall moyen (bp)",
        title="Sensibilité : mêmes marchés et mêmes plans, hypothèse d'impact variable",
    )
    ax.legend()
    _save(fig, directory / "impact_sensitivity.png")


def write_report(result: ExperimentResult, output_dir: str | Path = "reports") -> Path:
    """Créer les rapports ; remplacer uniquement les artefacts nommés du projet."""
    directory = Path(output_dir)
    figures = directory / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    tables = {
        "summary": result.summary,
        "aggregate_summary": result.aggregate_summary,
        "fills": result.fills,
        "forecast_metrics": result.forecast_metrics,
        "sensitivity": result.sensitivity,
        "volume_profiles": result.profiles,
    }
    for name, table in tables.items():
        table.to_csv(directory / f"{name}.csv", index=False, float_format="%.10g")
    metadata = {
        **result.metadata,
        "software": {
            "python": python_version(),
            **{name: version(name) for name in ["numpy", "pandas", "matplotlib"]},
        },
    }
    (directory / "experiment.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _figures(result, figures)
    rows = []
    for row in result.aggregate_summary.itertuples(index=False):
        std = f"{row.std_cost_bps:.2f}" if pd.notna(row.std_cost_bps) else "n/a (une séance)"
        rows.append(
            f"| {row.strategy} | {row.evaluated_sessions} | {row.mean_fill_rate:.1%} | {row.mean_cost_bps:.2f} | {std} |"
        )
    forecast = result.forecast_metrics
    reconciliation = result.summary["reconciliation_error"].abs().max()
    dataset_label = (
        "synthétiques"
        if result.metadata.get("data_type") == "synthetic"
        else "fournies par l'utilisateur"
    )
    forecast_note = (
        "Le générateur possède volontairement un profil en U : la comparaison teste le fonctionnement de la méthode sur ce cas construit."
        if result.metadata.get("data_type") == "synthetic"
        else "Cette comparaison décrit uniquement le jeu de données fourni ; elle ne démontre pas une généralisation à un autre marché."
    )
    report = f"""# Démonstration V2 — execution-cost-analytics

Données **{dataset_label}**, {result.metadata["n_buckets"]} créneaux par séance. Ordre : **{result.metadata["quantity"]:,} actions**, côté **{result.metadata["side"]}**. Les chiffres ci-dessous sont calculés par le même pipeline que le notebook exécuté `notebooks/01_execution_cost_analysis.ipynb`.

## Protocole

- Historique initial : {result.metadata["initial_training_days"]} séances ; fenêtre glissante : {result.metadata["lookback"]} séances antérieures.
- Évaluation : du {result.metadata["evaluated_sessions"][0]} au {result.metadata["evaluated_sessions"][-1]} ; aucune séance cible n'entre dans sa propre prévision.
- Décision fictive : dernier mid de la séance précédente ; arrivée : premier mid de la séance évaluée ; reliquat valorisé au dernier mid de cette séance.
- POV : {result.metadata["participation"]:.1%} du volume externe contemporain ; plafond ordinaire : {result.metadata["config"]["max_participation"]:.1%}. Mode d'échéance : `{result.metadata["config"]["deadline_mode"]}`. ADAPTIVE rattrape son retard avec les exécutions antérieures réellement observées.

## Comparaison descriptive

| Stratégie | Séances | Complétion moyenne | IS moyen (bp) | Écart-type entre séances (bp) |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

**Lecture :** un IS positif est un coût défavorable, pour un achat comme pour une vente. Il inclut la valorisation du reliquat, qui peut être négative si l'évolution des prix lui est favorable. Un faible coût sur quelques séances fictives ne prouve aucune supériorité de stratégie. L'écart-type décrit la dispersion ; ce n'est pas un intervalle de confiance.

![Prix et quantités exécutées](figures/execution_paths.png)

![Coûts et complétion](figures/cost_decomposition.png)

## Prévision des volumes

Erreur absolue moyenne des parts de volume par créneau : **{forecast["profile_mae"].mean():.6f}** pour le profil historique, contre **{forecast["uniform_profile_mae"].mean():.6f}** pour le profil uniforme. Ces valeurs sont des fractions du volume journalier, moyennées sur les créneaux puis sur les séances ; multiplier par 100 pour les exprimer en points de pourcentage. {forecast_note}

![Prévision du profil](figures/volume_forecast.png)

## Sensibilité et contrôles

![Sensibilité à l'impact](figures/impact_sensitivity.png)

Écart absolu maximal entre l'IS direct et la somme de ses six composantes : **{reconciliation:.3g} unité monétaire du jeu de données**. Les tests vérifient aussi les achats, les ventes, le reliquat, la conservation des quantités et l'absence d'accès aux créneaux futurs dans le calendrier POV.

## Limites

Ce laboratoire utilise une simulation par barres : POV participe au flux contemporain observé dans une approximation agrégée. L'impact temporaire vaut `mid × eta × sigma × (quantité exécutée / volume local réalisé)^alpha`. Le volume prévu sert à décider et n'entre pas dans la facturation de l'impact. Cette forme reste hypothétique et non calibrée. Les prix du marché sont exogènes ; aucun carnet ni latence n'est reproduit.

Le benchmark VWAP est une moyenne pondérée des **mids** de la séance, calculée ex post, et non le VWAP officiel de transactions d'une place. La comparaison au VWAP sur des ordres partiellement exécutés doit être lue avec le taux de complétion et l'IS total.

## Retrouver les calculs

- `summary.csv` : chaque séance et chaque stratégie, six composantes et réconciliation.
- `aggregate_summary.csv` : tableau de comparaison ci-dessus.
- `fills.csv` : chaque créneau, plan, quantité exécutée, prix et frais.
- `forecast_metrics.csv` et `volume_profiles.csv` : prévisions et évaluation ex post.
- `sensitivity.csv` : scénarios η = 0 ; 0,025 ; 0,05 ; 0,1.
- `experiment.json` : paramètres et versions utilisés.

Le protocole V2, ses tests de grille et l'étude appariée sont dans `docs/PROTOCOLE_V2.md` et `reports/study/RESULTATS.md`. Le guide et les formules sont dans `docs/GUIDE_PAS_A_PAS.md` et `docs/METHODOLOGIE.md` à la racine du dépôt. Cette démonstration remplace les résultats V1 fondés sur l'ancien impact par tranche.
"""
    path = directory / "RESULTATS.md"
    path.write_text(report, encoding="utf-8")
    return path

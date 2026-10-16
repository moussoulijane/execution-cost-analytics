"""Tables, figures et conclusions conditionnelles de l'étude V2."""

import json
from importlib.metadata import version
from pathlib import Path
from platform import python_version

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .reporting import COLORS, _save

SCENARIO_LABELS = {
    "normal": "Volume habituel",
    "low_volume": "Volume à 55 %",
    "midday_shutdown": "Interruption centrale",
    "late_shift": "Volume tardif",
    "stressed": "Liquidité et volatilité dégradées",
}


EVIDENCE_LABELS = {
    "conditional_saving": "Économie conditionnelle selon le protocole",
    "observed_completion_cost_tradeoff": "Compromis coût / complétion observé",
    "uncertain_or_no_economic_saving": "Économie utile non établie",
}


def _table(frame: pd.DataFrame, columns: list[str], labels: list[str]) -> str:
    rows = ["| " + " | ".join(labels) + " |", "| " + " | ".join(["---"] * len(labels)) + " |"]
    for values in frame[columns].itertuples(index=False, name=None):
        formatted = [f"{value:.3f}" if isinstance(value, float) else str(value) for value in values]
        rows.append("| " + " | ".join(formatted) + " |")
    return "\n".join(rows)


def _selected(frame: pd.DataFrame, scenario: str) -> pd.DataFrame:
    return frame.loc[
        frame["scenario"].eq(scenario)
        & frame["impact_model"].eq("sqrt")
        & np.isclose(frame["quantity_adv_ratio"], 0.10)
    ].copy()


def _figures(result, figures: Path) -> None:
    scenarios = list(result.aggregate["scenario"].unique())
    focus = "low_volume" if "low_volume" in scenarios else scenarios[0]
    selected = _selected(result.aggregate, focus)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), layout="constrained")
    x = np.arange(4)
    for offset, mode in enumerate(["soft", "common_deadline"]):
        group = selected.loc[selected["deadline_mode"].eq(mode)].set_index("strategy")
        group = group.reindex(list(COLORS))
        label = "Échéance souple" if mode == "soft" else "Urgence finale commune"
        axes[0].bar(
            x + (offset - 0.5) * 0.36,
            group["mean_explicit_cost_bps"],
            width=0.36,
            label=label,
            alpha=1 if offset else 0.55,
        )
        axes[1].bar(
            x + (offset - 0.5) * 0.36,
            group["completion_probability"] * 100,
            width=0.36,
            label=label,
            alpha=1 if offset else 0.55,
            yerr=np.vstack(
                [
                    np.maximum(
                        0, group["completion_probability"] - group["completion_probability_ci_low"]
                    ),
                    np.maximum(
                        0, group["completion_probability_ci_high"] - group["completion_probability"]
                    ),
                ]
            )
            * 100,
            capsize=3,
            error_kw={"elinewidth": 1},
        )
    for ax in axes:
        ax.set_xticks(x, list(COLORS))
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2, fontsize=8)
    axes[0].set(
        ylabel="Spread + impact + frais moyens (bp)", title="Coût explicite effectivement payé"
    )
    axes[1].set(
        ylabel="Ordres entièrement exécutés (%)", ylim=(0, 115), title="Probabilité de terminer"
    )
    fig.suptitle(f"{SCENARIO_LABELS.get(focus, focus)} — ordre = 10 % du volume journalier prévu")
    _save(fig, figures / "completion_cost.png")

    comparison = result.comparisons.loc[
        result.comparisons["strategy"].eq("ADAPTIVE")
        & result.comparisons["baseline"].eq("VWAP")
        & result.comparisons["deadline_mode"].eq("common_deadline")
        & np.isclose(result.comparisons["quantity_adv_ratio"], 0.10)
    ]
    fig, ax = plt.subplots(figsize=(11, max(4.5, len(scenarios) * 1.05)), layout="constrained")
    for offset, model in enumerate(["sqrt", "linear"]):
        group = (
            comparison.loc[comparison["impact_model"].eq(model)]
            .set_index("scenario")
            .reindex(scenarios)
        )
        center = group["saving_bps"].to_numpy()
        lower, upper = group["saving_ci_low"].to_numpy(), group["saving_ci_high"].to_numpy()
        y = np.arange(len(scenarios)) + (offset - 0.5) * 0.22
        ax.errorbar(
            center,
            y,
            xerr=np.vstack([np.maximum(0, center - lower), np.maximum(0, upper - center)]),
            fmt="o" if model == "sqrt" else "s",
            capsize=3,
            label="Impact racine carrée" if model == "sqrt" else "Impact linéaire",
        )
    ax.axvline(0, color="#6b7280", linewidth=1)
    ax.axvline(
        0.5, color="#6b7280", linewidth=1, linestyle="--", label="Gain minimal illustratif : 0,5 bp"
    )
    ax.set(
        yticks=np.arange(len(scenarios)),
        yticklabels=[SCENARIO_LABELS.get(s, s) for s in scenarios],
        xlabel="Économie d'IS : VWAP − ADAPTIVE (bp), IC bootstrap apparié 95 %",
        title="L'adaptation réduit-elle le coût total ?",
    )
    ax.legend(loc="best", fontsize=8)
    ax.grid(axis="x", alpha=0.2)
    _save(fig, figures / "paired_savings.png")

    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    modes = {"soft": "o", "common_deadline": "^"}
    for strategy, color in COLORS.items():
        for mode, marker in modes.items():
            group = result.aggregate.loc[
                result.aggregate["scenario"].eq(focus)
                & result.aggregate["impact_model"].eq("sqrt")
                & result.aggregate["strategy"].eq(strategy)
                & result.aggregate["deadline_mode"].eq(mode)
            ].sort_values("quantity_adv_ratio")
            ax.plot(
                group["mean_explicit_cost_bps"],
                group["completion_probability"] * 100,
                color=color,
                marker=marker,
                linestyle="-" if mode == "soft" else "--",
                label=f"{strategy} · {'souple' if mode == 'soft' else 'urgence'}",
                markerfacecolor="none",
            )
            last = group.iloc[-1]
            ax.scatter(
                [last["mean_explicit_cost_bps"]],
                [last["completion_probability"] * 100],
                color=color,
                marker=marker,
                zorder=3,
            )
    ax.set(
        xlabel="Coût explicite moyen (bp du notionnel initial)",
        ylabel="Ordres entièrement exécutés (%)",
        ylim=(-3, 105),
        title="Compromis observés — creux : Q = 5 % ADV ; plein : Q = 10 % ADV",
    )
    ax.grid(alpha=0.2)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8)
    _save(fig, figures / "cost_completion_tradeoff.png")


def write_study_report(result, output_dir: str | Path = "reports/study") -> Path:
    """Exporter les sorties sans re-sélectionner un contraste après observation."""
    directory = Path(output_dir)
    figures = directory / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for name in [
        "summary",
        "aggregate",
        "comparisons",
        "forecast_metrics",
        "grid_check",
        "sample_fills",
    ]:
        getattr(result, name).to_csv(directory / f"{name}.csv", index=False, float_format="%.12g")
    metadata = {
        **result.metadata,
        "software": {
            "python": python_version(),
            **{name: version(name) for name in ["numpy", "pandas", "matplotlib"]},
        },
    }
    (directory / "experiment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _figures(result, figures)
    real = metadata.get("data_type") == "public_historical"
    title = (
        "Confrontation historique publique"
        if real
        else "Étude V2 : volume incertain et coût de complétion"
    )
    primary = result.comparisons.loc[result.comparisons["is_primary"].eq(True)]
    display_comparisons = result.comparisons.loc[
        result.comparisons["strategy"].eq("ADAPTIVE")
        & result.comparisons["baseline"].eq("VWAP")
        & result.comparisons["impact_model"].eq("sqrt")
        & result.comparisons["deadline_mode"].eq("common_deadline")
        & np.isclose(result.comparisons["quantity_adv_ratio"], 0.10)
    ].copy()
    interpretation = []
    for row in primary.itertuples(index=False):
        interpretation.append(
            f"Contraste principal fixé avant l'expérience : **ADAPTIVE contre VWAP**, volume réalisé réduit, ordre de 10 % du volume prévu, urgence finale commune, impact racine carrée. Économie moyenne d'IS : **{row.saving_bps:.3f} bp**, IC bootstrap apparié 95 % **[{row.saving_ci_low:.3f} ; {row.saving_ci_high:.3f}]**. Variation de probabilité de terminer : **{row.completion_delta_pp:+.2f} points de pourcentage**. Borne prudente de non-infériorité de complétion : **{row.completion_noninferiority_bound_pp:.2f} points**, à comparer à la marge de −1 point. Lecture du protocole : **`{row.evidence}`**."
        )
    if not interpretation:
        interpretation = [
            "Aucun contraste confirmatoire dans cette sortie. Les comparaisons sont descriptives ou exploratoires."
        ]
    display_comparisons["evidence"] = display_comparisons["evidence"].map(EVIDENCE_LABELS)
    for key, label in EVIDENCE_LABELS.items():
        interpretation = [line.replace(f"`{key}`", label) for line in interpretation]
    max_error = result.summary["reconciliation_error"].abs().max()
    grid_passed = bool(len(result.grid_check) and result.grid_check["passed"].all())
    data_note = (
        "Prix et volumes de transactions historiques Binance Vision, BTCUSDT et ETHUSDT en janvier 2026. Chaque actif est étudié séparément : ses journées évaluées constituent les paires. Le prix est un VWAP de transactions par barre, pas un milieu bid/ask ; spread de 2 bp et impact sont des hypothèses. Les 14 premières journées forment l'historique initial ; les 17 suivantes sont évaluées chronologiquement avec une fenêtre de 14 jours. Les choix ont été fixés avant lecture des résultats."
        if real
        else "Marchés synthétiques : mêmes trajectoires pour toutes les stratégies, cinq régimes, deux tailles d'ordre, deux modèles d'impact et deux modes d'échéance. Les graines de développement sont séparées des graines d'évaluation. L'unité de rééchantillonnage est le chemin indépendant, jamais une barre. Les scénarios et seuils sont figés dans le protocole et son empreinte."
    )
    columns = [
        "scenario",
        "n_pairs",
        "saving_bps",
        "saving_ci_low",
        "saving_ci_high",
        "completion_delta_pp",
        "completion_noninferiority_bound_pp",
        "evidence",
    ]
    labels = [
        "Régime / actif",
        "Paires",
        "Économie IS (bp)",
        "IC bas",
        "IC haut",
        "Δ complétion (pp)",
        "Borne prudente (pp)",
        "Lecture",
    ]
    historical_warning = (
        "**Incertitude historique descriptive :** les 17 journées sont consécutives et les prévisions utilisent des fenêtres glissantes. Le bootstrap de journées et Wilson supposent une indépendance approximative non vérifiée ; leurs intervalles ne constituent pas une preuve statistique de performance historique ni une validation de l'impact."
        if real
        else ""
    )
    comparison_scope = (
        "Cette confrontation historique ne comporte aucun test confirmatoire. Les lignes et le modèle linéaire décrivent les résultats conditionnels et leur sensibilité ; les intervalles ne suffisent pas à établir une performance historique."
        if real
        else (
            "Le contraste principal est le seul test prévu comme principal. Les autres lignes et le modèle linéaire décrivent la sensibilité, sans transformer une cellule favorable en découverte confirmatoire."
            if len(primary)
            else "Cette sortie exploratoire ne comporte aucun test confirmatoire. Les lignes et le modèle linéaire décrivent les résultats conditionnels et leur sensibilité, sans transformer une cellule favorable en découverte confirmatoire."
        )
    )
    license_note = (
        "\n## Attribution et licence des résultats historiques\n\nDonnées : **Binance Vision**. Ces tables, figures et commentaires dérivés des données sont placés sous **CC BY-NC-SA 4.0**, sous réserve des conditions Binance Vision : https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md . La licence MIT du code ne couvre pas ces sorties. Les archives brutes et CSV préparés restent dans `data/`, ignoré par Git. Les URLs exactes, empreintes SHA-256 et contrôles de complétude figurent dans `experiment.json`.\n"
        if real
        else ""
    )
    report = f"""# {title}

{data_note}

{historical_warning}

## Question et protocole

Quel coût supplémentaire accompagne une meilleure probabilité de terminer lorsque les volumes sont mal prévus ? Le protocole décrit une étude ; il ne garantit aucun gagnant. Il est figé localement avant les expériences, sans prétendre à un préenregistrement indépendant.

{chr(10).join(interpretation)}

Le signe de l'économie est `IS_VWAP − IS_ADAPTIVE` : positif favorise ADAPTIVE. La variation de complétion est `P(terminer)_ADAPTIVE − P(terminer)_VWAP`. Les intervalles sont conditionnels au jeu de données et au modèle ; ils n'incluent pas l'incertitude sur la validité économique du simulateur.

## Comparaisons conditionnelles

{_table(display_comparisons, columns, labels)}

{comparison_scope} Une amélioration de complétion accompagnée d'un coût plus élevé est un compromis à chiffrer ; aucun budget client ne permet ici de déclarer ce prix acceptable universellement.

![Coût explicite et probabilité de terminer](figures/completion_cost.png)

![Comparaisons appariées](figures/paired_savings.png)

![Compromis coût et complétion](figures/cost_completion_tradeoff.png)

## Comment juger les résultats

- Quantités entières, limites de capacité et chronologie : contrôlées par les tests.
- Réconciliation : écart absolu maximal **{max_error:.3g}** unité monétaire.
- Grille 26 / 52 / 104 : **{"contrôles réussis" if grid_passed else "contrôles à examiner"}** dans `grid_check.csv`. Même prix, même participation, quantité et volume subdivisés proportionnellement ; les arrondis sont testés séparément.
- Gain minimal illustratif : **0,5 bp**. Marge de non-infériorité de complétion : **1 point**. Écart de q95 des coûts : garde-fou **descriptif** de 2 bp, pas un test de risque établi.
- Le bootstrap peut donner un intervalle de complétion dégénéré `[0 ; 0]` en l'absence de cas discordants observés. Il ne prouve pas que la différence vraie est nulle. La décision ajoute la borne prudente `100 × (WilsonLower(candidat) − WilsonUpper(baseline))` ; les bornes Wilson restent approximatives. Voir `completion_bootstrap_degenerate` et `completion_noninferiority_bound_pp`.
- Toujours examiner `completion_probability` (ordre entièrement terminé), `mean_fill_rate` (fraction moyenne exécutée), IS et coût explicite. Ce sont des indicateurs différents.
- Le nombre de chemins est fixé dans le protocole ; aucune taille d'échantillon n'est sélectionnée pour obtenir un résultat favorable.

## Modèle et information disponible

La politique reçoit un plan ex ante et les quantités réellement exécutées auparavant. ADAPTIVE ajoute `ceil(gain × retard antérieur)` à la demande courante. Le simulateur facture ensuite l'impact selon `prix × eta × sigma × (quantité / volume local réalisé)^alpha`. La prévision n'est pas utilisée comme liquidité de facturation.

En mode souple, aucun remplissage final n'est imposé. En mode urgence commune, toutes les politiques demandent le reliquat durant les derniers `ceil(20 % × nombre de créneaux)` créneaux, avec plafond de participation 40 % au lieu de 15 %. Spread, impact et frais sont payés ; les capacités peuvent rendre l'objectif impossible. Aucun reliquat n'est acheté gratuitement au dernier prix.

Les deux exposants, 0,5 et 1, sont normalisés au même impact à 10 % de participation. Cela facilite la comparaison de forme ; aucune calibration de marché n'est revendiquée.

## Limites et reproductibilité

Les prix demeurent exogènes, sans carnet, files d'attente, latence ou impact permanent. POV est une instruction de participation au flux contemporain dans une représentation agrégée. Les modèles d'impact restent hypothétiques. Ajouter des observations historiques ne suffit pas à identifier l'effet causal de nos propres ordres.

`summary.csv` conserve chaque paire et configuration, `aggregate.csv` les moyennes et queues, `comparisons.csv` les différences appariées et intervalles, `sample_fills.csv` des traces d'exécution, `forecast_metrics.csv` les erreurs de prévision et `experiment.json` les paramètres et empreintes. Le guide se trouve dans `docs/GUIDE_PAS_A_PAS.md` à la racine du projet.
{license_note}
"""
    path = directory / "RESULTATS.md"
    path.write_text(report.rstrip() + "\n", encoding="utf-8")
    if real:
        (directory / "LICENSE.md").write_text(
            "# Licence des résultats historiques\n\nAttribution : Binance Vision.\n\nCes résultats dérivés sont sous CC BY-NC-SA 4.0 : https://creativecommons.org/licenses/by-nc-sa/4.0/ . Conditions supplémentaires : "
            + metadata.get(
                "terms_url",
                "https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md",
            )
            + "\n\nLe code du projet conserve sa licence MIT.\n",
            encoding="utf-8",
        )
    return path

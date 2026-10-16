"""Reconstruire les sources des notebooks ; execute_notebook.py recrée les sorties."""

from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell


def save(cells, name):
    document = nbf.v4.new_notebook(cells=cells)
    document.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nbf.write(document, ROOT / "notebooks" / name)


save(
    [
        md("""# Démonstration V2 : décisions, exécutions et coûts

Marché synthétique. Cette démonstration explique les mécanismes ; le second notebook examine le protocole et les incertitudes. Les résultats V1 fondés sur `sqrt(q / volume_journalier_prévu)` sont remplacés.
"""),
        code("""from pathlib import Path

import pandas as pd
from IPython.display import Image, display

from execution_cost_analytics.data import generate_market_data
from execution_cost_analytics.experiment import run_experiment
from execution_cost_analytics.reporting import write_report
from execution_cost_analytics.strategies import pov_schedule, twap_schedule, vwap_schedule

ROOT = Path.cwd()
if not (ROOT / 'pyproject.toml').exists():
    ROOT = ROOT.parent
assert (ROOT / 'pyproject.toml').exists()
"""),
        md("""## 1. Retrouver les quantités à la main

TWAP et VWAP construisent un calendrier entier. La fonction POV ci-dessous illustre la participation à un flux ; l'expérience utilise le moteur séquentiel et les quantités effectivement exécutées.
"""),
        code("""pd.DataFrame({
    'TWAP_101': twap_schedule(101, 4),
    'VWAP_100': vwap_schedule(100, [0.1, 0.2, 0.3, 0.4]),
    'POV_100_a_10pct': pov_schedule(100, [100, 200, 100, 100], 0.1),
})
"""),
        md("""## 2. Simuler quatre politiques sur les mêmes séances

La prévision utilise les 20 journées antérieures. ADAPTIVE ajoute au plan prévu un rattrapage du retard observé avec les fills passés. Le moteur applique ensuite capacité et coût réalisés. La démonstration prend sa référence à la dernière observation de la veille ; l'étude V2 prend décision = arrivée pour isoler l'exécution intraday.
"""),
        code("""market = generate_market_data(n_days=40, n_buckets=26, seed=42)
result = run_experiment(market, quantity=50_000, train_days=30, lookback=20)
result.metadata.update({'data_type': 'synthetic', 'seed': 42, 'generated_days': 40})
write_report(result, ROOT / 'reports')
display(result.aggregate_summary.round(4))
assert (result.forecast_metrics['last_training_session'] < result.forecast_metrics['session']).all()
assert result.summary['reconciliation_error'].abs().max() < 1e-6
display(Image(filename=str(ROOT / 'reports/figures/cost_decomposition.png')))
"""),
        md("""## 3. Coût local et information disponible

L'impact temporaire par unité vaut `prix × eta × sigma × (q / volume_local_réalisé)^alpha`. La prévision sert à décider, pas à facturer une liquidité artificielle. Dans un cas contrôlé, subdiviser quantité et volume proportionnellement conserve la participation et le coût. Ce contrôle ne calibre pas le modèle économiquement.
"""),
        code("""from execution_cost_analytics.study import grid_invariance_check

grid = grid_invariance_check()
display(grid)
assert grid['passed'].all()
display(Image(filename=str(ROOT / 'reports/figures/volume_forecast.png')))
"""),
        md("""## 4. Reprendre le développement

Le guide `docs/GUIDE_PAS_A_PAS.md` relie chaque fonction à un exemple et un test. Pour tester la règle terminale : `demo --deadline-mode common_deadline --output-dir outputs/deadline`. Les derniers `ceil(20 % × B)` créneaux reçoivent la même instruction pour toutes les méthodes : demander le reliquat sous un plafond de 40 %, avec spread, impact et frais. Un manque de capacité laisse l'ordre incomplet.
"""),
    ],
    "01_execution_cost_analysis.ipynb",
)

save(
    [
        md("""# V2 — Volume incertain, coût et probabilité de terminer

Question : **combien coûte une meilleure complétion lorsque les volumes sont mal prévus ?** Le protocole est fixé localement avant l'évaluation complète, sans préenregistrement indépendant.

Les tables proviennent de `python -m execution_cost_analytics study`. Ce notebook recalcule les statistiques depuis les observations exportées et lit la confrontation historique. La CLI régénère les simulations complètes ; les sorties de référence permettent de lire ce notebook sans télécharger les données brutes.
"""),
        code("""import json
from pathlib import Path

import numpy as np
import pandas as pd
from IPython.display import Image, display

from execution_cost_analytics.study import grid_invariance_check, load_protocol, summarize_study

ROOT = Path.cwd()
if not (ROOT / 'pyproject.toml').exists():
    ROOT = ROOT.parent
protocol = load_protocol()
metadata = json.loads((ROOT / 'reports/study/experiment.json').read_text(encoding='utf-8'))
summary = pd.read_csv(ROOT / 'reports/study/summary.csv')
assert metadata['analysis_status'] == 'pre_specified_test'
assert set(metadata['executed_seeds']).isdisjoint(protocol['development_seeds'])
assert protocol['training']['seed'] not in metadata['executed_seeds']
print('Chemins indépendants test :', summary['path_id'].nunique())
print('Observations de stratégie :', len(summary))
"""),
        md("""## 1. Contraste principal annoncé

ADAPTIVE contre VWAP, volume à 55 %, ordre de 10 % du volume prévu, urgence finale commune, impact racine. Les autres cellules sont descriptives. Les cinq transformations d'un même chemin et ses barres ne sont pas des observations indépendantes supplémentaires.
"""),
        code("""aggregate, comparisons = summarize_study(summary, protocol, split='test')
primary = comparisons.loc[comparisons['is_primary']]
columns = ['scenario', 'n_pairs', 'saving_bps', 'saving_ci_low', 'saving_ci_high',
           'completion_delta_pp', 'completion_noninferiority_bound_pp', 'evidence']
display(primary[columns].round(4))
reference = pd.read_csv(ROOT / 'reports/study/comparisons.csv')
assert np.allclose(comparisons['saving_bps'], reference['saving_bps'], atol=1e-6)
display(Image(filename=str(ROOT / 'reports/study/figures/paired_savings.png')))
"""),
        md("""## 2. Coût et probabilité de terminer

Le taux moyen de remplissage et la probabilité de terminer un ordre sont distincts. L'IS inclut les mouvements de marché et l'opportunité du reliquat ; le coût explicite additionne spread, impact et frais.

Un bootstrap peut donner `[0 ; 0]` lorsque tous les indicateurs observés coïncident. La borne prudente Wilson évite d'en déduire une non-infériorité établie. Les seuils de 0,5 bp et 1 point de complétion sont des hypothèses pédagogiques, pas des normes de marché.
"""),
        code("""focus = aggregate.loc[
    aggregate['scenario'].eq('low_volume') & aggregate['impact_model'].eq('sqrt')
    & np.isclose(aggregate['quantity_adv_ratio'], 0.10)
]
display(focus[['deadline_mode', 'strategy', 'mean_explicit_cost_bps', 'mean_cost_bps',
               'mean_fill_rate', 'completion_probability', 'completion_probability_ci_low',
               'completion_probability_ci_high']].round(4))
display(Image(filename=str(ROOT / 'reports/study/figures/completion_cost.png')))
display(Image(filename=str(ROOT / 'reports/study/figures/cost_completion_tradeoff.png')))
"""),
        md("""## 3. Contrôle de subdivision

Même horizon, même prix, même ordre, même participation : la quantité et le volume sont subdivisés proportionnellement. Les modèles linéaire et racine sont normalisés au même impact à 10 % de participation, sans calibration empirique.
"""),
        code("""grid = grid_invariance_check(protocol)
display(grid)
assert grid['passed'].all()
print('Erreur maximale de réconciliation :', summary['reconciliation_error'].abs().max())
assert summary['reconciliation_error'].abs().max() < 1e-5
"""),
        md("""## 4. Confrontation aux observations publiques

BTCUSDT et ETHUSDT, janvier 2026, archives Binance Vision vérifiées par SHA-256 et complétude minute par minute. Par actif : 14 jours initiaux et 17 jours évalués chronologiquement. Les marchés ne sont pas regroupés en 34 observations indépendantes.

La référence d'exécution est le VWAP des transactions de la barre, pas un midpoint bid/ask. Décision et arrivée utilisent la première ouverture ; le reliquat la dernière clôture. Spread 2 bp, volatilité 2 % et impact restent hypothétiques. Les intervalles par jour supposent une indépendance temporelle non vérifiée et restent descriptifs.

**Attribution : Binance Vision.** Les résultats historiques de ce notebook sont sous CC BY-NC-SA 4.0 et conditions Binance Vision. Voir `reports/real/LICENSE.md` et `docs/SOURCES.md`.
"""),
        code("""real = pd.read_csv(ROOT / 'reports/real/comparisons.csv')
real_focus = real.loc[
    real['strategy'].eq('ADAPTIVE') & real['baseline'].eq('VWAP')
    & real['impact_model'].eq('sqrt') & real['deadline_mode'].eq('common_deadline')
    & np.isclose(real['quantity_adv_ratio'], 0.10)
]
display(real_focus[['scenario', 'n_pairs', 'saving_bps', 'saving_ci_low', 'saving_ci_high',
                    'completion_delta_pp', 'evidence']].round(4))
assert not real['is_primary'].any()
display(Image(filename=str(ROOT / 'reports/real/figures/completion_cost.png')))
"""),
        md("""## 5. Conclusion à défendre

Lire le contraste principal, puis les sensibilités et contre-exemples. Aucun avantage économique n'est établi par le contraste principal de référence. Une autre cellule favorable ne le remplace pas. Une meilleure complétion contre un coût plus élevé reste un compromis à chiffrer.

Les conclusions détaillées sont dans `reports/study/RESULTATS.md` et `reports/real/RESULTATS.md`. Le guide explique comment reproduire, interpréter et modifier l'étude. Les contrôles logiciels établissent la cohérence des calculs ; l'effet causal d'un ordre réel demanderait d'autres données et validations.
"""),
    ],
    "02_volume_uncertainty.ipynb",
)

print("Sources des deux notebooks V2 préparées.")

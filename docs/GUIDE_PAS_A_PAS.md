# Comprendre et reprendre le projet — guide pas à pas V2

Ce guide est ton parcours pour devenir le développeur du projet : refaire un calcul, retrouver son code, modifier une règle et défendre le résultat devant un reviewer. Tu peux suivre une séance par jour, puis revenir aux exercices.

**La question V2 : combien coûte une meilleure probabilité de terminer un ordre lorsque la prévision de volume est mauvaise ?**

La V1 apprenait à découper des ordres. La V2 ajoute une politique adaptative, des stress de liquidité, des comparaisons appariées et une confrontation à des données publiques. L'impact V1 dépendait artificiellement du nombre de tranches ; il a été corrigé. **Les anciens chiffres V1 ne sont plus les conclusions de référence.**

Les coûts d'impact restent simulés, y compris sur les prix et volumes réels. Le but est de comprendre un compromis et ses limites.

## Ton parcours

| Séance | Objectif |
| --- | --- |
| 1 | Installer, exécuter et retrouver les sorties V2. |
| 2 | Lire une fonction Python et calculer TWAP/VWAP à la main. |
| 3 | Lire les données et protéger la chronologie. |
| 4 | Refaire l'impact local et comprendre la correction V1 → V2. |
| 5 | Suivre ADAPTIVE avec les vrais remplissages passés. |
| 6 | Expliquer l'échéance, le reliquat et le coût complet. |
| 7 | Comprendre les scénarios, l'appariement et les intervalles. |
| 8 | Décider si un résultat est utile. |
| 9 | Reproduire l'étude publique et identifier les hypothèses. |
| 10 | Modifier, vérifier, enregistrer avec Git et présenter le projet. |

Garde [METHODOLOGIE.md](METHODOLOGIE.md) pour les équations, [PROTOCOLE_V2.md](PROTOCOLE_V2.md) pour les critères de décision et [SOURCES.md](SOURCES.md) pour les références et la provenance. Dans un carnet, note « hypothèse → résultat attendu → résultat obtenu → explication ».

## Séance 1 — Installer et reproduire la V2

### 1. Retrouver le dossier

Dans PowerShell :

```powershell
Set-Location -LiteralPath 'C:\Users\mouss\Documents\ChatGPT\git learning projects'
Get-Location
Get-ChildItem
```

`Set-Location` change le dossier courant. Les guillemets conservent les espaces du chemin. Tu dois voir `pyproject.toml`, `src`, `tests` et `docs`. Toutes les commandes du guide partent de cette racine.

Sur un autre ordinateur, récupère le dépôt de référence dans un nouveau dossier :

```powershell
git clone https://github.com/moussoulijane/execution-cost-analytics.git
Set-Location execution-cost-analytics
```

Le [README anglais](../README.md) présente l'étude aux reviewers ; le [README français](../README.fr.md) et ce guide permettent de la reprendre pas à pas.

### 2. Installer dans un environnement isolé

```powershell
python --version
git --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip check
```

Si `python` est absent, examine `py -0p` et utilise `py -3.11 -m venv .venv` si Python 3.11 est installé. L'environnement de référence utilise Python 3.11.9 ; les versions de bibliothèques sont fixées dans `pyproject.toml`.

`.venv` contient le Python et les bibliothèques ; `src` contient notre code. Le mode `-e` permet de modifier le code sans réinstaller à chaque changement. `.[dev]` ajoute les outils de tests et de notebook. L'installation peut nécessiter Internet.

Appeler directement `.\.venv\Scripts\python.exe` évite d'activer l'environnement ou de changer la politique PowerShell. Si `.venv` fonctionne déjà, réutilise-le.

### 3. Vérifier puis lancer l'étude

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m execution_cost_analytics study --output-dir outputs/ma_reproduction_v2
```

`pytest` vérifie les règles du problème. Ruff détecte certains défauts de code. `study` calcule le protocole : 80 chemins de test et 2 000 tirages bootstrap par défaut. Le dossier personnel évite de remplacer les rapports livrés.

Pour une vérification rapide :

```powershell
.\.venv\Scripts\python.exe -m execution_cost_analytics study --split dev --paths 4 --bootstrap-reps 100 --output-dir outputs/essai_rapide
```

**Cet essai est exploratoire.** Quatre chemins ne remplacent pas l'étude de référence, même si le résultat paraît meilleur. Les paramètres utilisés figurent dans `experiment.json`.

### 4. Lire les sorties

Commence par `reports/study/RESULTATS.md` ou ton rapport généré.

| Sortie V2 | Utilité |
| --- | --- |
| `RESULTATS.md` | Question, résultat calculé et limites. |
| `summary.csv` | Détail par chemin, régime, taille, politique et hypothèses. |
| `aggregate.csv` | Coût, risque et complétion par cellule. |
| `comparisons.csv` | Différences appariées et intervalles. |
| `forecast_metrics.csv` | Erreur de volume et de profil. |
| `grid_check.csv` | Vérification 26, 52 et 104 créneaux. |
| `sample_fills.csv` | Une trajectoire pour expliquer le mécanisme. |
| `experiment.json` | Protocole, paramètres et reproduction. |
| `figures/` | Figures tirées des tables. |

`reports/` contient aussi la démonstration historique. Pour la recherche V2, utilise `reports/study/`, puis `reports/real/` pour l'expérience publique.

**Exercice :** peut-on avoir 99 % de remplissage moyen et 0 % d'ordres entièrement terminés ?

**Corrigé :** oui, si chaque ordre reste incomplet à 99 %. « Presque terminé » et « terminé » répondent à des besoins différents.

## Séance 2 — Une fonction, TWAP et VWAP

Un ordre de 100 unités sur quatre créneaux égaux donne `[25, 25, 25, 25]` avec TWAP. Un plan représente des **demandes prévues**, pas des exécutions garanties.

Version minimale pour comprendre Python :

```python
def partage_simple(quantity, n_buckets):
    quantite_par_creneau = quantity / n_buckets
    return [quantite_par_creneau] * n_buckets
```

`def` définit une fonction ; les paramètres sont les entrées. Le corps est indenté ; `return` renvoie la sortie. Cette version ne gère pas les arrondis ni les entrées invalides. La vraie fonction est dans `strategies.py`.

Ouvre Python depuis PowerShell :

```powershell
.\.venv\Scripts\python.exe
```

L'invite `>>>` indique que tu es dans Python ; ne la recopie pas.

```python
from execution_cost_analytics.strategies import twap_schedule, vwap_schedule

plan = twap_schedule(101, 4)
print(plan.tolist())
print(plan.sum())
print(vwap_schedule(100, [1, 2, 1]).tolist())
```

Résultats : `[26, 25, 25, 25]`, `101`, puis `[25, 50, 25]`.

TWAP utilise le quotient et le reste. `divmod(101, 4)` donne `(25, 1)` : quatre groupes de 25 et une unité à distribuer. VWAP attribue plus de quantité aux poids élevés. La méthode des plus grands restes distribue les unités restantes sans changer le total.

```python
import numpy as np

liste = [10, 20, 30]
tableau = np.array(liste)
print(liste * 2)
print((tableau * 2).tolist())
assert int(plan.sum()) == 101
assert len(plan) == 4
assert plan[0] == 26
```

Une liste multipliée se répète ; NumPy multiplie ses valeurs. Les indices commencent à zéro. `assert` déclenche une erreur si la proposition est fausse.

Une annotation comme `quantity: int` documente le type attendu sans remplacer les contrôles. Essaie `twap_schedule(-1, 4)` : le `ValueError` est volontaire.

**Exercice :** calcule `twap_schedule(10, 3)` et `vwap_schedule(8, [1, 2, 1])` avant de les lancer.

**Corrigé :** `[4, 3, 3]` et `[2, 4, 2]`. La somme représente tout l'ordre prévu.

Pour revenir à PowerShell :

```python
exit()
```

## Séance 3 — Données et chronologie

Ouvre Python, puis :

```python
from execution_cost_analytics.data import generate_market_data, forecast_volume_profile

market = generate_market_data(n_days=40, n_buckets=26, seed=42)
print(market.head())
print(market.shape)
print(market.columns.tolist())

target = sorted(market["session"].unique())[30]
forecast = forecast_volume_profile(market, as_of=target, lookback=20)
print(forecast.training_sessions)
print(forecast.expected_daily_volume)
print(forecast.weights.sum())
assert all(day < target for day in forecast.training_sessions)
```

Un `DataFrame` pandas est une table à colonnes nommées. `head()` affiche les premières lignes ; `shape` indique les dimensions. Ici, 40 × 26 donne 1 040 lignes. `market["market_volume"]` sélectionne une colonne.

`forecast` est une structure nommée : le point lit un attribut. Les poids donnent le profil relatif et le volume prévu donne l'échelle journalière.

La fonction filtre les dates **avant** d'estimer le profil. Une séance terminée peut entrer dans l'historique de la suivante. Une séance future ne peut pas aider à prévoir le passé.

L'étude synthétique estime une seule prévision sur les 30 séances initiales, puis la garde fixe pour les chemins indépendants. L'étude publique réestime chaque journée avec une fenêtre glissante. Ne confonds pas ces deux plans d'expérience.

```python
import numpy as np

changed = market.copy()
changed.loc[changed["session"] >= target, "market_volume"] *= 10
other = forecast_volume_profile(changed, as_of=target, lookback=20)
assert np.allclose(forecast.weights, other.weights)
assert forecast.expected_daily_volume == other.expected_daily_volume
```

`copy()` crée une table de travail. `.loc[condition, colonne]` sélectionne des cellules. `np.allclose` compare les nombres flottants avec tolérance.

**Exercice :** pourquoi ne pas prévoir VWAP avec les volumes réalisés de la séance ?

**Corrigé :** ils sont inconnus à la planification. Ils servent après coup au benchmark et à l'évaluation. Les utiliser avant serait une fuite temporelle.

La V2 sépare aussi la prévision et la facture : le plan dépend de la prévision, mais la capacité et l'impact utilisent le volume **réalisé**. Quitte Python avant la suite.

## Séance 4 — Recalculer l'impact local

### 1. Comprendre la correction

L'ancienne formule dépendait de `sqrt(q / volume_journalier_prévu)`. Diviser chaque tranche en quatre réduisait artificiellement son impact par unité par deux.

La V2 utilise `(q / V_local_réalisé)^alpha`. Si tu divises quantité et volume dans la même proportion, la participation reste la même.

`100 / 1 000 = 25 / 250 = 10 %`. À prix constant, quatre sous-tranches de 25 coûtent ensemble autant que la tranche de 100. Le test 26/52/104 vérifie ce cas contrôlé. Des arrondis ou une liquidité réellement différente peuvent modifier d'autres cas.

### 2. Un coût à la main

Achat de 10 unités ; prix 100 ; volume local 100 ; spread complet 2 bp ; `eta = 0,05` ; volatilité 2 % ; exposant 0,5 ; frais 0,5 bp.

```text
Participation = 10 / 100 = 10 %
Demi-spread par unité = 100 × 2 / 20 000 = 0,01
Impact par unité = 100 × 0,05 × 0,02 × sqrt(0,10) ≈ 0,03162278
Prix exécuté ≈ 100,04162278
Coût spread + impact sur 10 unités ≈ 0,41622777
Frais ≈ 10 × 100,04162278 × 0,5 / 10 000 ≈ 0,05002081
Coût total ≈ 0,46624858, soit 4,66249 bp du notionnel 1 000
```

### 3. Le même calcul dans le code

Dans Python :

```python
import pandas as pd
from execution_cost_analytics.simulation import SimulationConfig, simulate_execution
from execution_cost_analytics.analytics import summarize_execution

one_bar = pd.DataFrame({
    "timestamp": pd.to_datetime(["2026-01-05 09:30"]),
    "session": ["2026-01-05"],
    "bucket": [0],
    "mid_price": [100.0],
    "market_volume": [100],
    "spread_bps": [2.0],
})
config = SimulationConfig(
    side="buy",
    daily_volatility=0.02,
    impact_coefficient=0.05,
    impact_exponent=0.5,
    fee_bps=0.5,
    max_participation=0.15,
)
fills = simulate_execution(one_bar, [10], total_quantity=10, config=config)
metrics = summarize_execution(
    fills, total_quantity=10,
    decision_price=100.0, arrival_price=100.0, side="buy",
)
print(fills[["executed_quantity", "execution_price", "fee"]])
print(metrics["total_cost"], metrics["total_cost_bps"])
print(metrics["reconciliation_error"])
```

Le coût doit retrouver le calcul manuel à l'erreur numérique près. Les quantités entières sont exactes ; les prix flottants demandent une tolérance.

Le spread, l'impact et les frais sont des pénalités. Timing et reliquat peuvent contribuer avec l'un ou l'autre signe. Une baisse favorable du marché peut rendre le coût négatif sans avantage prédictif de l'algorithme.

**Exercice :** que fait le coût si tu changes seulement `expected_daily_volume`, à remplissages et marché identiques ?

**Corrigé :** rien. Le champ est conservé pour compatibilité mais ne détermine plus l'impact. Une prévision différente peut toutefois modifier la décision en amont.

## Séance 5 — Suivre ADAPTIVE

TWAP et VWAP suivent leur calendrier. ADAPTIVE ajoute à sa demande le retard déjà observé. POV demande une fraction du flux contemporain ; sa représentation par barres suppose une participation pendant le créneau.

Dans la session Python de la séance 4 :

```python
from execution_cost_analytics.policies import ExecutionPolicy
from execution_cost_analytics.simulation import SimulationConfig, simulate_policy

day = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-05 09:00", periods=4, freq="30min"),
    "session": ["2026-01-05"] * 4,
    "bucket": [0, 1, 2, 3],
    "mid_price": [100.0] * 4,
    "market_volume": [100, 1000, 1000, 1000],
    "spread_bps": [2.0] * 4,
})
config = SimulationConfig(deadline_mode="soft")
fixed = simulate_policy(day, 100, ExecutionPolicy("VWAP"), config)
adaptive = simulate_policy(day, 100, ExecutionPolicy("ADAPTIVE"), config)
print(fixed[["requested_quantity", "executed_quantity"]])
print(adaptive[["requested_quantity", "executed_quantity"]])
```

Sans poids fournis, la base est uniforme. Dans l'étude, les deux politiques reçoivent les mêmes poids prévus.

| Créneau | Demande VWAP | Exécuté VWAP | Demande ADAPTIVE | Exécuté ADAPTIVE |
| --- | ---: | ---: | ---: | ---: |
| 1 | 25 | 15 | 25 | 15 |
| 2 | 25 | 25 | 35 | 35 |
| 3 | 25 | 25 | 25 | 25 |
| 4 | 25 | 25 | 25 | 25 |
| Total | 100 | 90 | 110 | 100 |

Au premier créneau, 15 % du volume autorisent 15 unités. Au second, ADAPTIVE observe un retard de 10 et demande `25 + 10 = 35`.

La somme des **demandes** peut dépasser l'ordre, car des unités non remplies sont redemandées. La somme des **exécutions** ne dépasse jamais l'ordre.

Dans `policies.py`, `request_quantity` reçoit le calendrier et les remplissages passés ; il ne reçoit pas une table de marché future. ADAPTIVE reste une heuristique, sans preuve d'optimalité.

**Exercices :** mets `catchup_gain=0` ; modifie seulement les deux dernières barres ; demande-toi si cet exemple prouve une supériorité économique.

**Corrigés :** gain nul reproduit VWAP ; les deux premières lignes restent identiques ; l'exemple prouve le mécanisme dans ce cas, pas son intérêt économique général.

## Séance 6 — Échéance et reliquat

### 1. Même règle terminale

En mode `common_deadline`, toutes les politiques demandent le reste dans les derniers 20 % de la grille et partagent un plafond terminal de 40 %, contre 15 % avant. La fenêtre est arrondie au nombre de créneaux supérieur.

```python
deadline = SimulationConfig(deadline_mode="common_deadline")
for kind in ("TWAP", "VWAP", "POV", "ADAPTIVE"):
    result = simulate_policy(day, 100, ExecutionPolicy(kind), deadline)
    print(kind, int(result["executed_quantity"].sum()))
    print(result[["bucket", "is_terminal", "requested_quantity",
                  "executed_quantity", "terminal_quantity"]])
```

Les transactions terminales paient spread, impact et frais. L'échéance ne crée pas une capacité infinie.

**Exercice :** quatre créneaux de volume 100 et un ordre de 200 peuvent-ils être entièrement exécutés ?

**Corrigé :** la fenêtre terminale comporte un créneau ; la capacité totale est `15 + 15 + 15 + 40 = 85`. Aucune politique ne peut en exécuter 200. Déclarer l'échec est correct.

### 2. Le coût complet

Le shortfall compare l'ordre au prix de décision et décompose :

| Composante | Question |
| --- | --- |
| Délai | Mouvement entre décision et arrivée ? |
| Timing | Mouvement pendant l'exécution ? |
| Spread | Coût de la fourchette traversée ? |
| Impact | Pénalité ajoutée par le modèle ? |
| Frais | Commission appliquée ? |
| Opportunité | Valorisation terminale du reliquat ? |

Dans l'étude synthétique V2, décision et arrivée sont le premier mid de la séance. La commande historique `demo` conserve sa décision à la veille. L'étude publique utilise le prix d'ouverture initial pour décision/arrivée et le prix de clôture final pour le reliquat. Cette valorisation ne crée aucune transaction.

**Exercice :** achat de 100 unités décidé à 100 ; 60 exécutées à 101 ; terminal 102 ; ignore les frais.

**Corrigé :** coût exécuté `60 × (101 − 100) = 60` ; reliquat `40 × (102 − 100) = 80` ; total 140, soit 140 bp du notionnel 10 000.

La somme des composantes retrouve la formule directe. Cette identité est nécessaire ; elle ne démontre pas le réalisme de l'impact. Quitte Python avec `exit()`.

## Séance 7 — Expérience et incertitude

### 1. Ce qui varie

Cinq régimes : normal, volume à 55 %, interruption du tiers central, volume déplacé vers la fin, stress volume/volatilité. Deux tailles d'ordre, deux formes d'impact, deux échéances et quatre politiques sont comparées.

La quantité vaut 5 % ou 10 % du volume **prévu**. Utiliser le total réalisé pour choisir l'ordre donnerait artificiellement la bonne taille après avoir vu le futur.

Les 12 graines de développement sont distinctes des 80 graines de test. Le volume à 55 % est un stress du protocole, pas une fréquence d'événement estimée sur le marché.

Dans les études V2, le taux POV est `quantité / volume prévu` : environ 5 % ou 10 % selon l'ordre. La commande historique `demo` conserve 3 % à titre pédagogique. Cela évite d'expliquer une mauvaise complétion V2 par un taux POV arbitrairement trop faible dès le départ.

### 2. Pourquoi les mêmes chemins ?

Une trajectoire favorable peut rendre deux politiques bon marché. Pour isoler leur différence, compare les deux sur le **même marché**, avec même ordre et mêmes contraintes.

Dans Python, exercice fictif :

```python
import numpy as np

cout_vwap = np.array([3.0, 8.0, -2.0, 6.0])
cout_adaptive = np.array([3.4, 8.2, -1.1, 6.3])
delta = cout_adaptive - cout_vwap
print(delta)
print(delta.mean())
```

Le surcoût moyen vaut 0,45 bp. Ces nombres servent à apprendre, pas à citer un résultat du projet.

### 3. Comprendre le bootstrap

Le bootstrap tire avec remise des unités observées et recalcule la statistique. Une unité peut apparaître plusieurs fois. Pour conserver l'appariement, le même tirage s'applique aux deux politiques.

Dans le synthétique, on rééchantillonne des **chemins**. Les 26 barres d'un jour ne sont pas 26 expériences indépendantes ; les régimes dérivés d'un même chemin ne sont pas non plus de nouvelles observations indépendantes.

Un intervalle à 95 % décrit la variabilité de l'estimation selon la procédure et ses hypothèses. Il ne signifie pas que la politique gagne 95 % des jours. Il ne corrige pas un modèle d'impact faux.

**Exercice :** écart moyen ADAPTIVE − VWAP de −1 bp, intervalle [−2,8 ; +0,8]. Économie fiable ?

**Corrigé :** la direction reste incertaine : l'intervalle contient zéro et permet aussi un surcoût.

### 4. Retrouver les responsabilités du code

```text
Historique → prévision → ordre et calendrier
                           ↓
Politique + remplissages passés → demande
                           ↓
Volume local → capacité → quantité exécutée → coût
                           ↓
Comparaisons appariées → coût / risque / complétion
```

| Module | Responsabilité |
| --- | --- |
| `strategies.py` | Calendriers et conservation des entiers. |
| `data.py` | Synthétique et prévision historique. |
| `policies.py` | Décisions autorisées des politiques. |
| `simulation.py` | Capacité, échéance et prix d'exécution. |
| `analytics.py` | Coût et réconciliation. |
| `study.py` | Protocole, stress et statistiques V2. |
| `public_data.py` | Données publiques et transformation. |
| `cli.py` | Paramètres reçus de PowerShell. |
| `tests/` | Protection des règles. |

Les rapports et le notebook présentent les calculs ; ils ne doivent pas inventer une seconde version des formules.

## Séance 8 — Décider si les résultats sont bons

Lis `docs/PROTOCOLE_V2.md` avant les gains. La comparaison principale choisie avant le calcul final est ADAPTIVE contre VWAP, faible volume, ordre de 10 % prévu, échéance commune, impact racine carrée.

Les seuils sont propres au projet : gain utile de 0,5 bp, tolérance de 1 point de probabilité de complétion, objectif illustratif de 95 % et garde-fou descriptif de +2 bp sur le quantile 95 %. Ce ne sont pas des normes universelles.

Dans `comparisons.csv`, `saving_bps` vaut coût VWAP moins coût ADAPTIVE : positif signifie économie du candidat. Le delta de complétion garde le sens candidat moins référence : positif signifie davantage d'ordres terminés.

Attention au cas « 80 succès sur 80 ». Le bootstrap des différences peut afficher [0 ; 0] si les deux politiques ont toujours terminé. Cela ne prouve pas une égalité parfaite des probabilités. Le rapport utilise aussi des bornes Wilson, calculées à partir des succès et de l'échantillon. La borne prudente de non-infériorité reste alors proche de −4,58 points, insuffisante pour une marge de 1 point. Le bon verdict peut donc être **échantillon insuffisant**, même avec une économie moyenne et tous les ordres terminés.

| Filtre | Questions |
| --- | --- |
| Exactitude | Quantités, plafonds, chronologie, coûts et subdivision corrects ? |
| Comparabilité | Même marché et ordre ? Même droit terminal ? Reliquat visible ? |
| Utilité | Effet assez grand, incertitude publiée, risque acceptable ? |
| Robustesse | Conclusion stable selon la forme d'impact, le régime et la taille ? |

Un intervalle étroit n'élimine pas l'incertitude du modèle.

Cas fictifs pour apprendre :

| Observation | Conclusion |
| --- | --- |
| Gain dont tout l'intervalle dépasse 0,5 bp, complétion acceptable | Argument favorable dans le périmètre testé. |
| Petit gain moyen, intervalle traversant zéro | Direction incertaine. |
| Surcoût et meilleure complétion | Compromis à comparer au prix de l'urgence. |
| Aucun gain utile, davantage de complexité | La référence simple reste intéressante. |
| Gain uniquement sous une forme d'impact | Résultat dépendant du modèle. |

Évite de sélectionner la plus belle cellule comme découverte principale. Les résultats secondaires expliquent le mécanisme ; leurs intervalles ne corrigent pas les essais multiples.

**Exercice :** écris une observation du rapport, son explication possible et sa limite. Chaque chiffre doit être retrouvé dans un CSV et associé à une configuration.

## Séance 9 — Confrontation aux données publiques

Dans PowerShell :

```powershell
.\.venv\Scripts\python.exe -m execution_cost_analytics fetch-public-data --symbols BTCUSDT ETHUSDT --month 2026-01 --output-dir data/public
.\.venv\Scripts\python.exe -m execution_cost_analytics real-study --input-dir data/public --output-dir outputs/ma_reproduction_reelle
```

Le téléchargement nécessite Internet, sans clé privée. SHA-256 contrôle l'intégrité de l'archive, pas la justesse économique de chaque observation.

Les minutes sont agrégées en 48 créneaux de 30 minutes par journée UTC. Les 14 premières journées initialisent la prévision ; 17 sont évaluées avec une fenêtre glissante de 14 jours. Les quantités sont exprimées en millionièmes d'actif.

| Élément | Statut |
| --- | --- |
| Volumes et valeur des transactions | Observations des archives. |
| Valeur échangée / quantité échangée | Proxy VWAP de transactions, stocké dans `mid_price`. |
| Prix d'ouverture initial / clôture finale | Références de décision/arrivée et de reliquat. |
| Spread complet de 2 bp | Hypothèse. |
| Forme et coefficient d'impact | Hypothèses. |
| Exécution à la participation imposée | Hypothèse du moteur agrégé. |
| Unité d'un millionième d'actif | Unité comptable ; pas le lot réel de la plateforme. |

Un VWAP de barre n'est pas un vrai mid bid–ask. Les barres ne donnent pas l'ordre causal exact des transactions à l'intérieur. Les 17 dates sont peu nombreuses ; les journées peuvent être liées et les actifs corrélés.

Les fichiers de provenance identifient les sources, unités et contrôles. [SOURCES.md](SOURCES.md) explique les conditions Binance Vision : les données et leurs dérivés ont des droits distincts du code MIT.

**Exercice :** que faudrait-il pour valider l'impact causal ?

**Corrigé :** des données d'exécutions indépendantes et adaptées, des informations de liquidité/carnet et une chronologie plus fine. Des bougies seules ne suffisent pas.

Le notebook V2 est `notebooks/02_volume_uncertainty.ipynb`. Lis ses sorties, puis réexécute-le depuis un noyau neuf en sélectionnant `.venv\Scripts\python.exe`. Un noyau garde les variables entre cellules ; redémarrer évite qu'une variable oubliée fasse croire que le notebook se suffit à lui-même.

Pour exécuter les deux notebooks livrés depuis PowerShell, sans installer d'interface Jupyter supplémentaire :

```powershell
.\.venv\Scripts\python.exe scripts/execute_notebook.py
```

Pour sélectionner uniquement le parcours V2 :

```powershell
.\.venv\Scripts\python.exe scripts/execute_notebook.py --notebook notebooks/02_volume_uncertainty.ipynb
```

Le notebook V2 lit les CSV de référence versionnés et recalcule les comparaisons ; il ne télécharge pas les données ni ne remplace une nouvelle exécution complète de `study`. Il reprend les observations publiques dérivées avec leur attribution CC BY-NC-SA 4.0.

## Séance 10 — Modifier, vérifier, enregistrer et présenter

### 1. Une modification personnelle limitée

Exemple : « un gain de rattrapage de 0,5 réduit-il le coût contre un gain de 1 ? »

1. Écris le mécanisme attendu et un exemple manuel.
2. Repère le paramètre dans `ExecutionPolicy`.
3. Conserve le protocole de référence ; range l'essai dans `outputs/`.
4. Compare coût, risque et complétion dans toutes les cellules annoncées.
5. Explique le résultat, même s'il contredit ton hypothèse.

Dans la séance 5, `catchup_gain=0.5` demande 30 unités au deuxième créneau : la moitié du retard de 10 est rattrapée. Le reste se propage ensuite.

Si tu changes une règle, ajoute un test de propriété utile, puis vérifie :

```powershell
.\.venv\Scripts\python.exe -m pytest -k adaptive
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Un test protège une règle ; il ne doit pas simplement recopier l'implémentation. Les tests techniques ne prouvent pas la validité empirique.

### 2. Les trois états de Git

| État | Sens | Inspection |
| --- | --- | --- |
| Travail | Fichiers en cours de modification. | `git diff` |
| Index | Version préparée pour le prochain commit. | `git diff --staged` |
| Historique | Versions enregistrées. | `git log --oneline` |

Le dépôt de référence possède déjà son historique. Les étapes de premier commit ci-dessous expliquent sa construction ; dans ton clone, elles servent à enregistrer tes prochaines modifications. Examine son état :

```powershell
git status
git branch --show-current
git log --oneline -5
git diff
git ls-files --others --exclude-standard
```

Avant le premier commit, `git log` indique qu'il n'y a pas encore d'historique. Les nouveaux fichiers se repèrent avec `status` ; ils n'apparaissent pas dans `diff`.

Vérifie ton identité :

```powershell
git config user.name
git config user.email
```

Si nécessaire, remplace ces exemples :

```powershell
git config --local user.name "Ton nom"
git config --local user.email "ton-adresse@example.com"
```

Après les vérifications, sélectionne et relis les fichiers voulus :

```powershell
git add README.md docs src tests notebooks pyproject.toml
git diff --staged --stat
git diff --staged
git status
```

Ajoute séparément les autres fichiers voulus, notamment les rapports avec leurs conditions de provenance. `data/`, `outputs/` et `.venv/` sont ignorés. `git add .` sélectionnerait tous les fichiers non ignorés ; une sélection explicite aide à relire le commit.

Pour retirer de l'index après le premier commit : `git restore --staged chemin/du/fichier`. Avant le premier commit, pour un nouveau fichier : `git rm --cached -- chemin/du/fichier`. Ces commandes conservent le fichier de travail.

Quand la sélection est correcte :

```powershell
git commit -m "Study execution cost and completion under volume uncertainty"
git status
git log --oneline -5
```

Un commit est local et ne publie rien sur GitHub. Après un premier commit, crée une branche d'exercice avec `git switch -c codex/catchup-experiment`.

**Exercice :** après `git add`, tu modifies encore le fichier. Quelle version sera enregistrée ?

**Corrigé :** celle du dernier `git add`. `git diff --staged` montre la sélection ; `git diff` montre la modification suivante.

### 3. Présenter honnêtement le projet

Trame à reformuler avec tes mots :

> « J'étudie le coût d'une meilleure complétion quand les volumes sont mal prévus. Le projet sépare prévision, politique et moteur. J'ai corrigé un impact qui diminuait artificiellement avec le nombre de tranches. Je compare VWAP à une règle de rattrapage du retard observé avec capacité et échéance communes. Les résultats sont appariés et évalués selon un protocole écrit avant le calcul final. Une confrontation publique apporte des prix et volumes historiques ; l'impact reste supposé. »

Ajoute une observation calculée, ses conditions et sa limite. Tu dois savoir remonter du rapport au CSV puis au remplissage.

| Question | Élément à expliquer |
| --- | --- |
| Pourquoi ADAPTIVE peut-il coûter plus ? | Il peut exécuter davantage et à une participation plus élevée. |
| Pourquoi corriger l'ancienne formule ? | Sa référence de liquidité ne suivait pas la subdivision de la tranche. |
| A-t-on supprimé toute fuite ? | Prévision et politique n'utilisent pas le futur ; l'agrégation intrabarre reste une approximation. |
| Pourquoi l'échéance commune ? | Même droit terminal, coût payé, capacité finie. |
| Un résultat nul est-il un échec ? | Non, s'il précise quand la complexité n'apporte rien d'utile. |
| Le réel valide-t-il l'impact ? | Les trajectoires sont réelles ; notre impact contrefactuel est supposé. |
| Que mesure l'intervalle ? | L'incertitude d'échantillonnage, distincte de l'erreur du modèle. |

La publication GitHub est distincte du commit local. Le dépôt de référence est [moussoulijane/execution-cost-analytics](https://github.com/moussoulijane/execution-cost-analytics). Pour comprendre la première mise en ligne, consulte la [documentation officielle d'ajout d'un dépôt local](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

Dans un clone, `origin` désigne déjà GitHub. Après avoir créé une branche d'exercice, modifié le code, vérifié les résultats et enregistré un commit, publie cette branche :

```powershell
git remote -v
git status
git push -u origin codex/catchup-experiment
```

Cette commande suppose que ta branche s'appelle `codex/catchup-experiment` et que tu as accès en écriture au dépôt. Sur GitHub, ouvre ensuite une pull request pour relire la modification. L'onglet **Actions** montre les vérifications sous Python 3.11 et 3.12 : installation, style, tests et exécution des notebooks. Un push réussi et une CI réussie sont deux vérifications différentes.

## Petit lexique Python

| Construction | Sens |
| --- | --- |
| `from ... import ...` | Rendre un nom utilisable. |
| `if condition:` | Exécuter le bloc si la condition est vraie. |
| `for element in collection:` | Parcourir une collection. |
| `enumerate(...)` | Parcourir position et valeur. |
| `zip(a, b)` | Parcourir des paires correspondantes. |
| `dict["cle"]` | Lire une valeur par sa clé. |
| `None` | Absence de valeur. |
| `np.nan` | Nombre manquant ; le prix d'une non-exécution n'est pas zéro. |
| `dataclass` | Regrouper des attributs nommés. |
| `replace(config, ...)` | Créer une configuration modifiée. |
| `raise ValueError(...)` | Refuser une entrée invalide. |
| `groupby(...)` / `pivot(...)` | Regrouper ou réorganiser une table. |
| `Path` | Représenter un chemin. |
| `main` / `__main__.py` | Relier le terminal aux fonctions. |

Après chaque séance, note le problème, l'hypothèse, le fichier étudié, la vérification et la conclusion. Tu maîtrises la V2 lorsque tu sais recalculer un coût, suivre le retard, expliquer un échec de complétion, lire un intervalle et modifier une règle de façon vérifiable avec Git.

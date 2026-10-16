# Méthodologie V2 — coût, risque et complétion sous erreur de volume

Ce document décrit les règles effectivement étudiées. [Le guide pas à pas](GUIDE_PAS_A_PAS.md) explique comment refaire les calculs. Le protocole de référence est conservé dans [PROTOCOLE_V2.md](PROTOCOLE_V2.md) et sa version exploitable dans [PROTOCOLE_V2.json](PROTOCOLE_V2.json).

**La V2 remplace les conclusions numériques de la V1.** La V1 facturait l'impact de chaque tranche avec le volume journalier prévu au dénominateur : multiplier artificiellement les tranches réduisait son coût. Ses 10 séances synthétiques, son avantage moyen VWAP de 0,21 bp et sa bonne erreur de prévision ne constituent plus les résultats de référence. Les commandes historiques restent utiles pour apprendre ; l'étude V2 répond à une question différente avec un modèle corrigé.

## 1. Question et niveau de preuve

> Quel surcoût et quel risque faut-il accepter pour améliorer la probabilité de terminer un ordre lorsque les volumes sont mal prévus ?

La comparaison principale oppose **ADAPTIVE à VWAP**, pour un ordre de **10 % du volume journalier prévu**, en régime de faible volume, avec échéance commune et impact en racine carrée. Les autres tailles, régimes, formes d'impact et échéances servent à discuter la robustesse et le mécanisme.

Le code ne cherche pas un rendement d'investissement. Il mesure un coût d'exécution simulé. Les stress synthétiques permettent une expérience contrôlée ; les données publiques permettent une confrontation à des trajectoires historiques. Le modèle d'impact reste supposé dans les deux cas.

Le protocole est écrit avant le calcul final V2 et conservé avec les résultats. Il s'agit d'une spécification interne reproductible, pas d'un préenregistrement certifié par un tiers. Les périodes historiques publiques ne sont pas inconnues des auteurs ; la séparation chronologique ne supprime pas tous les biais de conception.

## 2. Données, unités et horodatages

Une ligne du schéma commun représente un créneau.

| Colonne | Convention |
| --- | --- |
| `timestamp` | Horodatage naïf ; le fuseau ou l'horloge d'origine est décrit dans la provenance. |
| `session` | Date `YYYY-MM-DD` correspondant à cet horodatage. |
| `bucket` | Position entière, commençant à zéro, dans une grille régulière. |
| `mid_price` | Mid fictif pour le synthétique ; **proxy de prix de transactions** pour le réel. |
| `market_volume` | Volume externe au modèle, en unités entières ; notre ordre n'est pas ajouté à ce volume. |
| `spread_bps` | Spread complet en bp : généré pour le synthétique, supposé pour l'étude publique. |

Un point de base vaut `0,0001` en proportion. À un prix de 100, un coût de 3 bp vaut 0,03 par unité.

La participation utilise `q / V`, et non `q / (V + q)`. Le modèle interprète les volumes observés comme un flux externe à l'ordre simulé. Les archives réelles contiennent déjà toutes les transactions historiques : le scénario contrefactuel suppose que notre ordre n'aurait pas modifié ce flux.

Les créneaux représentent une approximation agrégée. Ils ne décrivent ni le carnet, ni la priorité en file, ni la latence, ni l'ordre chronologique des transactions au sein d'une barre.

## 3. Information disponible et séparation des responsabilités

Pour une séance cible `d`, `forecast_volume_profile(history, as_of=d, lookback=...)` utilise uniquement les séances dont la date est strictement antérieure à `d`. Il produit :

- un profil `weights`, moyenne des profils quotidiens normalisés ;
- `expected_daily_volume`, moyenne des volumes journaliers historiques ;
- `training_sessions`, les dates réellement utilisées.

Chaque journée contribue avec le même poids au profil. Moyenne de profils et mise en commun de tous les volumes ne sont pas la même opération.

La prévision fixe la quantité relative de l'ordre et le calendrier VWAP. Elle **ne sert plus de liquidité réalisée dans la facture d'impact**. Le moteur prend les décisions de politique, observe les volumes réalisés pour limiter les remplissages et calcule leurs coûts. Les quantités exécutées précédemment peuvent alimenter la décision adaptative suivante.

Le benchmark VWAP de marché utilise les volumes réalisés après la séance. C'est une référence d'analyse, jamais un profil futur communiqué au calendrier VWAP.

POV participe idéalement au flux du créneau contemporain. Le moteur agrège cette participation en utilisant le volume de la barre ; ce total n'est effectivement connu qu'à sa clôture. Ce choix est une approximation de participation intrabarre, pas la preuve d'une exécution causale au niveau transaction. Les politiques ne reçoivent pas les barres futures.

## 4. Les quatre politiques

L'interface `ExecutionPolicy` sépare la politique et le moteur d'exécution. `simulate_policy` combine une politique, un ordre, un marché et `SimulationConfig`.

| Politique | Quantité demandée avant limitation |
| --- | --- |
| TWAP | Calendrier uniforme sur des créneaux de même durée. |
| VWAP | Calendrier proportionnel au profil prévu avant la séance. |
| POV | Fraction configurée du flux contemporain, bornée par le reste de l'ordre. |
| ADAPTIVE | Calendrier VWAP de base augmenté d'une fraction du retard cumulé avant le créneau. |

TWAP et VWAP répartissent exactement l'ordre entre les créneaux prévus. Le traitement des entiers conserve les quantités. Cela n'oblige pas le marché à les remplir.

Pour ADAPTIVE, le retard avant le créneau `t` est la différence positive entre la quantité de base qui aurait dû être exécutée avant `t` et la quantité réellement exécutée. Avec un gain `g = 1`, toute cette différence est ajoutée à la demande de base courante. Avec `g = 0`, on retrouve la demande VWAP sans rattrapage. La demande est bornée par le reste de l'ordre, puis par la capacité réalisée. Le rattrapage utilise les remplissages effectifs, pas seulement les demandes passées.

Cette règle est une **heuristique**. Elle n'optimise pas une fonction d'utilité et ne sait pas qu'un futur choc va arriver. Si la liquidité devient insuffisante, elle peut rester en retard.

## 5. Capacité et échéance communes

La capacité d'un créneau de volume `V_t` au taux maximal `c_t` est :

```text
cap_t = floor(c_t × V_t)
q_t = min(demande_t, reste_de_l_ordre, cap_t)
```

`floor` signifie arrondi à l'entier inférieur. Si `V_t = 0`, la quantité exécutée vaut zéro. L'ordre ne peut être exécuté au-delà de sa quantité totale.

Deux modes répondent à des besoins différents :

| Mode | Règle |
| --- | --- |
| `soft` | Chaque politique suit sa règle avec un plafond ordinaire de 15 %. Le reliquat est mesuré et valorisé. |
| `common_deadline` | Durant les derniers 20 % de la séance, toutes les politiques demandent le reste de l'ordre et partagent le même plafond terminal de 40 %. |

Les plafonds, la fenêtre et les autres hypothèses sont fixés dans le protocole. La transition concerne la fin de séance ; elle ne dépend pas de la connaissance du volume futur.

Dans les études synthétique et publique V2, le taux POV vaut `quantité / volume journalier prévu` : environ 5 % ou 10 % selon la taille d'ordre. Le rythme vise donc la taille demandée si le volume prévu se réalise. La démonstration historique `demo` conserve un taux fixe illustratif de 3 % ; ses résultats POV ne doivent pas être confondus avec ce protocole.

Dans le mode à échéance, les quantités exécutées en rattrapage terminal paient spread, impact et frais. Ce n'est ni une transaction gratuite ni un achat illimité au dernier prix. Si la capacité restante est insuffisante, l'ordre peut échouer à terminer.

L'échéance commune ne rend pas les taux de remplissage identiques. Elle rend la règle terminale identique, de sorte que l'avantage apparent d'une politique ne vient pas d'un droit exclusif à la liquidité terminale. Les complétions restent publiées.

## 6. Impact local corrigé

Pour un achat `s = +1` et pour une vente `s = −1` :

```text
rho_t = q_t / V_t                         si q_t > 0
demi_spread_t = mid_t × spread_bps_t / 20 000
impact_t = mid_t × eta × sigma × rho_t^alpha
prix_execution_t = mid_t + s × (demi_spread_t + impact_t)
frais_t = q_t × prix_execution_t × fee_bps / 10 000
```

Les créneaux sans remplissage n'ont ni prix d'exécution effectif ni pénalité monétaire. `sigma` est une hypothèse de volatilité journalière en proportion, `eta` un coefficient et `alpha` la forme de participation. Les prix futurs de marché ne sont pas modifiés : l'impact est temporaire dans cette expérience, sans rétroaction sur le marché.

Le volume `V_t` est **réalisé et local**. Le champ historique `expected_daily_volume` reste accepté pour compatibilité de l'API, mais ne facture plus l'impact. Modifier une prévision peut modifier une décision et donc un remplissage ; à remplissages et marché identiques, cela ne modifie plus l'impact.

La configuration simple de référence utilise `eta = 0,05` et `sigma = 0,02` pour la forme racine carrée (`alpha = 0,5`). À 10 % de participation :

```text
10 000 × 0,05 × 0,02 × sqrt(0,10) ≈ 3,1623 bp d'impact par unité
```

L'étude compare aussi la forme linéaire (`alpha = 1`), en ajustant le coefficient pour qu'elle ait le même coût au point de participation de 10 %. Sinon une comparaison des formes mélangerait courbure et simple échelle. Ce point d'ancrage est un choix expérimental, pas une estimation de marché.

### Test de subdivision

Considérons un prix constant et un créneau de `q = 100` unités exécutées dans un volume `V = 1 000`. Divisons les deux par quatre : chaque sous-créneau a `q = 25` et `V = 250`. Dans les deux cas, `rho = 10 %`. L'impact par unité est inchangé ; la somme des coûts des quatre sous-créneaux retrouve le coût initial.

L'étude vérifie ce comportement sur 26, 52 et 104 créneaux pour une trajectoire homogène et divisible. Des arrondis entiers, une variation réelle de liquidité ou des décisions différentes peuvent créer des différences dans des cas généraux. L'invariance du cas contrôlé corrige l'artefact V1 ; elle ne valide pas le modèle empiriquement.

## 7. Mesure de coût et reliquat

Les références sont :

- `P_D` : prix de décision ;
- `P_A` : prix d'arrivée ;
- `P_T` : prix terminal ;
- `Q_E = somme(q_t)` : quantité exécutée ;
- `Q_R = Q − Q_E` : reliquat.

L'étude synthétique V2 fixe la décision et l'arrivée au premier mid de la séance ; elle isole ainsi l'exécution pendant la séance. La commande historique `demo` conserve sa décision au dernier mid de la veille. Dans l'étude publique, décision et arrivée sont le prix d'ouverture de la première barre, disponible au début ; le terminal est le prix de clôture de la dernière barre. Le proxy VWAP de barre sert au prix de remplissage simulé. Ces références sont des prix de transactions, pas des cotations bid–ask.

Le shortfall direct est :

```text
IS = s × [somme(q_t × prix_execution_t) + Q_R × P_T − Q × P_D] + somme(frais_t)
IS_bps = 10 000 × IS / (Q × P_D)
```

Le dénominateur est le notionnel demandé à la décision, commun aux politiques, même si l'ordre reste partiel. Le reliquat est valorisé au terminal : cette valorisation **ne crée pas une exécution**.

La décomposition doit retrouver le même coût :

| Composante | Formule |
| --- | --- |
| Délai | `s × Q_E × (P_A − P_D)` |
| Timing | `s × somme(q_t × (mid_t − P_A))` |
| Spread | `somme(q_t × demi_spread_t)` |
| Impact | `somme(q_t × impact_t)` |
| Frais | `somme(frais_t)` |
| Opportunité | `s × Q_R × (P_T − P_D)` |

Le code vérifie l'identité pour les achats et les ventes. Un coût positif est défavorable ; un coût négatif peut provenir d'un mouvement favorable du marché. Une réconciliation correcte valide la comptabilité, pas les hypothèses d'impact.

Le coût du reliquat dépend du prix terminal et peut être positif ou négatif. Une faible complétion peut donc sembler bon marché dans certaines trajectoires. La quantité restante et la probabilité de terminer accompagnent toujours le coût.

## 8. Plan des expériences synthétiques

Le protocole V2 distingue un historique de prévision et des ensembles de développement et de test :

| Élément | Référence |
| --- | --- |
| Historique initial | 30 séances ; graine 31 000. |
| Développement | 12 chemins, graines 41 000 à 41 011. |
| Évaluation de référence | 80 chemins, graines 51 000 à 51 079. |
| Quantités | 5 % et 10 % du volume journalier **prévu**, sans utiliser le total futur pour choisir l'ordre. |
| Politiques | TWAP, VWAP, POV, ADAPTIVE. |
| Modes | Échéance souple et échéance commune. |
| Impact | Racine carrée et linéaire, ancrées au même coût à 10 % de participation. |

Les cinq régimes sont :

| Régime | Construction et mécanisme |
| --- | --- |
| `normal` | Référence synthétique sans stress supplémentaire. |
| `low_volume` | Volume réalisé réduit à 55 % ; le calendrier peut surestimer la liquidité. |
| `midday_shutdown` | Volume nul dans le tiers central ; test de retard et de capacité de rattrapage. |
| `late_shift` | Profil déplacé vers la fin de séance ; erreur de forme temporelle. |
| `stressed` | Volume à 55 %, volatilité journalière de 4 % et spread doublé ; stress conjoint. |

Il ne s'agit pas de fréquences empiriques d'événements. Les régimes d'un même chemin sont liés par construction. Les stratégies affrontent les mêmes marchés ; l'unité indépendante pour les intervalles synthétiques est le **chemin**, et non chaque barre ou chaque régime considéré comme une observation nouvelle.

Le profil et le volume prévus synthétiques sont estimés une seule fois sur l'historique initial et restent fixes pour les chemins indépendants. Les dates des chemins servent d'identifiants ; ces réalisations ne sont pas une série chronologique sur laquelle on réapprend chaque jour. L'évaluation publique, elle, utilise une fenêtre glissante. Le stress de volatilité est aussi un scénario d'hypothèses de coût : sa volatilité est fixée par le design, sans revendication de détection en temps réel du régime.

La qualité de prévision distingue l'erreur de forme du profil et l'erreur de volume total. Une bonne erreur moyenne de profil ne garantit ni un coût faible ni une bonne complétion.

## 9. Comparaisons, risque et critères fixés à l'avance

Pour chaque chemin comparable, on calcule :

```text
delta_cout = coût_ADAPTIVE − coût_VWAP          en bp ; négatif = ADAPTIVE moins cher
delta_completion = complet_ADAPTIVE − complet_VWAP
```

Dans `comparisons.csv`, `saving_bps` utilise le signe inverse pour faciliter la lecture : coût VWAP moins coût ADAPTIVE. Un `saving_bps` positif correspond donc à une économie du candidat. Toujours lire le nom et le sens de la colonne avant de commenter un signe.

`complet` est un indicateur : 1 si l'ordre entier est exécuté, 0 sinon. Sa moyenne est une fréquence de complétion dans l'échantillon. Elle diffère du taux moyen de remplissage : 99 % exécutés chaque jour donnent un taux moyen de remplissage de 99 % mais zéro ordre entièrement terminé.

La comparaison publie les moyennes des différences, les intervalles appariés et les risques de queue. Le bootstrap de référence utilise 2 000 rééchantillonnages. Les mêmes unités sont tirées pour les deux politiques ; mélanger deux tirages indépendants détruirait l'appariement.

Les seuils d'étude sont **illustratifs et propres au protocole** :

| Critère | Sens |
| --- | --- |
| 0,5 bp | Gain de coût minimal jugé utile dans l'étude. |
| 1 point de pourcentage | Tolérance de non-infériorité pour la probabilité de complétion. |
| 1 point de pourcentage | Tolérance supplémentaire pour le taux moyen de remplissage ; sa différence est évaluée par bootstrap apparié. |
| 95 % | Objectif de complétion illustratif. Ce n'est pas une norme de marché. |
| +2 bp sur le quantile 95 % | Garde-fou descriptif de risque ; ce seuil n'est pas assorti d'une preuve statistique autonome. |

Un intervalle entièrement au-delà du seuil utile apporte un argument plus solide qu'un seul gain moyen. Un intervalle qui traverse zéro indique une direction incertaine ; un intervalle qui exclut zéro mais n'atteint pas le seuil utile peut signaler un effet trop petit pour justifier la complexité.

Pour la complétion, un bootstrap peut devenir trompeusement dégénéré : si les deux politiques terminent 80 ordres sur 80, leur différence observée et tous les tirages valent zéro. Cela ne démontre pas que leurs probabilités de succès sont connues exactement. Le garde-fou de non-infériorité utilise donc `100 × (borne Wilson inférieure candidat − borne Wilson supérieure référence)` et demande une borne au moins égale à −1 point. Cette construction prudente est une approximation marginale qui ignore l'appariement ; ce n'est pas un intervalle exact de différence. Avec 80 succès sur 80 pour chacune, la borne reste proche de −4,58 points : l'échantillon ne suffit pas à établir la marge de 1 point. Le rapport conserve donc un statut non concluant lorsque ce critère manque.

La décision se fait sur le compromis, avec le sens des différences explicite : coût supplémentaire pour meilleure complétion, économie à complétion acceptable, résultat non concluant ou politique défavorable. Nous ne déclarons pas un vainqueur universel sur la seule moyenne.

Les comparaisons secondaires sont descriptives. Les intervalles ne sont pas corrigés pour une sélection parmi toutes les cellules ; leur accumulation ne vaut pas une série de découvertes indépendantes. Le quantile 95 % est peu précis sur un petit échantillon, particulièrement pour la partie publique. La variation des formes d'impact est une analyse de sensibilité du modèle, distincte de l'incertitude statistique.

## 10. Confrontation publique : BTCUSDT et ETHUSDT

L'adaptateur utilise les archives Spot Binance Vision de janvier 2026, à la minute, agrégées en 48 créneaux de 30 minutes par journée UTC. Il conserve un contrôle d'intégrité SHA-256. Les 14 premières journées servent à initialiser la prévision ; les 17 suivantes sont évaluées avec une fenêtre historique glissante de 14 journées antérieures.

Le prix de barre est le rapport entre volume en devise de cotation et volume de l'actif de base. C'est un VWAP de transactions, utilisé comme proxy dans `mid_price`. Les colonnes `open_price` et `close_price` conservent les prix d'ouverture et de clôture de barre pour les références temporelles. Les quantités sont exprimées en millionièmes d'actif afin de conserver les calculs entiers. Cette unité comptable ne représente pas le lot minimal réellement négociable d'une plateforme.

Le spread complet de 2 bp est supposé. L'impact local et les frais appliqués sont aussi des hypothèses. Les choix de taille utilisent le volume prévu, pas le volume réalisé du jour. Il faut conserver ensemble l'instrument, la période, les unités, les hypothèses et le nombre de journées quand on cite un résultat.

L'observation historique est chronologique, mais les marchés quotidiens peuvent être dépendants et les deux actifs corrélés. L'analyse publique reste descriptive par actif, avec seulement 17 journées évaluées, des différences bootstrap appariées par journée et des intervalles Wilson de complétion. Le rééchantillonnage quotidien n'est pas un bootstrap par blocs et n'est pas corrigé pour la dépendance temporelle : les intervalles sont donc à lire comme diagnostics conditionnels. Elle constitue une vérification de comportement sur un petit périmètre, pas une démonstration générale sur les actions ni une validation causale d'impact.

Les archives et artefacts dérivés relèvent des droits de Binance Vision, distincts du code MIT. [SOURCES.md](SOURCES.md) précise l'attribution et les conditions.

## 11. Résultats à consulter

| Artefact | Vérification |
| --- | --- |
| `reports/study/RESULTATS.md` | Conclusion calculée et limites du laboratoire synthétique V2. |
| `reports/study/summary.csv` | Une observation de politique et de cellule expérimentale par chemin. |
| `reports/study/aggregate.csv` | Coût, risque et complétion par cellule. |
| `reports/study/comparisons.csv` | Différences appariées et intervalles, avec sens des écarts. |
| `reports/study/forecast_metrics.csv` | Erreurs de volume et de profil. |
| `reports/study/grid_check.csv` | Cohérence du coût lorsque la grille est subdivisée. |
| `reports/study/sample_fills.csv` | Détail permettant d'expliquer une trajectoire et un rattrapage. |
| `reports/study/experiment.json` | Paramètres, graines, protocole et métadonnées de reproduction. |
| `reports/real/` | Rapport et tables sur les observations publiques, avec leur provenance et leurs droits. |
| `notebooks/02_volume_uncertainty.ipynb` | Parcours d'analyse qui réutilise le package. |

Les sorties exploratoires avec une autre taille d'échantillon, un autre split ou d'autres paramètres doivent porter ce statut. Les résultats de la commande historique `demo` sont une démonstration et ne remplacent pas le protocole d'évaluation V2.

## 12. Quand considérer le travail réussi ?

Le résultat doit d'abord être exact : conservation des quantités, capacités respectées, chronologie, réconciliation et subdivision contrôlée. Il doit ensuite être comparable : mêmes marchés, mêmes contraintes, reliquat visible. Il doit enfin permettre une conclusion conditionnelle, avec incertitude et sensibilité.

Une absence d'avantage adaptatif est un résultat recevable. Une amélioration de complétion accompagnée d'un surcoût peut aussi répondre à la question. Le succès du projet consiste à déterminer ce compromis de façon traçable ; un simulateur qui proclame systématiquement la supériorité de la stratégie ajoutée serait au contraire suspect.

La validation opérationnelle demanderait des données d'exécutions et de carnet adaptées, une calibration indépendante des coûts et une étude plus large des instruments, périodes, tailles et contraintes réelles.

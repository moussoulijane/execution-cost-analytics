# Sources, provenance et portée des références

Références vérifiées les **15 et 16 octobre 2026**. Ce fichier distingue les travaux qui motivent l'étude, la documentation des outils et la provenance des données. Les formules effectivement codées sont décrites dans [la méthodologie](METHODOLOGIE.md) ; une citation ne constitue pas une calibration de ces formules.

## Exécution et recherche quantitative

| Source primaire | Proposition utile | Rapport avec notre étude |
| --- | --- | --- |
| [Almgren et Chriss — *Optimal Execution of Portfolio Transactions*, décembre 2000, texte original conservé sur un miroir](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf) | Articulation entre coût d'exécution et risque de prix ; impact temporaire et permanent dans leur cadre. | Motive la lecture simultanée du coût et du risque. Nous n'implémentons ni leur solution optimale ni leur calibration ; notre adaptation avec contrainte de capacité est une règle heuristique. |
| [Zarinelli, Treccani, Farmer et Lillo — *Beyond the square root*, 2014](https://arxiv.org/abs/1412.2152) | Étude de l'impact des métaordres, avec rôle de la durée et de la participation ; limites d'une loi universelle en racine carrée. | Motive la sensibilité à plusieurs formes d'impact. Notre impact local est une hypothèse de simulation ; il ne reproduit pas l'estimation empirique de ce papier. |
| [Bailey, Borwein, López de Prado et Zhu — *The Probability of Backtest Overfitting*, version de février 2015](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Risque de sélectionner une stratégie favorable en multipliant les essais sur les mêmes données. | Motive un protocole écrit avant le calcul final et la publication des résultats défavorables. Nous ne calculons pas leur mesure PBO et n'implémentons pas leur procédure CSCV. |
| [Interactive Brokers — TWAP (Fox River)](https://www.ibkrguides.com/traderworkstation/fox-twap.htm) | Répartition d'un ordre dans le temps. | Le principe de notre calendrier discret TWAP ; aucun algorithme de courtier n'est reproduit. |
| [Interactive Brokers — VWAP](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/vwap) | Objectif lié au prix pondéré par les volumes et contraintes de remplissage. | Distinguer le profil prévu avant la séance du benchmark réalisé après la séance. |
| [Interactive Brokers — Percent of Volume (Fox River)](https://www.ibkrguides.com/traderworkstation/fox-pov.htm) | Exécution à un rythme associé au volume observé. | Situer notre approximation par créneaux et son possible reliquat. |

Référence bibliographique pour le terme *implementation shortfall* : André F. Perold, *The implementation shortfall: Paper versus reality*, **The Journal of Portfolio Management**, 14(3), 4–9, 1988, [DOI 10.3905/jpm.1988.409150](https://doi.org/10.3905/jpm.1988.409150). Le texte intégral n'a pas servi à reproduire une décomposition ; notre identité comptable est explicitée et testée dans le code.

## Incertitude statistique

La [documentation officielle de scipy.stats.bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) décrit le rééchantillonnage avec remise et l'utilisation des mêmes indices pour des observations appariées. Elle sert de référence de méthode : notre calcul est réalisé avec NumPy, sans dépendance à SciPy. Le choix des unités rééchantillonnées est propre à cette étude ; l'étude publique ne met pas en œuvre de bootstrap par blocs pour la dépendance temporelle.

Les intervalles du projet décrivent la variabilité des comparaisons sous les hypothèses de rééchantillonnage retenues. Ils n'incluent pas automatiquement l'erreur de spécification du simulateur, l'incertitude de calibration de l'impact ni tous les biais de sélection. Un intervalle étroit dans un simulateur mal spécifié reste insuffisant pour conclure sur un marché réel.

Le [NIST — intervalles de confiance pour une proportion](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) fournit la formule de Wilson utilisée pour les fréquences de complétion. La différence prudente entre une borne basse du candidat et une borne haute de référence est un garde-fou choisi par notre étude ; elle n'est pas présentée comme un intervalle exact apparié de différence. Elle évite notamment de transformer 80 succès sur 80 en certitude de complétion à 100 %.

## Données de marché publiques

La documentation du producteur, [Binance Public Data](https://github.com/binance/binance-public-data), décrit les archives Spot et les colonnes des bougies (*klines*). Elle fournit aussi les fichiers de contrôle SHA-256. Les horodatages Spot sont en microsecondes à partir du 1er janvier 2025. Le traitement du projet doit garder cette unité explicite.

Les droits applicables aux données sont précisés séparément dans les [Binance Vision Dataset Terms, version 1.0 du 26 août 2026](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md). Ils indiquent une licence **CC BY-NC-SA 4.0** et des conditions supplémentaires, notamment pour les usages non commerciaux et les travaux dérivés. La mention MIT du dépôt d'outils ne suffit pas à licencier les archives de marché. Lire les conditions exactes avant une réutilisation différente.

Pour l'expérience réelle, les éléments de provenance à conserver sont : instrument, mois, intervalle, URL de chaque archive, date de téléchargement, empreintes attendue et calculée, fuseau, unité des volumes et transformation des prix. Le manifeste produit avec les données et les métadonnées de l'expérience sont les références pour la période effectivement calculée.

Les bougies ne contiennent pas le carnet d'ordres. Un prix dérivé des transactions et stocké dans la colonne générique mid_price reste un **proxy de prix**, pas un mid bid–ask observé. Le spread et les coefficients d'impact appliqués à ces observations sont des hypothèses. Les rapports sur données publiques confrontent les calendriers à des volumes et prix historiques ; ils ne valident pas l'impact causal de nos ordres.

Les données brutes et les sorties personnelles sont rangées sous data/ et outputs/, ignorés par Git. Le code est sous licence MIT. Toute redistribution de données Binance et d'artefacts dérivés doit conserver l'attribution **Binance Vision** et les conditions applicables ; elle ne se déduit pas de la licence du code.

## Données synthétiques

Le générateur initial fournit un univers artificiel reproductible. La V2 applique des perturbations contrôlées aux volumes, profils et volatilités pour étudier un mécanisme. Une graine identifie une réalisation aléatoire dans un environnement donné. Multiplier les graines permet d'examiner la variabilité sous ce générateur ; cela n'ajoute pas des observations réelles.

Les stress synthétiques, leur amplitude et les paramètres de coût proviennent de notre protocole. Aucune source extérieure n'est présentée comme validant leur fréquence ou leur réalisme empirique.

## Python, bibliothèques et Git

| Documentation officielle | Utilisation dans le parcours |
| --- | --- |
| [Python 3.11 — venv](https://docs.python.org/3.11/library/venv.html) | Recréer l'environnement et appeler son interpréteur sous Windows. |
| [Python — fonctions et contrôle du déroulement](https://docs.python.org/3/tutorial/controlflow.html) | Lire def, if, les boucles et return. |
| [Python — structures de données](https://docs.python.org/3/tutorial/datastructures.html) | Listes et dictionnaires. |
| [Python Packaging User Guide — environnements et installation](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/) | Installer le package et ses dépendances. |
| [NumPy — les bases](https://numpy.org/doc/stable/user/absolute_beginners.html) | Tableaux et calculs élément par élément. |
| [pandas — tables et colonnes](https://pandas.pydata.org/docs/getting_started/intro_tutorials/01_table_oriented.html) | Lire et filtrer un DataFrame. |
| [pytest — assertions](https://docs.pytest.org/en/stable/how-to/assert.html) | Vérifier une propriété ou un cas calculé indépendamment. |
| [Ruff — linter](https://docs.astral.sh/ruff/linter/) | Détecter certains défauts de code. |
| [Git — tutoriel](https://git-scm.com/docs/gittutorial) | Fichiers de travail, index et commits. |
| [Git — diff](https://git-scm.com/docs/git-diff) | Relire les modifications et le contenu préparé. |
| [Git — restore](https://git-scm.com/docs/git-restore) | Retirer un fichier de l'index après le premier commit. |
| [GitHub — ajouter un dépôt local](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) | Comprendre la publication initiale d'un dépôt relu. |

Une page récente peut documenter une version différente de celle du projet. Les versions installées sont fixées dans pyproject.toml et consignées dans les métadonnées de reproduction ; l'environnement Python de référence est 3.11.9.

## Ajouter une référence

Relier la page précise du producteur ou le papier original, indiquer ce qu'elle permet de vérifier et séparer cette proposition des hypothèses du code. Une formule choisie par le projet doit rester présentée comme telle, même lorsqu'elle est motivée par un article connu.

# Protocole V2 figé avant le calcul

Date : 15 octobre 2026. Paramètres exécutables : [PROTOCOLE_V2.json](PROTOCOLE_V2.json).
Ce document et son JSON sont écrits avant la première évaluation V2. Il s'agit d'un protocole local, pas d'un enregistrement auprès d'un tiers. Son empreinte SHA-256 et son contenu sont archivés dans chaque résultat ; toute modification ultérieure doit être visible et justifiée.

## Question et résultat attendu

**Quel coût supplémentaire accompagne une meilleure probabilité de terminer un ordre lorsque le volume est mal prévu ?** L'objectif est d'expliquer un compromis conditionnel entre coût, risque et complétion. Une absence de gain fiable ou une dépendance au modèle d'impact constitue aussi un résultat utile. Aucun paramètre ne sera choisi parce qu'il gagne sur les graines de test.

## Échantillons et chronologie

- Historique : 30 séances synthétiques, graine 31000. La moyenne des profils normalisés des 20 dernières séances fournit les poids prévus et la moyenne des volumes fournit l'ADV prévu.
- Développement : 12 chemins indépendants, graines 41000 à 41011.
- Test : 80 chemins indépendants, graines 51000 à 51079. Aucune graine n'est commune à l'historique, au développement ou au test.
- Chaque chemin comporte 26 créneaux et un ordre d'achat. Prix de décision et d'arrivée = premier mid ; le délai de la veille est ainsi exclu de la question étudiée.
- La prévision est figée avant tous les chemins d'évaluation ; les observations du test ne servent pas à la réestimer. La date de chaque chemin est postérieure à l'historique.
- TWAP et VWAP fixent leur calendrier avant la séance. ADAPTIVE utilise son retard fondé sur les exécutions passées. POV représente une participation au flux contemporain agrégé : ce n'est pas une simulation de messages de carnet ou de transactions individuelles.

## Expériences annoncées

La quantité vaut 5 % ou 10 % de l'ADV prévu, arrondie en actions entières. Les quatre méthodes sont TWAP, VWAP prévu, POV et ADAPTIVE. Le taux POV vaut `Q / ADV_prévu`, donc son objectif nominal correspond au même ordre ; un taux arbitraire plus faible ne lui impose pas mécaniquement une faible complétion. ADAPTIVE ajoute au calendrier VWAP le retard cumulé multiplié par un gain fixé à 1.

Les cinq scénarios utilisent **les mêmes tirages de base** pour un chemin donné :

| Scénario | Transformation réalisée ; prévision inchangée |
| --- | --- |
| normal | Aucune. |
| low_volume | Volumes multipliés par 0,55, puis arrondis vers le bas. |
| midday_shutdown | Volumes des indices `B // 3` à `2 * B // 3 - 1` mis à zéro, sans compensation ultérieure. |
| late_shift | Volumes pondérés par un facteur linéaire de 0,2 à 2,0 ; total journalier conservé par allocation entière. |
| stressed | Volumes × 0,55, volatilité intraday × 2 et spreads × 2. |

Le stress n'est pas annoncé à la stratégie. La volatilité utilisée dans le coût est une hypothèse de scénario, pas une estimation donnée à la politique. Le mouvement de prix est sans signal prédictif exploité par les stratégies ; aucun drift favorable n'est ajouté.

Deux règles de fin sont comparées :

1. **soft** : plafond de participation de 15 %, reliquat possible ; aucune exécution terminale inventée.
2. **common_deadline** : sur les derniers `ceil(20 % × B)` créneaux, toutes les méthodes demandent leur solde, au plafond commun de 40 % du volume externe effectivement réalisé. Les volumes nuls donnent une capacité nulle. Le coût local habituel est payé sur ces actions ; aucune transaction gratuite ni liquidité supplémentaire ne sont ajoutées. Le nom décrit l'objectif commun ; il ne garantit pas que l'ordre peut terminer.

## Impact et contrôles

Impact temporaire par action : `mid × eta × sigma × (q / V_réalisé)^exposant`. Le volume prévu sert à décider et le volume réalisé sert à exécuter. L'ordre ne modifie pas les mids futurs ; il n'y a ni impact permanent, ni carnet, ni calibration empirique.

- Modèle racine : exposant 0,5, eta 0,05.
- Modèle linéaire : exposant 1, eta `0,05 / sqrt(0,1)`.

Les deux modèles ont le même impact à 10 % de participation : on compare ainsi la forme, à un point de normalisation commun. Les hypothèses de frais sont 0,5 bp ; la volatilité quotidienne de base vaut 2 %.

Avant interprétation, vérifier les quantités, les plafonds, l'absence de décision dépendant des créneaux futurs et la réconciliation comptable. Un contrôle à prix constant partage exactement Q=10400 et V=104000 entre 26, 52 et 104 créneaux : participation identique, impact identique pour les deux formes. Ce test retire l'artefact de subdivision de la V1 ; il ne prouve pas une invariance pour des politiques discrètes ou un marché hétérogène.

## Mesures et incertitude

Chaque ligne d'évaluation représente **un ordre sur un chemin**, jamais une barre indépendante. Publier le shortfall en bp du notionnel initial, le coût explicite (spread + impact + frais), le coût d'opportunité du reliquat, le taux de remplissage, l'indicateur de complétion totale, les quantités traitées en urgence et leur coût explicite. Le coût d'urgence est celui des actions effectivement exécutées pendant la phase terminale, pas un coût incrémental causal estimé.

Par cellule : moyenne et écart-type du shortfall, quantile 95 % défavorable, remplissage moyen, probabilité observée de complétion totale et nombre de chemins. Le reliquat est valorisé au dernier mid, ce qui n'est pas une exécution. Un coût négatif peut refléter un mouvement favorable des prix.

Les comparaisons sont appariées sur le même chemin. Le bootstrap rééchantillonne 2000 fois les identifiants de chemin avec remise, en gardant les stratégies ensemble ; IC percentiles à 95 %. Les tirages d'un même chemin entre scénarios ne sont pas traités comme de nouvelles observations indépendantes : aucun regroupement de scénarios pour gonfler n. Le quantile 95 % avec 80 chemins reste peu précis ; son écart est un garde-fou descriptif, pas une preuve de maîtrise du risque extrême. Un bootstrap de 80 chemins mesure l'incertitude Monte-Carlo dans ce générateur, pas l'incertitude de calibration sur un vrai marché.

Les comparaisons signalent les différences de remplissage ou de complétion constantes sur tous les chemins : leur IC bootstrap est alors dégénéré, par exemple `[0 ; 0]`. Cela ne prouve pas qu'aucun cas discordant n'existe hors de l'échantillon. Les probabilités de complétion de chaque méthode sont aussi accompagnées d'un intervalle de Wilson ; 80 succès observés ne donnent pas une probabilité connue de 100 %.

Le garde-fou de non-infériorité de **probabilité de complétion totale** utilise `100 × (WilsonLower(candidat) − WilsonUpper(baseline))`. Avec deux Wilson bilatéraux à 95 %, chaque borne pertinente est marginalement unilatérale à 97,5 % ; leur combinaison par l'argument de Bonferroni est prudente et ignore l'information de l'appariement. Wilson garde une couverture approximative, sans garantie exacte en petit échantillon. Cette borne peut rester sous -1 point même après 80 complétions sur 80 pour les deux méthodes : l'échantillon est alors insuffisant pour affirmer cette non-infériorité. On conserve les IC bootstrap appariés affichés, sans les utiliser seuls pour cette décision.

## Contraste principal et décisions

Un seul contraste principal est fixé : **ADAPTIVE contre VWAP, low_volume, Q=10 % ADV prévu, common_deadline, impact racine**. Les comparaisons contre TWAP et les autres cellules servent à expliquer les mécanismes et la sensibilité. Leurs IC sont descriptifs, sans correction de tests multiples ; on n'en choisira pas une après coup pour remplacer le contraste principal.

Le gain de coût est `coût_baseline - coût_stratégie` : positif signifie une économie. L'écart de remplissage est `stratégie - baseline`, en points de pourcentage. Les seuils suivants sont pédagogiques, à remplacer par les objectifs d'un client et les erreurs de calibration avant un usage réel :

- Économie minimale utile : 0,5 bp.
- Marge de non-infériorité de remplissage : 1 point de pourcentage.
- Marge de non-infériorité de probabilité de complétion totale : 1 point de pourcentage, vérifiée avec la borne prudente ci-dessus.
- Garde-fou descriptif : quantile 95 % du coût au plus 2 bp au-dessus du baseline.
- Objectif illustratif de probabilité de complétion : 95 % ; c'est un paramètre métier, pas un seuil universel.

Une **évidence conditionnelle d'économie** exige que la borne basse de l'IC du gain dépasse 0,5 bp, que la borne basse de l'écart de remplissage dépasse -1 point, que la borne prudente de probabilité de complétion soit au moins -1 point et que le garde-fou de quantile soit respecté. Une baisse de coût sans ces conditions reste incertaine ou non comparable. Si la complétion augmente en échange d'un coût plus élevé, publier les deux écarts et conclure à un compromis ; aucun budget d'acceptation n'est inventé. La probabilité de complétion totale est publiée séparément du remplissage moyen.

Une exécution de développement, un sous-ensemble de chemins, un nombre de réplications modifié ou un protocole changé sont marqués **exploratoires**. Les graines de test ne deviennent pas de nouvelles données de validation après consultation. Les tests logiciels vérifient des invariants ; on ne modifiera pas une stratégie pour rendre son classement favorable.

## Portée empirique

Cette étude peut mettre au jour les mécanismes du simulateur et montrer quand un rattrapage aide ou coûte cher. Elle ne valide pas une stratégie réelle. Une confrontation intraday doit documenter provenance, droits, horodatages, qualité et période hors échantillon. Des OHLCV historiques seuls ne suffisent pas à identifier l'impact causal de nos ordres. Cette étape reste explicitement distincte des résultats synthétiques.

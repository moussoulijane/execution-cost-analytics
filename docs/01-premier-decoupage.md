# Première séance — découper un ordre puis vérifier ce qui est exécuté

Cette séance conserve le point de départ du projet. La V2 est expliquée dans [le guide pas à pas](GUIDE_PAS_A_PAS.md). Commence ici si tu veux comprendre le code comme son développeur.

## Le problème initial

Un investisseur souhaite acheter 100 actions entre 9 h et 10 h, réparties régulièrement sur quatre créneaux de quinze minutes.

| Créneau | Quantité prévue |
| --- | ---: |
| 9 h 00 à 9 h 15 | 25 |
| 9 h 15 à 9 h 30 | 25 |
| 9 h 30 à 9 h 45 | 25 |
| 9 h 45 à 10 h 00 | 25 |
| Total | 100 |

C'est un calendrier TWAP simplifié : une répartition uniforme dans le temps. La fonction reçoit la quantité et le nombre de créneaux, puis renvoie les quantités prévues :

```python
twap_schedule(100, 4)
# [25, 25, 25, 25] après conversion en liste
```

La fonction ne traite pas encore les prix ni les coûts. Sa sortie doit contenir quatre entiers positifs ou nuls, dont la somme vaut 100. Pour une quantité de 101, le reste est conservé : `[26, 25, 25, 25]`.

**Exercice :** écris le résultat attendu pour 120 actions sur quatre créneaux, puis explique pourquoi `[30, 30, 30]` serait faux.

**Corrigé :** `[30, 30, 30, 30]`. Trois valeurs ne représentent que 90 actions et ne couvrent que trois créneaux.

## La question qui transforme cet exercice en projet de recherche

Un plan est une intention. Si le premier créneau autorise seulement 15 actions à cause de la liquidité, que fait-on des 10 actions non exécutées ?

Dans cet exemple, les volumes sont `[100, 1000, 1000, 1000]` et la participation maximale ordinaire est de 15 % :

| Créneau | Calendrier fixe : exécuté | Rattrapage adaptatif : exécuté |
| --- | ---: | ---: |
| 1 | 15 | 15 |
| 2 | 25 | 35 |
| 3 | 25 | 25 |
| 4 | 25 | 25 |
| Total | 90 | 100 |

Au deuxième créneau, la politique adaptative connaît le retard passé de 10 actions et l'ajoute à la demande prévue de 25. Elle ne sait pas ce que seront les créneaux futurs.

Ce rattrapage peut augmenter le coût ou le risque. Voilà la question V2 : **quand une meilleure chance de terminer justifie-t-elle le prix du rattrapage ?** Il faut une expérience et des critères pour y répondre ; ce tableau seul ne prouve pas une supériorité.

## Les règles à protéger

1. Le plan fixe représente exactement la quantité initiale.
2. La quantité exécutée ne dépasse ni le reste de l'ordre ni la capacité locale.
3. Modifier le futur ne change pas une décision passée.
4. Le coût est calculé avec la liquidité réellement rencontrée.
5. Le coût et le reliquat sont publiés ensemble.

Le guide t'apprend à relier chacune de ces règles à un fichier, un calcul manuel et une vérification.

## Les mots Git

- **Dossier du projet** : fichiers sur ton ordinateur.
- **Dépôt Git** : dossier accompagné de son historique de versions.
- **Index** : sélection de fichiers préparée pour le prochain enregistrement.
- **Commit** : enregistrement local de cette sélection.
- **GitHub** : service où publier ensuite une copie distante.

Le dépôt local est initialisé. `git status` et `git log --oneline` permettent d'examiner son état actuel. Le guide explique comment vérifier puis enregistrer toi-même une modification. Aucun résultat n'est publié sur GitHub par le simple lancement du projet.

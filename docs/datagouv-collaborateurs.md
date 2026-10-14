# Publication data.gouv.fr — Collaborateurs parlementaires (kit de publication)

Exports CSV prêts, générés chaque matin par la webapp (BOM UTF-8, séparateur virgule) :

- https://media.dataparl.fr/assets/collab/an.csv — Assemblée nationale
- https://media.dataparl.fr/assets/collab/senat.csv — Sénat
- https://media.dataparl.fr/assets/collab/pe.csv — Parlement européen

Colonne `chambre` : `assemblee` / `senat` / `europarl`. Le PE précise la catégorie
d'assistant dans `fonction` (accrédité, local, groupement, questure,
vice-présidence, tiers payant, prestataire de services spécialisé).

## Création du jeu (une seule fois, dans l'UI data.gouv)

1. Se connecter sur data.gouv.fr avec le compte de l'organisation **DataParl'**.
2. « Publier un jeu de données » → organisation DataParl' ; coller les textes
   ci-dessous (un jeu par chambre, ou un seul jeu avec les 3 ressources).
3. Pour chaque ressource : « Ajouter un fichier » → « Fichier distant » →
   coller l'URL de l'export. ⚠️ Fichier distant obligatoire : la mise à jour
   quotidienne est assurée par la webapp, il ne faut pas téléverser une copie.
4. Licence : **ODbL — Open Database License** (composition avec le reste des
   jeux DataParl'). Mention d'attribution des sources dans la description
   (déjà incluse dans les textes ci-dessous).
5. Une fois créé : « Moissonnage » n'est pas nécessaire pour un fichier
   distant ; data.gouv le relit périodiquement. Vérifier « Date de dernière
   mise à jour » au bout de 24 h.

## Titres

- Collaborateurs des députés de l'Assemblée nationale (en poste)
- Collaborateurs des sénateurs (en poste)
- Collaborateurs et assistants des députés européens français (en poste)

## Description commune (à adapter par chambre)

> Liste des collaborateurs parlementaires en poste, mise à jour chaque matin
> d'après les publications officielles (liste des collaborateurs par député
> publiée par l'Assemblée nationale / liste annuelle des collaborateurs des
> sénateurs publiée par le Sénat / pages assistants du Parlement européen).
>
> Chaque ligne : le collaborateur (nom, prénom, civilité, clé de
> rapprochement), l'élu (nom, identifiant, groupe parlementaire) et la
> fonction (catégorie d'assistant pour le Parlement européen : accrédité,
> local, groupement, questure, vice-présidence, tiers payant, prestataire
> de services spécialisé).
>
> Le site dataparl.fr exploite ces données pour suivre les mouvements
> (arrivées, départs, transferts), le turnover et la mixité des équipes.
> Historique des mouvements depuis 2017 également publié par DataParl'.

Sources : Assemblée nationale, Sénat, Parlement européen. Licence ODbL.

## Métadonnées à saisir

| Champ | Valeur |
|---|---|
| Licence | ODbL (Open Database License) |
| Fréquence de mise à jour | quotidien |
| Mot-clés | collaborateurs parlementaires, Assemblée nationale, Sénat, Parlement européen, turnover |
| Schéma | pas de schéma data.gouv standard ; les schémas Table Schema des autres jeux DataParl' sont sur https://raw.dataparl.fr/schemas/ |
| Organisation | DataParl' (https://www.data.gouv.fr/organizations/dataparl/) |

## Après publication

- Créer la **réutilisation** « DataParl' » pointant vers https://dataparl.fr
  (onglet Réutilisations du jeu) — les 3 jeux existants en ont 0.
- Compléter la page de présentation de l'organisation DataParl' (voir TODO du
  projet).
- Ajouter les URLs des fiches data.gouv dans les pages `/donnees` de la webapp.

## Automatisation éventuelle (clé API fournie par l'éditeur)

Si une clé API data.gouv (`DATAGOUV_API_KEY`) est fournie, un workflow peut
créer/mettre à jour les jeux via l'API
(`POST /api/1/datasets/`, `POST /api/1/datasets/{id}/resources/`) — le CSV
restant distant, seule la description a besoin d'être poussée une fois.

## Annexe — texte de présentation de l'organisation DataParl'

À coller dans https://www.data.gouv.fr/organizations/dataparl/ → « Modifier » →
description (respecte l'anonymat de l'éditeur) :

> DataParl' recense, à partir des publications officielles de l'Assemblée
> nationale, du Sénat et du Parlement européen, les collaborateurs
> parlementaires — collaborateurs de députés, de sénateurs, assistants
> accrédités et locaux, groupements, tiers payants et prestataires des
> députés européens — ainsi que leurs mouvements : arrivées, départs et
> transferts, historisés depuis 2017.
>
> L'éditeur a choisi de ne pas rendre publique son identité. Les jeux de
> données sont publiés sous licence ODbL ; le site dataparl.fr en propose
> la mise en forme : trombinoscopes, turnover par chambre et par élu
> (VigiParl'), mixité des équipes (MixiParl'), fiches par parti, par
> groupe et par mandature. Une API publique (api.dataparl.fr) et des
> schémas Table Schema accompagnent chaque jeu.
>
> Sources : Assemblée nationale, Sénat, Parlement européen, data.gouv.fr,
> Regards Citoyens, Wayback Machine. Collecte automatisée chaque matin ;
> les cas douteux (changements d'orthographe des sources) sont mis de
> côté et tranchés à la main — jamais par le robot.

Réutilisation à créer ensuite, sur chaque jeu : « DataParl' — suivi des
collaborateurs parlementaires » (lien : https://dataparl.fr, type « application »).

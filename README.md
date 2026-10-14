# DataParl' : suivi des mouvements de collaborateurs parlementaires

Ce dépôt suit, jour après jour, les collaborateurs des parlementaires français dans les trois assemblées :

| Chambre | Source officielle | Élus suivis |
|---|---|---|
| Assemblée nationale | `data.assemblee-nationale.fr`, CSV open data des collaborateurs (+ CSV des députés pour les groupes) | députés en exercice |
| Sénat | PDF « Liste des collaborateurs par Sénateur » publié par l'A.G.A.S. (+ `ODSEN_GENERAL.csv` pour matricule et groupe) | sénateurs en exercice |
| Parlement européen | pages publiques `europarl.europa.eu` (liste des eurodéputés français, puis page « assistants » de chacun) | eurodéputés élus en France |

> **Parlement européen : suivi repris (8 octobre 2026).** Après un mois de blocage par le défi anti-robot AWS WAF du site (HTTP 202 sur toutes les IP datacenter), le suivi PE tourne à nouveau via le transport Playwright (`collabs/pe_waf.py`) sur un runner auto-hébergé étiqueté `europarl` — voir `docs/europarl-suivi.md`. Premier run : 81 élus, 458 affectations. La vanne `vars.PE_PAUSE` permet de couper le cron sans toucher au runner.

Chaque matin, un workflow GitHub Actions relit les trois sources, compare avec l'état de la veille et consigne les **arrivées**, **départs** et **transferts** dans `data/mouvements.csv`. L'historique git de `data/` est la trace d'audit complète.

## Données produites

```
data/
  assemblee/affectations.csv   état courant : un couple élu / collaborateur par ligne
  senat/affectations.csv
  europarl/affectations.csv
  mouvements.csv               journal de tous les mouvements détectés (append-only)
  runs.csv                     un résumé par chambre et par run (hors jours sans changement)
```

### `mouvements.csv`

| Colonne | Contenu |
|---|---|
| `id` | identifiant stable (hash), sert à dédupliquer |
| `date_event` | date de détection (Europe/Paris) |
| `chambre` | `assemblee`, `senat`, `europarl` |
| `type` | `arrivee`, `depart`, `transfert` (sans accent) |
| `collab_nom`, `collab_prenom`, `collab_civilite`, `collab_cle` | le collaborateur ; `collab_cle` est la clé normalisée utilisée pour le diff |
| `elu_cle`, `elu_id`, `elu_nom`, `elu_groupe` | l'élu rejoint (arrivée, transfert) ou quitté (départ) ; `elu_groupe` est un sigle homogène (table dans `collabs/groupes.py`) |
| `elu_origine_*` | pour un transfert, l'élu quitté |
| `fonction` | PE : type d'assistant (accrédité, local...) |
| `contexte` | vide pour un mouvement ordinaire ; `elu_sortant` / `elu_entrant` quand le mouvement découle d'un changement d'élu (fin de mandat, renouvellement) |
| `source`, `confiance` | `live`, `bot` |
| `date_source` | date d'édition de la source quand elle est publiée (Sénat) |
| `run_id` | identifiant du run GitHub Actions |

Les conventions (`type` sans accent, `chambre` en minuscules, `source`, `confiance`, `date_event`) sont celles du schéma Supabase V2, pour permettre un import direct.

## Supabase

Les CSV du dépôt restent la source de vérité ; ils sont recopiés dans le projet Supabase `dataparl` (eu-west-1) pour être interrogés par la webapp ou une API :

| Table | Contenu | Clé |
|---|---|---|
| `mouvements` | live + historique (Regards Citoyens, Wayback), colonne `source` | `id` |
| `affectations` | état courant par chambre | (`chambre`, `elu_cle`, `collab_cle`) |
| `runs` | résumé des runs | (`run_id`, `chambre`) |

Lecture publique (RLS : `select` ouvert à `anon`), écriture uniquement avec la clé `service_role`. La synchro tourne après chaque run quotidien et après le workflow « Historique Wayback » ; « Synchro Supabase » permet une recharge complète à la main. Secrets GitHub requis : `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.

## Méthode

**Identifier un collaborateur.** Les sources n'écrivent pas les noms de la même façon (« DUPONT Jean » au Sénat, « Jean DUPONT » au PE, colonnes séparées à l'AN, « Jean-Pierre » un jour et « Jean Pierre » le lendemain). Chaque collaborateur est donc identifié par une clé : nom et prénom en minuscules, sans accents, sans civilité, tokens triés. Une variation d'orthographe de ce type ne produit aucun mouvement.

**Identifier un élu.** Clé stable et propre à chaque source : identifiant `PA…` à l'AN, identifiant européen au PE, clé du nom au Sénat (le PDF ne donne pas d'identifiant ; le matricule issu d'ODSEN est ajouté en enrichissement dans `elu_id`, sans jamais servir au diff, pour qu'une indisponibilité d'ODSEN ne fasse pas bouger les clés).

**Arrivée, départ, transfert.** Un couple élu / collaborateur qui apparaît est une arrivée, un couple qui disparaît un départ. Si, pour un même collaborateur, exactement un couple disparaît et exactement un apparaît le même jour, les deux sont fusionnés en un transfert. Dans les cas ambigus (homonymes, collaborateur partagé entre plusieurs élus), on garde des arrivées et départs séparés plutôt que d'inventer un transfert.

**Date.** `date_event` est la date à laquelle le changement est vu dans la source, pas la date du contrat : les sources ne publient pas de dates d'embauche.

### Garde-fous

Une chambre qui déclenche un garde-fou n'écrit rien (ni snapshot, ni mouvement), les autres chambres continuent, et le workflow finit en échec pour alerter.

1. **Complétude** : planchers absolus d'affectations et d'élus, et pas de chute de plus de 30 % par rapport à la veille.
2. **Pages illisibles (PE)** : si la page d'un eurodéputé ne répond pas, ses collaborateurs de la veille sont reconduits (pas de faux départs) ; au-delà de 20 % d'échecs, la chambre est bloquée.
3. **Élus disparus** : plus de 10 élus absents d'un coup bloque la chambre (une liste tronquée produirait sinon des départs en masse).
4. **Plafond** : plus de 80 mouvements ordinaires dans une chambre bloque la chambre (les mouvements `elu_entrant` / `elu_sortant` ne comptent pas).

Seuils réglables par variables d'environnement : `COLLABS_MIN_RATIO`, `COLLABS_MAX_ECHECS_RATIO`, `MAX_ELUS_SORTANTS`, `MAX_EVENTS`. Le premier run d'une chambre initialise son état sans produire de mouvement.

### Renouvellements et dissolution

Le renouvellement sénatorial (série 2, septembre 2026) ou une dissolution de l'Assemblée déclenchera volontairement les garde-fous 1 ou 3. Procédure :

1. lancer le workflow à la main avec `dry_run` coché et vérifier le log ;
2. relancer avec `dry_run` décoché et `force` coché.

Après une dissolution, mettre aussi à jour la variable `AN_LEGISLATURE` (17 par défaut) : les URL open data de l'AN changent de répertoire à chaque législature.

## Historique (Regards Citoyens)

`data/historique/` contient l'historique reconstruit depuis le dépôt git de [Regards Citoyens](https://github.com/regardscitoyens/Collaborateurs-Parlement), qui a converti chaque nuit les listes officielles en CSV :

| Fichier | Période | Mouvements |
|---|---|---|
| `senat_regardscitoyens.csv` | mai 2015 à octobre 2023 | 4 559 |
| `assemblee_regardscitoyens.csv` | février 2017 à juin 2024 | 20 568 |

Même format que `mouvements.csv`, avec `source=regardscitoyens` et `confiance=moyen` ; `date_event` est la date de la conversion nocturne (à un jour près de la publication). Les clés sont celles du suivi quotidien, l'historique se raccorde donc aux données live.

Nettoyage appliqué : versions quasi vides ou sans noms d'élus écartées ; versions « ratées puis corrigées le lendemain » écartées ; accents corrigés quand la source les écrivait en séquences littérales (juin 2018) ; allers-retours d'un même couple à moins de 7 jours retirés (bruit de publication). Les groupes politiques ne sont pas renseignés sur cette période.

**Lacunes** : de novembre 2023 à septembre 2026 pour le Sénat, de juin 2024 à septembre 2026 pour l'AN (à combler avec les archives Wayback Machine). Pour régénérer : `python -m collabs historique --repo <clone de Collaborateurs-Parlement>`.

## Utilisation

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python -m collabs run --dry-run
python -m collabs run --chambre senat --dry-run
python -m collabs run
```

Options : `--chambre` (une ou plusieurs), `--dry-run` (ou `DRY_RUN=true`), `--force`, `--max-events`, `--date AAAA-MM-JJ`, `--data-dir`.

### Mise en service sur GitHub

1. Pousser le dépôt ; dans *Settings → Actions → General*, autoriser les workflows en « Read and write permissions ».
2. *Actions → Suivi quotidien → Run workflow* avec `dry_run` coché : vérifie que les sources répondent depuis les runners.
3. Relancer avec `dry_run` décoché : initialise les états (aucun mouvement ce jour-là).
4. À partir du lendemain, le cron quotidien (07:47 à Paris) consigne les mouvements.

## Limites connues

- **AN** : le CSV ne donne pas la civilité des collaborateurs.
- **PE** : toutes les catégories de la page « assistants » sont suivies (accrédités, locaux, groupements, questure, vice-présidence, tiers payants, prestataires de services spécialisés) ; seuls les stagiaires sont ignorés. Les tiers payants et prestataires sont le plus souvent des sociétés : nom conservé entier, sans découpage prénom/nom. Pour les personnes, les noms sont découpés en prénom / nom d'après les capitales, ce qui peut se tromper sur des noms atypiques (sans effet sur le diff, qui repose sur la clé).
- **Sénat** : un sénateur est identifié par son nom tel qu'écrit dans le PDF ; un changement d'orthographe de son nom par l'A.G.A.S. produirait des départs / arrivées avec le contexte `elu_sortant` / `elu_entrant`.
- **Homonymes** : deux collaborateurs homonymes dans une même chambre partagent la même clé.

## Tests

Le parser du Sénat est testé sur un vrai PDF de l'A.G.A.S. (édition du 30/10/2023) et comparé couple par couple au CSV publié par [Regards Citoyens](https://github.com/regardscitoyens/Collaborateurs-Parlement) pour la même édition. Au développement, il a aussi été vérifié sur 26 éditions réparties entre mai 2015 et octobre 2023, avec une concordance exacte à chaque fois.

## Sources et licences

- Assemblée nationale et Sénat : données publiées sous Licence Ouverte / Etalab.
- Parlement européen : informations publiques de `europarl.europa.eu`, réutilisation autorisée avec mention de la source.
- Regards Citoyens : référence de test (ODbL).

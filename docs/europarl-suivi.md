# Reprendre le suivi du Parlement europÃ©en

Le rÃ©fÃ©rentiel PE (parlementaires, mandats, groupes, commissions) est dÃ©jÃ 
collectÃ© par l'API open data `data.europarl.europa.eu` (aucun filtrage) et
publiÃ© sur dataparl.fr. Seul le suivi des **assistants** des eurodÃ©putÃ©s est
en pause : les pages `www.europarl.europa.eu/meps/en/{id}/HOME/assistants`
sont protÃ©gÃ©es par un dÃ©fi JavaScript AWS WAF (HTTP 202) qui bloque toutes
les IP datacenters observÃ©es (runners GitHub Actions, Vercel, sandbox).

## 1. VÃ©rifier depuis le poste choisi

```bash
git clone https://github.com/dataparl/collaborateurs.git
cd collaborateurs
pip install -r requirements.txt
python -m collabs diag europarl
```

Si le diagnostic renvoie du HTML de fiche (HTTP 200), le poste passe :
installer un runner auto-hÃ©bergÃ© (option A). Sinon, utiliser le transport
Playwright (option B) â un vrai navigateur exÃ©cute le dÃ©fi JavaScript et
conserve le cookie de dÃ©fi (`aws-waf-token`).

## 2. Option A â runner auto-hÃ©bergÃ© (recommandÃ©)

Sur une machine qui passe le diagnostic (poste perso, VPS non datacenter) :

1. `Settings â Actions â Runners â New self-hosted runner` sur
   `dataparl/collaborateurs`, suivre les instructions d'installation.
2. Ajouter l'Ã©tiquette **`europarl`** au runner
   (`./config.sh --labels europarl` ou via l'interface).
3. Le workflow `.github/workflows/suivi-europarl.yml` (branche
   `europarl-suivi`) tourne alors chaque matin Ã  08:17 heure de Paris et
   publie mouvements + Supabase avec les mÃªmes secrets que le suivi
   AN/SÃ©nat (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`).
4. Premier test : `Actions â Suivi Parlement europÃ©en â Run workflow` avec
   **DRY RUN** cochÃ©, vÃ©rifier le journal, puis relancer sans dry run.
5. `vars.PE_PAUSE` (variable de dÃ©pÃ´t) permet de couper le cron sans
   retirer le runner.

Le runner ne doit pas Ãªtre exposÃ© sur internet : il se connecte Ã  GitHub
en sortie uniquement. Aucun port n'Ã©coute.

## 3. Option B â transport Playwright (sans runner)

Le module `collabs/pe_waf.py` charge les pages dans Chromium headless
(profil persistant `~/.cache/dataparl-pe-chromium`) qui rÃ©sout le dÃ©fi
comme un navigateur ordinaire, puis rÃ©utilise le cookie pour les 81 pages.

```bash
pip install -r requirements.txt playwright
playwright install chromium
python -m collabs.pe_waf run --chambre europarl --dry-run   # contrÃ´le
python -m collabs.pe_waf run --chambre europarl             # collecte
python -m collabs supabase                                  # publication
```

Ã lancer en cron local (ex. `17 8 * * *`). En cas d'IP malgrÃ© tout
dÃ©fiÃ©e, le profil navigateur rejoue le dÃ©fi automatiquement.

## 4. AprÃ¨s la premiÃ¨re collecte

- Le `data/mouvements.csv` et les CSV `data/senat`/`data/assemblee`
  sont alimentÃ©s par chambre ; vÃ©rifier `data/derive/` pour le PE.
- Le bandeau Â« suivi en pause Â¿ de la webapp (`app/(site)/mouvements/
  [chambre]/page.tsx`) peut Ãªtre retirÃ© une fois deux ou trois journÃ©es
  de collecte confirmÃ©es.
- VigiParl' et MixiParl' s'alimentent des vues `stats_annuelles` et
  `stats_durees` : ils couvriront le PE dÃ©s que `periodes` contient
  des lignes `europarl` assez anciennes.

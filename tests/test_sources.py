import csv
from pathlib import Path

from collabs.sources import assemblee, europarl, senat

FIX = Path(__file__).parent / "fixtures"


# ── Assemblée nationale ──────────────────────────────────────────────────────

AN_COLLABS = (
    '"Identifiant du député","Nom du député","Prénom du député","Nom du collaborateur","Prénom du collaborateur"\n'
    '"PA840773","Fayssat","Olivier","Rioult","Olivier"\n'
    '"PA840773","Fayssat","Olivier","Gregori","Anne-Marie"\n'
    '"795998","K/Bidi","Émeline","Hoarau","Jean"\n'
    '"PA840773","Fayssat","Olivier","","" \n'
).encode("utf-8-sig")

AN_DEPUTES = (
    '"identifiant","Prénom","Nom","Région","Département","Numéro de circonscription","Profession",'
    '"Groupe politique (complet)","Groupe politique (abrégé)"\n'
    '"795998","Émeline","K/Bidi","Réunion","Réunion","4","Avocate","Gauche Démocrate et Républicaine","GDR"\n'
).encode("utf-8")


def test_assemblee_parse():
    groupes = assemblee.parse_deputes(AN_DEPUTES)
    assert groupes == {"PA795998": "GDR"}
    affs = assemblee.parse_collaborateurs(AN_COLLABS, groupes)
    assert len(affs) == 3
    kb = [a for a in affs if a.elu_cle == "PA795998"][0]
    assert (kb.elu_nom, kb.elu_groupe, kb.collab_nom, kb.collab_prenom) == ("Émeline K/Bidi", "GDR", "Hoarau", "Jean")


def test_assemblee_colonnes_manquantes():
    import pytest
    with pytest.raises(ValueError):
        assemblee.parse_collaborateurs(b'"a","b"\n"1","2"\n')


# ── Sénat ────────────────────────────────────────────────────────────────────

def test_senat_pdf_reel_identique_a_la_reference():
    """PDF A.G.A.S. du 30/10/2023, comparé au CSV publié par Regards Citoyens."""
    rows, edition = senat.parse_pdf((FIX / "senat_agas_2023-10-30.pdf").read_bytes())
    assert edition == "2023-10-30"
    affs = senat.build_affectations(rows)
    with (FIX / "senat_agas_2023-10-30_attendu.csv").open(encoding="utf-8") as f:
        attendu = {(r["elu_cle"], r["collab_cle"]) for r in csv.DictReader(f)}
    assert {a.pair for a in affs} == attendu
    assert sum(1 for a in affs if a.statut == senat.CONGE_MARK) == 3
    allizard = sorted(a.collab_nom for a in affs if a.elu_nom == "Pascal ALLIZARD")
    assert allizard == ["OLIVIER", "TOLINI"]


def test_senat_odsen_enrichissement():
    content = (
        '% Requête : select ...\n'
        '"Matricule","Qualité","Nom usuel","Prénom usuel","État","Groupe politique"\n'
        '"14133K","M.","Allizard","Pascal","ACTIF","Les Républicains"\n'
        '"99999Z","M.","Ancien","Paul","ANCIEN","X"\n'
    ).encode("latin-1")
    odsen = senat.parse_odsen(content)
    assert odsen == {"allizard pascal": ("14133K", "LR")}
    affs = senat.build_affectations([("M. ALLIZARD Pascal", "Mme OLIVIER Béatrice", "")], odsen)
    assert (affs[0].elu_id, affs[0].elu_groupe, affs[0].elu_cle) == ("14133K", "LR", "allizard pascal")


# ── Parlement européen ───────────────────────────────────────────────────────

SEARCH_HTML = """
<div class="es_member-list-item" id="member-block-256869">
  <div class="es_title-h4">Grégory ALLIONE</div><span class="sln-additional-info">Renew Europe Group</span>
</div>
<div class="es_member-list-item" id="member-block-197533">
  <div class="es_title-h4">Manon AUBRY</div><span class="sln-additional-info">The Left group in the European Parliament</span>
</div>
"""

ASSISTANTS_HTML = """
<div class="erpl_meps-assistants">
 <div class="erpl_type-assistants"><h4 class="es_title-h4">Accredited assistants</h4>
   <span class="erpl_assistant">Anne-Michele DEPREZ</span><span class="erpl_assistant">Paul MARTIN</span></div>
 <div class="erpl_type-assistants"><h4 class="es_title-h4">Local assistants</h4>
   <span class="erpl_assistant">Léa de LA TOUR</span></div>
 <div class="erpl_type-assistants"><h4 class="es_title-h4">Paying agents</h4>
   <span class="erpl_assistant">SOCIETE FIDUCIAIRE SARL</span></div>
</div>
"""


def test_europarl_liste_meps():
    meps = europarl.parse_search_page(SEARCH_HTML)
    assert meps["256869"] == {"name": "Grégory ALLIONE", "group": "Renew Europe Group"}
    assert len(meps) == 2


def test_europarl_full_list_xml():
    xml = b"""<meps><mep><fullName>Manon AUBRY</fullName><country>France</country>
      <politicalGroup>The Left</politicalGroup><id>197533</id></mep>
      <mep><fullName>Hans X</fullName><country>Germany</country><politicalGroup>EPP</politicalGroup><id>1</id></mep></meps>"""
    assert europarl.parse_full_list_xml(xml) == {"197533": {"name": "Manon AUBRY", "group": "The Left"}}


def test_europarl_assistants_toutes_categories():
    # Les paying agents sont collectés depuis l'ajout des tiers payants /
    # prestataires (structures européennes) : ils font partie du résultat.
    got = europarl.parse_assistants_page(ASSISTANTS_HTML)
    assert got == [
        ("Anne-Michele DEPREZ", "Assistant accrédité"),
        ("Paul MARTIN", "Assistant accrédité"),
        ("Léa de LA TOUR", "Assistant local"),
        ("SOCIETE FIDUCIAIRE SARL", "Tiers payant"),
    ]


def test_europarl_page_inattendue_est_un_echec():
    assert europarl.parse_assistants_page("<html><body>Service unavailable</body></html>") is None


def test_sigles_homogenes():
    from collabs.groupes import sigle
    assert sigle("senat", "Les Républicains") == ("LR", True)
    assert sigle("senat", "Les Indépendants") == ("INDEP", True)
    assert sigle("senat", "SER") == ("SER", True)
    assert sigle("senat", "Communiste Républicain Citoyen et Écologiste — Kanaky") == ("CRCE-K", True)
    assert sigle("senat", "Nouveau groupe") == ("Nouveau groupe", False)
    assert sigle("assemblee", "LFI-NFP") == ("LFI-NFP", True)
    assert sigle("europarl", "Renew Europe Group") == ("Renew", True)
    assert sigle("europarl", "Patriots for Europe Group") == ("PfE", True)

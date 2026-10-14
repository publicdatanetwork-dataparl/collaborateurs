// Enrichissement automatique : chambre, élu et département détectés dans le
// titre ou le texte de l'offre, au format standard :
//   [An/Sénat/PE] Département - Prénom NOM de l'élu (Parti) : intitulé

export const sansAccents = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

const { createHash } = await import("crypto");
export const fingerprint = (titre, url) =>
  createHash("sha256").update(sansAccents(titre).toLowerCase().replace(/\s+/g, " ").trim() + "|" + url).digest("hex");

// Chambre : devinée depuis le vocabulaire de l'annonce.
export function chambreDepuisTexte(t) {
  const s = sansAccents(t).toLowerCase();
  if (/eurodepute|parlement europeen|depute europeen|mpe\b/.test(s)) return "pe";
  if (/senateur|senatrice/.test(s)) return "senat";
  if (/depute|deputee|assemblee nationale|circonscription/.test(s)) return "an";
  return null;
}

// Élu : « sénatrice Catherine BELRHITI », « député Nicolas Ray »…
// Prénom = un mot casse basse, Nom = UN À TROIS mots tout en majuscules,
// ou un Nom casse normale après le prénom si pas de majuscules.
export function eluDepuisTexte(t) {
  const s = t;
  const m = s.match(
    /(?:s[eé]natrice|s[eé]nateur|d[eé]put[eé]e|d[eé]put[eé]|d[eé]put[eé]e europ[eé]enne?|eurod[eé]put[eé]e?)\s+(?:de\s+|d'\s*)?(?:la\s+|le\s+)?([A-ZÉÈÀÂÎÔ][a-zéèàâîôûç]+)\s+((?:[A-ZÉÈÀÂÎÔ][a-zéèàâîôûç-]+\s?){1,2}|(?:[A-ZÉÈÀÂÎÔ][A-ZÉÈÀÂÎÔ'\s-]+){1,2})/
  );
  if (!m) return null;
  const prenom = m[1];
  const nom = m[2].trim();
  if (!nom || nom.length < 2) return null;
  return { elu_prenom: prenom, elu_nom: nom };
}

// Département : « de la Moselle », « (54) », « de Meurthe-et-Moselle »…
const DEPTS = ["Moselle","Meurthe-et-Moselle","Ain","Aisne","Allier","Alpes-Maritimes","Ardèche","Ardennes","Ariège","Aube","Aude","Aveyron","Bas-Rhin","Bouches-du-Rhône","Calvados","Cantal","Charente","Charente-Maritime","Cher","Corrèze","Corse-du-Sud","Côte-d'Or","Côtes-d'Armor","Creuse","Deux-Sèvres","Dordogne","Doubs","Drôme","Essonne","Eure","Eure-et-Loir","Finistère","Gard","Gers","Gironde","Gironde","Haute-Garonne","Haute-Loire","Haute-Marne","Haute-Saône","Haute-Savoie","Haute-Vienne","Hautes-Alpes","Hautes-Pyrénées","Haut-Rhin","Hauts-de-Seine","Hérault","Ille-et-Vilaine","Indre","Indre-et-Loire","Isère","Jura","Landes","Loir-et-Cher","Loire","Loire-Atlantique","Loiret","Lot","Lot-et-Garonne","Lozère","Maine-et-Loire","Manche","Marne","Mayenne","Mayotte","Morbihan","Moselle","Nièvre","Nord","Oise","Orne","Paris","Pas-de-Calais","Puy-de-Dôme","Pyrénées-Atlantiques","Pyrénées-Orientales","Réunion","Rhône","Saône-et-Loire","Sarthe","Savoie","Seine-et-Marne","Seine-Maritime","Seine-Saint-Denis","Somme","Tarn","Tarn-et-Garonne","Territoire de Belfort","Val-de-Marne","Val-d'Oise","Var","Vaucluse","Vendée","Vienne","Vosges","Yonne","Yvelines"];
export function departementDepuisTexte(t) {
  const s = sansAccents(t).toLowerCase().replace(/[-'\s]+/g, " ");
  for (const d of DEPTS) {
    const n = sansAccents(d).toLowerCase().replace(/[-'\s]+/g, " ");
    if (s.includes(n)) return d;
  }
  return null;
}

// Filtres parlementaires communs.
export const RE_PARLEMENTAIRE = /(collaborateur|collaboratrice|assistant|assistante|attache|attachee|charge|chargee)[^a-z]{0,6}(e\)?\s)?\s?parlementaire/;
export const RE_EQUIPE = /equipe parlementaire|depute|deputee|senateur|senatrice|eurodepute|groupe parlementaire/;
export const estParlementaire = (t) => { const x = sansAccents(t).toLowerCase(); return RE_PARLEMENTAIRE.test(x) || RE_EQUIPE.test(x); };

// Enrichissement complet d'une ligne d'offre (best effort — la revue humaine
// complète ou corrige ce qui manque).
// Renvoie la ligne COMPLÈTE (toutes ses clés d'origine) enrichie des quatre
// champs détectés — les collecteurs insèrent directement la valeur renvoyée.
// IMPORTANT : toujours inclure les 4 clés chambre/elu_prenom/elu_nom/
// departement (avec null quand rien n'est détecté) — PostgREST refuse les
// inserts groupés dont les objets n'ont pas tous exactement les mêmes clés
// (PGRST102 "All object keys must match").
export function enrichir(ligne, texteSource) {
  const t = ((ligne.titre ?? "") + " " + (texteSource ?? "")).slice(0, 600);
  const chambre = chambreDepuisTexte(t);
  const elu = eluDepuisTexte(t);
  const departement = departementDepuisTexte(t);
  return {
    ...ligne,
    chambre: ligne.chambre ?? chambre ?? null,
    elu_prenom: ligne.elu_prenom ?? elu?.elu_prenom ?? null,
    elu_nom: ligne.elu_nom ?? elu?.elu_nom ?? null,
    departement: ligne.departement ?? departement ?? null,
  };
}

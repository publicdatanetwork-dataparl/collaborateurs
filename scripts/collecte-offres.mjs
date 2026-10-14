// Collecte des offres d'emploi de collaborateur parlementaire — DataParl' Jobs.
// Sources institutionnelles et agrégateurs publics. Chaque offre est
// enrichie au format standard (chambre, élu, département) par jobs-lib.mjs.
// Écarté après test (oct. 2026) : Indeed (RSS supprimé), LinkedIn (accès
// bloqué, partenariat fermé), Welcome to the Jungle (pas d'API publique).
import { enrichir, estParlementaire, fingerprint } from "./jobs-lib.mjs";

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;

const SOURCES = [
  { nom: "emplois-politiques", url: "https://www.emplois-politiques.fr/les-offres-d-emplois" },
  { nom: "emplois-politiques", url: "https://www.emplois-politiques.fr/les-offres-d-emplois/categories/cdi" },
  { nom: "emplois-politiques", url: "https://www.emplois-politiques.fr/les-offres-d-emplois/categories/cdd" },
  { nom: "emplois-politiques", url: "https://www.emplois-politiques.fr/les-offres-d-emplois/categories/stage" },
  { nom: "emplois-politiques", url: "https://www.emplois-politiques.fr/les-offres-d-emplois/categories/alternance" },
  { nom: "emplois-politiques", url: "https://www.emplois-politiques.fr/les-offres-d-emplois/categories/freelance" },
  { nom: "assemblee-nationale", url: "https://www2.assemblee-nationale.fr/informations-pratiques/concours-et-autres-recrutements/offres-d-emploi2" },
  { nom: "senat", url: "https://www.senat.fr/le-senat-et-vous/travailler-au-senat/effectuer-un-stage-au-senat/contractuels/toutes-les-offres-demploi.html" },
  { nom: "parlement-europeen", url: "https://www.europarl.europa.eu/at-your-service/fr/work-with-us/how-to-apply" },
];

const extraireOffres = (html, base) => {
  const offres = [];
  const reTitre = /<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/gi;
  let m;
  while ((m = reTitre.exec(html)) !== null) {
    const titre = m[1].replace(/<[^>]*>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
    const apres = html.slice(m.index, m.index + 3000);
    const lm = apres.match(/href=["']([^"']+)["']/i);
    let url = base;
    if (lm) { try { const u = new URL(lm[1], base); if (u.protocol.startsWith("http")) url = u.toString(); } catch {} }
    offres.push({ titre, url });
  }
  return offres;
};

(async () => {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) throw new Error("SUPABASE_URL / SUPABASE_SERVICE_KEY manquants");

  const vues = new Map();
  for (const s of SOURCES) {
    try {
      const html = await fetch(s.url, { headers: { "User-Agent": "DataParlBot/1.0 (+https://www.dataparl.fr)" } }).then((r) => r.text());
      const offres = extraireOffres(html, s.url);
      const retenu = offres.filter((o) => o.titre.length > 15 && estParlementaire(o.titre));
      console.log(s.nom + " : " + retenu.length + " offre(s) parlementaire(s) sur " + offres.length + " titres");
      for (const o of retenu) {
        const fp = fingerprint(o.titre, o.url);
        if (!vues.has(fp)) vues.set(fp, enrichir({
          fingerprint: fp,
          titre: o.titre.slice(0, 290),
          description: "",
          source_url: o.url.slice(0, 990),
          source_connector: s.nom.replace(/-.*$/, ""),
          statut: "active",
          review_status: "pending",
        }, o.titre));
      }
    } catch (e) { console.log(s.nom + " : ignoré (" + String(e.message).slice(0, 80) + ")"); }
  }
  if (!vues.size) { console.log("Aucune offre candidate aujourd'hui."); return; }
  console.log([...vues.values()].length + " offre(s) à déposer en revue.");

  const r = await fetch(SUPABASE_URL + "/rest/v1/job_offers?on_conflict=fingerprint", {
    method: "POST",
    headers: {
      "apikey": SUPABASE_SERVICE_KEY,
      "Authorization": "Bearer " + SUPABASE_SERVICE_KEY,
      "Content-Type": "application/json",
      "Prefer": "resolution=ignore-duplicates,return=minimal",
    },
    body: JSON.stringify([...vues.values()]),
  });
  if (!r.ok) throw new Error("job_offers : HTTP " + r.status + " " + (await r.text()).slice(0, 200));
  console.log("Offres déposées (déjà connues ignorées).");
})().catch((e) => { console.error(e.message); process.exit(1); });

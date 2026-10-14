// Dépose une offre FICTIVE de test dans job_offers (review_status = pending).
// Permet de tester le flux complet : Admin → Emplois → Revue → approuver → /jobs.
// Idempotent grâce au fingerprint fixe : relancer ne duplique jamais.

const SUPABASE_URL = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_KEY;
const { createHash } = await import("crypto");

const offre = {
  fingerprint: createHash("sha256").update("test-offre-fictive|https://www.dataparl.fr/jobs-test").digest("hex"),
  titre: "[TEST] Collaborateur parlementaire — équipe d'un député de la 2e circonscription de Meurthe-et-Moselle",
  description: "Offre fictive de test du pipeline DataParl' Jobs — ne pas publier telle quelle sur le site définitif.\n\nMissions fictives : appui au travail législatif, suivi des dossiers de circonscription, permanences, relation avec les élus locaux.\n\nContrat : CDI fictif, temps plein, basé à Nancy (54).",
  type_poste: "CDI",
  localisation: "Nancy (54)",
  groupe_politique: "Test",
  source_url: "https://www.dataparl.fr/jobs-test",
  source_connector: "test",
  statut: "active",
  review_status: "pending",
};

(async () => {
  if (!SUPABASE_URL || !KEY) throw new Error("Secrets manquants");
  const r = await fetch(SUPABASE_URL + "/rest/v1/job_offers?on_conflict=fingerprint", {
    method: "POST",
    headers: {
      "apikey": KEY,
      "Authorization": "Bearer " + KEY,
      "Content-Type": "application/json",
      "Prefer": "resolution=ignore-duplicates,return=minimal",
    },
    body: JSON.stringify([offre]),
  });
  if (!r.ok) throw new Error("HTTP " + r.status + " " + (await r.text()).slice(0, 200));
  console.log("Offre fictive [TEST] déposée en revue (pending) — ignorée si déjà présente.");
})().catch((e) => { console.error(e.message); process.exit(1); });
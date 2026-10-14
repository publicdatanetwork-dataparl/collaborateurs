// DataParl' Jobs — veille Bluesky : les élus et leurs équipes y relaient leurs offres.
// Recherche publique (app.bsky.feed.searchPosts, sans compte), filtres
// « offre + terme parlementaire + lien », enrichissement au format standard.
// X (Twitter) : API de recherche payante — non intégré.
import { enrichir, fingerprint, sansAccents } from "./jobs-lib.mjs";

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;
const BSKY = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts";

const RECHERCHES = [
  "\"collaborateur parlementaire\" offre",
  "\"assistante parlementaire\" recrutement",
  "\"attaché parlementaire\" poste",
  "\"recherche collaborateur\" député",
  "\"recherche collaborateur\" sénateur",
];

const RE_METIER = /(collaborateur|collaboratrice|assistant|assistante|attache|attachee)[^a-z]{0,6}(e\)?\s)?\s?parlementaire/;
const RE_OFFRE = /offre|recrutement|recherche|poste|candidature|candidat|job|hiring|nous rejoindre/;

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) throw new Error("Secrets manquants");
  const vues = new Map();

  for (const q of RECHERCHES) {
    try {
      const r = await fetch(BSKY + "?q=" + encodeURIComponent(q) + "&limit=50", {
        headers: { "User-Agent": "DataParlBot/1.0 (+https://www.dataparl.fr)" },
      });
      if (!r.ok) { console.log("Bluesky : HTTP " + r.status + " pour « " + q + " »"); continue; }
      const d = await r.json();
      const posts = d.posts ?? [];
      console.log("« " + q + " » : " + posts.length + " posts");
      for (const p of posts) {
        const post = p.post ?? p;
        const auteur = post.author?.handle ?? "inconnu";
        const texte = (post.record?.text ?? "").replace(/\s+/g, " ").trim();
        const creer = post.record?.createdAt ?? new Date().toISOString();
        if (Date.now() - new Date(creer).getTime() > 21 * 864e5) continue;
        const s = sansAccents(texte).toLowerCase();
        if (!RE_METIER.test(s) && !/parlementaire/.test(s)) continue;
        if (!RE_OFFRE.test(s)) continue;
        const ext = (post.record?.external?.uri ?? post.embed?.external?.uri ?? post.embed?.record?.uri ?? null);
        const lien = ext ?? ("https://bsky.app/profile/" + auteur + "/post/" + (post.uri ?? "").split("/").pop());
        const titre = texte.slice(0, 290) || "Offre relayée sur Bluesky";
        const fp = fingerprint(titre, lien);
        if (!vues.has(fp)) vues.set(fp, enrichir({
          fingerprint: fp,
          titre: titre,
          description: texte.slice(0, 2000),
          source_url: lien.slice(0, 990),
          source_connector: "bluesky",
          source_raw: JSON.stringify({ auteur, date: creer }).slice(0, 5000),
          statut: "active",
          review_status: "pending",
          review_note: "Relayée sur Bluesky par @" + auteur,
        }, texte));
      }
      await dormir(2500);
    } catch (e) { console.log("« " + q + " » : ignoré (" + String(e.message).slice(0, 60) + ")"); }
  }

  console.log(vues.size + " offre(s) candidate(s) sur Bluesky.");
  if (!vues.size) return;
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
  console.log("Offres Bluesky déposées en revue.");
})().catch((e) => { console.error(e.message); process.exit(1); });

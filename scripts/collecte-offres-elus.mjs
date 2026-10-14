// DataParl' Jobs — recherche d'offres sur les sites personnels des élus.
// Deux passes : fiche institutionnelle (site perso référencé) puis accueil du
// site + pages emploi. L'élu et la chambre viennent de la base data : les
// offres partent déjà au format standard. Rotation 120 élus/run.
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;
const DATA_URL = process.env.DATA_SUPABASE_URL ?? "https://yuhqajaznizwmenmyzms.supabase.co";
const DATA_KEY = process.env.DATA_SUPABASE_KEY;

const PAR_RUN = 120;
const UA = "DataParlBot/1.0 (+https://www.dataparl.fr)";
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

const sansAccents = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const RE_PARLEMENTAIRE = /(collaborateur|collaboratrice|assistant|assistante|attache|attachee)[^a-z]{0,6}(e\)?\s)?\s?parlementaire/;

const { createHash } = await import("crypto");
const fingerprint = (titre, url) => createHash("sha256").update(sansAccents(titre).replace(/\s+/g, " ").trim() + "|" + url).digest("hex");

const liens = (html, base) => {
  const out = [];
  const re = /<a[^>]+href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const texte = m[2].replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    try { out.push({ href: new URL(m[1], base).toString(), texte }); } catch {}
  }
  return out;
};

const texteTitres = (html) =>
  (html.match(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/gi) ?? [])
    .map((h) => h.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim())
    .filter(Boolean);

(async () => {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY || !DATA_KEY) throw new Error("Secrets manquants");

  const rP = await fetch(
    DATA_URL + "/rest/v1/parlementaires?select=slug,prenom,nom,chambre,url_officielle&actif=eq.true&order=slug.asc&limit=2000",
    { headers: { apikey: DATA_KEY } }
  );
  if (!rP.ok) throw new Error("parlementaires : HTTP " + rP.status);
  const parlementaires = await rP.json();
  console.log(parlementaires.length + " parlementaires actifs.");

  const jour = new Date().getUTCDay();
  const tranche = parlementaires.slice(jour * PAR_RUN, (jour + 1) * PAR_RUN);
  console.log("Tranche du jour : " + tranche.length + " élus.");

  const CHAMBRES = { assemblee: "an", senat: "senat", europarl: "pe", europeen: "pe" };
  const vues = new Map();
  let sitesPersoTrouves = 0;

  for (const p of tranche) {
    try {
      const fiche = await fetch(p.url_officielle, { headers: { "User-Agent": UA } }).then((r) => r.text());
      const exterieurs = liens(fiche, p.url_officielle).filter((l) =>
        l.href.startsWith("http") &&
        !/assemblee-nationale\.fr|senat\.fr|europarl\.europa\.eu|youtube\.|twitter\.|x\.com|facebook\.|instagram\.|linkedin\.|vimeo\.|dailymotion\.|flickr\.|\.gouv\.fr|wikipedia\./.test(l.href)
      );
      const perso = exterieurs.find((l) => /^https?:\/\/(?!www\.)?([a-z0-9-]+\.)?[a-z0-9-]+\.[a-z]{2,}/.test(l.href) && l.href.split("/").length > 2);
      if (!perso) continue;
      sitesPersoTrouves++;

      const pages = [perso.href];
      const accueil = await fetch(perso.href, { headers: { "User-Agent": UA } }).then((r) => r.text());
      const pagesEmploi = liens(accueil, perso.href)
        .filter((l) => /recrut|emploi|hiring|join|rejoindre|travailler/.test(sansAccents(l.href + " " + l.texte)))
        .slice(0, 2)
        .map((l) => l.href);
      pages.push(...pagesEmploi);

      for (const url of pages) {
        const html = url === perso.href ? accueil : await fetch(url, { headers: { "User-Agent": UA } }).then((r) => r.text()).catch(() => "");
        if (!html) continue;
        const titres = texteTitres(html);
        const annonces = titres.filter((t) => RE_PARLEMENTAIRE.test(sansAccents(t)));
        const contientParlementaire = /parlementaire/.test(sansAccents(html));
        if (!annonces.length && !(contientParlementaire && /recrutement|offre d emploi|poste/.test(sansAccents(html)))) continue;
        const titreRetenu = annonces[0] ?? ("Offre sur le site de " + p.prenom + " " + p.nom);
        const fp = fingerprint(titreRetenu, url);
        if (!vues.has(fp)) vues.set(fp, {
          fingerprint: fp,
          titre: titreRetenu.slice(0, 290),
          description: "",
          source_url: url.slice(0, 990),
          source_connector: "site-elu",
          parlementaire_slug: p.slug,
          elu_prenom: p.prenom,
          elu_nom: p.nom,
          chambre: CHAMBRES[p.chambre] ?? null,
          statut: "active",
          review_status: "pending",
          review_note: "Détectée sur le site personnel de " + p.prenom + " " + p.nom,
        });
      }
      await dormir(1500);
    } catch (e) { console.log(p.slug + " : ignoré (" + String(e.message).slice(0, 60) + ")"); }
  }
  console.log(sitesPersoTrouves + " sites personnels parcourus, " + vues.size + " offre(s) candidate(s).");

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
  console.log("Offres déposées en revue.");
})().catch((e) => { console.error(e.message); process.exit(1); });

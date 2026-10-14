// Publication automatique du Daily via l'API Buffer (GraphQL, api.buffer.com).
// Zéro geste quotidien. Signé DataParl' — jamais de nom personnel.

const AUJOURDHUI = new Date().toISOString().slice(0, 10); // UTC
const dateTitre = (iso) => new Date(iso + "T12:00:00Z").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });

const gabarits = [
  (t, a, s) => t + " mouvements dans les équipes parlementaires : " + a + " à l'Assemblée, " + s + " au Sénat. Qui a rejoint qui ? Tout est là 👇",
  () => "Un(e) collaborateur(-trice) a changé d'équipe aujourd'hui. Lequel ou laquelle — et pour quel élu ? Réponse dans le Daily 👇",
  () => "Le point du matin sur les équipes parlementaires est en ligne 👇",
  (t, a, s) => "Aujourd'hui au Parlement : " + a + " à l'Assemblée, " + s + " au Sénat. Détail chambre par chambre 👇",
  () => "Qui travaille pour vos élus ? La réponse du jour, tirée des listes officielles 👇",
  () => "Les listes officielles des collaborateurs parlementaires ont été mises à jour : voici qui arrive, qui part 👇",
  (t, a, s, d) => "Daily #Parlement du " + d + " 📋 Les mouvements du jour, vérifiés à la source 👇",
  (t, a, s) => "Côté Assemblée : " + a + " mouvements aujourd'hui. Côté Sénat : " + s + ". Le détail 👇",
  (t) => "+" + t + " parcours reconstitués aujourd'hui. L'historique complet depuis 2015 👇",
  (t, a, s, d) => "Mouvements de collaborateurs parlementaires du " + d + " : arrivées, départs, transferts. Source : listes officielles 👇",
];
const gabarit = gabarits[(Number(AUJOURDHUI.slice(8, 10)) - 1) % gabarits.length];
const hashtags = "\n\n#AssembléeNationale #Sénat #Parlement #transparence";

const gql = async (token, query, variables) => {
  const r = await fetch("https://api.buffer.com", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify(variables ? { query, variables } : { query }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error("Buffer GraphQL: HTTP " + r.status + " " + JSON.stringify(j).slice(0, 300));
  if (j.errors?.length) throw new Error("Buffer GraphQL: " + j.errors.map((e) => e.message).join(" ; ").slice(0, 300));
  return j.data;
};

(async () => {
  const token = process.env.BUFFER_ACCESS_TOKEN || process.env.Dataparl_buffer_api;
  if (!token) throw new Error("Secret Buffer introuvable");

  const page = await fetch(process.env.DAILY_BASE + "/" + AUJOURDHUI).then((r) => r.text());
  const total = parseInt((page.match(/(\d+)\s+mouvements?/) || [])[1] ?? "0", 10);
  if (!total) { console.log("Aucun mouvement publié aujourd'hui — rien à publier."); return; }
  const an = (page.match(/(\d+) à l'Assemblée/) || [])[1] ?? "?";
  const senat = (page.match(/(\d+) au Sénat/) || [])[1] ?? "?";

  const org = await gql(token, "query { account { organizations { id name } } }");
  const orgId = org.account.organizations[0]?.id;
  if (!orgId) throw new Error("Aucune organisation Buffer trouvée");
  const reqCanaux = 'query { channels(input: { organizationId: "' + orgId + '" }) { id name service } }';
  const chans = await gql(token, reqCanaux);
  const liste = chans.channels ?? [];
  console.log("Canaux Buffer : " + liste.map((c) => c.service + " (" + c.id + ")").join(", "));
  const px = liste.find((c) => /twitter/i.test(c.service));
  const pb = liste.find((c) => /bluesky/i.test(c.service));
  if (!px || !pb) throw new Error("Connecte X et Bluesky dans Buffer (canaux vus : " + liste.map((c) => c.service).join(", ") + ")");

  // Anti-doublon : on cherche les LIENS COURTS exacts (pas la date seule),
  // pour ne pas être bloqué par une idée ou un brouillon qui mentionne la date.
  const liens = ["/l/daily-x/" + AUJOURDHUI, "/l/daily-bsky/" + AUJOURDHUI];
  try {
    const reqPosts = 'query { posts(input: { organizationId: "' + orgId + '" }) { edges { node { text status } } } }';
    const posts = await gql(token, reqPosts);
    const textes = (posts.posts?.edges ?? []).map((e) => (e.node?.text ?? ""));
    const bloque = textes.filter((x) => liens.some((l) => x.includes(l)));
    if (bloque.length) { console.log("Posts existants contenant les liens du jour (" + bloque.length + ") — ex : " + bloque[0].slice(0, 80)); console.log("Le Daily d'aujourd'hui est déjà présent — on s'arrête."); return; }
    console.log("Anti-doublon : aucun post avec les liens du jour. " + textes.length + " posts examinés.");
  } catch (e) { console.log("Anti-doublon ignoré (" + String(e.message).slice(0, 100) + ")"); }

  const midiUTC = new Date(AUJOURDHUI + "T10:00:00.000Z").getTime();
  const dans2h = Date.now() + 2 * 60 * 60 * 1000;
  const dueAt = new Date(Math.max(midiUTC, dans2h)).toISOString();
  console.log("Publication programmée pour : " + dueAt);
  const MUT = "mutation CreateScheduledPost($input: CreatePostInput!) { createPost(input: $input) { __typename ... on PostActionSuccess { post { id text dueAt } } ... on MutationError { message } } }";
  const publier = async (canal, reseau, lien) => {
    const texte = gabarit(total, an, senat, dateTitre(AUJOURDHUI)) + hashtags + "\n" + lien;
    const m = await gql(token, MUT, { input: { text: texte, channelId: canal.id, schedulingType: "automatic", mode: "customScheduled", dueAt } });
    const out = m.createPost;
    if (out?.post?.id) console.log("Programmé sur " + reseau + " (" + out.post.id + ") → " + lien);
    else throw new Error("Buffer (" + reseau + "): " + (out?.message ?? JSON.stringify(out).slice(0, 200)));
  };

  // NB : liens[] sert uniquement à l'anti-doublon ("/l/daily-x/…" est aussi
  // une sous-chaîne des anciens posts "/l/l/daily-x/…"). Pour l'URL, on
  // recompose LIENS_BASE + "/daily-x/…" sans doubler le préfixe "/l/".
  await publier(px, "x", process.env.LIENS_BASE + "/daily-x/" + AUJOURDHUI);
  await publier(pb, "bluesky", process.env.LIENS_BASE + "/daily-bsky/" + AUJOURDHUI);
  console.log("Daily programmé sur X et Bluesky via Buffer (GraphQL).");
})().catch((e) => { console.error(e.message); process.exit(1); });
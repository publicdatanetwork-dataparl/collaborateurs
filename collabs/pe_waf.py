"""Contournement du WAF du site du Parlement européen pour le suivi PE.

Depuis septembre 2026, www.europarl.europa.eu répond aux requêtes automatisées
par un défi JavaScript AWS WAF (HTTP 202). L'API open data
data.europarl.europa.eu n'est pas filtrée mais n'expose pas les assistants.

Ce module fournit un transport alternatif pour collabs.sources.europarl :
les pages sont chargées dans un vrai navigateur (Playwright/Chromium, profil
persistant) qui exécute le défi JavaScript comme le ferait un visiteur. Le
cookie de défi (aws-waf-token) est ensuite réutilisé pour toutes les pages de
la session, avec le délai de politesse habituel (EP_DELAY_SECONDS).

Utilisation (à la place de `python -m collabs`) :

    pip install -r requirements.txt playwright
    playwright install chromium
    python -m collabs.pe_waf run --chambre europarl --dry-run
    python -m collabs.pe_waf run --chambre europarl

Sans Playwright (import impossible), le module retombe sur le transport HTTP
ordinaire : le diagnostic de collabs s'applique alors tel quel.

Le profil du navigateur est conservé dans ~/.cache/dataparl-pe-chromium pour
ne pas rejouer le défi à chaque exécution. Le navigateur ne tourne que le
temps de la collecte (aucun port n'écoute sur le réseau local).
"""

from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlencode

PROFIL = os.environ.get("PE_WAF_PROFIL", os.path.expanduser("~/.cache/dataparl-pe-chromium"))
DELAI_DEFI = float(os.environ.get("PE_WAF_TIMEOUT_DEFI", "20"))
MARQUEUR_DEFI = ("JavaScript is disabled", "verify that you're not a robot", "x-amzn-waf")


class Reponse:
    """Équivalent minimal de requests.Response pour le pipeline."""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


class TransportPlaywright:
    """Un seul navigateur, un seul contexte, pour toute la collecte."""

    def __init__(self):
        from playwright.sync_api import sync_playwright  # noqa: import différé, optionnel
        self._pw = sync_playwright().start()
        self._nav = self._pw.chromium.launch_persistent_context(
            PROFIL,
            headless=True,
            locale="en",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._nav.new_page()
        self._vivant = True

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> Reponse:
        cible = url + (("?" + urlencode(params)) if params else "")
        self._page.goto(cible, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + DELAI_DEFI
        while True:
            html = self._page.content()
            if self._page.url != "about:blank" and not any(m in html for m in MARQUEUR_DEFI):
                return Reponse(200, html)
            if time.monotonic() > deadline:
                return Reponse(202, html)
            time.sleep(0.5)

    def fermer(self):
        if self._vivant:
            self._vivant = False
            try:
                self._nav.close()
            finally:
                self._pw.stop()


_transport: TransportPlaywright | None = None


def get(session, url: str, **kwargs) -> Reponse:
    """Signature compatible avec collabs.http.get, utilisée par la source PE.

    Essaie d'abord le transport HTTP ordinaire (rapide, et le site peut
    rouvrir aux IP non datacenters) ; au premier défi WAF, bascule sur
    le navigateur pour le reste de l'exécution.
    """
    global _transport
    if _transport is None:
        try:
            r = session.get(url, **kwargs)
            if getattr(r, "status_code", None) != 202 and not any(
                m in (getattr(r, "text", "") or "")[:400] for m in MARQUEUR_DEFI
            ):
                return r
        except Exception:
            pass
        print("pe_waf : défi WAF détecté, bascule sur Playwright…", file=sys.stderr)
        try:
            _transport = TransportPlaywright()
        except ImportError:
            print(
                "pe_waf : Playwright absent (pip install playwright && "
                "playwright install chromium) ; le site reste bloqué.",
                file=sys.stderr,
            )
            raise
    return _transport.get(url, kwargs.get("params"), kwargs.get("headers"))


def main(argv: list[str]) -> int:
    """`python -m collabs.pe_waf <args de collabs>` : patche la source puis délègue au CLI."""
    from collabs import cli
    from collabs.sources import europarl

    europarl.get = get  # la source importe `get` dans son propre espace de noms
    try:
        return cli.main(argv)
    finally:
        if _transport is not None:
            _transport.fermer()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

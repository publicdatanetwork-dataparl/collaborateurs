"""Diagnostic réseau des sources : `python -m collabs diag [chambre ...]`.

Affiche, pour chaque URL interrogée, le code HTTP, le type de contenu, la
taille, un extrait et ce que les parsers en tirent. Sert à comprendre ce que
voit un runner GitHub Actions quand une source change ou bloque.
"""

from __future__ import annotations

from .http import TIMEOUT, make_session
from .sources import europarl

EP_URLS = [
    ("search/advanced FR leg", f"{europarl.SITE}/meps/en/search/advanced?countryCode=FR&leg={europarl.LEGISLATURE}", europarl.HTML_HEADERS),
    ("search/advanced FR", f"{europarl.SITE}/meps/en/search/advanced?countryCode=FR", europarl.HTML_HEADERS),
    ("full-list xml", f"{europarl.SITE}/meps/en/full-list/xml", {"Accept": "application/xml,text/xml,*/*"}),
    ("full-list xml FR", f"{europarl.SITE}/meps/en/full-list/xml/FR", {"Accept": "application/xml,text/xml,*/*"}),
    ("full-list all", f"{europarl.SITE}/meps/en/full-list/all", europarl.HTML_HEADERS),
    ("assistants Aubry", f"{europarl.SITE}/meps/en/197533/HOME/assistants", europarl.HTML_HEADERS),
]


def _probe(session, label, url, headers):
    try:
        r = session.get(url, headers=headers, timeout=TIMEOUT)
    except Exception as e:
        print(f"- {label}: EXCEPTION {type(e).__name__}: {e}")
        return None
    snippet = r.text[:300].replace("\n", " ")
    hist = " -> ".join(str(h.status_code) for h in r.history)
    print(f"- {label}: HTTP {r.status_code}{' (via ' + hist + ')' if hist else ''} "
          f"{r.headers.get('content-type', '?')} {len(r.content)} octets, url finale {r.url}")
    print(f"    extrait: {snippet!r}")
    return r


def diag_europarl(session):
    print("== europarl")
    for label, url, headers in EP_URLS:
        r = _probe(session, label, url, headers)
        if r is None or not r.content:
            continue
        if "xml" in label:
            try:
                print(f"    -> {len(europarl.parse_full_list_xml(r.content))} MEPs français (XML)")
            except Exception as e:
                print(f"    -> XML illisible : {e}")
        elif "assistants" in label:
            print(f"    -> assistants : {europarl.parse_assistants_page(r.text)}")
        else:
            print(f"    -> {len(europarl.parse_search_page(r.text))} cartes MEP")


def main(chambres):
    session = make_session()
    if "europarl" in chambres:
        diag_europarl(session)
    return 0

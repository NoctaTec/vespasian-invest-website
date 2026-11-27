#!/usr/bin/env python3
"""SEO-Pflege vor jedem Content-Push (alle sechs Vespasian-/NoctaTec-Repos).

Aufruf im Repo-Stammverzeichnis, nach dem Bearbeiten und VOR dem Commit:
    python3 _bau/seo_pflege.py            # aktualisiert sitemap.xml, llms.txt, prüft robots.txt
    python3 _bau/seo_pflege.py --pruefen  # ändert nichts, Exit 1 wenn etwas fehlt

Was es tut
1. sitemap.xml: Aufgenommen wird jede HTML-Seite, deren canonical auf sich selbst zeigt
   und die kein noindex hat. Reihenfolge und lastmod bestehender Einträge bleiben,
   neue Seiten kommen ans Ende, entfernte oder auf noindex gesetzte fliegen raus.
   lastmod wird auf heute gesetzt, wenn die Datei gegenüber dem letzten Commit
   geändert oder neu ist (git diff HEAD + nicht versionierte Dateien).
2. llms.txt: Jede Seite aus der Sitemap, die dort noch nicht verlinkt ist (außer
   Datenschutz/Impressum), wird unter „## Weitere Seiten“ mit Titel und
   Beschreibung ergänzt. Danach kann die Zeile von Hand in den passenden Abschnitt
   verschoben werden.
3. robots.txt: muss genau „Sitemap: https://<CNAME>/sitemap.xml“ enthalten,
   fehlt die Zeile, wird sie ergänzt.
"""
import datetime
import html
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path.cwd()
HEUTE = datetime.date.today().isoformat()
PRUEFEN = "--pruefen" in sys.argv
AUSNAHMEN_LLMS = ("datenschutz", "impressum")
probleme, aenderungen = [], []


def lesen(p):
    return p.read_text(encoding="utf-8")


def schreiben(p, text):
    if not p.exists() or lesen(p) != text:
        aenderungen.append(p.name)
        if not PRUEFEN:
            p.write_text(text, encoding="utf-8")


def host():
    cname = ROOT / "CNAME"
    if not cname.exists():
        sys.exit("Kein CNAME im aktuellen Verzeichnis. Bitte im Repo-Stamm ausführen.")
    return lesen(cname).strip()


def geaenderte_dateien():
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        except Exception:
            return []
    namen = git("diff", "--name-only", "HEAD") + git("ls-files", "--others", "--exclude-standard")
    return {n.strip() for n in namen if n.strip()}


def seiten(basis):
    """Liefert {url: (relativer_pfad, titel, beschreibung)} aller indexierbaren Seiten."""
    erg = {}
    for f in sorted(ROOT.rglob("*.html")):
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith((".", "_")) or "/_" in rel or "/." in rel:
            continue
        t = lesen(f)
        if re.search(r'<meta[^>]+name="robots"[^>]+content="[^"]*noindex', t, re.I):
            continue
        m = re.search(r'<link rel="canonical" href="([^"]+)"', t)
        if not m:
            continue
        if rel == "index.html":
            eigene = basis + "/"
        elif rel.endswith("/index.html"):
            eigene = f"{basis}/{rel[:-len('index.html')]}"
        else:
            eigene = f"{basis}/{rel}"
        if m.group(1) != eigene:
            continue
        titel = re.search(r"<title>(.*?)</title>", t, re.S)
        besch = re.search(r'<meta name="description" content="([^"]*)"', t)
        erg[eigene] = (rel,
                       html.unescape(titel.group(1).strip()) if titel else eigene,
                       html.unescape(besch.group(1).strip()) if besch else "")
    return erg


def sitemap(basis, alle, geaendert):
    pfad = ROOT / "sitemap.xml"
    alt = []
    if pfad.exists():
        alt = re.findall(r"<loc>([^<]+)</loc>(?:<lastmod>([^<]+)</lastmod>)?", lesen(pfad))
    eintraege, gesehen = [], set()
    for loc, lastmod in alt:
        if loc in alle and loc not in gesehen:
            eintraege.append([loc, lastmod or HEUTE]); gesehen.add(loc)
    for loc in alle:
        if loc not in gesehen:
            eintraege.append([loc, HEUTE]); gesehen.add(loc)
    for e in eintraege:
        if alle[e[0]][0] in geaendert:
            e[1] = HEUTE
    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    zeilen += [f"  <url><loc>{l}</loc><lastmod>{d}</lastmod></url>" for l, d in eintraege]
    zeilen.append("</urlset>")
    schreiben(pfad, "\n".join(zeilen) + "\n")
    return [l for l, _ in eintraege]


def llms(urls, alle):
    pfad = ROOT / "llms.txt"
    if not pfad.exists():
        probleme.append("llms.txt fehlt")
        return
    text = lesen(pfad)
    fehlend = [u for u in urls
               if not any(x in u for x in AUSNAHMEN_LLMS)
               and f"({u})" not in text and f"]({u}" not in text and u != urls[0]]
    if not fehlend:
        return
    if "## Weitere Seiten" not in text:
        text = text.rstrip("\n") + "\n\n## Weitere Seiten\n"
    neu = ""
    for u in fehlend:
        _, titel, besch = alle[u]
        titel = re.split(r"\s+[|·–-]\s+", titel)[0]
        neu += f"\n- [{titel}]({u})" + (f": {besch}" if besch else "")
    if text.rstrip("\n").endswith("## Weitere Seiten"):
        neu = "\n" + neu
    text = text.rstrip("\n") + neu + "\n"
    schreiben(pfad, text)
    probleme.append("llms.txt ergänzt, bitte Zeilen ggf. in den passenden Abschnitt verschieben: " + ", ".join(fehlend))


def robots(basis):
    pfad = ROOT / "robots.txt"
    zeile = f"Sitemap: {basis}/sitemap.xml"
    text = lesen(pfad) if pfad.exists() else "User-agent: *\nAllow: /\n"
    if zeile not in text.splitlines():
        text = re.sub(r"(?im)^Sitemap:.*\n?", "", text).rstrip("\n") + f"\n\n{zeile}\n"
        schreiben(pfad, text)
        probleme.append("robots.txt: Sitemap-Zeile korrigiert")


def main():
    basis = "https://" + host()
    alle = seiten(basis)
    if basis + "/" not in alle:
        probleme.append("Startseite hat kein selbstbezogenes canonical")
    urls = sitemap(basis, alle, geaenderte_dateien())
    llms(urls, alle)
    robots(basis)
    print(f"{host()}: {len(urls)} Seiten in der Sitemap")
    for a in aenderungen:
        print(("würde ändern: " if PRUEFEN else "geändert: ") + a)
    for p in probleme:
        print("Hinweis: " + p)
    if PRUEFEN and aenderungen:
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
digest_roi.py — Digest ROI hebdomadaire (audit Fable, reco #2).

POURQUOI : la boucle go -> fait -> paye existe et fonctionne (suivi_go.py,
feedback.py) mais elle etait DORMANTE : rien ne resumait "cette semaine, X go
lances, Y faits, Z euros confirmes". Sans ce compteur, le pipeline optimise
"faire des moves" mais ne montre jamais si ca RAPPORTE vraiment.

REGLE DURE (anti-hallu, coherente avec tout le pipeline) : le montant "confirme"
ne vient QUE des go au statut "paye" (donc deja verrouille par confirme_par_adam
ou un event feedback — voir suivi_go.py). Ce module ne fait AUCUNE inference sur
un € : il compte ce qui est deja prouve ailleurs. Le "potentiel estime" (champ
meta du move, ex "2h - 300EUR") est affiche SEPAREMENT, etiquete clairement
comme non confirme -> jamais melange au montant reel.

Stdlib pure. Lecture seule sur data/go_suivi.json et briefs/*.

REVISION (audit Fable 5, retour visuel sur le 1er envoi reel) :
  1. Accents corriges dans le texte Telegram (le repli ASCII console reste
     intact, c'est un souci d'AFFICHAGE console uniquement, pas d'envoi).
  2. MECE : "lances" est desormais le TOTAL, la repartition (faits/payes/
     en cours/dormants) est presentee comme un SOUS-NIVEAU de ce total, plus
     jamais une addition qui donne l'impression d'un decompte double.
  3. Chaque go en cours est nomme (nom d'affichage produit via config_projets,
     ex "BrandPulse" au lieu de "serp-scraper") : substance pilotable, pas
     juste un chiffre.
  4. "Cash-close" : le go le plus avance (le plus de commits) cite son propre
     do_now (le texte du move, deja ecrit par le radar) comme prochain pas —
     JAMAIS un pas invente ici, uniquement une citation d'un champ existant.
  5. Le montant ESTIME (champ meta du move, ex "1h - 300EUR") est affiche a
     part, etiquete "estime, pas confirme", UNIQUEMENT si un montant y est
     detectable (sinon on ne l'affiche pas — pas de "0EUR" invente).
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
GO_SUIVI = DATA / "go_suivi.json"

# config_projets : optionnel, degrade proprement si absent (jamais bloquant).
try:
    import config_projets
except Exception:
    config_projets = None

JOURS_FENETRE = 7  # digest = "cette semaine"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _parse_date(s: str):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def _nom_projet(slug: str) -> str:
    """Nom d'affichage produit ('BrandPulse') pour un slug technique
    ('serp-scraper'). Repli sur le slug brut si config_projets est absent ou
    ne connait pas ce projet — jamais d'exception, jamais de nom invente."""
    if not slug:
        return "?"
    if config_projets is not None:
        try:
            nom = config_projets.nom_affichage_de(slug)
            if nom:
                return nom
        except Exception:
            pass
    return slug


def _extraire_montant_euros(texte: str) -> float:
    """Extrait un montant en euros d'un champ 'montant' TEXTE DE CONFIANCE
    (Adam a tape "paye N 50EUR" lui-meme dans Telegram — c'est verrouille par
    confirme_par_adam/event feedback en amont dans suivi_go.py). Ici le premier
    chiffre trouve EST le montant, sans ambiguite possible sur ce champ precis.
    Best-effort SANS inventer : si rien de numerique n'est trouve, renvoie 0.0."""
    if not texte:
        return 0.0
    m = re.search(r"[\d]+(?:[.,]\d+)?", str(texte))
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", "."))
    except Exception:
        return 0.0


# Marqueur monetaire explicite : euro, EUR, ou "€" — insensible a la casse.
_RE_MARQUEUR_EURO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|eur\b|euros?\b)", re.IGNORECASE)


def _extraire_montant_estime(texte: str) -> float:
    """Extrait un montant UNIQUEMENT si un marqueur monetaire explicite
    l'accompagne (€, EUR, euro). Champ 'meta' du move : texte libre ECRIT PAR
    LE LLM (ex '1h - positionnement', '2h - 300EUR') qui melange SOUVENT une
    duree ('1h', '2h') avec un eventuel montant. Contrairement a
    _extraire_montant_euros (champ 'montant' de confiance, tape par Adam), ici
    on ne peut PAS supposer qu'un chiffre nu est un montant — sinon '1h'
    devient a tort '1€' (bug reel corrige suite a l'audit visuel Fable 5 sur
    le 1er envoi). Renvoie 0.0 si aucun marqueur monetaire n'est present :
    c'est le signal explicite 'pas de montant estime detectable', jamais
    invente."""
    if not texte:
        return 0.0
    m = _RE_MARQUEUR_EURO.search(str(texte))
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(",", "."))
    except Exception:
        return 0.0


def calculer_digest(jours: int = JOURS_FENETRE) -> dict:
    """Compte les go des `jours` derniers jours, par statut. Renvoie un dict
    factuel : rien n'est devine, tout vient de go_suivi.json (lui-meme derive
    de la hierarchie de preuves de suivi_go.py — confirmation Adam > event >
    commit > LLM, avec 'paye' impossible a halluciner)."""
    snap = _load(GO_SUIVI, {"go": []})
    tous = snap.get("go", [])
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)

    fenetre = []
    for g in tous:
        d = _parse_date(g.get("date_lancement"))
        if d and d >= seuil:
            fenetre.append(g)

    nb_lances = len(fenetre)
    nb_fait = sum(1 for g in fenetre if g.get("statut") in ("fait", "paye"))
    nb_paye = sum(1 for g in fenetre if g.get("statut") == "paye")
    nb_dormant = sum(1 for g in fenetre if g.get("statut") == "dormant")
    en_cours = [g for g in fenetre if g.get("statut") in ("lance", "projet_bouge")]
    dormants = [g for g in fenetre if g.get("statut") == "dormant"]
    nb_en_cours = len(en_cours)

    total_confirme = sum(
        _extraire_montant_euros(g.get("montant"))
        for g in fenetre if g.get("statut") == "paye"
    )

    payes_detail = [
        {"projet": _nom_projet(g.get("projet", "")), "montant": g.get("montant", "")}
        for g in fenetre if g.get("statut") == "paye"
    ]
    en_cours_detail = [
        {"projet": _nom_projet(g.get("projet", "")),
         "commits": g.get("commits_depuis_go", 0) or 0,
         "do_now": (g.get("do_now") or "").strip()}
        for g in en_cours
    ]
    dormants_detail = [
        {"projet": _nom_projet(g.get("projet", ""))} for g in dormants
    ]

    # CASH-CLOSE (audit Fable, point 4) : le go en_cours le plus avance (le plus
    # de commits depuis le lancement) cite son PROPRE do_now comme prochain pas.
    # Jamais un pas invente : uniquement une citation d'un champ deja ecrit par
    # le radar au moment de sa creation.
    plus_avance = None
    if en_cours_detail:
        candidat = max(en_cours_detail, key=lambda x: x["commits"])
        if candidat["do_now"]:
            plus_avance = candidat

    # POTENTIEL ESTIME (audit Fable, point 5) : somme des € detectables dans le
    # champ 'meta' des go en cours (ex "2h - 300EUR"). EXIGE un marqueur
    # monetaire explicite (_extraire_montant_estime, pas _extraire_montant_euros)
    # -> "1h - positionnement" ne donne plus a tort '1€' (le '1' de '1h' etait
    # pris pour un montant avant ce correctif). Affiche SEPAREMENT du montant
    # confirme, jamais mele. Si aucun meta ne porte de marqueur monetaire, on
    # n'affiche RIEN plutot que d'inventer un montant.
    potentiel_estime = sum(
        _extraire_montant_estime(g.get("meta", ""))
        for g in en_cours
        if _extraire_montant_estime(g.get("meta", "")) > 0
    )

    return {
        "jours": jours,
        "nb_lances": nb_lances,
        "nb_fait": nb_fait,
        "nb_paye": nb_paye,
        "nb_dormant": nb_dormant,
        "nb_en_cours": nb_en_cours,
        "total_confirme_euros": total_confirme,
        "payes_detail": payes_detail,
        "en_cours_detail": en_cours_detail,
        "dormants_detail": dormants_detail,
        "plus_avance": plus_avance,
        "potentiel_estime_euros": potentiel_estime,
    }


def formater_digest(jours: int = JOURS_FENETRE) -> str:
    """Message Telegram HTML. Distingue TOUJOURS le prouve (paye confirme) du
    reste. Si aucun go cette semaine, message honnete ('rien de neuf'), pas de
    zero deguise en succes ni en echec.

    Structure MECE (point 2) : "lances" est le TOTAL en tete, la repartition
    (faits/payes/en cours/dormants) vient ensuite comme sous-niveau de CE
    total — jamais une 2e addition qui donne l'impression d'un double compte."""
    d = calculer_digest(jours)

    if d["nb_lances"] == 0:
        return (
            f"📊 <b>The Wire — bilan {jours} jours</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            "<i>Aucun go lancé sur cette période. Réponds « go N » à un radar pour démarrer.</i>"
        )

    L = [
        f"📊 <b>The Wire — bilan {jours} jours</b>",
        "━━━━━━━━━━━━━━━",
        "",
        f"🚀 <b>{d['nb_lances']}</b> go lancé(s) → dont :",
        f"   ✅ {d['nb_fait']} fait(s) / shippé(s)",
    ]
    if d["nb_paye"] > 0:
        montant_str = f"{d['total_confirme_euros']:.0f}€" if d["total_confirme_euros"] > 0 else ""
        L.append(f"   💶 {d['nb_paye']} payé(s)" + (f" — <b>{montant_str} confirmés</b>" if montant_str else ""))
    else:
        L.append("   💶 0 payé confirmé pour l'instant")
    if d["nb_en_cours"] > 0:
        L.append(f"   🔨 {d['nb_en_cours']} en cours")
    if d["nb_dormant"] > 0:
        L.append(f"   💤 {d['nb_dormant']} dormant(s) — à relancer ou classer")

    # Detail nomme (point 3) : substance pilotable, pas juste un chiffre.
    if d["payes_detail"]:
        L.append("")
        L.append("<b>Payés :</b>")
        for p in d["payes_detail"]:
            L.append(f"   · {p['projet']} — {p['montant'] or '(montant non chiffré)'}")
    if d["en_cours_detail"]:
        L.append("")
        L.append("<b>En cours :</b>")
        for e in d["en_cours_detail"]:
            trace = f"{e['commits']} commit(s)" if e["commits"] else "pas encore de trace"
            L.append(f"   · {e['projet']} — {trace}")
    if d["dormants_detail"]:
        L.append("")
        L.append("<b>Dormants :</b>")
        for dm in d["dormants_detail"]:
            L.append(f"   · {dm['projet']}")

    # Cash-close (point 4) : le go le plus avance cite SON PROPRE do_now (deja
    # ecrit par le radar) comme prochain pas — rien d'invente ici.
    if d["plus_avance"]:
        L.append("")
        L.append(f"👉 <b>Le plus avancé</b> — {d['plus_avance']['projet']} : {d['plus_avance']['do_now']}")

    # Potentiel estime (point 5) : affiche a part, seulement si detectable,
    # jamais mele au montant confirme.
    if d["potentiel_estime_euros"] > 0:
        L.append("")
        L.append(f"<i>Potentiel estimé (non confirmé) sur les moves en cours : ~{d['potentiel_estime_euros']:.0f}€</i>")

    L.append("")
    if d["nb_paye"] == 0:
        L.append("<i>Aucun € confirmé cette semaine — ce n'est pas 0 valeur, c'est 0 CONFIRMÉ. "
                 "Tape « paye N &lt;montant&gt; » dès qu'un move rapporte.</i>")
    else:
        L.append("<i>Chiffres 100% prouvés : « payé » ne vient que de tes confirmations, jamais d'une supposition.</i>")

    return "\n".join(L)


def main() -> int:
    jours = JOURS_FENETRE
    if "--jours" in sys.argv:
        i = sys.argv.index("--jours")
        try:
            jours = int(sys.argv[i + 1])
        except Exception:
            pass
    txt = formater_digest(jours)
    ascii_safe = re.sub(r"</?[^>]+>", "", txt).encode("ascii", "replace").decode("ascii")
    print(ascii_safe)
    return 0


if __name__ == "__main__":
    sys.exit(main())

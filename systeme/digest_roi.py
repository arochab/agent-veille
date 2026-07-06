#!/usr/bin/env python3
"""
digest_roi.py - Digest ROI hebdomadaire (audit Fable, reco #2).

POURQUOI : la boucle go -> fait -> paye existe et fonctionne (suivi_go.py,
feedback.py) mais elle etait DORMANTE : rien ne resumait "cette semaine, X go
lances, Y faits, Z euros confirmes". Sans ce compteur, le pipeline optimise
"faire des moves" mais ne montre jamais si ca RAPPORTE vraiment.

REGLE DURE (anti-hallu, coherente avec tout le pipeline) : le montant "confirme"
ne vient QUE des go au statut "paye" (donc deja verrouille par confirme_par_adam
ou un event feedback - voir suivi_go.py). Ce module ne fait AUCUNE inference sur
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
     do_now (le texte du move, deja ecrit par le radar) comme prochain pas -
     JAMAIS un pas invente ici, uniquement une citation d'un champ existant.
  5. Le montant ESTIME (champ meta du move, ex "1h - 300EUR") est affiche a
     part, etiquete "estime, pas confirme", UNIQUEMENT si un montant y est
     detectable (sinon on ne l'affiche pas - pas de "0EUR" invente).
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

# TENUE A L'ECHELLE : au-dela de N lignes par section detaillee (payes / en cours /
# dormants), le surplus devient "... et K autres". Le bilan doit rester lisible en
# 20 secondes et < 3500 caracteres MEME avec 30 go - rien n'est perdu : tout reste
# entier dans go_suivi.json, seul l'AFFICHAGE est plafonne.
MAX_DETAIL_PAR_SECTION = 5


def esc(s) -> str:
    """Echappe le HTML pour Telegram (parse_mode=HTML). Duplique volontairement
    envoyer_telegram.esc() (meme logique a 3 lignes) plutot que de l'importer :
    envoyer_telegram.py importe DEJA digest_roi -> un import inverse creerait un
    cycle. Necessaire ici : do_now/projet/montant peuvent contenir du texte ecrit
    par le LLM (jury produit, vague 2B) - un '<' isole casserait le HTML envoye
    et ferait echouer TOUT le digest, pas juste ce champ."""
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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
    ne connait pas ce projet - jamais d'exception, jamais de nom invente."""
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
    (Adam a tape "paye N 50EUR" lui-meme dans Telegram - c'est verrouille par
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


# Marqueur monetaire explicite : euro, EUR, ou "€" - insensible a la casse.
_RE_MARQUEUR_EURO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|eur\b|euros?\b)", re.IGNORECASE)


def _extraire_montant_estime(texte: str) -> float:
    """Extrait un montant UNIQUEMENT si un marqueur monetaire explicite
    l'accompagne (€, EUR, euro). Champ 'meta' du move : texte libre ECRIT PAR
    LE LLM (ex '1h - positionnement', '2h - 300EUR') qui melange SOUVENT une
    duree ('1h', '2h') avec un eventuel montant. Contrairement a
    _extraire_montant_euros (champ 'montant' de confiance, tape par Adam), ici
    on ne peut PAS supposer qu'un chiffre nu est un montant - sinon '1h'
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


def _plafonner(items: list, tri=None) -> tuple:
    """TENUE A L'ECHELLE (20+ go sur la fenetre) : renvoie (tetes, k_caches) pour une
    section detaillee - les MAX_DETAIL_PAR_SECTION premieres entrees et le nombre
    d'entrees masquees. Le tri (optionnel, decroissant) choisit QUOI montrer en tete :
    les payes les plus gros, les en-cours les plus actifs. Sans tri, l'ordre d'origine
    est conserve. Aucune donnee n'est perdue : les caches sont COMPTES ('... et K
    autres') et restent entiers dans go_suivi.json."""
    tries = sorted(items, key=tri, reverse=True) if tri else list(items)
    return tries[:MAX_DETAIL_PAR_SECTION], max(0, len(tries) - MAX_DETAIL_PAR_SECTION)


def _couper_mot(texte: str, max_len: int = 200) -> str:
    """Raccourcit une CITATION (ex : le do_now du go le plus avance) a la limite de
    mot, sans la reformuler ni la denaturer - garde-fou pour que le message complet
    tienne sous les 3500 caracteres meme si un do_now est tres long. Rien n'est
    invente : c'est le texte reel, juste coupe proprement avec une ellipse."""
    t = (texte or "").strip()
    if len(t) <= max_len:
        return t
    coupe = t[:max_len]
    esp = coupe.rfind(" ")
    if esp >= 20:
        coupe = coupe[:esp]
    return coupe.rstrip(" ,;:-") + "…"


def _jours_go_vers_preuve(g: dict, statut_cible: str) -> float:
    """Jours ENTRE le lancement du go (date_lancement) et la preuve qui a fait
    passer son statut a statut_cible ('fait' ou 'paye'). None si le go n'est pas
    (ou plus) a ce statut, ou si une des deux dates est illisible.

    FACTUEL, ZERO inference : la date d'arrivee est preuves[-1]['date'] - dans
    suivi_go.py::_decider, exactement UNE branche elif ajoute une preuve avant de
    fixer le statut courant, donc la DERNIERE preuve de la liste est TOUJOURS
    celle qui a produit ce statut precis (confirmation Adam, event feedback, ou
    commit matche). Rien n'est devine : si preuves[] est vide/illisible -> None,
    jamais une duree inventee."""
    if g.get("statut") != statut_cible:
        return None
    d0 = _parse_date(g.get("date_lancement"))
    preuves = g.get("preuves") or []
    if not d0 or not preuves:
        return None
    d1 = _parse_date(preuves[-1].get("date"))
    if not d1:
        return None
    delta = (d1 - d0).total_seconds() / 86400.0
    return delta if delta >= 0 else None


def _mediane(valeurs: list) -> float:
    """Mediane simple, stdlib pure (pas de dependance a statistics.median pour
    rester coherent avec le reste du fichier). [] -> None."""
    if not valeurs:
        return None
    v = sorted(valeurs)
    n = len(v)
    mid = n // 2
    if n % 2 == 1:
        return v[mid]
    return (v[mid - 1] + v[mid]) / 2.0


def calculer_time_to_cash() -> dict:
    """Time-to-cash REEL (mission post-go) : jours MEDIANS go -> fait et go -> paye,
    calcules sur TOUT go_suivi.json (pas seulement la fenetre 7 jours du digest
    hebdo) - un go lance il y a 10 jours et paye hier doit compter, sinon la
    fenetre courte biaiserait vers les conversions rapides et mentirait sur le
    delai reel. AUCUNE inference d'argent : ce module ne compte que des DATES deja
    prouvees ailleurs (go_horodatage via date_lancement, confirmations/events via
    preuves[-1]['date'], memes sources que suivi_go.py). {} si aucun go 'fait' et
    aucun go 'paye' n'a de duree calculable (pas encore assez de recul)."""
    snap = _load(GO_SUIVI, {"go": []})
    tous = snap.get("go", [])
    delais_fait = [d for g in tous
                   for d in [_jours_go_vers_preuve(g, "fait")] if d is not None]
    delais_paye = [d for g in tous
                   for d in [_jours_go_vers_preuve(g, "paye")] if d is not None]
    return {
        "n_fait": len(delais_fait),
        "mediane_jours_fait": _mediane(delais_fait),
        "n_paye": len(delais_paye),
        "mediane_jours_paye": _mediane(delais_paye),
    }


def calculer_digest(jours: int = JOURS_FENETRE) -> dict:
    """Compte les go des `jours` derniers jours, par statut. Renvoie un dict
    factuel : rien n'est devine, tout vient de go_suivi.json (lui-meme derive
    de la hierarchie de preuves de suivi_go.py - confirmation Adam > event >
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
        # time-to-cash (mission post-go) : calcule sur TOUT go_suivi.json, pas la
        # fenetre - voir calculer_time_to_cash() pour le detail anti-biais.
        "time_to_cash": calculer_time_to_cash(),
    }


def formater_digest(jours: int = JOURS_FENETRE) -> str:
    """Message Telegram HTML. Distingue TOUJOURS le prouve (paye confirme) du
    reste. Si aucun go cette semaine, message honnete ('rien de neuf'), pas de
    zero deguise en succes ni en echec.

    Structure MECE (point 2) : "lances" est le TOTAL en tete, la repartition
    (faits/payes/en cours/dormants) vient ensuite comme sous-niveau de CE
    total - jamais une 2e addition qui donne l'impression d'un double compte."""
    d = calculer_digest(jours)

    if d["nb_lances"] == 0:
        return (
            f"📊 <b>The Wire - bilan {jours} jours</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            "<i>Aucun go lancé sur cette période. Réponds « go N » à un radar pour démarrer.</i>\n\n"
            "<i>- The Wire</i>"
        )

    # MECE (jury produit, vague 2B) : nb_fait INCLUT deja les payes (statut in
    # ("fait","paye"), calculer_digest ligne 182) - payes est un SOUS-ENSEMBLE de
    # faits, pas une categorie a cote. Affiche "fait" = shippe mais PAS (encore)
    # confirme paye, pour que les sous-lignes s'additionnent exactement au total
    # (jamais 5+3+8+3=19 pour 16 lances).
    nb_fait_non_paye = d["nb_fait"] - d["nb_paye"]
    montant_str = f"{d['total_confirme_euros']:.0f}€" if d["total_confirme_euros"] > 0 else ""
    L = [
        f"📊 <b>The Wire - bilan {jours} jours</b>",
        "━━━━━━━━━━━━━━━",
        "",
    ]
    if d["nb_lances"] < 4:
        # PETITS NOMBRES = UNE PHRASE (audit GTM) : un tableau de ventilation pour
        # 2-3 go, c'est de la comptabilite bureaucratique - a cette echelle, le
        # momentum se dit en une ligne humaine. La ventilation ne revient qu'a
        # partir de 4 go, quand elle aide vraiment a s'y retrouver. Meme rigueur
        # MECE : chaque segment est disjoint, la somme = le total.
        seg = []
        if d["nb_paye"] > 0:
            seg.append(f"{d['nb_paye']} payé" + ("s" if d["nb_paye"] > 1 else "")
                       + (f" (<b>{montant_str} confirmés</b>)" if montant_str else ""))
        if nb_fait_non_paye > 0:
            seg.append(f"{nb_fait_non_paye} shippé" + ("s" if nb_fait_non_paye > 1 else ""))
        if d["nb_en_cours"] > 0:
            seg.append(f"{d['nb_en_cours']} en cours qui bouge" + ("nt" if d["nb_en_cours"] > 1 else ""))
        if d["nb_dormant"] > 0:
            seg.append(f"{d['nb_dormant']} dormant" + ("s" if d["nb_dormant"] > 1 else ""))
        pluriel = "s" if d["nb_lances"] > 1 else ""
        L.append(f"🚀 <b>{d['nb_lances']}</b> go lancé{pluriel} cette semaine - " + " · ".join(seg) + ".")
    else:
        L.append(f"🚀 <b>{d['nb_lances']}</b> go lancé(s) → dont :")
        L.append(f"   ✅ {nb_fait_non_paye} shippé(s) (pas encore payé confirmé)")
        if d["nb_paye"] > 0:
            L.append(f"   💶 {d['nb_paye']} payé(s)" + (f" - <b>{montant_str} confirmés</b>" if montant_str else ""))
        else:
            L.append("   💶 0 payé confirmé pour l'instant")
        if d["nb_en_cours"] > 0:
            L.append(f"   🔨 {d['nb_en_cours']} en cours")
        if d["nb_dormant"] > 0:
            L.append(f"   💤 {d['nb_dormant']} dormant(s) - à relancer ou classer")

    # Detail nomme (point 3) : substance pilotable, pas juste un chiffre.
    # TENUE A L'ECHELLE : chaque section est plafonnee (top MAX_DETAIL_PAR_SECTION) -
    # payes tries par montant decroissant (le tri relit le champ 'montant' de confiance
    # via _extraire_montant_euros, fonction INCHANGEE), en cours par commits
    # decroissants, dormants dans l'ordre. Le surplus = une ligne "… et K autres".
    if d["payes_detail"]:
        tetes, k = _plafonner(d["payes_detail"],
                              tri=lambda p: _extraire_montant_euros(p["montant"]))
        L.append("")
        L.append("<b>Payés :</b>")
        for p in tetes:
            L.append(f"   · {esc(p['projet'])} - {esc(p['montant']) or '(montant non chiffré)'}")
        if k:
            L.append(f"   <i>… et {k} autre(s)</i>")
    if d["en_cours_detail"]:
        tetes, k = _plafonner(d["en_cours_detail"], tri=lambda e: e["commits"])
        L.append("")
        L.append("<b>En cours :</b>")
        for e in tetes:
            n_c = int(e["commits"] or 0)
            trace = (f"{n_c} commit" + ("s" if n_c > 1 else "")) if n_c else "pas encore de trace"
            L.append(f"   · {esc(e['projet'])} - {trace}")
        if k:
            L.append(f"   <i>… et {k} autre(s)</i>")
    if d["dormants_detail"]:
        tetes, k = _plafonner(d["dormants_detail"])
        L.append("")
        L.append("<b>Dormants :</b>")
        for dm in tetes:
            L.append(f"   · {esc(dm['projet'])}")
        if k:
            L.append(f"   <i>… et {k} autre(s)</i>")

    # Cash-close (point 4) : le go le plus avance cite SON PROPRE do_now (deja
    # ecrit par le radar) comme prochain pas - rien d'invente ici. esc() car
    # do_now vient du LLM (jury produit, vague 2B) : un '<' non echappe cassait
    # le HTML et faisait echouer l'envoi du digest ENTIER, pas juste ce move.
    if d["plus_avance"]:
        L.append("")
        # do_now CITE tel quel (echappe), juste coupe a la limite de mot s'il
        # deborde (tenue a l'echelle : le message entier doit rester < 3500 car).
        L.append(f"👉 <b>Le plus avancé</b> - {esc(d['plus_avance']['projet'])} : {esc(_couper_mot(d['plus_avance']['do_now']))}")

    # Potentiel estime (point 5) : affiche a part, seulement si detectable,
    # jamais mele au montant confirme.
    if d["potentiel_estime_euros"] > 0:
        L.append("")
        L.append(f"<i>Potentiel estimé (non confirmé) sur les moves en cours : ~{d['potentiel_estime_euros']:.0f}€</i>")

    # TIME-TO-CASH REEL (mission post-go) : jours MEDIANS go -> fait et go -> paye,
    # calcules sur des dates prouvees (go_horodatage + confirmations/events), jamais
    # une inference d'argent. N'affiche une ligne QUE si au moins une des deux durees
    # est calculable (sinon rien - pas de "0j" trompeur faute de recul).
    ttc = d.get("time_to_cash") or {}
    morceaux_ttc = []
    if ttc.get("mediane_jours_fait") is not None:
        morceaux_ttc.append(f"go → fait : {ttc['mediane_jours_fait']:.1f}j (médiane, n={ttc['n_fait']})")
    if ttc.get("mediane_jours_paye") is not None:
        morceaux_ttc.append(f"go → payé : {ttc['mediane_jours_paye']:.1f}j (médiane, n={ttc['n_paye']})")
    if morceaux_ttc:
        L.append("")
        L.append(f"⏱ <b>Time-to-cash</b> - {' · '.join(morceaux_ttc)}")

    L.append("")
    if d["nb_paye"] == 0:
        L.append("<i>Aucun € confirmé cette semaine - ce n'est pas 0 valeur, c'est 0 CONFIRMÉ. "
                 "Tape « paye N &lt;montant&gt; » dès qu'un move rapporte.</i>")
    else:
        L.append("<i>Chiffres 100% prouvés : « payé » ne vient que de tes confirmations, jamais d'une supposition.</i>")

    # Signature commune avec le radar matinal (envoyer_telegram.format_radar) : même
    # voix éditoriale sur les deux messages de The Wire (mission design, pt. 2).
    L.append("")
    L.append("<i>- The Wire</i>")

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

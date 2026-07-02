#!/usr/bin/env python3
"""
scoring.py — Note chaque signal frais 0..100 pour que le radar du jour priorise
ce qui mene au CASH et a la DEMANDE reelle, pas au bruit de vanite.

POURQUOI ICI ET MAINTENANT
  Le scoring s'applique sur signaux_frais.json (qui porte etoiles + canal + date),
  AVANT que veille.py ne compacte en _pour_analyse.json (qui perd etoiles/canal).
  Donc on score dans collecte_signaux.py juste avant d'ecrire le JSON.

CONTRAT DUR (proof-of-dev, auditable ligne a ligne)
  - PUR & DETERMINISTE : "aujourd'hui" est un PARAMETRE (str "YYYY-MM-DD").
    Aucune horloge lue dans la logique de score. Meme (signal, aujourdhui) -> meme entier.
  - AUCUN I/O dans les fonctions de score. stdlib only (math, datetime).
  - JAMAIS d'exception qui plante : tout parsing fragile (date, etoiles) est sous
    try/except et retombe sur une branche neutre. Un signal pourri est note bas, pas fatal.
  - ASCII console : ce module n'imprime rien ; le fold ASCII des mots-cles evite
    aussi les surprises d'accents/Unicode.

FORMULE (4 composantes, fraicheur en MULTIPLICATEUR)
    base_business = V_TIER (0..40) + BONUS_DEMANDE_ARGENT (0..45)      # le FOND
    variable      = TRACTION_plafonnee (0..15)                         # le BRUIT
    score_brut    = base_business * FRAICHEUR + variable * FRAICHEUR_traction
    score         = round(clamp(score_brut, 0, 100))

  Borne max : 40+45 = 85 (*1.0) + 15 (*1.0) = 100. Atteinte UNIQUEMENT par un
  signal TIER1 + (argent ET demande) + frais du jour + forte traction fraiche.
  C'est exactement le "move of the day" ideal.
"""
from __future__ import annotations

import math
from datetime import datetime

__all__ = ["score_signal", "scorer_tous", "expliquer_signal"]


# =========================================================================
# 1) VALEUR BUSINESS DU PROJET — V_TIER (socle 0..40), TABLE FIGEE
#    Le tier vient du champ projet (rempli par le collecteur depuis l'atelier),
#    JAMAIS d'un mot du titre -> on ne peut pas usurper un tier en l'ecrivant.
# =========================================================================
TIER1 = {"serp-scraper", "brandpulse", "claude-eats-tokens"}   # actif LIVE, peut facturer cette semaine
TIER2 = {"cuepoint", "prism", "lumiere"}                       # actif reel, monetisation proche
TIER3 = {"mixhub", "pacto-club", "axis-command-os", "stratum"} # pre-revenu / pre-lancement

V_TIER1 = 40
V_TIER2 = 28
V_TIER3 = 16
V_INCONNU = 10   # plancher : on ne jette pas, mais on ne valorise pas (anti-usurpation)

# Alias -> nom canonique. Table figee, pas de devinette.
# serp-scraper et brandpulse sont le meme actif (SERP scraper = moteur de BrandPulse).
ALIAS_PROJET = {
    "pacto club": "pacto-club",
    "pacto_club": "pacto-club",
    "brand pulse": "brandpulse",
    "serp scraper": "serp-scraper",
    "serp_scraper": "serp-scraper",
    "claude eats tokens": "claude-eats-tokens",
    "claude_eats_tokens": "claude-eats-tokens",
    "axis command os": "axis-command-os",
    "axis_command_os": "axis-command-os",
}


def _normaliser_projet(nom) -> str:
    """lower/strip + resolution d'alias. Pur, table figee. Jamais d'exception."""
    try:
        n = str(nom or "").strip().lower()
    except Exception:
        return ""
    return ALIAS_PROJET.get(n, n)


# --- COUCHE 2 (overlay appris) : bonus de tier par projet, lu d'un fichier EXTERNE.
# scoring.py reste PUR : sans overlay, comportement identique (filet vert garanti).
# Le bonus est BORNE [0..TIER_BONUS_MAX] -> un projet qui PAIE peut monter, jamais
# descendre, et jamais au-dela d'une limite dure. Le panier ARGENT (POIDS_A) n'est
# JAMAIS touche par l'apprentissage : la vanite ne peut pas battre le cash.
TIER_BONUS_MAX = 12


def _overlay_tier() -> dict:
    """Lit data/poids_overlay.json a CHAQUE appel (pas de cache : garantit le
    determinisme et reflete l'overlay courant). {projet_normalise: bonus_borne}.
    Vide si absent/corrompu -> aucun effet (scoring identique au socle)."""
    try:
        from pathlib import Path
        import json as _json
        p = Path(__file__).resolve().parent.parent / "data" / "poids_overlay.json"
        raw = _json.loads(p.read_text(encoding="utf-8"))
        out = {}
        for proj, bonus in (raw.get("tier_bonus", {}) or {}).items():
            try:
                b = float(bonus)
            except Exception:
                continue
            # BORNE DURE : jamais negatif, jamais au-dela du max. Securite.
            out[_normaliser_projet(proj)] = max(0.0, min(TIER_BONUS_MAX, b))
        return out
    except Exception:
        return {}   # absent/corrompu -> aucun effet


def _v_tier(projet) -> int:
    """Mappe projet -> socle 0..40 via table dure. Inconnu/vide -> plancher 10.
    + bonus appris (couche 2) borne, si un overlay existe : un projet qui A PAYE
    monte un peu. Borne dure -> jamais > 40 (le socle reste la valeur max de base)."""
    n = _normaliser_projet(projet)
    if not n:
        return V_INCONNU
    if n in TIER1:
        base = V_TIER1
    elif n in TIER2:
        base = V_TIER2
    elif n in TIER3:
        base = V_TIER3
    else:
        base = V_INCONNU
    bonus = _overlay_tier().get(n, 0.0)
    # Le bonus appris ne fait JAMAIS depasser V_TIER1 (40) : on ne cree pas un
    # super-tier ; un projet qui paie rejoint au mieux le niveau des actifs LIVE.
    return int(min(V_TIER1, base + bonus))


# =========================================================================
# 2) BONUS DEMANDE / ARGENT — 0..45
#    3 paniers de mots-cles. Dans un panier : 1 hit ou 10 hits = MEME poids
#    (anti keyword-stuffing). On additionne les paniers DISTINCTS touches, cape a 45.
# =========================================================================
PANIER_A_ARGENT = (
    "[hiring]", "hiring", "freelance", "[selling]", "anyone selling", "contract",
    "budget", "will pay", "paid", "rates", "quote", "invoice", "[for hire]",
    "looking to hire", "we're hiring",
)
PANIER_B_DEMANDE = (
    "needed", "looking for", "anyone know", "how do i", "how to", "recommend",
    "alternative to", "is there a tool", "does anyone", "help with",
    "struggling with", "pain", "frustrated", "[request]", "wtb", "want to buy",
)
PANIER_C_SKILL = (
    "geo", "generative engine optimization", "ai visibility", "llm cost",
    "token cost", "claude code", "ai agent", "agent orchestration", "mixing",
    "mix analysis", "power bi", "csv analytics",
)

POIDS_A = 30
POIDS_B = 22
POIDS_C = 18
BONUS_CAP = 45


def _ascii_fold(s) -> str:
    """Minuscule + repli ASCII : insensible casse/accents, et les caracteres
    Unicode decoratifs (zero-width, homoglyphes non-ascii) sont SUPPRIMES.
    Ainsi 'Hiring', 'HIRING', 'h​iring' -> tous detectes. Jamais d'exception."""
    try:
        return str(s or "").lower().encode("ascii", "ignore").decode("ascii")
    except Exception:
        return ""


def _panier_touche(texte: str, panier) -> bool:
    """True si AU MOINS un mot-cle du panier est dans le texte (substring)."""
    for mot in panier:
        if mot in texte:
            return True
    return False


def _bonus_demande_argent(signal: dict) -> int:
    """Scanne titre + resume (ASCII-fold). MAX par panier, somme des paniers
    distincts touches, capee a 45. A+B+C brut = 70 -> ramene a 45 (anti-empilement)."""
    try:
        titre = signal.get("titre", "")
        resume = signal.get("resume", "")
    except Exception:
        titre, resume = "", ""
    texte = _ascii_fold(titre) + " " + _ascii_fold(resume)

    total = 0
    if _panier_touche(texte, PANIER_A_ARGENT):
        total += POIDS_A
    if _panier_touche(texte, PANIER_B_DEMANDE):
        total += POIDS_B
    if _panier_touche(texte, PANIER_C_SKILL):
        total += POIDS_C
    return min(BONUS_CAP, total)


# =========================================================================
# 3) FRAICHEUR — multiplicateur applique au FOND business (et, variante plus
#    severe, a la traction). Un vieux signal voit TOUT son score rabattu :
#    la fraicheur ne s'additionne pas, elle multiplie (anti-accumulation).
# =========================================================================
def _age_jours(date_str, aujourdhui: str):
    """Renvoie l'age en jours (int >= 0) ou None si non parsable.
    Parsing PUR de deux strings 'YYYY-MM-DD' (strptime, sans tz, sans now()).
    Futur (age < 0) -> clamp a 0 (pas de plantage, pas de bonus). Jamais d'exception."""
    try:
        d_sig = datetime.strptime(str(date_str).strip(), "%Y-%m-%d")
        d_auj = datetime.strptime(str(aujourdhui).strip(), "%Y-%m-%d")
    except Exception:
        return None
    age = (d_auj - d_sig).days
    if age < 0:        # date dans le futur -> traitee comme aujourd'hui
        age = 0
    return age


def _fraicheur(date_str, aujourdhui: str, plancher: float, defaut_vide: float) -> float:
    """Courbe de fraicheur, parametrable par son plancher et sa valeur 'date inconnue'.
      date vide / non parsable -> defaut_vide
      age <= 1 j  -> 1.00 ;  <= 3 -> 0.90 ;  <= 7 -> 0.75
      <= 14 -> 0.60 ;  <= 30 -> 0.50 ;  > 30 -> plancher"""
    age = _age_jours(date_str, aujourdhui)
    if age is None:
        return defaut_vide
    if age <= 1:
        return 1.00
    if age <= 3:
        return 0.90
    if age <= 7:
        return 0.75
    if age <= 14:
        return 0.60
    if age <= 30:
        return 0.50
    return plancher


def _fraicheur_fond(date_str, aujourdhui: str) -> float:
    """Pour le FOND business : plancher 0.40 (un vieux TIER1 vaut encore un peu),
    date inconnue -> 0.60 (penalite moderee, ni 0 ni plein tarif)."""
    return _fraicheur(date_str, aujourdhui, plancher=0.40, defaut_vide=0.60)


def _fraicheur_traction(date_str, aujourdhui: str) -> float:
    """Pour la TRACTION : meme courbe mais plus severe (plancher 0.25, vide 0.40).
    Un vieux buzz est encore moins pertinent qu'un vieux fond business."""
    return _fraicheur(date_str, aujourdhui, plancher=0.25, defaut_vide=0.40)


# =========================================================================
# 4) TRACTION — 0..15, PLAFONNEE + LOGARITHMIQUE (anti-vanite, le coeur).
#    etoiles = stars GitHub OU points HN. reddit/youtube n'ont pas le champ -> 0.
#    log10 casse la vanite : 100->10 000 etoiles n'ajoute presque rien.
# =========================================================================
TRACTION_CAP = 15.0


def _traction(signal: dict) -> float:
    """min(15, 5 * log10(1 + t)). Reperes : t=0->0, 9->5, 99->10, 999->15, 10000->cape 15.
    Cast robuste : 'etoiles':'beaucoup' ou None -> 0, jamais d'exception, jamais d'infini."""
    try:
        t = int(signal.get("etoiles", 0) or 0)
    except Exception:
        t = 0
    if t < 0:
        t = 0
    return min(TRACTION_CAP, 5.0 * math.log10(1 + t))


# =========================================================================
# CLAMP + ASSEMBLAGE
# =========================================================================
def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def score_signal(signal: dict, aujourdhui: str) -> int:
    """Note un signal sur 0..100. PUR et DETERMINISTE (today_str en parametre).

    base_business = V_TIER + BONUS_DEMANDE_ARGENT          (0..85)
    variable      = TRACTION_plafonnee                     (0..15)
    score_brut    = base_business * FRAICHEUR_fond + variable * FRAICHEUR_traction
    score         = round(clamp(score_brut, 0, 100))

    Robuste : un signal non-dict ou vide -> score plancher, jamais d'exception.
    """
    if not isinstance(signal, dict):
        return 0

    date_str = signal.get("date", "")

    v_tier = _v_tier(signal.get("projet", ""))
    bonus = _bonus_demande_argent(signal)
    base_business = v_tier + bonus

    traction = _traction(signal)

    fr_fond = _fraicheur_fond(date_str, aujourdhui)
    fr_trac = _fraicheur_traction(date_str, aujourdhui)

    score_brut = base_business * fr_fond + traction * fr_trac
    return int(round(_clamp(score_brut, 0.0, 100.0)))


def expliquer_signal(signal: dict, aujourdhui: str) -> dict:
    """Meme calcul que score_signal mais renvoie la decomposition (audit / debug /
    affichage 'raisons' dans le radar). PUR, aucun I/O, jamais d'exception."""
    if not isinstance(signal, dict):
        return {"score": 0, "raisons": ["signal invalide"]}

    date_str = signal.get("date", "")
    v_tier = _v_tier(signal.get("projet", ""))
    bonus = _bonus_demande_argent(signal)
    traction = _traction(signal)
    fr_fond = _fraicheur_fond(date_str, aujourdhui)
    fr_trac = _fraicheur_traction(date_str, aujourdhui)

    base_business = v_tier + bonus
    score_brut = base_business * fr_fond + traction * fr_trac
    score = int(round(_clamp(score_brut, 0.0, 100.0)))

    # Quels paniers ont touche (pour des raisons lisibles)
    texte = _ascii_fold(signal.get("titre", "")) + " " + _ascii_fold(signal.get("resume", ""))
    paniers = []
    if _panier_touche(texte, PANIER_A_ARGENT):
        paniers.append("argent/embauche")
    if _panier_touche(texte, PANIER_B_DEMANDE):
        paniers.append("demande/douleur")
    if _panier_touche(texte, PANIER_C_SKILL):
        paniers.append("skill-Adam")

    age = _age_jours(date_str, aujourdhui)
    if age is None:
        age_txt = "date inconnue"
    else:
        age_txt = f"{age}j"

    raisons = [
        f"projet={_normaliser_projet(signal.get('projet', '')) or '(inconnu)'} -> tier {v_tier}/40",
        f"intention {bonus}/45" + (f" [{', '.join(paniers)}]" if paniers else " [aucun mot-cle]"),
        f"traction {round(traction, 1)}/15",
        f"fraicheur {age_txt} (fond x{round(fr_fond, 2)}, traction x{round(fr_trac, 2)})",
    ]
    return {
        "score": score,
        "v_tier": v_tier,
        "bonus": bonus,
        "traction": round(traction, 2),
        "fraicheur_fond": round(fr_fond, 2),
        "fraicheur_traction": round(fr_trac, 2),
        "paniers": paniers,
        "age_jours": age,
        "raisons": raisons,
    }


def scorer_tous(signaux, aujourdhui: str) -> list:
    """Note une liste de signaux et la renvoie TRIEE par score decroissant.

    - Chaque signal recoit "score" (int 0..100) et "raisons" (list[str]).
    - Tri stable, deterministe : (score desc, puis ordre d'origine) -> meme entree,
      meme sortie. Aucune mutation surprise : on travaille sur les dicts d'origine
      (on AJOUTE juste les cles), ce qui est exactement ce dont collecte_signaux a besoin
      pour reecrire signaux_frais.json enrichi.
    - Robuste : entree non-iterable ou element non-dict -> ignore proprement,
      jamais d'exception qui sauterait le batch entier.
    """
    try:
        liste = list(signaux or [])
    except Exception:
        return []

    enrichis = []
    for sig in liste:
        if not isinstance(sig, dict):
            continue
        info = expliquer_signal(sig, aujourdhui)
        sig["score"] = info["score"]
        sig["raisons"] = info["raisons"]
        enrichis.append(sig)

    # Tri par score decroissant ; Python sort est stable -> a score egal, ordre d'origine.
    enrichis.sort(key=lambda s: s.get("score", 0), reverse=True)
    return enrichis


# Auto-test minimal (lance: python scoring.py). N'imprime que de l'ASCII.
if __name__ == "__main__":
    aujourdhui = "2026-06-30"
    echantillon = [
        {"canal": "reddit", "projet": "serp-scraper", "date": "2026-06-30",
         "titre": "[HIRING] freelance needed for AI visibility audit, will pay",
         "resume": "r/forhire - budget ready, GEO expert", "etoiles": 0},
        {"canal": "github", "projet": "claude-eats-tokens", "date": "2024-01-01",
         "titre": "Old unrelated repo", "resume": "", "etoiles": 50000},
        {"canal": "youtube", "projet": "", "date": "",
         "titre": "Generic tutorial about coding", "resume": ""},
        {"canal": "hackernews", "projet": "cuepoint", "date": "2026-06-28",
         "titre": "Show HN: audio mix analysis tool", "resume": "", "etoiles": 99},
    ]

    def _ascii(x):
        return str(x).encode("ascii", "replace").decode("ascii")

    classes = scorer_tous(echantillon, aujourdhui)
    print("ASCII self-test (today=%s):" % aujourdhui)
    for s in classes:
        print("  score=%3d  [%s]  %s" % (s["score"], s["canal"], _ascii(s["titre"])[:55]))
        for r in s["raisons"]:
            print("        - " + _ascii(r))
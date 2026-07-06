#!/usr/bin/env python3
"""
envoyer_telegram.py - Pousse le radar du jour sur Telegram (bot The Wire).

Lit le token + chat_id depuis config.local.json (LOCAL, jamais sur GitHub),
formate le radar (data/radar.json) en message lisible, et l'envoie.

Usage : python systeme/envoyer_telegram.py
Robuste : si pas de radar.json ou radar vide -> message "rien de neuf" (ou silence).
"""
from __future__ import annotations
import json
import re
import sys
import time
import urllib.error  # explicite : ne pas dependre de l'import implicite fait par urllib.request
import urllib.request
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG = ROOT / "config.local.json"
RADAR = ROOT / "data" / "radar.json"
SIGNAUX = ROOT / "data" / "signaux_frais.json"
TG_LIMIT = 4096  # limite Telegram par message
DELAIS_RETRY = (2.0, 5.0)  # backoff des re-essais d'envoi : ~2 s puis ~5 s (2 retries max)
RETRY_AFTER_PLAFOND = 30.0  # un 429 Telegram peut annoncer retry_after : respecte mais plafonne

# Delai du planificateur Fable, SOURCE UNIQUE = executer_move.PLAN_GO_TIMEOUT_S (le CTA
# ne doit jamais afficher un chiffre invente/orphelin). Import paresseux tolerant : si
# executer_move est indisponible (env de test isole, etc.), repli 8 min (valeur actuelle
# documentee), jamais un crash du radar pour un simple affichage de delai.
try:
    sys.path.insert(0, str(HERE))
    from executer_move import PLAN_GO_TIMEOUT_S as _PLAN_GO_TIMEOUT_S  # type: ignore
except Exception:
    _PLAN_GO_TIMEOUT_S = 8 * 60


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.local.json absent - pas de Telegram configuré.")
        sys.exit(0)
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def esc(s) -> str:
    """Échappe le HTML pour Telegram (parse_mode=HTML)."""
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _dans_une_balise(s: str, pos: int) -> bool:
    """True si l'indice pos tombe DANS une balise (entre un '<' et son '>').
    Sert a ne jamais couper au milieu de <blockquote>/<pre>/<a ...>."""
    ouvre = s.rfind("<", 0, pos)
    if ouvre == -1:
        return False
    ferme = s.find(">", ouvre)
    return ferme >= pos  # un '<' non encore ferme avant pos = on est dans la balise


def _dans_une_entite(s: str, pos: int) -> bool:
    """True si pos tombe au MILIEU d'une entite HTML (&amp; &lt; ...). Couper la
    laisserait un '&am' orphelin en fin de chunk et un debut d'entite perdu au
    suivant : texte affiche faux. Une entite fait moins de 10 caracteres, on ne
    regarde donc qu'en arriere proche."""
    amp = s.rfind("&", max(0, pos - 9), pos)
    if amp == -1:
        return False
    return ";" not in s[amp:pos]  # '&' pas encore referme avant pos = on est dedans


# Balises HTML acceptees par Telegram : les seules a fermer/rouvrir a la coupe.
BALISES_TG = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
              "a", "code", "pre", "blockquote", "tg-spoiler", "span"}


def _balises_ouvertes(s: str) -> list:
    """Scanne le HTML et rend la pile des balises encore OUVERTES a la fin, sous
    forme (nom, texte_ouvrant_complet) - ex. ('blockquote', '<blockquote expandable>').
    POURQUOI : Telegram rejette tout chunk aux balises non appariees ('can't find
    end tag') et TOUT l'envoi echoue ; pour decouper sans casser, il faut savoir
    exactement quoi fermer en fin de chunk et quoi rouvrir au debut du suivant."""
    pile = []
    i, n = 0, len(s)
    while i < n:
        ouvre = s.find("<", i)
        if ouvre == -1:
            break
        ferme = s.find(">", ouvre + 1)
        if ferme == -1:
            break  # balise tronquee en bout de chaine (les coupes l'evitent en amont)
        contenu = s[ouvre + 1:ferme].strip()
        if contenu.startswith("/"):
            nom = contenu[1:].strip().lower()
            for k in range(len(pile) - 1, -1, -1):  # depile la derniere ouverture du meme nom
                if pile[k][0] == nom:
                    del pile[k]
                    break
        elif contenu:
            nom = contenu.split()[0].lower()
            if nom in BALISES_TG:
                pile.append((nom, s[ouvre:ferme + 1]))
        i = ferme + 1
    return pile


def _equilibrer_balises(chunks: list) -> list:
    """Ferme les balises restees ouvertes en fin de chunk et les ROUVRE au debut
    du suivant (attributs conserves : '<blockquote expandable>', '<a href=...>').
    POURQUOI : une frontiere de decoupe peut tomber au milieu d'un <b>...</b> ;
    sans ce raccommodage, Telegram rejette le chunk et le radar entier est perdu."""
    out = []
    pile = []  # balises ouvertes heritees du chunk precedent
    for chunk in chunks:
        chunk = "".join(texte for _, texte in pile) + chunk
        pile = _balises_ouvertes(chunk)
        out.append(chunk + "".join("</%s>" % nom for nom, _ in reversed(pile)))
    return out


def _position_coupe(s: str, limite: int) -> int:
    """Meilleure position de coupe avant `limite` : le dernier '\\n' HORS balise
    (frontiere naturelle), sinon on recule jusqu'a sortir de toute balise ou
    entite. En dernier recours : coupe dure juste avant la limite (pathologique)."""
    for i in range(limite - 1, 0, -1):
        if s[i] == "\n" and not _dans_une_balise(s, i):
            return i
    coupe = limite - 1
    while coupe > 0 and (_dans_une_balise(s, coupe) or _dans_une_entite(s, coupe)):
        coupe -= 1
    if coupe <= 0:
        coupe = limite - 1  # abandon : coupe dure (cas pathologique)
    return coupe


def _refendre_si_trop_long(chunk: str) -> list:
    """FILET DE SECURITE : garantit qu'aucun morceau ne depasse TG_LIMIT, meme si un
    seul bloc (un move a gros <pre>, ou la queue) est enorme. La coupe est HTML-SAFE :
    jamais au milieu d'une balise ni d'une entite, et toute balise encore ouverte a
    la coupe (<b>, <pre>, <blockquote>...) est FERMEE en fin de morceau puis ROUVERTE
    au debut du suivant. Sans ce filet, Telegram renvoie HTTP 400 et TOUT le radar
    est perdu silencieusement."""
    if len(chunk) <= TG_LIMIT:
        return [chunk]
    out = []
    reste = chunk
    while len(reste) > TG_LIMIT:
        # coupe sure la plus tardive, en gardant la place pour FERMER les balises
        limite = TG_LIMIT
        while True:
            coupe = _position_coupe(reste, limite)
            pile = _balises_ouvertes(reste[:coupe])
            fermetures = "".join("</%s>" % nom for nom, _ in reversed(pile))
            if coupe + len(fermetures) <= TG_LIMIT or limite <= 1:
                break
            limite = max(coupe - len(fermetures), 1)  # trop juste : retente plus tot
        piece = reste[:coupe] + fermetures
        suivant = "".join(texte for _, texte in pile) + reste[coupe:].lstrip("\n")
        if len(suivant) >= len(reste):
            # garde-fou anti-boucle (nid de balises pathologique, jamais vu en vrai) :
            # coupe dure sans equilibrage plutot que boucler a l'infini
            piece, suivant = reste[:TG_LIMIT], reste[TG_LIMIT:]
        out.append(piece)
        reste = suivant
    if reste:
        out.append(reste)
    return out


def _retry_after_depuis(corps: str, defaut: float) -> float:
    """Extrait parameters.retry_after du corps JSON d'un 429 Telegram (sinon rend
    `defaut`). Plafonne : un retry_after delirant annonce par l'API ne doit pas
    suspendre le run du matin plus de RETRY_AFTER_PLAFOND secondes."""
    try:
        val = float(json.loads(corps).get("parameters", {}).get("retry_after"))
        return max(0.0, min(val, RETRY_AFTER_PLAFOND))
    except Exception:
        return defaut


def _appel_api(req: urllib.request.Request) -> dict | None:
    """UN appel HTTP a l'API Telegram, re-essaye 2 fois sur erreur TRANSITOIRE :
    panne reseau/timeout, HTTP 5xx, HTTP 429 (en respectant son retry_after).
    POURQUOI : le radar part a 10h pile ; un hoquet reseau de 2 s ne doit pas
    couter le brief du jour. Un 4xx autre que 429 = CONTENU refuse : insister est
    inutile, on echoue net. Rend le JSON de reponse, ou None si tout a echoue
    (l'appelant rend alors False -> code retour 1, contrat de lancer_veille.bat)."""
    for tentative in range(len(DELAIS_RETRY) + 1):
        try:
            return json.load(urllib.request.urlopen(req, timeout=20))
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")
            transitoire = (e.code == 429) or (500 <= e.code < 600)
            if not transitoire or tentative >= len(DELAIS_RETRY):
                print("HTTP", e.code, corps.encode("ascii", "replace").decode("ascii"))
                return None
            attente = DELAIS_RETRY[tentative]
            if e.code == 429:
                attente = _retry_after_depuis(corps, attente)
            print("HTTP %d transitoire, nouvel essai dans %.0f s..." % (e.code, attente))
            time.sleep(attente)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # URLError couvre DNS/connexion ; TimeoutError le timeout d'urlopen
            if tentative >= len(DELAIS_RETRY):
                print("Echec envoi:", str(e).encode("ascii", "replace").decode("ascii"))
                return None
            attente = DELAIS_RETRY[tentative]
            print("Erreur reseau (%s), nouvel essai dans %.0f s..." % (e.__class__.__name__, attente))
            time.sleep(attente)
        except Exception as e:
            # erreur NON transitoire (ex. reponse illisible) : re-essayer est inutile
            print("Echec envoi:", str(e).encode("ascii", "replace").decode("ascii"))
            return None
    return None


# Pastille colorée par projet (repère visuel rapide) - même 6 couleurs ramp que la PWA
# (DESIGN-SPEC.md §3) : l'identité du projet, jamais décorative.
DOT = {"blue": "🔵", "teal": "🟢", "purple": "🟣", "coral": "🟠", "amber": "🟡", "gray": "⚪"}

# LEXIQUE FIXE - la seule palette dont on dispose en Telegram (HTML pauvre, pas de
# couleur ni de taille) est la hiérarchie typographique + un jeu d'emojis-signal
# CONSTANT. Chaque emoji ne veut dire qu'UNE chose, toujours la même, jamais posé
# pour décorer. Registre complet (pour ne pas en introduire un nouveau par accident) :
#   📡 hook du jour (headline)   ⭐️ move du jour (star)      💡 insight (lecture stratégique)
#   👉 do now (action immédiate) ⏱ meta (effort/gain, sur le PLI)  ➡️ ensuite (prochaine étape)
#   ♻️ aussi pour (transfert)    🎓 skill up de la semaine   📲 lien vers la PWA
#   ☕️ jour calme                ↩️ répondre (go N / fait N - le CTA)
# (le ✓ a été retiré : il se lisait "déjà fait" alors qu'il marquait le critère
#  de done - remplacé par "Fini quand :" en toutes lettres.)
DOT_SANS_RAMP = "⚪"


def send(token: str, chat: str, html: str) -> bool:
    """Envoie en HTML riche. Si > limite, découpe sur les FRONTIERES DE BLOCS
    (fin de move), JAMAIS au milieu d'une balise - sinon Telegram refuse
    ('can't find end tag'). Deux filets par-dessus : _equilibrer_balises referme et
    rouvre toute balise a cheval sur une frontiere, et _refendre_si_trop_long
    garantit qu'aucun morceau ne depasse jamais 4096, meme si un seul bloc est
    enorme (gros <pre>). Chaque appel HTTP est re-essaye sur erreur transitoire
    (_appel_api) ; un echec definitif rend False -> code retour 1 du script."""
    chunks = []
    if len(html) <= TG_LIMIT:
        chunks = [html]
    else:
        # Frontieres SURES = fin d'un move. Deux marqueurs, car un move SANS
        # aucun champ detaille (meta/pourquoi/insight/do_now/steps/ensuite/
        # aussi_pour, cas rare) n'a PAS de </blockquote> (format_radar, "if
        # detail:") -> se fier a lui seul coupait parfois EN PLEIN MILIEU d'un
        # tel move (bug reel trouve par le jury produit, vague 2B). Le second
        # marqueur ("\n\n\n" + dot de debut de move) existe pour TOUT move,
        # avec ou sans blockquote -> filet de coupe universel.
        pos = set()
        i = html.find("</blockquote>")
        while i != -1:
            pos.add(i + len("</blockquote>"))
            i = html.find("</blockquote>", i + 1)
        for dot in set(DOT.values()) | {DOT_SANS_RAMP}:
            marqueur = "\n\n\n" + dot
            i = html.find(marqueur)
            while i != -1:
                if i > 0:  # jamais une coupe a la toute premiere position
                    pos.add(i)
                i = html.find(marqueur, i + 1)
        frontieres = sorted(pos)
        blocs, prev = [], 0
        for f in frontieres:
            blocs.append(html[prev:f])
            prev = f
        if prev < len(html):
            blocs.append(html[prev:])
        buf = ""
        for bloc in blocs:
            if buf and len(buf) + len(bloc) > TG_LIMIT:
                chunks.append(buf); buf = bloc
            else:
                buf += bloc
        if buf:
            chunks.append(buf)
    # FILET 1 : jamais de balise laissee ouverte en fin de chunk (Telegram rejette).
    chunks = _equilibrer_balises(chunks)
    # FILET 2 : un bloc unique peut lui-meme depasser 4096 (gros <pre>, longue queue).
    # On re-fend chaque chunk survivant sur une frontiere sure ET equilibree.
    chunks = [c for chunk in chunks for c in _refendre_si_trop_long(chunk)]
    for chunk in chunks:
        if not chunk.strip():
            continue  # jamais de message vide vers l'API (400 assure, envoi perdu)
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": chunk, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        r = _appel_api(req)
        if r is None:
            return False
        if not r.get("ok"):
            print("Erreur Telegram:", r.get("description"))
            return False
    return True




def _section_suivi_go() -> str:
    """Section 'Tes go en cours' (module suivi_go). Import paresseux + tolérant :
    si le module échoue, le radar part quand même (jamais de matin sans The Wire).
    Retourne '' si aucun go actif -> la section n'alourdit pas le message pour rien."""
    try:
        import suivi_go  # type: ignore
        return suivi_go.formater_section_radar()
    except Exception as e:
        print("suivi_go indisponible (section go ignorée):", e)
        return ""


def _detail_move(m: dict) -> list:
    """Le DÉPLIÉ d'un move. Ordre voulu : POURQUOI + DO NOW (ce qui compte), puis
    le plan complet (steps) en secondaire, puis ensuite/aussi_pour.
    La META (⏱ effort/gain) vit désormais sur le PLI (format_radar) : c'est une
    info de DÉCISION ("je déplie ou pas ?"), la mettre ici la cachait derrière
    le tap qu'elle est censée déclencher (audit GTM)."""
    out = []
    if m.get("pourquoi_maintenant"):
        out.append(f"<b>Pourquoi maintenant :</b> {esc(m['pourquoi_maintenant'])}")
        out.append("")
    if m.get("insight"):
        # La lecture STRATEGIQUE du move (champ optionnel, exige pour le move star
        # par prompt_analyse_auto.md) : ce que le fait IMPLIQUE, jamais sa repetition.
        # Tronque a 160 en dur (garde-fou deterministe : la spec SPEC-INSIGHT-2B
        # limite a 160, le jury ne scanne pas encore ce champ).
        out.append(f"<i>💡 {esc(str(m['insight'])[:160])}</i>")
        out.append("")
    if m.get("do_now"):
        out.append("<b>👉 Fais ça maintenant :</b>")
        out.append(esc(m["do_now"]))
        out.append("")
    # Plan complet (secondaire) - chaque texte-a-coller en <pre> (copie propre mobile)
    steps = m.get("steps", [])
    if steps:
        out.append("<b>Le plan complet :</b>")
        for i, s in enumerate(steps, 1):
            out.append(f"<b>{i}.</b> {esc(s.get('t',''))}")
            if s.get("how"):
                out.append(f"<i>{esc(s['how'])}</i>")
            if s.get("paste"):
                out.append(f"<pre>{esc(s['paste'])}</pre>")
            if s.get("done"):
                # "Fini quand :" explicite - l'ancien "✓ ..." se lisait comme une
                # étape DÉJÀ faite (le ✓ signale l'accompli partout ailleurs),
                # alors que c'est le CRITÈRE de done (audit GTM, point 5).
                out.append(f"<i>Fini quand : {esc(s['done'])}</i>")
            out.append("")
    if m.get("ensuite"):
        out.append(f"➡️ <b>Ensuite :</b> {esc(m['ensuite'])}")
    if m.get("aussi_pour"):
        out.append(f"♻️ <b>Aussi pour :</b> {esc(m['aussi_pour'])}")
    return out


# Regex MIROIR d'extractVerdict (pwa/app.js) : premier montant en € trouve
# n'importe ou dans le titre, suffixe /mois·/an conserve. Anti-invention : pas
# de € dans le titre -> None, jamais de montant fabrique. Tenue synchro a la
# main avec la version JS (meme contrat, deux runtimes differents).
_RE_GAIN = re.compile(
    r"(?:(?:gagne|gain|rapporte|encaisse)\s+)?~?\s*([\d][\d\s.,]*)\s*€\s*"
    r"(/\s*(?:mois|an|semaine|jour))?",
    re.IGNORECASE,
)


def _gain_du_titre(title: str) -> str:
    """Extrait '~<montant>€<suffixe>' du titre du move star (ex. 'Gagne ~290€ : ...'
    -> '~290€'). Rend '' si aucun montant en € present (AUCUNE invention) - dans ce
    cas la ligne CTA ne cite aucun chiffre."""
    t = str(title or "")
    m = _RE_GAIN.search(t)
    if not m:
        return ""
    num = re.sub(r"[\s.,](?=\d{3}\b)", "", m.group(1))  # separateurs de milliers
    num = re.sub(r",00$", "", num)                        # ",00" decoratif
    num = re.sub(r"[\s.,]+$", "", num).strip()
    if not num or not re.search(r"\d", num):
        return ""
    suffixe = ""
    if m.group(2):
        suffixe = "/" + re.sub(r"[\s/]+", "", m.group(2))
    return f"~{num}€{suffixe}"


_MOIS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
            "juil.", "août", "sept.", "oct.", "nov.", "déc."]
_JOURS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def _date_humaine(iso: str) -> str:
    """'2026-06-30' -> 'lun. 30 juin'. Manuel (listes FR en dur) : la locale
    Windows du Planificateur n'est pas fiable, et une date machine dans un
    message soigne casse le registre. Repli : la chaine brute si illisible."""
    try:
        from datetime import date as _d
        d = _d.fromisoformat(str(iso)[:10])
        return f"{_JOURS_FR[d.weekday()]} {d.day} {_MOIS_FR[d.month - 1]}"
    except Exception:
        return str(iso)


def format_radar(radar: dict, pwa_url: str = "https://arochab.github.io/agent-veille/") -> str:
    """Radar -> Telegram. LIMPIDE : chaque move = title ultra-direct (le PLI) ; le
    déplié montre POURQUOI + DO NOW d'abord, plan complet ensuite. Tout est repliable
    pour que le fil reste scannable en 3 secondes."""
    L = []
    date = esc(radar.get("date", ""))
    moves = radar.get("moves", [])

    # Style B : on aère avec des lignes vides (2 entre moves), zéro séparateur lourd.
    if not moves:
        L.append(f"📡 <b>THE WIRE</b>  ·  <i>{_date_humaine(date)}</i>")
        L.append("")
        L.append("")
        L.append("☕️ <b>Rien de neuf aujourd'hui.</b>")
        L.append("<i>Jour calme = bonne nouvelle. The Wire ne te réveille que pour du concret.</i>")
        # Même un jour calme, on montre où en sont les go déjà lancés (s'il y en a).
        suivi = _section_suivi_go()
        if suivi:
            L.append(suivi)
        L.append("")
        L.append("")
        L.append("<i>- The Wire</i>")
        return "\n".join(L)
    # LE HOOK D'ABORD (audit GTM) : la preview de notification Telegram ne montre
    # que les ~50 premiers caractères - les dépenser sur "THE WIRE · date" (que
    # Telegram affiche DÉJÀ : nom du bot + heure) gaspillait l'accroche du jour.
    # La headline ouvre le message ; la marque passe en 2e ligne discrète.
    if radar.get("headline"):
        L.append(f"📡 <b>{esc(radar['headline'])}</b>")
        L.append(f"<i>The Wire · {_date_humaine(date)}</i>")
    else:
        L.append(f"📡 <b>THE WIRE</b>  ·  <i>{_date_humaine(date)}</i>")

    # Move du jour en premier (rank=star), puis les autres par ordre du radar.
    star_move = next((m for m in moves if m.get("rank") == "star"), moves[0])
    ordered = [star_move] + [m for m in moves if m is not star_move]

    for m in ordered:
        dot = DOT.get(m.get("ramp", "gray"), DOT_SANS_RAMP)
        star = "⭐️ " if m.get("rank") == "star" else ""
        # Rang numéroté sur les moves 2..n (le star porte déjà ⭐️, pas besoin d'un
        # numéro en plus) : au coup d'oeil, "tu es sur le move 2 sur 3" - même repère
        # que le rail numéroté de la PWA (DESIGN-SPEC.md §2, "Moves 2..n"). Rang et
        # titre dans le MÊME <b> : deux balises grasses collées casseraient la lecture.
        rang = "" if star else f"{esc(m.get('rank',''))}. "
        L.append("")
        L.append("")   # gros espace entre les moves (style B)
        # LE PLI : titre ultra-direct (suffit à décider) + qualification VISIBLE
        # avant le tap (audit GTM) : l'effort/gain (⏱ meta) décide "je déplie ou
        # pas" - le cacher dans le déplié forçait un tap à l'aveugle.
        L.append(f"{dot} {star}<b>{rang}{esc(m.get('title',''))}</b>")
        sous = esc(m.get("projet", ""))
        if m.get("meta"):
            sous = f"{sous} · ⏱ {esc(m['meta'])}" if sous else f"⏱ {esc(m['meta'])}"
        if sous:
            L.append(f"<i>{sous}</i>")
        # LE DÉPLIÉ : pourquoi + do now + plan, replié
        detail = _detail_move(m)
        if detail:
            body = "\n".join(x for x in detail).strip()
            L.append(f"<blockquote expandable>{body}</blockquote>")

    # LA CONVERSION (audit GTM) : le geste attendu - répondre « go N » - n'était
    # écrit NULLE PART. Un radar sans call-to-action est une newsletter ; avec,
    # c'est un bon de commande. DEUX lignes, après les moves, jamais répétées :
    # la 1ere est le geste (go N), la 2e nomme le PIPELINE (Fable planifie, Sonnet
    # execute) et RECOPIE le gain du move star - l'argument de vente etait jusqu'ici
    # invisible dans le CTA (brief renforcement Activation, 2026-07-06). Le delai
    # affiche derive de PLAN_GO_TIMEOUT_S (executer_move.py), jamais un chiffre
    # orphelin recopie a la main.
    L.append("")
    L.append("")
    L.append("↩️ <b>Réponds « go 1 »</b> (ou 2, 3...)")
    gain = _gain_du_titre(star_move.get("title", ""))
    delai_min = max(1, round(_PLAN_GO_TIMEOUT_S / 60))
    vise = f" - vise {gain}" if gain else ""
    L.append(f"<i>Fable pose le plan (2 à {delai_min} min), Sonnet exécute sous ton contrôle{vise}.</i>")

    if radar.get("skill_up"):
        L.append("")
        L.append("")
        L.append("🎓 <b>Cette semaine :</b> " + f"<i>{esc(radar['skill_up'])}</i>")

    # Suivi des go déjà lancés : où on en est, prouvé, formulé net (juste avant le pied).
    suivi = _section_suivi_go()
    if suivi:
        L.append("")
        L.append(suivi)

    # Libellé honnête (audit GTM) : la page publique n'affiche que la DÉMO tant
    # que le vrai radar n'est pas publié (données privées, choix assumé) -
    # « Radar complet » promettait plus que la page ne donne.
    L.append("")
    L.append("")
    L.append(f'📲 <a href="{pwa_url}">L\'app The Wire</a>')
    L.append("<i>- The Wire</i>")
    return "\n".join(L)


def format_incident(incidents: list) -> str:
    """Message d'ALERTE PANNE, volontairement distinct du brief normal.
    On veut qu'Adam distingue d'un coup d'oeil 'jour calme' de 'canal casse'."""
    L = ["⚠️ <b>THE WIRE - INCIDENT</b>",
         "<i>Un canal cense etre vivant est muet. Ce n'est pas un jour calme.</i>",
         "━━━━━━━━━━━━━━━"]
    for inc in incidents:
        canal = esc(inc.get("canal", "?"))
        err = esc(inc.get("erreur", ""))
        L.append("")
        L.append(f"\U0001f4f5 <b>Canal {canal} muet</b>")
        L.append(f"<code>{err}</code>")
    L.append("")
    L.append("<i>Verifie ce canal : la veille du jour est peut-etre incomplete.</i>")
    return "\n".join(L)


def format_analyse_morte() -> str:
    """Alerte 'cerveau muet' : la collecte a ramene du grain, mais l'analyse LLM
    (claude -p) n'a produit AUCUN radar. Distinct du 'jour calme' : ici il FAUT agir
    (souvent : 'claude /login' a expire). On ne laisse jamais un cerveau casse passer
    pour un matin tranquille."""
    return "\n".join([
        "🧠⚠️ <b>THE WIRE - ANALYSE MUETTE</b>",
        "<i>La collecte a trouve du grain ce matin, mais l'analyse n'a produit aucun radar.</i>",
        "━━━━━━━━━━━━━━━",
        "",
        "Ce n'est <b>pas</b> un jour calme : le cerveau (claude -p) n'a pas repondu.",
        "<b>Cause la plus probable :</b> la connexion <code>claude</code> a expire.",
        "",
        "👉 <b>Repare en 20 s :</b> ouvre un terminal, tape <code>claude</code> puis <code>/login</code>.",
        "<i>Le prochain run repartira normalement.</i>",
    ])


def envoyer_analyse_morte(token: str, chat: str) -> int:
    """Mode --analyse-morte : push l'alerte 'cerveau muet' (appele par lancer_veille.bat
    quand analyser_auto.bat renvoie le code 3)."""
    ok = send(token, chat, format_analyse_morte())
    print("Alerte analyse muette envoyee." if ok else "Echec de l'alerte analyse muette.")
    return 0 if ok else 1


def format_envoi_echoue() -> str:
    """Alerte 'envoi echoue' : le radar existe, le jury a dit GO, mais l'envoi du
    brief lui-meme a echoue (reseau/API Telegram). Distinct de l'analyse muette :
    ici le cerveau a bien produit un radar, seule la livraison a rate. On tente
    cette alerte sur le MEME canal Telegram : si le reseau est vraiment mort,
    elle echouera aussi silencieusement (loggue par l'appelant), mais c'est le
    seul canal dont on dispose."""
    return "\n".join([
        "📡⚠️ <b>THE WIRE - ENVOI ECHOUE</b>",
        "<i>Le radar du jour a ete produit et valide, mais l'envoi Telegram a echoue.</i>",
        "━━━━━━━━━━━━━━━",
        "",
        "Ce n'est <b>pas</b> un jour calme : le brief existe, il n'est juste pas arrive.",
        "<b>Cause probable :</b> panne reseau ou API Telegram temporaire.",
        "",
        "👉 <code>data/radar.json</code> a ete CONSERVE (pas archive) : le prochain",
        "run peut le renvoyer sans perte. Si ca persiste, verifie ta connexion",
        "et le token dans <code>config.local.json</code>.",
    ])


def envoyer_envoi_echoue(token: str, chat: str) -> int:
    """Mode --envoi-echoue : alerte qu'un radar valide n'a pas pu partir (appele
    par lancer_veille.bat quand l'envoi normal du radar a renvoye un code != 0)."""
    ok = send(token, chat, format_envoi_echoue())
    print("Alerte envoi-echoue envoyee." if ok else "Echec de l'alerte envoi-echoue (reseau probablement mort).")
    return 0 if ok else 1


def envoyer_incident(token: str, chat: str) -> int:
    """Mode --incident : lit signaux_frais.json, et SI panne -> push l'alerte."""
    if not SIGNAUX.exists():
        print("Pas de signaux_frais.json - rien a verifier.")
        return 0
    try:
        data = json.loads(SIGNAUX.read_text(encoding="utf-8"))
    except Exception as e:
        print("Lecture signaux_frais.json impossible:", e)
        return 1
    incidents = data.get("incidents", []) or []
    if not incidents:
        print("Aucun incident -> pas d'alerte (silence normal).")
        return 0
    ok = send(token, chat, format_incident(incidents))
    print("Alerte panne envoyee." if ok else "Echec de l'alerte panne.")
    return 0 if ok else 1


def envoyer_digest_roi(token: str, chat: str) -> int:
    """Mode --roi : bilan hebdo go -> fait -> paye (audit Fable, reco #2).
    Ne fait AUCUNE inference d'argent : digest_roi.py ne compte que des go
    deja au statut 'paye' (verrouille ailleurs par confirmation Adam/event)."""
    try:
        import digest_roi
    except Exception as e:
        print("digest_roi indisponible:", e)
        return 1
    ok = send(token, chat, digest_roi.formater_digest())
    print("Digest ROI envoye." if ok else "Echec de l'envoi du digest ROI.")
    return 0 if ok else 1


def format_jury_nogo() -> str:
    """Alerte 'defaut de fond' : le cerveau A produit un radar, mais le jury de
    clarte le rejette encore APRES la tentative d'auto-reparation (raccourcir les
    champs trop longs ne suffit pas -> le probleme est dans le FOND, pas la forme :
    ex. move star sans insight, que l'auto-reparateur ne peut jamais inventer).
    Distinct de l'analyse muette (aucun radar produit) : ici il EXISTE mais il est
    refuse. Comme envoi-echoue, radar.json reste sur disque (pas archive)."""
    return "\n".join([
        "🧠🚫 <b>THE WIRE - RADAR REJETE PAR LE JURY</b>",
        "<i>L'analyse a produit un radar, mais le jury de clarte le refuse encore apres auto-reparation.</i>",
        "━━━━━━━━━━━━━━━",
        "",
        "Ce n'est <b>pas</b> un jour calme : un radar existe, il ne passe pas le controle qualite.",
        "<b>Cause probable :</b> un defaut de FOND (ex. un move star sans insight - l'auto-reparateur",
        "raccourcit les textes trop longs, mais n'invente jamais un contenu manquant).",
        "",
        "👉 <code>data/radar.json</code> a ete CONSERVE (pas archive) : regarde",
        "<code>data/veille.log</code> pour le detail du rejet, corrige si besoin,",
        "relance <code>python systeme/jury_clarte.py data/radar.json</code>.",
    ])


def envoyer_jury_nogo(token: str, chat: str) -> int:
    """Mode --jury-nogo : alerte qu'un radar produit a ete rejete par le jury de
    clarte meme apres auto-reparation (appele par lancer_veille.bat sur NO-GO
    persistant - jusqu'ici une panne totalement silencieuse, corrige suite au
    jury produit de la vague 2B)."""
    ok = send(token, chat, format_jury_nogo())
    print("Alerte jury-nogo envoyee." if ok else "Echec de l'alerte jury-nogo (reseau probablement mort).")
    return 0 if ok else 1


def main() -> int:
    mode_incident = "--incident" in sys.argv
    mode_analyse_morte = "--analyse-morte" in sys.argv
    mode_envoi_echoue = "--envoi-echoue" in sys.argv
    mode_jury_nogo = "--jury-nogo" in sys.argv
    mode_roi = "--roi" in sys.argv
    cfg = load_config()
    token = cfg.get("telegram_bot_token", "")
    chat = str(cfg.get("telegram_chat_id", ""))
    if not token or not chat:
        print("Token ou chat_id manquant dans config.local.json.")
        return 1
    if mode_analyse_morte:
        return envoyer_analyse_morte(token, chat)
    if mode_envoi_echoue:
        return envoyer_envoi_echoue(token, chat)
    if mode_jury_nogo:
        return envoyer_jury_nogo(token, chat)
    if mode_roi:
        return envoyer_digest_roi(token, chat)
    if mode_incident:
        return envoyer_incident(token, chat)
    if not RADAR.exists():
        print("Pas de data/radar.json - rien a envoyer (lance d'abord l'analyse).")
        return 0
    radar = json.loads(RADAR.read_text(encoding="utf-8"))
    # Option : ne RIEN envoyer un jour vide (silence total). Ici on envoie le "rien de neuf".
    text = format_radar(radar)
    ok = send(token, chat, text)
    print("Radar envoye sur The Wire." if ok else "Echec de l'envoi.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

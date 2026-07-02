#!/usr/bin/env python3
"""
envoyer_telegram.py — Pousse le radar du jour sur Telegram (bot The Wire).

Lit le token + chat_id depuis config.local.json (LOCAL, jamais sur GitHub),
formate le radar (data/radar.json) en message lisible, et l'envoie.

Usage : python systeme/envoyer_telegram.py
Robuste : si pas de radar.json ou radar vide -> message "rien de neuf" (ou silence).
"""
from __future__ import annotations
import json
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


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.local.json absent — pas de Telegram configuré.")
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
    forme (nom, texte_ouvrant_complet) — ex. ('blockquote', '<blockquote expandable>').
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


def send(token: str, chat: str, html: str) -> bool:
    """Envoie en HTML riche. Si > limite, découpe sur les FRONTIERES DE BLOCS
    (</blockquote>), JAMAIS au milieu d'une balise — sinon Telegram refuse
    ('can't find end tag'). Deux filets par-dessus : _equilibrer_balises referme et
    rouvre toute balise a cheval sur une frontiere, et _refendre_si_trop_long
    garantit qu'aucun morceau ne depasse jamais 4096, meme si un seul bloc est
    enorme (gros <pre>). Chaque appel HTTP est re-essaye sur erreur transitoire
    (_appel_api) ; un echec definitif rend False -> code retour 1 du script."""
    chunks = []
    if len(html) <= TG_LIMIT:
        chunks = [html]
    else:
        # Frontieres SURES = fin d'un move (</blockquote>) : jamais au milieu d'une
        # balise <pre>/<blockquote>. On coupe apres un </blockquote> quand le buffer
        # approche la limite.
        blocs = []
        reste = html
        marqueur = "</blockquote>"
        while marqueur in reste:
            i = reste.index(marqueur) + len(marqueur)
            blocs.append(reste[:i])
            reste = reste[i:]
        if reste:
            blocs.append(reste)
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


# Pastille colorée par projet (repère visuel rapide)
DOT = {"blue": "🔵", "teal": "🟢", "purple": "🟣", "coral": "🟠", "amber": "🟡", "gray": "⚪"}


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
    """Le DÉPLIÉ d'un move. Ordre voulu : POURQUOI + DO NOW d'abord (ce qui compte),
    puis le plan complet (steps) en secondaire, puis ensuite/aussi_pour."""
    out = []
    if m.get("pourquoi_maintenant"):
        out.append(f"<b>Pourquoi maintenant :</b> {esc(m['pourquoi_maintenant'])}")
        out.append("")
    if m.get("do_now"):
        out.append("<b>👉 Fais ça maintenant :</b>")
        out.append(esc(m["do_now"]))
        out.append("")
    # Plan complet (secondaire) — chaque texte-a-coller en <pre> (copie propre mobile)
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
                out.append(f"✓ <i>{esc(s['done'])}</i>")
            out.append("")
    if m.get("ensuite"):
        out.append(f"➡️ <b>Ensuite :</b> {esc(m['ensuite'])}")
    if m.get("aussi_pour"):
        out.append(f"♻️ <b>Aussi pour :</b> {esc(m['aussi_pour'])}")
    return out


def format_radar(radar: dict, pwa_url: str = "https://arochab.github.io/agent-veille/") -> str:
    """Radar -> Telegram. LIMPIDE : chaque move = title ultra-direct (le PLI) ; le
    déplié montre POURQUOI + DO NOW d'abord, plan complet ensuite. Tout est repliable
    pour que le fil reste scannable en 3 secondes."""
    L = []
    date = esc(radar.get("date", ""))
    moves = radar.get("moves", [])

    # Style B : on aère avec des lignes vides (2 entre moves), zéro séparateur lourd.
    L.append(f"📡 <b>THE WIRE</b>  ·  <i>{date}</i>")
    if not moves:
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
        L.append("<i>— The Wire</i>")
        return "\n".join(L)
    if radar.get("headline"):
        L.append("")
        L.append(f"<i>{esc(radar['headline'])}</i>")

    # Move du jour en premier (rank=star), puis les autres par ordre du radar.
    star_move = next((m for m in moves if m.get("rank") == "star"), moves[0])
    ordered = [star_move] + [m for m in moves if m is not star_move]

    for m in ordered:
        dot = DOT.get(m.get("ramp", "gray"), "⚪")
        star = "⭐️ " if m.get("rank") == "star" else ""
        L.append("")
        L.append("")   # gros espace entre les moves (style B)
        # LE PLI : titre ultra-direct (suffit à décider) + projet discret
        L.append(f"{dot} {star}<b>{esc(m.get('title',''))}</b>")
        if m.get("projet"):
            L.append(f"<i>{esc(m.get('projet',''))}</i>")
        # LE DÉPLIÉ : pourquoi + do now + plan, replié
        detail = _detail_move(m)
        if detail:
            body = "\n".join(x for x in detail).strip()
            L.append(f"<blockquote expandable>{body}</blockquote>")

    if radar.get("skill_up"):
        L.append("")
        L.append("")
        L.append("🎓 <b>Cette semaine :</b> " + f"<i>{esc(radar['skill_up'])}</i>")

    # Suivi des go déjà lancés : où on en est, prouvé, formulé net (juste avant le pied).
    suivi = _section_suivi_go()
    if suivi:
        L.append("")
        L.append(suivi)

    L.append("")
    L.append("")
    L.append(f'📲 <a href="{pwa_url}">Radar complet</a>')
    L.append("<i>— The Wire · ton fil, chaque matin</i>")
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
        "🧠⚠️ <b>THE WIRE — ANALYSE MUETTE</b>",
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
        "📡⚠️ <b>THE WIRE — ENVOI ECHOUE</b>",
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


def main() -> int:
    mode_incident = "--incident" in sys.argv
    mode_analyse_morte = "--analyse-morte" in sys.argv
    mode_envoi_echoue = "--envoi-echoue" in sys.argv
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
    if mode_roi:
        return envoyer_digest_roi(token, chat)
    if mode_incident:
        return envoyer_incident(token, chat)
    if not RADAR.exists():
        print("Pas de data/radar.json — rien a envoyer (lance d'abord l'analyse).")
        return 0
    radar = json.loads(RADAR.read_text(encoding="utf-8"))
    # Option : ne RIEN envoyer un jour vide (silence total). Ici on envoie le "rien de neuf".
    text = format_radar(radar)
    ok = send(token, chat, text)
    print("Radar envoye sur The Wire." if ok else "Echec de l'envoi.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

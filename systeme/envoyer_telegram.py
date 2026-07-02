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
import urllib.request
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG = ROOT / "config.local.json"
RADAR = ROOT / "data" / "radar.json"
SIGNAUX = ROOT / "data" / "signaux_frais.json"
TG_LIMIT = 4096  # limite Telegram par message


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


def _refendre_si_trop_long(chunk: str) -> list:
    """FILET DE SECURITE : garantit qu'aucun morceau ne depasse TG_LIMIT, meme si un
    seul bloc (un move a gros <pre>, ou la queue) est enorme. On coupe sur la frontiere
    sure la plus tardive avant la limite : un saut de ligne HORS balise. En dernier
    recours (aucun saut de ligne exploitable), coupe dure a un point hors balise.
    Sans ce filet, Telegram renvoie HTTP 400 et TOUT le radar est perdu silencieusement."""
    if len(chunk) <= TG_LIMIT:
        return [chunk]
    out = []
    reste = chunk
    while len(reste) > TG_LIMIT:
        # cherche le dernier '\n' avant la limite qui ne soit pas dans une balise
        coupe = -1
        for i in range(TG_LIMIT - 1, 0, -1):
            if reste[i] == "\n" and not _dans_une_balise(reste, i):
                coupe = i
                break
        if coupe <= 0:
            # aucun saut de ligne sur : recule jusqu'a sortir de toute balise
            coupe = TG_LIMIT - 1
            while coupe > 0 and _dans_une_balise(reste, coupe):
                coupe -= 1
            if coupe <= 0:
                coupe = TG_LIMIT - 1  # abandon : coupe dure (cas pathologique)
        out.append(reste[:coupe])
        reste = reste[coupe:].lstrip("\n")
    if reste:
        out.append(reste)
    return out


def send(token: str, chat: str, html: str) -> bool:
    """Envoie en HTML riche. Si > limite, découpe sur les FRONTIERES DE BLOCS
    (</blockquote>), JAMAIS au milieu d'une balise — sinon Telegram refuse
    ('can't find end tag'). Un FILET (_refendre_si_trop_long) garantit en plus qu'aucun
    morceau ne depasse jamais 4096, meme si un seul bloc est enorme (gros <pre>)."""
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
    # FILET : un bloc unique peut lui-meme depasser 4096 (gros <pre>, longue queue).
    # On re-fend chaque chunk survivant sur une frontiere sure. Aucun envoi > limite.
    chunks = [c for chunk in chunks for c in _refendre_si_trop_long(chunk)]
    for chunk in chunks:
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": chunk, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        try:
            r = json.load(urllib.request.urlopen(req, timeout=20))
            if not r.get("ok"):
                print("Erreur Telegram:", r.get("description"))
                return False
        except urllib.error.HTTPError as e:
            print("HTTP", e.code, e.read().decode("utf-8", "replace"))
            return False
        except Exception as e:
            print("Echec envoi:", e)
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

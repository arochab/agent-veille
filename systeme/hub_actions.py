#!/usr/bin/env python3
"""
hub_actions.py - The Wire CONSOMME les actions d'Adam venues du hub Second Cerveau.

Quand Adam touche un bouton "Go move N" dans la PWA du hub, le hub ecrit
atomiquement un fichier dans second-cerveau/data/actions/wire/*.json (contrat
HUB-OUTBOX-CONTRAT.md section 6.2). Le poller (executer_move.py --watch) appelle
`traiter_actions_hub()` a chaque tour : on lit ces fichiers, on resout le move
cible, et on lance le MEME pipeline qu'un "go N" Telegram - le hub devient une
2e source d'entree, Telegram reste le filet.

Regles du contrat appliquees ici (section 6.3) :
- On LIT le dossier du hub, on n'ecrit JAMAIS dedans (un seul ecrivain par dossier :
  c'est le hub). Notre curseur d'ids traites vit dans NOTRE repo.
- Livraison AU MOINS UNE FOIS -> idempotence par `id` de fichier action : un
  fichier deja vu = on ne refait rien. Deuxieme filet : la cle (message_id,
  action_id) et le go_traites.json existant dedoublonnent au niveau metier.
- Fichier invalide (JSON casse, champ manquant) : ignore + journalise, jamais de
  plantage. Le hub ecrit atomiquement donc un fichier partiel ne devrait pas
  exister, mais on ne fait pas confiance aveuglement.
- Le hub purge les actions apres 14 j : notre curseur peut oublier les vieux ids.

Anti-collision avec Telegram : deux entrees (Telegram + hub) partagent le MEME
go_traites.json (via la cle date|move_id dans traiter_go). Un "go 1" tape sur
Telegram puis clique dans la PWA ne lance qu'une fois : le 2e est refuse par
go_deja_traite. C'est le comportement voulu.

Zero dependance (stdlib). Ne leve jamais vers le poller : une action hub qui
echoue ne doit pas tuer le poller Telegram.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"

# Racine de l'atelier -> le repo du hub est un voisin (contrat : chemins relatifs
# a la racine Adam CHABBI Pro). On lit SEULEMENT, jamais d'ecriture cote hub.
ATELIER_ROOT = ROOT.parent
HUB_ACTIONS = ATELIER_ROOT / "second-cerveau" / "data" / "actions" / "wire"

# Notre curseur d'idempotence, dans NOTRE repo (jamais chez le hub).
CURSEUR = DATA / "hub_actions_traitees.json"
CURSEUR_MAX = 500  # on ne garde pas un historique infini (le hub purge a 14 j)

try:
    from atomic_io import write_json_atomic
except ImportError:
    sys.path.insert(0, str(HERE))
    from atomic_io import write_json_atomic


def _log(msg: str) -> None:
    """Journalise dans data/executer_move.log (meme journal que le poller)."""
    try:
        ligne = f"{datetime.now():%Y-%m-%d %H:%M:%S}  [hub] {msg}\n"
        with (DATA / "executer_move.log").open("a", encoding="utf-8") as fh:
            fh.write(ligne)
    except Exception:
        pass


def _charger_curseur() -> list:
    try:
        v = json.loads(CURSEUR.read_text(encoding="utf-8"))
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _marquer_traite(curseur: list, action_id: str) -> None:
    """Ajoute action_id au curseur (borne a CURSEUR_MAX, on jette les plus vieux)."""
    if action_id in curseur:
        return
    curseur.append(action_id)
    if len(curseur) > CURSEUR_MAX:
        del curseur[: len(curseur) - CURSEUR_MAX]
    write_json_atomic(CURSEUR, curseur)


def _resoudre_numero_move(move_id: str, date_radar: str, dernier_radar_fn,
                          moves_ordonnes_fn, radar_date_fn, mid_fn) -> int | None:
    """Traduit un move_id (paye par le hub) en NUMERO de move (1..k) dans le
    radar courant, pour reutiliser traiter_go tel quel. Renvoie None si le
    move_id n'est pas dans le radar du jour (radar regenere, id perime...).

    mid_fn(move) doit reproduire EXACTEMENT le calcul d'id de traiter_go
    (move._id sinon 'projet-title' normalise) : c'est la meme identite qu'un
    go Telegram, garantie par la fonction pretee par le poller.

    On s'appuie sur le radar archive le plus recent (comme un go Telegram). Si
    date_radar est fourni et ne correspond pas au radar courant, on refuse : on
    ne lance jamais un vieux move sur un nouveau radar (securite, coherence)."""
    path, radar = dernier_radar_fn()
    if radar is None:
        return None
    if date_radar and radar_date_fn(radar, path) != str(date_radar):
        return None
    for i, m in enumerate(moves_ordonnes_fn(radar), 1):
        if str(mid_fn(m)) == str(move_id):
            return i
    return None


def traiter_actions_hub(token: str, chat: str, traiter_go_fn,
                        dernier_radar_fn, moves_ordonnes_fn, radar_date_fn,
                        mid_fn) -> int:
    """Lit les fichiers d'action du hub, lance les go correspondants (via
    traiter_go_fn, la MEME fonction que Telegram). Renvoie le nombre d'actions
    reellement traitees ce tour. Ne leve jamais.

    Les fonctions du poller sont passees en parametres (dernier_radar, etc.) pour
    eviter tout import circulaire : hub_actions ne connait pas executer_move, c'est
    executer_move qui l'appelle en lui pretant ses helpers."""
    if not HUB_ACTIONS.exists():
        return 0  # le hub n'a pas encore ecrit d'action : cout nul, silencieux.
    n = 0
    curseur = _charger_curseur()
    curseur_set = set(curseur)
    try:
        fichiers = sorted(HUB_ACTIONS.glob("*.json"))
    except Exception:
        return 0
    for f in fichiers:
        aid = f.stem
        if aid in curseur_set:
            continue  # idempotence : deja traite (livraison au moins une fois)
        try:
            act = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            _log(f"action illisible ignoree : {f.name}")
            continue
        if not isinstance(act, dict) or act.get("action_id") is None:
            _log(f"action invalide (champ manquant) ignoree : {f.name}")
            continue

        payload = act.get("payload") or {}
        move_id = payload.get("move_id")
        date_radar = payload.get("date_radar", "")
        if not move_id:
            # action sans move_id : rien a lancer cote Wire, on marque traite pour
            # ne pas la relire indefiniment.
            _log(f"action sans move_id, ignoree : {act.get('id', f.name)}")
            _marquer_traite(curseur, aid)
            curseur_set.add(aid)
            continue

        numero = _resoudre_numero_move(
            move_id, date_radar, dernier_radar_fn, moves_ordonnes_fn, radar_date_fn, mid_fn)
        if numero is None:
            _log(f"move_id {move_id!r} absent du radar courant (date={date_radar!r}) : "
                 f"action {act.get('id', f.name)} marquee traitee sans lancer.")
            _marquer_traite(curseur, aid)
            curseur_set.add(aid)
            continue

        _log(f"action hub {act.get('id', f.name)} -> go {numero} (move_id={move_id}).")
        try:
            # MEME pipeline que Telegram : accuse de reception, Fable, Sonnet.
            # go_deja_traite (dans traiter_go) empeche un double lancement si le
            # meme move a deja ete lance par Telegram. Marquer AVANT le lancement :
            # une action rejouee (curseur perdu) ne relancera pas (go_traites la bloque),
            # et on ne boucle jamais sur une action qui ferait planter traiter_go.
            _marquer_traite(curseur, aid)
            curseur_set.add(aid)
            traiter_go_fn(token, chat, numero)
            n += 1
        except Exception as e:
            _log(f"echec traitement action {act.get('id', f.name)} : {e!r}")
    return n

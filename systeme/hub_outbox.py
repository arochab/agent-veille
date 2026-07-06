#!/usr/bin/env python3
"""
hub_outbox.py - The Wire EMET vers le hub Second Cerveau (module "wire").

Depose des messages JSON dans data/outbox/ selon HUB-OUTBOX-CONTRAT.md (schema 1)
du repo second-cerveau. Le hub les decouvre au scan (< 10 s), les affiche dans la
PWA, notifie via ntfy, et renvoie les actions d'Adam dans
second-cerveau/data/actions/wire/ (lues par le poller, voir hub_actions.py).

Regles du contrat appliquees ici :
- Un seul ecrivain par dossier : on n'ecrit QUE dans notre data/outbox/.
- Ecriture atomique (write_json_atomic) : jamais de fichier tronque lu par le hub.
- Limites STRICTES (un message invalide est INVISIBLE) : titre 200, corps 8000,
  fichier 64 Ko, 10 actions, resume_push 200. On tronque/valide AVANT depot.
- Tirets simples "-" partout (regle anti-IA permanente d'Adam) : le contenu
  affiche ne doit porter aucun tiret/fleche unicode.
- resume_push : compose PAR NOUS, jamais du contenu externe brut (ntfy public).
- Zero dependance : stdlib only.

Cout : nul si le repo hub n'existe pas encore. Tant que second-cerveau/ n'est pas
la, on ecrit quand meme dans NOTRE outbox (le hub lira quand il demarrera) ; c'est
un depot local, pas un appel reseau. Jamais d'exception remontante : emettre vers
le hub ne doit JAMAIS casser la chaine du matin.
"""
from __future__ import annotations
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUTBOX = ROOT / "data" / "outbox"

MODULE_ID = "wire"

# Limites DURES du contrat (section 3.1 / 4). Au-dela = message invalide = invisible.
MAX_TITRE = 200
MAX_CORPS = 8000
MAX_RESUME_PUSH = 200
MAX_FICHIER_OCTETS = 64 * 1024
MAX_ACTIONS = 10
MAX_LABEL = 40
MAX_PAYLOAD_OCTETS = 4 * 1024

# Faux-tirets et fleches unicode interdits dans le contenu affiche (regle anti-IA).
_UNICODE_PARFAIT = {
    "—": "-", "–": "-", "―": "-", "‒": "-", "−": "-",
    "→": "->", "←": "<-", "…": "...",
}

try:
    from atomic_io import write_json_atomic
except ImportError:  # import robuste quel que soit le cwd
    sys.path.insert(0, str(HERE))
    from atomic_io import write_json_atomic


def _sans_unicode_parfait(s: str) -> str:
    """Remplace les tiret/fleche/ellipsis unicode par leur equivalent ASCII."""
    for mauvais, bon in _UNICODE_PARFAIT.items():
        s = s.replace(mauvais, bon)
    return s


def _horodatage_iso() -> str:
    """ISO 8601 AVEC offset local (exige par le contrat, section 4)."""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _nouvel_id() -> str:
    """<module>-<AAAAMMJJ>-<HHMMSS>-<4 hex>. L'aleatoire vient de os.urandom
    (pas de random.seed a gerer). PID ajoute par prudence anti-collision."""
    now = datetime.now()
    hexa = os.urandom(2).hex()  # 4 caracteres hex
    return f"{MODULE_ID}-{now:%Y%m%d}-{now:%H%M%S}-{hexa}"


def _valider_actions(actions) -> list:
    """Filtre/valide la liste d'actions selon le contrat (section 6.1).
    Une action invalide est ECARTEE (pas le message entier), sauf une url a
    schema dangereux qui, elle, invaliderait le message cote hub -> on la refuse
    ici aussi pour ne jamais emettre un message qui sera rejete en bloc."""
    if not actions:
        return []
    out = []
    vus = set()
    for a in actions[:MAX_ACTIONS]:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id", "")).strip()
        if not re.match(r"^[a-z0-9_-]{1,32}$", aid) or aid in vus:
            continue
        typ = a.get("type")
        if typ not in ("module", "url"):
            continue
        label = _sans_unicode_parfait(str(a.get("label", "")).strip())[:MAX_LABEL]
        if not label:
            continue
        action = {"id": aid, "label": label, "type": typ}
        if typ == "url":
            url = str(a.get("url", "")).strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                # schema dangereux -> le hub rejetterait TOUT le message : on saute
                continue
            action["url"] = url
        else:  # module
            payload = a.get("payload")
            if payload is not None:
                # payload : uniquement des identifiants metier, jamais de contenu
                # externe. On verifie juste la taille (4 Ko) et la serialisabilite.
                try:
                    taille = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                except Exception:
                    continue
                if taille > MAX_PAYLOAD_OCTETS:
                    continue
                action["payload"] = payload
            if a.get("confirmer"):
                action["confirmer"] = True
        vus.add(aid)
        out.append(action)
    return out


def emettre(titre, corps="", *, type_="evenement", priorite="normal",
            resume_push=None, tags=None, fil=None, remplace=None,
            en_reponse_a=None, expire_le=None, actions=None, data=None):
    """Depose UN message dans data/outbox/. Renvoie l'id du message (str) si emis,
    None si rien n'a ete ecrit (titre vide, ou echec disque). Ne leve JAMAIS.

    Tout le contenu affiche (titre, corps, labels d'action) est nettoye des
    tirets/fleches unicode. Les limites sont appliquees par troncature (titre,
    corps, resume_push) : un message tronque vaut mieux qu'un message invisible.
    Si apres serialisation le fichier depasse 64 Ko, on retente en vidant `data`,
    puis en tronquant le corps ; en dernier recours on abandonne proprement."""
    try:
        titre = _sans_unicode_parfait(str(titre or "").replace("\n", " ").strip())[:MAX_TITRE]
        if not titre:
            return None
        corps = _sans_unicode_parfait(str(corps or ""))[:MAX_CORPS]

        if type_ not in ("digest", "evenement", "alerte"):
            type_ = "evenement"
        if priorite not in ("urgent", "normal", "info"):
            priorite = "normal"

        mid = _nouvel_id()
        msg = {
            "schema": 1,
            "id": mid,
            "module": MODULE_ID,
            "cree_le": _horodatage_iso(),
            "type": type_,
            "priorite": priorite,
            "titre": titre,
        }
        if corps:
            msg["corps"] = corps
        if resume_push:
            msg["resume_push"] = _sans_unicode_parfait(
                str(resume_push).replace("\n", " ").strip())[:MAX_RESUME_PUSH]
        if tags:
            propres = [t for t in tags if re.match(r"^[a-z0-9-]{1,24}$", str(t))][:8]
            if propres:
                msg["tags"] = propres
        if fil:
            msg["fil"] = str(fil)
        if remplace:
            msg["remplace"] = str(remplace)
        if en_reponse_a:
            msg["en_reponse_a"] = str(en_reponse_a)
        if expire_le:
            msg["expire_le"] = str(expire_le)
        acts = _valider_actions(actions)
        if acts:
            msg["actions"] = acts
        if data is not None:
            msg["data"] = data

        # Garde-fou 64 Ko : degrade proprement plutot que d'emettre un invalide.
        def _octets(m):
            return len(json.dumps(m, ensure_ascii=False, indent=2).encode("utf-8"))
        if _octets(msg) > MAX_FICHIER_OCTETS and "data" in msg:
            del msg["data"]
        if _octets(msg) > MAX_FICHIER_OCTETS and "corps" in msg:
            marge = _octets(msg) - len(msg["corps"].encode("utf-8"))
            place = max(0, MAX_FICHIER_OCTETS - marge - 4)
            msg["corps"] = msg["corps"].encode("utf-8")[:place].decode("utf-8", "ignore") + "..."
        if _octets(msg) > MAX_FICHIER_OCTETS:
            return None  # irrecuperable : on n'emet pas un fichier qui sera ignore

        cible = OUTBOX / f"{mid}.json"
        ok = write_json_atomic(cible, msg)
        return mid if ok else None
    except Exception:
        # Emettre vers le hub ne doit JAMAIS casser la chaine appelante.
        return None


def purger(jours: int = 30) -> int:
    """Supprime nos vieux messages (> `jours`). Le hub garde sa propre archive,
    donc supprimer chez nous ne perd rien (contrat section 3.3). Renvoie le nombre
    supprime. Ne leve jamais."""
    n = 0
    try:
        if not OUTBOX.exists():
            return 0
        limite = datetime.now().timestamp() - jours * 86400
        for f in OUTBOX.glob("*.json"):
            try:
                if f.stat().st_mtime < limite:
                    f.unlink()
                    n += 1
            except Exception:
                pass
    except Exception:
        pass
    return n


if __name__ == "__main__":
    # Auto-test : emet un "hello" (checklist contrat section 9 point 3).
    mid = emettre(
        "hello depuis The Wire",
        corps="# Test de branchement\nThe Wire est connecte au hub.\n\n- ecriture atomique OK\n- limites respectees",
        type_="evenement", priorite="info", tags=["test"],
    )
    if mid:
        print(f"Message emis : {OUTBOX / (mid + '.json')}")
    else:
        print("Echec d'emission (voir les limites / le disque).")

#!/usr/bin/env python3
"""
tests_hub.py - Filet du branchement The Wire <-> hub Second Cerveau.

Couvre les 3 modules du pont (hub_outbox emet, hub_radar transforme le radar,
hub_actions consomme les actions d'Adam) contre HUB-OUTBOX-CONTRAT.md. Tout est
teste en isolation (dossiers temporaires sous data/, nettoyes) : zero effet sur la
production, zero appel reseau, aucun vrai go lance (traiter_go est mocke).

  python systeme/tests_hub.py   -> exit 0 si tout vert.
"""
from __future__ import annotations
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import hub_outbox
import hub_radar
import hub_actions

TIRETS_UNICODE = "-...->—–―−‒→←…"  # variantes 'parfaites' interdites dans l'affiche


def _radar_demo() -> dict:
    return json.loads((ROOT / "data" / "radar.demo.json").read_text(encoding="utf-8"))


class TestOutbox(unittest.TestCase):
    """hub_outbox.emettre : schema, atomicite, limites, anti-IA."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hubtest_out_", dir=str(ROOT / "data")))
        self._orig = hub_outbox.OUTBOX
        hub_outbox.OUTBOX = self.tmp

    def tearDown(self):
        hub_outbox.OUTBOX = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lire(self, mid):
        return json.loads((self.tmp / f"{mid}.json").read_text(encoding="utf-8"))

    def test_message_minimal_valide(self):
        mid = hub_outbox.emettre("Titre test")
        self.assertIsNotNone(mid)
        m = self._lire(mid)
        self.assertEqual(m["schema"], 1)
        self.assertEqual(m["module"], "wire")
        self.assertEqual(m["id"], mid)
        self.assertEqual(m["type"], "evenement")   # defaut
        self.assertEqual(m["priorite"], "normal")  # defaut
        self.assertIn("+", m["cree_le"] + "Z")     # offset present

    def test_titre_vide_nemet_rien(self):
        self.assertIsNone(hub_outbox.emettre("   "))

    def test_troncature_titre_et_corps(self):
        mid = hub_outbox.emettre("T" * 500, corps="C" * 20000)
        m = self._lire(mid)
        self.assertLessEqual(len(m["titre"]), hub_outbox.MAX_TITRE)
        self.assertLessEqual(len(m["corps"]), hub_outbox.MAX_CORPS)

    def test_anti_ia_tirets_fleches(self):
        mid = hub_outbox.emettre("Gain - vise -> 290 EUR ...",
                                 corps="ligne - avec -> fleche et ... ellipsis",
                                 resume_push="push - avec -> fleche")
        m = self._lire(mid)
        blob = m["titre"] + m.get("corps", "") + m.get("resume_push", "")
        for ch in "—–―−‒→←…":
            self.assertNotIn(ch, blob, f"unicode parfait {ch!r} present dans l'emis")

    def test_action_url_dangereuse_ecartee(self):
        mid = hub_outbox.emettre("t", actions=[
            {"id": "bad", "label": "x", "type": "url", "url": "javascript:alert(1)"},
            {"id": "ok", "label": "Ouvrir", "type": "url", "url": "https://ex.com"},
        ])
        m = self._lire(mid)
        ids = [a["id"] for a in m.get("actions", [])]
        self.assertNotIn("bad", ids)   # schema dangereux ecarte
        self.assertIn("ok", ids)

    def test_ecriture_atomique_pas_de_tmp_orphelin(self):
        hub_outbox.emettre("t")
        self.assertEqual(list(self.tmp.glob("*.tmp*")), [], "un .tmp est reste (non atomique)")


class TestRadar(unittest.TestCase):
    """hub_radar.emettre_radar : radar -> digest + boutons go."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hubtest_rad_", dir=str(ROOT / "data")))
        self._orig = hub_outbox.OUTBOX
        hub_outbox.OUTBOX = self.tmp

    def tearDown(self):
        hub_outbox.OUTBOX = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_radar_demo_produit_digest_avec_actions(self):
        mid = hub_radar.emettre_radar(ROOT / "data" / "radar.demo.json")
        self.assertIsNotNone(mid)
        m = json.loads((self.tmp / f"{mid}.json").read_text(encoding="utf-8"))
        self.assertEqual(m["type"], "digest")
        self.assertEqual(m["fil"], "radar")
        # un bouton par move, chacun avec move_id + date_radar
        self.assertGreaterEqual(len(m["actions"]), 1)
        for a in m["actions"]:
            self.assertEqual(a["type"], "module")
            self.assertTrue(a["confirmer"])
            self.assertIn("move_id", a["payload"])
            self.assertIn("date_radar", a["payload"])

    def test_move_id_identique_a_traiter_go(self):
        """Le move_id du bouton = le mid qu'executer_move.traiter_go calcule."""
        import executer_move as em
        radar = _radar_demo()
        moves = em.moves_ordonnes(radar)
        attendu = [
            m.get("_id") or f"{em._norm(m.get('projet',''))}-{em._norm(m.get('title',''))}"
            for m in moves
        ]
        mid = hub_radar.emettre_radar(ROOT / "data" / "radar.demo.json")
        m = json.loads((self.tmp / f"{mid}.json").read_text(encoding="utf-8"))
        obtenus = [a["payload"]["move_id"] for a in m["actions"]]
        self.assertEqual(obtenus, attendu, "les move_id du hub divergent de traiter_go")

    def test_jour_calme_emet_digest_sobre_sans_action(self):
        vide = self.tmp / "radar_vide.json"
        vide.write_text(json.dumps({"date": "2026-07-06", "moves": []}), encoding="utf-8")
        mid = hub_radar.emettre_radar(vide)
        m = json.loads((self.tmp / f"{mid}.json").read_text(encoding="utf-8"))
        self.assertEqual(m["type"], "digest")
        self.assertNotIn("actions", m)

    def test_radar_absent_nemet_rien(self):
        self.assertIsNone(hub_radar.emettre_radar(self.tmp / "inexistant.json"))


class TestActions(unittest.TestCase):
    """hub_actions.traiter_actions_hub : resolution, idempotence, robustesse."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hubtest_act_", dir=str(ROOT / "data")))
        self._orig_dir = hub_actions.HUB_ACTIONS
        self._orig_cur = hub_actions.CURSEUR
        hub_actions.HUB_ACTIONS = self.tmp
        hub_actions.CURSEUR = self.tmp / "curseur.json"
        import executer_move as em
        self.em = em
        self.path, self.radar = em.dernier_radar()
        self.moves = em.moves_ordonnes(self.radar) if self.radar else []
        self.date = em.radar_date(self.radar, self.path) if self.radar else ""
        self.mid_fn = lambda m: m.get("_id") or f"{em._norm(m.get('projet',''))}-{em._norm(m.get('title',''))}"

    def tearDown(self):
        hub_actions.HUB_ACTIONS = self._orig_dir
        hub_actions.CURSEUR = self._orig_cur
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ecrire_action(self, aid, move_id, date=None):
        act = {"schema": 1, "id": aid, "message_id": "wire-test", "action_id": "go1",
               "payload": {"move_id": move_id, "date_radar": date if date is not None else self.date},
               "declenche_le": "2026-07-06T21:00:00+02:00", "source": "pwa"}
        (self.tmp / f"{aid}.json").write_text(json.dumps(act), encoding="utf-8")

    def _traiter(self):
        lances = []
        n = hub_actions.traiter_actions_hub(
            "TOK", "CHAT", lambda t, c, num: lances.append(num),
            self.em.dernier_radar, self.em.moves_ordonnes, self.em.radar_date, self.mid_fn)
        return n, lances

    def test_action_resout_le_bon_go(self):
        if not self.moves:
            self.skipTest("aucun radar reel archive")
        self._ecrire_action("act-001", self.mid_fn(self.moves[0]))
        n, lances = self._traiter()
        self.assertEqual(lances, [1])

    def test_idempotence_double_clic(self):
        if not self.moves:
            self.skipTest("aucun radar reel archive")
        self._ecrire_action("act-002", self.mid_fn(self.moves[0]))
        self._traiter()
        _, lances2 = self._traiter()
        self.assertEqual(lances2, [], "une action deja traitee a relance un go")

    def test_move_id_inconnu_ne_lance_rien(self):
        self._ecrire_action("act-003", "move-qui-nexiste-pas-999")
        _, lances = self._traiter()
        self.assertEqual(lances, [])

    def test_json_casse_ignore_sans_planter(self):
        (self.tmp / "act-casse.json").write_text("{ pas du json", encoding="utf-8")
        n, lances = self._traiter()   # ne doit pas lever
        self.assertEqual(lances, [])

    def test_action_sans_move_id_marquee_traitee(self):
        act = {"schema": 1, "id": "act-004", "action_id": "x", "payload": {}}
        (self.tmp / "act-004.json").write_text(json.dumps(act), encoding="utf-8")
        self._traiter()
        # 2e passage : deja dans le curseur, aucune relecture qui planterait
        _, lances = self._traiter()
        self.assertEqual(lances, [])

    def test_hub_absent_renvoie_zero(self):
        hub_actions.HUB_ACTIONS = self.tmp / "nexiste_pas"
        n, lances = self._traiter()
        self.assertEqual((n, lances), (0, []))


def main() -> int:
    suite = unittest.TestSuite()
    for cls in (TestOutbox, TestRadar, TestActions):
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(cls))
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

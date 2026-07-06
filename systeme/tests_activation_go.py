#!/usr/bin/env python3
"""
tests_activation_go.py — Filet dedie au levier "Telegram - l'instant du go : conviction
avant, zero silence pendant, cash apres" (brief renforcement Activation, 2026-07-06).

POURQUOI un fichier SEPARE de systeme/tests.py : meme raison que tests_plan_go.py
(tests.py est un ORGANE VITAL protege par hash dans immunite.py ; le modifier
casserait sa signature et ferait basculer immunite.exiger_sain() en BLOQUE pour tout
le systeme). Ce fichier teste :
  (1) envoyer_telegram._gain_du_titre (miroir Python de extractVerdict, pwa/app.js) ;
  (2) envoyer_telegram.format_radar : CTA en 2 lignes, pipeline nomme, delai derive
      de PLAN_GO_TIMEOUT_S, gain recopie (ou absent si pas de € dans le titre) ;
  (3) executer_move.traiter_go : accuse de reception IMMEDIAT avant tout appel au
      planificateur Fable (zero silence), messages finaux enrichis (gain + do_now +
      cloture fait/paye) dans les deux branches (plan Fable pose / repli direct).

Stdlib pure (unittest, monkey-patch), zero appel reseau, zero vrai `claude`, zero
VS Code ouvert, zero ecriture data/ non restauree. Console ASCII (Windows).
  python systeme/tests_activation_go.py   -> exit 0 si tout vert, 1 sinon.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import envoyer_telegram as et  # noqa: E402
import executer_move as em  # noqa: E402

TIRETS_UNICODE = "—–―−‒"


def _sans_tiret_unicode(s: str) -> bool:
    return not any(c in s for c in TIRETS_UNICODE)


def _move_test(projet="proj-factice", title="Titre du move test", do_now="fais X"):
    return {
        "projet": projet,
        "title": title,
        "pourquoi_maintenant": "un fait test",
        "insight": "un insight test",
        "do_now": do_now,
        "steps": [{"t": "etape 1", "how": "comment", "paste": "", "done": "fini quand..."}],
        "ensuite": "",
        "meta": "1h",
        "_id": "proj-factice-titre-du-move-test",
    }


# ------------------------------------------------------------------------------
# (1) _gain_du_titre — miroir de extractVerdict (pwa/app.js)
# ------------------------------------------------------------------------------

class TestGainDuTitre(unittest.TestCase):
    def test_montant_simple(self):
        self.assertEqual(et._gain_du_titre("Gagne ~290€ : ton app BrandPulse peut deja vendre"),
                         "~290€")

    def test_montant_avec_suffixe_mois(self):
        self.assertEqual(et._gain_du_titre("Rapporte 1200€/mois si tu fais X"), "~1200€/mois")

    def test_montant_milliers(self):
        g = et._gain_du_titre("Encaisse 1 200€ ce mois-ci")
        self.assertTrue(g.startswith("~1200€") or g.startswith("~1 200€"),
                         f"gain inattendu : {g!r}")

    def test_aucun_montant_rend_vide(self):
        self.assertEqual(et._gain_du_titre("3 apps copient la tienne cette semaine"), "")

    def test_titre_vide_rend_vide(self):
        self.assertEqual(et._gain_du_titre(""), "")
        self.assertEqual(et._gain_du_titre(None), "")

    def test_jamais_de_tiret_unicode(self):
        g = et._gain_du_titre("Gagne ~290€ : ton app")
        self.assertTrue(_sans_tiret_unicode(g))


# ------------------------------------------------------------------------------
# (2) format_radar — CTA en 2 lignes, pipeline nomme, delai derive, gain recopie
# ------------------------------------------------------------------------------

class TestCTAFormatRadar(unittest.TestCase):
    def test_cta_deux_lignes_avec_gain(self):
        radar = {
            "date": "2026-07-06",
            "moves": [dict(_move_test(title="Gagne ~290€ : fais ceci maintenant"), rank="star")],
        }
        txt = et.format_radar(radar)
        self.assertIn('Réponds « go 1 »', txt)
        self.assertIn("Fable pose le plan", txt)
        self.assertIn("Sonnet exécute", txt)
        self.assertIn("~290€", txt)
        # Delai derive de PLAN_GO_TIMEOUT_S (8 min par defaut), jamais un chiffre en dur different.
        delai_attendu = max(1, round(em.PLAN_GO_TIMEOUT_S / 60))
        self.assertIn(f"{delai_attendu} min", txt)

    def test_cta_sans_montant_ne_cite_rien(self):
        radar = {
            "date": "2026-07-06",
            "moves": [dict(_move_test(title="Un move star sans chiffre"), rank="star")],
        }
        txt = et.format_radar(radar)
        self.assertIn("Fable pose le plan", txt)
        self.assertIn("Sonnet exécute", txt)
        # Aucune invention : pas de '€' invente dans la ligne CTA quand le titre n'en a pas.
        ligne_cta = [l for l in txt.split("\n") if "Fable pose le plan" in l][0]
        self.assertNotIn("€", ligne_cta)

    def test_jamais_de_tiret_unicode_dans_le_cta(self):
        radar = {
            "date": "2026-07-06",
            "moves": [dict(_move_test(title="Gagne ~50€ maintenant"), rank="star")],
        }
        txt = et.format_radar(radar)
        self.assertTrue(_sans_tiret_unicode(txt), "aucun tiret unicode ne doit apparaitre")

    def test_radar_demo_produit_un_cta_complet(self):
        """Rendu sur les vraies donnees demo (data/radar.demo.json, lecture seule)."""
        demo = ROOT / "data" / "radar.demo.json"
        if not demo.exists():
            self.skipTest("radar.demo.json absent")
        import json
        radar = json.loads(demo.read_text(encoding="utf-8"))
        txt = et.format_radar(radar)
        self.assertIn("Fable pose le plan", txt)
        self.assertTrue(_sans_tiret_unicode(txt))


# ------------------------------------------------------------------------------
# (3) traiter_go — accuse de reception immediat + messages finaux enrichis
# ------------------------------------------------------------------------------

class TestAccuseDeReceptionImmediat(unittest.TestCase):
    """L'accuse de reception doit partir AVANT lancer_planificateur_fable (zero
    silence pendant les jusqu'a 8 min de l'appel Fable synchrone)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="thewire_activation_", dir=str(ROOT / "data")))
        self._move_backup = None
        if em.MOVE_POUR_PLAN.exists():
            self._move_backup = em.MOVE_POUR_PLAN.read_bytes()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._move_backup is not None:
            em.MOVE_POUR_PLAN.write_bytes(self._move_backup)
        elif em.MOVE_POUR_PLAN.exists():
            em.MOVE_POUR_PLAN.unlink()

    def test_accuse_avant_appel_fable(self):
        radar = {"date": "2026-07-06",
                  "moves": [dict(_move_test(title="Gagne ~290€ : fais ceci"), rank="star")]}
        ordre = []  # trace l'ordre reel des evenements

        def _tg_send(token, chat, text):
            ordre.append(("tg_send", text))
            return True

        def _fable(move, projet_dir):
            ordre.append(("fable_appele", None))
            return True, ""

        def _lancer_claude(projet_dir, prompt_file, md_file="", plan_go_ok=False):
            ordre.append(("lancer_claude", plan_go_ok))

        orig = {
            "tg_send": em.tg_send, "dernier_radar": em.dernier_radar,
            "resoudre_dossier": em.resoudre_dossier, "lancer_claude": em.lancer_claude,
            "go_deja_traite": em.go_deja_traite, "marquer_go_traite": em.marquer_go_traite,
            "lancer_planificateur_fable": em.lancer_planificateur_fable,
        }
        em.tg_send = _tg_send
        em.dernier_radar = lambda: (Path("radar_test.json"), radar)
        em.resoudre_dossier = lambda nom: (str(self.tmp), None)
        em.lancer_claude = _lancer_claude
        em.go_deja_traite = lambda cle: False
        em.marquer_go_traite = lambda cle, move=None, projet_dir="": None
        em.lancer_planificateur_fable = _fable
        try:
            em.traiter_go("FAKE_TOKEN", "FAKE_CHAT", 1)
        finally:
            em.tg_send = orig["tg_send"]
            em.dernier_radar = orig["dernier_radar"]
            em.resoudre_dossier = orig["resoudre_dossier"]
            em.lancer_claude = orig["lancer_claude"]
            em.go_deja_traite = orig["go_deja_traite"]
            em.marquer_go_traite = orig["marquer_go_traite"]
            em.lancer_planificateur_fable = orig["lancer_planificateur_fable"]

        # Au moins un tg_send AVANT fable_appele -> l'accuse de reception part en premier.
        idx_premier_send = next(i for i, e in enumerate(ordre) if e[0] == "tg_send")
        idx_fable = next(i for i, e in enumerate(ordre) if e[0] == "fable_appele")
        self.assertLess(idx_premier_send, idx_fable,
                         f"l'accuse de reception doit partir AVANT l'appel Fable : {ordre}")

        premier_msg = ordre[idx_premier_send][1]
        self.assertIn("Recu", premier_msg)
        self.assertIn("move #1", premier_msg)
        self.assertIn("proj-factice", premier_msg)
        self.assertIn("~290€", premier_msg)
        self.assertIn("Fable planifie maintenant", premier_msg)
        self.assertTrue(_sans_tiret_unicode(premier_msg))

    def test_accuse_sans_montant_ne_cite_rien(self):
        radar = {"date": "2026-07-06",
                  "moves": [dict(_move_test(title="Un move sans chiffre"), rank="star")]}
        messages = []
        orig = {
            "tg_send": em.tg_send, "dernier_radar": em.dernier_radar,
            "resoudre_dossier": em.resoudre_dossier, "lancer_claude": em.lancer_claude,
            "go_deja_traite": em.go_deja_traite, "marquer_go_traite": em.marquer_go_traite,
            "lancer_planificateur_fable": em.lancer_planificateur_fable,
        }
        em.tg_send = lambda token, chat, text: (messages.append(text) or True)
        em.dernier_radar = lambda: (Path("radar_test.json"), radar)
        em.resoudre_dossier = lambda nom: (str(self.tmp), None)
        em.lancer_claude = lambda *a, **kw: None
        em.go_deja_traite = lambda cle: False
        em.marquer_go_traite = lambda cle, move=None, projet_dir="": None
        em.lancer_planificateur_fable = lambda move, projet_dir: (True, "")
        try:
            em.traiter_go("FAKE_TOKEN", "FAKE_CHAT", 1)
        finally:
            em.tg_send = orig["tg_send"]
            em.dernier_radar = orig["dernier_radar"]
            em.resoudre_dossier = orig["resoudre_dossier"]
            em.lancer_claude = orig["lancer_claude"]
            em.go_deja_traite = orig["go_deja_traite"]
            em.marquer_go_traite = orig["marquer_go_traite"]
            em.lancer_planificateur_fable = orig["lancer_planificateur_fable"]

        premier_msg = messages[0]
        self.assertIn("Recu", premier_msg)
        self.assertNotIn("€", premier_msg, "aucun montant invente si le titre n'en a pas")


class TestMessagesFinauxEnrichis(unittest.TestCase):
    """Les messages finaux (plan Fable pose / repli direct) doivent recopier gain +
    do_now + cloture fait/paye, en gardant mot pour mot la distinction honnete."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="thewire_activation_final_", dir=str(ROOT / "data")))
        self._move_backup = None
        if em.MOVE_POUR_PLAN.exists():
            self._move_backup = em.MOVE_POUR_PLAN.read_bytes()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._move_backup is not None:
            em.MOVE_POUR_PLAN.write_bytes(self._move_backup)
        elif em.MOVE_POUR_PLAN.exists():
            em.MOVE_POUR_PLAN.unlink()

    def _traiter_go_capture(self, radar, plan_go_retour):
        messages = []
        orig = {
            "tg_send": em.tg_send, "dernier_radar": em.dernier_radar,
            "resoudre_dossier": em.resoudre_dossier, "lancer_claude": em.lancer_claude,
            "go_deja_traite": em.go_deja_traite, "marquer_go_traite": em.marquer_go_traite,
            "lancer_planificateur_fable": em.lancer_planificateur_fable,
        }
        em.tg_send = lambda token, chat, text: (messages.append(text) or True)
        em.dernier_radar = lambda: (Path("radar_test.json"), radar)
        em.resoudre_dossier = lambda nom: (str(self.tmp), None)
        em.lancer_claude = lambda *a, **kw: None
        em.go_deja_traite = lambda cle: False
        em.marquer_go_traite = lambda cle, move=None, projet_dir="": None
        em.lancer_planificateur_fable = lambda move, projet_dir: plan_go_retour
        try:
            em.traiter_go("FAKE_TOKEN", "FAKE_CHAT", 1)
        finally:
            em.tg_send = orig["tg_send"]
            em.dernier_radar = orig["dernier_radar"]
            em.resoudre_dossier = orig["resoudre_dossier"]
            em.lancer_claude = orig["lancer_claude"]
            em.go_deja_traite = orig["go_deja_traite"]
            em.marquer_go_traite = orig["marquer_go_traite"]
            em.lancer_planificateur_fable = orig["lancer_planificateur_fable"]
        return messages

    def test_message_final_plan_fable_pose(self):
        move = dict(_move_test(title="Gagne ~300€ maintenant", do_now="Envoie ce message au client X"),
                     rank="star")
        radar = {"date": "2026-07-06", "moves": [move]}
        messages = self._traiter_go_capture(radar, (True, ""))
        final = messages[-1]
        self.assertIn("~300€", final)
        self.assertIn("Premier euro", final)
        self.assertIn("Envoie ce message au client X", final)
        self.assertIn('"fait 1"', final)
        self.assertIn('"paye 1', final)
        # Distinction honnete gardee mot pour mot (jury du 2026-07-02).
        self.assertIn("Fable a deja depose un plan detaille", final)
        self.assertIn("attend ton OK", final)
        self.assertTrue(_sans_tiret_unicode(final))

    def test_message_final_repli_direct(self):
        move = dict(_move_test(title="Gagne ~150€ maintenant", do_now="Fais ceci en premier"),
                     rank="star")
        radar = {"date": "2026-07-06", "moves": [move]}
        messages = self._traiter_go_capture(radar, (False, "timeout"))
        final = messages[-1]
        self.assertIn("~150€", final)
        self.assertIn("Premier euro", final)
        self.assertIn("Fais ceci en premier", final)
        self.assertIn('"fait 1"', final)
        self.assertIn('"paye 1', final)
        # Distinction honnete gardee mot pour mot : repli direct, rien ecrit avant l'OK.
        self.assertIn("Plan Fable indisponible", final)
        self.assertIn("il n'ecrit rien avant ton OK", final)
        self.assertTrue(_sans_tiret_unicode(final))

    def test_do_now_long_est_tronque(self):
        do_now_long = "x" * 300
        move = dict(_move_test(title="Gagne ~10€", do_now=do_now_long), rank="star")
        radar = {"date": "2026-07-06", "moves": [move]}
        messages = self._traiter_go_capture(radar, (True, ""))
        final = messages[-1]
        # Le do_now complet (300 x) ne doit pas apparaitre integralement.
        self.assertNotIn(do_now_long, final)
        self.assertIn("...", final)

    def test_do_now_vide_omet_la_ligne_premier_euro(self):
        move = dict(_move_test(title="Gagne ~10€", do_now=""), rank="star")
        radar = {"date": "2026-07-06", "moves": [move]}
        messages = self._traiter_go_capture(radar, (True, ""))
        final = messages[-1]
        self.assertNotIn("Premier euro :", final)


class TestDoNowTronque(unittest.TestCase):
    def test_court_inchange(self):
        self.assertEqual(em._do_now_tronque("fais ceci"), "fais ceci")

    def test_long_tronque_sur_espace(self):
        s = "mot " * 60  # bien > 140
        r = em._do_now_tronque(s)
        self.assertLessEqual(len(r), 145)
        self.assertTrue(r.endswith("..."))
        self.assertFalse(r[:-3].endswith(" "))

    def test_vide(self):
        self.assertEqual(em._do_now_tronque(""), "")
        self.assertEqual(em._do_now_tronque(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

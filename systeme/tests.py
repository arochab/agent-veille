#!/usr/bin/env python3
"""
tests.py — LE FILET DE SECURITE de The Wire.

C'est la fondation de l'auto-amelioration : TANT QUE ces tests ne sont pas verts,
rien ne s'auto-modifie. Ils prouvent que les deux organes vitaux marchent encore :
  - le SCORING fait toujours passer le CASH avant la vanite (et reste deterministe),
  - le JURY bloque toujours le jargon / les actions floues.

Runner stdlib (unittest), < 2s, zero reseau, zero dependance. Console ASCII (Windows).
  python systeme/tests.py        -> exit 0 si tout vert, 1 sinon.

Quand l'auto-amelioration voudra changer quoi que ce soit, elle DEVRA d'abord
lancer ceci et obtenir 0. Un changement qui casse un test = refuse + rollback.
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import score_signal            # noqa: E402
from jury_clarte import juger_radar          # noqa: E402
import auto_sources                          # noqa: E402

TODAY = "2026-06-30"   # date fixe : les tests sont deterministes, pas lies a "maintenant"


def sig(canal="github", titre="x", resume="", projet="", date=TODAY, etoiles=0):
    return {"canal": canal, "titre": titre, "resume": resume,
            "projet": projet, "date": date, "etoiles": etoiles}


class TestScoring(unittest.TestCase):
    """Le scoring est l'organe qui oriente vers le cash. On verrouille son comportement."""

    def test_determinisme(self):
        # Meme entree + meme jour -> meme score, toujours. (proof-of-dev)
        s = sig(canal="reddit", titre="[HIRING] need GEO help, will pay", projet="serp-scraper")
        a = score_signal(s, TODAY)
        b = score_signal(s, TODAY)
        self.assertEqual(a, b, "Le score doit etre deterministe (meme entree -> meme sortie)")

    def test_bornes_0_100(self):
        # Quoi qu'on lui donne, le score reste dans [0, 100].
        for s in (sig(titre="[HIRING] will pay GEO ai visibility", projet="serp-scraper", etoiles=999),
                  sig(titre="", projet="", etoiles=0),
                  sig(titre="random", projet="inconnu", date="", etoiles=50000)):
            v = score_signal(s, TODAY)
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

    def test_cash_bat_vanite(self):
        # LE test cardinal : une vraie demande/argent fraiche DOIT battre
        # un repo geant mais vieux et hors-sujet. Le cash > la vanite sociale.
        cash = sig(canal="reddit", titre="[HIRING] need AI visibility / GEO, will pay freelance",
                   projet="serp-scraper", date=TODAY, etoiles=0)
        vanite = sig(canal="github", titre="awesome-list of random stuff",
                     projet="", date="2026-01-01", etoiles=50000)
        self.assertGreater(score_signal(cash, TODAY), score_signal(vanite, TODAY),
                           "Un signal cash frais doit TOUJOURS battre un repo geant vieux hors-sujet")

    def test_anti_keyword_stuffing(self):
        # Repeter un mot-cle 10x ne doit pas decupler le score (anti-gaming).
        une = sig(canal="reddit", titre="hiring GEO", projet="serp-scraper")
        dix = sig(canal="reddit", titre="hiring hiring hiring hiring hiring GEO GEO GEO GEO GEO",
                  projet="serp-scraper")
        # Tolerance : le bourrage ne doit pas faire gagner plus de quelques points.
        self.assertLessEqual(abs(score_signal(dix, TODAY) - score_signal(une, TODAY)), 6,
                             "Bourrer un mot-cle ne doit pas gonfler le score")

    def test_tier1_prioritaire(self):
        # A intention egale, un projet TIER1 (qui peut facturer) bat un TIER3 (pre-revenu).
        t1 = sig(canal="hackernews", titre="looking for LLM cost tool", projet="claude-eats-tokens")
        t3 = sig(canal="hackernews", titre="looking for design tool", projet="stratum")
        self.assertGreater(score_signal(t1, TODAY), score_signal(t3, TODAY),
                           "A intention egale, l'actif qui peut facturer doit primer")

    def test_fraicheur_compte(self):
        # Le meme signal, plus vieux, doit valoir moins (la fraicheur est un multiplicateur).
        frais = sig(canal="reddit", titre="[HIRING] GEO will pay", projet="serp-scraper", date=TODAY)
        vieux = sig(canal="reddit", titre="[HIRING] GEO will pay", projet="serp-scraper", date="2026-01-01")
        self.assertGreater(score_signal(frais, TODAY), score_signal(vieux, TODAY),
                           "Un signal frais doit valoir plus que le meme signal vieux")

    def test_overlay_cash_reste_roi(self):
        # COUCHE 2 : meme avec un overlay au MAXIMUM sur un projet pre-revenu, un vrai
        # signal d'argent doit TOUJOURS le battre. L'apprentissage ne deforme jamais
        # la priorite au cash. On ecrit un overlay temporaire et on nettoie.
        import json as _json
        import scoring as _sc
        overlay_path = Path(_sc.__file__).resolve().parent.parent / "data" / "poids_overlay.json"
        sauv = overlay_path.read_text(encoding="utf-8") if overlay_path.exists() else None
        try:
            overlay_path.parent.mkdir(parents=True, exist_ok=True)
            # bonus max (12) sur mixhub (tier3 pre-revenu)
            overlay_path.write_text(_json.dumps({"tier_bonus": {"mixhub": 12}}), encoding="utf-8")
            cash = sig(canal="reddit", titre="[HIRING] need GEO, will pay freelance",
                       projet="serp-scraper", date=TODAY)
            paye = sig(canal="reddit", titre="looking for DJ gear", projet="mixhub", date=TODAY)
            self.assertGreater(score_signal(cash, TODAY), score_signal(paye, TODAY),
                               "Un vrai signal argent doit battre un projet pre-revenu meme avec overlay max")
        finally:
            if sauv is None:
                try:
                    overlay_path.unlink()
                except Exception:
                    pass
            else:
                overlay_path.write_text(sauv, encoding="utf-8")


class TestJury(unittest.TestCase):
    """Le jury est le gardien de la clarte. On verrouille qu'il laisse passer le clair
    et bloque le confus."""

    def _radar(self, moves):
        return {"date": TODAY, "headline": "x", "moves": moves, "skill_up": "", "stats": {}}

    def test_jour_calme_est_go(self):
        # Un radar vide (rien de neuf) est un message legitime -> GO.
        self.assertTrue(juger_radar(self._radar([]))["go"])

    def test_move_clair_est_go(self):
        move = {"rank": "star", "projet": "BrandPulse",
                "title": "Gagne ~290 EUR avec ton app, il manque juste un prix",
                "pourquoi_maintenant": "3 repos ont copie l'idee cette semaine mais aucun ne facture.",
                "do_now": "Ajoute une ligne 'Rapport complet : 290 EUR' sur ta page."}
        self.assertTrue(juger_radar(self._radar([move]))["go"], "Un move clair doit etre GO")

    def test_jargon_est_no_go(self):
        move = {"rank": "star", "projet": "X", "title": "Leverage your wedge",
                "pourquoi_maintenant": "un fait date concret",
                "do_now": "fais l'action X concrete maintenant"}
        self.assertFalse(juger_radar(self._radar([move]))["go"], "Le jargon doit etre bloque")

    def test_phrase_creuse_est_no_go(self):
        move = {"rank": "star", "projet": "X", "title": "Vends ton rapport a 290 EUR",
                "pourquoi_maintenant": "le creneau est ouvert",
                "do_now": "ajoute un prix sur la page"}
        self.assertFalse(juger_radar(self._radar([move]))["go"], "Les phrases creuses doivent etre bloquees")

    def test_action_vide_est_no_go(self):
        move = {"rank": "star", "projet": "X", "title": "Vends ton rapport a 290 EUR",
                "pourquoi_maintenant": "un fait date concret du jour", "do_now": ""}
        self.assertFalse(juger_radar(self._radar([move]))["go"], "Un move sans action doit etre bloque")


class TestAutoSources(unittest.TestCase):
    """Couche 1 (auto-amelioration des sources). On verrouille les garde-fous durs :
    fallback sur la base figee, socle immortel, jury anti-jargon, determinisme.

    IMPORTANT : chaque test redirige auto_sources.MEM vers un fichier TEMPORAIRE.
    On ne touche JAMAIS au vrai data/sources_memoire.json, et on nettoie en tearDown."""

    BASE = {
        "serp-scraper": ["AI visibility GEO checker", "generative engine optimization tool"],
        "cuepoint": ["AI mixing assistant"],
    }
    ATELIER = {"projets": [{"nom": "serp-scraper"}, {"nom": "cuepoint"}]}

    def setUp(self):
        # MEM isole par test, dans un dossier temporaire dedie.
        self._mem_origine = auto_sources.MEM
        self._tmpdir = Path(tempfile.mkdtemp(prefix="thewire_test_"))
        auto_sources.MEM = self._tmpdir / "sources_memoire.json"

    def tearDown(self):
        # Restaure le vrai chemin et efface le dossier temporaire (et ses .bak/.tmp).
        auto_sources.MEM = self._mem_origine
        try:
            for f in self._tmpdir.iterdir():
                f.unlink()
            self._tmpdir.rmdir()
        except Exception:
            pass

    def test_fallback_sans_memoire(self):
        # Aucune memoire ecrite -> requetes_effectives renvoie EXACTEMENT base_figee.
        eff = auto_sources.requetes_effectives(self.ATELIER, self.BASE)
        self.assertEqual(eff, self.BASE,
                         "Sans memoire, la couche doit rendre exactement la base figee (fallback dur)")

    def test_fallback_memoire_corrompue(self):
        # Fichier memoire au JSON invalide -> fallback dur sur base_figee (jamais pire).
        auto_sources.MEM.write_text("{ ceci n'est : pas du json valide ]", encoding="utf-8")
        eff = auto_sources.requetes_effectives(self.ATELIER, self.BASE)
        self.assertEqual(eff, self.BASE,
                         "Memoire corrompue -> la couche doit retomber sur la base figee")

    def test_socle_jamais_banci(self):
        # LE garde-fou cardinal : une requete socle avec rendement NUL repete reste socle,
        # est toujours interrogee, et n'est jamais retrogradee/bancie.
        socle_q = "AI visibility GEO checker"
        frais_nuls = [{"projet": "serp-scraper", "requete": socle_q,
                       "score": 0, "canal": "github", "titre": "x", "resume": ""}]
        for _ in range(8):   # bien au-dela de RUNS_MIN_ACTIF / ESSAI_RUNS
            self.assertTrue(auto_sources.observer(frais_nuls, self.BASE),
                            "observer doit ecrire (memoire valide)")
        mem = json.loads(auto_sources.MEM.read_text(encoding="utf-8"))
        fiche = mem["projets"]["serp-scraper"][socle_q]
        self.assertEqual(fiche["etat"], "socle", "Le socle ne doit JAMAIS etre banci")
        # et il reste bien dans les requetes effectives
        eff = auto_sources.requetes_effectives(self.ATELIER, self.BASE)
        self.assertIn(socle_q, eff["serp-scraper"])

    def test_jury_rejette_jargon(self):
        # Une requete candidate avec du jargon est rejetee par jury_ok ;
        # une requete propre passe.
        self.assertFalse(auto_sources.jury_ok("leverage your moat"),
                         "Le jargon (leverage/moat) doit etre rejete")
        self.assertFalse(auto_sources.jury_ok("disruptive synergy paradigm"))
        self.assertTrue(auto_sources.jury_ok("r/forhire"))
        self.assertTrue(auto_sources.jury_ok("ai mixing assistant"))

    def test_candidate_jargon_non_introduite(self):
        # Bout en bout : un signal haut-score dont le bi-gramme porteur est du jargon
        # ne doit PAS introduire de requete candidate jargonneuse en memoire.
        frais = [{"projet": "serp-scraper", "requete": "AI visibility GEO checker",
                  "score": 90, "canal": "github",
                  "titre": "leverage moat", "resume": ""}]
        self.assertTrue(auto_sources.observer(frais, self.BASE))
        mem = json.loads(auto_sources.MEM.read_text(encoding="utf-8"))
        fiches = mem["projets"]["serp-scraper"]
        self.assertNotIn("leverage moat", fiches,
                         "Une candidate jargonneuse ne doit jamais entrer en memoire")

    def test_determinisme(self):
        # Meme (frais, memoire de depart) -> meme memoire en sortie, deux fois.
        frais = [{"projet": "serp-scraper", "requete": "AI visibility GEO checker",
                  "score": 80, "canal": "reddit", "titre": "hiring geo expert",
                  "resume": "r/forhire - 50 upvotes"}]
        memA = self._tmpdir / "a.json"
        memB = self._tmpdir / "b.json"
        auto_sources.MEM = memA
        self.assertTrue(auto_sources.observer(frais, self.BASE))
        auto_sources.MEM = memB
        self.assertTrue(auto_sources.observer(frais, self.BASE))
        self.assertEqual(memA.read_text(encoding="utf-8"),
                         memB.read_text(encoding="utf-8"),
                         "observer doit etre deterministe (meme entree -> meme memoire)")


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestScoring))
    suite.addTests(loader.loadTestsFromTestCase(TestJury))
    suite.addTests(loader.loadTestsFromTestCase(TestAutoSources))
    suite.addTests(loader.loadTestsFromTestCase(TestReste))
    suite.addTests(loader.loadTestsFromTestCase(TestApparier))
    suite.addTests(loader.loadTestsFromTestCase(TestImmuniteStructure))
    # Sortie ASCII-safe (Windows cp1252)
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    ok = result.wasSuccessful()
    print("\n" + ("FILET VERT - le systeme est sain, l'auto-amelioration peut tourner."
                  if ok else "FILET ROUGE - NE PAS auto-modifier. Reparer d'abord."))
    return 0 if ok else 1


class TestReste(unittest.TestCase):
    """Le bloc 'Reste' du suivi CLARIFIE le do_now sans JAMAIS inventer d'etape ni
    juger l'avancement. On verrouille l'anti-invention (exigence dure d'Adam)."""

    def _clair(self, do_now, entree=None):
        import suivi_go
        return " ".join(suivi_go._reste_clair(do_now, entree or {}))

    def _mots(self, s):
        import re
        return set(re.findall(r"[a-z0-9]{4,}", (s or "").lower()))

    def test_do_now_tronque_garde_ses_points(self):
        # Un do_now coupe a l'ecriture ('...') ne doit PAS etre complete (= invention).
        out = self._clair("Ouvre visual-engine-optimization (github.com/alan-g-friar)...")
        self.assertIn("...", out, "le '...' d'un do_now tronque doit etre conserve")
        self.assertIn("visual-engine-optimization", out)
        self.assertIn("alan-g-friar", out)

    def test_aucune_etape_ajoutee(self):
        # Tous les mots significatifs de la sortie viennent de l'entree (aucun mot invente).
        do_now = ("Ouvre https://github.com/omrikais/cctally et "
                  "jamesleoreyes/cc-usage-tracker-tracker - note ce qu ils font vs ta feature.")
        out = self._clair(do_now)
        # vocabulaire autorise = mots du do_now + mots du glossaire (explications legitimes)
        import suivi_go
        gloss = " ".join(suivi_go._GLOSSAIRE.values())
        autorises = self._mots(do_now) | self._mots(gloss) | self._mots("le la repo de page pourquoi")
        intrus = self._mots(out) - autorises
        self.assertEqual(intrus, set(), f"le Reste ne doit ajouter aucun mot hors do_now/glossaire : {intrus}")

    def test_chemin_fichier_pas_pris_pour_repo(self):
        # 'web/index.html.' (fichier en fin de phrase + point) ne doit PAS devenir 'le repo'.
        out = self._clair("Modifie web/index.html.")
        self.assertNotIn("le repo index", out.lower(),
                         "un chemin de fichier ne doit jamais etre reecrit en 'repo'")

    def test_cta_pas_transforme_en_repo(self):
        # Le glossaire CTA contient 'bouton ou phrase' (pas de '/') -> pas de faux repo.
        out = self._clair("Ajoute un CTA au README.")
        self.assertNotIn("le repo", out.lower(),
                         "expliciter CTA/README ne doit pas fabriquer un faux repo")

    def test_pas_de_fallback_meta_comme_pourquoi(self):
        # 'meta' (tag d'effort) ne doit JAMAIS etre presente sous le label 'pourquoi'.
        out = self._clair("Ouvre le dashboard.", {"meta": "1h - positionnement"})
        self.assertNotIn("pourquoi", out.lower(),
                         "meta n'est pas un 'pourquoi' : ne pas le citer sous ce label")

    def test_pourquoi_reel_cite_tel_quel(self):
        # Le vrai 'pourquoi_maintenant' du radar est cite (jamais genere).
        out = self._clair("Ouvre le repo.", {"pourquoi_maintenant": "3 repos GEO sortis cette semaine"})
        self.assertIn("pourquoi", out.lower())
        self.assertIn("cette semaine", out.lower())

    def test_do_now_vide_rend_vide(self):
        self.assertEqual(self._clair(""), "")

    def test_sigle_inconnu_non_devine(self):
        # Un sigle hors glossaire est laisse tel quel (jamais invente une signification).
        out = self._clair("Configure le XYZ.")
        self.assertIn("XYZ", out, "un sigle inconnu ne doit pas etre devine ni supprime")


class TestApparier(unittest.TestCase):
    """Le matching step<->commit ne doit JAMAIS declarer une etape 'faite' sur des mots
    generiques (repo, readme, page...). Anti-invention du bloc 'ce que le go a produit'."""

    def test_commit_generique_ne_matche_pas(self):
        # LE faux positif reel corrige : 'auditer le repo concurrent' ne doit PAS etre
        # prouve fait par un commit qui nettoie le PROPRE repo ('clean repo, rewrite readme').
        import suivi_go
        self.assertFalse(
            suivi_go._commit_matche_step(
                "Clean public repo: rewrite README, remove internal docs",
                "Auditer le repo concurrent",
                "Lis le README de visual-engine-optimization, note les features"),
            "un commit generique (repo+readme) ne doit jamais prouver un step precis")

    def test_deux_mots_generiques_insuffisants(self):
        # 'page' + 'pricing' seuls (generiques) ne prouvent pas un step.
        import suivi_go
        self.assertFalse(
            suivi_go._commit_matche_step(
                "Add pricing page layout", "Publier la page pricing", "cree la page"),
            "deux mots passe-partout ne suffisent pas a prouver un step")

    def test_mot_specifique_commun_matche(self):
        # Un mot SPECIFIQUE commun (ex 'heatmap') doit permettre le match.
        import suivi_go
        self.assertTrue(
            suivi_go._commit_matche_step(
                "feat: dual heatmap SERP + AI visibility",
                "Ajouter la heatmap SERP", "construis la heatmap comparative"),
            "un mot specifique commun (heatmap) doit prouver le step")

    def test_apparier_sans_digest_ne_fabrique_pas_de_fait(self):
        # Sans digest, un step sans commit/fichier reste 'inconnu', jamais 'fait'.
        import suivi_go
        steps = [{"t": "Auditer le repo concurrent", "how": "lis le readme"}]
        commits = [{"hash": "56ea1b3xyz", "message": "Clean public repo rewrite README"}]
        res = suivi_go._apparier_steps(steps, commits, None, "", "2026-07-01T18:00:00+02:00")
        self.assertEqual(res[0]["etat"], "inconnu",
                         "sans preuve reelle, un step ne doit jamais passer 'fait'")


class TestImmuniteStructure(unittest.TestCase):
    """Auto-protection du GARDIEN, SANS cycle : tests.py ne hash PAS immunite.py
    (un hash croise tests<->immunite serait impossible a signer : changer l'un
    changerait le hash de l'autre, a l'infini). A la place, on verrouille la
    STRUCTURE : la liste exacte des vitaux, le blocage reel sur alteration,
    l'alerte-sans-frein des sentinelles, et le fait que les references sont
    CODEES EN DUR (jamais lues depuis data/, que le systeme sait ecrire)."""

    # La liste canonique des 6 organes vitaux. Si quelqu'un en retire un
    # d'ATTENDUS (= le de-protege en douce), ce test devient rouge.
    VITAUX = {"tests.py", "jury_clarte.py", "scoring.py",
              "auto_sources.py", "feedback.py", "apprends_poids.py"}

    def setUp(self):
        # On neutralise le kill-switch pour ces tests : HALT pointe vers un chemin
        # temporaire INEXISTANT (jamais le vrai data/HALT.flag de production).
        import immunite
        self._halt_origine = immunite.HALT
        self._sha_origine = immunite._sha
        self._tmpdir = Path(tempfile.mkdtemp(prefix="thewire_immu_"))
        immunite.HALT = self._tmpdir / "HALT.flag"

    def tearDown(self):
        import immunite
        immunite.HALT = self._halt_origine
        immunite._sha = self._sha_origine
        try:
            for f in self._tmpdir.iterdir():
                f.unlink()
            self._tmpdir.rmdir()
        except Exception:
            pass

    def test_attendus_exactement_les_6_vitaux(self):
        # ATTENDUS contient EXACTEMENT les 6 cles vitales (ni plus, ni moins),
        # et chaque valeur a la forme d'un vrai sha256 (64 hexa, pas de placeholder).
        import re
        import immunite
        self.assertEqual(set(immunite.ATTENDUS.keys()), self.VITAUX,
                         "ATTENDUS doit couvrir exactement les 6 organes vitaux")
        for nom, h in list(immunite.ATTENDUS.items()) + list(immunite.SENTINELLES.items()):
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", h),
                            f"hash invalide pour {nom} (attendu : 64 caracteres hexa)")

    def test_vital_altere_bloque(self):
        # LE contrat cardinal : un vital altere => ok=False et exiger_sain() leve
        # SystemExit (le frein reel du systeme). halt reste False : halt est reserve
        # au kill-switch HALT.flag (semantique existante, verrouillee ici).
        import contextlib
        import io
        import immunite
        immunite._sha = lambda p: "0" * 64   # tous les fichiers paraissent alteres
        v = immunite.verifier()
        self.assertFalse(v["ok"], "un vital altere doit rendre ok=False (blocage)")
        self.assertFalse(v["halt"], "halt reste reserve au kill-switch HALT.flag")
        self.assertEqual(set(v["alteres"]), self.VITAUX)
        with self.assertRaises(SystemExit, msg="exiger_sain doit stopper net si un vital est altere"):
            with contextlib.redirect_stdout(io.StringIO()):
                immunite.exiger_sain()

    def test_sentinelle_alteree_avertit_sans_bloquer(self):
        # Une sentinelle alteree REMONTE (alteres_sentinelle) mais ne bloque RIEN :
        # ok reste True, halt False, alteres/manquants vides (compatibilite totale).
        import immunite
        vrai_sha = self._sha_origine
        cible = next(iter(immunite.SENTINELLES))
        immunite._sha = lambda p: ("0" * 64 if p.name == cible else vrai_sha(p))
        v = immunite.verifier()
        self.assertTrue(v["ok"], "une sentinelle alteree ne doit JAMAIS bloquer (ok reste True)")
        self.assertFalse(v["halt"])
        self.assertEqual(v["alteres"], [])
        self.assertIn(cible, v["alteres_sentinelle"],
                      "l'alteration d'une sentinelle doit etre remontee (alerte sans frein)")

    def test_halt_flag_gele_tout(self):
        # Le kill-switch : HALT.flag present => halt=True et ok=False, sans lister
        # de faux alteres (c'est un gel volontaire, pas une alteration).
        import immunite
        immunite.HALT.write_text("gel", encoding="utf-8")
        v = immunite.verifier()
        self.assertTrue(v["halt"])
        self.assertFalse(v["ok"])
        self.assertEqual(v["alteres"], [])

    def test_references_codees_en_dur_jamais_data(self):
        # PARADE anti-boucle : les references (ATTENDUS/SENTINELLES) doivent etre des
        # dicts LITTERAUX de constantes dans le source — donc impossibles a charger
        # depuis data/ (que le systeme peut ecrire) ou depuis n'importe quel fichier.
        import ast
        import immunite
        src = Path(immunite.__file__).read_text(encoding="utf-8")
        trouves = {}
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Assign):
                for cible in node.targets:
                    if isinstance(cible, ast.Name) and cible.id in ("ATTENDUS", "SENTINELLES"):
                        trouves[cible.id] = node.value
        self.assertEqual(set(trouves), {"ATTENDUS", "SENTINELLES"},
                         "ATTENDUS et SENTINELLES doivent etre assignes au niveau module")
        for nom, val in trouves.items():
            self.assertIsInstance(val, ast.Dict,
                                  f"{nom} doit etre un dict LITTERAL code en dur (pas charge d'un fichier)")
            for k in val.keys:
                self.assertIsInstance(k, ast.Constant, f"{nom} : cles litterales uniquement")
                self.assertNotIn("data/", str(k.value))
                self.assertNotIn("data\\", str(k.value))
            for v in val.values:
                self.assertIsInstance(v, ast.Constant,
                                      f"{nom} : chaque hash doit etre une constante litterale")


if __name__ == "__main__":
    sys.exit(main())

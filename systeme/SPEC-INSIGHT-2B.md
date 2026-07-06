# SPEC-INSIGHT-2B - champ optionnel `insight` par move dans `data/radar.json`

Statut : champ SPÉCIFIÉ et déjà demandé au LLM du matin (`systeme/prompt_analyse_auto.md`).
L'affichage Telegram n'est PAS branché : c'est le travail de l'équipe qui tient
`systeme/envoyer_telegram.py` (fichier hors périmètre de l'équipe 2B).

## 1. Pourquoi ce champ existe

`title` (≤95), `pourquoi_maintenant` (≤200) et `do_now` (≤240) sont saturés par leurs
rôles (gain, fait daté, action). L'exigence d'Adam - chaque move porte un VRAI insight
(fenêtre de marché, second ordre, avantage factuel) - n'avait pas de place dédiée.
`insight` la lui donne sans toucher aux limites du jury.

## 2. Contrat du champ

| Propriété | Valeur |
|---|---|
| Clé JSON | `insight` (au niveau du move, à côté de `pourquoi_maintenant`) |
| Type | string |
| Longueur | **≤ 160 caractères** (dur : tronquer à l'affichage si dépassé) |
| Présence | OPTIONNEL. Le prompt l'exige pour le move `rank="star"`, le recommande pour les autres. Un move sans `insight` reste valide. |
| Contenu | Ce que le signal révèle que les autres n'ont pas encore vu : timing, second ordre, ou avantage factuel d'Adam. Exprimé en faits, ne répète pas `pourquoi_maintenant`. |
| Hypothèses | Toute hypothèse non sourcée commence par « Pari : » (radar FR). Jamais une hypothèse déguisée en fait. |
| Registre | Mêmes interdits que le reste (phrases creuses, jargon brut) - voir §4, le jury ne surveille PAS ce champ. |

## 3. Preuve de compatibilité (décision « champ toléré » - vérifiée le 2026-07-02)

- **`systeme/jury_clarte.py`** (protégé, lu en l'état) : `juger_radar()` ne lit que
  `title`, `pourquoi_maintenant`, `do_now` (lignes ~74-101) ; la boucle phrases
  creuses/jargon (ligne ~104) itère uniquement sur ces trois champs. **Aucune
  whitelist de champs, aucun rejet d'une clé inconnue** -> un move portant `insight`
  passe le jury tel quel.
- **`systeme/envoyer_telegram.py`** : tous les accès aux moves sont des
  `m.get("...")` (ex. lignes ~283-305, ~338-349). Une clé non lue est simplement
  ignorée -> **zéro changement d'affichage tant que le branchement n'est pas fait**,
  zéro risque de crash.
- **`systeme/immunite.py` / `systeme/tests.py`** : les prompts et le format des moves
  ne sont ni protégés par hash ni figés par un test. `systeme/tests.py` reste vert
  (vérifié après modification des prompts).

Rétro-compatibilité totale : un radar SANS `insight` (anciens radars, jours calmes)
se comporte exactement comme avant.

## 4. Garde-fou registre (important pour l'équipe jury, si elle étend un jour)

Le jury actuel ne scanne pas `insight`. Le prompt du matin s'auto-impose les interdits
(phrases creuses, jargon brut, mots « ton angle/edge/asymétrie »), mais il n'y a pas de
filet déterministe. Extension FACULTATIVE proposée pour `jury_clarte.py` (à faire par
l'équipe qui le possède, jamais par 2B) :
- `INSIGHT_MAX = 160` ; bloquer si dépassé.
- Ajouter `("insight", insight)` à la boucle phrases creuses/jargon.
- NE PAS rendre le champ obligatoire : `insight` absent = GO (sinon les anciens radars
  et les moves secondaires casseraient).

## 5. Affichage Telegram proposé (pour l'équipe `envoyer_telegram.py`)

Position : entre `pourquoi_maintenant` et `do_now` (le fait -> ce qu'il implique -> l'action).

```
🔵 ⭐️ <b>{title}</b>
<i>{projet}</i>
{pourquoi_maintenant}
💡 <i>{insight}</i>          <- NOUVEAU, seulement si m.get("insight") est non vide
👉 {do_now}
...
```

Règles d'implémentation :
- `if m.get("insight"): L.append(f"💡 <i>{esc(m['insight'][:160])}</i>")` - même
  échappement HTML `esc()` que les autres champs (le texte vient d'un LLM qui a lu
  des données d'internet : l'échappement n'est pas optionnel).
- Tronquer à 160 caractères par sécurité même si le prompt promet ≤160.
- Champ absent ou vide -> ne rien afficher (pas de ligne vide, pas de 💡 orphelin).

## 6. Ce que 2B a livré (périmètre clos)

- `systeme/prompt_analyse_auto.md` : exige insight/cash-path/scale/« Pari : » par move,
  spécifie `insight` ≤160 dans le format et la structure JSON de sortie.
- `systeme/PROMPT_RADAR.md` : mêmes exigences adaptées au brief interactif (en anglais :
  « Bet: » ; l'insight vit dans la rubrique existante « Rivals miss », pas de champ JSON).
- Ce fichier.

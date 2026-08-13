# Prologue production plan — "Beyond the Wall"

The first hour of Hollow Crown, mapped from the gameplay script to the assets,
data and engine features it needs. 45–60 minutes of play.

This is the production checklist. The script is the creative source; this
document is what gets built and in what order.

---

## Status

| Layer | State |
| --- | --- |
| Script | Complete (Hollow Crown — Prologue Gameplay Script) |
| Asset catalogs | Complete — 60 assets defined, 1 generated and validated |
| Game data | Complete — 2 battles, 28 dialogue scenes, 12 flags, all cross-validated |
| Engine | Not started. See [ARCHITECTURE.md](../ARCHITECTURE.md) |

`python -m hollowasset validate-content` passes with zero errors.

---

## Source of truth: the script wins

**Decided by the director, 2026-08-13.** Where the master brief and the prologue
script disagree about the first hour, **the script is canonical.** Build what the
script says.

This rule exists because the two documents genuinely conflict, and a future
session reading brief section 69 alone would build the wrong thing:

| | Brief section 69 | Prologue script | Built |
| --- | --- | --- | --- |
| Duration | ~15 minutes | 45–60 minutes | Script |
| Party | Rowan, Maeve, knight ally, archer ally | Rowan, Maeve, Tomas (spear) | Script |
| Battles | One | Two | Script |
| Boss | Goblin commander | **Wallstalker** | Script |
| Enemies | 6–8 | 7 in battle 01 | Both agree |

Consequences, now settled rather than open:

1. **No archer in the prologue party.** `hero_archer_ally` is not in any catalog
   and should not be added.
2. **No goblin commander.** The prologue's boss is the Wallstalker. If a goblin
   commander is wanted later in Act I, it is new work, not prologue work.
3. **The vertical slice is the whole prologue**, not a 15-minute subset. Milestone
   10 is larger than brief section 69 implied, and it is a far better trailer.

Everywhere else the two documents agree, and where the script is silent the brief
still governs — polygon budgets, texture strategy, the turn system, the shared
skeleton, the save format. The precedence rule is scoped to the prologue's
content, not to the technical standards.

---

## Beat map

Scene numbers are the script's. Every asset id resolves to a catalog entry and
every data id to `Content/Data`.

| Beat | Assets | Data | Engine features |
| --- | --- | --- | --- |
| **01** Black screen, impacts, title text | — | `prologue_opening` | Title-card sequencer, screen shake, sfx |
| **02** Greenvale morning, Maeve wakes Rowan | Village kit, `set_crownwall_section`, `set_greenvale_castle_distant`, `prop_village_fountain`, `prop_chicken`, `hero_rowan`, `hero_maeve`, `weapon_training_sword_wood` | `greenvale_intro` | Third-person camera, NPC follower, music |
| **Explore** Old woman, child, barrels, well | `npc_villager_old_woman`, `npc_villager_child`, `npc_villager_blacksmith`, `prop_barrel_a` ✅ | `greenvale_old_woman`, `greenvale_child`, `greenvale_barrel_first`, `greenvale_well` | Interaction, inventory, flags |
| **03** Training yard, Aldric | `npc_aldric`, `npc_edrin`, `npc_guard_greenvale`, `prop_weapon_rack`, `prop_training_dummy`, `weapon_iron_sword` | `training_yard_aldric`, `training_yard_sword` | Equipment menu and stat display |
| **04** First assignment, party forms | `hero_tomas`, `weapon_soldier_spear` | `prologue_first_assignment` | Party management |
| **Gate** Guard's warning | `building_north_gate` | `greenvale_gate_guard` | Flags |
| **05** Outskirts, ambush spotted | `veg_tree_oak_a/b`, `veg_rock_a`, `prop_fence_section` | `prologue_ambush_spotted` | Sprint, optional pickups, scene transition |
| **BATTLE 01** North Meadow | `enemy_goblin_raider`, `enemy_goblin_spearman`, `enemy_goblin_archer`, `prop_merchant_cart_overturned`, goblin weapons | `battle_north_meadow` | **Grid, movement range, attack, magic, weapon range, height, mid-battle event, rewards** |
| **06** No merchant, human footprints, impacts | — | `prologue_after_battle`, `prologue_new_objective` | Investigation interaction, screen shake |
| **Path** Checkpoint, warm blade, blood | `prop_guard_checkpoint`, `prop_broken_sword` | `prologue_checkpoint` | Inspect interaction, music fade |
| **07** Watchtower, cracked Wall, voices | `set_watchtower`, `set_crownwall_breach` | `prologue_watchtower`, `prologue_voices` | Muffled dialogue styling, sfx |
| **Reveal** Refugees through the crack | `npc_refugee_man/woman/child`, `npc_refugee_leader` | `prologue_story_reveal` | Crowd decoration |
| **08** Varric, the choice | `npc_varric` | `prologue_varric_arrives`, `prologue_the_choice` | **Dialogue choice, tone flag** |
| **BATTLE 02** The Breach | `boss_wallstalker`, `set_crownwall_breach_collapsed` | `battle_the_breach` | **Non-lethal rule, hesitant AI, terrain mutation, mid-battle spawn, side switching, objective replacement, directional armour** |
| **09** Aldric arrives, "Run, boy" | — | `prologue_aldric_arrives` | Flags, objective change |
| **Escape** Tomas stays | — | `prologue_escape` | Real-time chase, party removal |
| **10** Forest overlook, the lights | `veg_cliff_rock_large` | `prologue_forest_overlook` | Camera rise, sunset lighting |
| **Title** | — | `prologue_title_card` | Title card, autosave, chapter transition |

✅ = generated and validated.

---

## What the prologue demands of the engine

Everything the first hour needs, in dependency order. Nothing here is optional,
and nothing outside it is needed for the prologue.

**Exploration:** third-person movement and camera, NPC followers, interaction
prompts, inventory pickups, scene transitions, sprint.

**Dialogue:** speaker portraits with expressions, narration lines with no
speaker, styled lines (title card, tutorial, system, inspect, muffled), a choice
with flag outcomes, sfx and screen-shake cues inline, and a dialogue log.

**Tactical battle:** grid from JSON, terrain costs and defence, height, movement
range, A\* pathing, weapon range, MP and skills, damage preview, turn order,
victory and defeat conditions, rewards, level-up.

**Scripted battle events, the demanding part:** turn-triggered and
state-triggered events, forced movement, flee-to-exit, terrain mutation
mid-battle, unit spawning mid-battle, side switching, AI reassignment, objective
replacement, rule removal, prop swapping, camera focus.

**Rules:** directional armour, non-lethal defeat, hesitant AI.

**World:** a flag system with typed and enumerated flags, autosave.

If the engine runs `battle_the_breach.json` correctly, brief section 42's
collapsing sandworm bridge is the same feature set with different data. That is
the main reason the prologue is worth building before anything else.

---

## Asset production

60 assets across four catalogs. Estimated **1,539 credits**; the account had
2,485 at the time of writing. Re-check with
`hollowasset generate <catalog> --dry-run` rather than trusting this number after
any catalog edit.

| Catalog | Assets | Credits |
| --- | --- | --- |
| `greenvale_props.json` | 12 | 240 |
| `prologue_cast.json` | 18 | 699 |
| `prologue_environment.json` | 20 | 400 |
| `prologue_weapons.json` | 10 | 200 |

### Recommended order

1. **`prologue_weapons.json` and the rest of `greenvale_props.json`.** Cheap,
   static, no rigging. Proves the pipeline at batch scale and fills the village.
2. **One character, all the way through.** Pick `npc_guard_greenvale` — it is
   reused for half a dozen roles, so it earns its cost immediately, and it is not
   a named character whose design needs approving. Rig it, bake all fourteen
   animation clips, watch them, and correct
   `Tools/hollowasset/animations.py`. **Do not generate the rest of the cast
   before this is done**: the action ids there are provisional, and getting them
   wrong across 18 characters means paying twice.
3. **The retargeting spike.** Second character, same clips, shared skeleton via
   Godot's `BoneMap`. Prove animation reuse works before scale.
4. **`prologue_environment.json`.** The Crownwall first — the whole prologue's
   composition depends on it reading as impossible, and that is worth iterating
   on early while credits are plentiful.
5. **Concept art for the named cast**, then `prologue_cast.json` via
   image-to-3d. Rowan, Maeve, Tomas, Aldric, Varric and the refugee leader are
   characters the player looks at for thirty hours. Text-to-3d blockouts are for
   testing the grid, not for shipping.

### The one hard dependency

`set_crownwall_breach` and `set_crownwall_breach_collapsed` must share a
silhouette and palette, because battle 02 swaps one for the other mid-fight.
Generate the cracked version first and use it as the visual reference for the
collapsed one, or the swap reads as a pop rather than a collapse.

---

## Numbers the script fixes

The script specifies exact values. The data is tuned to hold them, and these are
the regression targets:

- **Rowan's first attack deals 8.** Attack 8 + Iron Sword 3 − Raider defence 3.
- **Spark costs 3 MP, range 3.** Maeve's 12 MP gives four casts.
- **Spark kills a Raider in two casts.** Power 6 + magic 9 − resistance 1 = 14
  across two casts against 12 HP.
- **Tomas reaches two tiles.** Spear range 2.
- **Level-up shows HP +2, ATK +1, AGI +1.** Consistent with Rowan's growth rates.
- **Battle 01 loot: 20 gold and a Goblin Charm**, the latter shown as
  "Unknown Item".
- **The Wallstalker is level 3 with an armoured front and weak flanks.**
  Directional armour gives effective defence 14 front, 8 flank, 6 rear, so
  Rowan's 11 attack deals 1 from the front and 5 from behind. The lesson lands
  without tutorial text.
- **Post-prologue:** Rowan and Maeve at roughly level 2, Tomas unavailable, and
  six world flags set.

---

## Open content questions

1. **The archer ally and the goblin commander** — see the discrepancy above.
2. **Captain Heron** is named in scene 07 as an unconscious or dead officer. He
   currently reuses `npc_guard_greenvale`. If he matters later, he needs his own
   asset and a character entry.
3. **The Goblin Charm's reveal** has no setter yet. `goblin_charm_identified` is
   declared and the validator reports it as awaiting a writer, which is correct
   for now — the payoff belongs to a later chapter and should be assigned to one.
4. **Music** needs the Greenvale theme, an urgent variation of it, a battle
   theme, a tense variation and a quiet main theme. Brief section 50 wants one
   recognisable motif reused in every form, so the motif has to be written before
   any of these five, not extracted from them afterwards.
5. **Portraits.** 15 speakers × the expressions each actually uses. Currently
   referenced at `Content/UI/Portraits/` and not yet produced; the validator
   tracks the model paths but does not yet check portrait files.

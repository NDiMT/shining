# Hollow Engine — technology recommendation

Answers brief section 110. **Revision 2, and it reverses revision 1.**

Revision 1 recommended a custom C++20 engine on SDL3 and SDL_GPU, following brief
sections 9, 11 and 12. This revision recommends building on **Godot 4** with
**C#**, which is a deliberate deviation from the brief, made after the director
asked the question directly. The reasoning is below, including what the change
costs.

---

## Executive summary

| Decision | Recommendation |
| --- | --- |
| Engine | **Godot 4**, latest stable, version pinned in the repo |
| Renderer | Godot Forward+ on Vulkan; Compatibility as the low-spec fallback |
| Gameplay systems | **C#**, in a pure library with no Godot dependency |
| Scene glue, UI wiring, VFX timing | **GDScript** |
| Game data | Our own JSON in `Content/Data`, not Godot resources |
| 3D assets | glTF/GLB — Godot's native import format, pipeline unchanged |
| Animation retargeting | Godot 4 `BoneMap` + `SkeletonProfileHumanoid` |
| Debug tooling | The Godot editor and a small in-game dev console |
| Game UI | Godot `Control` nodes |
| Tests | `dotnet test` against the pure C# library |
| Steam | GodotSteam or Steamworks.NET behind a platform interface |
| Licence | MIT, no royalties, no per-title fee |

**The single most important architectural rule below:** the tactical and RPG
rules live in a C# library that does not reference Godot. Everything else follows
from that.

---

## Why Godot, and why the reversal

Revision 1 was the right answer to the question *"what is the smallest custom
engine that satisfies brief section 12?"* It was the wrong answer to *"how does
Hollow Crown ship?"*

Every goal brief section 9 lists is better served by Godot:

| Brief section 9 goal | Custom engine | Godot |
| --- | --- | --- |
| Fast iteration | Build, run, attach debugger | Hot reload, live scene editing, instant play |
| AI-assisted development | Every session must re-read our engine | Large public corpus; sessions arrive already knowing it |
| Simplicity | Five milestones before any gameplay | The section 70 loop at milestone 3 |
| Low-poly 3D | Write a renderer | Exactly Godot 4's competence |
| Steam release | Build a platform abstraction from nothing | Export templates and a maintained Steam binding |
| Long-term stability | Our bugs, our fixes, our time | Upstream fixes, and MIT source when we need our own |

Two passages in the brief itself argue for this:

- **Section 108:** "Hollow Engine is done enough when it can reliably support the
  complete game… The player never sees the engine. The engine exists to ship
  Hollow Crown." Godot satisfies that definition on day one.
- **Section 107:** "Whenever there is a choice between technically sophisticated
  but invisible to the player, and simple implementation that creates visible
  polish, prefer visible polish." A custom renderer is the definitive example of
  invisible sophistication.

And the decisive one. Revision 1 named **content volume as the risk most likely
to kill this project**: 25–40 hours, seven acts, 25–35 recruitable characters. A
custom engine makes that risk strictly worse, because it consumes exactly the
months the content needs. Recommending both a custom engine and content volume
as the top risk was not a coherent position.

### What this costs, stated plainly

- **It contradicts the brief.** Sections 9, 11 and 12 specify a custom C++20
  engine and name Godot as something not to become. This is the director's call,
  taken with that in front of us.
- **Shader compilation stutter.** Real in Godot 4. Mitigated by pre-warming
  materials during load screens, which the scene-based structure of brief
  section 66 already gives us natural places for.
- **Engine bugs we do not control.** Mitigated by MIT source, a pinned version,
  and GDExtension as an escape hatch for anything genuinely hot.
- **Version drift.** Godot minor releases have broken projects before. Pin the
  exact version, upgrade deliberately, never automatically.
- **It does not solve art direction.** The "generic asset game" risk of brief
  section 6 is unaffected by the engine. `docs/STYLE_GUIDE.md` is what addresses
  it.

### What it does not cost

The asset pipeline in `Tools/hollowasset` is unaffected. glTF is Godot's native
import format, so generated assets drop straight in. The validator becomes *more*
valuable, not less: Godot's importer will not fix a mis-scaled or Z-up model, it
will faithfully import the mistake.

---

## The architecture that matters: rules separate from presentation

```
/Game.Rules          pure C#, NO Godot reference
    Tactical/        grid, pathfinding, movement range, turn order
    Combat/          damage, criticals, elements, status effects
    RPG/             stats, levelling, promotion, equipment, inventory
    AI/              behaviour evaluation
    World/           flags, quests, party state
    Data/            JSON loading and the data contracts
    Save/            versioned serialisation and migration

/Game.Godot          Godot project, references Game.Rules
    Scenes/          battle, exploration, town, UI
    Presentation/    turning rule events into animation, camera, VFX, sound
    Input/
    Platform/        Steam behind an interface
```

`Game.Rules` must not reference Godot. That one constraint buys four things the
brief explicitly asks for:

- **Section 73, testing.** `dotnet test` runs the damage formulas, levelling,
  promotions, pathfinding, movement cost, inventory, status effects, save
  serialisation and quest flags with no engine, no window and no scene tree. Fast
  enough to run on every commit.
- **Section 74, determinism.** One seeded RNG service, injected. Never Godot's
  global randomness, never `Random` at call sites. A battle becomes reproducible
  from a seed plus an input log, which is what makes bug reports actionable.
- **Section 15, AI-friendliness.** A future session can read and change the
  combat rules without understanding the scene tree.
- **Reversibility.** If Godot ever becomes the wrong answer, the game's actual
  logic is portable. That is worth more than the control revision 1 was buying.

The rules layer emits events — `UnitMoved`, `DamageDealt`, `UnitDied`,
`ObjectiveChanged` — and the presentation layer subscribes and plays them back
with camera work, hit-stop and sound. This is also what makes brief section 92's
battle-speed options straightforward: fast mode changes playback, never rules.

### Language boundary

- **C#** for anything with a rule, a number, or a test.
- **GDScript** for scene glue, UI wiring, VFX and animation timing — code that
  is naturally written against the editor and changes constantly.

The boundary is: if it would be worth a unit test, it is C#.

---

## What Godot deletes from revision 1's plan

Work that no longer needs doing: renderer, SDL_GPU abstraction, HLSL toolchain
and DXIL build step, glTF loader, image loader, material system, skeleton and
skinned-mesh playback, animation blending, scene loading, audio mixer and buses,
collision primitives, immediate-mode UI layer, ImGui debug panels, and the math
library.

That is revision 1's milestones 1 through 4, and most of 8, gone.

**Godot 4's retargeting also directly addresses the second-biggest risk.**
Revision 1 flagged animation retargeting onto brief section 56's shared skeleton
as the most under-specified step in the pipeline, because Meshy rigs each model
individually. Godot 4 ships `BoneMap` and `SkeletonProfileHumanoid` for exactly
this: map each imported rig onto a canonical profile once, then share clips
across the cast. `validate.py` already enforces the canonical bone list and
carries an alias table, which is the groundwork.

It still needs proving on two different characters before the cast is generated.
It is no longer a research problem.

---

## Major technical risks

Reordered for this stack.

### 1. Content volume — still the risk that kills the project

25–40 hours, seven acts, 25–35 characters, towns and dungeons for each. Godot
buys months back; it does not change the arithmetic of content.

*Mitigation, unchanged and now more affordable:* treat the prologue as a
measurement instrument. It is fully specified and encoded as data
(`Content/Data`), so when it is playable, record what one finished hour actually
cost in hours and credits, multiply honestly, and size the act structure to what
that number supports. Brief section 100 permits exactly this.

### 2. Rules and presentation leaking into each other

The main way this architecture fails is gradually: a `Node3D` reference appears
in a combat class, then tests need a scene tree, then they stop being run.

*Mitigation:* make it mechanical. `Game.Rules` has no Godot package reference, so
a leak is a compile error rather than a judgement call. Enforce it in CI.

### 3. Shader compilation stutter

*Mitigation:* pre-warm materials during scene loads; measure frame times against
brief section 62's 60fps at 1080p target rather than assuming.

### 4. Save format migration

Unchanged from revision 1, and the reason to keep saves as our own JSON rather
than Godot resources: explicit `saveVersion`, an explicit migration chain, and
round-trip tests in the pure C# library. Brief section 46 calls the save system a
major subsystem and is right.

### 5. Godot version drift

*Mitigation:* pin the exact version, record it in `BUILDING.md`, upgrade on
purpose with the test suite as the gate.

### 6. Perceived AI-generated quality

Brief section 68's commercial risk, unchanged and engine-independent.
Consistency, not sophistication. The style guide and the validators enforce it
mechanically because taste applied per-asset over three years drifts.

---

## Repository structure

```
/Game.Rules/                pure C# library, no Godot
/Game.Godot/                Godot 4 project
    project.godot
    Scenes/  Presentation/  Input/  Platform/  UI/
/Content/
    Data/                   characters, classes, items, weapons, skills,
                            terrain, flags, Battles/, Dialogue/
    Models/                 generated GLBs by asset type
    References/             approved concept art
    Provenance/             assets.jsonl
    UI/                     portraits, icons
    Audio/                  Music/ SFX/ Ambience/
/Tools/
    hollowasset/            asset generation, validation, provenance
    catalog/                asset definitions
/Tests/                     Python tool tests
/Game.Rules.Tests/          C# rule tests
/docs/
```

`Content/Data` is deliberately outside the Godot project. It is the game's
content contract, edited by humans and AI sessions, validated by
`hollowasset validate-content`, and loaded at runtime rather than imported as
engine resources. Brief section 14 wants adding ten forest enemies to touch no
engine code; keeping the data out of Godot's import pipeline is what guarantees
it, and it keeps hot reload trivial.

---

## The smallest executable prototype

Brief section 70, unchanged, because it is still the right target:

```
window -> 3D scene -> camera -> ground -> one character -> battle grid
       -> select character -> highlight reachable tiles -> click tile
       -> character walks -> select enemy -> attack animation
       -> enemy loses HP -> enemy dies
```

Reached at **milestone 3** instead of milestone 5.

---

## Milestones

Each ends in something playable. No milestone is a refactor.

| # | Milestone | Done when |
| --- | --- | --- |
| 1 | **Skeleton.** Pinned Godot 4 project, `Game.Rules` library with no Godot reference, `dotnet test` in CI, seeded RNG service, structured logging | A window opens, the test suite runs green in CI, and CI fails if `Game.Rules` gains a Godot reference |
| 2 | **Data and assets.** JSON loaders for the whole `Content/Data` contract, GLB import, one scene with the pipeline's real barrel, tree and a character under a tactical camera | Prologue data loads and round-trips; generated assets render at correct scale and orientation |
| 3 | **Tactical grid — the prototype loop.** Grid from battle JSON, terrain costs, selection, A\*, movement range, attack, HP, death, debug overlays | **Brief section 70's loop runs end to end**, driven entirely by `battle_north_meadow.json` |
| 4 | **Combat systems.** Agility turn order, damage model, criticals, elements, status effects, rule-based AI including `hesitant` and directional armour, AI debug scores | Two AI sides fight to a conclusion with no input. All formulas unit-tested |
| 5 | **Battle presentation.** Battle HUD, damage preview, gamepad menus, attack camera, hit-stop, impact particles, layered sound, battle-speed options | A battle feels good, not merely correct. Brief sections 26, 27 and 92 |
| 6 | **Battle 01 shipped.** North Meadow playable from data, with tutorials, the fleeing spearman event and rewards | A stranger plays battle 01 unaided and understands grid, range, magic and height |
| 7 | **Exploration and dialogue.** Third-person Greenvale, NPCs, the full prologue dialogue set, chests, barrels, equipment tutorial, world flags | Greenvale is walkable and every optional interaction in the script works |
| 8 | **Battle 02 — dynamic objectives.** Non-lethal rule, hesitant AI, terrain mutation, mid-battle spawn, side switching, objective replacement, the Wallstalker | `battle_the_breach.json` runs its turn-3 event correctly. Brief section 41 proven, so section 42's collapsing bridge is reachable |
| 9 | **Save and world state.** Versioned saves with a migration chain and round-trip tests, autosave points, the prologue's closing flag state | Save mid-prologue, reload, continue. Post-prologue state matches the script |
| 10 | **Prologue complete.** Escape sequence, forest overlook, title card, music, VFX, polish | The first hour is playable start to finish and is trailer material |

Milestones 1–5 are engine and systems. From 6 onward the deliverable is the
prologue itself, which is why it was worth encoding as data first.

---

## What is not being built

Brief section 105, restated so it is checkable: no multiplayer, no live service,
no procedural worlds, no rigid-body physics beyond collision and raycasts, no ray
tracing, no facial mocap, no visual scripting layer of our own, no general
purpose editor, no mod support during initial development.

Deliberately deferred: ECS (Godot's node model plus plain C# structs is
sufficient at this scale, and brief section 82 agrees), threading beyond asset
loading, Lua (brief section 87 — our data-driven events already cover the
prologue's needs, including its dynamic objectives), and GDExtension.

---

## Decisions still open

1. **Godot version to pin.** Take the latest stable 4.x at milestone 1 and record
   it. Not a judgement call, but it must be written down rather than assumed.
2. **Steam binding: GodotSteam or Steamworks.NET.** Defer to milestone 9 or
   later. Brief section 67 says not to block core development on Steamworks, and
   the platform interface makes it a late, contained choice.
3. **Confirm saves stay as our own JSON** rather than Godot resources. This is
   the one place where the Godot-native path is tempting and, given brief section
   46's migration requirement, worse.
4. **Accept the milestone 2 retargeting spike** on two characters before the cast
   is generated, rather than discovering it at character twenty.
5. **Confirm the prologue doubles as the schedule measurement**, and that the act
   structure may shrink based on what it measures.

---

## Addendum, 2026-08-13: what building the battle scene changed

Milestone 3's scene exists (`docs/GODOT_SCENE.md`, which also records what is
verified and what still needs an editor). Three things about the architecture
above turned out to need stating rather than assuming.

### `Game.Rules` now owns the grid's metre scale

`Game.Rules/Tactical/GridLayout.cs` converts a `Coord` into a world-space point.
That looks like presentation in the rules layer and is not, for two reasons.
ANIME_DIRECTION.md rule 4 already fixes the coupling in the other direction —
"heights do not change, a hero is still 1.7m, because the tactical grid, the
movement costs and the camera all depend on it" — so a tile's size in metres is a
rule about the game. And it is the one part of the scene-building path that can be
tested without an engine, while being the part most likely to be silently wrong:
a mirrored battlefield still looks like a plausible battlefield.

It returns a plain `WorldPoint(float, float, float)` with no arithmetic on it.
The engine's vector type stays on the engine's side of the boundary.

The general rule this is an instance of: **when the presentation layer needs an
answer that can be expressed as a number or a set of coordinates, the answer
belongs in `Game.Rules`, because that is the half that has tests.** Movement range
was already there; attack range, threat range and prop placement joined it rather
than being written against the scene tree.

### Content outside `res://` has a cost, and it is paid at load

`Content/Data` being outside the Godot project was a deliberate choice above, and
it stands. What was not written down is that it applies to `Content/Models` too,
and Godot cannot reference a path above `res://` — so GLBs are parsed at runtime
with `GltfDocument` instead of going through the editor importer.

That means no import-time compression, no LOD generation, and parse cost on the
loading screen. It is the right trade today, because it keeps the content contract
as one tree that the Python tooling and the engine both read. If load time becomes
a problem, the fix is a build step that copies `Content/Models` into `res://` at
export — not moving the content back inside the project.

### The presentation layer is where the asset pipeline's failures surface

`docs/ASSET_PIPELINE.md` measured that generated assets arrive with scenery
attached, and that avoid tokens do not stop it. The engine is the last place that
can notice: it measures every model before adding it to the tree, removes mesh
nodes that measure like a ground slab, and reports the ones it cannot fix rather
than mangling them.

This is a general obligation of the presentation layer that the split above did
not anticipate. The rules layer is protected from asset problems by construction —
a battle plays identically whether nine props load or none, because what blocks a
unit is the terrain symbol and never the model. That protection is exactly why the
engine has to be loud: an asset defect can no longer break the game, so nothing
else will notice it.

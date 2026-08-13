# The battle scene

How to open and run the North Meadow battle, and — more importantly — **exactly
what about it has been verified and what has not.**

> **Read this first.** Godot could not be installed in the environment this scene
> was written in, so **the scene has never been run**. Every C# file here has been
> type-checked and every rule it calls is unit tested, but nothing in this
> document should be read as "it works". The last two sections separate the two
> honestly, and the checklist at the end is the fastest way for you to close the
> gap.

---

## Running it

**Prerequisites**

- Godot 4.3 **.NET** build (the C# one — the standard build cannot open this
  project). `Game.Godot.csproj` pins `Godot.NET.Sdk/4.3.0`, and
  `project.godot` declares feature `"4.3"`.
- .NET 8 SDK.

**Steps**

1. Open the Godot project manager and import `Game.Godot/project.godot`.
2. Let it build the C# solution when prompted, then press **F5**.
   `run/main_scene` is `res://Scenes/Battle.tscn`.
3. **Record the exact Godot version** (Help → About) in `docs/BUILDING.md`.
   ARCHITECTURE.md's open decision 1 asks for this, and version drift between
   4.x minor releases has broken projects before.

The scene expects to run from inside the repository: it walks up from `res://`
until it finds `Content/Data`, because that directory sits outside the Godot
project on purpose. An exported build will need `Content/` shipped alongside the
executable, which is a milestone 10 packaging job and is not done.

**Controls**

| Input | Does |
| --- | --- |
| Left click | Select a friendly unit; move it to a highlighted tile; attack an enemy in reach |
| Right click | Deselect |
| Arrow keys | Move the grid cursor, in screen directions rather than grid axes |
| Enter | The same as a left click, on the cursor's tile |
| Tab | Next friendly unit that has not acted, camera follows |
| Middle drag | Orbit |
| Wheel | Zoom |
| W A S D | Pan, relative to where the camera is facing |
| Q / E | Turn the camera a quarter turn |
| F | Focus the cursor's tile |
| R | Reset the view |
| Space | End the round — everyone acts again |

Keys are polled directly rather than bound through Godot's InputMap. Adding an
InputMap means hand-editing serialised `InputEventKey` objects into
`project.godot`, which is exactly the kind of edit that should be made with the
editor open. Gamepad support (brief section 26) waits on the same step.

**To run a different battle:** select the `Battle` root node and change the
`Battle File` export to `battle_the_breach.json`. There is no code to change —
that is the point of building the field from data.

---

## What it builds, and from what

Nothing on the battlefield is hand placed. `Scenes/Battle.tscn` contains four
nodes: the environment, one directional light, the camera rig and the HUD layer.
Everything else is constructed at load from
`Content/Data/Battles/battle_north_meadow.json` through `Game.Rules`.

| Piece | Built by | Read from |
| --- | --- | --- |
| Terrain tiles, elevation, colour | `TerrainBuilder` | `terrain` grid + `terrain.json` |
| Props | `PropBuilder`, `ModelLibrary` | `props` array + `Content/Models` |
| Units and placeholders | `UnitBuilder`, `PlaceholderUnit` | `player_units` / `enemy_units` + `characters.json` |
| Movement range | `Movement.Reachable` | terrain move costs |
| Attack and threat range | `Targeting` | weapon range |
| Damage preview | `DamageModel.ForecastPhysical` | the same function the attack uses |
| Stats panel | `Unit`, `TerrainType` | `characters.json`, `classes.json`, `weapons.json` |

### The grid convention

The one thing in this scene most likely to be silently wrong, because a mirrored
battlefield still looks like a plausible battlefield.

```
battle file terrain array   row 0 is written FIRST and is the NORTH row
BattleGrid.Parse            flips it once: row 0 becomes y = height - 1
GridLayout / GridSpace      grid +X (west→east) -> world +X
                            grid +Y (south→north) -> world -Z
                            terrain height level -> world +Y, 0.5 m per level
```

So the camera's default seat is **south of the field looking north**, and the
player's deployment row is nearest the viewer. This is pinned by tests, not by
this paragraph — see `GridLayoutTests` below.

### Scale

| Quantity | Value | Why |
| --- | --- | --- |
| Tile | 2.0 m | A hero is 1.7 m (ANIME_DIRECTION rule 4); a 2 m tile keeps neighbours clear at the camera's angle |
| Height level | 0.5 m | The only rise on this field is `hill` at height 1; visible as a step without hiding the unit behind |
| Field | 24 × 28 m | 12 × 14 tiles |
| Tile gutter | 6 cm | The dark base plane shows through, which draws the grid for free |

---

## Assets: what you will actually see

Six GLBs exist of a catalog of dozens, so the honest expectation is a field of
placeholders. Concretely, for North Meadow:

- **Props: 1 placed, 10 skipped.** The only prop in this battle that has been
  generated is `veg_tree_oak_a`, standing on the forest tile at `[4,12]` near the
  **north** edge. The overturned cart, the four fence sections, the four rocks and
  the second oak have not been generated; each logs one warning and is skipped.
- **Units: 0 modelled, 10 placeholders.** `characters.json` names a model for
  every unit in this battle and none of those files exist. The only generated
  character, `npc_guard_greenvale`, is not in this battle.
- **Ground slabs:** the oak's grass disc is **fused to the trunk**
  (`docs/ASSET_PIPELINE.md` measured it as a single 22,104-triangle island), so
  `SceneryTrim` cannot remove it. It will warn that the model is still ~5 m
  across against a 2 m tile and leave it alone. That is deliberate — see below.

Placeholders are marked with a magenta base ring in a colour that appears in no
palette in `STYLE_GUIDE.md`, so a screenshot of this scene can never be mistaken
for finished art. They still carry the class silhouette (cape, spear, sleeves,
bow) and the character hue, so the readability test in STYLE_GUIDE section 4 can
be run on them.

### What the scene does about the scenery problem

`docs/ASSET_PIPELINE.md` records that generated assets arrive with scenery
attached: the house on a 7.79 m ground slab with two bonus trees, the barrel
inside 32 islands of grass tufts, the oak on a grass disc. It also records that
avoid tokens do not stop it.

The import path here does not silently accept that.

- Every model is **measured before it is added to the scene tree**, so nothing
  wrong is ever on screen even for one frame.
- A mesh node that measures like a ground slab — under 25 cm thick, at least 1.5
  tiles across, sitting at the model's base — is removed, with a warning naming
  the measurement.
- A model that is still oversized after that is **reported and left alone**. That
  is the fused case, and a heuristic aggressive enough to fix it would be one that
  eventually deletes half a tree.

Why it matters here specifically: a 7.79 m slab is nearly four tiles wide on a
2 m grid, so a house dropped on this field would carpet it in a second, subtly
different ground surface — while the terrain underneath went on costing 1
movement point. It would look like terrain and behave like nothing, which is worse
than an obviously missing model.

The real fix stays where the pipeline doc puts it: strip non-subject islands at
generation time, opt-in per asset.

### Why models load through `GltfDocument` and not the editor importer

`Content/` is outside the Godot project by design (ARCHITECTURE.md), and Godot
cannot reference a path above `res://`. So GLBs are parsed at load with
`GltfDocument.AppendFromFile`.

The cost is real: no import-time compression, no LOD generation, and parsing on
the loading screen rather than at build time. The benefit is that the content
contract stays one tree that both the Python tooling and the engine read, and a
regenerated asset appears with no import step. If load time becomes a problem the
fix is a build step that copies `Content/Models` into `res://` — not moving the
content.

---

## The anime look

`Shaders/toon.gdshader` implements rule 1, `Shaders/outline.gdshader` rule 2.
Both are commented at length; the short version:

**Rule 1, quantised ramp.** A custom `light()` function buckets `N·L × shadow`
into bands with a hard step and no smoothing anywhere. Band count and every
threshold are uniforms, surfaced as `[Export]` properties on the `Battle` root
node so the look can be dialled in **in the inspector with the game running**.
Terrain gets one more band than characters do, because a 24 × 28 m surface under
one light barely varies in `N·L` and two bands across it read as a flat sheet.

**Rule 2, inverted hull with a distance term.** The width is world-space with a
sub-linear distance multiplier, then clamped in pixels at both ends. The two
naive choices fail in opposite directions: a fixed width in metres falls under a
pixel at the back of a 14-deep grid and shimmers, and a fixed width in pixels eats
a distant unit — which is the failure the spec names. `distance_falloff` picks the
blend; 0.0 is pure world space, 1.0 pure screen space, default 0.55.

Supporting decisions, all of which follow from the rules rather than from taste:

- **One directional light.** A second adds a second terminator, which is the usual
  way a cel-shaded scene stops reading as one thing.
- **No specular anywhere.** A highlight is a smooth gradient by construction.
- **SSAO, SSIL, SDFGI, glow and fog off** in the environment. Each is a gradient,
  and baked AO is in the spec's ban table for the same reason.
- **Low ambient (0.30).** Enough to keep the shadow band off black, not enough to
  soften the terminator.
- **Zero shadow blur, one orthogonal split.** A soft shadow edge beside a hard
  terminator reads as a bug rather than as depth.
- **Cool shadow tint.** Rule 5 says separation comes from hue, because cel shading
  collapses value range by design; the shadow band earns its separation the same
  way the palette does.
- **No outline on terrain tiles.** An inverted hull on 168 tiles outlines every
  tile individually and turns the field into graph paper — the "every crease
  becomes a line" failure in the ban table. The 6 cm gutter over a dark base plane
  draws the grid instead.

---

## Verified

Run `dotnet test HollowCrown.sln` — **101 tests, all passing** (73 before this
work). The 28 added for it are in `Game.Rules.Tests/PresentationQueryTests.cs`.

| Claim | How it is verified |
| --- | --- |
| The grid convention survives from file to world space | `GridLayoutTests.TheFileIsReadNorthRowFirstAllTheWayToWorldSpace`, `NorthIsNegativeZ`, `EastIsPositiveX` |
| Mouse picking is the exact inverse of tile placement | `EveryTileOfTheRealBattleRoundTrips` — all 168 tiles of the real battle |
| Hill tiles are raised by one height step | `HeightLevelsBecomeMetres` |
| The field is centred on the camera's pivot | `TheFieldIsCentredOnTheOrigin` |
| Attack range is a Manhattan diamond, clipped to the field | `TargetingTests.RangeIsAManhattanDiamondWithoutTheCentre`, `RangeIsClippedToTheField` |
| Reach crosses a fence that movement cannot | `RangeIgnoresTerrainBecauseASpearReachesOverAFence` |
| Threat range obeys terrain cost, not step count | `ThreatRangeRespectsTerrainCostRatherThanStepCount` |
| Tomas' spear really is range 2 in the shipped data | `TargetsInRangeUseTheRealBattleAndComeBackNearestFirst` |
| North Meadow's 11 props load with the right positions, rotation and scale | `PropPlacementTests` |
| An absent `scale` defaults to 1 and not to 0 | `AnAbsentScaleIsOneRatherThanZero` |
| Props still line up with the terrain they dress | `ThePropsAgreeWithTheTerrainUnderneathThem` |
| Units carry their class and model path out of content | `UnitPresentationDataTests` |
| `Game.Rules` is still engine-free | The CI guard in `.github/workflows/game.yml`, re-run by hand: clean |
| `Game.Rules` builds with zero warnings | `dotnet build --no-incremental`: 0 warnings, 0 errors |
| Every `Game.Godot` script is well-formed C# and calls `Game.Rules` correctly | Compiled against a throwaway stub of the Godot API. **This proves the C# — it proves nothing about whether those are Godot's real signatures.** |

---

## NOT verified — needs the editor opened once

Everything below is written from the Godot 4 documentation and has never been
executed. Ordered by how load-bearing it is and how likely it is to be wrong.

### The five things to check first

1. **Does `Battle.tscn` parse, and does the project open at all?**
   The scene file carries `;` comment lines. Godot's text parser is shared with
   `ConfigFile` and should skip them, but if the scene fails to load with a parse
   error, **delete the `;` lines** — that is the whole fix, and the reasoning they
   carry is all repeated in this document. Also confirm the `Environment` and
   `DirectionalLight3D` property names took effect rather than being silently
   dropped.

2. **Is the map the right way round?** With the default camera, you should see:
   the road running *toward* you with Rowan, Tomas and Maeve standing on it; the
   goblins *away* from you; the raised hill block (six tiles, `x` 4–6 by `y`
   10–11) in the far half; the single oak tree beyond it at `[4,12]`; the row of
   escape tiles along the far edge at `y = 13`.
   If any of that is reversed, the world mapping is mirrored and every test in
   `GridLayoutTests` was testing the wrong convention — tell me and I will flip it
   in one place.

3. **Does the toon shader light anything, and by how much?**
   Godot's own diffuse term carries a `1/π` factor that a custom `light()`
   function does not. If the scene is uniformly washed out or uniformly dark,
   the fix is the `Light Gain` export on the `Battle` node (try `0.32`, ≈ 1/π, and
   `1.0`), *not* the band levels. Then confirm the terminator is genuinely hard —
   a visible step, not a soft edge — and that the third rim band appears on the
   top of units.

4. **Does the outline appear at all?** It depends on three things I could not
   check: that writing `POSITION` in `vertex()` works as documented, that
   `VIEWPORT_SIZE` is readable in a vertex shader, and that `next_pass` renders
   the hull. If there is no line, that is where it is. If there is a line, the
   question that matters is the spec's: **walk a unit to the back row and confirm
   it is not swallowed by its own outline**, then zoom right in and confirm the
   line does not become a slab. `Outline Width Metres` and
   `Outline Distance Falloff` are the two knobs.

5. **Does clicking select the tile you are pointing at, on the hill?**
   Picking intersects the ground plane twice — once at y = 0, then again at the
   hit tile's own height — because at the camera's 48° pitch a 0.5 m hill offsets
   the hit by about 0.45 m, nearly a quarter of a tile. Flat ground working while
   hills are off by one is the signature of that second pass not doing its job.

### Everything else that is unverified

**API surface I could not compile against the real engine.** Any of these being
wrong is a compile error with a clear message, not a subtle bug:
`GltfDocument.AppendFromFile` / `GenerateScene` signatures;
`RichTextLabel.FitContent` (it was `FitContentHeight` before 4.2);
`MultiMeshInstance3D.Multimesh` casing; `Transform3D.LookingAt` argument order;
`Key.KpEnter`; `Control.SizeFlags.ExpandFill`; `Label3D`'s outline properties.

**Behaviour, not compilation:**

- **Camera framing.** `Frame()` uses a heuristic — the longer side of the field
  × 0.95, giving 26.6 m here. Whether the whole field is on screen depends on the
  viewport aspect and the 40° field of view. If it is wrong, this is one number.
- **HUD layout.** Built from containers and spacers rather than anchor offsets, so
  it should behave at any resolution, but it has never been laid out once. The
  panel minimum widths (380/360/400/300 px) are guesses.
- **Tab key.** Godot's UI may consume Tab for focus traversal before
  `_UnhandledInput` sees it. Every HUD control is set to ignore the mouse, which
  should keep focus away from them, but this is untested.
- **Transparent overlay sorting.** Three overlay layers plus a cursor, all
  unshaded alpha, stacked 1 cm apart. They should sort by depth; they might not.
- **Runtime glTF import.** The oak is 22,104 triangles and its texture is 1024²;
  the parse cost at load has never been measured.
- **`SceneryTrim` on real geometry.** The slab thresholds (25 cm thick, 1.5 tiles
  across) come from the pipeline doc's measurements, not from watching them run.
  The only prop in this battle that will exercise it is the oak, and its disc is
  the case the trim explicitly cannot fix — so the trim's *removal* path is
  entirely unexercised until a house or a barrel is put on a field.
- **Shader compilation stutter.** ARCHITECTURE.md's known Godot 4 risk. Materials
  are cached by colour so each distinct material compiles once, but nothing
  pre-warms them, so expect a hitch on the first frame each new colour appears.
- **Placeholder proportions.** A 1.7 m capsule with a `1.7 / 6.5` head is what
  ANIME_DIRECTION rule 4 says; whether twelve of them are distinguishable at
  tactical distance is exactly the question STYLE_GUIDE section 4's readability
  test asks, and it wants a person looking at a screen.

---

## What this is not

Not a turn loop. There is no AI, no initiative gating and no victory check —
`TurnOrder` is built and its round counter is displayed, but a unit is free to
act whenever the player clicks it, and **Space** resets everyone. That is
milestone 4 and milestone 5 work. What is here is milestone 3's target from
ARCHITECTURE.md — grid from battle JSON, terrain costs, selection, movement
range, attack, HP, death, debug overlays — plus the anime look on top of it.

The scripted events in the battle file (the archer taking the hill on turn 2, the
spearman fleeing) are parsed by `BattleLoader` and are **not executed** here.

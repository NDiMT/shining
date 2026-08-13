# Asset pipeline

Brief sections 53, 54, 55 and 79. How a Hollow Crown 3D asset gets from an idea
to something the engine will load, and what stops a bad one getting through.

Everything here is offline tooling. It never ships in the game build.

---

## The pipeline

```
Character concept  (human, director-approved)
        v
Front / side / back references            <- Content/References/
        v
AI 3D generation  (Meshy)                 <- Tools/hollowasset
        v
Triangle budget remesh
        v
Texture
        v
Rig  (shared skeleton, brief section 56)
        v
Animation  (core set, brief section 57)
        v
GLB
        v
Asset validator                           <- FAILS BUILD if out of budget
        v
Content/ + provenance record              <- Content/Provenance/assets.jsonl
        v
Hollow Engine import
```

Everything except concept approval is automated. That one stays human on
purpose: brief section 68 puts character design under human creative direction,
and it is the decision that most determines whether the game reads as deliberate
or as generated.

---

## Quick start

Requires Python 3.11+. Pillow is optional and only used for texture
downscaling — everything else, including the validator, is standard library
only, which is why the validator can run in CI with nothing installed.

```sh
export MESHY_API_KEY=...          # never commit this
export PYTHONPATH=Tools
pip install Pillow                # optional; enables texture downscaling

python -m hollowasset budgets                                    # the rules
python -m hollowasset balance                                    # credits left
python -m hollowasset prompt   Tools/catalog/greenvale_props.json # free, spends nothing
python -m hollowasset generate Tools/catalog/greenvale_props.json --dry-run
python -m hollowasset generate Tools/catalog/greenvale_props.json --id prop_barrel_a
python -m hollowasset validate --catalog Tools/catalog/greenvale_props.json
python -m hollowasset provenance --report --out docs/ASSET_PROVENANCE.md
```

Run from the repository root.

---

## Adding assets

Edit a catalog file in `Tools/catalog/`. Nothing else. Per brief section 14,
content is data:

```json
{
  "id": "prop_barrel_a",
  "class": "prop",
  "subject": "wooden barrel with three iron bands, slightly tapered staves"
}
```

`class` selects the polygon and texture budget, the output directory, the
expected height and whether a skeleton is required. `subject` describes *what the
thing is* — never how it looks. Art direction lives in
`Tools/hollowasset/style.py`, so the entire game can be restyled from one file
instead of by rewriting every asset definition.

Optional fields:

| Field | Purpose |
| --- | --- |
| `region` | Palette and light: `greenvale`, `ruins`, `vaelor`, `outer_world`, `neutral` |
| `extra` | Per-asset direction that outranks house style |
| `avoid` | Extra negative tokens |
| `references` | Concept art URLs. **Present means image-to-3d instead of text-to-3d.** |
| `enable_pbr` | Metallic/roughness/normal maps. Default off — see brief section 8 |
| `pose` | `t-pose` or `a-pose`. Defaults to `t-pose` for rigged classes |
| `rig` | Override the class default |
| `animations` | Clip names from `animations.py`, e.g. `["idle", "walk", "attack_1"]` |
| `notes` | Carried into the provenance record |

### Prompt length

The API caps prompts at 600 characters. `style.py` packs them by priority and
reports what it dropped:

```
dropped to fit the 600-char limit: even neutral lighting, logos
```

Losing tail tokens is fine. If it reports dropping `stylized low-poly 3D game
asset`, that is a bug — those core tokens are protected. If it drops your `extra`
direction, shorten the `subject`.

---

## Named characters go through concept art

Text-to-3d gives you *a* young swordsman. It does not give you Rowan, and it
gives you a different one every run. That is fine for a blockout and wrong for a
character the player will look at for thirty hours.

So for anything named:

1. Director approves a concept (drawn, or generated and then chosen — the
   decision is human either way).
2. Produce front, side and back views. Put them in `Content/References/`.
3. Add their URLs to `references` on the catalog entry.
4. Regenerate. The pipeline switches to image-to-3d automatically, and the mesh
   follows the approved design.

The entries in `Tools/catalog/vertical_slice_characters.json` are blockouts
today, with empty `references` arrays and a note saying so. They are good enough
to build and test the tactical grid against, and they are not shippable heroes.

---

## What the validator checks

`python -m hollowasset validate` implements the seven checks brief section 55
asks for, plus two the brief implies. Generated content is not assumed correct:
Meshy honours `target_polycount` only approximately, occasionally exports a
character lying on its side, and will happily return a 2048px texture for a
barrel.

| Check | Fails when |
| --- | --- |
| `triangle_count` | Over the class hard cap, or zero triangles |
| `texture_resolution` | Over the class budget, or an image is not embedded |
| `material` | No materials, or a material with no base colour at all |
| `scale` | Height more than 35% off the expected height for the class |
| `orientation` | Tallest axis is not Y — a Z-up export |
| `skeleton` | A rigged class with no skin, or missing 4+ canonical bones |
| `animations` | Clips were requested and none came back |
| `origin` | *warns* — lowest point is not at y=0, so the asset floats or sinks |
| `draw_cost` | *warns* — more than 8 primitives, i.e. 8 draw calls per instance |

Exit code is non-zero on any error, so this belongs in CI as soon as there is CI.

The GLB reader (`glb.py`) is standard-library only: it parses the glTF JSON
chunk, walks the node hierarchy to get world-space bounds, and reads image
dimensions straight from the embedded PNG/JPEG headers. No mesh library, nothing
to install, works in any Python 3.11+ environment including a fresh AI session.

### Known gaps, stated rather than hidden

- **Orientation is a heuristic.** True facing direction cannot be recovered from
  geometry. The check catches Z-up exports and suspiciously deep bounds, which
  are the two failures that actually happen; it cannot catch a character facing
  −Z. Rigging failures will surface that.
- **Rotated nodes over-estimate bounds.** The node walk transforms each mesh's
  local box corner by corner and re-fits, so a rotated node reports a slightly
  larger box than the true geometry. That errs in the safe direction for a budget
  check.
- **UV quality is not checked.** Overlapping or wasteful UVs need eyes or
  Blender.
- **Skinned assets skip scale normalisation.** See below.

---

## Normalisation: what the pipeline fixes automatically

Generated output is not engine-ready. Measured against a real run, three things
were reliably wrong, and none of them is a generator defect — they are
differences in convention:

| Symptom | Measured | Fix |
| --- | --- | --- |
| Scale | A barrel arrived 1.84m tall — output is normalised to ~1.8 units regardless of subject | Wrapper transform node scales it to the class height |
| Origin | Mesh centred on its bounding box, lowest point at y=−0.918 | Same node translates it so it sits on y=0 |
| Texture size | 2048px — the API's smallest texture is 2k, brief section 8 wants 512 for props | Downscaled with Lanczos, re-encoded as PNG, buffer repacked |
| Triangle count | 6,392 triangles against a 550 request | Remesh API pass, triggered by measuring the real file |

`postprocess.normalise()` handles the first three and is idempotent — running it
twice changes nothing. `target_polycount` is a request rather than a guarantee,
so the triangle budget is enforced *after* download by measuring the actual file
and spending a remesh only when one is genuinely needed.

Scale is corrected with a wrapper node rather than by rewriting vertex data:
exact, reversible, and it leaves the original accessor bounds inspectable. The
GLB reader honours node transforms so the validator sees corrected numbers.

**Skinned assets are deliberately excluded from scale normalisation.** For a
skinned mesh the node's own transform is ignored at runtime and joint matrices
come from the skeleton, so wrapping is subtler than it looks. The rigging API
already takes `height_meters`, so rigged assets should arrive correctly sized;
scaling them here would risk a subtle, hard-to-debug break for no gain. The
pipeline says so in its log rather than guessing.

Every correction is recorded on the provenance row prefixed `auto:`, so a future
session can see what the pipeline changed and distinguish it from a hand repair
in Blender.

---

## What the generator actually does, measured

Five assets generated and rendered — barrel, crate, iron sword, oak tree, village
house. Three findings, all of them things the numeric checks alone would not have
told us:

**1. The style direction lands. The scenery habit does not go away.**

The house came back half-timbered with painted framing and flat colour blocks,
exactly the look the style guide asks for. It also came back standing on a
7.79 × 7.79 m ground slab with two bonus trees on it. The tree came back on a
baked grass disc. The barrel came back surrounded by grass tufts and pebbles.

All three had `base plinth`, `ground plane` and `scenery around the object` in
the avoid clause at generation time. **Avoid tokens do not stop this.** They also
are not free: at eighteen tokens the avoid list filled 380 of the 600 characters
and pushed vegetation's `clustered angular canopy masses rather than individual
leaves` out of the prompt entirely — positive direction, which in the same
samples did land. The list is now six tokens, split into geometry and texture
halves, and `test_the_most_important_class_style_token_survives` guards the
regression.

The real fix is not another token. Scenery arrives as **separate mesh islands**,
so it can be measured and removed:

| Asset | Islands | Subject | Scenery |
| --- | --- | --- | --- |
| `building_house_small_a` | 4 | 2,933 | 779 + 770 (trees) + 56 (slab) |
| `prop_barrel_a` | 33 | 1,060 | 3,546 across 32 islands |
| `veg_tree_oak_a` | 2 | 22,104 | grass disc **fused to the trunk** |

Stripping the non-subject islands would take the barrel from 4,606 triangles to
1,060 — inside its 400–4,000 budget, with no reduction pass and nothing lost.
That is the next pipeline stage to build, and it has to be opt-in per asset: a
market stall is legitimately a counter plus an awning, and a blind "keep the
largest island" rule would throw the awning away. The tree shows the limit of the
approach — a fused disc needs Blender or a better prompt.

**2. Prompts leak their own failure modes.** Two of the worst results were
self-inflicted. The crate came back photoreal with stencilled lettering; its
catalog `surface` literally said `stencilled markings` while the avoid clause said
`no stencilled markings`. The tree came back on a grass disc; its `surface` said
`moss at the base`. Read the resolved prompt before blaming the generator —
`hollowasset prompt` is free.

**3. `target_polycount` is a suggestion, and how bad a one depends on the class.**

| Asset | Requested | Delivered | Over |
| --- | --- | --- | --- |
| `prop_crate_a` | 2,200 | 3,152 | 1.4× |
| `prop_barrel_a` | 2,200 | 4,606 | 2.1× |
| `weapon_iron_sword` | 1,200 | 8,555 | 7.1× |
| `veg_tree_oak_a` | 3,400 | 22,124 | 6.5× |

Dense organic subjects overshoot hardest. Budget enforcement has to measure the
delivered file rather than trust the request, which is what
`_enforce_triangle_budget` does — but remesh stays opt-in, because at an 11×
reduction it tore the barrel apart. Island stripping first, remesh only after.

---

## Look before you rig

A character's mesh costs a preview and a refine. Rigging it and baking a clip set
costs several times that, and the thing most likely to be wrong is the
silhouette — which you can see from the mesh alone.

```sh
python -m hollowasset generate Tools/catalog/prologue_cast.json \
    --id npc_guard_greenvale --mesh-only
```

Review it, apply the readability test from `docs/STYLE_GUIDE.md` (render it small,
cover the face, can you still name the class), and only then run the same entry
without the flag to rig it and bake its clips.

The same order applies to a batch: generate the cheapest, most reused asset
first, look at it, and let what you learn correct the prompts before the
expensive ones run.

---

## Rigging and animation

`rig` uses the Meshy rigging API, which needs a **textured humanoid facing +Z**
with clear limb separation. Untextured meshes and non-humanoids will fail; the
validator's orientation check catches the most common cause before credits are
spent on the rig.

Animations come back **one GLB per clip**, saved beside the model as
`hero_rowan__idle.glb`, `hero_rowan__walk.glb` and so on, named with the brief's
animation names rather than provider action ids.

Consolidating them onto one shared skeleton is Godot's job, not this pipeline's:
Godot 4's `BoneMap` and `SkeletonProfileHumanoid` retarget each imported rig onto
a canonical profile, which is what makes brief section 56's animation reuse
affordable across 25–35 characters. The canonical bone list and alias table in
`validate.py` are the groundwork for that mapping. It still needs proving on two
different characters before the full cast is generated — see
[PROLOGUE_PRODUCTION.md](PROLOGUE_PRODUCTION.md).

`Tools/hollowasset/animations.py` maps the brief's fourteen-clip core set to
Meshy action ids. **Those ids are provisional.** They were picked from the
library's published category ranges, and individual ids within a category are
not interchangeable in feel. Before any character animation reaches production:
generate one rigged test character, bake all fourteen clips, watch them, fix the
table, and set `VERIFIED = True`.

`MINIMAL_SET` (idle, walk, attack_1, hit_front, death) is what a unit needs to
be playable in a tactical battle — five clips instead of fourteen, for early
iteration.

---

## Provenance

Every generation appends a record to `Content/Provenance/assets.jsonl`,
capturing what brief section 54 requires: asset id, path, type, tool, date,
plan and licence position, prompt, texture prompt, references, Meshy task ids,
credits consumed, measured triangles and texture size, SHA-256, manual edits,
validation result and rights notes.

Append-only JSONL, chosen deliberately: it merges cleanly in git, survives a
crashed batch with completed records intact, stays readable in a diff, and keeps
the full regeneration history of every asset. Failed generations are recorded
too, so a failure leaves a trace rather than a gap.

```sh
python -m hollowasset provenance                          # summary
python -m hollowasset provenance --history hero_rowan     # every attempt
python -m hollowasset provenance --report --out docs/ASSET_PROVENANCE.md
```

`docs/ASSET_PROVENANCE.md` is generated. Do not edit it by hand.

**Record manual edits.** When an asset is repaired in Blender, add what changed
to its `manual_edits` list. Without that, a regeneration silently discards the
fix and nobody knows why the asset got worse.

### Licence position

`provenance.DEFAULT_LICENSE_NOTE` records the claim we would have to stand
behind: commercial use permitted under the Meshy plan terms in force on the
generation date. Re-verify on any plan change and update the string with the
date. Brief section 54 asks for this because the game is a commercial release,
and "we think it was fine at the time" is not an answer.

---

## Cost

Credits are finite, so the tooling makes cost visible before it is spent:

- `prompt` and `--dry-run` resolve everything and spend nothing.
- `generate` estimates the batch and **refuses to start** if the estimate
  exceeds the account balance, rather than failing halfway with assets
  half-generated.
- Actual `consumed_credits` from each finished task is recorded in provenance,
  so the estimates can be corrected against reality.

Rough per-asset cost: ~15 credits for a static prop (preview + refine), ~35 for
a rigged character with five clips.

---

## Security

The API key is read from `MESHY_API_KEY` and never written to logs, provenance
records or generated documentation. It must not be committed —
`.gitignore` covers the usual accidents, but the real control is that nothing in
this package ever writes the key anywhere.

If a key is ever pasted into a chat, an issue, a commit or a log, treat it as
compromised and rotate it in the Meshy dashboard. Meshy supports multiple keys
per account, so rotating one does not interrupt work.

---

## Seeing a whole battle

`preview` answers "is this asset any good". It cannot answer "does the game look
like anything", and while Godot cannot be installed here that question has no
other answer at all. `scene` composes one:

```sh
python -m hollowasset scene Content/Data/Battles/battle_north_meadow.json --out shot.png
python -m hollowasset scene Content/Data/Battles/battle_the_breach.json --out breach.png --size 1600
python -m hollowasset scene Content/Data/Battles/battle_north_meadow.json --out smooth.png --smooth --no-outline
```

It reads the battle file, terrain.json, characters.json and classes.json, builds
the grid, colours every tile by terrain type, respects tile elevation, places
whatever props and character models have actually been generated, highlights the
active unit's movement range, and shoots it from the tactical camera. Useful
flags: `--size`, `--yaw`, `--pitch`, `--active`, `--flat`, `--no-labels`, and
`--smooth` / `--no-outline` to turn off rules 1 and 2 of
`docs/ANIME_DIRECTION.md` for comparison.

Nothing missing is fatal. Ungenerated props are reported and skipped; units with
no model are drawn as a coloured stand-in figure, because an empty field is not
a picture of a battle. The warning list on a run is a to-generate list.

**Rules 1 and 2 live in `preview.py`, not here.** `TOON_RAMP` and `TOON_RIM` are
the quantised lighting; `_edge_pass` is the screen-space outline, taken from the
depth and normal buffers rather than faked by darkening back faces. Both are on
by default for `preview` as well, so single-asset contact sheets and the composed
scene are lit the same way.

### What the composed scene showed that single-asset previews did not

- **The camera pitch was inverted.** Every contact sheet and line-up produced
  before 2026-08-13 was shot from *below* the asset. It survived that long
  because a barrel looks much the same either way; it was obvious the moment a
  house was rendered and the roof never appeared. Positive pitch now looks down.
- **The tree's baked grass disc is worse in a scene than in a preview.** At 3.03 m
  across it covers nine tiles of a 1 m grid, and its green is not the terrain's
  green, so it reads as a dark stain around the trunk rather than as ground. The
  single oak battle 01 places at [4,12] already spills onto the hill at [3..5,11]
  that the archer climbs on turn 2; the battle asks for a second one.
- **`building_house_small_a`'s 7.79 m slab is unusable in a battle.** It is
  nearly eight tiles square and would sit on top of the grid it is meant to
  stand on.
- **The one generated character loses to its own placeholder at tactical
  distance.** On a 14-tile board at 1200 px `npc_guard_greenvale` is about 40 px
  tall, and at that size its dark, low-contrast texture reads as a green smudge
  while the flat saturated stand-in three tiles away reads as a unit
  immediately. At 1600 px it recovers. That is rules 3 and 5 failing in a
  generated texture, and it is the argument for judging characters at camera
  distance rather than in close-up — which is what `scene` is for.
- **Bind pose is not a battle pose.** The guards stand arms-out across the
  board. Nothing is wrong with the asset; it is a reminder that a scene shot is
  worth much less until the idle clip can be sampled.

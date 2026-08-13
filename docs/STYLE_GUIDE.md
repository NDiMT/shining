# Hollow Crown visual style guide

Brief sections 6, 8, 59, 89 and 90. This document is the reference the asset
prompts in `Tools/hollowasset/style.py` encode, and the standard any asset is
reviewed against before it enters `Content/`.

The guiding principle from the brief is unchanged:

> **Simple geometry, rich atmosphere.**

---

## 1. The Shining Force II reference, handled properly

Shining Force II is the agreed touchstone. Using it well means being precise
about *what* we are taking, because the answer determines both the art direction
and the legal position of a commercial release.

### What we take: the design discipline

Shining Force II looks good on hardware that allowed almost nothing. Its
readability came from constraints — small sprites, a tight on-screen palette —
and the discipline those constraints forced is exactly what a low-poly tactical
RPG needs, because our constraint is the same problem wearing different clothes:
**a unit is 60 pixels tall on a tactical camera and must be identifiable
instantly.**

Six transferable rules:

1. **One dominant hue per character.** Each unit gets a single costume hue, one
   bright accent and one neutral (metal, leather, cloth). A player should be able
   to name a unit from its colour alone at a distance where its face is invisible.
2. **Silhouette before detail.** The recognisable feature is a shape — a cape, a
   crested helm, a bow arc, oversized ears — not surface decoration. Brief
   section 89 states this directly: a recognizable hairstyle and a strong cape
   beat thirty tiny belts.
3. **Warm, not grim.** Bright mid values, saturated colour, clean surfaces. The
   story goes to dark places (brief section 99); the palette does not follow it
   there by default. Grime is a deliberate regional choice, never a house habit.
4. **Class legibility over individual realism.** Every swordsman should read as a
   swordsman before it reads as a specific person. Silhouette families are
   assigned per class, and characters vary within them.
5. **Non-humans are ordinary.** Brief section 33 wants a party of orcs, ratfolk,
   mushroom mages and golems that feels like a travelling family. Design them at
   the same level of stylisation as the humans, not as novelty exceptions.
6. **Backdrops recede.** Environments carry atmosphere through light, fog and
   value, and stay lower in contrast than units. Nothing in a battlefield should
   compete with a unit for attention.

### What we never take

The list above is design *method*. None of it requires anything from Sega's
files, and this project must not use any:

- **No third-party name enters a prompt.** Not "Shining Force", not "Sega", not
  any character name from those games. `style.py` describes the look in our own
  vocabulary for exactly this reason, and every prompt sent to a generator is
  recorded in the provenance database, so this is auditable rather than a
  promise.
- **No screenshots, sprites, box art or official artwork as generator input.**
  The image-to-3d path takes our own commissioned or generated concept art only.
  Feeding someone else's character art into a 3D generator produces a derivative
  of that art, whatever the tool's terms say about the output.
- **No recognisable redesigns.** A character who is identifiably a specific
  Shining Force character in new clothes is a problem regardless of how the mesh
  was made.
- **No lifted names or coinages.** Generic class and item names (Swordsman,
  Wizard, Paladin, Healing Seed) are common fantasy vocabulary. Names invented by
  that series are not ours to reuse.

### Why the distinction is worth this much space

Game *mechanics* are broadly not protected by copyright — a grid-based tactical
system with agility-ordered turns, class promotions, hidden recruitable
characters and an explorable overworld can be built freely, and brief section 2
is right that this is where the "feeling" of the reference actually lives.
Expressive material is protected: character designs, artwork, names, music,
dialogue and text.

So the safe and the good path are the same one. Take the systems and the
discipline, generate the art from our own direction. An asset that needed someone
else's picture to exist is both a legal exposure on a commercial Steam release
and, per brief section 68, the thing most likely to make the game read as
derivative rather than deliberate.

This is standard practice in the genre rather than legal advice; get a lawyer's
review before store submission, and give them this document.

---

## 2. Palette

A fixed base palette keeps assets generated weeks apart consistent. Regional
palettes shift temperature and value, never the underlying discipline.

### Character accent hues

Each recruitable character claims one. Two characters in the same battle party
must not share a hue.

| Hue | Hex | Claimed by |
| --- | --- | --- |
| Tabard blue | `#3E6FB0` | Rowan |
| Violet | `#6B4E9E` | Maeve |
| Deep red | `#A83A3A` | Knight ally |
| Forest green | `#4A7A46` | Archer ally |
| Ochre | `#C08A3E` | unclaimed |
| Teal | `#3A8A8A` | unclaimed |
| Rose | `#C4707F` | unclaimed |
| Bone | `#D8CFB8` | unclaimed |

Neutrals, shared by everything: iron `#7A8189`, leather `#6B4F3A`,
cloth `#B8AA96`, dark line `#2A2620`.

### Faction colours

Enemies read as a faction before they read as a creature.

| Faction | Primary | Accent |
| --- | --- | --- |
| Goblin raiders | sickly green `#7C9B4E` | rust red `#8E4430` |
| Vaelor's army | cold steel `#5A6472` | ember orange `#D07A2C` |
| Sealed fragments | void violet `#3A2C4E` | pale gold `#E0C07A` |

### Regional light

Applied as texture guidance by `style.REGIONS`. These describe light and value
only — a region string that named foliage would tint every barrel in the region
green.

| Region | Direction |
| --- | --- |
| `greenvale` | Warm afternoon, bright mid values, gentle contrast |
| `ruins` | Cool desaturated, low mid values, sparse warm highlights |
| `vaelor` | Cold desaturated, dark values, one warm orange accent |
| `outer_world` | Dusty ochre and teal, weathered mid values |

---

## 3. Silhouette families

Per brief section 89, silhouette is assigned by class so the tactical camera
stays readable with twelve units on screen.

| Class | Silhouette | Readable feature |
| --- | --- | --- |
| Swordsman | Upright, medium width, cape | Cape and single pauldron |
| Knight | Boxy, widest, heavy shoulders | Crested helm, rectangular shield |
| Archer | Narrow, tall | Bow arc |
| Mage | Wide sleeves, tapering robe | Sleeve mass, staff |
| Priest | Rounded, hooded | Hood shape |
| Thief | Small, crouched, quick | Hunched profile, hood |
| Beast | Low, wide, quadruped mass | Animal profile |
| Flying Knight | Wide horizontal | Wing span |

Bosses get one silhouette element no rank-and-file unit has — horns, a
disproportionate weapon, a wing, a second head. That element is how a player
finds the commander in a crowded battlefield.

---

## 4. The readability test

Every character asset must pass this before it enters `Content/`:

1. Render at 64 pixels tall on the game's background value.
2. Cover the face.
3. Can you name the class? Can you name the character? Can you name the faction?

Three noes means the silhouette or the palette is wrong. Adding detail will not
fix it; changing the shape will. This test costs a minute and prevents the
failure mode brief section 6 warns about — a game that looks like a generic
asset pack because every unit is a differently-textured version of the same
shape.

---

## 5. Geometry and texture rules

Numbers live in `Tools/hollowasset/budgets.py`, enforced by
`python -m hollowasset validate`. See `docs/ASSET_PIPELINE.md`.

- Flat-shaded or lightly smoothed. Hard edges are the style, not a defect.
- No geometry for anything a texture can carry at tactical distance.
- Buildings are modular kit pieces with flush, grid-aligned edges (brief
  section 90). Variation comes from arrangement, scale, rotation, colour and
  light — never from a new monolithic mesh.
- Vertex colours are supported and encouraged for foliage, terrain and rock
  variation (brief section 8): it is the cheapest variety available.
- No baked lighting in textures. Lighting is the renderer's job, and baked
  shadows fight the engine's directional sun.
- Base colour plus good lighting is the default. PBR maps are opt-in per asset,
  for heroes and metal-heavy bosses.

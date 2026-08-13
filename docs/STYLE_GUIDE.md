# Hollow Crown visual style guide

Brief sections 6, 8, 59, 89 and 90, and the director's call in
[ANIME_DIRECTION.md](ANIME_DIRECTION.md). That file is the definition of the look;
this one is how the look is produced and reviewed. It is the reference the asset
prompts in `Tools/hollowasset/style.py` encode, and the standard any asset is
measured against before it enters `Content/`.

The guiding principle from the brief is unchanged:

> **Simple geometry, rich atmosphere.**

The look that principle now serves is anime: flat lit colour, a hard shadow
terminator, a dark outline on every silhouette, and a bright saturated palette.
The two are not in tension. Cel shading rewards big clean forms and punishes
fussy detail, which is the same discipline section 6 was already asking for.

---

## 0. Who does what

The single most expensive mistake available here is asking the generator for the
lighting, so the split is stated first:

| Anime rule | Who implements it |
| --- | --- |
| 1. Two bands, one hard edge | Renderer and Godot toon shader |
| 2. Dark outline on every silhouette | Godot inverted-hull material, offline edge pass |
| 3. Flat colour in the texture | Prompt grammar — positively, as "flat unshaded colour" |
| 4. Anime proportion, real height | Prompt grammar — `CLASS_STYLE` |
| 5. Saturated separated hues | Prompt grammar — `CLASS_PALETTE`, plus the palette below |

**No prompt ever says "cel shaded", "toon shaded", "outlined" or "rim light".** A
generator asked for cel shading paints the light bands and the ink line into the
texture; that texture then bands a second time under the real shader and turns to
mud, which is the one failure mode that makes cel shading look cheap rather than
deliberate. `test_no_prompt_ever_asks_the_generator_for_the_lighting` enforces
this across every catalog entry, not just the style constants.

The corollary is the rule that decides whether an asset is any good: **ask for
what you want, not for what you fear.** Measured in `docs/ASSET_PIPELINE.md`, an
eighteen-token avoid list filled 380 of the 600 available characters, failed to
prevent the failure it named, and pushed out the positive direction that did
land. The avoid clause stays short on purpose.

---

## 1. Where the look comes from, handled properly

Two touchstones, deliberately separated.

**Structure** comes from the 16-bit tactical RPG tradition: a village, a grid, a
readable cast. **Rendering** comes from modern cel-shaded JRPGs.

### What we take: the design discipline

The genre's classics look good on hardware that allowed almost nothing. Their
readability came from constraints — small sprites, a tight on-screen palette —
and the discipline those constraints forced is exactly what a low-poly tactical
RPG needs, because our constraint is the same problem wearing different clothes:
**a unit is 60 pixels tall on a tactical camera and must be identifiable
instantly.**

Six transferable rules, each now sharpened by the anime direction:

1. **One dominant hue per character.** Each unit gets a single costume hue, one
   bright accent and one neutral. A player should be able to name a unit from its
   colour alone at a distance where its face is invisible. This matters *more*
   than it did: a two-band shader collapses the value range by design, so hue is
   all that is left to separate one material from its neighbour.
2. **Silhouette before detail.** The recognisable feature is a shape — a cape, a
   crested helm, a bow arc, oversized ears — not surface decoration. Brief
   section 89 states this directly, and the outline pass doubles down on it: the
   silhouette is literally drawn in black on every frame.
3. **Warm, not grim.** Bright mid values, saturated colour, clean surfaces. The
   story goes to dark places (brief section 99); the palette does not follow it
   there by default. Grime is a deliberate regional choice, never a house habit —
   and a muddy palette destroys rule 1 outright.
4. **Class legibility over individual realism.** Every swordsman should read as a
   swordsman before it reads as a specific person.
5. **Non-humans are ordinary.** Brief section 33 wants a party of orcs, ratfolk,
   mushroom mages and golems that feels like a travelling family. Design them at
   the same level of stylisation as the humans, not as novelty exceptions.
6. **Backdrops recede.** Environments carry atmosphere through light, fog and
   value, and stay lower in contrast than units. Nothing in a battlefield should
   compete with a unit for attention.

### What we never take

The list above is design *method*. None of it requires anything from another
company's files, and this project must not use any:

- **No third-party name enters a prompt.** Not a series name, not a publisher,
  not a character name from someone else's game. `style.py` describes the look in
  our own vocabulary for exactly this reason, every prompt sent to a generator is
  recorded in the provenance database, and `test_no_third_party_ip_appears_in_any_prompt`
  checks the resolved prompts of every catalog entry. This is auditable rather
  than a promise.
- **No screenshots, sprites, box art or official artwork as generator input.**
  The image-to-3d path takes our own commissioned or generated concept art only.
  Feeding someone else's character art into a 3D generator produces a derivative
  of that art, whatever the tool's terms say about the output.
- **No recognisable redesigns.** A character who is identifiably someone else's
  character in new clothes is a problem regardless of how the mesh was made.
- **No lifted names or coinages.** Generic class and item names (Swordsman,
  Wizard, Paladin, Healing Seed) are common fantasy vocabulary. Names invented by
  another series are not ours to reuse.

"Anime" as a rendering style is a technique, not anyone's property, and this
section is unaffected by the change of look. Cel shading is implemented from
first principles in our own shaders.

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

Anime rule 5 governs the whole section: **neighbouring materials differ in hue,
not in shade.** A brown belt on a brown tunic is one shape once the shader has
quantised it. Pick the belt a different hue, or accept that it will not read.

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

These are **unlit base colours**, and that is a change worth stating: what you
see on screen is this colour in its lit band and a darker, slightly hue-shifted
version of it in its shadow band. The shadow tone is derived by the shader, and
is not painted into the texture by anyone, ever.

`#2A2620` is the outline colour. It is a shader constant, not a paint.

### Faction colours

Enemies read as a faction before they read as a creature.

| Faction | Primary | Accent |
| --- | --- | --- |
| Goblin raiders | sickly green `#7C9B4E` | rust red `#8E4430` |
| Vaelor's army | cold steel `#5A6472` | ember orange `#D07A2C` |
| Sealed fragments | void violet `#3A2C4E` | pale gold `#E0C07A` |

### Regional light

Applied as texture guidance by `style.REGIONS`. These describe palette only — a
region string that named foliage would tint every barrel in the region green.

| Region | Direction |
| --- | --- |
| `greenvale` | Warm afternoon palette, bright mid values, gentle contrast |
| `ruins` | Cool blue-grey palette, low mid values, sparse warm highlight hue |
| `vaelor` | Cold steel-blue palette, dark values, one warm orange accent hue |
| `outer_world` | Dusty ochre and teal palette, weathered mid values |

None of them says "desaturated" any more. Regional identity is bought by naming
the hue a region leans towards, because a desaturated region would be asking for
the thing rule 5 and the texture avoid clause both forbid, and a prompt that
argues with itself spends characters to buy nothing.

---

## 3. Silhouette families

Per brief section 89, silhouette is assigned by class so the tactical camera
stays readable with twelve units on screen. The outline pass draws these shapes
in black, so a family that is not distinct is not distinct in the worst possible
way.

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

### Proportion, and the height that does not move

Anime rule 4, and the half of it that gets forgotten: **the head grows, the
character does not shrink.**

- A hero is about six and a half heads tall rather than eight.
- Eyes are large and clean; features are simplified, not detailed.
- Hair is cut into a few solid angular clumps, never strands.
- Cloth falls in a few big folds, never many small ones.
- **A hero is still 1.7 metres.** The tactical grid, the movement costs and the
  camera all depend on it, and `budgets.py` hands that height to the rigging API
  regardless of what the mesh looks like.

That last point is why `CLASS_AVOID` carries `chibi proportions` for every
humanoid class. Asking for a larger head is how the read is bought, and nothing
in that phrasing tells a generator where to stop. This one is a stated risk
rather than a measured failure — it costs two words, on the humanoid classes
only, and a three-head chibi does not stand on this grid.

---

## 4. The readability test

Every character asset must pass this before it enters `Content/`:

1. Render at 64 pixels tall on the game's background value.
2. Cover the face.
3. Can you name the class? Can you name the character? Can you name the faction?

Three noes means the silhouette or the palette is wrong. Adding detail will not
fix it; changing the shape will. This test costs a minute and prevents the
failure mode brief section 6 warns about — a game that looks like a generic asset
pack because every unit is a differently-textured version of the same shape.

```sh
python -m hollowasset preview Content/Models/Characters/npc_guard_greenvale.glb \
    --out /tmp/guard.png --flat
```

`--flat` renders untextured grey. Use it: the test is about silhouette, and a
texture is very good at hiding a bad one.

---

## 5. The dividing line: form is geometry, detail is texture

The most important production rule in this project, and the one that decides
whether an asset is cheap and clean or expensive and fragile:

> **If it can be painted, paint it.**

Geometry carries **form** — the silhouette, the mass, the shape you would
recognise from across a battlefield. Texture carries **detail** — bands, seams,
rivets, trim, panel lines, carved runes, painted wear.

This is not a compromise for performance. At tactical-camera distance a painted
iron band and a modelled iron band are indistinguishable, and the painted one
costs nothing, survives any reduction, and can be changed without touching the
mesh. Under an outline pass it is better than indistinguishable: **every modelled
crease becomes a black line.** A modelled band that used to be merely wasteful is
now a drawn artefact.

### Measured, not asserted

A barrel prompted as *"wooden barrel with three iron bands"* had its bands
modelled as raised rings. Reduced to fit the prop budget, it became a formless
lump: the reducer had real geometry to destroy, and it destroyed it. At 561,
1,030 and 2,061 triangles the result was a blob, a blob with hinted bands, and
ragged bands full of holes.

The bands were never supposed to be geometry.

### How this is enforced

Catalog entries split the description in two:

```json
{
  "subject": "smooth tapered wooden barrel, simple drum form, flat top and base",
  "surface": "flat warm wood colour, three dark iron bands, a few painted plank lines"
}
```

`subject` goes to the geometry prompt. `surface` goes **only** to the texture
prompt, so the generator has no reason to build it. `style.py` also carries
"surface detail painted in the texture, not modelled" as a core token that is
never dropped, and an avoid token for *surface detail modelled as raised trim or
extruded panel lines*.

### `surface` names paint, not material

New under the anime direction, and the change with the most entries behind it.
A `surface` field says what colour something is and what marks are painted on it.
It does not name a material sample:

| Write this | Not this | Because |
| --- | --- | --- |
| `flat warm wood colour, a few painted plank lines` | `wood grain` | "Grain" is a request for a photograph |
| `two flat stone greys separated by hue` | `stone grain, lichen, moss` | Moss is what grew the grass disc |
| `flat bright steel blade, warm grip binding` | `polished iron` | "Polished" asks for a specular highlight, i.e. baked light |
| `flat straw ochre body` | `old cut marks, weathered` | Grime is a regional decision, not a house habit |
| `saturated green field, flat iron boss` | `iron boss, plank seams` | Two materials need two hues, not two browns |

Two of the ugliest assets in `Content/` were self-inflicted this way, both
documented in `docs/ASSET_PIPELINE.md`: a crate whose `surface` said *stencilled
markings* came back photoreal with stencilled lettering, and a tree whose
`surface` said *moss at the base* came back on a baked grass disc. Read the
resolved prompt before blaming the generator — `hollowasset prompt` is free.

### Where the line falls

| Geometry | Texture |
| --- | --- |
| The barrel's drum | Its iron bands and plank seams |
| A cape, a pauldron, a crested helm | Straps, buckles, stitching, heraldry |
| A roof plane and wall mass | Timber framing, plaster colour, thatch |
| A tree's canopy masses and trunk | Its two flat greens |
| A weapon's blade and guard | Engraving, wrapping |
| A boss's horns and armour plates | Every rune on them |

The test: **cover the object and describe its outline from memory.** Whatever
survives that description is geometry. Everything else is texture.

---

## 6. Geometry and texture rules

Numbers live in `Tools/hollowasset/budgets.py`, enforced by
`python -m hollowasset validate`. See `docs/ASSET_PIPELINE.md`.

- Flat-shaded or lightly smoothed *normals*. Hard edges are the style, not a
  defect. This is a mesh property and has nothing to do with painted shading.
- No geometry for anything a texture can carry at tactical distance.
- Buildings are modular kit pieces with flush, grid-aligned edges (brief
  section 90). Variation comes from arrangement, scale, rotation, colour and
  light — never from a new monolithic mesh.
- Vertex colours are supported and encouraged for foliage, terrain and rock
  variation (brief section 8): it is the cheapest variety available, and a hue
  shift per instance is exactly what rule 5 wants.
- **No baked lighting in textures, of any kind.** No shadows, no ambient
  occlusion, no painted highlights, no soft gradients. Lighting is the shader's
  job, and a texture that brings its own fights the toon ramp and produces mud.
- **No PBR maps.** `enable_pbr` is `false` on every catalog entry, and should
  stay that way: a two-band toon shader ignores metallic, roughness and normal
  maps entirely, so they are texture memory spent on nothing. Base colour is the
  whole material. (This reverses the previous opt-in for heroes and metal-heavy
  bosses, on the direction's explicit ban.)

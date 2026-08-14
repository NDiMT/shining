# Anime direction

Director's call, 2026-08-13: the whole game moves to an anime look. This file is
the one definition of what that means for Hollow Crown, so the prompt grammar,
the offline renderer and the Godot shaders all implement the *same* thing rather
than three people's separate idea of "anime".

It supersedes nothing in the brief. Brief section 6 still asks for simple
geometry and rich atmosphere, and section 89 still asks for shapes readable at
tactical-camera distance. Anime is how those are achieved now, not a replacement
for them — and it makes them easier, because cel shading rewards big clean forms
and punishes fussy detail.

The touchstone remains Shining Force II for *structure* (a village, a grid, a
readable cast). The rendering touchstone is modern cel-shaded JRPG: flat lit
colour, hard shadow terminator, dark outline, bright saturated palette.

---

## The five rules

**1. Two lighting bands, one hard edge.**
Not a gradient. A lit tone and a shadow tone, meeting at a sharp terminator. A
third, narrower band is allowed for a bright rim, and nothing else. This is the
single change that reads as "anime" from across the room, and it is a *shading*
decision, so it lives in the renderer and the shader — not in the texture.

**2. Dark outline on every silhouette.**
Inverted-hull outline in engine, scaled with distance so a unit at the back of
the grid is not eaten by its own line. Outlines are what let a 4,000-triangle
character read at tactical-camera distance against busy terrain.

**3. Flat colour in the texture. No light baked in.**
Textures carry hue and material, never shading. This tightens the existing house
rule rather than replacing it: painted detail yes, painted *shadow* no. A texture
with baked lighting fights the cel shader and produces mud, which is the one
failure mode that makes cel shading look cheap instead of deliberate.

**4. Small, chunky-limbed anime proportion.**
Director's call, revised: the cast is *small*, in the mould of a Kingdom Hearts
party rather than a realistic soldier. Concretely, and these numbers are the
rule:

| | Target |
| --- | --- |
| Head-to-body | **5 to 5.5 heads** — a realistic adult is 7.5 to 8 |
| Standing height | **1.5 m** for heroes, NPCs and humanoid enemies |
| Hands and feet | **Oversized.** Big simple shoes, chunky gloved hands |
| Limbs | Slim between the joints, so the large extremities read |
| Hair | One or two solid angular masses, never strands |
| Face | Large clean eyes, small nose and mouth, no wrinkles or stubble |

Tiles stay 2 m and props stay the size they are. That is the point: shrinking
only the cast is what makes them read as small, because a 0.9 m barrel beside a
1.5 m character is a different picture from the same barrel beside a 1.7 m one.

This also serves brief section 89 rather than fighting it. A bigger head and
bigger hands are more pixels on the parts a player reads a class from, at the one
distance that matters.

**Text-to-3d has failed this rule twice.** Both attempts put the proportion
language in the prompt, verified it survived packing, and got back the same
seven-and-a-half-head soldier. Treat the prompt path as worth one more try at
these much more concrete numbers, and the concept-art path
(`references` → image-to-3d, see ASSET_PIPELINE.md) as the one that is actually
expected to work.

**5. Saturated, separated hues.**
Neighbouring materials get different *hues*, not different shades of one. Cel
shading collapses value range by design, so hue is what is left to separate a
brown belt from a brown tunic. The one-dominant-hue-per-character rule from
STYLE_GUIDE.md survives and matters more than before.

---

## What this bans

| Banned | Because |
| --- | --- |
| Smooth shading gradients | Reads as generic 3D the moment it appears |
| Baked ambient occlusion, baked shadows | Fights the shader, produces mud |
| PBR metallic/roughness/normal maps | Cel shading ignores them; they cost texture memory for nothing |
| Photographic surface detail | Already banned; anime makes it worse, not better |
| Desaturated or muddy palettes | Kills the hue separation rule 5 depends on |
| Modelled surface detail | Unchanged from before, and outlines make it worse: every crease becomes a line |

---

## Where each rule is implemented

| Rule | Prompt grammar | Offline renderer | Godot |
| --- | --- | --- | --- |
| 1. Two bands | asks for flat colour, not shading | quantised lighting | toon shader ramp |
| 2. Outline | — | screen-space edge pass | inverted-hull material |
| 3. Flat texture | avoid clause + positive direction | — | — |
| 4. Proportion | class shape direction | — | — |
| 5. Hue separation | class palette + region | — | — |

Rules 1 and 2 are *not* the generator's job and must never be asked of it. A
generator asked for "cel shaded" paints the bands into the texture, which then
double-shades under the real shader. It gets asked for flat colour; the engine
does the lighting.

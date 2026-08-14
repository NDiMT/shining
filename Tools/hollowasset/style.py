"""The Hollow Crown prompt grammar.

Brief section 6 asks for "simple geometry, rich atmosphere" and section 89 asks
for shapes that stay readable at tactical-camera distance. docs/ANIME_DIRECTION.md
is the director's call on *how* that is achieved: two lighting bands with one hard
edge, a dark outline on every silhouette, flat colour in the texture, small
chunky-limbed anime proportion, and saturated separated hues. This module encodes
the part of that spec the generator is allowed to know about.

Three rules govern this file, and all three matter for a commercial Steam release:

1. No prompt ever names a third-party game, publisher or character. We describe
   the visual language in our own terms. See docs/STYLE_GUIDE.md for why this
   distinction is not cosmetic.
2. Style lives here, not in the catalog. Catalog entries describe *subjects*;
   this module decides how they look. Changing the game's art direction should
   be one edit here, not a sweep through every asset definition.
3. **The generator is never asked for the lighting.** Anime rules 1 and 2 — the
   two-band ramp and the outline — belong to the renderer and the Godot shaders.
   A generator asked for "cel shaded", "toon shaded", "outlined" or "rim light"
   paints those bands and that ink line into the texture, and the texture then
   double-shades under the real toon shader: two terminators, a painted outline
   swimming against the inverted-hull one, and the mud ANIME_DIRECTION.md names
   as the one failure that makes cel shading look cheap instead of deliberate.
   So these prompts ask for flat colour and anime *form*, nothing else, and
   ``test_no_prompt_ever_asks_the_generator_for_the_lighting`` guards it.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import budgets

# ---------------------------------------------------------------------------
# The house style
# ---------------------------------------------------------------------------

#: Non-negotiable. These three tokens are the entire art direction in miniature,
#: so they are never dropped to make room for a long subject: an asset generated
#: without them is off-style by definition and has to be regenerated anyway.
#:
#: "anime style" replaces the old bare "stylized" because a bare "stylized"
#: bought us very little: the crate and the guard in Content/Models both came
#: back essentially photoreal under it, with real wood grain and woven chainmail.
#: "low-poly" stays — it is the token that keeps the *form* simple, and it is
#: doing separate work from the anime cue.
#:
#: The third is the most important and the last to be learned. Anything that can
#: be painted must be painted. A barrel's iron bands, a plank seam, a rivet, a
#: carved rune are surface detail: modelled they cost geometry, break under any
#: reduction, and read no better at tactical-camera distance than a texture does.
#: Brief section 6 says it in four words — simple geometry, rich atmosphere, and
#: anime rule 2 sharpens it: under an inverted-hull outline every modelled crease
#: becomes a black line, so modelled detail is now actively worse than before.
CORE_STYLE_TOKENS = [
    "anime style low-poly 3D game asset",
    "bold readable silhouette",
    "surface detail painted in the texture, not modelled",
]

#: Applied to every asset when there is room, most important token first.
#:
#: Held as a list rather than one string because prompts are capped at 600
#: characters by the API. When a detailed subject uses most of that budget,
#: whole tokens are dropped from the end of this list instead of the string
#: being cut mid-clause, so the surviving prompt is always well formed.
#:
#: The first token carries anime rule 3 and is phrased positively on purpose:
#: "flat unshaded colour" asks for the thing we want, where the equivalent
#: negative ("no baked shading") would spend the same characters asking the
#: generator not to do something the eighteen-token avoid list already proved it
#: will do anyway. The old "even neutral lighting" is gone entirely — asking for
#: *any* lighting invites it into the texture, which is the one thing rule 3
#: forbids.
BASE_STYLE_TOKENS = [
    "flat unshaded colour",
    "large simple forms, very few small details",
    "saturated separated hues on neighbouring parts",
    "crisp hard edges between large planes",
]

#: Tokens that keep the *mesh* away from the failure modes in section 6, most
#: important first, for the same reason.
#:
#: Deliberately short. Meshy has no negative-prompt field, so an avoid clause is
#: only a suggestion riding along in the positive prompt, and a long one is
#: measurably worse than a short one for two reasons. It is weak: a tree
#: generated with "base plinth", "ground plane" and "scenery around the object"
#: all present came back standing on a baked grass disc anyway, and a barrel came
#: back with grass tufts. And it is expensive: at eighteen tokens it filled 380 of
#: the 600 characters and pushed out "clustered angular canopy masses rather than
#: individual leaves" — positive direction, which in the same two samples *did*
#: land. Space spent saying what we want beats space spent saying what we don't.
#:
#: So each entry here has to earn its characters, and anything that describes a
#: painted surface rather than a shape belongs in TEXTURE_AVOID_TOKENS instead —
#: telling a mesh generator to avoid "logos" was pure waste.
BASE_AVOID_TOKENS = [
    "photorealistic",
    "hyperdetailed",
    # Keeps detail out of the mesh. Measured: a barrel whose iron bands were
    # modelled as raised geometry became a torn lump under every reduction,
    # because the reducer had real geometry to destroy.
    "surface detail modelled as raised trim or extruded panel lines",
    # Scenery the generator adds unasked, and the costliest failure of the three.
    # It is worse than ugly: the ground disc inflates the bounding box, so height
    # normalisation shrinks the actual asset to fit scenery nobody wants, and
    # every instance in the village carries its own identical clump of grass.
    "any ground, base, plinth, terrain or scenery beneath or around the object",
    "dense engraved ornament, many tiny straps and buckles",
]

#: Avoid tokens for the *texture* prompt. Separate from the geometry list because
#: the two prompts fail in different directions and share no failure mode worth
#: the characters: a mesh cannot have a logo, and a texture cannot have a plinth.
#:
#: Still four tokens, because this whole list is packed as one optional element:
#: if it grows past the space a long hero subject leaves, it is not truncated, it
#: is dropped entirely. Third and fourth carry anime rules 3 and 5 — painted
#: highlights and soft gradients are the two shapes baked lighting arrives in, and
#: a desaturated palette destroys the hue separation that a collapsed value range
#: leaves as the only way to tell a brown belt from a brown tunic.
TEXTURE_AVOID_TOKENS = [
    "photographic detail",
    "printed text, stencilled markings or logos",
    "baked shadows, ambient occlusion or painted highlights",
    "soft gradients, muddy desaturated colours",
]

#: Per-class **shape** direction, and where anime rule 4 is implemented. These are
#: the deltas that give a class its identity at 30 metres on a tactical camera,
#: which is the only distance that matters.
#:
#: Rule 4 is now "small, chunky-limbed anime proportion", and it is stated in
#: numbers because the vaguer version failed twice: two characters generated with
#: "anime proportions with a slightly enlarged head" came back as the same
#: seven-and-a-half-head soldier. "five heads tall" is a ratio the generator can
#: act on; "anime proportions" is not. The old chibi avoid token is gone with it
#: — it was defending a 1.7m adult build that is no longer what we want.
#:
#: Oversized hands and feet do more work than they look like they should. They are
#: what separates this from a shrunken adult, and they are large forms, which is
#: what survives reduction, an outline pass and a 60-pixel-tall unit.
#:
#: Each entry is split on commas by _tokens, so a clause at a time is dropped when
#: a subject is long, and only the *first* clause is protected. The whole
#: proportion statement is therefore written without internal commas: as three
#: clauses, hero_rowan's long subject kept "five heads tall, big head" and dropped
#: the oversized hands and shoes, which are precisely what separates this build
#: from a shrunken adult.
#:
#: Colour deliberately does not live here. It goes in CLASS_PALETTE and rides the
#: texture prompt, which is both the correct place for it and the one with room
#: to spare — a detailed hero subject fills the geometry prompt's 600 characters
#: and would otherwise push the palette rule out entirely.
CLASS_STYLE: dict[str, str] = {
    "hero": (
        "small anime hero five heads tall with a big head oversized hands and "
        "large simple shoes, slim limbs, hair in one solid angular mass, "
        "large clean eyes"
    ),
    "npc": (
        "small anime villager five heads tall with a big head oversized hands and "
        "large simple shoes, slim limbs, cloth in a few big folds"
    ),
    "enemy_humanoid": (
        "small anime enemy five heads tall with a big head and oversized hands "
        "and feet, slim limbs, crude asymmetric armour plates, exaggerated weapon"
    ),
    "monster_large": (
        "oversized head and paws on a heavy mass, exaggerated dominant feature such "
        "as jaws claws or horns, readable animal silhouette"
    ),
    "boss": (
        "big head and oversized hands on a theatrical silhouette, large-form armour "
        "with few big shapes, unmistakable profile"
    ),
    "weapon": (
        "oversized game-readable proportions, thick blade or shaft, "
        "simple pommel and guard"
    ),
    "prop": "chunky hand-made village craft object, simple solid form",
    "vegetation": (
        "clustered angular canopy masses rather than individual leaves, "
        "sturdy simple trunk"
    ),
    "building_module": (
        "modular kit piece with flush edges for tiling, "
        "clean straight roof and wall planes, simple boxy massing"
    ),
    "set_piece": (
        "monumental scale with large unbroken planes, "
        "no human-scale detail anywhere, silhouette read from far away"
    ),
}

#: Per-class **colour** direction, applied to the texture prompt, and where anime
#: rule 5 is implemented.
#:
#: Rule one of docs/STYLE_GUIDE.md is one dominant hue per character, and this is
#: where that rule is actually enforced on the generator.
#:
#: Every entry now separates by *hue* rather than by value or shade, because the
#: two-band ramp collapses the value range by design: a brown belt on a brown
#: tunic that differed only in brightness reads as one brown shape once the shader
#: has quantised it to two tones. The old vegetation entry — "clear light and
#: shadow greens" — was worse than merely weak, it asked the generator to paint
#: the light, which is exactly the rule 3 failure that produces mud under the real
#: shader. set_piece keeps a value instruction on purpose: backdrops recede by
#: value (style guide rule 6), and a distant wall has no neighbouring material to
#: separate itself from anyway.
CLASS_PALETTE: dict[str, str] = {
    "hero": "one dominant saturated costume hue, one bright accent hue, clean bright metal",
    "npc": "one clear costume hue with a single brighter accent hue",
    "enemy_humanoid": "cohesive faction hue across every unit of the type, one contrast hue",
    "monster_large": "two-hue creature palette, skin and plate clearly different hues",
    "boss": "one dramatic saturated accent hue against deep cool darks",
    "weapon": "metal and wood as two clearly different hues, not two browns",
    # Deliberately material-agnostic. The old wording named wood and iron, which a
    # clay urn, a stone well and a stone fountain all inherited from the same class.
    "prop": "two or three flat material hues clearly separated, bands and seams painted on",
    "vegetation": "two flat foliage greens separated by hue, warmer trunk hue",
    "building_module": (
        "plaster, timber and thatch as three distinct hues, "
        "timber framing painted on rather than modelled"
    ),
    "set_piece": "narrow value range so it recedes behind foreground units",
}

#: Extra avoid-tokens per class, layered on top of BASE_AVOID.
#:
#: "realistic adult body proportions" is the other half of anime rule 4, and it
#: replaces the chibi token that used to sit here — the direction reversed, so the
#: thing to push away from is the realistic soldier the generator keeps returning,
#: not the small build we now want. It is deliberately *not* in BASE_AVOID: it is
#: only meaningful for the humanoid classes, and the avoid clause is the scarcest
#: space in the prompt — a prop paying characters for it would push real direction
#: out, which is the failure recorded in docs/ASSET_PIPELINE.md.
#:
#: The npc entry no longer says "armour, weapons". It contradicted half the class:
#: npc_guard_greenvale's subject is a soldier "over mail with a conical helm, round
#: shield and short sword", so the prompt was arguing with itself, and a prompt
#: that argues with itself spends characters to buy nothing.
CLASS_AVOID: dict[str, str] = {
    "hero": "generic knight, realistic adult body proportions, modern clothing",
    "npc": "realistic adult body proportions, heroic pose",
    "enemy_humanoid": "realistic adult body proportions",
    # "metal shipping container" is gone. Meshy has no negative-prompt field, so
    # every avoid token is also a noun sitting in the positive prompt, and the one
    # asset that carried this token is prop_crate_a — which came back photoreal
    # with metal corner brackets and stencilled lettering, i.e. a shipping crate.
    # Naming the failure mode is not free when the naming happens in the prompt.
    "prop": "modern materials, plastic",
    "vegetation": "individual leaf geometry, thin twigs, transparent planes",
    "building_module": "interior furniture",
}

# ---------------------------------------------------------------------------
# Regional palettes, from brief section 59
# ---------------------------------------------------------------------------

#: Colour temperature and value range per region. Applied as texture guidance so
#: a Greenvale barrel and a Vaelor barrel read as different places from the same
#: mesh.
#:
#: These describe *palette only*, never scene content: a region string that
#: mentioned foliage would tint every barrel in the region green.
#:
#: "desaturated" is gone from ruins and vaelor. Anime rule 5 needs saturation to
#: separate neighbouring materials by hue, and TEXTURE_AVOID_TOKENS now bans muddy
#: desaturated colour outright, so a region asking for the banned thing was the
#: same self-contradiction as telling a guard to avoid armour. Regional identity is
#: bought instead by naming the hue the region is biased towards, which is a
#: positive instruction and reads as a stronger place-difference, not a weaker one.
REGIONS: dict[str, str] = {
    "greenvale": "warm afternoon palette, bright mid values, gentle contrast",
    "ruins": "cool blue-grey palette, low mid values, sparse warm highlight hue",
    "vaelor": "cold steel-blue palette, dark values, one warm orange accent hue",
    "outer_world": "dusty ochre and teal palette, weathered mid values",
    "neutral": "",
}


#: The API rejects prompts over this length outright.
PROMPT_LIMIT = 600

#: Characters held back from the geometry prompt for the avoid clause. Without a
#: reservation the avoid tokens sit last and get dropped first, which is exactly
#: backwards: they are what keeps a detailed subject from drifting realistic.
AVOID_RESERVE = 170


@dataclass(frozen=True)
class Prompt:
    """A resolved prompt pair, ready for the Meshy client."""

    geometry: str
    texture: str
    #: Style tokens that did not fit. Surfaced by the `prompt` command so an
    #: over-long subject is a visible decision rather than a silent loss.
    dropped: tuple[str, ...] = ()

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"geometry: {self.geometry}\ntexture:  {self.texture}"


def _tokens(*parts: str) -> list[str]:
    """Split comma-separated fragments into individual style tokens."""
    out: list[str] = []
    for part in parts:
        for token in str(part).split(","):
            token = token.strip()
            if token:
                out.append(token)
    return out


def _truncate(text: str, limit: int) -> str:
    """Cut on a word boundary, marking the cut."""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",") + "…"


def _dedupe(tokens: list[str], seen: set[str] | None = None) -> list[str]:
    """Drop repeated tokens, keeping the first occurrence.

    Style arrives from several layers that legitimately overlap — a crate whose
    catalog ``surface`` said "warm painted wood tones" got it a second time from
    the prop palette, and the repeat bought nothing but characters that a real
    token then failed to fit into.
    """
    seen = set() if seen is None else seen
    out: list[str] = []
    for token in tokens:
        key = token.lower()
        if key not in seen:
            seen.add(key)
            out.append(token)
    return out


def _pack(
    required: list[str], optional: list[str], limit: int, *, seen: set[str] | None = None
) -> tuple[str, list[str]]:
    """Join required tokens plus as many optional ones as fit.

    Returns the joined text and the optional tokens that were dropped. Required
    tokens are never dropped; callers must size them to fit before calling.

    ``seen`` pre-loads the dedupe. The geometry prompt needs it because its
    required half arrives as one already-joined string, so the tokens inside it
    are invisible to _dedupe: a house whose catalog said "simple boxy massing"
    got it a second time from the building class, and paid twice.
    """
    seen = set() if seen is None else set(seen)
    required = _dedupe(required, seen)
    optional = _dedupe(optional, seen)
    text = ", ".join(required)
    if len(text) > limit:
        return _truncate(text, limit), list(optional)

    dropped: list[str] = []
    for token in optional:
        candidate = f"{text}, {token}" if text else token
        if len(candidate) <= limit:
            text = candidate
        else:
            dropped.append(token)
    return text, dropped


def build(
    subject: str,
    class_key: str,
    *,
    region: str = "neutral",
    extra: str = "",
    avoid: str = "",
    surface: str = "",
) -> Prompt:
    """Resolve a catalog entry into geometry and texture prompts.

    ``subject`` describes the *form*: the silhouette a modeller would block out.
    ``surface`` describes detail that must be **painted rather than modelled** —
    iron bands, plank seams, rivets, carved runes, painted trim. It is added to
    the texture prompt and deliberately kept out of the geometry prompt, so the
    generator has no reason to build it as geometry.

    That split is the single biggest lever on asset quality in this pipeline.
    A barrel described as "wooden barrel with three iron bands" gets bands
    modelled as raised rings, which cost triangles and tear apart under any
    reduction. The same barrel as form "smooth tapered barrel" plus surface
    "three iron bands" gets a clean drum and the bands in the texture, where they
    read identically at tactical-camera distance for a fraction of the cost.

    Meshy takes the geometry prompt at preview time and the texture prompt at
    refine time, so silhouette language goes in the former and colour language
    in the latter. Both are packed to fit ``PROMPT_LIMIT`` by dropping whole
    low-priority style tokens, in this order of precedence:

        subject, per-asset extras, core style  (never dropped)
        the class signature clause             (never dropped)
        avoid clause                           (gets all remaining space)
        rest of the class art direction        (dropped before the subject)
        remaining house style tokens           (dropped first)
    """
    budget = budgets.get(class_key)

    # 1. What can never be dropped: the subject, the catalog's own extra
    #    direction, the core style tokens, and the first clause of the class
    #    direction. If a subject is long enough to crowd them out, the *subject*
    #    is what gets trimmed — an asset generated without the house style is
    #    off-style by definition, so keeping every word of an over-long
    #    description would be the wrong trade.
    #
    #    The class signature is protected because measured on the real catalogs it
    #    was not surviving: _pack fills greedily, so a 69-character proportion
    #    clause was skipped and three shorter tail tokens took its place. Every
    #    character in prologue_cast.json lost "anime proportions ..." that way,
    #    which would have made anime rule 4 a no-op in the one prompt that decides
    #    the mesh. Vegetation lost its canopy clause to a different mechanism once
    #    before — an eighteen-token avoid list — and the tree grew individual
    #    leaves. Losing the class signature has cost us a generation twice now, so
    #    it stops being optional.
    #    Style and proportion lead; the subject follows. The order is the whole
    #    point and it was learned twice, the second time expensively.
    #
    #    On the texture prompt, a crate whose prompt opened "square wooden
    #    shipping crate" came back photoreal with real grain and stencilled
    #    lettering despite "photorealistic" sitting in the avoid list. Putting
    #    "hand-painted stylized game texture, not photographic" in front of the
    #    subject fixed it in one generation.
    #
    #    The geometry prompt kept the old order, and it failed the same way three
    #    times. As sent, the guard's prompt opened with 200 characters of "human
    #    Greenvale soldier in a green tabard over mail with a conical helm, round
    #    shield and short sword" — an unambiguously realistic adult — and only
    #    then mentioned five heads. A realistic noun phrase in front carries an
    #    overwhelming prior, exactly as "shipping crate" did, and the proportion
    #    clause was arguing with it from fifth place instead of setting the frame.
    core_text = ", ".join(CORE_STYLE_TOKENS)
    class_clauses = _tokens(CLASS_STYLE.get(class_key, ""))
    signature = class_clauses[0] if class_clauses else ""
    #    Order settled by experiment and then left alone. Style tokens, then the
    #    class signature, then the subject. Pushing the signature ahead of the
    #    core tokens as well was tried and came back a tall thin figure in a long
    #    tunic, worse than this order on every count -- but that is one sample
    #    against a generator measured at 31-41% variance on repeat runs of an
    #    identical prompt, so it is not evidence that first place is harmful. It
    #    is only a reason to keep the arrangement that produced the best result
    #    and stop spending 30 credits a time on orderings we cannot tell apart.
    fixed_text = f"{core_text}, {signature}" if signature else core_text
    subject_text = ", ".join(_tokens(subject, extra))
    room_for_subject = PROMPT_LIMIT - AVOID_RESERVE - len(fixed_text) - 2
    subject_text = _truncate(subject_text, room_for_subject)
    required_text = f"{fixed_text}, {subject_text}" if subject_text else fixed_text

    # 2. The avoid clause gets whatever space is left rather than a fixed slice:
    #    a short subject should get the full avoid list, not an arbitrarily
    #    truncated one. AVOID_RESERVE is only the floor guaranteed above.
    #
    #    Universal tokens first, then class-specific and per-asset ones, then the
    #    rest of the generic list — "generic knight" does more work than "logos",
    #    so it must not be the first thing squeezed out.
    #
    #    Meshy has no negative-prompt field, so these ride along as an explicit
    #    clause. Weaker than a real negative prompt, measurably better than
    #    omitting them.
    avoid_tokens = (
        BASE_AVOID_TOKENS[:3]
        + _tokens(CLASS_AVOID.get(class_key, ""), avoid)
        + BASE_AVOID_TOKENS[3:]
    )
    avoid_text, avoid_dropped = _pack(
        ["avoid: " + avoid_tokens[0]],
        avoid_tokens[1:],
        PROMPT_LIMIT - len(required_text) - 2,
    )

    # 3. Remaining house style fills whatever is still free. The triangle hint
    #    sits last on purpose: target_polycount is passed to the API as a real
    #    parameter, so losing the prompt version costs nothing.
    optional = class_clauses[1:] + BASE_STYLE_TOKENS + [
        f"clean topology around {budget.tri_target} triangles"
    ]
    geometry, style_dropped = _pack(
        [required_text],
        optional,
        PROMPT_LIMIT - len(avoid_text) - 2,
        seen={token.lower() for token in _tokens(required_text)},
    )
    geometry = f"{geometry}, {avoid_text}"

    # Texture. Style leads, subject follows.
    #
    # The order matters and was learned the hard way. With the subject first, a
    # crate came back photoreal: real wood grain, screwed metal corner brackets
    # and stencilled lettering, despite "photorealistic" sitting in the avoid
    # list. A subject like "shipping crate" carries an overwhelming photographic
    # prior, and putting it in front of the style direction lets that prior win.
    #
    # So the prompt now opens by naming what kind of image this is, and only then
    # says what it depicts.
    #
    # The opener names the medium, not the lighting: "flat unshaded colour blocks"
    # is anime rule 3, and there is deliberately no "cel shaded" anywhere near it.
    # The engine's toon ramp needs an unlit albedo to band; hand it a texture with
    # bands already in it and it bands the bands.
    texture_required = _tokens(
        "hand-painted anime game texture, flat unshaded colour blocks, "
        "crisp colour edges, not photographic",
        subject,
        surface,
        CLASS_PALETTE.get(class_key, ""),
    )
    # Region palette first, then the avoid clause, then the rest. Positive
    # direction outranks negative direction here for the same reason it does in
    # the geometry prompt: in every sample so far the palette landed and the
    # avoid tokens were a coin flip.
    texture_optional = (
        _tokens(REGIONS.get(region, ""))
        + ["avoid: " + ", ".join(TEXTURE_AVOID_TOKENS)]
        # Hue contrast, not value contrast: the shader quantises value into two
        # bands, so two materials differing only in value collapse into one flat
        # shape once it has run. Hue is what survives.
        + _tokens("strong hue contrast between neighbouring materials", extra)
    )
    texture, texture_dropped = _pack(texture_required, texture_optional, PROMPT_LIMIT)

    return Prompt(
        geometry=geometry,
        texture=texture,
        dropped=tuple(style_dropped + avoid_dropped + texture_dropped),
    )


def region_keys() -> list[str]:
    return sorted(REGIONS)

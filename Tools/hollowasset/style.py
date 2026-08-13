"""The Hollow Crown prompt grammar.

Brief section 6 asks for "simple geometry, rich atmosphere" and section 89 asks
for shapes that stay readable at tactical-camera distance. Shining Force II is
the agreed touchstone for that look, so this module encodes what that game
actually *does* visually and feeds it to the generator as concrete art
direction.

Two rules govern this file, and both matter for a commercial Steam release:

1. No prompt ever names Shining Force, Sega, or any character from it. We
   describe the visual language in our own terms. See docs/STYLE_GUIDE.md for
   why this distinction is not cosmetic.
2. Style lives here, not in the catalog. Catalog entries describe *subjects*;
   this module decides how they look. Changing the game's art direction should
   be one edit here, not a sweep through every asset definition.
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
#: The third is the most important and the last to be learned. Anything that can
#: be painted must be painted. A barrel's iron bands, a plank seam, a rivet, a
#: carved rune are surface detail: modelled they cost geometry, break under any
#: reduction, and read no better at tactical-camera distance than a texture does.
#: Brief section 6 says it in four words — simple geometry, rich atmosphere.
CORE_STYLE_TOKENS = [
    "stylized low-poly 3D game asset",
    "bold readable silhouette",
    "surface detail painted in the texture, not modelled",
]

#: Applied to every asset when there is room, most important token first.
#:
#: Held as a list rather than one string because prompts are capped at 600
#: characters by the API. When a detailed subject uses most of that budget,
#: whole tokens are dropped from the end of this list instead of the string
#: being cut mid-clause, so the surviving prompt is always well formed.
BASE_STYLE_TOKENS = [
    "clean flat-shaded surfaces",
    "saturated storybook fantasy palette",
    "large simple forms, very few small details",
    "even neutral lighting",
]

#: Tokens that keep the generator away from the failure modes in section 6,
#: most important first, for the same reason.
BASE_AVOID_TOKENS = [
    "photorealistic",
    "hyperdetailed",
    # The three that keep detail out of the mesh. Measured: a barrel whose iron
    # bands were modelled as raised geometry became a torn lump under every
    # reduction, because the reducer had real geometry to destroy.
    "modelled surface detail",
    "raised bands or trim",
    "extruded panel lines",
    "grimdark",
    "muddy colours",
    "baked shadows",
    "dense engraved ornament",
    "many tiny straps and buckles",
    "base plinth",
    "ground plane",
    "text",
    "logos",
]

#: Per-class **shape** direction. These are the deltas that give a class its
#: identity at 30 metres on a tactical camera, which is the only distance that
#: matters.
#:
#: Colour deliberately does not live here. It goes in CLASS_PALETTE and rides the
#: texture prompt, which is both the correct place for it and the one with room
#: to spare — a detailed hero subject fills the geometry prompt's 600 characters
#: and would otherwise push the palette rule out entirely.
CLASS_STYLE: dict[str, str] = {
    "hero": (
        "heroic proportions with broad shoulders and a slightly oversized head, "
        "distinctive hairstyle, strong cape or shoulder shape, iconic weapon"
    ),
    "npc": "ordinary villager build, simple cloth shapes",
    "enemy_humanoid": (
        "menacing but readable build, crude asymmetric armour plates, exaggerated weapon"
    ),
    "monster_large": (
        "heavy imposing mass, exaggerated dominant feature such as jaws claws or horns, "
        "readable animal silhouette"
    ),
    "boss": (
        "commanding scale and theatrical silhouette, ornate but large-form armour, "
        "unmistakable profile"
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

#: Per-class **colour** direction, applied to the texture prompt.
#:
#: Rule one of docs/STYLE_GUIDE.md is one dominant hue per character, and this is
#: where that rule is actually enforced on the generator.
CLASS_PALETTE: dict[str, str] = {
    "hero": "one dominant costume hue plus one bright accent and clean metal",
    "npc": "muted earthy costume with a single brighter accent colour",
    "enemy_humanoid": "cohesive faction colour across every unit of the type",
    "monster_large": "two-colour creature palette",
    "boss": "single dramatic accent colour against dark values",
    "weapon": "clear metal and wood separation",
    "prop": "warm painted wood tones, plank seams and iron bands painted on",
    "vegetation": "two-tone foliage with clear light and shadow greens",
    "building_module": (
        "plaster, timber and thatch as three distinct values, "
        "timber framing painted on rather than modelled"
    ),
    "set_piece": "narrow value range so it recedes behind foreground units",
}

#: Extra avoid-tokens per class, layered on top of BASE_AVOID.
CLASS_AVOID: dict[str, str] = {
    "hero": "generic knight, faceless armour, modern clothing",
    "npc": "armour, weapons, heroic pose",
    "prop": "modern materials, plastic, metal shipping container",
    "vegetation": "individual leaf geometry, thin twigs, transparent planes",
    "building_module": "interior furniture, terrain, surrounding ground",
}

# ---------------------------------------------------------------------------
# Regional palettes, from brief section 59
# ---------------------------------------------------------------------------

#: Colour temperature and value range per region. Applied as texture guidance so
#: a Greenvale barrel and a Vaelor barrel read as different places from the same
#: mesh.
#:
#: These describe *light and value only*, never scene content: a region string
#: that mentioned foliage would tint every barrel in the region green.
REGIONS: dict[str, str] = {
    "greenvale": "warm afternoon colour temperature, bright mid values, gentle contrast",
    "ruins": "cool desaturated colour temperature, low mid values, sparse warm highlights",
    "vaelor": "cold desaturated colour temperature, dark values, one warm orange accent",
    "outer_world": "dusty ochre and teal colour temperature, weathered mid values",
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


def _pack(required: list[str], optional: list[str], limit: int) -> tuple[str, list[str]]:
    """Join required tokens plus as many optional ones as fit.

    Returns the joined text and the optional tokens that were dropped. Required
    tokens are never dropped; callers must size them to fit before calling.
    """
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
        avoid clause                           (gets all remaining space)
        class art direction                    (dropped before the subject)
        remaining house style tokens           (dropped first)
    """
    budget = budgets.get(class_key)

    # 1. What can never be dropped: the subject, the catalog's own extra
    #    direction, and the core style tokens. If a subject is long enough to
    #    crowd out the core tokens, the *subject* is what gets trimmed — an asset
    #    generated without the house style is off-style by definition, so keeping
    #    every word of an over-long description would be the wrong trade.
    core_text = ", ".join(CORE_STYLE_TOKENS)
    subject_text = ", ".join(_tokens(subject, extra))
    room_for_subject = PROMPT_LIMIT - AVOID_RESERVE - len(core_text) - 2
    subject_text = _truncate(subject_text, room_for_subject)
    required_text = f"{subject_text}, {core_text}" if subject_text else core_text

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
    optional = _tokens(CLASS_STYLE.get(class_key, "")) + BASE_STYLE_TOKENS + [
        f"clean topology around {budget.tri_target} triangles"
    ]
    geometry, style_dropped = _pack(
        [required_text], optional, PROMPT_LIMIT - len(avoid_text) - 2
    )
    geometry = f"{geometry}, {avoid_text}"

    # Texture. The subject anchors it, then the class palette rule, which is
    # required rather than optional: it is rule one of the style guide and the
    # single strongest lever on whether a cast reads as one art direction.
    # Region light outranks the generic painting notes, because it is what makes
    # the same mesh read as a different place.
    texture, texture_dropped = _pack(
        _tokens(subject, surface, "hand-painted stylized game texture",
                CLASS_PALETTE.get(class_key, "")),
        _tokens(
            REGIONS.get(region, ""),
            "flat colour blocks with soft gradients",
            "no baked shadows",
            "high value contrast between neighbouring materials",
            extra,
        ),
        PROMPT_LIMIT,
    )

    return Prompt(
        geometry=geometry,
        texture=texture,
        dropped=tuple(style_dropped + avoid_dropped + texture_dropped),
    )


def region_keys() -> list[str]:
    return sorted(REGIONS)

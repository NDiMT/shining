"""Two sprite tiers, measured off Shining Force II rather than guessed.

The numbers below come from the Shining Force Central disassembly tooling, which
states the game's own formats:

* ``SF2MapSpriteManager`` lays map sprites out at **24x24 pixels**, and its
  importer requires **"4BPP / 16 indexed colors, transparent color at index 0"**.
* ``SF2BattleSpriteManager`` builds a battle frame as ``tilesPerRow * 8`` wide by
  ``12 * 8`` tall, with ``tilesPerRow`` 12 for an ally and 16 for a monster --
  **96x96 for a party member, 128x96 for an enemy** -- and stores each palette as
  32 bytes, which is sixteen Genesis CRAM entries. Same 16 colours.

    SF2 map sprite     24x24    16 colours
    SF2 ally battle    96x96    16 colours
    SF2 enemy battle  128x96    16 colours

What was built before reading any of that: a 64x64 map sprite and a 128x128
battle sprite, both "highly detailed" with "detailed shading" and full 24-bit
colour. Roughly seven times the pixel area on the map tier, and thousands of
colours where the reference has fifteen. Chasing *more* detail was the mistake --
Shining Force II is a game of hard restraint, and the restraint is what reads.

Both of those corrections then went too far. Forcing flat shading and quantising
to sixteen colours was measured against the raw output on the same subject four
ways, and the raw sprites won every time: the tunic washed out, the cape went
dull, faces flattened. PixelLab already produces disciplined pixel art, and its
hundred-odd colours are shading ramps rather than photographic noise. So the
tiers ask for real shading again, quantising is opt-in and off, and the Genesis
palette is kept for a ROM export where 4BPP is a file format rather than taste.

Sizes are the nearest the API supports. ``animate-with-skeleton`` takes 16, 32,
64, 128 or 256 and nothing between; ``animate-with-text`` is 64 only; and
``bitforge``, the only endpoint that style-matches, caps at an area of 200x200.
So the map tier is 32 (nearest to 24) and the battle tier is 128 (nearest to 96
that is both style-matchable and animatable).

Art direction lives here and nowhere else, exactly as it did for the 3D pipeline:
changing the game's look should be one edit in this file, not a sweep through
every catalog entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tier:
    """Everything that differs between a map sprite and a battle sprite."""

    key: str
    size: int
    view: str
    direction: str
    outline: str
    shading: str
    detail: str
    #: Appended to every description in this tier.
    direction_tokens: tuple[str, ...] = ()
    #: Facings generated for this tier. West and north-west are mirrored from
    #: their opposites rather than generated, because a rotation costs about what
    #: a fresh sprite costs and a mirrored sprite is exact.
    facings: tuple[str, ...] = ()
    #: Comma clauses of the subject this tier keeps. A prompt has to shrink with
    #: the pixel budget: at 32 pixels a fifteen-clause description of belts and
    #: trim is not detail the sprite can hold, it is noise competing for the same
    #: four hundred pixels, and it came back as mush. Three clauses -- who it is,
    #: the dominant colour, the one accent -- is what 24x24 can actually carry.
    subject_clauses: int | None = None
    subdir: str = ""
    notes: str = ""

    def describe(self, subject: str) -> str:
        return ", ".join([subject, *self.direction_tokens])


#: Exploration. Read at a glance, twelve at a time, on a busy grid.
#:
#: Super-deformed is not a stylistic flourish, it is what 24 pixels forces. At
#: that size a realistic figure has about four pixels of head, which cannot carry
#: a face or an identity. SF2 gives the head nearly half the sprite and draws the
#: eyes as two dots. This is also, finally, the "small chunky proportion" the 3D
#: direction asked for five times and never got.
MAP = Tier(
    key="map",
    size=64,
    view="high top-down",
    direction="south",
    outline="single color black outline",
    shading="flat shading",
    detail="medium detail",
    direction_tokens=(
        "super deformed chibi sprite",
        "huge head, tiny body, two heads tall",
        "dot eyes, no facial detail",
        "no weapon drawn",
        "solid flat colour blocks",
        "16 colour Sega Genesis palette",
    ),
    facings=("south", "south-east", "east", "north-east", "north"),
    subject_clauses=3,
    subdir="Characters",
    notes="24x24 in SF2, but 32 produced noise on four separate attempts and "
          "64 does not. Mirror east to west and north-east to north-west.",
)

#: The attack screen. One figure filling the frame, so detail earns its pixels.
BATTLE = Tier(
    key="battle",
    size=128,
    view="side",
    direction="east",
    outline="single color black outline",
    shading="medium shading",
    detail="highly detailed",
    direction_tokens=(
        "16 bit Sega Genesis JRPG battle sprite",
        "four heads tall, large head",
        "solid flat colour blocks, one highlight and one shadow tone",
        "bold black outline, no anti-aliasing",
        "16 colour palette",
    ),
    facings=("east",),
    subdir="Battle",
    notes="96x96 for an ally in SF2; 128 is the nearest size that is both "
          "style-matchable and animatable. Mirror east to west -- the attack "
          "screen only ever shows two facings.",
)

TIERS: dict[str, Tier] = {tier.key: tier for tier in (MAP, BATTLE)}

#: Applied to every sprite in the game, both tiers. The house style.
#:
#: "limited palette" and "no gradients" are here rather than in one tier because
#: they are the era, not the tier. palette.py enforces the count afterwards; this
#: is about getting the generator to paint in blocks in the first place, so that
#: quantising has flat areas to keep rather than ramps to destroy.
HOUSE_TOKENS: tuple[str, ...] = (
    "16 bit era pixel art",
    "limited palette, no gradients, no dithering",
    "saturated storybook fantasy colours",
    "clean hard pixel edges",
)

#: Never wanted, either tier. Short on purpose: the same lesson the 3D prompt
#: grammar learned the expensive way is that space spent saying what we want
#: beats space spent saying what we don't.
AVOID_TOKENS: tuple[str, ...] = (
    "blurry",
    "anti-aliased",
    "soft gradients",
    "dithering",
    "photographic",
    "3d render",
    "modern high detail pixel art",
    "text or watermark",
)

#: Regional palettes, carried over from the 3D direction because the regions did
#: not change when the renderer did. Light and value only, never scene content: a
#: region string that mentioned foliage would tint every character green.
REGIONS: dict[str, str] = {
    "greenvale": "warm afternoon palette, bright mid values",
    "ruins": "cool desaturated palette, low mid values, sparse warm highlights",
    "vaelor": "cold palette, dark values, one warm orange accent",
    "outer_world": "dusty ochre and teal palette, weathered mid values",
    "neutral": "",
}


@dataclass(frozen=True)
class Prompt:
    description: str
    negative: str
    tier: Tier


def build(subject: str, tier_key: str, *, region: str = "neutral",
          extra: str = "", avoid: str = "") -> Prompt:
    """Resolve a subject into a prompt for one tier.

    Deliberately not the 600-character packing problem the 3D grammar solved:
    PixelLab imposes no prompt length limit, so priority ordering and token
    dropping are machinery this pipeline does not need and should not inherit.
    """
    if tier_key not in TIERS:
        raise KeyError(f"unknown tier {tier_key!r}; known: {', '.join(sorted(TIERS))}")
    tier = TIERS[tier_key]
    if region not in REGIONS:
        raise KeyError(f"unknown region {region!r}; known: {', '.join(sorted(REGIONS))}")

    clauses = [c.strip() for c in subject.split(",") if c.strip()]
    if tier.subject_clauses:
        clauses = clauses[: tier.subject_clauses]
    parts = [", ".join(clauses), *tier.direction_tokens, *HOUSE_TOKENS]
    if REGIONS[region]:
        parts.append(REGIONS[region])
    if extra:
        parts.append(extra)

    negative = list(AVOID_TOKENS)
    if avoid:
        negative.append(avoid)

    return Prompt(", ".join(parts), ", ".join(negative), tier)


def tier(key: str) -> Tier:
    if key not in TIERS:
        raise KeyError(f"unknown tier {key!r}; known: {', '.join(sorted(TIERS))}")
    return TIERS[key]

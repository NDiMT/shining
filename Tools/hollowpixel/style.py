"""Two sprite tiers, and the house art direction for both.

Shining Force II draws every character twice, and Hollow Crown does the same
because it is the right answer rather than an homage. Exploration shows a dozen
units at once on a grid, so a map sprite has to read as a silhouette at a glance
and nothing else. The attack screen shows one attacker and one defender filling
the frame, so a battle sprite can carry a face, a weapon and cloth.

    MAP      64x64   high top-down   compact, chunky, silhouette-first
    BATTLE  128x128  side            detailed, full figure, animated

Those numbers are not preferences. Three API limits fix them between them:

* ``animate-with-text`` accepts **64x64 only**.
* ``animate-with-skeleton`` accepts **16, 32, 64, 128, 256** and nothing between.
* ``bitforge`` -- the only endpoint that style-matches a reference -- caps at an
  area of **200x200**.

So 128 is the largest size that can be *both* style-matched to the rest of the
cast *and* animated, which makes it the battle tier. 256 would be bigger and
could not be style-matched, and a cast that drifts is the failure that cost the
3D pipeline five generations on one guard. The map tier is 64, and that was measured rather than assumed. 32 is the
compact-looking answer and it does not work: at 32 the figure came back as mush
whatever the style strength, because the detail has nowhere to go. 64 keeps a
readable head, a weapon and a silhouette, and it is also the only size
``animate-with-text`` accepts -- so the compact tier animates the cheap way and
the battle tier animates by skeleton.

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
    subdir: str = ""
    notes: str = ""

    def describe(self, subject: str) -> str:
        return ", ".join([subject, *self.direction_tokens])


#: Exploration. Read at a glance, twelve at a time, on a busy grid.
#:
#: "chunky" and "large head" are doing the same job the 3D direction's rule 4
#: was after and never achieved: at this size a realistic figure is a smudge,
#: and the head is the only part with room to carry identity.
MAP = Tier(
    key="map",
    size=64,
    view="high top-down",
    direction="south",
    outline="single color black outline",
    shading="basic shading",
    detail="low detail",
    direction_tokens=(
        "chunky compact game sprite",
        "large head and small body",
        "bold simple silhouette",
        "few flat colours",
        "no small details",
    ),
    facings=("south", "south-east", "east", "north-east", "north"),
    subdir="Characters",
    notes="Mirror east to west and north-east to north-west at draw time. "
          "style_strength 60 against the battle sprite: 25 loses the palette, "
          "70 drags battle-tier detail down into a frame that cannot hold it.",
)

#: The attack screen. One figure filling the frame, so detail earns its pixels.
BATTLE = Tier(
    key="battle",
    size=128,
    view="side",
    direction="east",
    outline="single color black outline",
    shading="detailed shading",
    detail="highly detailed",
    direction_tokens=(
        "full body battle sprite",
        "dynamic combat stance",
        "detailed face and weapon",
        "readable cloth folds",
        "rich shading",
    ),
    facings=("east",),
    subdir="Battle",
    notes="Mirror east to west; the attack screen only ever shows two facings.",
)

TIERS: dict[str, Tier] = {tier.key: tier for tier in (MAP, BATTLE)}

#: Applied to every sprite in the game, both tiers. The house style.
HOUSE_TOKENS: tuple[str, ...] = (
    "pixel art",
    "saturated storybook fantasy palette",
    "clean hard pixel edges",
)

#: Never wanted, either tier. Short on purpose: the same lesson the 3D prompt
#: grammar learned the expensive way is that space spent saying what we want
#: beats space spent saying what we don't.
AVOID_TOKENS: tuple[str, ...] = (
    "blurry",
    "anti-aliased",
    "photographic",
    "3d render",
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

    parts = [subject, *tier.direction_tokens, *HOUSE_TOKENS]
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

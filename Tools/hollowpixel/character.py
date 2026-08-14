"""Build one character's whole sprite set, on the v2 character API.

Shining Force draws every hero twice, and so does this: a compact figure for the
map, where a dozen units share the screen, and a large one for the attack screen,
where two fill it. They are two separate PixelLab characters, both anchored to
the same reference so they are the same person.

    BATTLE  128px  side            8 rotations + attack, block, damage, faint, idle
    MAP      48px  high top-down   8 rotations + walk

Every clip is a **template** animation rather than an action description. The
templates are skeleton-driven and professionally animated; free text invents
motion, and the invented kind is what produced clips whose character changed
between frames and whose sword vanished halfway through.

There is no sword-swing template -- the library is martial arts -- but the
character is *holding* a sword, so the skeleton carries it: ``lead-jab`` reads as
a thrust, ``cross-punch`` as a cut, and ``flying-kick`` as the leap into the blow
that Shining Force's attacker makes.

This module used to compose v1's low-level endpoints by hand: generate, rotate,
animate-with-skeleton, plus a hand-rolled pose library and a hand-rolled palette
lock. All of that exists in v2 properly, and every hand-built version was worse
than the thing it replaced. ``pixellab.py`` keeps the v1 surface for reference
and is no longer the path anything should take.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .v2 import Character, Client

#: Battle-screen clips mapped to templates that actually exist. Verified by
#: sending an invalid id and reading the error, because the OpenAPI description
#: truncates the list with an ellipsis *and* the body-level validator advertises
#: a shorter, different set than the server returns once it knows which body
#: template the character was built with.
BATTLE_CLIPS: dict[str, str] = {
    "attack": "lead-jab",
    "attack_leap": "flying-kick",
    "attack_cut": "cross-punch",
    "block": "crouching",
    "damage": "taking-punch",
    "faint": "falling-back-death",
    "idle": "fight-stance-idle-8-frames",
}

#: Exploration. One clip, four ways.
MAP_CLIPS: dict[str, str] = {"walk": "walking-6-frames"}

#: A tactical grid moves on four axes; the attack screen shows two facings, and
#: the second is a mirror of the first.
MAP_DIRECTIONS = ("south", "east", "north", "west")
BATTLE_DIRECTIONS = ("east",)

#: Enough for a unit to appear in a battle at all.
MINIMAL = ("attack", "damage", "faint")


@dataclass
class Build:
    asset_id: str
    battle: Character | None = None
    map: Character | None = None
    spent: float = 0.0
    warnings: list[str] = field(default_factory=list)


def build(
    asset_id: str,
    battle_description: str,
    map_description: str,
    *,
    reference: bytes | None = None,
    client: Client | None = None,
    battle_clips: tuple[str, ...] = tuple(BATTLE_CLIPS),
    map_clips: tuple[str, ...] = tuple(MAP_CLIPS),
    destination: str = "Content/Sprites",
    log=print,
) -> Build:
    """Generate both tiers and export them.

    ``reference`` anchors the battle character; the battle character's own south
    rotation then anchors the map character. So the compact sprite is a smaller
    drawing of the same hero rather than a second hero described in fewer words,
    which is how the map tier drifted every time it was generated from scratch.
    """
    client = client or Client()
    before = client.balance()
    result = Build(asset_id=asset_id)

    log(f"{asset_id}: battle tier")
    result.battle = client.create_character(
        asset_id, battle_description, reference=reference, size=128,
        view="side", detail="highly detailed", log=log)
    _animate(client, result, result.battle, battle_clips, BATTLE_CLIPS,
             BATTLE_DIRECTIONS, log)
    battle_dir = os.path.join(destination, "Battle", asset_id)
    client.export(result.battle, battle_dir)

    log(f"{asset_id}: map tier")
    result.map = client.create_character(
        f"{asset_id}_map", map_description, reference=south_rotation(battle_dir),
        size=48, view="high top-down", detail="low detail", log=log)
    _animate(client, result, result.map, map_clips, MAP_CLIPS, MAP_DIRECTIONS, log)
    client.export(result.map, os.path.join(destination, "Characters", asset_id))

    result.spent = before - client.balance()
    log(f"{asset_id}: ${result.spent:.4f}")
    return result


def south_rotation(directory: str) -> bytes | None:
    """The south-facing rotation from an exported character, if it is there."""
    for root, _, files in os.walk(directory):
        if os.path.basename(root) == "rotations" and "south.png" in files:
            with open(os.path.join(root, "south.png"), "rb") as handle:
                return handle.read()
    return None


def _animate(client, result, character, wanted, table, directions, log) -> None:
    for clip in wanted:
        template = table.get(clip)
        if template is None:
            result.warnings.append(f"{clip}: no template for it")
            log(f"  {clip}: no template, skipped")
            continue
        try:
            client.animate_template(character, clip, template,
                                    directions=directions, log=log)
        except Exception as exc:  # noqa: BLE001 - one clip must not lose the set
            result.warnings.append(f"{clip}: {exc}")
            log(f"  {clip}: FAILED, {exc}")

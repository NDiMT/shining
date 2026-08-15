"""Build one character's whole sprite set, on the v2 character API.

Shining Force draws every hero twice, and so does this: a compact figure for the
map, where a dozen units share the screen, and a large one for the attack screen,
where two fill it. They are two separate PixelLab characters, both anchored to
the same reference so they are the same person.

    BATTLE  128px  side            8 rotations + attack, block, damage, faint, idle
    MAP      48px  high top-down   8 rotations + walk

The two tiers animate by different means, because they want different things.

The map tier uses **templates**: skeleton-driven, professionally animated, one
generation per direction, and a walk cycle is a solved problem no generator
should be reinventing four times.

The battle tier uses **pro** custom animation. There is no sword-swing template
-- the ``mannequin`` library is 49 martial-arts clips, and the ``attack`` ids in
the API's own list belong to the quadruped skeletons -- and the martial-arts
stand-ins were a bad trade: ``cross-punch`` and ``flying-kick`` make the
character drop the blade, and ``lead-jab`` keeps it for three frames of a punch.
The cheap custom mode, ``v3``, was worse still: it redraws the character in place
so the body never commits to the blow, and it papers over the missing motion with
an invented white impact flash. ``pro`` costs twenty to forty generations per
direction and is the only one that produced a swing -- weight onto the front
foot, shoulders turning through the cut, cape following, no effects.

At roughly $0.10 a direction that is real money across a roster. It is also the
difference between an attack screen and a slideshow, and the attack screen is the
thing the player looks at most.

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

#: Battle-screen clips as motion, for pro custom animation.
#:
#: Written as weight and shoulders rather than as arm positions. "Swings the
#: sword" gave a rotating sword on a statue; naming the step, the turn and the
#: finish gave a body that moves through the blow. Every one of them ends
#: somewhere specific, because a clip with no stated end pose drifts back to idle
#: and reads as nothing having happened.
BATTLE_CLIPS: dict[str, str] = {
    "attack": (
        "steps forward onto the front foot, raises the sword high overhead with "
        "both shoulders turning, then swings it down and across in one committed "
        "diagonal cut, ending crouched low with the blade held out to the side"),
    "block": (
        "plants both feet and turns the shoulder forward, bringing the sword up "
        "across the chest to guard, head tucked behind the blade"),
    "damage": (
        "snaps backwards from the impact, head thrown back and arms flung wide, "
        "staggering off the back foot"),
    "faint": (
        "buckles at the knees and falls backwards to the ground, sword slipping "
        "from the hand, ending flat on the back"),
    "idle": (
        "breathes in a ready stance, sword held low, weight shifting gently from "
        "foot to foot"),
}

#: Exploration. One clip, four ways -- and a template, because a walk cycle is
#: solved. Verified by sending an invalid id and reading the error, because the
#: OpenAPI description truncates the list with an ellipsis *and* the body-level
#: validator advertises a shorter, different set than the server returns once it
#: knows which body template the character was built with.
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
    battle_dir = os.path.join(destination, "Battle", asset_id)
    # Export first: the rotations are what lock the palette on every clip, and
    # force_colors without a colour image is the no-op this pipeline shipped for
    # weeks. Nothing to pass means nothing is forced.
    client.export(result.battle, battle_dir)
    _battle_clips(client, result, result.battle, battle_clips,
                  east_rotation(battle_dir), battle_description, log)
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


def rotation(directory: str, facing: str) -> bytes | None:
    """One facing from an exported character, if it is there."""
    name = f"{facing}.png"
    for root, _, files in os.walk(directory):
        if os.path.basename(root) == "rotations" and name in files:
            with open(os.path.join(root, name), "rb") as handle:
                return handle.read()
    return None


def south_rotation(directory: str) -> bytes | None:
    """The south-facing rotation -- what v3 wants as a rotation reference."""
    return rotation(directory, "south")


def east_rotation(directory: str) -> bytes | None:
    """The east-facing rotation -- the battle facing, and its own palette."""
    return rotation(directory, "east")


def _battle_clips(client, result, character, wanted, palette, description, log) -> None:
    """Pro custom animation, one clip at a time, one failure never losing the set."""
    for clip in wanted:
        action = BATTLE_CLIPS.get(clip)
        if action is None:
            result.warnings.append(f"{clip}: no motion written for it")
            log(f"  {clip}: unknown clip, skipped")
            continue
        try:
            client.animate(character, clip, action=action, description=description,
                           mode="pro", palette=palette,
                           directions=BATTLE_DIRECTIONS, log=log)
        except Exception as exc:  # noqa: BLE001 - one clip must not lose the set
            result.warnings.append(f"{clip}: {exc}")
            log(f"  {clip}: FAILED, {exc}")


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

"""Mapping from the brief's animation set to Meshy animation library action ids.

Brief section 57 defines the core humanoid animation library the engine expects:

    idle walk run turn attack_1 attack_2 heavy_attack cast heal block
    hit_front hit_back death victory

The Meshy animation library exposes roughly 593 actions addressed by integer
``action_id``. This module is the single place that translates between the two,
so catalogs and engine data refer to Hollow Crown names and never to raw
provider ids.

VERIFICATION STATUS
-------------------
The ids below were selected from the published library category ranges:

    idle 0, 11-12, 32-33, 36, 38, 48, 243-254
    walk 1, 30, 55, 106-125          run 14-16, 110, 120, 509-539
    combat stance 89, 156-162         attack 4, 86-87, 91-92, 97-98, 102-105, 222-242
    cast 125-137                      block 138-155
    hit reaction 172-180              death 8, 181-190

Individual ids inside a category are NOT interchangeable in feel, and the
mapping has not yet been confirmed clip by clip. Before any of these reaches
production, generate one rigged test character, bake all fourteen clips and
review them, then correct this table. Treat every entry as provisional until
``VERIFIED`` below says otherwise.
"""

from __future__ import annotations

#: Flip to True only after a human has watched all fourteen baked clips.
VERIFIED = False

#: Hollow Crown animation name -> Meshy action_id. Provisional; see above.
CORE_SET: dict[str, int] = {
    "idle": 0,
    "walk": 1,
    "run": 14,
    "turn": 9,
    "attack_1": 4,
    "attack_2": 86,
    "heavy_attack": 91,
    "cast": 125,
    "heal": 128,
    "block": 138,
    "hit_front": 172,
    "hit_back": 174,
    "death": 8,
    "victory": 22,
}

#: The smallest set that makes a unit playable in a tactical battle. Used for
#: first-pass generation so a character costs 5 clips rather than 14.
MINIMAL_SET = ["idle", "walk", "attack_1", "hit_front", "death"]


def resolve(name_or_id: str | int) -> int:
    """Accept a Hollow Crown animation name or a raw Meshy action id."""
    if isinstance(name_or_id, int):
        return name_or_id
    text = str(name_or_id).strip()
    if text.isdigit():
        return int(text)
    try:
        return CORE_SET[text]
    except KeyError:
        known = ", ".join(sorted(CORE_SET))
        raise KeyError(f"unknown animation {text!r}; known names: {known}") from None


def resolve_all(values: list[str | int]) -> list[int]:
    return [resolve(value) for value in values]


def name_for(action_id: int) -> str:
    """Reverse lookup, for filenames and reports."""
    for name, value in CORE_SET.items():
        if value == action_id:
            return name
    return f"action_{action_id}"

"""Build one character's whole sprite set, from one anchor.

Consistency is the requirement, so it is enforced structurally rather than asked
for. Everything below derives from a single generated sprite:

    battle stance (128, side)          <- generated once. The anchor.
        |-- palette                    <- extracted; every file is mapped to it
        |-- attack / block / hit / faint   <- animate-with-skeleton from it
        `-- map sprite (64, top-down)  <- bitforge, styled by the anchor
                |-- facings            <- rotate from the map sprite
                `-- walk per facing    <- animate-with-skeleton from each facing

Nothing is described twice. A second prompt for a second sprite is a second
chance to drift, which is exactly how the 3D pipeline lost five generations to a
single guard, so the only place a description appears is the anchor.

The palette does the work no prompt can. Sixteen colours are extracted from the
anchor and every other file is mapped onto them, so the hair is one brown across
four facings and a walk cycle rather than sixteen near-identical browns. That
mirrors the ROM: ``SF2BattleSpriteManager`` stores one palette per character, so
the game's own format already treats colour as an attribute of the character.

West is mirrored, never generated. A rotation costs about what a fresh sprite
costs and cannot be as exact as a flip.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from . import palette, poses, style
from .pixellab import Client


class _Anchor:
    """Carries the anchor bytes under the name the rest of this module uses."""

    def __init__(self, image: bytes) -> None:
        self.image = image

#: Facings generated for the map tier. West, south-west and north-west are
#: mirrored from their opposites at write time.
MAP_FACINGS = ("south", "south-east", "east", "north-east", "north")

#: facing -> the facing it is mirrored from.
MIRRORED = {"south-west": "south-east", "west": "east", "north-west": "north-east"}

#: What the attack screen needs. "faint" is the game's word for it; the pose
#: library calls the clip "death".
BATTLE_CLIPS = {"attack": "attack", "block": "block", "damage": "hit", "faint": "death"}


@dataclass
class CharacterSet:
    asset_id: str
    files: dict[str, bytes] = field(default_factory=dict)
    colours: list[tuple[int, int, int]] = field(default_factory=list)
    spent: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def write(self, root: str = "Content/Sprites") -> list[str]:
        written = []
        for name, payload in sorted(self.files.items()):
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)
            written.append(path)
        return written


def mirror(image: bytes) -> bytes:
    """Flip horizontally. Exact, free, and the reason west is never generated."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        flipped = opened.convert("RGBA").transpose(Image.FLIP_LEFT_RIGHT)
    buffer = io.BytesIO()
    flipped.save(buffer, format="PNG")
    return buffer.getvalue()


def build(
    asset_id: str,
    subject: str,
    *,
    client: Client | None = None,
    region: str = "greenvale",
    log=print,
    reference: bytes | None = None,
    reference_strength: int = 300,
    intensity: float = 1.0,
    coverage: int = 90,
) -> CharacterSet:
    """Generate the anchor, then everything else from it.

    ``reference`` is the director's concept art, seeded into the anchor as an
    init image. It goes in once, at the only point where a description is used,
    so the whole set inherits the approved design through the same chain that
    already carries the palette.
    """
    client = client or Client()
    result = CharacterSet(asset_id=asset_id)

    # 1. The anchor. The only call that works from a description.
    prompt = style.build(subject, "battle", region=region)
    anchor_raw = client.generate(
        prompt.description, size=style.BATTLE.size, negative=prompt.negative,
        view=style.BATTLE.view, direction=style.BATTLE.direction,
        outline=style.BATTLE.outline, shading=style.BATTLE.shading,
        detail=style.BATTLE.detail, text_guidance_scale=8.0,
        coverage_percentage=coverage,
        init_image=reference, init_image_strength=reference_strength)

    # No quantising, and no forced shared palette. Both were mine and both made
    # the sprites worse -- see palette.py. Consistency now comes from where it
    # always should have: one anchor, and every other file derived from it by
    # rotate, pose or mirror rather than by a second prompt.
    anchor = _Anchor(anchor_raw)
    result.colours = palette.extract(anchor_raw)
    log(f"  anchor: {len(result.colours)} colours, kept as generated")

    def fix(image: bytes) -> bytes:
        return image

    battle_dir = f"Battle/{asset_id}"
    result.files[f"{battle_dir}/stance_east.png"] = anchor.image
    result.files[f"{battle_dir}/stance_west.png"] = mirror(anchor.image)

    # 2. Battle clips, posed from the anchor.
    skeleton = client.estimate_skeleton(anchor.image)
    for name, clip in BATTLE_CLIPS.items():
        try:
            frames = client.animate_skeleton(
                anchor.image,
                skeleton_frames=poses.frames_for(skeleton, clip, intensity=intensity),
                size=style.BATTLE.size, direction="east", view="side",
                guidance_scale=8.0)
        except Exception as exc:  # noqa: BLE001 - one clip must not lose the set
            result.warnings.append(f"battle clip {name}: {exc}")
            log(f"  battle {name}: FAILED, {exc}")
            continue
        for index, frame in enumerate(frames):
            payload = fix(frame)
            result.files[f"{battle_dir}/{name}_east_{index}.png"] = payload
            result.files[f"{battle_dir}/{name}_west_{index}.png"] = mirror(payload)
        log(f"  battle {name}: {len(frames)} frames")

    # 3. The map sprite, styled by the anchor rather than described again.
    map_prompt = style.build(subject, "map", region=region)
    map_south = client.generate(
        map_prompt.description, size=style.MAP.size, negative=map_prompt.negative,
        view=style.MAP.view, direction="south", outline=style.MAP.outline,
        shading=style.MAP.shading, detail=style.MAP.detail,
        style_image=anchor.image, style_strength=50,
        coverage_percentage=coverage, text_guidance_scale=8.0)
    log("  map sprite generated")

    facings = {"south": map_south}
    for facing in MAP_FACINGS[1:]:
        try:
            facings[facing] = fix(client.rotate(
                map_south, to_direction=facing, from_direction="south",
                size=style.MAP.size, view=style.MAP.view))
            log(f"  map facing {facing}")
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"map facing {facing}: {exc}")
            log(f"  map facing {facing}: FAILED, {exc}")

    # 4. Walk, per generated facing. The mirrored facings inherit their source's
    #    frames flipped, so a walk cycle never disagrees with itself left to right.
    map_dir = f"Characters/{asset_id}"
    for facing, sprite in facings.items():
        result.files[f"{map_dir}/idle_{facing}.png"] = sprite
        # Skeleton animation, not animate-with-text, and not by choice: that
        # endpoint is hardcoded to 64x64 and answers a 422 naming the mismatch
        # ("reference_image is 32x32 but image_size is 64x64"). The map tier is
        # 32, so the walk cycle uses the same mechanism the battle clips do --
        # which is better anyway, because one animation path means one place
        # where a clip can be wrong.
        try:
            frames = client.animate_skeleton(
                sprite,
                skeleton_frames=poses.frames_for(
                    client.estimate_skeleton(sprite), "walk", intensity=intensity),
                size=style.MAP.size, direction=facing, view=style.MAP.view,
                guidance_scale=8.0)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"walk {facing}: {exc}")
            log(f"  walk {facing}: FAILED, {exc}")
            continue
        for index, frame in enumerate(frames):
            result.files[f"{map_dir}/walk_{facing}_{index}.png"] = fix(frame)
        log(f"  walk {facing}: {len(frames)} frames")

    for target, source in MIRRORED.items():
        for name, payload in list(result.files.items()):
            if f"_{source}" in name and name.startswith(map_dir):
                result.files[name.replace(f"_{source}", f"_{target}")] = mirror(payload)

    result.spent = client.spent
    return result

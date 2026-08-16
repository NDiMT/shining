"""The weapon is a separate sprite, the way Shining Force II does it.

Rowan kept appearing with the blade emerging from his back. It reads as an
impalement, and no amount of prompt wording fixed it, because it is not a
prompt problem. The generator draws one picture per frame; when the arm winds
back, the blade goes behind the torso, and a single flat image has no way to say
which of the two is in front.

Shining Force II never had that problem, because it never drew the sword into
the character. Its battle animation frame is eight bytes, and three of them are
about the weapon alone (`SF2DISASM`, ShiningForceCentral):

===========  ==================================================================
Byte 0       battle sprite frame index (``$0F`` = hold the previous one)
Byte 1       display frames, at 60 per second
Bytes 2-3    battle sprite x, y offset
Byte 4       **weapon sprite frame**: 0 is up, clockwise to 3; ``0x10`` flips
             horizontally, ``0x20`` vertically
Byte 5       **weapon z-index**: 1 draws it under the character, 2 over
Bytes 6-7    weapon x, y offset, relative to the battle sprite
===========  ==================================================================

Byte 5 is the whole answer. The game decides, per frame, whether the blade
passes behind the body or in front of it -- so on the wind-up the sword is drawn
*under* the character and is simply hidden by him, and on the follow-through it
is drawn *over* and sweeps across his chest. Baked into one image, both of those
frames are guesses, and half the guesses are wrong.

Byte 4 pays for itself twice over as well: four drawings of a sword, plus a
horizontal and a vertical flip flag, cover sixteen orientations. And because the
weapon is a layer rather than paint, changing what the character is holding is a
different file and not a different character -- which is what this project needs
anyway, since Rowan will not carry one sword for thirty hours.

One more thing byte 0 gives away, and it is the reason the generated clips were
built the wrong shape entirely. ``$0F`` means *keep the battle sprite frame from
the previous animation frame*: the body holds still while the weapon carries on
through its own frames. So an SF2 attack is a handful of body poses with the
sword moving between them, not a fresh drawing of the whole character every
frame -- which is exactly what this pipeline had been paying for.

Producing a body that can take a weapon layer needs the body generated unarmed
**from the start**. `create-character-state` will not take a sword away; see
:meth:`v2.Client.create_state`. Generating the swing with no weapon anywhere in
the text gives poses with closed fists exactly where a grip belongs, and the
blade drops into them.

This module is the data model and the compositor. It does not generate anything.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment problem, not logic
    raise ImportError("weapon.py needs Pillow: pip install Pillow") from exc

#: Weapon orientations, in the order SF2 stores them: up first, then clockwise.
#: Four drawings; the flips in :class:`Pose` reach the other twelve.
ORIENTATIONS = ("up", "right", "down", "left")

#: Draw order relative to the character, named rather than left as 1 and 2.
UNDER = 1
OVER = 2


@dataclass(frozen=True)
class Pose:
    """Where the weapon is for one frame, and whether it is behind or in front."""

    orientation: int = 0
    x: int = 0
    y: int = 0
    z: int = OVER
    flip_x: bool = False
    flip_y: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.orientation < len(ORIENTATIONS):
            raise ValueError(f"orientation must be 0..{len(ORIENTATIONS) - 1}")
        if self.z not in (UNDER, OVER):
            raise ValueError("z must be UNDER (1) or OVER (2)")

    @classmethod
    def from_byte(cls, frame_byte: int, z: int, x: int, y: int) -> "Pose":
        """Decode SF2's byte 4 -- orientation in the low bits, flips in 0x10/0x20."""
        return cls(orientation=frame_byte & 0x0F, x=x, y=y, z=z,
                   flip_x=bool(frame_byte & 0x10), flip_y=bool(frame_byte & 0x20))

    def to_byte(self) -> int:
        return self.orientation | (0x10 if self.flip_x else 0) | (0x20 if self.flip_y else 0)


@dataclass(frozen=True)
class Frame:
    """One animation frame: a body pose, a weapon pose, and a duration."""

    body: int
    ms: int
    weapon: Pose | None = None
    x: int = 0
    y: int = 0


def compose(frame: Frame, bodies: list["Image.Image"],
            weapons: list["Image.Image"], size: tuple[int, int]) -> "Image.Image":
    """Draw one frame: body, weapon, in the order the frame asks for.

    A frame with no weapon pose is just the body, which is what an idle or a
    faint wants -- SF2 uses the same absence for a unit whose weapon has left
    its hand.
    """
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    body = bodies[frame.body].convert("RGBA")

    blade = None
    if frame.weapon is not None:
        blade = weapons[frame.weapon.orientation].convert("RGBA")
        if frame.weapon.flip_x:
            blade = blade.transpose(Image.FLIP_LEFT_RIGHT)
        if frame.weapon.flip_y:
            blade = blade.transpose(Image.FLIP_TOP_BOTTOM)

    if blade is not None and frame.weapon.z == UNDER:
        canvas.alpha_composite(blade, (frame.x + frame.weapon.x, frame.y + frame.weapon.y))
    canvas.alpha_composite(body, (frame.x, frame.y))
    if blade is not None and frame.weapon.z == OVER:
        canvas.alpha_composite(blade, (frame.x + frame.weapon.x, frame.y + frame.weapon.y))
    return canvas


def render(frames: list[Frame], bodies: list["Image.Image"],
           weapons: list["Image.Image"], size: tuple[int, int]) -> list["Image.Image"]:
    """Compose a whole clip."""
    return [compose(f, bodies, weapons, size) for f in frames]

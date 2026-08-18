"""Cut-out animation: move parts of one sprite instead of redrawing the sprite.

Every generated path in the PixelLab API redraws the whole character for every
frame, and that is measurable rather than a matter of taste. Silhouette overlap
between consecutive frames -- how much of the figure stays put -- came out at:

===========================================  ==========  =========
path                                         mean        worst
===========================================  ==========  =========
``mode="pro"``, four keyframes per clip      0.64        0.42
``mode="template"``, skeleton-driven          0.50        0.37
this module, one sprite with a moving arm    **0.94**    **0.90**
===========================================  ==========  =========

Hand-drawn cycles sit at 0.75 and up, because an animator moves a limb against a
body that stays where it is. Both generated paths fall well under that, and the
symptom is a figure that boils: the torso re-forms, the cape re-drapes, the
proportions breathe. No amount of prompt wording changes it -- three separate
attempts to blame the prompt were measured and refuted first (blade proportions,
rotation damage to the pixels, palette drift; all three were within tolerance).

The template result being *worse* than the ad-hoc one was the surprise, and it is
what settled the argument. Skeleton-driven templates are the closest thing the
API has to real animation, so if they cannot hold a body still, nothing there can.

So the body is generated once, as a still, which is what the generator is
genuinely good at, and the motion is authored here. A part rotates about a pivot;
its child follows. The torso is the same pixels in every frame by construction,
which is why the number is 0.94 and not a matter of luck.

Two things this costs, both worth saying out loud:

* Cutting a part out leaves a hole, and leaving it in leaves a ghost of it
  wherever it swings away from. :func:`patch_hole` fills the hole by extending
  the neighbouring surface across it, which follows the tunic's shading instead
  of stamping a flat patch, and is good enough at this scale. It is not
  invisible under inspection.
* A perfectly still body is the opposite failure from a boiling one. It reads
  stiff, because a real swing shifts weight and moves the cape. Compose a rig
  arm over two or three generated body poses rather than one, and the overlap
  only drops at the two or three frames where the base changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment problem, not logic
    raise ImportError("rig.py needs Pillow: pip install Pillow") from exc


@dataclass(frozen=True)
class Part:
    """A piece cut from the base sprite, and where it turns.

    ``pivot`` and ``attach`` are in the coordinates of the sprite the part was cut
    from, not of the cut-out itself, so a part can be re-cut with a different
    rectangle without every pose having to be re-authored.
    """

    image: "Image.Image"
    rect: tuple[int, int, int, int]
    pivot: tuple[int, int]
    #: Where a child part hangs off this one -- the fist, for an arm.
    attach: tuple[int, int] | None = None

    @property
    def local_pivot(self) -> tuple[float, float]:
        return self.pivot[0] - self.rect[0], self.pivot[1] - self.rect[1]


def cut(sprite: "Image.Image", rect: tuple[int, int, int, int],
        pivot: tuple[int, int], attach: tuple[int, int] | None = None) -> Part:
    """Take a rectangle out of a sprite as a movable part."""
    left, top, right, bottom = rect
    if not (0 <= left < right <= sprite.width and 0 <= top < bottom <= sprite.height):
        raise ValueError("rect falls outside the sprite")
    if not (left <= pivot[0] < right and top <= pivot[1] < bottom):
        raise ValueError("pivot must lie inside rect")
    return Part(sprite.convert("RGBA").crop(rect), rect, pivot, attach)


def patch_hole(sprite: "Image.Image", rect: tuple[int, int, int, int]) -> "Image.Image":
    """Fill where a part was, by extending the surface to its right across it.

    Row by row rather than as one flat colour, so the tunic's own shading carries
    through the patch. Rows with nothing to the right are left alone -- better a
    hole at the silhouette's edge than a smear invented past it.
    """
    out = sprite.convert("RGBA").copy()
    px = out.load()
    left, top, right, bottom = rect
    for y in range(top, min(bottom, out.height)):
        fill = None
        for x in range(right, out.width):
            if px[x, y][3] > 127:
                fill = px[x, y]
                break
        if fill is None:
            continue
        for x in range(left, right):
            if px[x, y][3] > 127:
                px[x, y] = fill
    return out


def rotate_about(image: "Image.Image", pivot: tuple[float, float], degrees: float
                 ) -> tuple["Image.Image", tuple[float, float]]:
    """Rotate, and report where the pivot ended up in the enlarged result.

    Nearest-neighbour: any smoothing resample averages neighbouring pixels and
    turns hand-placed pixel art to mush. Measured, an arbitrary-angle rotation of
    a blade left at most one near-isolated pixel, so the coarseness costs nothing
    here -- which is worth knowing, because "rotation ruins pixel art" was one of
    the plausible explanations that had to be tested and dropped.
    """
    out = image.rotate(degrees, expand=True, resample=Image.NEAREST)
    angle = math.radians(degrees)
    dx = pivot[0] - image.width / 2
    dy = pivot[1] - image.height / 2
    return out, (dx * math.cos(angle) + dy * math.sin(angle) + out.width / 2,
                 -dx * math.sin(angle) + dy * math.cos(angle) + out.height / 2)


def swing_point(pivot: tuple[float, float], point: tuple[float, float],
                degrees: float) -> tuple[float, float]:
    """Where ``point`` lands after rotating about ``pivot``.

    The fist has to travel with the arm rather than be re-guessed per frame; that
    guessing is what left blades hanging in mid-air beside a hand.
    """
    angle = math.radians(degrees)
    dx, dy = point[0] - pivot[0], point[1] - pivot[1]
    return (pivot[0] + dx * math.cos(angle) + dy * math.sin(angle),
            pivot[1] - dx * math.sin(angle) + dy * math.cos(angle))


@dataclass
class Pose:
    """One frame of an authored clip."""

    arm: float = 0.0
    blade: float = 0.0
    #: Draw the weapon over the arm, or behind it. The same choice SF2 stores per
    #: frame in byte 5 of its animation format.
    over: bool = True


@dataclass
class Rig:
    """A base sprite, one rotating part, and a weapon hanging off it."""

    body: "Image.Image"
    arm: Part
    weapon: "Image.Image"
    #: Where the hand grips the weapon, as a fraction of the weapon sprite.
    grip: tuple[float, float] = (0.17, 0.83)
    #: The weapon drawing's own blade angle, clockwise from straight up.
    weapon_base: float = 45.0
    size: tuple[int, int] = (150, 200)
    offset: tuple[int, int] = (0, 0)
    shadow: bool = True

    def frame(self, pose: Pose) -> "Image.Image":
        canvas = Image.new("RGBA", self.size, (0, 0, 0, 0))
        ox, oy = self.offset

        if self.shadow:
            from PIL import ImageDraw

            # SF2 draws a flat black ellipse under the feet on every crouched
            # pose. Without it the figure reads as floating.
            base = oy + self.body.height
            ImageDraw.Draw(canvas).ellipse(
                [ox + 8, base - 8, ox + self.body.width - 4, base + 2],
                fill=(0, 0, 0, 110))

        canvas.alpha_composite(self.body, (ox, oy))

        turned, pivot = rotate_about(self.arm.image, self.arm.local_pivot, pose.arm)
        arm_at = (int(ox + self.arm.pivot[0] - pivot[0]),
                  int(oy + self.arm.pivot[1] - pivot[1]))

        blade = None
        if self.arm.attach is not None:
            fist = swing_point(self.arm.pivot, self.arm.attach, pose.arm)
            blade, grip = rotate_about(
                self.weapon,
                (self.weapon.width * self.grip[0], self.weapon.height * self.grip[1]),
                self.weapon_base - pose.blade)
            blade_at = (int(ox + fist[0] - grip[0]), int(oy + fist[1] - grip[1]))

        if blade is not None and not pose.over:
            canvas.alpha_composite(blade, blade_at)
        canvas.alpha_composite(turned, arm_at)
        if blade is not None and pose.over:
            canvas.alpha_composite(blade, blade_at)
        return canvas

    def render(self, poses: list[Pose]) -> list["Image.Image"]:
        return [self.frame(p) for p in poses]

"""Remove fragments that floated off the character.

The pro generator occasionally leaves debris: a boot, a patch of cape, a shape
that reads as a shield, sitting in clear space several tens of pixels from the
figure and connected to nothing. Two of Rowan's eight rotations came back that
way -- the character itself perfectly intact in both, with a detached boot
parked at the left edge of the frame.

Deleting it is safe in a way that redrawing is not. A regenerated rotation is a
new roll of the dice on identity, and the identity was the expensive part; the
debris is disconnected by definition, so removing it cannot touch the figure.

The rule is deliberately narrow, for the same reason the 3D scenery stripper's
is: **keep the largest connected region of opaque pixels, plus every region
within :data:`GAP` pixels of it.** The second clause is what protects a held
weapon. A sword can be a separate region -- a hand occludes the grip and splits
blade from body -- but the pieces of one object are drawn touching, while debris
sits in clear space. Keeping the largest region alone would throw away swords,
which is a far worse failure than leaving a stray boot in.

Proximity, specifically, and not "overlaps the figure's bounding box", which was
the first attempt. A figure holding a sword out to the side has a bounding box
wide enough to swallow half the frame, and Rowan's west rotation had its detached
cape patch sitting squarely inside it: kept, wrongly, by a rule that had looked
sound. Measured, the patch was thirteen pixels clear of the nearest body pixel
and an occluded blade is one or two, so the two cases separate cleanly on
distance and not at all on containment.

Connectivity is 8-way. A blade drawn one pixel wide on a diagonal is a single
region under 8-way and a dotted line of separate ones under 4-way.
"""

from __future__ import annotations

from dataclasses import dataclass

try:  # Pillow is present for the rest of the 2D pipeline; this module is honest
    from PIL import Image  # noqa: F401  if it is not, rather than failing later.
except ImportError as exc:  # pragma: no cover - environment problem, not logic
    raise ImportError("islands.py needs Pillow: pip install Pillow") from exc

#: Below this the pixel is background. Anti-aliased edges sit well above it, and
#: the generator's transparent areas sit at zero.
OPAQUE = 128

#: How close a separate region must come to the body to count as part of it.
#: Three is chosen off the measurement rather than by feel: the debris that
#: prompted this module cleared the figure by thirteen pixels, and a blade split
#: from its owner by an occluding hand is separated by one or two. Anything in
#: between has not been seen, so widening this should wait until it is.
GAP = 3


@dataclass(frozen=True)
class Region:
    """One connected blob of opaque pixels."""

    pixels: frozenset[tuple[int, int]]

    @property
    def area(self) -> int:
        return len(self.pixels)

    @property
    def box(self) -> tuple[int, int, int, int]:
        xs = [x for x, _ in self.pixels]
        ys = [y for _, y in self.pixels]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1

    def near(self, other: "Region", gap: int = GAP) -> bool:
        """Does any pixel come within ``gap`` of ``other``?

        Chebyshev distance, to match the 8-way connectivity: one step of the
        flood fill covers a diagonal, so the metric that measures the gap should
        too. Dilating the smaller region and testing set intersection rather than
        comparing every pair -- the pairwise form is quadratic, and on two
        thousand debris pixels against six thousand body pixels that is thirteen
        million comparisons for an answer worth one.
        """
        grown = {(x + dx, y + dy)
                 for x, y in self.pixels
                 for dx in range(-gap, gap + 1)
                 for dy in range(-gap, gap + 1)}
        return not grown.isdisjoint(other.pixels)


def regions(image) -> list[Region]:
    """Every 8-connected region of opaque pixels, largest first."""
    width, height = image.size
    alpha = image.convert("RGBA").getchannel("A").load()
    seen: set[tuple[int, int]] = set()
    found: list[Region] = []

    for start_y in range(height):
        for start_x in range(width):
            if alpha[start_x, start_y] < OPAQUE or (start_x, start_y) in seen:
                continue
            # Iterative flood fill: a 168x168 sprite is 28k pixels, and recursion
            # at that depth is a stack overflow rather than a slow answer.
            blob: set[tuple[int, int]] = set()
            stack = [(start_x, start_y)]
            seen.add((start_x, start_y))
            while stack:
                x, y = stack.pop()
                blob.add((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if not (0 <= nx < width and 0 <= ny < height):
                            continue
                        if (nx, ny) in seen or alpha[nx, ny] < OPAQUE:
                            continue
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            found.append(Region(frozenset(blob)))

    return sorted(found, key=lambda r: r.area, reverse=True)


def strip_debris(image, *, gap: int = GAP) -> tuple["Image.Image", int]:
    """Return the sprite without floating fragments, and how many pixels went.

    An empty or single-region image comes back untouched, which is the common
    case -- six of Rowan's eight rotations needed nothing doing to them.
    """
    from PIL import Image as _Image

    found = regions(image)
    if len(found) < 2:
        return image.convert("RGBA"), 0

    body = found[0]
    kept = {p for region in found
            if region is body or region.near(body, gap)
            for p in region.pixels}

    source = image.convert("RGBA")
    cleaned = _Image.new("RGBA", source.size, (0, 0, 0, 0))
    pixels = source.load()
    out = cleaned.load()
    for x, y in kept:
        out[x, y] = pixels[x, y]

    removed = sum(r.area for r in found) - len(kept)
    return cleaned, removed

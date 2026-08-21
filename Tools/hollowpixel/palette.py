"""Genesis palette discipline: 16 colours, index 0 transparent.

Read off the Shining Force II disassembly tooling rather than remembered, and
this is the constraint that makes a sprite look like the game instead of like
modern pixel art:

* ``SF2MapSpriteManager`` states its import and export format in the editor
  itself -- **"4BPP / 16 indexed colors. Transparent color at index 0."**
* ``SF2BattleSpriteManager`` stores each palette as 32 bytes, which is sixteen
  Genesis CRAM entries of two bytes each. Same 16 colours.

Everything the generator returns is full 24-bit colour with soft ramps, so a
sprite that has not been through here is not Shining Force II-shaped no matter
what the prompt asked for. Asking the model for "16 colours" does not work; the
count is a property of the file, so it is enforced on the file.

**Do not run this on PixelLab output.** That was the plan and it was wrong.
Measured on a four-way comparison of the same subject, the raw sprites were
visibly better than the quantised ones every time: the blue tunic washed out, the
red cape went dull, faces flattened. PixelLab already produces disciplined pixel
art, and its 100-200 colours are its shading ramps rather than photographic
noise. Collapsing them to fifteen does not make the sprite more Genesis, it makes
it muddier.

What this module is still for: a genuine ROM export, where 4BPP is the file
format and not a stylistic choice, and inspecting a sprite's colour count. It is
opt-in, and the pipeline no longer calls it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

#: Genesis colour depth. Each channel is three bits, so every component is one
#: of eight values -- 0, 36, 73, 109, 146, 182, 219, 255 when scaled to 8 bits.
#: A colour off that ladder is a colour the hardware could not display.
GENESIS_LEVELS = tuple(round(i * 255 / 7) for i in range(8))

#: Colours per sprite, index 0 transparent, so fifteen are actually paintable.
PALETTE_SIZE = 16


@dataclass(frozen=True)
class Quantised:
    image: bytes
    colours_before: int
    colours_after: int

    @property
    def reduced(self) -> bool:
        return self.colours_after < self.colours_before


def available() -> bool:
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


def quantise(image: bytes, *, colours: int = PALETTE_SIZE,
             genesis_ladder: bool = True) -> Quantised:
    """Reduce to ``colours`` and, optionally, snap each to the Genesis ladder.

    Transparency is preserved and kept out of the count: a pixel is either fully
    transparent or fully opaque, which is what index 0 means and is also true of
    every sprite the generator returns with ``no_background``.

    No dithering. Dither is how a photograph survives a small palette and it is
    the opposite of what pixel art wants -- it scatters single pixels across
    flat areas, which is precisely the noise that stops a 24x24 sprite reading.
    """
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        source = opened.convert("RGBA")

    alpha = source.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    before = len({p[:3] for p in source.getdata() if p[3] > 127})

    flat = Image.new("RGB", source.size, (0, 0, 0))
    flat.paste(source.convert("RGB"), mask=alpha)

    # One slot is reserved for transparency, matching index 0 in the ROM format.
    reduced = flat.quantize(colors=max(2, colours - 1), method=Image.MEDIANCUT,
                            dither=Image.NONE).convert("RGB")
    if genesis_ladder:
        reduced = _snap(reduced)

    out = reduced.convert("RGBA")
    out.putalpha(alpha)
    after = len({p[:3] for p in out.getdata() if p[3] > 127})

    buffer = io.BytesIO()
    out.save(buffer, format="PNG")
    return Quantised(buffer.getvalue(), before, after)


def count_colours(image: bytes) -> int:
    """Opaque colours in a sprite. What the validator checks."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        rgba = opened.convert("RGBA")
    return len({p[:3] for p in rgba.getdata() if p[3] > 127})


def _snap(image):
    """Round every channel to the nearest Genesis level."""
    table = bytes(min(GENESIS_LEVELS, key=lambda level: abs(level - value))
                  for value in range(256))
    return image.point(table * len(image.getbands()))


def extract(image: bytes) -> list[tuple[int, int, int]]:
    """The opaque colours of a sprite, most used first.

    The anchor of a character's look. In the ROM a character *has* a palette --
    ``SF2BattleSpriteManager`` stores one per sprite as 32 bytes -- so the game's
    own format already treats it as an attribute of the character rather than of
    each drawing. Doing the same is what makes consistency enforceable instead of
    hoped for.
    """
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        rgba = opened.convert("RGBA")
    counts: dict[tuple[int, int, int], int] = {}
    for pixel in rgba.getdata():
        if pixel[3] > 127:
            counts[pixel[:3]] = counts.get(pixel[:3], 0) + 1
    return sorted(counts, key=counts.get, reverse=True)  # type: ignore[arg-type]


def apply_palette(image: bytes, colours: list[tuple[int, int, int]]) -> Quantised:
    """Map every pixel to its nearest colour in ``colours``.

    Quantising each sprite on its own gives each its own sixteen colours, and
    across a walk cycle and four facings that is sixteen slightly different
    browns for the same hair. This forces one palette across every frame and
    every direction of a character, which is the difference between "generated
    from the same description" and actually consistent.

    Nearest in plain RGB. Perceptual distance would be more correct in general
    and is not here: the palette has already been snapped to the Genesis ladder,
    so the candidates are far apart and the two metrics agree.
    """
    from PIL import Image

    if not colours:
        raise ValueError("apply_palette needs at least one colour")

    with Image.open(io.BytesIO(image)) as opened:
        source = opened.convert("RGBA")
    alpha = source.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    before = len({p[:3] for p in source.getdata() if p[3] > 127})

    # Pad the unused entries by repeating the last real colour, not with black.
    # Pillow's quantize can land a pixel on an index past the ones supplied, and
    # padding with black introduced exactly one stray colour -- pure black -- into
    # 24 of 58 files, in a palette that had no pure black in it. Repeating a real
    # colour makes an out-of-range index harmless by construction.
    reference = Image.new("P", (1, 1))
    flat = [component for colour in colours for component in colour]
    reference.putpalette((flat + list(colours[-1]) * 256)[:768])

    flat_rgb = Image.new("RGB", source.size, colours[0])
    flat_rgb.paste(source.convert("RGB"), mask=alpha)
    mapped = flat_rgb.quantize(palette=reference, dither=Image.NONE).convert("RGBA")
    mapped.putalpha(alpha)

    after = len({p[:3] for p in mapped.getdata() if p[3] > 127})
    buffer = io.BytesIO()
    mapped.save(buffer, format="PNG")
    return Quantised(buffer.getvalue(), before, after)


# ---------------------------------------------------------------------------
# Reducing to the reference's palette structure.
#
# This is not the quantiser above, and the difference matters, because that one
# was measured and reverted. That one mapped a soft-shaded painterly sprite onto
# sixteen arbitrary Genesis-legal colours, which washed the tunic out, dulled the
# cape and flattened the face; the raw output beat it four ways on the same
# subject.
#
# What this does instead is close the two specific gaps that prompt wording could
# not, measured against a real Bowie sprite:
#
#   * SF2 has exactly **one** near-black, and it is 37% of the art -- every
#     outline and every interior separation line. Ours arrived with eight of
#     them, a soft dark ramp, which is what makes an outline read as a shadow
#     instead of a line.
#   * SF2 has **13** colours. Ours arrived with 30.
#
# The black collapse works and is worth keeping. **The colour reduction does
# not**, and that is measured rather than suspected: forced to thirteen, a hero
# whose hair is brown and whose cape is crimson came out red-haired, because
# brown and crimson are neighbours in RGB and the merge joined them. Keeping the
# more saturated of each pair -- which is the right rule, and recovered 0.04 of
# mean saturation over keeping the more common one -- makes that particular
# failure worse, since the cape is the saturated one.
#
# So this is the fourth time this project has measured colour reduction on
# generated output and the fourth time it lost. Do not run reduce_to on a
# character sprite. The palette gap has to be closed by the generator producing
# saturated colours in the first place, which prompt wording moved from 0.48 to
# 0.58 against the reference's 0.79.
#
# So the near-blacks collapse to one true black, and the remainder is merged down
# by joining whichever two colours are closest, weighted by how much of the
# sprite each covers. Merging the closest pair is the operation that changes the
# picture least per colour removed, which is the opposite of imposing a fixed
# palette from outside.
# ---------------------------------------------------------------------------

#: Below this lightness a pixel is doing the job SF2 gives its single black.
BLACK_CEILING = 0.14


def _saturation(colour):
    r, g, b = (v / 255 for v in colour[:3])
    hi, lo = max(r, g, b), min(r, g, b)
    if hi == lo:
        return 0.0
    mid = (hi + lo) / 2
    return (hi - lo) / (hi + lo) if mid <= 0.5 else (hi - lo) / (2 - hi - lo)


def _lightness(colour):
    r, g, b = (v / 255 for v in colour[:3])
    return (max(r, g, b) + min(r, g, b)) / 2


def collapse_blacks(image, ceiling: float = BLACK_CEILING):
    """Map every near-black to one pure black, as the reference has.

    Returns the image and how many distinct darks were merged away.
    """
    from PIL import Image as _Image

    source = image.convert("RGBA")
    darks = {p[:3] for p in source.getdata()
             if p[3] > 127 and _lightness(p) < ceiling}
    if len(darks) <= 1:
        return source, 0
    out = source.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a > 127 and (r, g, b) in darks:
                px[x, y] = (0, 0, 0, a)
    return out, len(darks) - 1


def reduce_to(image, colours: int = 13):
    """Merge the closest pair of colours repeatedly until ``colours`` remain.

    Weighted by coverage, so a colour holding two pixels is absorbed into its
    neighbour long before one holding two hundred is touched. Nothing is
    introduced that was not already in the sprite.
    """
    source = image.convert("RGBA")
    counts: dict[tuple[int, int, int], int] = {}
    for p in source.getdata():
        if p[3] > 127:
            counts[p[:3]] = counts.get(p[:3], 0) + 1
    if len(counts) <= colours:
        return source, {}

    mapping = {c: c for c in counts}
    live = dict(counts)
    while len(live) > colours:
        keys = list(live)
        best = None
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                d = sum((a[k] - b[k]) ** 2 for k in range(3))
                if best is None or d < best[0]:
                    best = (d, a, b)
        _, a, b = best
        # Keep the more saturated of the pair, not the more common one. Keeping
        # the common one was the first rule and it cost 0.09 of mean saturation
        # and five of nine saturated colours on the first sprite it ran on --
        # because the frequent colour is usually the large dark fill, and merging
        # a vivid highlight into it is exactly how the old quantiser dulled
        # everything. Ties fall back to coverage.
        sa, sb = _saturation(a), _saturation(b)
        if abs(sa - sb) < 1e-9:
            loser, winner = (a, b) if live[a] <= live[b] else (b, a)
        else:
            loser, winner = (a, b) if sa < sb else (b, a)
        live[winner] += live.pop(loser)
        for src, dst in list(mapping.items()):
            if dst == loser:
                mapping[src] = winner

    out = source.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a > 127:
                nr, ng, nb = mapping[(r, g, b)]
                px[x, y] = (nr, ng, nb, a)
    return out, mapping


def to_reference(image, colours: int = 13, ceiling: float = BLACK_CEILING):
    """Both steps: one black for the lines, then down to ``colours`` total."""
    out, merged = collapse_blacks(image, ceiling)
    out, _ = reduce_to(out, colours)
    return out, merged

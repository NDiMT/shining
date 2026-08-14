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

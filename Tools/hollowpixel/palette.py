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

Quantising is also the cheapest quality lever in the pipeline. It costs nothing,
it is deterministic, and it collapses exactly the thing that reads as wrong:
dozens of near-identical shading steps that a Genesis sprite could never hold.
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

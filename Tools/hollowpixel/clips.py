"""Assemble frames from two generators into one clip, and time it.

Two problems, both of which look like presentation and are not.

**Alignment.** Pro keyframes come back on the canvas that was asked for; the
interpolated inbetweens come back on a larger one, padded by an amount the API
does not report. Stacking them naively makes the character jump a few dozen
pixels sideways at the seam. The padding is recoverable, though: one of the
frames handed to the interpolator is reproduced as its first output, so matching
that frame against the output finds the offset directly instead of guessing it.

**Timing.** Four keyframes played at a constant rate is a slideshow, and so are
ten. A swing reads because the wind-up is held, the cut is not, and the impact is
held again -- the poses carry the drawing and the durations carry the weight.
Storing one duration per frame alongside the frames keeps that decision with the
animation rather than leaving each engine to invent its own.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment problem, not logic
    raise ImportError("clips.py needs Pillow: pip install Pillow") from exc


@dataclass(frozen=True)
class Beat:
    """One played frame: which picture, and for how long."""

    frame: int
    ms: int


#: The shape of a Shining Force swing, as beats rather than as a frame rate.
#:
#: Read left to right: settle in the stance, draw back, then run the cut evenly
#: and fast so the blade sweeps rather than snaps between poses, hold the moment
#: of contact, and ease out through the wind-up pose played backwards. The long
#: tail before the loop is what stops a looping reference GIF from reading as a
#: character swinging frantically forever.
def swing(cut_frames: int, *, ready: int = 0, wind_up: int = 1) -> list[Beat]:
    """Beats for a clip laid out as ready, wind-up, then ``cut_frames`` of arc."""
    first_cut = wind_up + 1
    last_cut = first_cut + cut_frames - 1
    beats = [Beat(ready, 320), Beat(wind_up, 120)]
    # The cut runs evenly and quickly; slowing any part of it reintroduces the
    # stutter the inbetweens were generated to remove.
    beats += [Beat(i, 60) for i in range(first_cut, last_cut)]
    beats += [Beat(last_cut, 280), Beat(last_cut, 120)]        # contact, held
    beats += [Beat(wind_up, 140), Beat(ready, 420)]            # recovery, rest
    return beats


def find_offset(padded: "Image.Image", original: "Image.Image") -> tuple[int, int]:
    """Where ``original`` sits inside ``padded``.

    Compared on the alpha channel only. The interpolator redraws its first output
    rather than copying the input -- shading and a few edge pixels differ -- so
    matching on colour finds nothing, while the silhouette is stable enough to
    locate to the pixel.
    """
    if original.width > padded.width or original.height > padded.height:
        raise ValueError("original does not fit inside padded")

    target = original.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 127 else 0)
    haystack = padded.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 127 else 0)
    want = list(target.getdata())

    best = None
    for oy in range(padded.height - original.height + 1):
        for ox in range(padded.width - original.width + 1):
            crop = haystack.crop((ox, oy, ox + original.width, oy + original.height))
            score = sum(1 for a, b in zip(crop.getdata(), want) if a != b)
            if best is None or score < best[0]:
                best = (score, ox, oy)
    return best[1], best[2]


def footing(image: "Image.Image", rows: int = 6) -> tuple[int, int]:
    """Where the figure meets the ground: (x of the feet, y of the lowest pixel).

    Generated frames are each centred in their own canvas, and the figure is not
    centred the same way twice -- a crouch sits low and narrow, a raised pose
    tall and wide. Composited on canvas centres, the character jumps around
    between frames while the animation plays, which reads as the frames having
    been dropped in at random rather than as motion.

    Shining Force II spends two of its eight animation bytes on exactly this,
    giving every frame an explicit sprite offset. Nothing here reports one, so
    it has to be measured, and the ground contact is the thing to measure: feet
    stay on the floor through a whole swing while heads, capes and blades do not.

    ``rows`` is how much of the bottom counts as feet. Six pixels of a 168-tall
    sprite is about one boot sole -- enough to average both feet when they are
    apart, little enough to ignore the knees.
    """
    alpha = image.convert("RGBA").getchannel("A")
    box = alpha.point(lambda a: 255 if a > 127 else 0).getbbox()
    if box is None:
        return image.width // 2, image.height - 1
    bottom = box[3] - 1
    pixels = alpha.load()
    xs = [x for y in range(max(box[1], bottom - rows + 1), bottom + 1)
          for x in range(box[0], box[2]) if pixels[x, y] > 127]
    return (sum(xs) // len(xs) if xs else (box[0] + box[2]) // 2), bottom


def ground_offsets(frames: list["Image.Image"], anchor: tuple[int, int],
                   rows: int = 6) -> list[tuple[int, int]]:
    """Offsets that put every frame's feet on the same spot."""
    return [(anchor[0] - fx, anchor[1] - fy)
            for fx, fy in (footing(f, rows) for f in frames)]


def align(frames: list["Image.Image"], offsets: list[tuple[int, int]],
          size: tuple[int, int]) -> list["Image.Image"]:
    """Place every frame on one canvas at its own offset."""
    if len(frames) != len(offsets):
        raise ValueError("one offset per frame")
    out = []
    for image, (ox, oy) in zip(frames, offsets):
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.alpha_composite(image.convert("RGBA"), (ox, oy))
        out.append(canvas)
    return out


def write_gif(frames: list["Image.Image"], beats: list[Beat], path: str,
              *, scale: int = 3, background: tuple[int, int, int, int] = (26, 28, 24, 255)) -> int:
    """Write a reference GIF at ``scale``, nearest-neighbour. Returns cycle ms.

    Nearest specifically: any smooth resample averages neighbouring pixels and
    turns hand-placed pixel art into a blur, which is the one thing a reference
    for pixel art must not do.
    """
    scaled = []
    for image in frames:
        big = Image.new("RGBA", (image.width * scale, image.height * scale), background)
        big.alpha_composite(image.convert("RGBA").resize(
            (image.width * scale, image.height * scale), Image.NEAREST))
        scaled.append(big.convert("P", palette=Image.ADAPTIVE, colors=255))

    sequence = [scaled[b.frame] for b in beats]
    durations = [b.ms for b in beats]
    sequence[0].save(path, save_all=True, append_images=sequence[1:],
                     duration=durations, loop=0, disposal=2, optimize=False)
    return sum(durations)

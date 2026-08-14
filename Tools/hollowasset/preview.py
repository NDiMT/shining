"""Render generated assets so a human can look at them.

The single highest-value feedback loop in this pipeline. Every serious problem
found so far was invisible to the numeric checks and obvious on sight:

* A barrel that validated cleanly at 561 triangles was a formless lump — the
  triangle count, scale, textures and materials were all fine.
* What the loose-parts check reported as "debris" turned out, once rendered with
  its texture, to be grass tufts and pebbles the generator had scattered around
  the base — which also inflated the bounding box and shrank the barrel.

Two lenses, because they answer different questions:

* **Flat shading** shows form. Silhouette is what the style guide is about, and
  texture actively hides a bad one.
* **Textured** shows the asset as the player sees it.

Optional dependencies. This module needs Pillow and numpy; the rest of the
package does not, so the validator still runs anywhere with nothing installed.
"""

from __future__ import annotations

import importlib.util
import io
import math
import struct
from dataclasses import dataclass

from . import glb
from .postprocess import _read

#: glTF component types to (struct format, byte size).
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
              5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_ELEMENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

BACKGROUND = (26, 30, 25)
INK = (232, 228, 214)
FAINT = (146, 152, 138)

#: Three-quarter from slightly above: close to the tactical camera, which is the
#: angle that matters for judging readability.
DEFAULT_VIEWS = [(0, 8, "front"), (32, 18, "three-quarter"), (90, 8, "side")]

#: Rule 1 of docs/ANIME_DIRECTION.md: two lighting bands meeting at one hard
#: terminator. Bands are ``(minimum N.L, multiplier)`` in ascending order and the
#: last band a face clears wins, so this table *is* the look — widen the gap
#: between the two multipliers for a harsher terminator, move the threshold to
#: swing the lit/shadow split.
#:
#: 0.28 rather than 0.0 puts the terminator off the geometric horizon: at 0.0 a
#: 12x14 terrain grid came out with every side wall on the light's half in the
#: lit tone, which flattened the whole board back into one value.
TOON_RAMP: tuple[tuple[float, float], ...] = ((-1.0, 0.52), (0.28, 1.0))

#: The one extra band rule 1 allows: ``(maximum |N.V|, multiplier)``. A face
#: within ~17 degrees of perpendicular to the view is on a silhouette, and
#: brightening it is what stops a dark unit dissolving into dark terrain behind
#: it. Anything wider than this stops reading as a rim and starts reading as a
#: third lighting band, which rule 1 bans.
TOON_RIM: tuple[float, float] = (0.30, 1.22)

#: Rule 2: the screen-space edge pass. Near-black rather than black so the line
#: sits in the same family as the darkest shadow band instead of punching a hole.
OUTLINE_COLOUR = (16, 18, 22)

#: A depth step counts as a silhouette above this many world units. The floor
#: matters as much as the pixel term: overlays drawn a centimetre or two clear of
#: the ground (unit markers, range plates) must stay under it, or every one of
#: them gets its own outline and the board reads as tiled stickers.
OUTLINE_DEPTH_FLOOR = 0.06
#: ...and above this many pixels' worth of depth, which is what scales the test
#: with the render size. A ground plane at 40 degrees of pitch already changes
#: depth by about 1.2 pixel-equivalents per pixel, so anything below ~2 here
#: outlines the bare ground.
OUTLINE_DEPTH_PIXELS = 4.0

#: Faces meeting at a sharper angle than this cosine get a crease line. Kept
#: generous (~75 degrees) because rule 2's own warning applies: on a 22k-triangle
#: generated tree every modelled crease becomes a line and the asset turns to
#: scribble.
OUTLINE_NORMAL_COSINE = 0.25


def available() -> bool:
    """Whether rendering is possible in this environment."""
    return (importlib.util.find_spec("PIL.Image") is not None
            and importlib.util.find_spec("numpy") is not None)


class PreviewUnavailable(RuntimeError):
    pass


@dataclass
class Geometry:
    """World-space triangles, their UVs, and the base colour texture.

    One asset needs one texture. A composed scene needs many — terrain painted in
    flat colour, a tree carrying its own atlas, a house carrying another — so the
    optional fields carry a per-triangle material without disturbing the
    single-asset case, which still constructs with three positional arguments.
    """

    triangles: object          # numpy array (n, 3, 3)
    uvs: object                # numpy array (n, 3, 2)
    texture: object | None     # numpy array (h, w, 3) or None
    #: Per-triangle flat RGB, used wherever ``texture_index`` is negative.
    colours: object | None = None
    #: Per-triangle index into ``textures``; -1 means "use ``colours``".
    texture_index: object | None = None
    #: Several base colour textures, for a scene composed of several assets.
    textures: list | None = None
    #: Per-corner vertex normals, (n, 3, 3), or None to shade flat.
    #:
    #: Without these every smooth surface renders faceted, and on a face that
    #: is not a small loss: Rowan's cheeks and chin came back covered in hard
    #: triangular breaks that survived a full retexture unchanged -- which is
    #: what gave it away, because a texture defect cannot survive being
    #: repainted. The GLB had carried NORMAL all along and this module read
    #: POSITION, TEXCOORD_0 and nothing else.
    normals: object | None = None

    def materials(self, numpy, textured: bool):
        """Resolve the texture list, per-triangle index and per-triangle colour."""
        count = len(self.triangles)
        if not textured:
            textures: list = []
            index = numpy.full(count, -1)
        elif self.textures is not None:
            textures = list(self.textures)
            index = (numpy.full(count, -1) if self.texture_index is None
                     else numpy.asarray(self.texture_index))
        elif self.texture is not None:
            textures = [self.texture]
            index = numpy.zeros(count, dtype=int)
        else:
            textures = []
            index = numpy.full(count, -1)

        if self.colours is None:
            colours = numpy.full((count, 3), 196.0)
        else:
            colours = numpy.asarray(self.colours, dtype=float)
        return textures, index, colours


@dataclass
class Camera:
    """Orthographic three-quarter camera, in radians and pixels per world unit.

    Split out of ``render`` because a scene needs to put a name tag over a unit's
    head, and that means projecting a world point with exactly the transform the
    rasteriser used. Two implementations of the same projection drift.

    Positive ``pitch`` looks *down*. That is the opposite of what this module did
    until 2026-08-13: the sign was inverted, so every contact sheet ever produced
    was shot from below. It showed up the moment a house was rendered — the
    generated 7.79 m ground slab was opaque and the roof was never visible.
    """

    yaw: float
    pitch: float
    scale: float
    origin_x: float
    origin_y: float
    width: int
    height: int

    def view(self, points):
        """World coordinates to view coordinates, same shape in and out."""
        numpy, _, _ = _require()
        array = numpy.asarray(points, dtype=float)
        flat = array.reshape(-1, 3)
        cos_yaw, sin_yaw = math.cos(self.yaw), math.sin(self.yaw)
        cos_pitch, sin_pitch = math.cos(self.pitch), math.sin(self.pitch)
        x = flat[:, 0] * cos_yaw + flat[:, 2] * sin_yaw
        z = -flat[:, 0] * sin_yaw + flat[:, 2] * cos_yaw
        return numpy.stack(
            [x,
             flat[:, 1] * cos_pitch + z * sin_pitch,
             -flat[:, 1] * sin_pitch + z * cos_pitch],
            axis=1,
        ).reshape(array.shape)

    def project(self, points):
        """World coordinates to (screen x, screen y, depth). Smaller depth wins."""
        numpy, _, _ = _require()
        array = numpy.asarray(points, dtype=float)
        view = self.view(array).reshape(-1, 3)
        out = numpy.stack([self.origin_x + view[:, 0] * self.scale,
                           self.origin_y - view[:, 1] * self.scale,
                           view[:, 2]], axis=1)
        return out.reshape(array.shape)


def _require():
    if not available():
        raise PreviewUnavailable(
            "preview needs Pillow and numpy: pip install Pillow numpy. "
            "The rest of hollowasset works without them."
        )
    import numpy
    from PIL import Image, ImageDraw
    return numpy, Image, ImageDraw


def _accessor(document, binary, index, numpy):
    accessor = document["accessors"][index]
    fmt, size = _COMPONENT[accessor["componentType"]]
    per = _ELEMENTS[accessor["type"]]
    view = document["bufferViews"][accessor["bufferView"]]
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or size * per
    out = numpy.empty((accessor["count"], per), dtype=numpy.float64)
    for i in range(accessor["count"]):
        out[i] = struct.unpack_from("<" + fmt * per, binary, base + i * stride)
    return out


def read_geometry(path: str) -> Geometry:
    """Gather world-space triangles, UVs and the base texture from a GLB."""
    numpy, Image, _ = _require()
    document, binary = _read(path)
    nodes = document.get("nodes", [])
    scenes = document.get("scenes", [{}])
    triangles: list = []
    uvs: list = []
    normals: list = []
    has_normals = True

    def visit(index: int, parent):
        node = nodes[index]
        world = glb._multiply(parent, glb._node_matrix(node))
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            for primitive in document["meshes"][mesh_index].get("primitives", []):
                attributes = primitive.get("attributes", {})
                if "POSITION" not in attributes:
                    continue
                positions = _accessor(document, binary, attributes["POSITION"], numpy)
                uv = (_accessor(document, binary, attributes["TEXCOORD_0"], numpy)
                      if "TEXCOORD_0" in attributes
                      else numpy.zeros((len(positions), 2)))
                if "NORMAL" in attributes:
                    raw = _accessor(document, binary, attributes["NORMAL"], numpy)
                    # A normal is a direction, so the node's translation must not
                    # apply. Transforming the origin and subtracting removes it and
                    # leaves the rotation and scale; renormalising undoes the scale.
                    zero = numpy.array(glb._transform_point(world, (0.0, 0.0, 0.0)))
                    world_normals = numpy.array(
                        [glb._transform_point(world, tuple(n)) for n in raw]) - zero
                    lengths = numpy.linalg.norm(world_normals, axis=1)
                    safe = lengths > 0
                    world_normals[safe] /= lengths[safe, None]
                else:
                    has_normals = False
                    world_normals = numpy.zeros((len(positions), 3))
                indices = (_accessor(document, binary, primitive["indices"], numpy)
                           .astype(int).ravel()
                           if "indices" in primitive else numpy.arange(len(positions)))
                world_positions = numpy.array(
                    [glb._transform_point(world, tuple(p)) for p in positions])
                for i in range(0, len(indices) - 2, 3):
                    a, b, c = indices[i], indices[i + 1], indices[i + 2]
                    triangles.append((world_positions[a], world_positions[b], world_positions[c]))
                    uvs.append((uv[a], uv[b], uv[c]))
                    normals.append((world_normals[a], world_normals[b], world_normals[c]))
        for child in node.get("children", []):
            visit(int(child), world)

    for root in scenes[document.get("scene", 0)].get("nodes", []):
        visit(int(root), glb._IDENTITY)

    texture = None
    images = document.get("images", [])
    if images and "bufferView" in images[0]:
        view = document["bufferViews"][images[0]["bufferView"]]
        start = view.get("byteOffset", 0)
        payload = binary[start:start + view["byteLength"]]
        texture = numpy.asarray(
            Image.open(io.BytesIO(payload)).convert("RGB"), dtype=numpy.float64)

    return Geometry(numpy.array(triangles), numpy.array(uvs), texture,
                    normals=numpy.array(normals) if has_normals and normals else None)


def _shade(normals, numpy, *, toon: bool):
    """Per-triangle light multiplier, vectorised over every triangle at once.

    Rule 1 of docs/ANIME_DIRECTION.md when ``toon``; the old smooth lambert
    otherwise, kept only so the two can be put side by side.
    """
    light = numpy.array([-0.42, 0.74, -0.52])
    light /= numpy.linalg.norm(light)
    lambert = normals @ light

    if not toon:
        return 0.28 + 0.72 * numpy.maximum(lambert, 0.0)

    shade = numpy.full(len(normals), TOON_RAMP[0][1])
    for threshold, value in TOON_RAMP:
        shade = numpy.where(lambert >= threshold, value, shade)
    # The view axis is +z in view space, so |normal z| is |N.V| directly.
    return numpy.where(numpy.abs(normals[:, 2]) < TOON_RIM[0], TOON_RIM[1], shade)


def _edge_pass(colour, zbuffer, normal_buffer, numpy, *, scale: float, width: int):
    """Rule 2: paint the silhouettes dark, in screen space.

    A depth buffer already knows where every silhouette is, so the honest edge is
    the one the depth buffer reports. Normals catch what depth cannot: a unit
    standing on the tile it is nearly touching has no depth step worth the name,
    but its side wall against the ground is a 90 degree crease.

    Deliberately not an inverted hull or a darkened back face. Those need a second
    pass over the geometry, and there is no reason to fake in a rasteriser what
    the buffers can measure directly.
    """
    filled = numpy.isfinite(zbuffer)
    # Background pixels hold +inf, and inf minus inf is a nan warning rather than
    # a depth step; they are handled by the background test below instead.
    depth = numpy.where(filled, zbuffer, 0.0)
    tolerance = max(OUTLINE_DEPTH_FLOOR, OUTLINE_DEPTH_PIXELS / max(scale, 1e-6))
    edge = numpy.zeros(zbuffer.shape, dtype=bool)

    for axis in (0, 1):
        near: list = [slice(None), slice(None)]
        far: list = [slice(None), slice(None)]
        near[axis] = slice(None, -1)
        far[axis] = slice(1, None)
        here, there = tuple(near), tuple(far)

        both = filled[here] & filled[there]
        step = both & (numpy.abs(depth[here] - depth[there]) > tolerance)
        step |= both & ((normal_buffer[here] * normal_buffer[there]).sum(axis=2)
                        < OUTLINE_NORMAL_COSINE)
        # Silhouette against empty background: ink the geometry side only, so the
        # line stays on the shape instead of haloing it.
        edge[here] |= step | (filled[here] & ~filled[there])
        edge[there] |= step | (filled[there] & ~filled[here])

    for _ in range(max(width - 1, 0)):
        grown = edge.copy()
        grown[:-1] |= edge[1:]
        grown[1:] |= edge[:-1]
        grown[:, :-1] |= edge[:, 1:]
        grown[:, 1:] |= edge[:, :-1]
        edge = grown

    edge &= filled
    colour[edge] = OUTLINE_COLOUR
    return edge


def fit_camera(
    geometry: Geometry,
    size: int,
    yaw_degrees: float,
    pitch_degrees: float,
    *,
    world_scale: float | None = None,
    margin: int = 48,
    height: int | None = None,
) -> Camera:
    """The camera that puts this geometry in this frame."""
    numpy, _, _ = _require()
    frame_height = size if height is None else height
    camera = Camera(math.radians(yaw_degrees), math.radians(pitch_degrees),
                    1.0, 0.0, 0.0, size, frame_height)
    view = camera.view(geometry.triangles)

    if world_scale is None:
        span_x = numpy.ptp(view[:, :, 0]) or 1.0
        span_y = numpy.ptp(view[:, :, 1]) or 1.0
        camera.scale = min((size - margin) / span_x, (frame_height - margin) / span_y)
        camera.origin_y = (frame_height / 2
                           + (view[:, :, 1].min() + view[:, :, 1].max()) / 2 * camera.scale)
    else:
        camera.scale = world_scale
        camera.origin_y = frame_height - margin / 2 - view[:, :, 1].min() * camera.scale

    camera.origin_x = (size / 2
                       - (view[:, :, 0].min() + view[:, :, 0].max()) / 2 * camera.scale)
    return camera


def render(
    geometry: Geometry,
    size: int,
    yaw_degrees: float,
    pitch_degrees: float,
    *,
    textured: bool = True,
    world_scale: float | None = None,
    margin: int = 48,
    height: int | None = None,
    toon: bool = True,
    outline: bool = True,
    camera: Camera | None = None,
    background=None,
):
    """Rasterise one view. Z-buffered, per-pixel UV, single directional light.

    ``world_scale`` is pixels per world unit. Passing the same value to several
    renders is what makes a line-up show real relative sizes; leave it None to fit
    this asset to its own frame.

    ``height`` decouples the frame's height from its width. A shared-scale line-up
    is only as tall as its tallest asset, and square tiles then waste whatever the
    widest asset's width bought.

    ``toon`` and ``outline`` implement rules 1 and 2 of docs/ANIME_DIRECTION.md
    and are on by default: the anime look is the look, not a mode. Turning them
    off is for putting the two side by side.

    ``camera`` overrides the automatic fit, which is how a scene keeps one camera
    across geometry it draws and geometry it labels.
    """
    numpy, Image, _ = _require()
    frame_height = size if height is None else height
    if camera is None:
        camera = fit_camera(geometry, size, yaw_degrees, pitch_degrees,
                            world_scale=world_scale, margin=margin, height=height)

    view = camera.view(geometry.triangles)
    screen = camera.project(geometry.triangles)
    screen_x, screen_y, depth = screen[:, :, 0], screen[:, :, 1], screen[:, :, 2]

    colour = numpy.zeros((frame_height, size, 3), dtype=numpy.float64)
    colour[:] = BACKGROUND if background is None else background
    zbuffer = numpy.full((frame_height, size), numpy.inf)
    normal_buffer = numpy.zeros((frame_height, size, 3))
    textures, texture_index, flat_colours = geometry.materials(numpy, textured)
    uvs = geometry.uvs

    # Normals, culling and shading for every triangle at once. Per triangle
    # inside the loop this cost more than the rasterising did once a composed
    # scene brought 30,000 of them.
    normals = numpy.cross(view[:, 1] - view[:, 0], view[:, 2] - view[:, 0])
    lengths = numpy.linalg.norm(normals, axis=1)
    usable = lengths > 0
    normals[usable] /= lengths[usable, None]
    front = usable & (normals[:, 2] <= 0)       # back faces point along +z
    shades = _shade(normals, numpy, toon=toon)

    # Vertex normals, in view space, for per-pixel shading. Culling still uses
    # the geometric normal above: a vertex normal can point away from the camera
    # on a silhouette triangle and would cull a face that is genuinely visible.
    #
    # The ramp has to be applied *after* interpolation, not blended between three
    # corner shades, or the hard terminator rule 1 asks for turns into a gradient
    # across every triangle it crosses -- which is the smooth shading this whole
    # module exists to avoid.
    vertex_normals = None
    if geometry.normals is not None and len(geometry.normals) == len(view):
        vertex_normals = camera.view(numpy.asarray(geometry.normals, dtype=float))

    low_x = numpy.clip(numpy.floor(screen_x.min(axis=1)), 0, size).astype(int)
    high_x = numpy.clip(numpy.ceil(screen_x.max(axis=1)) + 1, 0, size).astype(int)
    low_y = numpy.clip(numpy.floor(screen_y.min(axis=1)), 0, frame_height).astype(int)
    high_y = numpy.clip(numpy.ceil(screen_y.max(axis=1)) + 1, 0, frame_height).astype(int)
    front &= (high_x > low_x) & (high_y > low_y)

    for t in numpy.flatnonzero(front):
        ax, ay, az = screen_x[t, 0], screen_y[t, 0], depth[t, 0]
        bx, by, bz = screen_x[t, 1], screen_y[t, 1], depth[t, 1]
        cx, cy, cz = screen_x[t, 2], screen_y[t, 2], depth[t, 2]

        determinant = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(determinant) < 1e-12:
            continue

        px = numpy.arange(low_x[t], high_x[t]) + 0.5
        py = (numpy.arange(low_y[t], high_y[t]) + 0.5)[:, None]
        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / determinant
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / determinant
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue

        window = (slice(low_y[t], high_y[t]), slice(low_x[t], high_x[t]))
        z_at = w0 * az + w1 * bz + w2 * cz
        closer = inside & (z_at < zbuffer[window])
        if not closer.any():
            continue

        index = int(texture_index[t])
        if 0 <= index < len(textures) and len(uvs):
            texture = textures[index]
            texture_height, texture_width = texture.shape[:2]
            u = w0 * uvs[t, 0, 0] + w1 * uvs[t, 1, 0] + w2 * uvs[t, 2, 0]
            v = w0 * uvs[t, 0, 1] + w1 * uvs[t, 1, 1] + w2 * uvs[t, 2, 1]
            source = texture[
                numpy.clip((v % 1.0) * (texture_height - 1), 0, texture_height - 1).astype(int),
                numpy.clip((u % 1.0) * (texture_width - 1), 0, texture_width - 1).astype(int)]
        else:
            source = flat_colours[t]

        if vertex_normals is None:
            shade = shades[t]
        else:
            n = (w0[..., None] * vertex_normals[t, 0]
                 + w1[..., None] * vertex_normals[t, 1]
                 + w2[..., None] * vertex_normals[t, 2])
            lengths = numpy.linalg.norm(n, axis=-1)
            n = numpy.divide(n, lengths[..., None], out=n, where=lengths[..., None] > 0)
            shade = _shade(n.reshape(-1, 3), numpy, toon=toon).reshape(w0.shape)[..., None]

        tinted = numpy.clip(source * shade, 0, 255)
        block = colour[window]
        block[closer] = tinted[closer] if tinted.ndim == 3 else tinted
        colour[window] = block
        depths = zbuffer[window]
        depths[closer] = z_at[closer]
        zbuffer[window] = depths
        surface = normal_buffer[window]
        surface[closer] = normals[t]
        normal_buffer[window] = surface

    if outline:
        _edge_pass(colour, zbuffer, normal_buffer, numpy,
                   scale=camera.scale, width=max(1, round(size / 800)))

    return Image.fromarray(colour.astype(numpy.uint8))


def _projected_span(geometry: Geometry, yaw_degrees: float,
                    pitch_degrees: float) -> tuple[float, float]:
    """Width and height of this asset in world units, as seen from that angle."""
    numpy, _, _ = _require()
    camera = Camera(math.radians(yaw_degrees), math.radians(pitch_degrees),
                    1.0, 0.0, 0.0, 1, 1)
    view = camera.view(geometry.triangles).reshape(-1, 3)
    return float(numpy.ptp(view[:, 0])) or 1.0, float(numpy.ptp(view[:, 1])) or 1.0


def _fit_scale(geometry: Geometry, size: int, yaw_degrees: float, pitch_degrees: float,
               *, margin: int) -> float:
    """Pixels per world unit at which this asset exactly fills its tile."""
    span_x, span_y = _projected_span(geometry, yaw_degrees, pitch_degrees)
    return (size - margin) / max(span_x, span_y)


def contact_sheet(path: str, output: str, *, size: int = 420, textured: bool = True) -> str:
    """Several views of one asset, with its measurements underneath."""
    _, Image, ImageDraw = _require()
    geometry = read_geometry(path)
    info = glb.read(path)

    sheet = Image.new("RGB", (size * len(DEFAULT_VIEWS), size + 54), BACKGROUND)
    for index, (yaw, pitch, label) in enumerate(DEFAULT_VIEWS):
        sheet.paste(render(geometry, size, yaw, pitch, textured=textured), (index * size, 0))
        ImageDraw.Draw(sheet).text((index * size + 14, size + 30), label, fill=FAINT)

    width, height, depth = info.size
    ImageDraw.Draw(sheet).text(
        (14, size + 10),
        f"{path.rsplit('/', 1)[-1]}   {info.triangles:,} tris   "
        f"{width:.2f} x {height:.2f} x {depth:.2f} m   texture {info.max_texture_edge}px   "
        f"{len(info.islands)} island(s)",
        fill=INK)
    sheet.save(output)
    return output


def line_up(
    assets: list[tuple[str, str]],
    output: str,
    *,
    size: int = 380,
    yaw: float = 32,
    pitch: float = 16,
    textured: bool = True,
    title: str = "",
) -> str:
    """Several assets side by side at one shared scale, on a common ground line.

    Rendering each asset to fit its own frame is what a catalogue does, and it
    hides the two things most worth checking: whether everything reads as one art
    direction, and whether a house is actually eight times a barrel.
    """
    numpy, Image, ImageDraw = _require()
    geometries = [read_geometry(path) for path, _ in assets]

    # One shared pixels-per-metre, chosen so the widest asset still fits.
    #
    # Scaling by height alone looks right until an asset is wider than it is
    # tall: a 1.24m crate at 0.90m tall overflowed its tile and rendered as a
    # cropped close-up, while claiming to be at the same scale as the barrel
    # beside it. The projected extents have to decide, not one axis.
    margin = 48
    spans = [_projected_span(geometry, yaw, pitch) for geometry in geometries]
    shared_scale = min(
        _fit_scale(geometry, size, yaw, pitch, margin=margin) for geometry in geometries)

    # Tiles are as tall as the tallest asset needs and no taller. Squaring them
    # would let one wide asset -- a house that arrived on a 7.8m ground slab --
    # set the scale for everyone and leave the whole line-up in the bottom
    # eighth of the image, which is how the first one came out.
    tile_height = int(max(span_y for _, span_y in spans) * shared_scale + margin)

    header = 46 if title else 0
    sheet = Image.new("RGB", (size * len(assets), tile_height + 62 + header), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((14, 16), title, fill=INK)

    for index, ((path, label), geometry) in enumerate(zip(assets, geometries)):
        sheet.paste(
            render(geometry, size, yaw, pitch, textured=textured,
                   world_scale=shared_scale, margin=margin, height=tile_height),
            (index * size, header))
        info = glb.read(path)
        ground = header + tile_height - margin // 2
        draw.line([(index * size, ground), ((index + 1) * size, ground)],
                  fill=(58, 64, 54), width=1)
        draw.text((index * size + 14, header + tile_height + 8), label, fill=INK)
        draw.text((index * size + 14, header + tile_height + 26),
                  f"{info.triangles:,} tris   {info.size[1]:.2f} m   "
                  f"{info.max_texture_edge}px",
                  fill=FAINT)

    sheet.save(output)
    return output

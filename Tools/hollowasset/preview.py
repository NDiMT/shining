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


def available() -> bool:
    """Whether rendering is possible in this environment."""
    return (importlib.util.find_spec("PIL.Image") is not None
            and importlib.util.find_spec("numpy") is not None)


class PreviewUnavailable(RuntimeError):
    pass


@dataclass
class Geometry:
    """World-space triangles, their UVs, and the base colour texture."""

    triangles: object          # numpy array (n, 3, 3)
    uvs: object                # numpy array (n, 3, 2)
    texture: object | None     # numpy array (h, w, 3) or None


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
                indices = (_accessor(document, binary, primitive["indices"], numpy)
                           .astype(int).ravel()
                           if "indices" in primitive else numpy.arange(len(positions)))
                world_positions = numpy.array(
                    [glb._transform_point(world, tuple(p)) for p in positions])
                for i in range(0, len(indices) - 2, 3):
                    a, b, c = indices[i], indices[i + 1], indices[i + 2]
                    triangles.append((world_positions[a], world_positions[b], world_positions[c]))
                    uvs.append((uv[a], uv[b], uv[c]))
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

    return Geometry(numpy.array(triangles), numpy.array(uvs), texture)


def render(
    geometry: Geometry,
    size: int,
    yaw_degrees: float,
    pitch_degrees: float,
    *,
    textured: bool = True,
    world_height: float | None = None,
    margin: int = 48,
):
    """Rasterise one view. Z-buffered, per-pixel UV, single directional light.

    ``world_height`` fixes the world-to-pixel scale across several renders so a
    line-up shows real relative sizes. Leave it None to fit each asset to frame.
    """
    numpy, Image, _ = _require()
    yaw, pitch = math.radians(yaw_degrees), math.radians(pitch_degrees)
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)

    points = geometry.triangles.reshape(-1, 3)
    x = points[:, 0] * cos_yaw + points[:, 2] * sin_yaw
    z = -points[:, 0] * sin_yaw + points[:, 2] * cos_yaw
    y2 = points[:, 1] * cos_pitch - z * sin_pitch
    z2 = points[:, 1] * sin_pitch + z * cos_pitch
    view = numpy.stack([x, y2, z2], axis=1).reshape(-1, 3, 3)

    if world_height is None:
        span = max(numpy.ptp(view[:, :, 0]), numpy.ptp(view[:, :, 1])) or 1.0
        scale = (size - margin) / span
        origin_y = size / 2 + (view[:, :, 1].min() + view[:, :, 1].max()) / 2 * scale
    else:
        scale = (size - margin) / world_height
        origin_y = size - margin / 2 - view[:, :, 1].min() * scale

    origin_x = size / 2 - (view[:, :, 0].min() + view[:, :, 0].max()) / 2 * scale
    screen_x = origin_x + view[:, :, 0] * scale
    screen_y = origin_y - view[:, :, 1] * scale
    depth = view[:, :, 2]

    colour = numpy.zeros((size, size, 3), dtype=numpy.float64)
    colour[:] = BACKGROUND
    zbuffer = numpy.full((size, size), numpy.inf)
    light = numpy.array([-0.42, 0.74, -0.52])
    light /= numpy.linalg.norm(light)
    texture = geometry.texture if textured else None

    for t in range(len(view)):
        ax, ay, az = screen_x[t, 0], screen_y[t, 0], depth[t, 0]
        bx, by, bz = screen_x[t, 1], screen_y[t, 1], depth[t, 1]
        cx, cy, cz = screen_x[t, 2], screen_y[t, 2], depth[t, 2]

        normal = numpy.cross(view[t, 1] - view[t, 0], view[t, 2] - view[t, 0])
        length = numpy.linalg.norm(normal)
        if length == 0:
            continue
        normal /= length
        if normal[2] > 0:                        # back face
            continue
        shade = 0.28 + 0.72 * max(0.0, float(normal @ light))

        low_x, high_x = int(max(0, min(ax, bx, cx))), int(min(size - 1, max(ax, bx, cx)) + 1)
        low_y, high_y = int(max(0, min(ay, by, cy))), int(min(size - 1, max(ay, by, cy)) + 1)
        if high_x <= low_x or high_y <= low_y:
            continue

        yy, xx = numpy.mgrid[low_y:high_y, low_x:high_x]
        px, py = xx + 0.5, yy + 0.5
        determinant = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(determinant) < 1e-12:
            continue

        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / determinant
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / determinant
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue

        z_at = w0 * az + w1 * bz + w2 * cz
        closer = inside & (z_at < zbuffer[low_y:high_y, low_x:high_x])
        if not closer.any():
            continue

        if texture is not None and len(geometry.uvs):
            height, width = texture.shape[:2]
            u = w0 * geometry.uvs[t, 0, 0] + w1 * geometry.uvs[t, 1, 0] + w2 * geometry.uvs[t, 2, 0]
            v = w0 * geometry.uvs[t, 0, 1] + w1 * geometry.uvs[t, 1, 1] + w2 * geometry.uvs[t, 2, 1]
            source = texture[
                numpy.clip((v % 1.0) * (height - 1), 0, height - 1).astype(int),
                numpy.clip((u % 1.0) * (width - 1), 0, width - 1).astype(int)]
        else:
            source = numpy.full((*w0.shape, 3), 196.0)

        block = colour[low_y:high_y, low_x:high_x]
        block[closer] = numpy.clip(source[closer] * shade, 0, 255)
        colour[low_y:high_y, low_x:high_x] = block
        depths = zbuffer[low_y:high_y, low_x:high_x]
        depths[closer] = z_at[closer]
        zbuffer[low_y:high_y, low_x:high_x] = depths

    return Image.fromarray(colour.astype(numpy.uint8))


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
    _, Image, ImageDraw = _require()
    geometries = [read_geometry(path) for path, _ in assets]
    tallest = max(glb.read(path).size[1] for path, _ in assets)

    header = 46 if title else 0
    sheet = Image.new("RGB", (size * len(assets), size + 62 + header), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((14, 16), title, fill=INK)

    for index, ((path, label), geometry) in enumerate(zip(assets, geometries)):
        sheet.paste(
            render(geometry, size, yaw, pitch, textured=textured, world_height=tallest),
            (index * size, header))
        info = glb.read(path)
        draw.line([(index * size, header + size - 24), ((index + 1) * size, header + size - 24)],
                  fill=(58, 64, 54), width=1)
        draw.text((index * size + 14, header + size + 8), label, fill=INK)
        draw.text((index * size + 14, header + size + 26),
                  f"{info.triangles:,} tris   {info.size[1]:.2f} m   "
                  f"{info.max_texture_edge}px",
                  fill=FAINT)

    sheet.save(output)
    return output

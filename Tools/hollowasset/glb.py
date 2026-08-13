"""A GLB reader, standard library only.

Everything the asset validator needs to know is in the glTF JSON chunk and the
headers of the embedded images, so there is no reason to pull in a mesh library
to read it. This module does the parsing and reports facts; validate.py applies
judgement to those facts.

Reference: glTF 2.0 specification, section 4.4 (GLB container) and section 5
(accessors, meshes, skins).
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field

_GLB_MAGIC = 0x46546C67  # "glTF"
_CHUNK_JSON = 0x4E4F534A  # "JSON"
_CHUNK_BIN = 0x004E4942  # "BIN\0"

#: Primitive modes that produce triangles, mapped to a triangle-count function
#: of the vertex or index count. Modes 0-3 (points and lines) contribute none.
_TRIANGLE_MODES = {
    4: lambda n: n // 3,  # TRIANGLES
    5: lambda n: max(n - 2, 0),  # TRIANGLE_STRIP
    6: lambda n: max(n - 2, 0),  # TRIANGLE_FAN
}


class GlbError(ValueError):
    """The file is not a GLB we can read."""


@dataclass
class ImageInfo:
    index: int
    name: str
    mime: str
    width: int
    height: int
    bytes: int


@dataclass
class GlbInfo:
    """Measured facts about one GLB file."""

    path: str
    file_bytes: int
    triangles: int
    #: Primitive count, a reasonable proxy for draw calls per instance.
    primitives: int
    meshes: int
    materials: int
    images: list[ImageInfo] = field(default_factory=list)
    #: Axis-aligned bounds in model units, from POSITION accessor min/max.
    bounds_min: tuple[float, float, float] | None = None
    bounds_max: tuple[float, float, float] | None = None
    #: Joint names from the first skin, in skin order.
    joints: list[str] = field(default_factory=list)
    animations: list[str] = field(default_factory=list)
    #: Materials that declare no base colour texture and no base colour factor.
    untextured_materials: list[str] = field(default_factory=list)
    generator: str = ""

    @property
    def size(self) -> tuple[float, float, float]:
        """Width, height, depth in model units."""
        if not (self.bounds_min and self.bounds_max):
            return (0.0, 0.0, 0.0)
        return tuple(hi - lo for lo, hi in zip(self.bounds_min, self.bounds_max))  # type: ignore[return-value]

    @property
    def height(self) -> float:
        """Extent along +Y, the glTF up axis."""
        return self.size[1]

    @property
    def max_texture_edge(self) -> int:
        return max((max(i.width, i.height) for i in self.images), default=0)


def read(path: str) -> GlbInfo:
    """Parse a GLB file and measure it."""
    with open(path, "rb") as handle:
        blob = handle.read()

    document, binary = _split_chunks(blob, path)
    info = GlbInfo(
        path=path,
        file_bytes=len(blob),
        triangles=0,
        primitives=0,
        meshes=len(document.get("meshes", [])),
        materials=len(document.get("materials", [])),
        generator=str(document.get("asset", {}).get("generator", "")),
    )

    accessors = document.get("accessors", [])
    _measure_geometry(document, accessors, info)
    _measure_bounds(document, accessors, info)
    _measure_images(document, binary, info)
    _measure_rig(document, info)
    _measure_materials(document, info)
    return info


def _split_chunks(blob: bytes, path: str) -> tuple[dict, bytes]:
    if len(blob) < 12:
        raise GlbError(f"{path}: too short to be a GLB ({len(blob)} bytes)")
    magic, version, declared_length = struct.unpack_from("<III", blob, 0)
    if magic != _GLB_MAGIC:
        raise GlbError(f"{path}: not a GLB file (bad magic); is this a .gltf or a partial download?")
    if version != 2:
        raise GlbError(f"{path}: GLB version {version}, expected 2")
    if declared_length != len(blob):
        raise GlbError(
            f"{path}: header declares {declared_length} bytes but file is {len(blob)}; "
            "likely a truncated download"
        )

    document: dict | None = None
    binary = b""
    offset = 12
    while offset + 8 <= len(blob):
        chunk_length, chunk_type = struct.unpack_from("<II", blob, offset)
        start = offset + 8
        end = start + chunk_length
        if end > len(blob):
            raise GlbError(f"{path}: chunk at {offset} overruns the file")
        if chunk_type == _CHUNK_JSON:
            document = json.loads(blob[start:end].decode("utf-8"))
        elif chunk_type == _CHUNK_BIN:
            binary = blob[start:end]
        offset = end + (-end % 4)  # chunks are 4-byte aligned

    if document is None:
        raise GlbError(f"{path}: no JSON chunk found")
    return document, binary


def _measure_geometry(document: dict, accessors: list[dict], info: GlbInfo) -> None:
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            info.primitives += 1
            mode = primitive.get("mode", 4)
            counter = _TRIANGLE_MODES.get(mode)
            if counter is None:
                continue
            indices = primitive.get("indices")
            if indices is not None:
                count = int(accessors[indices].get("count", 0))
            else:
                position = primitive.get("attributes", {}).get("POSITION")
                count = int(accessors[position].get("count", 0)) if position is not None else 0
            info.triangles += counter(count)


Matrix = tuple[float, ...]  # 16 values, row-major

_IDENTITY: Matrix = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    return tuple(
        sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4))
        for row in range(4)
        for col in range(4)
    )


def _node_matrix(node: dict) -> Matrix:
    """Local transform of one node, as a row-major 4x4."""
    if "matrix" in node:
        # glTF stores matrices column-major; transpose to row-major.
        m = [float(v) for v in node["matrix"]]
        return tuple(m[col * 4 + row] for row in range(4) for col in range(4))

    tx, ty, tz = (float(v) for v in node.get("translation", (0.0, 0.0, 0.0)))
    sx, sy, sz = (float(v) for v in node.get("scale", (1.0, 1.0, 1.0)))
    x, y, z, w = (float(v) for v in node.get("rotation", (0.0, 0.0, 0.0, 1.0)))

    # Quaternion to rotation matrix, then fold in scale and translation.
    r = (
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
    )
    scale = (sx, sy, sz)
    return (
        r[0] * scale[0], r[1] * scale[1], r[2] * scale[2], tx,
        r[3] * scale[0], r[4] * scale[1], r[5] * scale[2], ty,
        r[6] * scale[0], r[7] * scale[1], r[8] * scale[2], tz,
        0.0, 0.0, 0.0, 1.0,
    )


def _transform_point(m: Matrix, p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )


def _measure_bounds(document: dict, accessors: list[dict], info: GlbInfo) -> None:
    """Union the POSITION accessor bounds in world space.

    Node transforms are applied, because they matter: postprocess.py corrects an
    asset's scale and ground position by wrapping it in a transform node rather
    than rewriting vertex data, so bounds read straight off the accessors would
    report the uncorrected size and the scale check would fail a perfectly good
    asset.

    Each mesh's local axis-aligned box is transformed corner by corner and
    re-fitted. For a rotated node that over-estimates slightly, which is the
    right direction to err for a budget check.

    Skinned meshes are measured in bind pose: the spec says a skinned mesh node's
    own transform is ignored at runtime, but bind pose is what we want to check
    scale against anyway.
    """
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    scenes = document.get("scenes", [])

    local_boxes: dict[int, tuple[list[float], list[float]]] = {}
    for index, mesh in enumerate(meshes):
        lows: list[list[float]] = []
        highs: list[list[float]] = []
        for primitive in mesh.get("primitives", []):
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None:
                continue
            accessor = accessors[position]
            low, high = accessor.get("min"), accessor.get("max")
            if isinstance(low, list) and isinstance(high, list) and len(low) == len(high) == 3:
                lows.append([float(v) for v in low])
                highs.append([float(v) for v in high])
        if lows:
            local_boxes[index] = (
                [min(v[i] for v in lows) for i in range(3)],
                [max(v[i] for v in highs) for i in range(3)],
            )

    if not local_boxes:
        return

    world_low = [float("inf")] * 3
    world_high = [float("-inf")] * 3
    seen: set[int] = set()

    def visit(node_index: int, parent: Matrix) -> None:
        # Guards against a malformed file with a cycle in the node graph.
        if node_index in seen or not (0 <= node_index < len(nodes)):
            return
        seen.add(node_index)
        node = nodes[node_index]
        world = _multiply(parent, _node_matrix(node))

        mesh_index = node.get("mesh")
        if mesh_index in local_boxes:
            low, high = local_boxes[mesh_index]
            for cx in (low[0], high[0]):
                for cy in (low[1], high[1]):
                    for cz in (low[2], high[2]):
                        point = _transform_point(world, (cx, cy, cz))
                        for axis in range(3):
                            world_low[axis] = min(world_low[axis], point[axis])
                            world_high[axis] = max(world_high[axis], point[axis])

        for child in node.get("children", []):
            visit(int(child), world)

    roots = scenes[document.get("scene", 0)].get("nodes", []) if scenes else range(len(nodes))
    for root in roots:
        visit(int(root), _IDENTITY)

    if world_low[0] == float("inf"):
        # No mesh reachable from the scene graph. Fall back to local boxes so a
        # malformed scene still reports a size rather than nothing at all.
        for low, high in local_boxes.values():
            for axis in range(3):
                world_low[axis] = min(world_low[axis], low[axis])
                world_high[axis] = max(world_high[axis], high[axis])

    if world_low[0] != float("inf"):
        info.bounds_min = (world_low[0], world_low[1], world_low[2])
        info.bounds_max = (world_high[0], world_high[1], world_high[2])


def _measure_images(document: dict, binary: bytes, info: GlbInfo) -> None:
    buffer_views = document.get("bufferViews", [])
    for index, image in enumerate(document.get("images", [])):
        payload = b""
        if "bufferView" in image:
            view = buffer_views[image["bufferView"]]
            start = int(view.get("byteOffset", 0))
            payload = binary[start : start + int(view.get("byteLength", 0))]
        elif str(image.get("uri", "")).startswith("data:"):
            _, _, encoded = str(image["uri"]).partition(",")
            try:
                payload = base64.b64decode(encoded)
            except ValueError:
                payload = b""
        # An external-file uri is left at 0x0; validate.py reports that as a
        # non-self-contained asset, which is its own problem.
        width, height, mime = _image_dimensions(payload)
        info.images.append(
            ImageInfo(
                index=index,
                name=str(image.get("name", "") or f"image_{index}"),
                mime=str(image.get("mimeType", "") or mime),
                width=width,
                height=height,
                bytes=len(payload),
            )
        )


def _image_dimensions(payload: bytes) -> tuple[int, int, str]:
    """Read width and height from a PNG or JPEG header."""
    if payload[:8] == b"\x89PNG\r\n\x1a\n" and len(payload) >= 24:
        width, height = struct.unpack_from(">II", payload, 16)
        return int(width), int(height), "image/png"
    if payload[:2] == b"\xff\xd8":
        offset = 2
        while offset + 4 <= len(payload):
            if payload[offset] != 0xFF:
                offset += 1
                continue
            marker = payload[offset + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                if offset + 9 <= len(payload):
                    height, width = struct.unpack_from(">HH", payload, offset + 5)
                    return int(width), int(height), "image/jpeg"
                break
            segment_length = struct.unpack_from(">H", payload, offset + 2)[0]
            offset += 2 + segment_length
    return 0, 0, ""


def _measure_rig(document: dict, info: GlbInfo) -> None:
    nodes = document.get("nodes", [])
    skins = document.get("skins", [])
    if skins:
        for joint in skins[0].get("joints", []):
            if 0 <= joint < len(nodes):
                info.joints.append(str(nodes[joint].get("name", f"node_{joint}")))
    info.animations = [
        str(animation.get("name", "") or f"animation_{i}")
        for i, animation in enumerate(document.get("animations", []))
    ]


def _measure_materials(document: dict, info: GlbInfo) -> None:
    for index, material in enumerate(document.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        has_texture = "baseColorTexture" in pbr
        has_factor = "baseColorFactor" in pbr
        if not has_texture and not has_factor:
            info.untextured_materials.append(str(material.get("name", "") or f"material_{index}"))

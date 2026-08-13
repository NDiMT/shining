"""Normalise a generated GLB to Hollow Crown's conventions.

Generators do not produce engine-ready assets. Measured against a real Meshy
result (see docs/ASSET_PIPELINE.md), three things are reliably wrong:

* **Scale.** Output is normalised to roughly 1.8 units regardless of subject, so
  a barrel arrives the size of a person.
* **Origin.** The mesh is centred on its bounding box rather than sitting on the
  ground plane, so it floats or sinks on the battle grid.
* **Texture size.** The API's smallest texture is 2k. Brief section 8 wants 512
  for generic assets and 1024 for standard characters.

None of that is a generator defect; it is a difference in conventions. This
module fixes all three in place so the validator's job is to catch real problems
rather than to complain about a known, fixable mismatch on every asset.

Pillow is an **optional** dependency, needed only for texture downscaling.
Geometry normalisation and everything else in this package are standard library
only, so the validator still runs anywhere with no install — which matters
because the validator is what belongs in CI.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import struct
from dataclasses import dataclass, field

from . import glb

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942


class PostProcessError(RuntimeError):
    pass


@dataclass
class Changes:
    """What normalisation actually did, for logs and provenance."""

    scaled: float | None = None
    grounded: bool = False
    resized_images: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return bool(self.scaled or self.grounded or self.resized_images)

    def describe(self) -> list[str]:
        out: list[str] = []
        if self.scaled:
            out.append(f"scaled by {self.scaled:.4f}")
        if self.grounded:
            out.append("origin moved to ground plane")
        for name in self.resized_images:
            out.append(f"downscaled texture {name}")
        return out


def pillow_available() -> bool:
    """Whether texture downscaling is possible in this environment."""
    return importlib.util.find_spec("PIL.Image") is not None


def normalise(
    path: str,
    *,
    target_height: float | None,
    texture_max: int,
    ground: bool = True,
) -> Changes:
    """Rewrite ``path`` in place so it matches our conventions.

    Returns a record of what changed. Safe to run more than once: a normalised
    asset produces no further changes.
    """
    document, binary = _read(path)
    changes = Changes()

    if target_height is not None:
        _normalise_transform(document, path, target_height, ground, changes)

    replacements: dict[int, bytes] = {}
    if texture_max:
        replacements = _downscale_images(document, binary, texture_max, changes)

    if changes.touched:
        binary = _repack_buffer(document, binary, replacements)
        _write(path, document, binary)
    return changes


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _normalise_transform(
    document: dict, path: str, target_height: float, ground: bool, changes: Changes
) -> None:
    """Insert a root node that scales the asset and sits it on y=0.

    A wrapper node is used rather than rewriting vertex data: it is exact,
    reversible, and leaves accessor bounds untouched so the original generator
    output stays inspectable.
    """
    if document.get("skins"):
        # For skinned meshes the mesh node's own transform is ignored and joint
        # matrices come from the skeleton, so wrapping is subtler than it looks.
        # The rigging API already takes height_meters, so rigged assets should
        # arrive correctly sized; scaling them here would risk a subtle,
        # hard-to-debug break for no gain.
        changes.skipped.append("scale: asset is skinned; rigging sets height instead")
        return

    info = glb.read(path)
    if info.bounds_min is None or info.bounds_max is None:
        changes.skipped.append("scale: no POSITION bounds")
        return

    height = info.height
    if height <= 0:
        changes.skipped.append("scale: zero height")
        return

    factor = target_height / height
    low, high = info.bounds_min, info.bounds_max
    centre_x = (low[0] + high[0]) / 2.0
    centre_z = (low[2] + high[2]) / 2.0

    needs_scale = abs(factor - 1.0) > 0.01
    needs_ground = ground and (
        abs(low[1]) > 1e-4 or abs(centre_x) > 1e-4 or abs(centre_z) > 1e-4
    )
    if not (needs_scale or needs_ground):
        return

    scenes = document.setdefault("scenes", [{"nodes": []}])
    scene = scenes[document.get("scene", 0)]
    old_roots = list(scene.get("nodes", []))
    if not old_roots:
        changes.skipped.append("scale: scene has no root nodes")
        return

    # A glTF node applies translation * rotation * scale to its children, so a
    # child point p maps to T + factor*p. Solving for the lowest point landing on
    # y=0 and the footprint centred on the origin gives the translation below.
    wrapper: dict = {"name": "hollow_normalise"}
    if needs_scale:
        wrapper["scale"] = [factor, factor, factor]
    if needs_ground:
        wrapper["translation"] = [
            -centre_x * factor,
            -low[1] * factor,
            -centre_z * factor,
        ]
    wrapper["children"] = old_roots

    document.setdefault("nodes", []).append(wrapper)
    scene["nodes"] = [len(document["nodes"]) - 1]

    if needs_scale:
        changes.scaled = factor
    if needs_ground:
        changes.grounded = True


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------


def _downscale_images(
    document: dict, binary: bytes, texture_max: int, changes: Changes
) -> dict[int, bytes]:
    """Resize oversized images. Returns replacement payloads by bufferView index.

    The replacements are applied by ``_repack_buffer`` rather than here, because
    changing one image's size shifts the offset of every bufferView after it.
    """
    images = document.get("images", [])
    if not images:
        return {}

    oversized = []
    buffer_views = document.get("bufferViews", [])
    for index, image in enumerate(images):
        if "bufferView" not in image:
            continue
        view = buffer_views[image["bufferView"]]
        start = int(view.get("byteOffset", 0))
        payload = binary[start : start + int(view.get("byteLength", 0))]
        width, height, _ = glb._image_dimensions(payload)
        if max(width, height) > texture_max:
            oversized.append((index, image, payload, width, height))

    if not oversized:
        return {}

    if not pillow_available():
        changes.skipped.append(
            f"texture downscale: Pillow not installed; {len(oversized)} image(s) "
            f"left over the {texture_max}px budget. Install Pillow or resize in Blender"
        )
        return {}

    from PIL import Image

    replacements: dict[int, bytes] = {}
    for index, image, payload, width, height in oversized:
        scale = texture_max / max(width, height)
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        with Image.open(io.BytesIO(payload)) as source:
            resized = source.convert("RGBA" if source.mode in ("RGBA", "LA", "P") else "RGB")
            resized = resized.resize(new_size, Image.LANCZOS)
            out = io.BytesIO()
            # PNG keeps the alpha channel and avoids a second generation of JPEG
            # artefacts on an already-compressed source.
            resized.save(out, format="PNG", optimize=True)
        replacements[image["bufferView"]] = out.getvalue()
        image["mimeType"] = "image/png"
        name = str(image.get("name", "") or f"image_{index}")
        changes.resized_images.append(f"{name} {width}x{height} -> {new_size[0]}x{new_size[1]}")

    return replacements


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


def _repack_buffer(
    document: dict, binary: bytes, replacements: dict[int, bytes]
) -> bytes:
    """Rebuild the binary chunk, applying any image replacements.

    Every bufferView is copied in index order into a fresh buffer with 4-byte
    alignment and its ``byteOffset`` rewritten. Rebuilding wholesale is the only
    safe way to change an image's size: patching in place would shift every
    offset after it.
    """
    buffer_views = document.get("bufferViews", [])
    if not buffer_views:
        return binary

    out = bytearray()
    for index, view in enumerate(buffer_views):
        if index in replacements:
            payload = replacements[index]
        else:
            start = int(view.get("byteOffset", 0))
            payload = binary[start : start + int(view.get("byteLength", 0))]
        while len(out) % 4:
            out.append(0)
        view["byteOffset"] = len(out)
        view["byteLength"] = len(payload)
        view["buffer"] = 0
        out.extend(payload)

    document["buffers"] = [{"byteLength": len(out)}]
    return bytes(out)


def _read(path: str) -> tuple[dict, bytes]:
    with open(path, "rb") as handle:
        blob = handle.read()
    if len(blob) < 12 or struct.unpack_from("<I", blob, 0)[0] != _GLB_MAGIC:
        raise PostProcessError(f"{path}: not a GLB file")

    document: dict | None = None
    binary = b""
    offset = 12
    while offset + 8 <= len(blob):
        length, kind = struct.unpack_from("<II", blob, offset)
        start, end = offset + 8, offset + 8 + length
        if kind == _CHUNK_JSON:
            document = json.loads(blob[start:end].decode("utf-8"))
        elif kind == _CHUNK_BIN:
            binary = blob[start:end]
        offset = end + (-end % 4)
    if document is None:
        raise PostProcessError(f"{path}: no JSON chunk")
    return document, binary


def _write(path: str, document: dict, binary: bytes) -> None:
    """Write a GLB atomically, so an interrupted run cannot corrupt the asset."""
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)  # pad with spaces, per spec
    binary_chunk = bytes(binary) + b"\x00" * (-len(binary) % 4)

    total = 12 + 8 + len(json_chunk) + (8 + len(binary_chunk) if binary_chunk else 0)
    parts = [
        struct.pack("<III", _GLB_MAGIC, 2, total),
        struct.pack("<II", len(json_chunk), _CHUNK_JSON),
        json_chunk,
    ]
    if binary_chunk:
        parts.append(struct.pack("<II", len(binary_chunk), _CHUNK_BIN))
        parts.append(binary_chunk)

    temporary = f"{path}.tmp"
    with open(temporary, "wb") as handle:
        handle.write(b"".join(parts))
    os.replace(temporary, path)

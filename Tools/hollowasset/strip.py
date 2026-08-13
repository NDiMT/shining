"""Remove the scenery the generator attaches to an asset.

Measured across a six-asset sample (docs/ASSET_PIPELINE.md), every static asset
came back as a diorama rather than an object:

===========================  =======  =========  ==========================
Asset                        Islands  Subject    Scenery
===========================  =======  =========  ==========================
``building_house_small_a``         4  2,933      779 + 770 trees, 56 slab
``prop_barrel_a``                 33  1,060      3,546 across 32 fragments
``veg_tree_oak_a``                 2  22,104     grass disc **fused**
===========================  =======  =========  ==========================

All three were generated with ``base plinth``, ``ground plane`` and ``scenery
around the object`` in the avoid clause. Prompt tokens do not stop this, so it
gets fixed after the fact instead — and it is worth fixing rather than living
with, for three reasons that are not about tidiness:

* **Budget.** The barrel drops from 4,606 triangles to 1,060, inside its
  400–4,000 prop budget, with no reduction pass and nothing lost. A reduction
  pass at that ratio tore the barrel apart when it was tried.
* **Scale.** Height normalisation fits the *bounding box*, so a 7.8m ground slab
  shrinks the house that stands on it. The asset is the wrong size until the slab
  is gone.
* **Repetition.** Twelve barrels in a village means twelve identical clumps of
  grass, at twelve different angles, intersecting the terrain.

The default rule drops only what lies entirely below the subject's base, which is
what ground litter *is* and is safe to run unattended. It under-removes on
purpose: the first version of this module kept the N largest islands instead, and
on the house that would have deleted the 56-triangle chimney along with the two
bonus trees. Small does not mean scenery, and no geometric test separates a
market stall's awning from a bonus tree — so anything beyond ground litter is a
human decision, made once per asset in the catalog.

Vertex data is compacted, not just re-indexed, and it has to be. The first
version rewrote indices alone: the barrel's triangle count fell from 4,606 to
1,060 and its measured **bounding box did not move**, because the discarded
vertices were still in the POSITION accessor and the validator reads that
accessor's declared min/max. The asset would have gone on being scaled to fit
grass that no longer existed — losing the second of the three reasons above,
which is the one that actually makes the asset the wrong size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import glb
from .postprocess import PostProcessError, _read, _repack_buffer, _write


@dataclass(frozen=True)
class Island:
    """One connected run of triangles within a primitive."""

    mesh: int
    primitive: int
    root: int
    triangles: int
    #: Local-space bounds. Local rather than world because the decision this
    #: informs — is this the subject or is it scenery — is about relative size
    #: and position within one primitive, where the node transform is common to
    #: every island and cancels out.
    low: tuple[float, float, float]
    high: tuple[float, float, float]

    @property
    def footprint(self) -> float:
        """Horizontal area of the island's bounding box.

        A ground slab is the one piece of scenery that is *not* small: the
        house's was 56 triangles and 7.8m square. Triangle count alone would rank
        it as the least significant island; by footprint it is the largest thing
        in the file.
        """
        return (self.high[0] - self.low[0]) * (self.high[2] - self.low[2])


@dataclass
class StripResult:
    path: str
    triangles_before: int = 0
    triangles_after: int = 0
    kept: list[Island] = field(default_factory=list)
    dropped: list[Island] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.dropped)

    def describe(self) -> list[str]:
        """Lines for the pipeline log and the provenance record."""
        if not self.changed:
            return []
        return [
            f"auto: stripped {len(self.dropped)} scenery island(s), "
            f"{self.triangles_before:,} -> {self.triangles_after:,} triangles"
        ]


def survey(path: str) -> list[Island]:
    """Every island in the file, largest first.

    Read-only. Run this before stripping anything: the count it reports is the
    number a catalog entry's ``keep_islands`` has to be set against, and getting
    it wrong deletes real geometry.
    """
    document, binary = _read(path)
    return _survey(document, binary)


def strip(path: str, *, keep: int | None = None, out: str | None = None) -> StripResult:
    """Remove scenery islands. Two modes, and the difference matters.

    With ``keep`` unset — the default and the only mode safe to run unattended —
    an island is dropped when its **highest point is at or below the subject's
    lowest point**. That is the geometric definition of litter lying on the
    ground around a thing, and it is what the generator actually produces:

    * The barrel's subject spans y −0.36…0.74; all thirty-two fragments span
      −0.73…−0.36 or lower. Every one is dropped, 4,606 triangles become 1,060,
      and nothing that is part of the barrel is touched.
    * The house keeps everything. Its two bonus trees start at y −0.38 against a
      subject floor of −0.49, so they overlap and survive; its chimney is at the
      top and obviously survives. Under-removal, on purpose.

    The tempting alternative — keep the N largest islands — was written first and
    is wrong. On the house it would have deleted the 56-triangle **chimney**
    along with the trees, because a chimney is small and a bonus tree is not.
    Small does not mean scenery, and there is no geometric test that separates an
    awning from a bonus tree. So the automatic rule under-removes by design: a
    surviving grass tuft costs triangles, a deleted chimney costs a regeneration.

    With ``keep=N``, the N largest islands by triangle count are kept and the rest
    dropped, regardless of position. This is the manual override, for the cases
    the automatic rule cannot reach. Run ``survey()`` and look at the numbers
    before setting it — this is the mode that deletes chimneys.

    Neither mode helps when the scenery is *fused* to the subject, which is the
    tree's grass disc and the house's ground slab: one island, one mesh, and
    nothing here can separate them. Those need Blender or a better prompt.
    """
    if keep is not None and keep < 1:
        raise PostProcessError(f"{path}: keep must be at least 1, got {keep}")

    document, binary = _read(path)
    islands = _survey(document, binary)
    result = StripResult(
        path=out or path,
        triangles_before=sum(island.triangles for island in islands),
    )
    if keep is not None:
        result.kept, result.dropped = islands[:keep], islands[keep:]
    elif islands:
        floor = islands[0].low[1]
        result.kept = [i for i in islands if i.high[1] > floor]
        result.dropped = [i for i in islands if i.high[1] <= floor]
    result.triangles_after = sum(island.triangles for island in result.kept)

    if not result.dropped:
        if out and out != path:
            _write(out, document, binary)
        return result

    survivors = {(i.mesh, i.primitive, i.root) for i in result.kept}
    replacements: dict[int, bytes] = {}
    _rewrite(document, binary, survivors, replacements)
    binary = _repack_buffer(document, binary, replacements)
    _write(out or path, document, binary)
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _triangle_islands(
    document: dict, binary: bytes, mesh_index: int, primitive_index: int
) -> tuple[list[int], list[int], list[int]] | None:
    """Partition one primitive's triangles into islands.

    Returns ``(raw_indices, welded_indices, root_per_triangle)``, or None when the
    primitive is not indexed triangles this module can safely touch.

    Connectivity is by welded vertex *position*, matching ``glb._measure_islands``
    — and for the same reason. A flat-shaded low-poly mesh duplicates vertices at
    every hard edge, so partitioning by raw index reported 351 islands in a barrel
    that has one body and some shards.
    """
    accessors = document.get("accessors", [])
    mesh = document.get("meshes", [])[mesh_index]
    primitive = mesh.get("primitives", [])[primitive_index]
    if primitive.get("mode", 4) != 4 or "indices" not in primitive:
        return None

    accessor = accessors[primitive["indices"]]
    entry = glb._INDEX_FORMAT.get(accessor.get("componentType"))
    if entry is None:
        return None
    fmt, size = entry
    view = document["bufferViews"][accessor["bufferView"]]
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    count = int(accessor.get("count", 0))
    if count < 3 or start + count * size > len(binary):
        return None

    raw = list(struct.unpack_from("<" + fmt * count, binary, start))
    weld = glb._weld_map(document, accessors, binary, primitive)
    if weld is None:
        return None
    welded = [weld[i] if i < len(weld) else i for i in raw]

    parent: dict[int, int] = {}

    def find(a: int) -> int:
        root = a
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(a, a) != root:
            parent[a], a = root, parent[a]
        parent[a] = root
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    triangles = range(0, count - 2, 3)
    for i in triangles:
        a, b, c = welded[i], welded[i + 1], welded[i + 2]
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        parent.setdefault(c, c)
        union(a, b)
        union(b, c)

    return raw, welded, [find(welded[i]) for i in triangles]


def _positions(document: dict, binary: bytes, primitive: dict) -> list[tuple[float, float, float]] | None:
    attributes = primitive.get("attributes", {})
    if "POSITION" not in attributes:
        return None
    accessor = document["accessors"][attributes["POSITION"]]
    if accessor.get("componentType") != 5126 or accessor.get("type") != "VEC3":
        return None
    view = document["bufferViews"][accessor["bufferView"]]
    stride = int(view.get("byteStride") or 12)
    base = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    count = int(accessor.get("count", 0))
    if base + max(0, count - 1) * stride + 12 > len(binary):
        return None
    return [struct.unpack_from("<fff", binary, base + i * stride) for i in range(count)]


def _survey(document: dict, binary: bytes) -> list[Island]:
    islands: list[Island] = []
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            partition = _triangle_islands(document, binary, mesh_index, primitive_index)
            if partition is None:
                continue
            raw, _, roots = partition
            points = _positions(document, binary, primitive)

            counts: dict[int, int] = {}
            low: dict[int, list[float]] = {}
            high: dict[int, list[float]] = {}
            for triangle, root in enumerate(roots):
                counts[root] = counts.get(root, 0) + 1
                if points is None:
                    continue
                for corner in raw[triangle * 3 : triangle * 3 + 3]:
                    if corner >= len(points):
                        continue
                    point = points[corner]
                    if root not in low:
                        low[root] = list(point)
                        high[root] = list(point)
                        continue
                    for axis in range(3):
                        low[root][axis] = min(low[root][axis], point[axis])
                        high[root][axis] = max(high[root][axis], point[axis])

            zero = (0.0, 0.0, 0.0)
            islands.extend(
                Island(
                    mesh=mesh_index,
                    primitive=primitive_index,
                    root=root,
                    triangles=total,
                    low=tuple(low.get(root, zero)),  # type: ignore[arg-type]
                    high=tuple(high.get(root, zero)),  # type: ignore[arg-type]
                )
                for root, total in counts.items()
            )

    return sorted(islands, key=lambda island: island.triangles, reverse=True)


def _rewrite(
    document: dict, binary: bytes, survivors: set[tuple[int, int, int]], replacements: dict[int, bytes]
) -> None:
    """Rebuild each primitive's index buffer from its surviving triangles.

    The index component type is left alone. Keeping a subset can only lower the
    largest index, never raise it, so a buffer that was valid as uint16 stays
    valid as uint16.
    """
    accessors = document["accessors"]
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        surviving_primitives = []
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            partition = _triangle_islands(document, binary, mesh_index, primitive_index)
            if partition is None:
                surviving_primitives.append(primitive)
                continue
            raw, _, roots = partition

            kept: list[int] = []
            for triangle, root in enumerate(roots):
                if (mesh_index, primitive_index, root) in survivors:
                    kept.extend(raw[triangle * 3 : triangle * 3 + 3])

            if not kept:
                # A primitive with no triangles left is dropped entirely rather
                # than kept as an empty draw call.
                continue

            # Compact the vertices too. Re-indexing alone leaves the discarded
            # vertices in the POSITION accessor, and the validator measures scale
            # from that accessor's min/max -- so the barrel's box stayed exactly
            # 1.16 x 0.90 x 1.16 after its grass was removed, and it would have
            # gone on being scaled to fit grass that no longer existed.
            order: dict[int, int] = {}
            for old in kept:
                order.setdefault(old, len(order))
            kept = [order[old] for old in kept]
            for name, accessor_index in primitive.get("attributes", {}).items():
                _compact_attribute(document, binary, accessor_index, order, replacements, name)

            accessor = accessors[primitive["indices"]]
            fmt, _ = glb._INDEX_FORMAT[accessor["componentType"]]
            _claim_view(document, accessor, replacements,
                        struct.pack("<" + fmt * len(kept), *kept))
            accessor["count"] = len(kept)
            if "min" in accessor or "max" in accessor:
                accessor["min"] = [min(kept)]
                accessor["max"] = [max(kept)]
            surviving_primitives.append(primitive)

        mesh["primitives"] = surviving_primitives


#: glTF component type -> (struct format, byte size). Mirrors glb._INDEX_FORMAT
#: but covers the signed and float types an attribute can use.
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
              5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_ELEMENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _claim_view(document: dict, accessor: dict, replacements: dict[int, bytes],
                payload: bytes) -> None:
    """Point ``accessor`` at ``payload``, without disturbing anything else.

    A bufferView shared by several accessors cannot be replaced in place, so the
    accessor gets a fresh view instead. Interleaved vertex data is the common case
    where this happens, and silently overwriting it would corrupt every other
    attribute in the same buffer.
    """
    view_index = accessor["bufferView"]
    if _view_users(document, view_index) > 1:
        document["bufferViews"].append({"buffer": 0, "byteOffset": 0, "byteLength": 0})
        view_index = len(document["bufferViews"]) - 1
        accessor["bufferView"] = view_index
    replacements[view_index] = payload
    accessor.pop("byteOffset", None)
    document["bufferViews"][view_index].pop("byteStride", None)


def _compact_attribute(document: dict, binary: bytes, accessor_index: int,
                       order: dict[int, int], replacements: dict[int, bytes],
                       name: str) -> None:
    """Rewrite one vertex attribute to hold only the vertices still referenced.

    Element-agnostic: whatever the component type and element count, one element
    is a fixed run of bytes, so gathering is a copy. Only ``min``/``max`` need to
    know what the numbers mean, and only when the accessor already declared them.
    """
    accessor = document["accessors"][accessor_index]
    entry = _COMPONENT.get(accessor.get("componentType"))
    per = _ELEMENTS.get(accessor.get("type", ""))
    if entry is None or per is None:
        raise PostProcessError(
            f"attribute {name}: unsupported accessor "
            f"{accessor.get('type')}/{accessor.get('componentType')}"
        )
    fmt, size = entry
    element = size * per
    view = document["bufferViews"][accessor["bufferView"]]
    stride = int(view.get("byteStride") or element)
    base = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))

    payload = bytearray()
    for old in sorted(order, key=order.__getitem__):
        start = base + old * stride
        if start + element > len(binary):
            raise PostProcessError(f"attribute {name}: accessor runs past the buffer")
        payload += binary[start : start + element]

    if "min" in accessor or "max" in accessor:
        values = [struct.unpack_from("<" + fmt * per, payload, i * element)
                  for i in range(len(order))]
        columns = list(zip(*values)) if values else [()] * per
        accessor["min"] = [min(column) for column in columns]
        accessor["max"] = [max(column) for column in columns]

    _claim_view(document, accessor, replacements, bytes(payload))
    accessor["count"] = len(order)


def _view_users(document: dict, view_index: int) -> int:
    users = sum(
        1 for accessor in document.get("accessors", [])
        if accessor.get("bufferView") == view_index
    )
    users += sum(
        1 for image in document.get("images", [])
        if image.get("bufferView") == view_index
    )
    return users

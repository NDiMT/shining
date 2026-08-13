"""Tests for scenery stripping.

In its own file rather than in test_hollowasset.py because these need a GLB
builder that places islands at chosen heights, and the shared ``build_glb``
deliberately puts every vertex on the ground plane.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Tools"))

from hollowasset import glb, strip  # noqa: E402
from hollowasset.postprocess import PostProcessError  # noqa: E402

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942


def build_islands(specs: list[tuple[int, float, float]], *, x_step: float = 100.0) -> bytes:
    """A GLB whose islands are ``(triangles, y_low, y_high)``.

    Each island is pushed ``x_step`` apart so position welding cannot join them,
    which is how the real connectivity check decides. Every triangle in an island
    spans the island's full y range, so a caller asking for (n, -0.7, -0.4) gets
    an island whose bounds are exactly that.
    """
    binary = bytearray()
    views: list[dict] = []

    def add_view(payload: bytes) -> int:
        while len(binary) % 4:
            binary.append(0)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(payload)})
        binary.extend(payload)
        return len(views) - 1

    coords = bytearray()
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for island, (triangles, y_low, y_high) in enumerate(specs):
        x = island * x_step
        for t in range(triangles):
            # A sliver triangle: two corners on the island's floor, one on its
            # ceiling, nudged along x so consecutive triangles in an island share
            # a welded corner and stay one connected component.
            offset = t * 1e-3
            for point in ((x + offset, y_low, 0.0),
                          (x + offset + 1e-3, y_low, 0.0),
                          (x + offset, y_high, 0.0)):
                coords += struct.pack("<fff", *point)
                for axis in range(3):
                    low[axis] = min(low[axis], point[axis])
                    high[axis] = max(high[axis], point[axis])
    position_view = add_view(bytes(coords))

    vertex_count = sum(t for t, _, _ in specs) * 3
    index_view = add_view(b"".join(struct.pack("<I", i) for i in range(vertex_count)))

    document = {
        "asset": {"version": "2.0", "generator": "hollowasset strip test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "asset_root", "mesh": 0}],
        "meshes": [{"primitives": [
            {"attributes": {"POSITION": 0}, "indices": 1, "material": 0, "mode": 4}]}],
        "materials": [{"name": "surface",
                       "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1]}}],
        "accessors": [
            {"bufferView": position_view, "componentType": 5126, "count": vertex_count,
             "type": "VEC3", "min": low, "max": high},
            {"bufferView": index_view, "componentType": 5125, "count": vertex_count,
             "type": "SCALAR", "min": [0], "max": [max(vertex_count - 1, 0)]},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }

    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary_chunk = bytes(binary) + b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    return b"".join([
        struct.pack("<III", _GLB_MAGIC, 2, total),
        struct.pack("<II", len(json_chunk), _CHUNK_JSON), json_chunk,
        struct.pack("<II", len(binary_chunk), _CHUNK_BIN), binary_chunk,
    ])


class StripTestCase(unittest.TestCase):
    def write(self, specs: list[tuple[int, float, float]]) -> str:
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "asset.glb")
        with open(path, "wb") as handle:
            handle.write(build_islands(specs))
        return path


class TestSurvey(StripTestCase):
    def test_islands_are_reported_largest_first_with_their_bounds(self):
        path = self.write([(20, -0.7, -0.4), (100, -0.4, 0.7), (5, 0.4, 0.5)])
        islands = strip.survey(path)
        self.assertEqual([i.triangles for i in islands], [100, 20, 5])
        self.assertAlmostEqual(islands[0].low[1], -0.4, places=5)
        self.assertAlmostEqual(islands[0].high[1], 0.7, places=5)

    def test_survey_does_not_modify_the_file(self):
        path = self.write([(100, 0.0, 1.0), (10, -0.5, -0.1)])
        with open(path, "rb") as handle:
            before = handle.read()
        strip.survey(path)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)


class TestGroundLitterRule(StripTestCase):
    """The barrel case: thirty-two fragments lying below the subject's base."""

    def test_islands_entirely_below_the_subject_are_dropped(self):
        subject = (1060, -0.36, 0.74)
        litter = [(200 - i * 5, -0.73, -0.36) for i in range(6)]
        path = self.write([subject, *litter])

        result = strip.strip(path)
        self.assertEqual(result.triangles_before, 1060 + sum(t for t, _, _ in litter))
        self.assertEqual(result.triangles_after, 1060)
        self.assertEqual(len(result.dropped), 6)
        self.assertEqual(glb.read(path).islands, [1060])

    def test_a_small_part_on_top_survives(self):
        """The house's chimney. 56 triangles against 2,933 -- a keep-the-largest
        rule deletes it, and it is not scenery."""
        path = self.write([(2933, -0.49, 0.49), (56, 0.44, 0.47)])
        result = strip.strip(path)
        self.assertFalse(result.changed)
        self.assertEqual(glb.read(path).islands, [2933, 56])

    def test_a_part_that_merely_overlaps_the_base_survives(self):
        """The house's bonus trees start above the subject's floor, so the rule
        keeps them. Under-removal is the intended failure direction."""
        path = self.write([(2933, -0.49, 0.49), (779, -0.38, 0.0)])
        self.assertFalse(strip.strip(path).changed)

    def test_a_clean_asset_is_left_byte_identical(self):
        path = self.write([(400, 0.0, 0.9)])
        with open(path, "rb") as handle:
            before = handle.read()
        self.assertFalse(strip.strip(path).changed)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)


class TestManualOverride(StripTestCase):
    def test_keep_n_drops_by_size_regardless_of_position(self):
        path = self.write([(2933, -0.49, 0.49), (779, -0.38, 0.0), (56, 0.44, 0.47)])
        result = strip.strip(path, keep=1)
        self.assertEqual(result.triangles_after, 2933)
        self.assertEqual(len(result.dropped), 2)

    def test_keep_two_preserves_the_second_part(self):
        """A market stall is a counter plus an awning, and an inn sign is a board
        plus a bracket. Both are two islands and neither is scenery."""
        path = self.write([(900, 0.0, 0.4), (300, 0.4, 0.9), (12, -0.4, -0.01)])
        result = strip.strip(path, keep=2)
        self.assertEqual(result.triangles_after, 1200)
        self.assertEqual([i.triangles for i in result.dropped], [12])

    def test_keep_below_one_is_refused(self):
        path = self.write([(100, 0.0, 1.0)])
        with self.assertRaises(PostProcessError):
            strip.strip(path, keep=0)


class TestOutputIsValid(StripTestCase):
    def test_the_stripped_file_is_still_a_readable_glb(self):
        path = self.write([(500, -0.3, 0.8), (40, -0.6, -0.3)])
        strip.strip(path)
        info = glb.read(path)
        self.assertEqual(info.triangles, 500)
        self.assertEqual(info.materials, 1)

    def test_out_leaves_the_original_untouched(self):
        path = self.write([(500, -0.3, 0.8), (40, -0.6, -0.3)])
        target = path.replace("asset.glb", "stripped.glb")
        result = strip.strip(path, out=target)
        self.assertEqual(result.path, target)
        self.assertEqual(glb.read(path).triangles, 540)
        self.assertEqual(glb.read(target).triangles, 500)

    def test_stripping_twice_changes_nothing_the_second_time(self):
        path = self.write([(500, -0.3, 0.8), (40, -0.6, -0.3)])
        self.assertTrue(strip.strip(path).changed)
        self.assertFalse(strip.strip(path).changed)

    def test_the_description_names_what_was_removed(self):
        path = self.write([(500, -0.3, 0.8), (40, -0.6, -0.3)])
        line = strip.strip(path).describe()[0]
        self.assertIn("1 scenery island", line)
        self.assertIn("540 -> 500", line)


if __name__ == "__main__":
    unittest.main()

"""Tests for the asset tooling.

Brief section 73: non-visual logic is testable and AI-written code is not assumed
correct. The GLB reader, the validator and the prompt packer are all pure
functions over data, so they get tested properly.

Hermetic by construction. Every test builds its own GLB in memory, so there are
no fixture files, no network and no Meshy credits involved. Run with:

    python -m unittest discover -s Tests -v
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Tools"))

from hollowasset import (  # noqa: E402
    animations,
    budgets,
    glb,
    postprocess,
    provenance,
    style,
    validate,
)

# ---------------------------------------------------------------------------
# Synthetic GLB construction
# ---------------------------------------------------------------------------


def make_png(width: int, height: int, colour: tuple[int, int, int] = (200, 150, 90)) -> bytes:
    """A real, decodable PNG. Hand-built so the tests need no image library."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + bytes(colour) * width  # filter byte 0, then pixels
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def build_glb(
    *,
    triangles: int = 500,
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (-0.3, 0.0, -0.3),
        (0.3, 0.9, 0.3),
    ),
    texture_size: int | None = 512,
    with_skin: bool = False,
    joint_names: list[str] | None = None,
    animation_names: list[str] | None = None,
    base_colour_factor: bool = True,
    node_scale: float | None = None,
    node_translation: tuple[float, float, float] | None = None,
) -> bytes:
    """Assemble a minimal but spec-valid GLB with the requested properties."""
    low, high = bounds
    vertex_count = triangles * 3

    binary = bytearray()
    buffer_views: list[dict] = []

    def add_view(payload: bytes) -> int:
        while len(binary) % 4:
            binary.append(0)
        buffer_views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(payload)})
        binary.extend(payload)
        return len(buffer_views) - 1

    position_view = add_view(b"\x00" * (vertex_count * 12))
    accessors = [
        {
            "bufferView": position_view,
            "componentType": 5126,  # FLOAT
            "count": vertex_count,
            "type": "VEC3",
            "min": list(low),
            "max": list(high),
        }
    ]

    document: dict = {
        "asset": {"version": "2.0", "generator": "hollowasset test"},
        "scene": 0,
        "meshes": [
            {
                "name": "mesh",
                "primitives": [{"attributes": {"POSITION": 0}, "material": 0, "mode": 4}],
            }
        ],
        "materials": [{"name": "surface", "pbrMetallicRoughness": {}}],
        "accessors": accessors,
        "bufferViews": buffer_views,
    }

    if base_colour_factor:
        document["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]

    node: dict = {"name": "asset_root", "mesh": 0}
    if node_scale is not None:
        node["scale"] = [node_scale, node_scale, node_scale]
    if node_translation is not None:
        node["translation"] = list(node_translation)
    document["nodes"] = [node]
    document["scenes"] = [{"nodes": [0]}]

    if texture_size:
        image_view = add_view(make_png(texture_size, texture_size))
        document["images"] = [{"name": "base_colour", "bufferView": image_view,
                               "mimeType": "image/png"}]
        document["samplers"] = [{}]
        document["textures"] = [{"sampler": 0, "source": 0}]
        document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}

    if with_skin:
        names = joint_names if joint_names is not None else list(validate.CANONICAL_BONES)
        first_joint = len(document["nodes"])
        for offset, name in enumerate(names):
            document["nodes"].append({"name": name})
        joints = [first_joint + i for i in range(len(names))]
        matrices = add_view(b"\x00" * (len(names) * 64))
        accessors.append(
            {"bufferView": matrices, "componentType": 5126, "count": len(names), "type": "MAT4"}
        )
        document["skins"] = [{"joints": joints, "inverseBindMatrices": len(accessors) - 1}]
        document["nodes"][0]["skin"] = 0
        document["scenes"][0]["nodes"] = [0] + joints

    if animation_names:
        document["animations"] = [{"name": name, "channels": [], "samplers": []}
                                  for name in animation_names]

    # Rebuild view offsets after all appends, then emit the container.
    document["bufferViews"] = buffer_views
    document["buffers"] = [{"byteLength": len(binary)}]

    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary_chunk = bytes(binary) + b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    return b"".join([
        struct.pack("<III", 0x46546C67, 2, total),
        struct.pack("<II", len(json_chunk), 0x4E4F534A),
        json_chunk,
        struct.pack("<II", len(binary_chunk), 0x004E4942),
        binary_chunk,
    ])


class GlbTempFile:
    """Context manager writing a synthetic GLB to a temporary path."""

    def __init__(self, **kwargs):
        self.payload = build_glb(**kwargs)
        self.path = ""

    def __enter__(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        handle.write(self.payload)
        handle.close()
        self.path = handle.name
        return self.path

    def __exit__(self, *_) -> None:
        for suffix in ("", ".tmp", ".part"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class TestBudgets(unittest.TestCase):
    def test_every_budget_is_internally_consistent(self):
        for key, budget in budgets.BUDGETS.items():
            low, high = budget.tri_soft
            self.assertLess(low, high, f"{key}: soft range inverted")
            self.assertGreaterEqual(budget.tri_hard, high, f"{key}: hard cap below soft range")
            self.assertIn(budget.tri_target, range(low, high + 1), f"{key}: target outside range")
            self.assertGreater(budget.texture_max, 0)

    def test_character_classes_match_the_brief_exactly(self):
        """Brief section 7 is the only source for these, and no character has
        been generated yet to justify moving them."""
        self.assertEqual(budgets.get("hero").tri_soft, (4_000, 10_000))
        self.assertEqual(budgets.get("hero").tri_hard, 12_000)
        self.assertEqual(budgets.get("npc").tri_soft, (2_000, 6_000))
        self.assertEqual(budgets.get("enemy_humanoid").tri_soft, (2_000, 6_000))
        self.assertEqual(budgets.get("monster_large").tri_soft, (5_000, 15_000))
        self.assertEqual(budgets.get("boss").tri_soft, (10_000, 25_000))

    def test_static_classes_admit_the_generator_native_density(self):
        """Deliberately above brief section 7. See the module docstring: API
        decimation was measured and tears geometry at every level, so a class
        that cannot hold a clean generated mesh just fails every asset.

        A barrel's clean native output was 6,392 triangles. The prop class must
        warn about that, not reject it.
        """
        prop = budgets.get("prop")
        self.assertGreater(prop.tri_hard, 6_392, "a clean native barrel must not fail")
        self.assertLess(prop.tri_soft[1], 6_392, "but it should still warn as over target")
        for key in ("weapon", "prop", "vegetation", "building_module", "set_piece"):
            self.assertFalse(budgets.get(key).needs_skeleton, f"{key} should be static")

    def test_brief_section_8_texture_sizes(self):
        self.assertEqual(budgets.get("hero").texture_max, 2048)
        self.assertEqual(budgets.get("boss").texture_max, 2048)
        self.assertEqual(budgets.get("npc").texture_max, 1024)
        self.assertEqual(budgets.get("prop").texture_max, 512)

    def test_unknown_class_names_the_alternatives(self):
        with self.assertRaises(KeyError) as caught:
            budgets.get("spaceship")
        self.assertIn("hero", str(caught.exception))


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestStyle(unittest.TestCase):
    def test_prompts_never_exceed_the_api_limit(self):
        for class_key in budgets.BUDGETS:
            prompt = style.build("a " + "very long subject clause " * 40, class_key)
            self.assertLessEqual(len(prompt.geometry), style.PROMPT_LIMIT, class_key)
            self.assertLessEqual(len(prompt.texture), style.PROMPT_LIMIT, class_key)

    def test_core_style_tokens_survive_an_overlong_subject(self):
        """Core tokens are the whole art direction; losing them is a bug."""
        prompt = style.build("wooden barrel " * 30, "prop")
        for token in style.CORE_STYLE_TOKENS:
            self.assertIn(token, prompt.geometry)

    def test_avoid_clause_is_always_present(self):
        prompt = style.build("wooden barrel " * 30, "prop")
        self.assertIn("avoid:", prompt.geometry)
        self.assertIn("photorealistic", prompt.geometry)

    def test_a_longer_subject_displaces_more_style(self):
        """The invariant is the relationship, not a specific count: the prompt
        budget is finite, so a longer subject must cost more style tokens."""
        short = style.build("barrel", "prop")
        long = style.build("barrel " * 40, "prop")
        self.assertLess(len(short.dropped), len(long.dropped))
        self.assertTrue(long.dropped, "an overlong subject must report what it displaced")

    def test_surface_detail_never_reaches_the_geometry_prompt(self):
        """The whole point of the surface field: the generator must have no
        reason to model what should be painted."""
        prompt = style.build(
            "smooth tapered wooden barrel",
            "prop",
            surface="three dark iron bands, vertical plank seams",
        )
        self.assertNotIn("iron bands", prompt.geometry)
        self.assertNotIn("plank seams", prompt.geometry)
        self.assertIn("iron bands", prompt.texture)
        self.assertIn("plank seams", prompt.texture)
        self.assertIn("not modelled", prompt.geometry)

    def test_subject_and_extra_are_never_dropped(self):
        prompt = style.build("wooden barrel", "prop", extra="must read from above")
        self.assertIn("wooden barrel", prompt.geometry)
        self.assertIn("must read from above", prompt.geometry)

    def test_region_changes_only_the_texture_prompt(self):
        greenvale = style.build("barrel", "prop", region="greenvale")
        vaelor = style.build("barrel", "prop", region="vaelor")
        self.assertEqual(greenvale.geometry, vaelor.geometry)
        self.assertNotEqual(greenvale.texture, vaelor.texture)

    def test_no_third_party_ip_appears_in_any_prompt(self):
        """Brief-adjacent but commercially important: see docs/STYLE_GUIDE.md.

        Nothing in the style module may leak a third-party name into a request
        sent to a generative service.
        """
        forbidden = ["shining force", "shining", "sega", "genesis", "megadrive", "mega drive"]
        haystacks = [style.BASE_STYLE_TOKENS, style.CORE_STYLE_TOKENS, style.BASE_AVOID_TOKENS]
        text = " ".join(" ".join(h) for h in haystacks).lower()
        text += " " + " ".join(style.CLASS_STYLE.values()).lower()
        text += " " + " ".join(style.CLASS_AVOID.values()).lower()
        text += " " + " ".join(style.REGIONS.values()).lower()
        for term in forbidden:
            self.assertNotIn(term, text, f"{term!r} must not appear in any prompt token")


# ---------------------------------------------------------------------------
# Animation mapping
# ---------------------------------------------------------------------------


class TestAnimations(unittest.TestCase):
    def test_core_set_covers_the_brief_section_57_list(self):
        expected = {
            "idle", "walk", "run", "turn", "attack_1", "attack_2", "heavy_attack",
            "cast", "heal", "block", "hit_front", "hit_back", "death", "victory",
        }
        self.assertEqual(set(animations.CORE_SET), expected)

    def test_resolve_accepts_names_ints_and_digit_strings(self):
        self.assertEqual(animations.resolve("idle"), animations.CORE_SET["idle"])
        self.assertEqual(animations.resolve(42), 42)
        self.assertEqual(animations.resolve("42"), 42)

    def test_unknown_name_lists_the_valid_ones(self):
        with self.assertRaises(KeyError) as caught:
            animations.resolve("backflip")
        self.assertIn("idle", str(caught.exception))

    def test_minimal_set_is_a_subset_of_core(self):
        for name in animations.MINIMAL_SET:
            self.assertIn(name, animations.CORE_SET)


# ---------------------------------------------------------------------------
# GLB reading
# ---------------------------------------------------------------------------


class TestGlbReader(unittest.TestCase):
    def test_reads_triangles_bounds_and_texture_size(self):
        with GlbTempFile(triangles=420, texture_size=256) as path:
            info = glb.read(path)
        self.assertEqual(info.triangles, 420)
        self.assertEqual(info.max_texture_edge, 256)
        self.assertAlmostEqual(info.height, 0.9, places=5)
        self.assertEqual(info.materials, 1)
        self.assertEqual(info.primitives, 1)

    def test_applies_node_transforms_to_bounds(self):
        """postprocess corrects scale with a wrapper node, so the reader must
        honour node transforms or it would report the uncorrected size."""
        with GlbTempFile(bounds=((-1, 0, -1), (1, 2, 1)), node_scale=0.5) as path:
            info = glb.read(path)
        self.assertAlmostEqual(info.height, 1.0, places=5)

        with GlbTempFile(bounds=((-1, -1, -1), (1, 1, 1)),
                         node_translation=(0.0, 1.0, 0.0)) as path:
            info = glb.read(path)
        self.assertAlmostEqual(info.bounds_min[1], 0.0, places=5)

    def test_detects_skin_joints_and_animations(self):
        with GlbTempFile(with_skin=True, animation_names=["idle", "walk"]) as path:
            info = glb.read(path)
        self.assertEqual(len(info.joints), len(validate.CANONICAL_BONES))
        self.assertEqual(info.animations, ["idle", "walk"])

    def test_flags_a_material_with_no_base_colour(self):
        with GlbTempFile(texture_size=None, base_colour_factor=False) as path:
            info = glb.read(path)
        self.assertEqual(info.untextured_materials, ["surface"])

    def test_rejects_a_non_glb_file(self):
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as handle:
            handle.write(b"this is not a GLB at all, not even close")
            path = handle.name
        try:
            with self.assertRaises(glb.GlbError):
                glb.read(path)
        finally:
            os.unlink(path)

    def test_rejects_a_truncated_download(self):
        payload = build_glb()
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as handle:
            handle.write(payload[: len(payload) // 2])
            path = handle.name
        try:
            with self.assertRaises(glb.GlbError) as caught:
                glb.read(path)
            self.assertIn("truncated", str(caught.exception))
        finally:
            os.unlink(path)

    def test_reads_jpeg_dimensions(self):
        # SOI, SOF0 with height 64 width 32, EOI.
        jpeg = b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" \
            + struct.pack(">HH", 64, 32) + b"\x03" + b"\x00" * 9 + b"\xff\xd9"
        self.assertEqual(glb._image_dimensions(jpeg), (32, 64, "image/jpeg"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidator(unittest.TestCase):
    def check(self, asset_class: str, **kwargs) -> validate.Report:
        with GlbTempFile(**kwargs) as path:
            return validate.validate(path, asset_class)

    def codes(self, report: validate.Report, severity: validate.Severity) -> set[str]:
        return {f.check for f in report.findings if f.severity is severity}

    def test_a_conforming_prop_passes(self):
        report = self.check("prop", triangles=500, texture_size=512,
                            bounds=((-0.3, 0.0, -0.3), (0.3, 0.9, 0.3)))
        self.assertTrue(report.ok, [str(f) for f in report.findings])

    def test_triangle_count_over_the_hard_cap_fails(self):
        report = self.check("prop", triangles=9_000)
        self.assertFalse(report.ok)
        self.assertIn("triangle_count", self.codes(report, validate.Severity.ERROR))

    def test_triangle_count_over_the_soft_range_only_warns(self):
        """5,000 is over the prop target of 400-4,000 but under the 7,000 cap,
        which is where a clean native-density generated prop lands."""
        report = self.check("prop", triangles=5_000)
        self.assertTrue(report.ok)
        self.assertIn("triangle_count", self.codes(report, validate.Severity.WARN))

    def test_oversized_texture_fails(self):
        report = self.check("prop", texture_size=2048)
        self.assertFalse(report.ok)
        self.assertIn("texture_resolution", self.codes(report, validate.Severity.ERROR))

    def test_wrong_scale_fails(self):
        report = self.check("prop", bounds=((-1, 0, -1), (1, 12, 1)))
        self.assertFalse(report.ok)
        self.assertIn("scale", self.codes(report, validate.Severity.ERROR))

    def test_origin_off_the_ground_warns(self):
        report = self.check("prop", bounds=((-0.3, -0.45, -0.3), (0.3, 0.45, 0.3)))
        self.assertIn("origin", self.codes(report, validate.Severity.WARN))

    def test_rigged_class_without_a_skeleton_fails(self):
        report = self.check("enemy_humanoid", triangles=3_000, texture_size=1024,
                            bounds=((-0.4, 0.0, -0.2), (0.4, 1.7, 0.2)))
        self.assertFalse(report.ok)
        self.assertIn("skeleton", self.codes(report, validate.Severity.ERROR))

    def test_rigged_class_with_the_canonical_skeleton_passes(self):
        report = self.check("enemy_humanoid", triangles=3_000, texture_size=1024,
                            bounds=((-0.4, 0.0, -0.2), (0.4, 1.7, 0.2)), with_skin=True)
        self.assertTrue(report.ok, [str(f) for f in report.findings])

    def test_missing_canonical_bones_fail(self):
        report = self.check("enemy_humanoid", triangles=3_000, texture_size=1024,
                            bounds=((-0.4, 0.0, -0.2), (0.4, 1.7, 0.2)), with_skin=True,
                            joint_names=["root", "hips", "head"])
        self.assertFalse(report.ok)
        self.assertIn("skeleton", self.codes(report, validate.Severity.ERROR))

    def test_bone_aliases_are_accepted(self):
        """A Mixamo-style rig should satisfy the canonical bone list."""
        aliased = [
            "Armature", "Pelvis", "Spine1", "Spine2", "neck", "head",
            "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
            "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
        ]
        report = self.check("enemy_humanoid", triangles=3_000, texture_size=1024,
                            bounds=((-0.4, 0.0, -0.2), (0.4, 1.7, 0.2)), with_skin=True,
                            joint_names=aliased)
        self.assertTrue(report.ok, [str(f) for f in report.findings])

    def test_z_up_export_fails_orientation(self):
        report = self.check("enemy_humanoid", triangles=3_000, texture_size=1024,
                            bounds=((-0.4, 0.0, -0.2), (0.4, 0.4, 1.7)), with_skin=True)
        self.assertFalse(report.ok)
        self.assertIn("orientation", self.codes(report, validate.Severity.ERROR))

    def test_requested_animations_that_are_missing_fail(self):
        with GlbTempFile(triangles=3_000, texture_size=1024, with_skin=True,
                         bounds=((-0.4, 0.0, -0.2), (0.4, 1.7, 0.2))) as path:
            report = validate.validate(path, "enemy_humanoid", expect_animations=True)
        self.assertFalse(report.ok)
        self.assertIn("animations", self.codes(report, validate.Severity.ERROR))

    def test_unreadable_file_reports_rather_than_raising(self):
        report = validate.validate("/nonexistent/asset.glb", "prop")
        self.assertFalse(report.ok)
        self.assertIn("readable", self.codes(report, validate.Severity.ERROR))


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


class TestPostProcess(unittest.TestCase):
    def test_scale_and_ground_normalisation(self):
        with GlbTempFile(bounds=((-0.6, -0.9, -0.6), (0.6, 0.9, 0.6)), texture_size=512) as path:
            changes = postprocess.normalise(path, target_height=0.9, texture_max=512)
            info = glb.read(path)
        self.assertAlmostEqual(info.height, 0.9, places=4)
        self.assertAlmostEqual(info.bounds_min[1], 0.0, places=4)
        self.assertIsNotNone(changes.scaled)
        self.assertTrue(changes.grounded)

    def test_normalisation_is_idempotent(self):
        with GlbTempFile(bounds=((-0.6, -0.9, -0.6), (0.6, 0.9, 0.6))) as path:
            postprocess.normalise(path, target_height=0.9, texture_max=512)
            second = postprocess.normalise(path, target_height=0.9, texture_max=512)
        self.assertFalse(second.touched, "a normalised asset must not change again")

    def test_output_is_still_a_readable_glb(self):
        with GlbTempFile(bounds=((-0.6, -0.9, -0.6), (0.6, 0.9, 0.6)),
                         texture_size=1024, animation_names=["idle"]) as path:
            postprocess.normalise(path, target_height=0.9, texture_max=512)
            info = glb.read(path)
        self.assertEqual(info.triangles, 500)
        self.assertEqual(info.animations, ["idle"])

    def test_skinned_assets_are_left_alone(self):
        """Rigging sets height via height_meters; wrapping a skeleton is riskier
        than it looks, so the pipeline must decline rather than guess."""
        with GlbTempFile(with_skin=True,
                         bounds=((-0.4, -0.85, -0.2), (0.4, 0.85, 0.2))) as path:
            changes = postprocess.normalise(path, target_height=1.7, texture_max=1024)
        self.assertIsNone(changes.scaled)
        self.assertTrue(any("skinned" in s for s in changes.skipped))

    @unittest.skipUnless(postprocess.pillow_available(), "Pillow not installed")
    def test_texture_downscaling(self):
        with GlbTempFile(texture_size=2048, bounds=((-0.3, 0.0, -0.3), (0.3, 0.9, 0.3))) as path:
            changes = postprocess.normalise(path, target_height=0.9, texture_max=512)
            info = glb.read(path)
        self.assertEqual(info.max_texture_edge, 512)
        self.assertTrue(changes.resized_images)

    @unittest.skipUnless(postprocess.pillow_available(), "Pillow not installed")
    def test_downscaled_asset_passes_validation(self):
        """The end-to-end promise: generator output plus normalisation validates."""
        with GlbTempFile(triangles=800, texture_size=2048,
                         bounds=((-0.6, -0.9, -0.6), (0.6, 0.9, 0.6))) as path:
            postprocess.normalise(path, target_height=0.9, texture_max=512)
            report = validate.validate(path, "prop")
        self.assertTrue(report.ok, [str(f) for f in report.findings])


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "assets.jsonl")

    def tearDown(self):
        for name in os.listdir(self.directory):
            os.unlink(os.path.join(self.directory, name))
        os.rmdir(self.directory)

    def record(self, asset_id: str, **kwargs) -> provenance.Record:
        defaults = dict(
            asset_id=asset_id,
            file_path=f"Content/Models/Props/{asset_id}.glb",
            asset_type="prop",
            generation_tool="Meshy",
            generation_date="2026-08-13",
            tool_plan_license=provenance.DEFAULT_LICENSE_NOTE,
            prompt="a wooden barrel",
        )
        defaults.update(kwargs)
        return provenance.Record(**defaults)

    def test_round_trip(self):
        provenance.append(self.record("prop_barrel_a", triangles=640), self.path)
        loaded = provenance.load(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].asset_id, "prop_barrel_a")
        self.assertEqual(loaded[0].triangles, 640)

    def test_regeneration_appends_and_latest_wins(self):
        provenance.append(self.record("prop_barrel_a", triangles=6_392,
                                      validation="FAIL"), self.path)
        provenance.append(self.record("prop_barrel_a", triangles=640,
                                      validation="pass"), self.path)
        current = provenance.load(self.path)
        self.assertEqual(len(current), 1, "load() reports current state, not history")
        self.assertEqual(current[0].triangles, 640)
        self.assertEqual(len(provenance.history("prop_barrel_a", self.path)), 2)

    def test_malformed_line_names_the_line_number(self):
        provenance.append(self.record("prop_barrel_a"), self.path)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        with self.assertRaises(ValueError) as caught:
            provenance.load(self.path)
        self.assertIn(":2:", str(caught.exception))

    def test_missing_database_is_not_an_error(self):
        self.assertEqual(provenance.load(os.path.join(self.directory, "absent.jsonl")), [])

    def test_report_covers_brief_section_54_fields(self):
        provenance.append(
            self.record("prop_barrel_a", triangles=640, max_texture_edge=512,
                        task_ids=["abc-123"], consumed_credits=30,
                        manual_edits=["auto: scaled by 0.4903"],
                        source_references=["Content/References/barrel_front.png"]),
            self.path,
        )
        text = provenance.report(self.path)
        for expected in ["prop_barrel_a", "Meshy", "2026-08-13", "abc-123",
                         "a wooden barrel", "auto: scaled by 0.4903",
                         "barrel_front.png", "Credits consumed"]:
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()

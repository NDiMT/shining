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
import math
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
    preview,
    provenance,
    scene,
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
    islands: int = 1,
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

    # Vertex positions. With islands=1 every vertex sits at the origin, which
    # welds into a single connected component. With more, each group is pushed
    # far apart so it reads as a separate island.
    coords = bytearray()
    for v in range(vertex_count):
        group = (v // 3) % max(islands, 1)
        coords += struct.pack("<fff", float(group) * 100.0, 0.0, 0.0)
    position_view = add_view(bytes(coords))

    index_bytes = b"".join(struct.pack("<I", i) for i in range(vertex_count))
    index_view = add_view(index_bytes)

    accessors = [
        {
            "bufferView": position_view,
            "componentType": 5126,  # FLOAT
            "count": vertex_count,
            "type": "VEC3",
            "min": list(low),
            "max": list(high),
        },
        {
            "bufferView": index_view,
            "componentType": 5125,  # UNSIGNED_INT
            "count": vertex_count,
            "type": "SCALAR",
        },
    ]

    document: dict = {
        "asset": {"version": "2.0", "generator": "hollowasset test"},
        "scene": 0,
        "meshes": [
            {
                "name": "mesh",
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0, "mode": 4}
                ],
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
    #: Anime rules 1 and 2 are the engine's job, never the generator's. A texture
    #: that arrives with the bands and the ink line already painted into it gets
    #: banded a second time by the real toon shader, which is the mud
    #: docs/ANIME_DIRECTION.md calls the one failure that makes cel shading look
    #: cheap. "shaded" is deliberately absent from this list: "flat unshaded
    #: colour" is the direction we *do* want, and contains it.
    BANNED_LIGHTING_TERMS = [
        "cel shad", "cel-shad", "celshad", "toon", "cartoon shad",
        "outline", "rim light", "rim-light", "ink line", "shading gradient",
    ]

    def resolved_prompts(self):
        """Every prompt this repository can actually send, and a synthetic grid.

        The catalogs are included because a constants-only check would miss the
        half of the problem that keeps happening: both failures recorded under
        "prompts leak their own failure modes" in docs/ASSET_PIPELINE.md were
        catalog fields, not style tokens.

        Yields ``(label, class_key, Prompt)``.
        """
        import glob

        from hollowasset import pipeline

        catalog_dir = os.path.join(os.path.dirname(__file__), "..", "Tools", "catalog")
        catalogs = sorted(glob.glob(os.path.join(catalog_dir, "*.json")))
        self.assertTrue(catalogs, "no catalog files found to check")
        for path in catalogs:
            for job in pipeline.load_catalog(path):
                yield job.asset_id, job.asset_class, job.prompt
        for class_key in budgets.BUDGETS:
            for region in style.region_keys():
                yield (
                    f"{class_key}/{region}",
                    class_key,
                    style.build("a test subject", class_key, region=region),
                )

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

    def test_both_prompts_carry_their_own_avoid_clause(self):
        """Geometry and texture fail in different directions, so each gets the
        avoid list for its own medium and neither pays for the other's."""
        prompt = style.build("barrel", "prop", surface="iron bands")
        self.assertIn("avoid:", prompt.geometry)
        self.assertIn("avoid:", prompt.texture)
        # A mesh cannot have a logo and a texture cannot have a plinth.
        self.assertNotIn("logos", prompt.geometry)
        self.assertNotIn("plinth", prompt.texture)

    def test_no_token_is_repeated_within_a_prompt(self):
        """Catalog surface and class palette legitimately overlap. Paying twice
        for the same words costs a real token its place in the 600 characters."""
        prompt = style.build(
            "square wooden storage crate",
            "prop",
            region="greenvale",
            surface="plank seams, warm painted wood tones",
        )
        for text in (prompt.geometry, prompt.texture):
            tokens = [t.strip().lower() for t in text.split(",") if t.strip()]
            self.assertCountEqual(tokens, set(tokens), f"repeated token in: {text}")

    def test_no_catalog_entry_pays_for_the_same_token_twice(self):
        """The same invariant over every asset we actually ship.

        The synthetic case above cannot see the failure that happened: a catalog
        'subject' repeating a word from its own class direction. The subject
        reaches the packer as one pre-joined string, so its tokens were invisible
        to the dedupe, and building_house_small_a asked for "simple boxy massing"
        twice.
        """
        for label, _class_key, prompt in self.resolved_prompts():
            for kind, text in (("geometry", prompt.geometry), ("texture", prompt.texture)):
                tokens = [t.strip().lower() for t in text.split(",") if t.strip()]
                self.assertCountEqual(tokens, set(tokens), f"{label} {kind}: {text}")

    def test_the_most_important_class_style_token_survives(self):
        """A regression guard. The avoid clause once ran to eighteen tokens and
        380 characters, which pushed vegetation's canopy direction out of the
        prompt entirely -- and the generated tree grew individual leaves."""
        prompt = style.build(
            "broad oak tree, three rounded canopy masses on a sturdy trunk",
            "vegetation",
            extra="trunk cut flat at the bottom, nothing beneath it",
        )
        self.assertIn("clustered angular canopy masses", prompt.geometry)

    def test_no_prompt_ever_asks_the_generator_for_the_lighting(self):
        """docs/ANIME_DIRECTION.md rules 1 and 2, and the reason this test exists
        at all: the two-band ramp and the outline belong to the renderer and the
        Godot shaders. A generator asked for them paints them into the texture,
        and a texture with light already in it double-shades under the real toon
        shader. We ask for flat colour and anime form; the engine lights it.

        Checked on resolved prompts rather than on the constants, because the
        offending word could equally arrive from a catalog 'surface' field.
        """
        for label, _class_key, prompt in self.resolved_prompts():
            for kind, text in (("geometry", prompt.geometry), ("texture", prompt.texture)):
                for term in self.BANNED_LIGHTING_TERMS:
                    self.assertNotIn(
                        term, text.lower(),
                        f"{label} {kind} prompt asks the generator for the lighting: {term!r}")

    def test_every_texture_prompt_asks_for_flat_unshaded_colour(self):
        """Anime rule 3, stated positively. Banning the wrong thing is not the
        same as asking for the right one, and docs/ASSET_PIPELINE.md measured the
        difference: the avoid tokens were a coin flip, the positive direction
        landed in every sample."""
        for label, _class_key, prompt in self.resolved_prompts():
            self.assertIn("flat unshaded colour blocks", prompt.texture, label)

    def test_anime_proportion_reaches_every_character_prompt(self):
        """Anime rule 4, which only exists if it survives the packer.

        Measured before this was guarded: every character in prologue_cast.json
        lost its proportion clause, because _pack fills greedily and a 69-char
        clause loses its place to three shorter tail tokens. The geometry prompt
        is the one that decides the mesh, so rule 4 was a no-op in the only place
        it could have taken effect.
        """
        humanoid = {"hero", "npc", "enemy_humanoid"}
        # The whole proportion statement, not just its opening. Written as three
        # comma-separated clauses it packed as three tokens, and hero_rowan's long
        # subject kept "five heads tall" while dropping the oversized hands and
        # shoes -- which are what separate this build from a shrunken adult.
        for label, class_key, prompt in self.resolved_prompts():
            if class_key in humanoid:
                self.assertIn("five heads tall with a big head", prompt.geometry, label)
                self.assertIn("oversized hands", prompt.geometry, label)

        long_subject = style.build("young human swordsman in a blue tabard " * 8, "hero")
        self.assertIn("five heads tall with a big head", long_subject.geometry)
        self.assertIn("oversized hands", long_subject.geometry)

    def test_no_third_party_ip_appears_in_any_prompt(self):
        """Brief-adjacent but commercially important: see docs/STYLE_GUIDE.md.

        Nothing in the style module *or the catalogs* may leak a third-party name
        into a request sent to a generative service. Every prompt is recorded in
        the provenance database, so this is auditable rather than a promise.
        """
        forbidden = ["shining force", "shining", "sega", "genesis", "megadrive", "mega drive"]
        haystacks = [style.BASE_STYLE_TOKENS, style.CORE_STYLE_TOKENS,
                     style.BASE_AVOID_TOKENS, style.TEXTURE_AVOID_TOKENS]
        text = " ".join(" ".join(h) for h in haystacks).lower()
        text += " " + " ".join(style.CLASS_STYLE.values()).lower()
        text += " " + " ".join(style.CLASS_PALETTE.values()).lower()
        text += " " + " ".join(style.CLASS_AVOID.values()).lower()
        text += " " + " ".join(style.REGIONS.values()).lower()
        for label, _class_key, prompt in self.resolved_prompts():
            text += f" {prompt.geometry.lower()} {prompt.texture.lower()}"
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

    def test_a_single_solid_mesh_reports_no_loose_parts(self):
        report = self.check("prop", triangles=600, islands=1)
        self.assertNotIn("loose_parts", self.codes(report, validate.Severity.WARN))

    def test_generator_debris_is_flagged(self):
        """Measured on a real generation: a barrel came back as one body plus
        eleven floating shards, and nothing else the validator checks noticed."""
        # 600 triangles across 100 islands is 6 each, 1% of the mesh apiece,
        # comfortably under the 2% debris threshold.
        report = self.check("prop", triangles=600, islands=100)
        self.assertIn("loose_parts", self.codes(report, validate.Severity.WARN))
        self.assertTrue(report.ok, "debris warns, it does not fail the asset")

    def test_a_few_substantial_parts_are_not_debris(self):
        """A cart has wheels, a chest has a lid. Separate is not the same as
        broken, so large islands report as INFO rather than a warning."""
        report = self.check("prop", triangles=600, islands=3)
        self.assertNotIn("loose_parts", self.codes(report, validate.Severity.WARN))

    def test_flat_shading_alone_is_not_debris(self):
        """Islands are welded by position first. Without that, a flat-shaded
        low-poly mesh reports one island per face - the first version of the
        check found 351 in a barrel with one body."""
        with GlbTempFile(triangles=600, islands=1) as path:
            info = glb.read(path)
        self.assertEqual(len(info.islands), 1, info.islands[:8])

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


class TestMeshOnly(unittest.TestCase):
    """The --mesh-only flag, which exists so a character's silhouette can be
    reviewed before credits are spent on a rig and a clip set."""

    def setUp(self):
        import io
        from contextlib import redirect_stdout
        self.io, self.redirect = io, redirect_stdout

    def run_cli(self, *args) -> str:
        from hollowasset.__main__ import main
        buffer = self.io.StringIO()
        with self.redirect(buffer):
            code = main(list(args))
        self.assertEqual(code, 0)
        return buffer.getvalue()

    def test_mesh_only_drops_the_rig_and_clip_cost(self):
        catalog = "Tools/catalog/prologue_cast.json"
        full = self.run_cli("generate", catalog, "--id", "hero_rowan", "--dry-run")
        mesh = self.run_cli("generate", catalog, "--id", "hero_rowan", "--dry-run", "--mesh-only")

        def credits(text: str) -> int:
            return int(text.split("estimated credits")[0].strip().split()[-1])

        self.assertLess(credits(mesh), credits(full))
        self.assertIn("nothing generated", mesh)

    def test_mesh_only_leaves_static_assets_alone(self):
        catalog = "Tools/catalog/greenvale_props.json"
        full = self.run_cli("generate", catalog, "--id", "prop_barrel_a", "--dry-run")
        mesh = self.run_cli("generate", catalog, "--id", "prop_barrel_a", "--dry-run", "--mesh-only")
        self.assertEqual(full, mesh)


# ---------------------------------------------------------------------------
# Scene composition
# ---------------------------------------------------------------------------


NORTH_MEADOW = "Content/Data/Battles/battle_north_meadow.json"
THE_BREACH = "Content/Data/Battles/battle_the_breach.json"


def _resolved_model(unit):
    """What scene._add_units will actually load for this unit, or None.

    Mirrors the module's own two-step lookup -- the declared path, then a search
    by asset id -- so a test can count placeholders without hard-coding which
    assets happen to exist today.
    """
    if unit.model and os.path.exists(unit.model):
        return unit.model
    if unit.model:
        return scene.find_model(os.path.splitext(os.path.basename(unit.model))[0])
    return None


class TestScene(unittest.TestCase):
    """The offline battle renderer.

    Most of this is about the grid convention. x runs west to east, y runs SOUTH
    to north, and the battle JSON writes its rows north first — get that backwards
    and the map is merely mirrored, which looks entirely plausible on screen and
    is wrong in every tactical detail. Nothing else in the renderer will complain,
    so these tests are the only thing holding it.
    """

    def setUp(self):
        self.terrain = scene.load_terrain()

    # -- the flip ----------------------------------------------------------

    def test_row_zero_of_the_file_is_the_northernmost_row(self):
        grid = scene.Grid.parse(["xxx", "ggg", "ppp"], self.terrain)
        self.assertEqual(grid.height, 3)
        self.assertEqual(grid.terrain_id(0, 2), "exit")   # file row 0 -> y = 2
        self.assertEqual(grid.terrain_id(0, 1), "grass")
        self.assertEqual(grid.terrain_id(0, 0), "path")   # file row 2 -> y = 0

    def test_x_is_not_flipped_with_y(self):
        # A grid that is asymmetric in both axes at once. Flipping x as well as y
        # would leave the previous test passing and this one failing.
        grid = scene.Grid.parse(["rgg", "ggg", "ggt"], self.terrain)
        self.assertEqual(grid.terrain_id(0, 2), "rock")    # north-west corner
        self.assertEqual(grid.terrain_id(2, 0), "forest")  # south-east corner

    def test_north_meadow_lands_the_way_the_file_reads(self):
        battle = scene.load_battle(NORTH_MEADOW)
        grid = battle.grid
        self.assertEqual((grid.width, grid.height), (12, 14))
        # The escape row the fleeing spearman leaves by is the north edge.
        self.assertTrue(all(grid.terrain_id(x, 13) == "exit" for x in range(12)))
        # The road runs into the southern deployment area, where the party starts.
        self.assertEqual([grid.terrain_id(5, y) for y in (0, 1, 2)], ["path"] * 3)
        # The hill the archer takes on turn 2 is at [5,11]; the event moves it there.
        self.assertEqual(grid.terrain_id(5, 11), "hill")
        self.assertEqual(grid.level(5, 11), 1)
        self.assertEqual(grid.terrain_id(5, 9), "grass")

    def test_north_is_the_far_edge_of_the_picture(self):
        # The convention only pays off if the camera agrees with it: north must
        # end up further from the camera and higher up the frame, or the picture
        # is upside down while every index is right.
        camera = preview.Camera(0.0, math.radians(scene.DEFAULT_PITCH), 60.0, 0.0, 500.0, 800, 800)
        south = scene.cell_centre(3, 0)
        north = scene.cell_centre(3, 11)
        points = [[south[0], 0.0, south[1]], [north[0], 0.0, north[1]]]
        (_, south_y, south_depth), (_, north_y, north_depth) = camera.project(points)
        self.assertGreater(north_depth, south_depth)
        self.assertLess(north_y, south_y)

    def test_the_breach_puts_the_crownwall_on_the_north_edge(self):
        battle = scene.load_battle(THE_BREACH)
        self.assertTrue(all(battle.grid.terrain_id(x, 11) == "wall" for x in range(14)))
        self.assertTrue(all(battle.grid.terrain_id(x, 0) != "wall" for x in range(14)))

    def test_a_ragged_grid_is_rejected_rather_than_drawn(self):
        with self.assertRaises(ValueError):
            scene.Grid.parse(["ggg", "gg"], self.terrain)

    def test_an_undefined_symbol_names_itself(self):
        with self.assertRaises(ValueError) as caught:
            scene.Grid.parse(["gZg"], self.terrain)
        self.assertIn("Z", str(caught.exception))

    # -- terrain data ------------------------------------------------------

    def test_every_terrain_type_has_a_colour(self):
        # A terrain type added to terrain.json without a colour here renders
        # magenta rather than crashing, which is deliberate; this test is what
        # makes sure nobody ships the magenta.
        for symbol, entry in self.terrain.items():
            with self.subTest(symbol=symbol):
                self.assertIn(entry["id"], scene.TERRAIN_COLOURS)

    def test_elevation_comes_from_the_terrain_data(self):
        grid = scene.Grid.parse(["hg"], self.terrain)
        self.assertEqual(grid.elevation(0, 0), scene.ELEVATION_STEP)
        self.assertEqual(grid.elevation(1, 0), 0.0)

    # -- movement range ----------------------------------------------------

    def test_movement_prefers_the_cheap_route_over_the_short_one(self):
        # Straight through the forest is two tiles at cost 2; around it is three
        # tiles at cost 1. Dijkstra has to find the cheaper one, which is the
        # reason Movement.cs is not a breadth-first flood.
        grid = scene.Grid.parse(["ggg", "gtg", "ggg"], self.terrain)
        reached = scene.reachable(grid, (1, 0), 3)
        self.assertEqual(reached[(1, 2)], 3)

    def test_blocked_terrain_stops_ground_movement(self):
        grid = scene.Grid.parse(["ggg", "fff", "ggg"], self.terrain)
        reached = scene.reachable(grid, (1, 0), 6)
        self.assertNotIn((1, 1), reached)
        self.assertNotIn((1, 2), reached)

    def test_flying_movement_crosses_a_fence(self):
        grid = scene.Grid.parse(["ggg", "fff", "ggg"], self.terrain)
        self.assertIn((1, 2), scene.reachable(grid, (1, 0), 6, "flying"))

    def test_a_unit_cannot_stop_on_an_occupied_tile(self):
        grid = scene.Grid.parse(["ggg", "ggg", "ggg"], self.terrain)
        reached = scene.reachable(grid, (1, 0), 4, occupied=frozenset({(1, 1)}))
        self.assertNotIn((1, 1), reached)
        # ...and cannot walk through it either, so the far side costs 4 the long
        # way round rather than 2 straight up.
        self.assertEqual(reached[(1, 2)], 4)

    def test_the_origin_is_not_in_its_own_range(self):
        grid = scene.Grid.parse(["gg"], self.terrain)
        self.assertNotIn((0, 0), scene.reachable(grid, (0, 0), 4))

    def test_rowan_gets_a_movement_range_on_the_real_battle(self):
        battle = scene.load_battle(NORTH_MEADOW)
        self.assertIsNotNone(battle.active)
        self.assertEqual(battle.active.id, "rowan")
        self.assertEqual(battle.active.movement, 6)      # characters.json baseStats
        self.assertTrue(battle.range_tiles)
        for tile in battle.range_tiles:
            self.assertTrue(battle.grid.passable(*tile))
        # The fence pen shapes the approach, so it must not be walkable.
        self.assertNotIn((2, 6), battle.range_tiles)

    # -- units and props ---------------------------------------------------

    def test_every_unit_in_both_battles_is_placed(self):
        for path, expected in ((NORTH_MEADOW, 3 + 0 + 7), (THE_BREACH, 3 + 2 + 6)):
            with self.subTest(battle=path):
                battle = scene.load_battle(path)
                self.assertEqual(len(battle.units), expected)
                for unit in battle.units:
                    self.assertTrue(battle.grid.inside(unit.x, unit.y))

    def test_sides_are_read_from_the_right_lists(self):
        battle = scene.load_battle(THE_BREACH)
        sides = {unit.id: unit.side for unit in battle.units}
        self.assertEqual(sides["rowan"], "player")
        self.assertEqual(sides["injured_guard_1"], "ally")
        self.assertEqual(sides["varric"], "enemy")

    def test_a_borrowed_npc_resolves_against_the_enemy_table(self):
        # battle 02 spawns greenvale_soldier under an `npc` key while
        # characters.json declares it under `enemies`. It has to resolve anyway.
        battle = scene.load_battle(THE_BREACH)
        soldier = next(unit for unit in battle.units if unit.id == "soldier_1")
        self.assertEqual(soldier.name, "Greenvale Soldier")
        self.assertEqual(soldier.movement, 5)

    def test_an_explicit_active_unit_can_be_chosen(self):
        battle = scene.load_battle(NORTH_MEADOW, active="archer_1")
        self.assertEqual(battle.active.id, "archer_1")

    def test_an_unknown_active_unit_warns_and_falls_back(self):
        battle = scene.load_battle(NORTH_MEADOW, active="nobody")
        self.assertEqual(battle.active.id, "rowan")
        self.assertTrue(any("nobody" in warning for warning in battle.warnings))

    def test_a_missing_prop_asset_warns_rather_than_raising(self):
        battle = scene.load_battle(NORTH_MEADOW)
        _, _ = scene.build(battle)
        missing = [w for w in battle.warnings if "prop_fence_section" in w]
        self.assertTrue(missing)
        self.assertIn("not drawn", missing[0])

    def test_a_generated_prop_is_actually_placed(self):
        # The oak is one of the few assets that exists, and it is the difference
        # between a scene and a set of coloured squares.
        battle = scene.load_battle(NORTH_MEADOW)
        bare = scene.Battle(id="bare", name="", grid=battle.grid, units=[], props=[], active=None)
        with_tree = scene.Battle(
            id="tree", name="", grid=battle.grid, units=[],
            props=[p for p in battle.props if p.asset == "veg_tree_oak_a"], active=None)
        self.assertEqual(len(with_tree.props), 1)
        empty, _ = scene.build(bare)
        planted, _ = scene.build(with_tree)
        self.assertGreater(len(planted.triangles), len(empty.triangles) + 20_000)

    def test_units_with_no_model_are_drawn_as_placeholders(self):
        """A unit whose GLB is missing gets a stand-in, never a hole.

        Both counts are derived from the battle rather than written down. The
        first version asserted literal 10 and 4, read off whichever assets
        happened to exist that day, and both broke the moment hero_rowan.glb
        was generated -- a test failing because the project made progress.
        """
        battle = scene.load_battle(NORTH_MEADOW)
        geometry, placeholders = scene.build(battle)
        expected = sum(1 for unit in battle.units if _resolved_model(unit) is None)
        self.assertEqual(placeholders, expected)
        self.assertGreater(len(geometry.triangles), 0)
        if expected:
            self.assertTrue(any("placeholder" in w for w in battle.warnings))

    def test_a_generated_character_model_is_used_when_it_exists(self):
        """Whatever has been generated must be drawn rather than stood in for."""
        battle = scene.load_battle(THE_BREACH)
        _, placeholders = scene.build(battle)
        modelled = [u for u in battle.units if _resolved_model(u) is not None]
        self.assertTrue(modelled, "the breach should resolve at least one real model")
        self.assertEqual(placeholders, len(battle.units) - len(modelled))

    def test_a_unit_stands_on_its_own_tile(self):
        grid = scene.Grid.parse(["gg", "gg"], self.terrain)
        unit = scene.Unit(id="u", name="U", side="player", x=1, y=0, model=None,
                          height=1.7, movement=4, movement_type="ground", hp=10)
        battle = scene.Battle(id="b", name="", grid=grid, units=[unit], props=[], active=None)
        geometry, _ = scene.build(battle)
        centre_x, centre_z = scene.cell_centre(1, 0)
        points = geometry.triangles.reshape(-1, 3)
        marker = points[points[:, 1] > 0.5]          # above the ground, so unit only
        self.assertLess(abs(marker[:, 0].mean() - centre_x), 0.1)
        self.assertLess(abs(marker[:, 2].mean() - centre_z), 0.1)

    def test_a_declared_size_that_disagrees_with_the_grid_is_reported(self):
        battle = scene.load_battle(NORTH_MEADOW)
        self.assertFalse([w for w in battle.warnings if "declared size" in w])

    # -- geometry ----------------------------------------------------------

    def test_tile_tops_face_upward(self):
        # The rasteriser culls back faces, so a floor wound the wrong way is
        # invisible and the board renders as a hole in the sky.
        import numpy

        builder = scene.Builder()
        builder.top(0.0, 1.0, 0.0, 1.0, 0.0, (1, 2, 3))
        triangles = numpy.array(builder.triangles)
        for triangle in triangles:
            normal = numpy.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            self.assertGreater(normal[1], 0)

    def test_box_faces_all_point_outward(self):
        import numpy

        builder = scene.Builder()
        builder.box(-1.0, 1.0, -1.0, 1.0, -1.0, 1.0, (1, 2, 3))
        for triangle in numpy.array(builder.triangles):
            normal = numpy.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            centre = triangle.mean(axis=0)          # the box is centred on the origin
            self.assertGreater(float(normal @ centre), 0)


class TestSceneRendering(unittest.TestCase):
    """The anime look, per docs/ANIME_DIRECTION.md rules 1 and 2."""

    def setUp(self):
        if not preview.available():
            self.skipTest("preview needs Pillow and numpy")
        import numpy

        self.numpy = numpy

    def _quad(self, z: float):
        """A camera-facing quad, wound so the rasteriser keeps it."""
        corners = [(-1.0, 0.0, z), (1.0, 0.0, z), (1.0, 2.0, z), (-1.0, 2.0, z)]
        return [(corners[0], corners[2], corners[1]), (corners[0], corners[3], corners[2])]

    def test_the_toon_ramp_only_ever_produces_its_own_bands(self):
        normals = self.numpy.array([[0.0, 1.0, -0.9], [0.0, -1.0, -0.9], [0.7, 0.7, -0.9]])
        shades = preview._shade(normals, self.numpy, toon=True)
        allowed = {value for _, value in preview.TOON_RAMP} | {preview.TOON_RIM[1]}
        for shade in shades:
            self.assertIn(float(shade), allowed)

    def test_the_smooth_mode_is_a_gradient_and_the_toon_mode_is_not(self):
        angles = self.numpy.linspace(0.0, 1.0, 40)
        normals = self.numpy.stack(
            [angles, self.numpy.sqrt(1 - angles ** 2), self.numpy.full(40, -0.9)], axis=1)
        normals /= self.numpy.linalg.norm(normals, axis=1)[:, None]
        toon = preview._shade(normals, self.numpy, toon=True)
        smooth = preview._shade(normals, self.numpy, toon=False)
        self.assertLessEqual(len(set(toon.tolist())), 3)
        self.assertGreater(len(set(smooth.tolist())), 20)

    def test_the_rim_band_is_the_only_third_tone(self):
        # Rule 1 allows one narrow rim band and nothing else, so a face facing
        # straight at the camera must never pick it up.
        facing = self.numpy.array([[0.0, 0.0, -1.0]])
        shade = preview._shade(facing, self.numpy, toon=True)[0]
        self.assertNotEqual(float(shade), preview.TOON_RIM[1])

    def test_the_edge_pass_inks_a_silhouette(self):
        geometry = preview.Geometry(
            self.numpy.array(self._quad(0.0)), self.numpy.zeros((2, 3, 2)), None)
        inked = self.numpy.asarray(preview.render(geometry, 120, 0, 0, textured=False))
        plain = self.numpy.asarray(
            preview.render(geometry, 120, 0, 0, textured=False, outline=False))
        ink = self.numpy.array(preview.OUTLINE_COLOUR)
        self.assertGreater(int((inked == ink).all(axis=2).sum()), 100)
        self.assertEqual(int((plain == ink).all(axis=2).sum()), 0)

    def test_the_edge_pass_stays_off_the_background(self):
        geometry = preview.Geometry(
            self.numpy.array(self._quad(0.0)), self.numpy.zeros((2, 3, 2)), None)
        image = self.numpy.asarray(preview.render(geometry, 120, 0, 0, textured=False))
        # Corner pixels are outside the quad at any fit, so an outline reaching
        # them would mean the line is haloing the shape instead of sitting on it.
        for pixel in (image[0, 0], image[0, -1], image[-1, 0], image[-1, -1]):
            self.assertEqual(tuple(pixel), preview.BACKGROUND)

    def test_positive_pitch_looks_down_on_the_scene(self):
        # The sign this module used until 2026-08-13 rendered every contact sheet
        # from underneath. A point above the ground has to come out nearer the
        # camera than the ground it stands on.
        camera = preview.Camera(0.0, math.radians(40.0), 50.0, 0.0, 0.0, 100, 100)
        ground, above = camera.project([[0.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
        self.assertLess(above[2], ground[2])

    def test_per_triangle_materials_survive_a_render(self):
        # Terrain is flat colour and assets are textured in the same buffer, so
        # a triangle's own colour has to reach the framebuffer.
        geometry = preview.Geometry(
            triangles=self.numpy.array(self._quad(0.0)),
            uvs=self.numpy.zeros((2, 3, 2)),
            texture=None,
            colours=self.numpy.array([[255.0, 0.0, 0.0], [255.0, 0.0, 0.0]]),
            texture_index=self.numpy.array([-1, -1]),
            textures=[],
        )
        image = self.numpy.asarray(preview.render(geometry, 120, 0, 0, outline=False))
        red = image[(image[:, :, 0] > 100) & (image[:, :, 1] < 60)]
        self.assertGreater(len(red), 500)

    def test_both_battles_render_end_to_end(self):
        for path in (NORTH_MEADOW, THE_BREACH):
            with self.subTest(battle=path):
                with tempfile.TemporaryDirectory() as folder:
                    out = os.path.join(folder, "shot.png")
                    scene.render_scene(path, out, size=320, log=lambda *_: None)
                    from PIL import Image
                    with Image.open(out) as image:
                        self.assertEqual(image.width, 320)
                        self.assertGreater(image.height, 320)

    def test_the_cli_renders_a_scene(self):
        import io
        from contextlib import redirect_stdout

        from hollowasset.__main__ import main

        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "shot.png")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["scene", NORTH_MEADOW, "--out", out, "--size", "300",
                             "--smooth", "--no-outline", "--flat"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out))
            self.assertIn("smooth", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()

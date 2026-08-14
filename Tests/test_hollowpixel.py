"""Tests for the 2D pipeline.

Pose maths only. It is deliberately the part that can be tested without the API,
which is why it lives apart from the client: a rotation that swings the wrong
limb costs a generation to discover through the API and nothing to discover here.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Tools"))

from hollowpixel import poses  # noqa: E402
from hollowpixel.pixellab import _integral_z, _match_size  # noqa: E402


def rest_skeleton() -> list[dict]:
    """A plain upright figure, in the shape estimate-skeleton returns."""
    layout = {
        "NOSE": (0.50, 0.20), "LEFT EYE": (0.53, 0.18), "RIGHT EYE": (0.47, 0.18),
        "LEFT EAR": (0.56, 0.19), "RIGHT EAR": (0.44, 0.19), "NECK": (0.50, 0.28),
        "LEFT SHOULDER": (0.58, 0.32), "RIGHT SHOULDER": (0.42, 0.32),
        "LEFT ELBOW": (0.62, 0.46), "RIGHT ELBOW": (0.38, 0.46),
        "LEFT ARM": (0.64, 0.60), "RIGHT ARM": (0.36, 0.60),
        "LEFT HIP": (0.55, 0.58), "RIGHT HIP": (0.45, 0.58),
        "LEFT KNEE": (0.56, 0.74), "RIGHT KNEE": (0.44, 0.74),
        "LEFT LEG": (0.57, 0.90), "RIGHT LEG": (0.43, 0.90),
    }
    return [{"label": k, "x": x, "y": y, "z_index": 0.0} for k, (x, y) in layout.items()]


class TestPoseGeometry(unittest.TestCase):
    def setUp(self):
        self.skeleton = rest_skeleton()
        self.rest = {p["label"]: (p["x"], p["y"]) for p in self.skeleton}

    def moved(self, frame):
        return {p["label"] for p in frame
                if abs(p["x"] - self.rest[p["label"]][0]) > 1e-9
                or abs(p["y"] - self.rest[p["label"]][1]) > 1e-9}

    def test_a_chain_rotation_moves_the_chain_and_nothing_else(self):
        """The whole point of naming chains: swinging an arm must not move a leg."""
        pose = poses.Pose("test", rotations={"right_arm": 40.0})
        moved = self.moved(poses.apply(self.skeleton, pose))
        self.assertEqual(moved, {"RIGHT ELBOW", "RIGHT ARM"})

    def test_the_chain_root_is_the_pivot_and_stays_put(self):
        pose = poses.Pose("test", rotations={"left_arm": 90.0})
        after = {p["label"]: (p["x"], p["y"]) for p in poses.apply(self.skeleton, pose)}
        self.assertEqual(after["LEFT SHOULDER"], self.rest["LEFT SHOULDER"])

    def test_rotation_preserves_limb_length(self):
        """A rotation that stretches the arm is a bug the render would hide."""
        pose = poses.Pose("test", rotations={"right_arm": 63.0})
        after = {p["label"]: (p["x"], p["y"]) for p in poses.apply(self.skeleton, pose)}
        for joint in ("RIGHT ELBOW", "RIGHT ARM"):
            before = _distance(self.rest["RIGHT SHOULDER"], self.rest[joint])
            now = _distance(after["RIGHT SHOULDER"], after[joint])
            self.assertAlmostEqual(before, now, places=9, msg=joint)

    def test_positive_degrees_swing_the_arm_forward_on_screen(self):
        """Screen y grows downward, so the sign convention is easy to get
        backwards -- and backwards means every attack in the game swings the
        wrong way."""
        forward = poses.apply(self.skeleton, poses.Pose("f", rotations={"right_arm": 45.0}))
        hand = next(p for p in forward if p["label"] == "RIGHT ARM")
        self.assertGreater(hand["y"], self.rest["RIGHT ARM"][1] - 0.5)
        self.assertGreater(hand["x"], self.rest["RIGHT ARM"][0])

    def test_lean_pivots_the_torso_and_leaves_the_legs(self):
        moved = self.moved(poses.apply(self.skeleton, poses.Pose("lean", lean=20.0)))
        self.assertIn("NECK", moved)
        self.assertIn("RIGHT SHOULDER", moved)
        self.assertNotIn("LEFT KNEE", moved)
        self.assertNotIn("RIGHT LEG", moved)

    def test_offset_moves_everything(self):
        moved = self.moved(poses.apply(self.skeleton, poses.Pose("o", offset=(0.05, 0.0))))
        self.assertEqual(len(moved), len(self.skeleton))

    def test_apply_does_not_modify_its_input(self):
        poses.apply(self.skeleton, poses.DOWN)
        self.assertEqual({p["label"]: (p["x"], p["y"]) for p in self.skeleton}, self.rest)

    def test_every_keypoint_stays_inside_the_frame(self):
        """A keypoint outside 0..1 is not reported by the API; it silently renders
        a limb jammed against the edge."""
        for name in poses.CLIPS:
            for frame in poses.frames_for(self.skeleton, name):
                for point in frame:
                    self.assertGreaterEqual(point["x"], 0.0, f"{name}/{point['label']}")
                    self.assertLessEqual(point["x"], 1.0, f"{name}/{point['label']}")
                    self.assertGreaterEqual(point["y"], 0.0, f"{name}/{point['label']}")
                    self.assertLessEqual(point["y"], 1.0, f"{name}/{point['label']}")


class TestClipLibrary(unittest.TestCase):
    def test_every_clip_is_exactly_three_frames(self):
        """animate-with-skeleton answers 422 for any other count."""
        for name in poses.CLIPS:
            self.assertEqual(len(poses.clip(name)), 3, name)

    def test_the_minimal_set_is_available(self):
        for name in poses.MINIMAL_CLIPS:
            self.assertIn(name, poses.CLIPS)

    def test_poses_only_name_chains_that_exist(self):
        """A misspelt chain is silently ignored at runtime and invisible in the
        output -- the frame just comes back slightly wrong."""
        for name, frames in poses.CLIPS.items():
            for pose in frames:
                for chain in pose.rotations:
                    self.assertIn(chain, poses.CHAINS, f"{name}/{pose.name}")

    def test_chains_only_name_real_keypoint_labels(self):
        for chain, labels in poses.CHAINS.items():
            for label in labels:
                self.assertIn(label, poses.LABELS, chain)

    def test_an_unknown_clip_lists_the_real_ones(self):
        with self.assertRaises(KeyError) as caught:
            poses.clip("backflip")
        self.assertIn("attack", str(caught.exception))


class TestTransportQuirks(unittest.TestCase):
    def test_fractional_depth_is_rounded_for_the_request(self):
        """estimate-skeleton returns -3.5; animate-with-skeleton rejects it."""
        frame = [{"label": "NOSE", "x": 0.5, "y": 0.2, "z_index": -3.5}]
        self.assertEqual(_integral_z(frame)[0]["z_index"], -4)
        self.assertIsInstance(_integral_z(frame)[0]["z_index"], int)

    def test_rounding_does_not_modify_the_caller_s_frame(self):
        frame = [{"label": "NOSE", "x": 0.5, "y": 0.2, "z_index": -3.5}]
        _integral_z(frame)
        self.assertEqual(frame[0]["z_index"], -3.5)

    def test_a_style_image_already_the_right_size_is_returned_unchanged(self):
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        import io
        buffer = io.BytesIO()
        Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(buffer, format="PNG")
        payload = buffer.getvalue()
        self.assertIs(_match_size(payload, 64), payload)

    def test_a_style_image_is_rescaled_without_smoothing(self):
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        import io
        source = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
        source.putpixel((0, 0), (255, 0, 0, 255))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")

        with Image.open(io.BytesIO(_match_size(buffer.getvalue(), 64))) as scaled:
            self.assertEqual(scaled.size, (64, 64))
            # Nearest neighbour keeps the palette exact. Any interpolation would
            # invent colours, and the palette is what a style reference carries.
            self.assertEqual(scaled.convert("RGBA").getpixel((5, 5)), (255, 0, 0, 255))


def _distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


if __name__ == "__main__":
    unittest.main()


class TestGenesisPalette(unittest.TestCase):
    """The 16-colour limit is the constraint that makes a sprite read as SF2.

    Taken from the Shining Force Central disassembly tooling, which states the
    game's own format: 4BPP, 16 indexed colours, transparent at index 0.
    """

    def setUp(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")

    def noisy(self, size=64, colours=200):
        """A sprite with far more colours than a Genesis palette can hold."""
        import io

        from PIL import Image
        image = Image.new("RGBA", (size, size))
        for y in range(size):
            for x in range(size):
                if (x - size // 2) ** 2 + (y - size // 2) ** 2 > (size // 2) ** 2:
                    image.putpixel((x, y), (0, 0, 0, 0))
                else:
                    v = (x * 7 + y * 11) % colours
                    image.putpixel((x, y), (v, (v * 3) % 256, (v * 5) % 256, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_quantising_reaches_the_palette_limit(self):
        from hollowpixel import palette
        result = palette.quantise(self.noisy())
        self.assertGreater(result.colours_before, palette.PALETTE_SIZE)
        self.assertLessEqual(result.colours_after, palette.PALETTE_SIZE - 1)
        self.assertTrue(result.reduced)

    def test_transparency_survives_and_stays_binary(self):
        """Index 0 is transparent, so a pixel is fully in or fully out."""
        import io

        from PIL import Image
        from hollowpixel import palette
        with Image.open(io.BytesIO(palette.quantise(self.noisy()).image)) as out:
            alphas = {p[3] for p in out.convert("RGBA").getdata()}
        self.assertTrue(alphas <= {0, 255}, alphas)
        self.assertIn(0, alphas)

    def test_every_colour_lands_on_the_genesis_ladder(self):
        """Three bits per channel. A colour off the ladder is one the hardware
        could not display, which is what stops this reading as 16-bit era."""
        import io

        from PIL import Image
        from hollowpixel import palette
        with Image.open(io.BytesIO(palette.quantise(self.noisy()).image)) as out:
            channels = {c for p in out.convert("RGBA").getdata() if p[3] > 127 for c in p[:3]}
        self.assertTrue(channels <= set(palette.GENESIS_LEVELS), sorted(channels))

    def test_the_ladder_can_be_turned_off(self):
        from hollowpixel import palette
        result = palette.quantise(self.noisy(), genesis_ladder=False)
        self.assertLessEqual(result.colours_after, palette.PALETTE_SIZE - 1)

    def test_quantising_an_already_small_palette_keeps_it(self):
        import io

        from PIL import Image
        from hollowpixel import palette
        image = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        image.paste((0, 0, 255, 255), (0, 0, 8, 8))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result = palette.quantise(buffer.getvalue())
        self.assertLessEqual(result.colours_after, 2)

    def test_count_colours_ignores_transparent_pixels(self):
        import io

        from PIL import Image
        from hollowpixel import palette
        image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.putpixel((1, 1), (0, 255, 0, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.assertEqual(palette.count_colours(buffer.getvalue()), 2)


class TestTiersMatchTheReference(unittest.TestCase):
    """SF2's own numbers, from the disassembly tooling, and the API sizes that
    can actually be asked for."""

    def test_sizes_are_supported_by_the_api(self):
        from hollowpixel import style
        from hollowpixel.pixellab import SPRITE_SIZES
        for tier in style.TIERS.values():
            self.assertIn(tier.size, SPRITE_SIZES, tier.key)

    def test_the_map_tier_is_the_smaller_one(self):
        from hollowpixel import style
        self.assertLess(style.MAP.size, style.BATTLE.size)

    def test_neither_tier_asks_for_the_detail_the_reference_cannot_hold(self):
        """SF2 is 16 colours and flat blocks. Asking for detailed shading was
        the mistake that made the first batch read as modern pixel art."""
        from hollowpixel import style
        for tier in style.TIERS.values():
            self.assertEqual(tier.shading, "flat shading", tier.key)
            self.assertNotEqual(tier.detail, "highly detailed", tier.key)


class TestSharedPalette(unittest.TestCase):
    """One palette per character, as the ROM format itself implies."""

    def setUp(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")

    def solid(self, colours, size=8):
        import io

        from PIL import Image
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        for i, colour in enumerate(colours):
            for y in range(size):
                image.putpixel((i % size, y), (*colour, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_extract_returns_opaque_colours_most_used_first(self):
        from hollowpixel import palette
        import io

        from PIL import Image
        image = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        image.paste((0, 0, 255, 255), (0, 0, 2, 10))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        colours = palette.extract(buffer.getvalue())
        self.assertEqual(colours[0], (255, 0, 0))
        self.assertIn((0, 0, 255), colours)

    def test_applying_a_palette_uses_only_that_palette(self):
        from hollowpixel import palette
        anchor = [(255, 0, 0), (0, 0, 255)]
        result = palette.apply_palette(self.solid([(250, 10, 10), (10, 10, 250)]), anchor)
        import io

        from PIL import Image
        with Image.open(io.BytesIO(result.image)) as out:
            used = {p[:3] for p in out.convert("RGBA").getdata() if p[3] > 127}
        self.assertTrue(used <= set(anchor), used)

    def test_a_near_colour_maps_to_its_nearest_neighbour(self):
        """The point of the whole exercise: sixteen slightly different browns
        for the same hair across a walk cycle become one brown."""
        from hollowpixel import palette
        import io

        from PIL import Image
        anchor = [(146, 73, 36), (0, 0, 0)]
        result = palette.apply_palette(self.solid([(150, 76, 40)]), anchor)
        with Image.open(io.BytesIO(result.image)) as out:
            used = {p[:3] for p in out.convert("RGBA").getdata() if p[3] > 127}
        self.assertIn((146, 73, 36), used)

    def test_transparency_survives_a_palette_swap(self):
        from hollowpixel import palette
        import io

        from PIL import Image
        result = palette.apply_palette(self.solid([(200, 30, 30)]), [(255, 0, 0)])
        with Image.open(io.BytesIO(result.image)) as out:
            alphas = {p[3] for p in out.convert("RGBA").getdata()}
        self.assertTrue(alphas <= {0, 255}, alphas)
        self.assertIn(0, alphas)

    def test_an_empty_palette_is_refused(self):
        from hollowpixel import palette
        with self.assertRaises(ValueError):
            palette.apply_palette(self.solid([(1, 2, 3)]), [])

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

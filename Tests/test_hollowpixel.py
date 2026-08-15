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

    def test_the_battle_tier_asks_for_real_shading(self):
        """Reversed on measurement. Flat shading plus a 16-colour quantiser was
        the "authentic" answer and it produced washed-out, muddy sprites; the
        generator's own shading beat it on the same subject four ways."""
        from hollowpixel import style
        self.assertIn(style.BATTLE.shading, ("medium shading", "detailed shading"))
        self.assertEqual(style.BATTLE.detail, "highly detailed")


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


class TestReferenceFitting(unittest.TestCase):
    """A concept sheet is tall and a sprite frame is square."""

    def setUp(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")

    def tall(self, width=64, height=256):
        import io

        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGBA", (width, height), (200, 40, 40, 255)).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_a_tall_reference_keeps_its_proportions(self):
        """Stretching one to a square produced a squat hunched figure at every
        seeding strength, and the distortion was mine rather than the model's."""
        import io

        from PIL import Image
        with Image.open(io.BytesIO(_match_size(self.tall(), 128))) as fitted:
            self.assertEqual(fitted.size, (128, 128))
            opaque = [(x, y) for y in range(128) for x in range(128)
                      if fitted.convert("RGBA").getpixel((x, y))[3] > 0]
        width = max(x for x, _ in opaque) - min(x for x, _ in opaque) + 1
        height = max(y for _, y in opaque) - min(y for _, y in opaque) + 1
        self.assertAlmostEqual(width / height, 64 / 256, places=1)

    def test_the_fitted_reference_is_centred(self):
        import io

        from PIL import Image
        with Image.open(io.BytesIO(_match_size(self.tall(), 128))) as fitted:
            rgba = fitted.convert("RGBA")
            columns = [x for x in range(128) if rgba.getpixel((x, 64))[3] > 0]
        self.assertAlmostEqual((min(columns) + max(columns)) / 2, 63.5, delta=1.5)


class TestPalettePaddingCannotLeak(unittest.TestCase):
    def test_no_colour_outside_the_palette_survives(self):
        """Padding the unused palette entries with black put pure black into 24
        of 58 files, in a palette that contained no black."""
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        import io

        from hollowpixel import palette
        source = Image.new("RGBA", (32, 32))
        for y in range(32):
            for x in range(32):
                source.putpixel((x, y), ((x * 8) % 256, (y * 8) % 256, 120, 255))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")

        anchor = [(219, 73, 73), (36, 36, 146), (255, 219, 109)]
        result = palette.apply_palette(buffer.getvalue(), anchor)
        with Image.open(io.BytesIO(result.image)) as out:
            used = {p[:3] for p in out.convert("RGBA").getdata() if p[3] > 127}
        self.assertTrue(used <= set(anchor), used - set(anchor))


class TestAnimationRequestShape(unittest.TestCase):
    """The parameters that were being sent into modes that ignore them.

    Every one of these was a silent failure: the API accepts the field, charges
    for the job, and returns a normal-looking animation with the parameter
    discarded. Nothing in the response says which knobs were live, so the only
    place the knowledge can live is a test that reads the request.
    """

    def client(self):
        from hollowpixel.v2 import Client

        sent = []
        client = Client(api_key="test-key")
        client._request = lambda method, path, payload=None, **kw: (
            sent.append((method, path, payload)) or {"background_job_ids": []})
        client._wait = lambda ids, **kw: []
        return client, sent

    def payload(self, **kwargs):
        from hollowpixel.v2 import Character

        client, sent = self.client()
        client.animate(Character(id="c1", name="rowan"), "attack", **kwargs)
        return sent[-1][2]

    def test_pro_is_the_default_mode(self):
        # v3 is the API default and the cheap one; it redraws the character in
        # place, so a swing came back as a statue holding a rotating sword.
        self.assertEqual(self.payload()["mode"], "pro")

    def test_forcing_colours_without_an_image_is_never_sent(self):
        # force_colors forces the colours *from* color_image. Sent alone -- as
        # this client did on every call for weeks -- it does nothing at all, and
        # the palette lock the docstring advertised did not exist.
        body = self.payload()
        self.assertNotIn("force_colors", body)
        self.assertNotIn("color_image", body)

    def test_a_palette_turns_the_flag_on_together_with_its_image(self):
        body = self.payload(palette=b"\x89PNG-pretend")
        self.assertTrue(body["force_colors"])
        self.assertIn("base64", body["color_image"])

    def test_frame_count_is_only_sent_in_the_mode_that_reads_it(self):
        # Documented v3-only. Pro picks its own count and returned four.
        self.assertNotIn("frame_count", self.payload(mode="pro"))
        self.assertEqual(self.payload(mode="v3", frames=8)["frame_count"], 8)

    def test_text_guidance_scale_is_not_sent_at_all(self):
        # Template mode only, per the schema, and this client only ever set it
        # on custom animations -- where it was read by nothing.
        for mode in ("pro", "v3"):
            self.assertNotIn("text_guidance_scale", self.payload(mode=mode))


class TestBattleClipsDescribeMotion(unittest.TestCase):
    def test_every_battle_clip_is_prose_not_a_template_id(self):
        from hollowpixel.character import BATTLE_CLIPS

        for clip, action in BATTLE_CLIPS.items():
            with self.subTest(clip=clip):
                # A template id is a slug; these have to be motion the model can
                # act on. "swings the sword" moved the sword and nothing else.
                self.assertNotIn("-", action.split(" ")[0])
                self.assertGreater(len(action.split()), 12, clip)

    def test_no_clip_asks_for_an_effect(self):
        from hollowpixel.character import BATTLE_CLIPS

        # The white impact burst came from the model filling in motion it had not
        # been given. Naming effects here would ask for it on purpose.
        banned = ("glow", "flash", "burst", "spark", "magic", "energy", "trail")
        for clip, action in BATTLE_CLIPS.items():
            for word in banned:
                self.assertNotIn(word, action.lower(), f"{clip} mentions {word}")


class TestFloatingDebrisRemoval(unittest.TestCase):
    """Two of eight pro rotations came back with a piece of the character
    parked in empty space. The figure was intact in both, so the fix is a
    deletion rather than a regeneration -- a re-roll risks the identity, which
    was the part that cost money."""

    def sprite(self, blobs, size=64):
        from PIL import Image

        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        pixels = image.load()
        for (left, top, right, bottom), colour in blobs:
            for x in range(left, right):
                for y in range(top, bottom):
                    pixels[x, y] = colour
        return image

    def opaque(self, image):
        return sum(1 for p in image.convert("RGBA").getdata() if p[3] > 127)

    def test_a_clean_sprite_is_returned_untouched(self):
        from hollowpixel.islands import strip_debris

        image = self.sprite([((20, 10, 40, 50), (0, 80, 200, 255))])
        out, removed = strip_debris(image)
        self.assertEqual(removed, 0)
        self.assertEqual(self.opaque(out), self.opaque(image))

    def test_a_detached_fragment_is_removed(self):
        from hollowpixel.islands import strip_debris

        image = self.sprite([((24, 8, 44, 56), (0, 80, 200, 255)),     # body
                             ((2, 20, 10, 32), (90, 60, 30, 255))])    # stray boot
        out, removed = strip_debris(image)
        self.assertEqual(removed, 8 * 12)
        self.assertEqual(self.opaque(out), 20 * 48)

    def test_a_blade_split_from_the_hand_survives(self):
        from hollowpixel.islands import strip_debris

        # The whole reason the rule is not "keep the largest region": an
        # occluding hand cuts the blade off the body, one or two pixels clear.
        image = self.sprite([((24, 8, 44, 56), (0, 80, 200, 255)),
                             ((46, 24, 60, 27), (200, 200, 210, 255))])  # 2px gap
        out, removed = strip_debris(image)
        self.assertEqual(removed, 0)
        self.assertEqual(self.opaque(out), 20 * 48 + 14 * 3)

    def test_containment_in_the_bounding_box_does_not_save_a_fragment(self):
        from hollowpixel.islands import strip_debris

        # The first version of this rule kept anything inside the body's box,
        # and a figure holding a sword out to the side has a box wide enough to
        # swallow the debris. Rowan's west rotation failed exactly here.
        image = self.sprite([((30, 8, 40, 56), (0, 80, 200, 255)),      # torso
                             ((40, 30, 62, 33), (200, 200, 210, 255)),  # held blade
                             ((44, 44, 52, 52), (120, 60, 60, 255))])   # debris, inside box
        out, removed = strip_debris(image)
        self.assertEqual(removed, 8 * 8)
        self.assertEqual(self.opaque(out), 10 * 48 + 22 * 3)

    def test_an_empty_frame_does_not_raise(self):
        from hollowpixel.islands import strip_debris

        out, removed = strip_debris(self.sprite([]))
        self.assertEqual(removed, 0)
        self.assertEqual(self.opaque(out), 0)

    def test_diagonal_pixels_count_as_one_region(self):
        from hollowpixel.islands import regions

        # 4-way connectivity would read a one-pixel diagonal blade as a dotted
        # line of separate regions and delete most of it.
        image = self.sprite([((i, i, i + 1, i + 1), (255, 255, 255, 255))
                             for i in range(10, 30)])
        self.assertEqual(len(regions(image)), 1)

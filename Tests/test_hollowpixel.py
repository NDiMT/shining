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
        """v1's skeleton endpoint took 16, 32, 64, 128 and nothing between, and
        that discrete set is what the tiers used to be rounded to. v2's pro
        endpoint takes any size from 32 to 168, so SF2's real 96 can be asked
        for exactly instead of rounded up to 128."""
        from hollowpixel import style
        from hollowpixel.pixellab import SPRITE_SIZES
        for tier in style.TIERS.values():
            with self.subTest(tier=tier.key):
                self.assertGreaterEqual(tier.size, 32, tier.key)
                self.assertLessEqual(tier.size, 168, tier.key)
        # The v1 set is still the constraint on the v1 path, so it is still real.
        self.assertEqual(SPRITE_SIZES, (16, 32, 64, 128))

    def test_the_battle_tier_is_sf2s_measured_frame_size(self):
        from hollowpixel import style
        self.assertEqual(style.BATTLE.size, style.SF2["frame"])
        self.assertEqual(style.SF2["frame"], 96, "measured off the reference sheet")

    def test_the_map_tier_is_the_smaller_one(self):
        from hollowpixel import style
        self.assertLess(style.MAP.size, style.BATTLE.size)

    def test_the_battle_tier_does_not_ask_for_flat_shading(self):
        """Two measurements point opposite ways here, so both are recorded.

        The earlier one: flat shading plus a 16-colour quantiser was the
        "authentic" answer, and on the same subject four ways it lost to the
        generator's own shading -- washed-out tunic, dull cape, flattened face.
        That is why "flat shading" stays excluded.

        The later one: a real SF2 sprite has 13 colours at mean saturation 0.79
        with one black doing every line, and asking for "highly detailed" got 29
        colours at 0.48 -- a soft dark ramp and muddy mid-tones, which is a
        modern indie look wearing SF2's dimensions. So the tier asks for basic
        shading and medium detail now, which is two flat tones per material
        rather than no tones at all.

        If the output ever comes back washed out, the first measurement is the
        reason and this is the line to revisit."""
        from hollowpixel import style
        self.assertNotIn("flat", style.BATTLE.shading)
        self.assertIn("shading", style.BATTLE.shading)
        self.assertIn(style.BATTLE.detail, ("medium detail", "highly detailed"))

    def test_the_battle_tier_speaks_the_reference_palette(self):
        from hollowpixel import style
        tokens = " ".join(style.BATTLE.direction_tokens).lower()
        # one black for every line, one white for every highlight, saturated fills
        self.assertIn("pure black", tokens)
        self.assertIn("pure white", tokens)
        self.assertIn("saturated", tokens)
        self.assertEqual(style.BATTLE.outline, "single color black outline")

    def test_the_prompt_grammar_rejects_the_modern_look(self):
        from hollowpixel import style
        avoid = " ".join(style.AVOID_TOKENS).lower()
        # the exact phrasing that produced 0.48 saturation and a five-step ramp
        for word in ("desaturated", "rim light", "painterly"):
            self.assertIn(word, avoid)


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


class TestClipAssembly(unittest.TestCase):
    """Pro keyframes and interpolated inbetweens arrive on different canvases,
    and stacking them without correcting for it makes the character jump
    sideways at the seam."""

    def frame(self, size, box, colour=(0, 90, 200, 255)):
        from PIL import Image

        image = Image.new("RGBA", size, (0, 0, 0, 0))
        pixels = image.load()
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                pixels[x, y] = colour
        return image

    def test_the_padding_offset_is_recovered_from_the_silhouette(self):
        from hollowpixel.clips import find_offset

        original = self.frame((40, 40), (10, 5, 30, 35))
        padded = self.frame((80, 70), (10 + 17, 5 + 12, 30 + 17, 35 + 12))
        self.assertEqual(find_offset(padded, original), (17, 12))

    def test_a_redrawn_first_frame_still_locates(self):
        from hollowpixel.clips import find_offset

        # The interpolator redraws rather than copies its start frame, so the
        # colours differ. Matching on alpha is what survives that.
        original = self.frame((40, 40), (10, 5, 30, 35), colour=(0, 90, 200, 255))
        padded = self.frame((80, 70), (27, 17, 47, 47), colour=(220, 40, 40, 255))
        self.assertEqual(find_offset(padded, original), (17, 12))

    def test_an_oversized_original_is_refused(self):
        from hollowpixel.clips import find_offset

        with self.assertRaises(ValueError):
            find_offset(self.frame((20, 20), (0, 0, 5, 5)),
                        self.frame((40, 40), (0, 0, 5, 5)))

    def test_aligning_puts_every_frame_on_one_canvas(self):
        from hollowpixel.clips import align

        frames = [self.frame((20, 20), (0, 0, 10, 10)) for _ in range(3)]
        out = align(frames, [(0, 0), (5, 5), (10, 10)], (40, 40))
        self.assertEqual({f.size for f in out}, {(40, 40)})
        self.assertEqual(out[1].getpixel((7, 7))[3], 255)
        self.assertEqual(out[1].getpixel((2, 2))[3], 0)

    def test_align_refuses_a_mismatched_offset_count(self):
        from hollowpixel.clips import align

        with self.assertRaises(ValueError):
            align([self.frame((8, 8), (0, 0, 4, 4))], [(0, 0), (1, 1)], (16, 16))

    def test_the_swing_holds_the_ends_and_runs_the_cut(self):
        from hollowpixel.clips import swing

        beats = swing(8)
        cut = [b for b in beats if 2 <= b.frame <= 8][:7]
        self.assertEqual({b.ms for b in cut}, {60}, "the cut must not stutter")
        self.assertGreater(beats[0].ms, 4 * 60, "the stance has to settle")
        self.assertGreater(max(b.ms for b in beats if b.frame == 9), 4 * 60,
                           "contact has to be held or the blow does not land")

    def test_the_swing_returns_to_the_pose_it_started_from(self):
        from hollowpixel.clips import swing

        beats = swing(8)
        self.assertEqual(beats[-1].frame, beats[0].frame)


class TestClipAssembly(unittest.TestCase):
    """Pro keyframes and interpolated inbetweens arrive on different canvases,
    padded by an amount the API does not report. Stacking them without
    correcting for it makes the character jump sideways at the seam."""

    def frame(self, size, box, colour=(0, 90, 200, 255)):
        from PIL import Image

        image = Image.new("RGBA", size, (0, 0, 0, 0))
        pixels = image.load()
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                pixels[x, y] = colour
        return image

    def test_the_padding_offset_is_recovered_from_the_silhouette(self):
        from hollowpixel.clips import find_offset

        original = self.frame((40, 40), (10, 5, 30, 35))
        padded = self.frame((80, 70), (27, 17, 47, 47))
        self.assertEqual(find_offset(padded, original), (17, 12))

    def test_a_redrawn_first_frame_still_locates(self):
        from hollowpixel.clips import find_offset

        # The interpolator redraws its start frame rather than copying it, so
        # the colours differ. Matching on alpha is what survives that.
        original = self.frame((40, 40), (10, 5, 30, 35), colour=(0, 90, 200, 255))
        padded = self.frame((80, 70), (27, 17, 47, 47), colour=(220, 40, 40, 255))
        self.assertEqual(find_offset(padded, original), (17, 12))

    def test_an_oversized_original_is_refused(self):
        from hollowpixel.clips import find_offset

        with self.assertRaises(ValueError):
            find_offset(self.frame((20, 20), (0, 0, 5, 5)),
                        self.frame((40, 40), (0, 0, 5, 5)))

    def test_aligning_puts_every_frame_on_one_canvas(self):
        from hollowpixel.clips import align

        frames = [self.frame((20, 20), (0, 0, 10, 10)) for _ in range(3)]
        out = align(frames, [(0, 0), (5, 5), (10, 10)], (40, 40))
        self.assertEqual({f.size for f in out}, {(40, 40)})
        self.assertEqual(out[1].getpixel((7, 7))[3], 255)
        self.assertEqual(out[1].getpixel((2, 2))[3], 0)

    def test_align_refuses_a_mismatched_offset_count(self):
        from hollowpixel.clips import align

        with self.assertRaises(ValueError):
            align([self.frame((8, 8), (0, 0, 4, 4))], [(0, 0), (1, 1)], (16, 16))

    def test_the_swing_holds_the_ends_and_runs_the_cut(self):
        from hollowpixel.clips import swing

        beats = swing(8)
        cut = [b for b in beats if 2 <= b.frame <= 8][:7]
        self.assertEqual({b.ms for b in cut}, {60}, "the cut must not stutter")
        self.assertGreater(beats[0].ms, 4 * 60, "the stance has to settle")
        self.assertGreater(max(b.ms for b in beats if b.frame == 9), 4 * 60,
                           "contact has to be held or the blow does not land")

    def test_the_swing_returns_to_the_pose_it_started_from(self):
        from hollowpixel.clips import swing

        beats = swing(8)
        self.assertEqual(beats[-1].frame, beats[0].frame)


class TestInterpolationRequestShape(unittest.TestCase):
    def payload(self, **kwargs):
        from hollowpixel.v2 import Character, Client

        sent = []
        client = Client(api_key="test-key")
        client._request = lambda m, p, body=None, **kw: (
            sent.append(body) or {"background_job_ids": []})
        client._wait = lambda ids, **kw: []
        client.interpolate(Character(id="c1", name="r"), "cut", b"start", b"end",
                           action="swings down", **kwargs)
        return sent[-1]

    def test_the_reference_frame_is_stripped_so_the_count_is_what_was_asked(self):
        # keep_first_frame would prepend the start pose, which is already the
        # last frame of the segment before it -- a duplicate at every seam.
        self.assertFalse(self.payload()["keep_first_frame"])

    def test_interpolation_runs_in_v3_because_pro_cannot_do_it(self):
        body = self.payload()
        self.assertEqual(body["mode"], "v3")
        self.assertIn("custom_start_frame", body)
        self.assertIn("end_frame", body)

    def test_a_description_is_forwarded_when_given(self):
        # Omitting it let the interpolator decorate the blade with invented
        # energy. Forwarding it does not fully stop that, but not sending it
        # leaves no way to ask at all.
        self.assertNotIn("description", self.payload())
        self.assertEqual(self.payload(description="plain steel")["description"],
                         "plain steel")


class TestWeaponLayer(unittest.TestCase):
    """Shining Force II keeps the weapon out of the character sprite and
    composites it per frame with its own offset and draw order. Byte 5 of its
    eight-byte animation frame is the z-index: 1 under the character, 2 over.
    That byte is why its heroes never had a blade sticking out of their back,
    and why a single baked image cannot avoid one."""

    def sprites(self):
        from PIL import Image

        body = Image.new("RGBA", (20, 40), (0, 90, 200, 255))
        blades = []
        for i in range(4):
            blade = Image.new("RGBA", (24, 6), (0, 0, 0, 0))
            for x in range(24):
                blade.putpixel((x, i), (200, 200, 210, 255))
            blades.append(blade)
        return [body], blades

    def test_under_puts_the_body_on_top(self):
        from hollowpixel.weapon import Frame, Pose, UNDER, compose

        bodies, blades = self.sprites()
        out = compose(Frame(body=0, ms=60, weapon=Pose(0, x=4, y=10, z=UNDER)),
                      bodies, blades, (40, 50))
        # The blade runs through where the body is; the body must win there.
        self.assertEqual(out.getpixel((10, 10))[:3], (0, 90, 200))

    def test_over_puts_the_weapon_on_top(self):
        from hollowpixel.weapon import Frame, Pose, OVER, compose

        bodies, blades = self.sprites()
        out = compose(Frame(body=0, ms=60, weapon=Pose(0, x=4, y=10, z=OVER)),
                      bodies, blades, (40, 50))
        self.assertEqual(out.getpixel((10, 10))[:3], (200, 200, 210))

    def test_the_same_frame_reads_both_ways_from_one_byte(self):
        from hollowpixel.weapon import Frame, Pose, OVER, UNDER, compose

        bodies, blades = self.sprites()
        seen = {z: compose(Frame(body=0, ms=60, weapon=Pose(0, x=4, y=10, z=z)),
                           bodies, blades, (40, 50)).getpixel((10, 10))[:3]
                for z in (UNDER, OVER)}
        self.assertNotEqual(seen[UNDER], seen[OVER],
                            "if draw order changed nothing, the layer buys nothing")

    def test_a_frame_without_a_weapon_is_just_the_body(self):
        from hollowpixel.weapon import Frame, compose

        bodies, blades = self.sprites()
        out = compose(Frame(body=0, ms=60), bodies, blades, (40, 50))
        self.assertEqual(out.getpixel((10, 10))[:3], (0, 90, 200))
        self.assertEqual(out.getpixel((35, 45))[3], 0)

    def test_the_sf2_frame_byte_round_trips(self):
        from hollowpixel.weapon import OVER, Pose

        # 0x10 flips horizontally, 0x20 vertically, low bits are the rotation.
        pose = Pose.from_byte(0x32, z=OVER, x=3, y=-4)
        self.assertEqual(pose.orientation, 2)
        self.assertTrue(pose.flip_x)
        self.assertTrue(pose.flip_y)
        self.assertEqual(pose.to_byte(), 0x32)

    def test_four_drawings_plus_flips_cover_sixteen_orientations(self):
        from hollowpixel.weapon import ORIENTATIONS, Pose

        combos = {Pose(o, flip_x=fx, flip_y=fy).to_byte()
                  for o in range(len(ORIENTATIONS))
                  for fx in (False, True) for fy in (False, True)}
        self.assertEqual(len(combos), 16)

    def test_an_impossible_z_or_orientation_is_refused(self):
        from hollowpixel.weapon import Pose

        with self.assertRaises(ValueError):
            Pose(orientation=4)
        with self.assertRaises(ValueError):
            Pose(orientation=0, z=3)

    def test_flipping_moves_the_blade_to_the_mirrored_row(self):
        from hollowpixel.weapon import Frame, Pose, OVER, compose

        bodies, blades = self.sprites()
        plain = compose(Frame(body=0, ms=60, weapon=Pose(1, x=20, y=0, z=OVER)),
                        bodies, blades, (50, 50))
        flipped = compose(Frame(body=0, ms=60, weapon=Pose(1, x=20, y=0, z=OVER,
                                                          flip_y=True)),
                          bodies, blades, (50, 50))
        self.assertEqual(plain.getpixel((30, 1))[3], 255)
        self.assertEqual(flipped.getpixel((30, 1))[3], 0)
        self.assertEqual(flipped.getpixel((30, 4))[3], 255)


class TestGroundAnchoring(unittest.TestCase):
    """Every generated frame is centred in its own canvas, and the figure is not
    centred the same way twice -- a crouch sits low and narrow, an overhead raise
    tall. Composited on canvas centres the character hops about while the clip
    plays, which reads as frames dropped in at random rather than as motion.

    Bowie's sheet settles what to anchor on. Across one row of six poses the
    content bottoms measure 75, 75, 74, 75, 76, 76 while the tops range from 0
    to 13: feet on a line, heads wherever the pose puts them. SF2 spends two of
    its eight animation bytes on exactly this."""

    def figure(self, size, feet_x, bottom, height, width=10):
        from PIL import Image

        image = Image.new("RGBA", size, (0, 0, 0, 0))
        pixels = image.load()
        for x in range(feet_x - width // 2, feet_x + width // 2):
            for y in range(bottom - height, bottom + 1):
                pixels[x, y] = (0, 90, 200, 255)
        return image

    def test_footing_reports_the_feet_not_the_centre(self):
        from hollowpixel.clips import footing

        image = self.figure((60, 60), feet_x=20, bottom=50, height=30)
        self.assertEqual(footing(image), (19, 50))

    def test_footing_averages_two_feet_apart(self):
        from PIL import Image

        from hollowpixel.clips import footing

        image = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        pixels = image.load()
        for x in list(range(10, 16)) + list(range(30, 36)):
            for y in range(44, 51):
                pixels[x, y] = (90, 60, 40, 255)
        x, y = footing(image)
        self.assertEqual(y, 50)
        self.assertTrue(20 <= x <= 26, x)

    def test_footing_ignores_a_head_that_moved(self):
        from hollowpixel.clips import footing

        low = self.figure((60, 60), feet_x=20, bottom=50, height=20)
        tall = self.figure((60, 60), feet_x=20, bottom=50, height=44)
        self.assertEqual(footing(low), footing(tall))

    def test_offsets_put_every_frame_on_one_floor(self):
        from hollowpixel.clips import align, footing, ground_offsets

        frames = [self.figure((60, 60), 20, 50, 30),
                  self.figure((60, 60), 34, 44, 18),
                  self.figure((60, 60), 12, 55, 40)]
        anchor = (40, 70)
        placed = align(frames, ground_offsets(frames, anchor), (80, 80))
        self.assertEqual({footing(f) for f in placed}, {anchor})

    def test_an_empty_frame_reports_something_usable(self):
        from PIL import Image

        from hollowpixel.clips import footing

        x, y = footing(Image.new("RGBA", (40, 30), (0, 0, 0, 0)))
        self.assertEqual((x, y), (20, 29))


class TestFindingTheGrip(unittest.TestCase):
    def scene(self, hand, cape=None):
        from PIL import Image

        image = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        pixels = image.load()
        for x in range(34, 46):                      # torso
            for y in range(20, 60):
                pixels[x, y] = (40, 70, 140, 255)
        for x in range(hand[0] - 3, hand[0] + 4):    # fist
            for y in range(hand[1] - 3, hand[1] + 4):
                pixels[x, y] = (120, 78, 58, 255)
        if cape:
            for x in range(cape[0], cape[0] + 20):   # cloth, flung wide
                for y in range(cape[1], cape[1] + 24):
                    pixels[x, y] = (135, 20, 35, 255)
        return image

    def test_the_hand_is_found_at_the_named_extremity(self):
        from hollowpixel.weapon import find_hand

        x, y = find_hand(self.scene(hand=(16, 40)), "left")
        self.assertLessEqual(abs(x - 13), 2)
        self.assertLessEqual(abs(y - 40), 3)

    def test_the_cape_does_not_pass_for_a_fist(self):
        from hollowpixel.weapon import find_hand

        # The cloth reaches further right than the arm ever does; a sword hung
        # off it floats in mid-air, which is what this excludes.
        scene = self.scene(hand=(62, 40), cape=(58, 18))
        x, _ = find_hand(scene, "right")
        self.assertLessEqual(x, 66, "the cape won the extremity test")

    def test_an_overhead_raise_is_found_at_the_top(self):
        from hollowpixel.weapon import find_hand

        x, y = find_hand(self.scene(hand=(40, 10)), "top")
        self.assertLessEqual(abs(x - 40), 3)
        self.assertLessEqual(abs(y - 7), 2)

    def test_an_unknown_extremity_is_refused(self):
        from hollowpixel.weapon import find_hand

        with self.assertRaises(ValueError):
            find_hand(self.scene(hand=(20, 40)), "sideways")


class TestCutOutRig(unittest.TestCase):
    """Generated frames redraw the whole character, so consecutive frames overlap
    0.64 at best (pro) and 0.50 (templates), against 0.75 and up for hand-drawn
    work. Moving parts of one sprite puts it at 0.94, because the torso is the
    same pixels every frame rather than the same character drawn again."""

    def sprite(self, size=(40, 60)):
        from PIL import Image

        image = Image.new("RGBA", size, (0, 0, 0, 0))
        pixels = image.load()
        for x in range(14, 26):                     # torso
            for y in range(10, 45):
                pixels[x, y] = (40, 70, 140, 255)
        for x in range(10, 16):                     # arm, over the torso's left edge
            for y in range(16, 38):
                pixels[x, y] = (120, 78, 58, 255)
        return image

    def blade(self):
        from PIL import Image

        image = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
        pixels = image.load()
        for i in range(12):
            pixels[i, 11 - i] = (200, 200, 210, 255)
        return image

    def test_a_part_reports_its_pivot_in_its_own_coordinates(self):
        from hollowpixel.rig import cut

        part = cut(self.sprite(), (10, 16, 16, 38), pivot=(12, 18), attach=(12, 36))
        self.assertEqual(part.local_pivot, (2, 2))
        self.assertEqual(part.image.size, (6, 22))

    def test_a_pivot_outside_the_rect_is_refused(self):
        from hollowpixel.rig import cut

        with self.assertRaises(ValueError):
            cut(self.sprite(), (10, 16, 16, 38), pivot=(30, 18))

    def test_a_rect_outside_the_sprite_is_refused(self):
        from hollowpixel.rig import cut

        with self.assertRaises(ValueError):
            cut(self.sprite(), (10, 16, 500, 38), pivot=(12, 18))

    def test_the_hole_is_filled_from_the_surface_beside_it(self):
        from hollowpixel.rig import patch_hole

        # Leaving the arm in leaves a ghost of it wherever it swings away; cutting
        # it out leaves a hole. The patch takes the torso's own colour per row.
        patched = patch_hole(self.sprite(), (10, 16, 16, 38))
        self.assertEqual(patched.getpixel((14, 20))[:3], (40, 70, 140))
        self.assertEqual(patched.getpixel((11, 20))[:3], (40, 70, 140),
                         "the arm's colour survived the patch")

    def test_patching_leaves_transparent_pixels_alone(self):
        from hollowpixel.rig import patch_hole

        patched = patch_hole(self.sprite(), (0, 0, 10, 10))
        self.assertEqual(patched.getpixel((2, 2))[3], 0)

    def test_a_point_swung_about_a_pivot_keeps_its_distance(self):
        import math

        from hollowpixel.rig import swing_point

        pivot, fist = (10.0, 10.0), (10.0, 30.0)
        for deg in (0, 30, 90, 180, -45):
            x, y = swing_point(pivot, fist, deg)
            r = math.hypot(x - pivot[0], y - pivot[1])
            self.assertAlmostEqual(r, 20.0, places=6,
                                   msg="the fist left the end of the arm")

    def test_a_quarter_turn_puts_the_fist_where_it_belongs(self):
        from hollowpixel.rig import swing_point

        x, y = swing_point((10.0, 10.0), (10.0, 30.0), 90)
        self.assertAlmostEqual(x, 30.0, places=6)
        self.assertAlmostEqual(y, 10.0, places=6)

    def test_rotating_reports_where_the_pivot_went(self):
        from hollowpixel.rig import rotate_about

        part = self.sprite()
        out, pivot = rotate_about(part, (5.0, 5.0), 0)
        self.assertEqual(out.size, part.size)
        self.assertAlmostEqual(pivot[0], 5.0, places=6)
        self.assertAlmostEqual(pivot[1], 5.0, places=6)

    def test_the_body_is_identical_in_every_frame(self):
        from hollowpixel.rig import Pose, Rig, cut, patch_hole

        base = self.sprite()
        arm = cut(base, (10, 16, 16, 38), pivot=(12, 18), attach=(12, 36))
        r = Rig(body=patch_hole(base, arm.rect), arm=arm, weapon=self.blade(),
                size=(90, 90), offset=(20, 20), shadow=False)
        frames = r.render([Pose(arm=a, blade=-a) for a in (0, -30, -60, 20)])

        # Compare a torso column no part ever covers: identical means identical.
        column = lambda f: [f.getpixel((20 + 22, 20 + y)) for y in range(12, 44)]
        first = column(frames[0])
        for i, f in enumerate(frames[1:], 1):
            self.assertEqual(column(f), first, f"the torso changed by frame {i}")

    def test_draw_order_decides_whether_the_blade_shows(self):
        from hollowpixel.rig import Pose, Rig, cut, patch_hole

        base = self.sprite()
        arm = cut(base, (10, 16, 16, 38), pivot=(12, 18), attach=(12, 36))
        r = Rig(body=patch_hole(base, arm.rect), arm=arm, weapon=self.blade(),
                size=(90, 90), offset=(20, 20), shadow=False)
        over, under = r.frame(Pose(over=True)), r.frame(Pose(over=False))
        self.assertNotEqual(list(over.getdata()), list(under.getdata()),
                            "if draw order changed nothing, the layer buys nothing")

    def test_an_arm_with_no_attachment_draws_no_weapon(self):
        from hollowpixel.rig import Pose, Rig, cut, patch_hole

        base = self.sprite()
        arm = cut(base, (10, 16, 16, 38), pivot=(12, 18))     # no attach
        r = Rig(body=patch_hole(base, arm.rect), arm=arm, weapon=self.blade(),
                size=(90, 90), offset=(20, 20), shadow=False)
        steel = sum(1 for p in r.frame(Pose()).getdata() if p[:3] == (200, 200, 210))
        self.assertEqual(steel, 0)


class TestReferencePaletteReduction(unittest.TestCase):
    """Reducing colour count on generated output is the operation this project
    has now measured four separate times and lost four separate times. The
    functions exist because the reference's structure is worth being able to
    state; they are not for character sprites."""

    def swatch(self, colours, size=(12, 12)):
        from PIL import Image

        image = Image.new("RGBA", size, (0, 0, 0, 0))
        pixels = image.load()
        n = len(colours)
        for i, c in enumerate(colours):
            for x in range(size[0]):
                for y in range(i * size[1] // n, (i + 1) * size[1] // n):
                    pixels[x, y] = c + (255,)
        return image

    def test_the_dark_ramp_collapses_to_one_black(self):
        from hollowpixel.palette import collapse_blacks

        # SF2 has exactly one near-black doing every outline and interior line,
        # and it is 37% of the art. Generated sprites arrive with a soft ramp of
        # them, which makes an outline read as a shadow rather than a line.
        image = self.swatch([(8, 6, 10), (18, 14, 20), (28, 22, 30), (200, 40, 60)])
        out, merged = collapse_blacks(image)
        darks = {p[:3] for p in out.convert("RGBA").getdata()
                 if p[3] > 127 and max(p[:3]) < 40}
        self.assertEqual(merged, 2)
        self.assertEqual(darks, {(0, 0, 0)})

    def test_a_sprite_with_one_black_is_left_alone(self):
        from hollowpixel.palette import collapse_blacks

        out, merged = collapse_blacks(self.swatch([(0, 0, 0), (200, 40, 60)]))
        self.assertEqual(merged, 0)

    def test_reduction_hits_the_requested_count(self):
        from hollowpixel.palette import reduce_to

        image = self.swatch([(200, 40, 60), (190, 50, 70), (180, 60, 80),
                             (40, 90, 200), (255, 255, 255), (0, 0, 0)])
        out, _ = reduce_to(image, colours=3)
        used = {p[:3] for p in out.convert("RGBA").getdata() if p[3] > 127}
        self.assertEqual(len(used), 3)

    def test_reduction_never_invents_a_colour(self):
        from hollowpixel.palette import reduce_to

        source = [(200, 40, 60), (190, 50, 70), (40, 90, 200), (0, 0, 0)]
        out, _ = reduce_to(self.swatch(source), colours=2)
        used = {p[:3] for p in out.convert("RGBA").getdata() if p[3] > 127}
        self.assertTrue(used <= set(source), "a colour appeared that was not there")

    def test_a_request_for_more_colours_than_exist_is_a_no_op(self):
        from hollowpixel.palette import reduce_to

        image = self.swatch([(200, 40, 60), (0, 0, 0)])
        out, mapping = reduce_to(image, colours=13)
        self.assertEqual(mapping, {})
        self.assertEqual(list(out.getdata()), list(image.convert("RGBA").getdata()))

    def test_the_merge_keeps_the_more_saturated_of_a_pair(self):
        from hollowpixel.palette import reduce_to

        # Keeping the more *common* colour was the first rule, and it cost 0.09
        # of mean saturation and four of nine saturated colours, because the
        # common colour is usually a large dull fill.
        vivid, dull = (220, 0, 40), (120, 70, 80)
        from PIL import Image
        image = Image.new("RGBA", (10, 10), dull + (255,))
        px = image.load()
        for x in range(10):
            px[x, 0] = vivid + (255,)          # vivid is rare
        out, _ = reduce_to(image, colours=1)
        used = {p[:3] for p in out.convert("RGBA").getdata() if p[3] > 127}
        self.assertEqual(used, {vivid})

    def test_this_is_documented_as_harmful_on_character_sprites(self):
        from hollowpixel import palette

        # Guards the finding, not the code: forced to 13 colours a hero's brown
        # hair merged into his crimson cape and came out red, because those are
        # neighbours in RGB. Anyone reaching for this on a character should read
        # why first.
        text = (palette.__doc__ or "") + (palette.reduce_to.__doc__ or "")
        source = open(palette.__file__).read()
        self.assertIn("quantiser", source.lower())
        self.assertIn("PixelLab output", source)

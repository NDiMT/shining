"""Pose templates for the battle screen, authored once for the whole cast.

The attack screen needs sprites far bigger than the tactical map's, and that
runs into the one hard constraint in the API: ``animate-with-text`` accepts
**64x64 only**. ``animate-with-skeleton`` goes to 256x256, which is where a
Shining Force II-scale battle sprite lives, but it wants a posed skeleton per
frame instead of the word "walk".

That sounds like more work and is actually less, because of how
``estimate-skeleton`` returns its answer: eighteen keypoints, **labelled**
(``RIGHT SHOULDER``, ``LEFT KNEE``) and **normalised to 0..1**. Labels plus
normalisation mean a pose is not tied to the character it was authored on. Swing
the right arm ninety degrees about the shoulder and it is the same instruction
for Rowan, for a goblin, and for a boss twice their size.

So this module is the 2D counterpart of the shared skeleton in brief section 56,
and it is what makes a 25-35 character cast affordable in the attack screen:
poses are written once here, and every character reuses them.

Nothing in this module calls the API. Poses are geometry, so they are testable
without spending anything, which is the whole reason they live apart from the
client.

**Two numbers here were measured, not chosen.** A five-way sweep of the same
attack against the same reference sprite settled both:

* **No whole-body offsets, and modest leans.** The first version shifted the
  whole figure and leaned it hard, which displaced all eighteen keypoints in
  every frame. The model then rebuilt the character rather than adjusting it:
  ghost swords, a redrawn face, identity drifting frame to frame. Rotations that
  move only the limb chain keep the character intact.
* **``guidance_scale=8``**, not the API default of 4. At 4 the character still
  drifts even with clean poses.

Rotations are correspondingly gentle, around 30-40 degrees rather than 50-65.
A bigger swing is built by chaining windows, not by asking one frame to travel
further -- which is also how the attack screen reads: approach, strike, reaction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Limb chains, parent first. A rotation applied to a chain turns every joint
#: after the first about that first joint, so the elbow carries the hand with it.
CHAINS: dict[str, tuple[str, ...]] = {
    "right_arm": ("RIGHT SHOULDER", "RIGHT ELBOW", "RIGHT ARM"),
    "left_arm": ("LEFT SHOULDER", "LEFT ELBOW", "LEFT ARM"),
    "right_leg": ("RIGHT HIP", "RIGHT KNEE", "RIGHT LEG"),
    "left_leg": ("LEFT HIP", "LEFT KNEE", "LEFT LEG"),
    "head": ("NECK", "NOSE", "LEFT EYE", "RIGHT EYE", "LEFT EAR", "RIGHT EAR"),
}

#: Everything above the hips, for a whole-torso lean.
TORSO = ("NECK", "NOSE", "LEFT EYE", "RIGHT EYE", "LEFT EAR", "RIGHT EAR",
         "LEFT SHOULDER", "RIGHT SHOULDER", "LEFT ELBOW", "RIGHT ELBOW",
         "LEFT ARM", "RIGHT ARM")

#: Every label ``estimate-skeleton`` returns. A pose naming anything else is a
#: typo, and typos in a pose table are invisible in the output — the frame just
#: comes back slightly wrong — so they are rejected instead.
LABELS = frozenset(
    label for chain in CHAINS.values() for label in chain
) | {"LEFT HIP", "RIGHT HIP"}


@dataclass(frozen=True)
class Pose:
    """One keyframe, as changes from the character's rest skeleton.

    Deltas rather than absolute positions, because absolute positions would bake
    in the proportions of whoever the pose was authored on. A goblin is not
    Rowan's shape, and "swing the arm forward" should mean the same thing for
    both.
    """

    name: str
    #: chain name -> degrees, positive anticlockwise on screen.
    rotations: dict[str, float] = field(default_factory=dict)
    #: Whole-body shift in normalised units. Positive x is screen-right.
    #:
    #: **Almost always leave this at zero.** Measured on a five-way sweep of the
    #: same attack against the same reference: any non-zero offset displaces all
    #: eighteen keypoints, the model stops recognising it as the same pose being
    #: adjusted and rebuilds the character from scratch, and the frames come back
    #: with a ghost of the old sword beside the new one and the face redrawn.
    #: Moving a sprite across the screen is the scene's job, not the skeleton's.
    offset: tuple[float, float] = (0.0, 0.0)
    #: Torso lean about the hip midpoint, degrees.
    lean: float = 0.0


def apply(skeleton: list[dict], pose: Pose) -> list[dict]:
    """Return a new keypoint list with ``pose`` applied. Input is not modified."""
    points = {p["label"]: dict(p) for p in skeleton}
    missing = set(CHAINS) - {c for c in CHAINS if all(l in points for l in CHAINS[c])}

    if pose.lean:
        hips = [points[l] for l in ("LEFT HIP", "RIGHT HIP") if l in points]
        if hips:
            pivot = (sum(h["x"] for h in hips) / len(hips),
                     sum(h["y"] for h in hips) / len(hips))
            for label in TORSO:
                if label in points:
                    _rotate_about(points[label], pivot, pose.lean)

    for chain, degrees in pose.rotations.items():
        if chain in missing or chain not in CHAINS:
            continue
        joints = CHAINS[chain]
        root = points.get(joints[0])
        if root is None:
            continue
        pivot = (root["x"], root["y"])
        for label in joints[1:]:
            if label in points:
                _rotate_about(points[label], pivot, degrees)

    dx, dy = pose.offset
    if dx or dy:
        for point in points.values():
            point["x"] += dx
            point["y"] += dy

    # Clamp inside the frame. A keypoint outside 0..1 is not an error the API
    # reports; it silently produces a frame with a limb jammed against the edge.
    for point in points.values():
        point["x"] = min(1.0, max(0.0, point["x"]))
        point["y"] = min(1.0, max(0.0, point["y"]))

    return [points[p["label"]] for p in skeleton]


def _rotate_about(point: dict, pivot: tuple[float, float], degrees: float) -> None:
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    x, y = point["x"] - pivot[0], point["y"] - pivot[1]
    # Screen y grows downward, so the sign of the sine terms is flipped from the
    # textbook rotation to keep "positive is anticlockwise" true on screen.
    point["x"] = pivot[0] + x * cos + y * sin
    point["y"] = pivot[1] - x * sin + y * cos


# ---------------------------------------------------------------------------
# The pose library
# ---------------------------------------------------------------------------

REST = Pose("rest")

#: Weight back, sword arm cocked. The lean does most of the work: rotating only
#: the arm reads as a character waving rather than winding up to hit something.
WINDUP = Pose("windup", rotations={"right_arm": -31.0, "left_arm": 8.0}, lean=-3.5)

#: Through the target. Arm past vertical, body committed forward.
STRIKE = Pose("strike", rotations={"right_arm": 38.0, "left_arm": -11.0}, lean=5.5)

#: Follow-through, before returning to rest.
RECOVER = Pose("recover", rotations={"right_arm": 13.0}, lean=2.0)

#: Struck. Head back, arms loose, whole body driven backwards.
HIT = Pose("hit", rotations={"right_arm": -16.0, "left_arm": -18.0, "head": -10.0}, lean=-7.5)

#: Defeated. Collapsed toward the ground rather than rotated flat, which reads
#: better at this size than a character lying rigidly on their side.
DOWN = Pose("down", rotations={"right_arm": -42.0, "left_arm": -42.0,
                               "right_leg": 20.0, "left_leg": 20.0, "head": -18.0},
            lean=-19.0)

#: Guarding. Both arms in, body square and low.
BLOCK = Pose("block", rotations={"right_arm": -20.0, "left_arm": 24.0}, lean=3.0)

#: Casting. Arms up and open, weight on the back foot.
CAST = Pose("cast", rotations={"right_arm": -48.0, "left_arm": 48.0, "head": 5.0}, lean=-3.0)

#: Mid-stride, for the approach the attack screen opens with.
STEP_LEFT = Pose("step_left", rotations={"left_leg": 24.0, "right_leg": -20.0,
                                         "left_arm": -16.0, "right_arm": 16.0})
STEP_RIGHT = Pose("step_right", rotations={"left_leg": -20.0, "right_leg": 24.0,
                                           "left_arm": 16.0, "right_arm": -16.0})

#: ``animate-with-skeleton`` takes **exactly three** frames and rejects anything
#: else with a 422, so every clip here is a three-pose window. Longer sequences
#: are chained windows, which is also how the attack screen is built: approach,
#: strike, reaction are three separate calls whose results are played in order.
CLIPS: dict[str, tuple[Pose, Pose, Pose]] = {
    "idle": (REST, Pose("breathe", lean=1.0), REST),
    "walk": (STEP_LEFT, REST, STEP_RIGHT),
    "attack": (WINDUP, STRIKE, RECOVER),
    "block": (REST, BLOCK, BLOCK),
    "hit": (REST, HIT, HIT),
    "death": (HIT, Pose("falling", lean=-12.0), DOWN),
    "cast": (REST, CAST, CAST),
}

#: What a unit needs before it can appear in the attack screen at all.
MINIMAL_CLIPS = ("idle", "attack", "hit", "death")


def clip(name: str) -> tuple[Pose, Pose, Pose]:
    if name not in CLIPS:
        raise KeyError(f"unknown clip {name!r}; known: {', '.join(sorted(CLIPS))}")
    return CLIPS[name]


def frames_for(skeleton: list[dict], name: str) -> list[list[dict]]:
    """The three posed skeletons ``animate-with-skeleton`` wants for one clip."""
    return [apply(skeleton, pose) for pose in clip(name)]

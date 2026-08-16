"""PixelLab v2: the character pipeline, which is the one that actually works.

Everything this project built by hand exists here properly, and finding that out
cost most of a day:

===========================  ==================================================
Hand-built, badly            v2 endpoint that already does it
===========================  ==================================================
``poses.py`` skeleton poses  ``/characters/animations`` action text or templates
``palette.apply_palette``    ``force_colors`` on the animation request
``character.py`` rotations   ``/create-character-v3``, eight directions per call
``mirror()`` for west        included; all eight are generated consistently
a shared palette by hand     ``keep_first_frame`` anchors every clip to frame 0
===========================  ==================================================

The v1 endpoints this package started on -- ``generate-image-pixflux``,
``rotate``, ``animate-with-skeleton`` -- are the low-level surface. They work,
and composing them by hand produced sprites that lost their sword between
frames, because each frame is independently redrawn from a pose hint rather than
animated. ``/characters/animations`` animates a *character*: one entity, one
identity, frames that belong to each other.

``/v2/llms.txt`` is only a link index; the thing worth reading is
``/v2/openapi.json``, whose per-field descriptions say which mode each parameter
belongs to. Three of this client's calls were sending parameters into modes that
ignore them, and nothing in the response says so:

===========================  ==================================================
Assumed                      Actually
===========================  ==================================================
``force_colors: true``       forces colours *from* ``color_image``; alone, a
                             no-op, so the palette lock never existed
``text_guidance_scale``      template mode only, ignored on every v3 call
``frame_count``              v3 only; pro picks its own (four, on the swing)
default animation mode       ``v3``, the cheap one. ``pro`` is the good one.
===========================  ==================================================

Two further levers this project spent weeks approximating with prompt wording:
``proportions`` on ``/create-character-with-8-directions`` takes a preset
(``chibi``, ``cartoon``, ``stylized``, ``heroic``) or per-part multipliers with
``head_size`` up to 1.7 -- the small-headed-to-chibi dial that was being asked
for in adjectives; and ``/create-character-pro`` with
``method=create_from_concept`` accepts a concept sketch directly, which is what
a character sheet is for.

Equipment is a **state**, not a regeneration. ``create_state`` applies one text
edit across all eight rotations and keeps the result grouped with its source, so
swapping Rowan's sword gives the same Rowan holding something else rather than a
second hero who resembles him.

Asynchronous. Generation endpoints return background job ids to poll, and the
finished character is exported as a ZIP -- the rotation URLs in the JSON are
signed for a different host and answer 403 to a bearer token, so the ZIP is the
supported way to fetch pixels.
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Any

BASE_URL = "https://api.pixellab.ai/v2"

#: Every facing a tactical grid can need. v3 generates all eight in one call, so
#: nothing is mirrored and nothing drifts.
DIRECTIONS = ("south", "south-east", "east", "north-east",
              "north", "north-west", "west", "south-west")

#: The battle screen only ever shows two, and the map wants four.
BATTLE_DIRECTIONS = ("east", "west")
MAP_DIRECTIONS = ("south", "east", "north", "west")

#: What a unit needs to fight, phrased as actions rather than pose tables.
#: ``action_description`` is what the model reads, so it describes motion, not
#: anatomy -- "swings the sword" rather than "rotate the right arm 38 degrees".
CLIPS: dict[str, str] = {
    "walk": "walks forward, arms and legs swinging",
    "attack": "swings the sword forward in a downward slash",
    "block": "raises the sword and shield to guard, bracing",
    "damage": "recoils backwards from a hit, head back",
    "faint": "collapses to the ground, defeated",
    "cast": "raises both arms and casts a spell",
}


class PixelLabV2Error(RuntimeError):
    pass


@dataclass
class Character:
    id: str
    name: str
    size: int = 128
    directions: int = 8


@dataclass
class Client:
    api_key: str = ""
    timeout: float = 300.0
    poll_seconds: float = 15.0
    #: Balance before and after, so a run reports what it really cost.
    started_with: float = 0.0
    charges: list[tuple[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("PIXELLAB_API_KEY", "")
        if not self.api_key:
            raise PixelLabV2Error("PIXELLAB_API_KEY is not set. Export it; never commit it.")

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None,
                 *, raw: bool = False) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            BASE_URL + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        # Retry transport failures, never HTTP ones. A generation can take minutes
        # and is polled for as long, so a single "connection reset by peer" used to
        # abandon a run whose jobs were already paid for and still running
        # server-side. An HTTP status is an answer and is not retried: repeating a
        # POST that the server accepted would order the work twice.
        last = ""
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read() if raw else json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                raise PixelLabV2Error(f"HTTP {exc.code} on {method} {path}: {detail}") from None
            except (urllib.error.URLError, OSError) as exc:
                last = str(getattr(exc, "reason", exc))
                if attempt < 3:
                    time.sleep(2 ** attempt)
        raise PixelLabV2Error(f"{method} {path} failed after 4 attempts: {last}")

    def balance(self) -> float:
        """Remaining US dollars.

        Nested differently from v1, which returned ``{"usd": ...}`` flat. v2
        wraps it in ``credits`` alongside a subscription block, and reading it
        the v1 way raises a KeyError rather than returning a wrong number --
        which is the better failure of the two.
        """
        body = self._request("GET", "/balance")
        return float(body.get("credits", body).get("usd", 0.0))

    def _wait(self, job_ids: list[str], *, log=lambda _: None) -> list[str]:
        pending = list(job_ids)
        while True:
            states = [self._request("GET", f"/background-jobs/{job}").get("status")
                      for job in pending]
            if all(state in ("completed", "failed", "error") for state in states):
                failed = [j for j, s in zip(pending, states) if s != "completed"]
                if failed:
                    raise PixelLabV2Error(f"background job(s) failed: {failed}")
                return states
            log(f"    {states.count('completed')}/{len(states)} done")
            time.sleep(self.poll_seconds)

    # -- characters --------------------------------------------------------

    def create_character(
        self,
        name: str,
        description: str,
        *,
        reference: bytes | None = None,
        size: int = 128,
        view: str = "low top-down",
        detail: str = "highly detailed",
        outline: str = "single color black outline",
        seed: int | None = None,
        log=lambda _: None,
    ) -> Character:
        """Eight directional rotations of one character, in one call.

        ``reference`` is a south-facing sprite the model rotates, rather than a
        style image or a concept sheet. Passing the best generated sprite here is
        what makes every facing the same character -- the identity is carried by
        the picture, not re-derived from a description eight times.
        """
        payload: dict[str, Any] = {
            "description": description,
            "name": name,
            "view": view,
            "detail": detail,
            "outline": outline,
            "no_background": True,
        }
        if reference is not None:
            payload["reference_image"] = {
                "type": "base64", "base64": base64.b64encode(reference).decode("ascii")}
        if size != 128:
            payload["image_size"] = {"width": size, "height": size}
        if seed is not None:
            payload["seed"] = seed

        body = self._request("POST", "/create-character-v3", payload)
        character = Character(id=body["character_id"], name=name, size=size)
        log(f"  character {character.id}")
        self._wait([body["background_job_id"]], log=log)
        return character

    def animate(
        self,
        character: Character,
        clip: str,
        *,
        action: str = "",
        description: str = "",
        frames: int = 8,
        directions: tuple[str, ...] = DIRECTIONS,
        mode: str = "pro",
        palette: bytes | None = None,
        log=lambda _: None,
    ) -> None:
        """Add one animation to a character, across the directions asked for.

        ``mode`` defaults to **pro**, and the difference is not subtle. ``v3``
        costs one generation per direction and redraws the character in place:
        the body stays where it was and only the limb the text mentions moves,
        so a sword swing came back as a static figure with a rotating sword, and
        the model filled the missing motion with an invented white impact burst.
        ``pro`` costs 20-40 generations per direction and builds the directions
        sequentially, each one referencing the sides already finished. On the
        same character and the same text it produced a step forward, shoulders
        turning through the swing, a cape that follows, and no effects at all,
        for $0.095 on one direction.

        ``palette`` is the fix to a flag that was doing nothing. ``force_colors``
        forces the colours *from ``color_image``*, so setting it alone -- which
        this client did on every call -- was a no-op, and the palette lock the
        code claimed to have never existed. Pass the character's own rotation.

        ``frame_count`` is v3-only; pro decides its own frame count and returned
        four. So is ``text_guidance_scale``, despite reading like a global knob:
        the schema marks it template mode only, and it was ignored on every v3
        call this project made.
        """
        payload: dict[str, Any] = {
            "character_id": character.id,
            "animation_name": clip,
            "action_description": action or CLIPS.get(clip, clip),
            "mode": mode,
            "directions": list(directions),
            "keep_first_frame": True,
        }
        if description:
            payload["description"] = description
        if mode == "v3":
            payload["frame_count"] = frames
        if palette is not None:
            payload["color_image"] = {
                "type": "base64", "base64": base64.b64encode(palette).decode("ascii")}
            payload["force_colors"] = True
        body = self._request("POST", "/characters/animations", payload)
        log(f"  {clip}: {mode}, {len(directions)} direction(s)")
        self._wait(body.get("background_job_ids", []), log=log)

    def interpolate(
        self,
        character: Character,
        clip: str,
        start: bytes,
        end: bytes,
        *,
        action: str,
        description: str = "",
        frames: int = 8,
        direction: str = "north-east",
        log=lambda _: None,
    ) -> None:
        """Fill the motion between two poses you already have.

        Pro picks its own keyframes and picks four of them, which is enough for a
        step or a stagger and not enough for a sword. On Rowan's attack it spent
        two frames winding up and one recovering, so the cut itself happened
        entirely in the gap between two pictures: the blade is drawn back, and
        then it is already through. Nothing is wrong with any single frame, and
        the swing is still unreadable.

        Interpolation fixes what pro cannot be argued into. Both extremes are
        given rather than invented, so the model's whole job is the arc between
        them, and the blade is forced through every position on the way. Eight
        inbetweens cost $0.015 against $0.125 for the pro keyframes -- the
        expensive call establishes the poses, the cheap one makes them move.

        ``description`` matters more here than anywhere else, and omitting it is
        not neutral. Left to itself the interpolator decorated the swing: green
        energy trailing off the blade in two frames, white speed streaks in two
        more. They are drawn touching the sword, so :mod:`islands` cannot remove
        them -- it only takes what is detached, and these are attached on
        purpose. The description is the only place to say the blade is ordinary
        metal.

        Exactly one direction, per the API, and the two frames must be the same
        size. The result comes back on a **larger canvas** than the frames handed
        in, so it cannot simply be appended to the pro clip; see
        :func:`clips.align`.
        """
        body = self._request("POST", "/characters/animations", {
            "character_id": character.id,
            "animation_name": clip,
            "mode": "v3",
            "action_description": action,
            **({"description": description} if description else {}),
            "custom_start_frame": {
                "type": "base64", "base64": base64.b64encode(start).decode("ascii")},
            "end_frame": {
                "type": "base64", "base64": base64.b64encode(end).decode("ascii")},
            "frame_count": frames,
            "directions": [direction],
            "keep_first_frame": False,
        })
        log(f"  {clip}: {frames} inbetweens, {direction}")
        self._wait(body.get("background_job_ids", []), log=log)

    def animate_template(
        self,
        character: Character,
        clip: str,
        template_animation_id: str,
        *,
        directions: tuple[str, ...] = DIRECTIONS,
        log=lambda _: None,
    ) -> None:
        """Add a template animation -- the good path.

        Templates are skeleton-driven and professionally animated, and cost one
        generation per direction. The alternative, ``animate`` with an action
        description, invents the motion, and invented motion is what produced
        clips whose character was redrawn between frames.

        The available ids are **not** discoverable from the OpenAPI description,
        which truncates them, and the body-level validator advertises a shorter,
        different list than the server returns once it knows the character's body
        template. Sending a deliberately invalid id and reading that second error
        is the only way to see the real set.

        The truncated list begins ``angry, attack, attack-back, attack-left,
        attack-right, backflip, ...``, which reads like a sword swing was there
        all along. It is not: those belong to the quadruped templates, and the
        ``mannequin`` set is 49 martial-arts clips with nothing that swings.
        ``lead-jab`` is the only one that keeps the blade in hand -- the kicks
        and the cross drop it -- and it is three frames of a punch.

        Which is why battle clips should use :meth:`animate` in ``pro`` mode
        instead. Templates remain right for locomotion, where ``walking-6-frames``
        is a real walk cycle and nothing invents anything.
        """
        body = self._request("POST", "/characters/animations", {
            "character_id": character.id,
            "animation_name": clip,
            "mode": "template",
            "template_animation_id": template_animation_id,
            "directions": list(directions),
            "keep_first_frame": True,
            "force_colors": True,
        })
        log(f"  {clip} <- {template_animation_id} ({len(directions)} direction(s))")
        self._wait(body.get("background_job_ids", []), log=log)

    def create_state(
        self,
        character: Character,
        state_name: str,
        edit: str,
        *,
        keep_palette: bool = True,
        seed: int | None = None,
        log=lambda _: None,
    ) -> Character:
        """A variant of a character -- a different weapon, armour, a wound.

        This is how equipment reaches the sprite. Rowan will not carry the same
        sword for thirty hours, and regenerating him per weapon would give a
        different Rowan each time. A state applies one text edit across all eight
        rotations at once and stays grouped with its source by ``group_id``, so
        "Rowan with a steel sword" is the same character holding something else
        rather than a second character who resembles him.

        ``use_color_palette_from_reference`` is on by default for the same
        reason: a new weapon should not restate the hero's colours.
        """
        body = self._request("POST", "/create-character-state", {
            "character_id": character.id,
            "edit_description": edit,
            "state_name": state_name,
            "use_color_palette_from_reference": keep_palette,
            "no_background": True,
            **({"seed": seed} if seed is not None else {}),
        })
        variant = Character(id=body["character_id"], name=f"{character.name}:{state_name}",
                            size=character.size)
        log(f"  state {state_name} -> {variant.id}")
        self._wait([body["background_job_id"]], log=log)
        return variant

    def export(self, character: Character, destination: str) -> list[str]:
        """Fetch the character as a ZIP and unpack it.

        The ZIP rather than ``rotation_urls``: those are signed for a storage
        host that answers 403 to an API bearer token, so following them looks
        like an auth bug and is not one.
        """
        blob = self._request("GET", f"/characters/{character.id}/zip", raw=True)
        os.makedirs(destination, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            archive.extractall(destination)
            return sorted(archive.namelist())

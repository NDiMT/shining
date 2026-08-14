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

``/v2/llms.txt`` exists and is written for exactly this purpose. It was there the
whole time.

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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read() if raw else json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise PixelLabV2Error(f"HTTP {exc.code} on {method} {path}: {detail}") from None
        except urllib.error.URLError as exc:
            raise PixelLabV2Error(f"{method} {path} failed: {exc.reason}") from None

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
        frames: int = 6,
        directions: tuple[str, ...] = DIRECTIONS,
        text_guidance_scale: float = 8.0,
        log=lambda _: None,
    ) -> None:
        """Add one animation to a character, across the directions asked for.

        ``keep_first_frame`` and ``force_colors`` are always on. The first pins
        every clip to the character's own idle frame so a swing starts from the
        pose the player was just looking at; the second locks the palette, which
        this project previously implemented by hand and got wrong twice.
        """
        payload = {
            "character_id": character.id,
            "animation_name": clip,
            "action_description": action or CLIPS.get(clip, clip),
            "frame_count": frames,
            "directions": list(directions),
            "keep_first_frame": True,
            "force_colors": True,
            "text_guidance_scale": text_guidance_scale,
        }
        body = self._request("POST", "/characters/animations", payload)
        log(f"  {clip}: {len(directions)} direction(s)")
        self._wait(body.get("background_job_ids", []), log=log)

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

"""PixelLab client. Standard library only, like the rest of the tooling.

Endpoints, verified against ``/v1/openapi.json`` on 2026-08-14 rather than taken
from documentation:

    POST  /generate-image-pixflux      text -> sprite
    POST  /generate-image-bitforge     text + style reference -> sprite
    POST  /rotate                      one direction -> another
    POST  /estimate-skeleton           sprite -> 18 labelled keypoints
    POST  /animate-with-skeleton       posed keypoints -> frames (exactly 3)
    POST  /animate-with-text           action name -> frames
    GET   /balance                     remaining USD

Billing is **US dollars, not credits**, and every response carries its own
``usage.usd``. Measured on the first run:

    64x64 sprite (pixflux)      $0.0066
    rotate to one direction     $0.0111 - $0.0125
    4-frame animation           $0.0126 - $0.0156

which puts a full character -- base sprite, three more directions, five clips in
four directions -- at roughly $0.34. That is the number the whole 2D decision
rests on, so it is measured here rather than estimated, and ``spent`` accumulates
the real figures as a run proceeds.

The key comes from ``PIXELLAB_API_KEY`` and is never written to a log, a
provenance record or a generated file.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE_URL = "https://api.pixellab.ai/v1"

#: The API rejects anything else on the animation endpoints, and ``rotate``
#: accepts only these squares. 64 is what the game uses: it is the only size
#: ``animate-with-text`` supports.
SPRITE_SIZES = (16, 32, 64, 128)
ANIMATION_SIZE = 64

#: A tactical grid needs facings. Eight are available; the game uses four and
#: mirrors, because a rotation costs about as much as a fresh sprite.
DIRECTIONS = ("north", "north-east", "east", "south-east",
              "south", "south-west", "west", "north-west")

CAMERA_VIEWS = ("side", "low top-down", "high top-down")

OUTLINES = ("single color black outline", "single color outline",
            "selective outline", "lineless")
SHADINGS = ("flat shading", "basic shading", "medium shading",
            "detailed shading", "highly detailed shading")
DETAILS = ("low detail", "medium detail", "highly detailed")


class PixelLabError(RuntimeError):
    pass


@dataclass
class Client:
    """Thin, synchronous PixelLab client that tracks what it has spent."""

    api_key: str = ""
    timeout: float = 420.0
    #: Real dollars reported by the API, accumulated across calls.
    spent: float = 0.0
    #: Every ``usage.usd`` seen, so a batch can be broken down after the fact.
    charges: list[tuple[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("PIXELLAB_API_KEY", "")
        if not self.api_key:
            raise PixelLabError(
                "PIXELLAB_API_KEY is not set. Export it; never commit it."
            )

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            BASE_URL + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise PixelLabError(f"HTTP {exc.code} on {method} {path}: {detail}") from None
        except urllib.error.URLError as exc:
            raise PixelLabError(f"{method} {path} failed: {exc.reason}") from None

        if isinstance(body, dict):
            usd = float((body.get("usage") or {}).get("usd", 0.0))
            if usd:
                self.spent += usd
                self.charges.append((path, usd))
        return body

    def balance(self) -> float:
        """Remaining balance in US dollars."""
        return float(self._request("GET", "/balance").get("usd", 0.0))

    # -- generation --------------------------------------------------------

    def generate(
        self,
        description: str,
        *,
        size: int = ANIMATION_SIZE,
        negative: str = "",
        view: str = "high top-down",
        direction: str = "south",
        outline: str = "single color black outline",
        shading: str = "basic shading",
        detail: str = "medium detail",
        style_image: bytes | None = None,
        style_strength: int = 50,
        init_image: bytes | None = None,
        init_image_strength: int = 300,
        no_background: bool = True,
        text_guidance_scale: float = 8.0,
        seed: int | None = None,
    ) -> bytes:
        """One sprite. Style-matched when ``style_image`` is given.

        Two endpoints behind one method, chosen by whether there is a style
        reference, because the choice is mechanical and the caller should not
        have to know the difference: ``pixflux`` invents a look, ``bitforge``
        matches one. Every asset after the first should be matching, or the cast
        drifts -- which is the failure the 3D pipeline spent five generations on.
        """
        payload: dict[str, Any] = {
            "description": description,
            "negative_description": negative,
            "image_size": {"width": size, "height": size},
            "view": view,
            "direction": direction,
            "outline": outline,
            "shading": shading,
            "detail": detail,
            "no_background": no_background,
            "text_guidance_scale": text_guidance_scale,
        }
        if seed is not None:
            payload["seed"] = seed
        if init_image is not None:
            # Seeds the generation from an existing picture. This is how the
            # director's concept sheet reaches the sprite: as an *init* image,
            # never a style one. The sheet is anime line art, so styling to it
            # would ask for anime line art in a 128px frame; seeding from it asks
            # for this design, drawn in our style. Lower strength follows it more
            # closely -- 300 is the API default and barely follows it at all.
            payload["init_image"] = _encode(_match_size(init_image, size))
            payload["init_image_strength"] = init_image_strength

        if style_image is None:
            return self._image(self._request("POST", "/generate-image-pixflux", payload))

        payload["style_image"] = _encode(_match_size(style_image, size))
        payload["style_strength"] = style_strength
        return self._image(self._request("POST", "/generate-image-bitforge", payload))

    def rotate(
        self,
        sprite: bytes,
        *,
        to_direction: str,
        from_direction: str = "south",
        size: int = ANIMATION_SIZE,
        view: str = "high top-down",
        image_guidance_scale: float = 3.0,
        seed: int | None = None,
    ) -> bytes:
        """The same character seen from another facing."""
        if to_direction not in DIRECTIONS or from_direction not in DIRECTIONS:
            raise PixelLabError(f"direction must be one of {DIRECTIONS}")
        payload: dict[str, Any] = {
            "image_size": {"width": size, "height": size},
            "from_image": _encode(sprite),
            "from_view": view,
            "to_view": view,
            "from_direction": from_direction,
            "to_direction": to_direction,
            "image_guidance_scale": image_guidance_scale,
        }
        if seed is not None:
            payload["seed"] = seed
        return self._image(self._request("POST", "/rotate", payload))

    def animate(
        self,
        sprite: bytes,
        *,
        description: str,
        action: str,
        frames: int = 4,
        direction: str = "south",
        view: str = "high top-down",
        image_guidance_scale: float = 1.4,
        text_guidance_scale: float = 8.0,
        seed: int | None = None,
    ) -> list[bytes]:
        """Frames for one clip, from an action name.

        ``animate-with-text`` rather than ``animate-with-skeleton``: the skeleton
        endpoint wants a posed keypoint set per frame and accepts exactly three
        frames, which means authoring the animation by hand. This one takes the
        word "walk". Measured, walk came back usable on the first try and a sword
        swing did not -- the character lost his face behind the arc -- so raising
        ``image_guidance_scale`` is the first lever for a clip that drifts off
        the reference.

        64x64 only. The API rejects every other size here.
        """
        payload: dict[str, Any] = {
            "image_size": {"width": ANIMATION_SIZE, "height": ANIMATION_SIZE},
            "description": description,
            "action": action,
            "reference_image": _encode(sprite),
            "n_frames": frames,
            "view": view,
            "direction": direction,
            "image_guidance_scale": image_guidance_scale,
            "text_guidance_scale": text_guidance_scale,
        }
        if seed is not None:
            payload["seed"] = seed
        body = self._request("POST", "/animate-with-text", payload)
        return [_decode(image) for image in body.get("images", [])]

    def animate_skeleton(
        self,
        sprite: bytes,
        *,
        skeleton_frames: list[list[dict]],
        size: int = 128,
        direction: str = "east",
        view: str = "side",
        guidance_scale: float = 4.0,
        seed: int | None = None,
    ) -> list[bytes]:
        """Frames for one clip, from three posed skeletons.

        The route to a Shining Force II-scale attack screen. ``animate-with-text``
        is capped at 64x64; this one goes to 256x256, which is the difference
        between a map sprite and a battle sprite.

        **Exactly three frames**, and the API answers a 422 rather than
        truncating, so the check is here where the error can name the real
        problem. Longer sequences are chained windows -- which is also how the
        attack screen reads: approach, strike, reaction are three beats, not one
        continuous take.
        """
        if len(skeleton_frames) != 3:
            raise PixelLabError(
                f"animate-with-skeleton takes exactly 3 frames, got {len(skeleton_frames)}. "
                "Chain windows for anything longer."
            )
        payload: dict[str, Any] = {
            "image_size": {"width": size, "height": size},
            "reference_image": _encode(sprite),
            "skeleton_keypoints": [_integral_z(frame) for frame in skeleton_frames],
            "view": view,
            "direction": direction,
            "guidance_scale": guidance_scale,
        }
        if seed is not None:
            payload["seed"] = seed
        body = self._request("POST", "/animate-with-skeleton", payload)
        return [_decode(image) for image in body.get("images", [])]

    def estimate_skeleton(self, sprite: bytes) -> list[dict]:
        """Eighteen labelled keypoints — NOSE, LEFT EYE, and so on.

        Not used by the generation path, which takes action names instead. It is
        here because it is the only way to ask "did this sprite come back as a
        humanoid at all", which is the 2D equivalent of the skeleton check the
        3D validator ran.
        """
        body = self._request("POST", "/estimate-skeleton", {"image": _encode(sprite)})
        return body.get("keypoints", [])

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _image(body: dict) -> bytes:
        image = body.get("image")
        if image is None:
            raise PixelLabError(f"no image in response: {sorted(body)}")
        return _decode(image)


def _integral_z(frame: list[dict]) -> list[dict]:
    """Round ``z_index`` to an integer, because the API is asymmetric about it.

    ``estimate-skeleton`` hands back fractional depths (-3.5 was in the first
    real skeleton) and ``animate-with-skeleton`` rejects them with a 422:
    "Input should be a valid integer, got a number with a fractional part". Its
    own output is not valid input. Fixed here rather than in the pose maths,
    which has no business knowing about a transport quirk.
    """
    return [dict(point, z_index=int(round(float(point.get("z_index", 0))))) for point in frame]


def _match_size(image: bytes, size: int) -> bytes:
    """Resize a style reference to the output size, without smoothing.

    bitforge rejects a mismatch outright -- "style_image must be size (128, 128),
    not torch.Size([64, 64])" -- so a 64px map sprite cannot style a 128px battle
    sprite as it stands. Nearest neighbour is the only correct filter here:
    anything else invents intermediate colours, and the palette is the thing the
    style reference exists to carry.

    Pillow is optional everywhere else in this package, so a caller without it
    gets the original bytes and the API's own error rather than a crash here.
    """
    try:
        import io

        from PIL import Image
    except ImportError:  # pragma: no cover - depends on the environment
        return image

    with Image.open(io.BytesIO(image)) as opened:
        if opened.size == (size, size):
            return image
        source = opened.convert("RGBA")

    # Fit, do not stretch. The first version resized straight to a square and
    # that is fine for a sprite, which is already square, and wrong for a concept
    # sheet: Rowan's side view is 282x966, and squashing it into 128x128 produced
    # a squat hunched figure at every seeding strength I tried. The distortion
    # looked like the model failing and was mine.
    ratio = min(size / source.width, size / source.height)
    width = max(1, round(source.width * ratio))
    height = max(1, round(source.height * ratio))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(source.resize((width, height), Image.NEAREST),
                 ((size - width) // 2, (size - height) // 2))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _encode(payload: bytes) -> dict[str, str]:
    return {"type": "base64", "base64": base64.b64encode(payload).decode("ascii")}


def _decode(image: Any) -> bytes:
    data = image["base64"] if isinstance(image, dict) else image
    return base64.b64decode(data)

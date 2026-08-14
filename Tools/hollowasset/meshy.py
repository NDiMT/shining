"""Minimal Meshy API client, standard library only.

Brief section 15 says not to add dependencies casually, and this tool runs in
CI, on the director's machine and inside AI sessions, so it uses nothing beyond
the Python standard library. ``urllib`` is entirely adequate for a handful of
JSON calls and a file download.

The client is deliberately thin: it knows how to create a task, wait for it and
download the result. Everything about *what* to generate lives in style.py and
the catalog; everything about *whether the result is acceptable* lives in
validate.py.

Endpoints confirmed live against the API on 2026-08-13:
    POST/GET  /openapi/v2/text-to-3d      preview and refine
    POST/GET  /openapi/v1/image-to-3d
    POST/GET  /openapi/v1/remesh
    POST/GET  /openapi/v1/rigging
    POST/GET  /openapi/v1/animations
    GET       /openapi/v1/balance
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

BASE_URL = "https://api.meshy.ai"

#: Task states the API reports. Anything not PENDING/IN_PROGRESS is terminal.
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}


class MeshyError(RuntimeError):
    """Any non-recoverable API failure."""


class TaskFailed(MeshyError):
    """A task reached a terminal state that was not SUCCEEDED."""

    def __init__(self, task: dict[str, Any]):
        self.task = task
        message = task.get("task_error", {}).get("message") or task.get("message") or "no detail"
        super().__init__(f"task {task.get('id')} finished {task.get('status')}: {message}")


@dataclass
class Client:
    """A Meshy API client.

    The key is read from ``MESHY_API_KEY`` by default. It is never written to
    logs, provenance records or generated documentation.
    """

    api_key: str = field(default_factory=lambda: os.environ.get("MESHY_API_KEY", ""))
    timeout: float = 60.0
    max_retries: int = 4
    #: Credits consumed by this client instance, for run summaries.
    credits_spent: int = 0

    def __post_init__(self) -> None:
        if not self.api_key:
            raise MeshyError(
                "no Meshy API key. Set MESHY_API_KEY in the environment; "
                "never commit it to the repository."
            )

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = f"{BASE_URL}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:400]
                # 4xx other than rate limiting means the request itself is wrong;
                # retrying an invalid prompt just burns wall-clock time.
                if exc.code == 429 or exc.code >= 500:
                    last_error = MeshyError(f"HTTP {exc.code} on {method} {path}: {detail}")
                else:
                    raise MeshyError(f"HTTP {exc.code} on {method} {path}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = MeshyError(f"{type(exc).__name__} on {method} {path}: {exc}")

            if attempt < self.max_retries - 1:
                time.sleep(2 ** (attempt + 1))

        raise last_error or MeshyError(f"{method} {path} failed")

    # -- account -----------------------------------------------------------

    def balance(self) -> int:
        """Remaining credits on the account."""
        return int(self._request("GET", "/openapi/v1/balance").get("balance", 0))

    # -- task creation -----------------------------------------------------

    def text_to_3d_preview(
        self,
        prompt: str,
        *,
        target_polycount: int,
        topology: str = "triangle",
        model_type: str = "lowpoly",
        pose_mode: str = "",
        origin_at: str = "bottom",
        ai_model: str = "latest",
        should_remesh: bool = True,
    ) -> str:
        """Create an untextured geometry task and return its id.

        ``model_type="lowpoly"`` is the whole reason this pipeline is viable:
        it makes Meshy generate the chunky faceted forms the brief wants
        instead of a dense organic mesh we then have to decimate down and lose
        the silhouette. ``should_remesh`` is forced on so ``target_polycount``
        and ``topology`` are actually honoured.
        """
        payload: dict[str, Any] = {
            "mode": "preview",
            "prompt": prompt,
            "model_type": model_type,
            "ai_model": ai_model,
            "should_remesh": should_remesh,
            "topology": topology,
            "target_polycount": int(target_polycount),
            "origin_at": origin_at,
            "target_formats": ["glb"],
            "moderation": True,
        }
        if pose_mode:
            payload["pose_mode"] = pose_mode
        return self._create("/openapi/v2/text-to-3d", payload)

    def text_to_3d_refine(
        self,
        preview_task_id: str,
        *,
        texture_prompt: str = "",
        texture_resolution: str = "2k",
        enable_pbr: bool = False,
        ai_model: str = "latest",
    ) -> str:
        """Texture a completed preview task and return the refine task id.

        ``enable_pbr`` defaults off. Brief section 8 is explicit that base
        colour plus good lighting is usually enough for stylized low-poly, and
        every extra map is another file to store, load and keep consistent.
        Turn it on per-asset for heroes and metal-heavy bosses.
        """
        payload: dict[str, Any] = {
            "mode": "refine",
            "preview_task_id": preview_task_id,
            "ai_model": ai_model,
            "enable_pbr": enable_pbr,
            "texture_resolution": texture_resolution,
            "target_formats": ["glb"],
            "moderation": True,
        }
        if texture_prompt:
            payload["texture_prompt"] = texture_prompt
        return self._create("/openapi/v2/text-to-3d", payload)

    def image_to_3d(
        self,
        image_urls: list[str],
        *,
        target_polycount: int,
        topology: str = "triangle",
        should_remesh: bool = True,
        should_texture: bool = True,
        ai_model: str = "latest",
        origin_at: str = "bottom",
    ) -> str:
        """Generate from concept references, per the brief's section 55 pipeline.

        This is the path for named characters: the director approves front,
        side and back concept art, and the mesh follows the approved design
        rather than whatever the text prompt happens to evoke that day.
        """
        if not image_urls:
            raise MeshyError("image_to_3d needs at least one reference image")

        payload: dict[str, Any] = {
            "ai_model": ai_model,
            "should_remesh": should_remesh,
            "should_texture": should_texture,
            "topology": topology,
            "target_polycount": int(target_polycount),
            "origin_at": origin_at,
            "target_formats": ["glb"],
            "moderation": True,
        }

        # One image and several images are different endpoints with differently
        # named fields, and getting it wrong is not a soft failure: posting
        # "image_urls" to the single endpoint returns
        # "Either image_url or input_task_id must be provided", which reads like
        # a missing-argument bug rather than a wrong-endpoint one.
        if len(image_urls) == 1:
            payload["image_url"] = image_urls[0]
            return self._create("/openapi/v1/image-to-3d", payload)
        payload["image_urls"] = image_urls
        return self._create("/openapi/v1/multi-image-to-3d", payload)

    def remesh(
        self,
        input_task_id: str,
        *,
        target_polycount: int,
        topology: str = "triangle",
    ) -> str:
        """Re-decimate an existing task's mesh to hit a triangle budget."""
        payload = {
            "input_task_id": input_task_id,
            "target_polycount": int(target_polycount),
            "topology": topology,
            "target_formats": ["glb"],
        }
        return self._create("/openapi/v1/remesh", payload)

    def rig(self, *, input_task_id: str = "", model_url: str = "", height_meters: float = 1.7) -> str:
        """Rig a textured humanoid. Requires the model to face +Z."""
        if not (input_task_id or model_url):
            raise MeshyError("rig() needs input_task_id or model_url")
        payload: dict[str, Any] = {"height_meters": height_meters}
        if input_task_id:
            payload["input_task_id"] = input_task_id
        else:
            payload["model_url"] = model_url
        return self._create("/openapi/v1/rigging", payload)

    def animate(self, rig_task_id: str, action_id: int, *, fps: int = 30) -> str:
        """Apply one library animation to a rigged character."""
        payload = {
            "rig_task_id": rig_task_id,
            "action_id": int(action_id),
            "post_process": {"operation_type": "change_fps", "fps": fps},
        }
        return self._create("/openapi/v1/animations", payload)

    def _create(self, path: str, payload: dict[str, Any]) -> str:
        result = self._request("POST", path, payload)
        task_id = result.get("result") or result.get("id")
        if not task_id:
            raise MeshyError(f"no task id in response from {path}: {result}")
        return str(task_id)

    # -- polling -----------------------------------------------------------

    #: Maps a task id prefix-free path lookup. Callers pass the endpoint they
    #: created the task on, because ids are not self-describing.
    def get(self, endpoint: str, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"{endpoint}/{task_id}")

    def wait(
        self,
        endpoint: str,
        task_id: str,
        *,
        poll_seconds: float = 10.0,
        timeout_seconds: float = 1800.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Block until a task reaches a terminal state.

        Polls rather than using the SSE stream endpoint: a dropped stream mid
        generation is a silent stall, whereas a dropped poll is one retry. The
        default 30 minute ceiling is generous for a texture pass and still
        stops a hung batch from running overnight.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            task = self.get(endpoint, task_id)
            status = task.get("status", "")
            if on_progress:
                on_progress(task)
            if status in TERMINAL:
                self.credits_spent += int(task.get("consumed_credits") or 0)
                if status != "SUCCEEDED":
                    raise TaskFailed(task)
                return task
            if time.monotonic() > deadline:
                raise MeshyError(
                    f"task {task_id} still {status or 'unknown'} after "
                    f"{timeout_seconds:.0f}s; check the Meshy dashboard"
                )
            time.sleep(poll_seconds)

    # -- download ----------------------------------------------------------

    def download(self, url: str, destination: str) -> int:
        """Download a result file. Returns bytes written.

        Meshy result URLs are pre-signed and expire, so assets are fetched to
        the repository immediately after generation rather than referenced by
        URL. Downloads to a temporary path and renames on success so an
        interrupted run cannot leave a truncated GLB that later validates as a
        corrupt file.
        """
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        temporary = f"{destination}.part"
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                request = urllib.request.Request(url, headers={"Accept": "*/*"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                with open(temporary, "wb") as handle:
                    handle.write(payload)
                os.replace(temporary, destination)
                return len(payload)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise MeshyError(f"download failed for {destination}: {last_error}")


#: Endpoints, for use with get()/wait().
TEXT_TO_3D = "/openapi/v2/text-to-3d"
IMAGE_TO_3D = "/openapi/v1/image-to-3d"
REMESH = "/openapi/v1/remesh"
RIGGING = "/openapi/v1/rigging"
ANIMATIONS = "/openapi/v1/animations"

"""The asset pipeline described in brief section 55.

    Concept -> references -> AI generation -> budget remesh -> texture
            -> rig -> animation -> GLB -> validator -> engine import

One job per catalog entry, each job driven entirely by data. Adding twelve
village props is an edit to a JSON file, never a change here. That is the point
of brief section 14: content is data, and a future session should be able to
extend the game's asset list without reading this module.

Cost discipline matters because credits are finite. Every job reports its
credits, ``--dry-run`` resolves prompts and paths without spending anything, and
the runner stops the batch if the account balance would go negative rather than
failing halfway through with assets half-generated.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from . import animations as anim
from . import budgets, glb, meshy, postprocess, provenance, style, validate

#: Rough credit cost per stage, used only for the pre-flight estimate. The
#: authoritative number is ``consumed_credits`` on each finished task, which is
#: what gets recorded in provenance.
CREDIT_ESTIMATE = {"preview": 5, "refine": 10, "remesh": 5, "rig": 5, "animation": 3}

Logger = Callable[[str], None]


def _noop(_: str) -> None:
    pass


@dataclass
class Job:
    """One asset to generate, fully resolved from its catalog entry."""

    asset_id: str
    asset_class: str
    subject: str
    prompt: style.Prompt
    budget: budgets.Budget
    output_path: str
    region: str = "neutral"
    references: list[str] = field(default_factory=list)
    enable_pbr: bool = False
    pose_mode: str = ""
    rig: bool = False
    animations: list[int] = field(default_factory=list)
    notes: str = ""

    @property
    def texture_resolution(self) -> str:
        """Meshy offers 2k, 4k and 8k.

        Brief section 8 wants 512 for generic assets and 1024 for standard
        characters, neither of which the API can produce directly, so
        everything is generated at 2k and downscaled in the post step. The
        validator fails any asset that reaches the engine still oversized, so
        the downscale cannot be quietly skipped.
        """
        return "2k"

    def estimate_credits(self) -> int:
        # The remesh is included because generation reliably overshoots
        # target_polycount, so in practice it almost always runs.
        total = CREDIT_ESTIMATE["preview"] + CREDIT_ESTIMATE["refine"] + CREDIT_ESTIMATE["remesh"]
        if self.rig:
            total += CREDIT_ESTIMATE["rig"]
        total += CREDIT_ESTIMATE["animation"] * len(self.animations)
        return total


@dataclass
class Result:
    job: Job
    downloaded: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    credits: int = 0
    report: validate.Report | None = None
    error: str = ""
    #: Automated corrections applied by postprocess, recorded in provenance.
    normalised: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error and (self.report is None or self.report.ok)


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------


def load_catalog(path: str, *, content_root: str = "Content/Models") -> list[Job]:
    """Read a catalog file into resolved jobs.

    Fails on the whole file rather than skipping bad entries: a typo in an
    asset class should stop the batch, not silently generate eleven of twelve
    assets and leave someone to notice later.
    """
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)

    default_region = str(document.get("region", "neutral"))
    entries = document.get("assets", [])
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: no 'assets' array")

    seen: set[str] = set()
    jobs: list[Job] = []
    for index, entry in enumerate(entries):
        where = f"{path}: assets[{index}]"
        asset_id = str(entry.get("id", "")).strip()
        if not asset_id:
            raise ValueError(f"{where}: missing 'id'")
        if asset_id in seen:
            raise ValueError(f"{where}: duplicate id {asset_id!r}")
        seen.add(asset_id)

        asset_class = str(entry.get("class", "")).strip()
        try:
            budget = budgets.get(asset_class)
        except KeyError as exc:
            raise ValueError(f"{where}: {exc}") from None

        subject = str(entry.get("subject", "")).strip()
        if not subject:
            raise ValueError(f"{where}: missing 'subject'")

        region = str(entry.get("region", default_region))
        if region not in style.REGIONS:
            raise ValueError(
                f"{where}: unknown region {region!r}; known: {', '.join(style.region_keys())}"
            )

        rig = bool(entry.get("rig", budget.needs_skeleton))
        jobs.append(
            Job(
                asset_id=asset_id,
                asset_class=asset_class,
                subject=subject,
                prompt=style.build(
                    subject,
                    asset_class,
                    region=region,
                    extra=str(entry.get("extra", "")),
                    avoid=str(entry.get("avoid", "")),
                ),
                budget=budget,
                output_path=os.path.join(content_root, budget.subdir, f"{asset_id}.glb"),
                region=region,
                references=[str(u) for u in entry.get("references", [])],
                enable_pbr=bool(entry.get("enable_pbr", False)),
                pose_mode=str(entry.get("pose", "t-pose" if budget.needs_skeleton else "")),
                rig=rig,
                animations=anim.resolve_all(entry.get("animations", [])),
                notes=str(entry.get("notes", "")),
            )
        )
    return jobs


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_job(
    job: Job,
    client: meshy.Client,
    *,
    log: Logger = _noop,
    provenance_path: str = provenance.DEFAULT_PATH,
    poll_seconds: float = 10.0,
) -> Result:
    """Generate, download, validate and record one asset.

    Stage order matters and is not obvious. The triangle budget is enforced
    *before* rigging, for two reasons: the rigging API caps input at 300k faces,
    and remeshing an already-rigged model would discard its skeleton. So the raw
    mesh is downloaded and measured first, remeshed if it overshot, and only then
    handed to the rigger.
    """
    result = Result(job=job)
    try:
        model_url, mesh_task_id = _generate_mesh(
            job, client, log=log, poll_seconds=poll_seconds, result=result
        )

        log(f"  downloading -> {job.output_path}")
        written = client.download(model_url, job.output_path)
        result.downloaded.append(job.output_path)
        log(f"  wrote {written / 1024:.0f} KiB")

        mesh_task_id = _enforce_triangle_budget(
            job, client, mesh_task_id, log=log, poll_seconds=poll_seconds, result=result
        )

        if job.rig:
            rigged_url = _rig_and_animate(
                job, client, mesh_task_id, log=log, poll_seconds=poll_seconds, result=result
            )
            log("  downloading rigged model")
            client.download(rigged_url, job.output_path)

        _normalise(job, log=log, result=result)

        result.report = validate.validate(
            job.output_path, job.asset_class, expect_animations=bool(job.animations)
        )
        for finding in result.report.findings:
            if finding.severity >= validate.Severity.WARN:
                log(f"  {finding}")

    except (meshy.MeshyError, OSError, ValueError) as exc:
        result.error = str(exc)
        log(f"  FAILED: {exc}")

    result.credits = client.credits_spent
    _record(job, result, provenance_path)
    return result


def _generate_mesh(
    job: Job, client: meshy.Client, *, log: Logger, poll_seconds: float, result: Result
) -> tuple[str, str]:
    """Produce a textured mesh. Returns (glb url, task id)."""
    if job.references:
        log(f"  image-to-3d from {len(job.references)} reference(s)")
        task_id = client.image_to_3d(
            job.references,
            target_polycount=job.budget.tri_target,
            should_texture=True,
        )
        result.task_ids.append(task_id)
        task = client.wait(
            meshy.IMAGE_TO_3D, task_id, poll_seconds=poll_seconds, on_progress=_progress(log)
        )
        return _glb_url(task), task_id

    log(f"  preview at {job.budget.tri_target:,} tris (lowpoly)")
    preview_id = client.text_to_3d_preview(
        job.prompt.geometry,
        target_polycount=job.budget.tri_target,
        pose_mode=job.pose_mode,
    )
    result.task_ids.append(preview_id)
    client.wait(meshy.TEXT_TO_3D, preview_id, poll_seconds=poll_seconds, on_progress=_progress(log))

    log(f"  refine, texture {job.texture_resolution}, pbr={job.enable_pbr}")
    refine_id = client.text_to_3d_refine(
        preview_id,
        texture_prompt=job.prompt.texture,
        texture_resolution=job.texture_resolution,
        enable_pbr=job.enable_pbr,
    )
    result.task_ids.append(refine_id)
    task = client.wait(
        meshy.TEXT_TO_3D, refine_id, poll_seconds=poll_seconds, on_progress=_progress(log)
    )
    return _glb_url(task), refine_id


def _rig_and_animate(
    job: Job,
    client: meshy.Client,
    input_task_id: str,
    *,
    log: Logger,
    poll_seconds: float,
    result: Result,
) -> str:
    """Rig the mesh and bake the requested animation clips. Returns the rigged GLB url.

    Meshy returns one GLB per animation rather than a single multi-clip file, so
    each clip is downloaded beside the base model as ``<asset>__<clip>.glb``,
    named with the brief's animation name rather than the provider's action id.
    Merging them into one GLB with a shared skeleton is a Blender step; see
    docs/ASSET_PIPELINE.md.
    """
    log(f"  rigging at {job.budget.height_m}m")
    rig_id = client.rig(input_task_id=input_task_id, height_meters=job.budget.height_m or 1.7)
    result.task_ids.append(rig_id)
    rig_task = client.wait(
        meshy.RIGGING, rig_id, poll_seconds=poll_seconds, on_progress=_progress(log)
    )
    rigged = (rig_task.get("result") or {}).get("rigged_character_glb_url") or _glb_url(rig_task)

    stem, _ = os.path.splitext(job.output_path)
    for action_id in job.animations:
        clip = anim.name_for(action_id)
        log(f"  animation {clip} (action {action_id})")
        animation_id = client.animate(rig_id, action_id)
        result.task_ids.append(animation_id)
        task = client.wait(
            meshy.ANIMATIONS, animation_id, poll_seconds=poll_seconds, on_progress=_progress(log)
        )
        url = (task.get("result") or {}).get("animation_glb_url")
        if not url:
            raise meshy.MeshyError(f"animation {action_id} returned no GLB url")
        destination = f"{stem}__{clip}.glb"
        client.download(url, destination)
        result.downloaded.append(destination)

    return rigged


def _enforce_triangle_budget(
    job: Job,
    client: meshy.Client,
    input_task_id: str,
    *,
    log: Logger,
    poll_seconds: float,
    result: Result,
) -> str:
    """Remesh through the API if the download came back over budget.

    Returns the task id that now holds the current mesh — the remesh task if one
    ran, otherwise the input task. Callers must use the returned id for any
    downstream stage, because rigging has to operate on the decimated mesh.

    ``target_polycount`` on the generation call is a request, not a guarantee:
    measured against a real run, a 550-triangle barrel came back at 6,392. So the
    budget is enforced after the fact, by measuring the actual file and spending a
    remesh only when one is genuinely needed.

    Failure here is a warning rather than an error. An over-budget asset is still
    useful for blockout work, the validator will fail it before it reaches the
    engine, and losing the whole generation over a failed decimation would waste
    the credits already spent.
    """
    try:
        measured = glb.read(job.output_path)
    except (glb.GlbError, OSError) as exc:
        log(f"  cannot measure triangles: {exc}")
        return input_task_id

    _, soft_high = job.budget.tri_soft
    if measured.triangles <= soft_high:
        return input_task_id

    # Remesh to the TOP of the soft range, not the midpoint. Measured on a real
    # barrel: the generator produced a clean 6,392-triangle mesh with defined
    # staves and iron bands, and decimating it to the 550 midpoint destroyed both.
    # Every triangle inside the budget is a triangle worth keeping.
    target = soft_high
    ratio = measured.triangles / max(target, 1)
    log(f"  {measured.triangles:,} tris over the {soft_high:,} target, remeshing to {target:,}")
    if ratio > 4:
        log(
            f"  WARNING: that is a {ratio:.1f}x reduction. Decimation this aggressive "
            "usually erases the features the prompt asked for. Review the preview "
            "before accepting, and consider whether this class's budget is too tight."
        )
    try:
        remesh_id = client.remesh(input_task_id, target_polycount=target)
        result.task_ids.append(remesh_id)
        task = client.wait(
            meshy.REMESH, remesh_id, poll_seconds=poll_seconds, on_progress=_progress(log)
        )
        client.download(_glb_url(task), job.output_path)
        after = glb.read(job.output_path)
        log(f"  remeshed to {after.triangles:,} tris")
        return remesh_id
    except (meshy.MeshyError, glb.GlbError, OSError) as exc:
        log(f"  remesh failed, keeping the original mesh: {exc}")
        return input_task_id


def _normalise(job: Job, *, log: Logger, result: Result) -> None:
    """Bring the asset in line with our scale, origin and texture conventions.

    Recorded on the provenance row as automated edits, because they are real
    modifications to the generator's output and a future session should be able
    to see that they happened.
    """
    try:
        changes = postprocess.normalise(
            job.output_path,
            target_height=job.budget.height_m,
            texture_max=job.budget.texture_max,
        )
    except (postprocess.PostProcessError, OSError) as exc:
        log(f"  normalise failed: {exc}")
        return

    for line in changes.describe():
        log(f"  {line}")
    for line in changes.skipped:
        log(f"  skipped {line}")
    result.normalised = changes.describe()


def _glb_url(task: dict[str, Any]) -> str:
    urls = task.get("model_urls") or (task.get("result") or {}).get("model_urls") or {}
    url = urls.get("glb")
    if not url:
        raise meshy.MeshyError(f"task {task.get('id')} returned no GLB url; got keys {list(urls)}")
    return str(url)


def _progress(log: Logger) -> Callable[[dict[str, Any]], None]:
    last: dict[str, int] = {}

    def report(task: dict[str, Any]) -> None:
        progress = int(task.get("progress") or 0)
        # Only log on movement; a 30 minute poll would otherwise emit 180 lines.
        if progress != last.get("p"):
            last["p"] = progress
            log(f"    {task.get('status', '?')} {progress}%")

    return report


def _record(job: Job, result: Result, provenance_path: str) -> None:
    """Write the provenance row. Runs even on failure, so a failed generation
    leaves a trace rather than a silent gap in the asset history."""
    info = result.report.info if result.report else None
    if result.error:
        validation = f"generation failed: {result.error[:120]}"
    elif result.report is None:
        validation = "unvalidated"
    elif result.report.ok:
        validation = f"pass ({len(result.report.warnings)} warning(s))"
    else:
        validation = "FAIL: " + "; ".join(f.check for f in result.report.errors)

    record = provenance.Record(
        asset_id=job.asset_id,
        file_path=job.output_path,
        asset_type=job.asset_class,
        generation_tool="Meshy (text-to-3d lowpoly)"
        if not job.references
        else "Meshy (image-to-3d)",
        generation_date=provenance.today(),
        tool_plan_license=provenance.DEFAULT_LICENSE_NOTE,
        prompt=job.prompt.geometry,
        texture_prompt=job.prompt.texture,
        source_references=job.references,
        task_ids=result.task_ids,
        consumed_credits=result.credits,
        triangles=info.triangles if info else 0,
        max_texture_edge=info.max_texture_edge if info else 0,
        sha256=provenance.sha256_of(job.output_path)
        if os.path.exists(job.output_path)
        else "",
        validation=validation,
        commercial_rights_notes=job.notes,
        # Brief section 54's "manual edits" field, carrying the automated
        # corrections too. Prefixed so a hand repair in Blender stays
        # distinguishable from something the pipeline did on its own.
        manual_edits=[f"auto: {line}" for line in result.normalised],
    )
    provenance.append(record, provenance_path)


def run_batch(
    jobs: list[Job],
    client: meshy.Client,
    *,
    log: Logger = _noop,
    provenance_path: str = provenance.DEFAULT_PATH,
    poll_seconds: float = 10.0,
    stop_on_error: bool = False,
) -> list[Result]:
    """Run jobs in order, with a pre-flight credit check."""
    estimate = sum(job.estimate_credits() for job in jobs)
    balance = client.balance()
    log(f"{len(jobs)} job(s), estimated {estimate} credits, balance {balance}")
    if estimate > balance:
        raise meshy.MeshyError(
            f"estimated {estimate} credits exceeds balance {balance}; "
            "trim the catalog or top up before starting"
        )

    results: list[Result] = []
    for index, job in enumerate(jobs, start=1):
        log(f"[{index}/{len(jobs)}] {job.asset_id} ({job.asset_class})")
        result = run_job(
            job, client, log=log, provenance_path=provenance_path, poll_seconds=poll_seconds
        )
        results.append(result)
        if not result.ok and stop_on_error:
            log("stopping: --stop-on-error and this job did not pass")
            break
    return results

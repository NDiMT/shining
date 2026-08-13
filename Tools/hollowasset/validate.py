"""Asset validation, per brief sections 55 and 79.

The brief asks for automatic checks on triangle count, texture resolution,
missing skeleton, missing animations, invalid material, incorrect scale and
incorrect orientation. All seven are implemented here.

This exists because generated content cannot be assumed correct. Meshy honours
``target_polycount`` approximately, occasionally exports a character lying on
its side, and will happily hand back a 2048px texture for a barrel. Catching
that here is cheap; catching it after two hundred assets are in the game is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from . import budgets, glb

#: Brief section 56. Humanoids share this skeleton so animations are reusable;
#: an asset missing any of these bones cannot play the shared animation set.
CANONICAL_BONES = [
    "root",
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "upperarm_l",
    "lowerarm_l",
    "hand_l",
    "upperarm_r",
    "lowerarm_r",
    "hand_r",
    "upperleg_l",
    "lowerleg_l",
    "foot_l",
    "upperleg_r",
    "lowerleg_r",
    "foot_r",
]

#: Bone naming varies between rigging tools, so matching is done on normalised
#: names. Extend this map rather than renaming bones by hand in Blender.
BONE_ALIASES = {
    "pelvis": "hips",
    "spine01": "spine",
    "spine02": "chest",
    "spine1": "spine",
    "spine2": "chest",
    "torso": "chest",
    "leftarm": "upperarm_l",
    "rightarm": "upperarm_r",
    "leftforearm": "lowerarm_l",
    "rightforearm": "lowerarm_r",
    "lefthand": "hand_l",
    "righthand": "hand_r",
    "leftupleg": "upperleg_l",
    "rightupleg": "upperleg_r",
    "leftleg": "lowerleg_l",
    "rightleg": "lowerleg_r",
    "leftfoot": "foot_l",
    "rightfoot": "foot_r",
    "armature": "root",
}

#: Scale tolerance. A hero at 1.4m or 2.1m still reads fine on a tactical
#: camera; one at 0.2m or 17m does not, and usually means unit confusion.
SCALE_TOLERANCE = 0.35


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    ERROR = 2


@dataclass
class Finding:
    severity: Severity
    check: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.name:5}] {self.check}: {self.message}"


@dataclass
class Report:
    path: str
    asset_class: str
    info: glb.GlbInfo | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARN]

    def add(self, severity: Severity, check: str, message: str) -> None:
        self.findings.append(Finding(severity, check, message))

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        counts = f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        return f"{status}  {self.path}  [{self.asset_class}]  {counts}"


def _strip(name: str) -> str:
    """Reduce a bone name to letters and digits, lowercased.

    Exporters vary on separators and prefixes, so ``upperarm_l``, ``UpperArm.L``
    and ``mixamorig:LeftArm`` all have to reduce to something comparable. The
    namespace prefix is dropped first, since Mixamo and Blender both use one.
    """
    tail = name.split(":")[-1]
    return "".join(c for c in tail.lower() if c.isalnum())


#: Stripped alias key -> stripped canonical name.
_ALIAS_LOOKUP = {_strip(alias): _strip(target) for alias, target in BONE_ALIASES.items()}

#: Stripped canonical name -> the canonical name as written, for reporting.
_CANONICAL_LOOKUP = {_strip(bone): bone for bone in CANONICAL_BONES}


def normalise_bone(name: str) -> str:
    """Map any exporter's bone name onto a canonical name where possible.

    Both sides of the comparison go through ``_strip``, which is the part that
    used to be wrong: comparing stripped rig names against unstripped canonical
    names meant every underscored bone such as ``upperarm_l`` reported missing.
    """
    key = _strip(name)
    return _ALIAS_LOOKUP.get(key, key)


def validate(path: str, asset_class: str, *, expect_animations: bool = False) -> Report:
    """Run every check against one GLB and return a report."""
    budget = budgets.get(asset_class)
    report = Report(path=path, asset_class=asset_class, info=None)

    try:
        info = glb.read(path)
    except (glb.GlbError, OSError) as exc:
        report.add(Severity.ERROR, "readable", str(exc))
        return report
    report.info = info

    _check_triangles(report, info, budget)
    _check_textures(report, info, budget)
    _check_materials(report, info)
    _check_scale(report, info, budget)
    _check_orientation(report, info, budget)
    _check_skeleton(report, info, budget)
    _check_animations(report, info, budget, expect_animations)
    _check_draw_cost(report, info)
    return report


def _check_triangles(report: Report, info: glb.GlbInfo, budget: budgets.Budget) -> None:
    low, high = budget.tri_soft
    count = info.triangles
    if count == 0:
        report.add(Severity.ERROR, "triangle_count", "mesh has no triangles")
    elif count > budget.tri_hard:
        report.add(
            Severity.ERROR,
            "triangle_count",
            f"{count:,} triangles exceeds the {budget.tri_hard:,} hard cap for "
            f"{budget.key}; run a remesh pass at {budget.tri_target:,}",
        )
    elif count > high:
        report.add(
            Severity.WARN,
            "triangle_count",
            f"{count:,} triangles is over the {low:,}-{high:,} target for {budget.key}",
        )
    elif count < low:
        report.add(
            Severity.WARN,
            "triangle_count",
            f"{count:,} triangles is under the {low:,}-{high:,} target; "
            "check the silhouette still reads",
        )
    else:
        report.add(Severity.INFO, "triangle_count", f"{count:,} triangles, within target")


def _check_textures(report: Report, info: glb.GlbInfo, budget: budgets.Budget) -> None:
    if not info.images:
        report.add(Severity.WARN, "texture_resolution", "no embedded textures; vertex colour only?")
        return
    for image in info.images:
        if image.width == 0 or image.height == 0:
            report.add(
                Severity.ERROR,
                "texture_resolution",
                f"image {image.name!r} is not embedded or has an unreadable header; "
                "GLBs must be self-contained",
            )
            continue
        edge = max(image.width, image.height)
        if edge > budget.texture_max:
            report.add(
                Severity.ERROR,
                "texture_resolution",
                f"image {image.name!r} is {image.width}x{image.height}, over the "
                f"{budget.texture_max}px budget for {budget.key}; downscale before import",
            )
        elif edge & (edge - 1):
            report.add(
                Severity.WARN,
                "texture_resolution",
                f"image {image.name!r} edge {edge}px is not a power of two",
            )
    if all(f.check != "texture_resolution" for f in report.findings):
        report.add(
            Severity.INFO,
            "texture_resolution",
            f"{len(info.images)} texture(s), max edge {info.max_texture_edge}px",
        )


def _check_materials(report: Report, info: glb.GlbInfo) -> None:
    if info.materials == 0:
        report.add(Severity.ERROR, "material", "no materials defined")
        return
    if info.untextured_materials:
        report.add(
            Severity.ERROR,
            "material",
            "material(s) with neither a base colour texture nor a base colour factor: "
            + ", ".join(info.untextured_materials),
        )
    if info.materials > 4:
        report.add(
            Severity.WARN,
            "material",
            f"{info.materials} materials; each one is an extra draw call, "
            "consider merging into an atlas (brief section 8)",
        )


def _check_scale(report: Report, info: glb.GlbInfo, budget: budgets.Budget) -> None:
    if budget.height_m is None:
        return
    if info.bounds_min is None:
        report.add(Severity.WARN, "scale", "no POSITION bounds; cannot check scale")
        return
    height = info.height
    expected = budget.height_m
    low = expected * (1 - SCALE_TOLERANCE)
    high = expected * (1 + SCALE_TOLERANCE)
    if not (low <= height <= high):
        report.add(
            Severity.ERROR,
            "scale",
            f"height {height:.2f}m is outside {low:.2f}-{high:.2f}m expected for "
            f"{budget.key}; glTF units are metres",
        )
    else:
        report.add(Severity.INFO, "scale", f"height {height:.2f}m")

    # Brief-adjacent but practically essential: grid placement assumes the mesh
    # origin sits on the ground plane.
    base = info.bounds_min[1]
    if abs(base) > max(0.05, expected * 0.05):
        report.add(
            Severity.WARN,
            "origin",
            f"lowest point is at y={base:.3f}, not 0; generate with origin_at=bottom "
            "or the asset will float or sink on the battle grid",
        )


def _check_orientation(report: Report, info: glb.GlbInfo, budget: budgets.Budget) -> None:
    """Heuristic orientation check.

    True facing direction cannot be recovered from geometry alone, so this
    catches the two failures that actually happen: a Z-up export (character
    lying on its back) and a character whose depth exceeds its width, which for
    a humanoid means it is facing along X instead of the +Z that Meshy rigging
    and our animations require.
    """
    if info.bounds_min is None or not budget.needs_skeleton:
        return
    width, height, depth = info.size
    if height <= 0:
        return
    if height < max(width, depth):
        report.add(
            Severity.ERROR,
            "orientation",
            f"bounds are {width:.2f}x{height:.2f}x{depth:.2f} (WxHxD); the tallest axis "
            "is not Y, so this is probably a Z-up export. glTF is Y-up",
        )
    elif depth > width * 1.6:
        report.add(
            Severity.WARN,
            "orientation",
            f"depth {depth:.2f}m exceeds width {width:.2f}m; character may face "
            "along X instead of +Z, which breaks shared animations",
        )
    else:
        report.add(Severity.INFO, "orientation", "Y-up, plausible +Z facing")


def _check_skeleton(report: Report, info: glb.GlbInfo, budget: budgets.Budget) -> None:
    if not budget.needs_skeleton:
        if info.joints:
            report.add(Severity.INFO, "skeleton", f"{len(info.joints)} joints on a static asset")
        return
    if not info.joints:
        report.add(
            Severity.ERROR,
            "skeleton",
            f"{budget.key} requires a skeleton; run the rigging pass before import",
        )
        return

    present = {normalise_bone(name) for name in info.joints}
    missing = [
        canonical for stripped, canonical in _CANONICAL_LOOKUP.items() if stripped not in present
    ]
    if missing:
        severity = Severity.ERROR if len(missing) > 3 else Severity.WARN
        report.add(
            severity,
            "skeleton",
            f"{len(info.joints)} joints but missing canonical bones: {', '.join(missing)}. "
            "Add an alias in validate.BONE_ALIASES if these exist under other names",
        )
    else:
        report.add(
            Severity.INFO,
            "skeleton",
            f"{len(info.joints)} joints, all {len(CANONICAL_BONES)} canonical bones present",
        )


def _check_animations(
    report: Report, info: glb.GlbInfo, budget: budgets.Budget, expect_animations: bool
) -> None:
    if not expect_animations:
        if info.animations:
            report.add(Severity.INFO, "animations", f"{len(info.animations)} clip(s) embedded")
        return
    if not info.animations:
        report.add(Severity.ERROR, "animations", "no animation clips found")
    else:
        report.add(
            Severity.INFO,
            "animations",
            f"{len(info.animations)} clip(s): {', '.join(info.animations[:8])}",
        )


def _check_draw_cost(report: Report, info: glb.GlbInfo) -> None:
    """Brief section 62 wants 30-50 visible units at 60fps, so per-unit draw
    calls are a budget item, not a detail."""
    if info.primitives > 8:
        report.add(
            Severity.WARN,
            "draw_cost",
            f"{info.primitives} primitives means {info.primitives} draw calls per instance; "
            "merge submeshes where the material allows",
        )

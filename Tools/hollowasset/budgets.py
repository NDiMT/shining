"""Asset budgets, transcribed from the Hollow Crown brief.

Sections 7 (polygon targets) and 8 (texture strategy) of the master brief are
the single source of truth for these numbers. They are guidelines in the brief,
so each class carries a soft range plus a hard ceiling: the generator aims at
the middle of the range, the validator warns outside it and fails past the
ceiling.

Keep this module data-only. Anything that reasons about budgets lives in
validate.py so the numbers stay easy to audit against the brief.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    """Limits for one class of asset."""

    #: Stable key used in catalog files.
    key: str
    #: Human label for reports.
    label: str
    #: Soft triangle range from brief section 7.
    tri_soft: tuple[int, int]
    #: Hard triangle ceiling. Exceeding this fails validation.
    tri_hard: int
    #: Largest allowed texture edge in pixels, from brief section 8.
    texture_max: int
    #: Expected height in metres, used for scale checks and Meshy rigging.
    height_m: float | None = None
    #: Whether the asset must ship a skeleton and animations.
    needs_skeleton: bool = False
    #: Content subdirectory under Content/Models.
    subdir: str = "Props"
    #: Notes carried into generated documentation.
    notes: str = ""

    @property
    def tri_target(self) -> int:
        """Generation target: the middle of the soft range.

        Meshy overshoots its own ``target_polycount`` fairly often, so aiming at
        the midpoint rather than the ceiling leaves room to land inside the
        range without a remesh pass.
        """
        low, high = self.tri_soft
        return (low + high) // 2


#: Every asset class the pipeline knows about, keyed by catalog ``class`` field.
BUDGETS: dict[str, Budget] = {
    b.key: b
    for b in [
        Budget(
            key="hero",
            label="Main playable hero",
            tri_soft=(4_000, 10_000),
            tri_hard=12_000,
            texture_max=2048,
            height_m=1.7,
            needs_skeleton=True,
            subdir="Characters",
            notes="Brief section 7: important heroes may reach ~12k if justified.",
        ),
        Budget(
            key="npc",
            label="Generic NPC",
            tri_soft=(2_000, 6_000),
            tri_hard=7_000,
            texture_max=1024,
            height_m=1.7,
            needs_skeleton=True,
            subdir="Characters",
        ),
        Budget(
            key="enemy_humanoid",
            label="Generic humanoid enemy",
            tri_soft=(2_000, 6_000),
            tri_hard=7_000,
            texture_max=1024,
            height_m=1.7,
            needs_skeleton=True,
            subdir="Enemies",
        ),
        Budget(
            key="monster_large",
            label="Large monster",
            tri_soft=(5_000, 15_000),
            tri_hard=18_000,
            texture_max=1024,
            height_m=3.0,
            needs_skeleton=True,
            subdir="Enemies",
        ),
        Budget(
            key="boss",
            label="Major boss",
            tri_soft=(10_000, 25_000),
            tri_hard=30_000,
            texture_max=2048,
            height_m=4.0,
            needs_skeleton=True,
            subdir="Enemies",
        ),
        Budget(
            key="weapon",
            label="Weapon",
            tri_soft=(300, 1_500),
            tri_hard=2_500,
            texture_max=512,
            height_m=1.1,
            subdir="Weapons",
            notes="Hero signature weapons may exceed the soft range.",
        ),
        Budget(
            key="prop",
            label="Environment prop",
            tri_soft=(100, 1_000),
            tri_hard=1_500,
            texture_max=512,
            height_m=0.9,
            subdir="Props",
        ),
        Budget(
            key="vegetation",
            label="Tree or rock",
            tri_soft=(300, 3_000),
            tri_hard=4_000,
            texture_max=512,
            height_m=4.0,
            subdir="Vegetation",
        ),
        Budget(
            key="building_module",
            label="Modular building piece",
            tri_soft=(500, 4_000),
            tri_hard=6_000,
            texture_max=1024,
            height_m=4.0,
            subdir="Buildings",
            notes="Brief section 7: prefer modular construction over monolithic meshes.",
        ),
        Budget(
            key="set_piece",
            label="Large set piece or horizon element",
            tri_soft=(1_000, 8_000),
            tri_hard=12_000,
            texture_max=2048,
            # Height is scene-specific for these — a Crownwall section and a
            # distant castle share nothing but their role — so scale is checked
            # per asset in the map data rather than against a class default.
            height_m=None,
            subdir="Buildings",
            notes=(
                "Structures the player sees but never walks on: the Crownwall, "
                "the distant castle, the watchtower silhouette. Budgeted low "
                "because they are always far away and read as silhouette plus "
                "value, not detail. A Crownwall that costs more than a hero is "
                "the wrong trade."
            ),
        ),
    ]
}


def get(class_key: str) -> Budget:
    """Look up a budget, with a helpful error listing the valid keys."""
    try:
        return BUDGETS[class_key]
    except KeyError:
        known = ", ".join(sorted(BUDGETS))
        raise KeyError(f"unknown asset class {class_key!r}; known classes: {known}") from None


def table() -> str:
    """Render the budget table for docs and the ``budgets`` CLI command."""
    rows = [
        ("class", "triangles", "hard cap", "texture", "height", "rigged"),
        ("-----", "---------", "--------", "-------", "------", "------"),
    ]
    for b in BUDGETS.values():
        rows.append(
            (
                b.key,
                f"{b.tri_soft[0]:,}-{b.tri_soft[1]:,}",
                f"{b.tri_hard:,}",
                f"{b.texture_max}px",
                f"{b.height_m}m" if b.height_m else "-",
                "yes" if b.needs_skeleton else "no",
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)

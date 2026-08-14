"""Asset budgets for generated assets.

Sections 7 (polygon targets) and 8 (texture strategy) of the master brief set the
targets. Each class carries a soft range plus a hard ceiling: the validator warns
outside the range and fails past the ceiling.

WHY THE STATIC-OBJECT RANGES ARE ABOVE THE BRIEF'S
--------------------------------------------------
The brief's section 7 numbers describe a *finished, cleaned-up* asset. They are
the right shipping targets. They are not achievable directly from the generator,
and the gap was measured rather than assumed.

A barrel generated against a 550-triangle request came back at 11,733. Decimated
through the API to 561, 1,030 and 2,061 triangles and rendered at each, the
results were a formless lump, a lump with hinted bands, and ragged bands full of
holes with the legs gone. The generator's own 6,392-triangle output was clean:
defined staves, four intact bands, legs present. The API's decimation tears
geometry at every level, and quality does not recover by giving it more
triangles.

So the static-object classes are budgeted for what the generator actually
produces cleanly. The cost is affordable: 200 props at 4,000 triangles is
800,000 triangles per frame, roughly 8% of what a modest GPU handles at 60fps,
against the section 62 target of 1080p60 on modest hardware.

If profiling later demands the brief's tighter numbers, the fix is a Blender
decimation pass with quadric error metrics in the pipeline — not the API's
remesh, which has now been measured and rejected.

CHARACTER CLASSES ARE UNCHANGED
-------------------------------
The evidence above is one static prop. No character has been generated yet, so
the hero, NPC, enemy, monster and boss ranges stay exactly as the brief sets
them. Raising them on the strength of a barrel would repeat the mistake this
comment exists to record. Revisit once the first character is measured.

Keep this module data-only. Anything that reasons about budgets lives in
validate.py so the numbers stay easy to audit.
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
        """The ``target_polycount`` sent to the generator: mid-range.

        Treat it as a hint rather than a setting. Measured, a 550-triangle
        request produced 11,733 triangles, so what actually keeps assets inside
        budget is the validator, not this number.
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
            height_m=1.5,
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
            height_m=1.5,
            needs_skeleton=True,
            subdir="Characters",
        ),
        Budget(
            key="enemy_humanoid",
            label="Generic humanoid enemy",
            tri_soft=(2_000, 6_000),
            tri_hard=7_000,
            texture_max=1024,
            height_m=1.5,
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
            tri_soft=(400, 3_000),
            tri_hard=5_000,
            texture_max=512,
            height_m=1.1,
            subdir="Weapons",
            notes="Hero signature weapons may exceed the soft range.",
        ),
        Budget(
            key="prop",
            label="Environment prop",
            tri_soft=(400, 4_000),
            tri_hard=7_000,
            texture_max=512,
            height_m=0.9,
            subdir="Props",
        ),
        Budget(
            key="vegetation",
            label="Tree or rock",
            tri_soft=(800, 6_000),
            tri_hard=9_000,
            texture_max=512,
            height_m=4.0,
            subdir="Vegetation",
        ),
        Budget(
            key="building_module",
            label="Modular building piece",
            tri_soft=(1_000, 8_000),
            tri_hard=12_000,
            texture_max=1024,
            height_m=4.0,
            subdir="Buildings",
            notes="Brief section 7: prefer modular construction over monolithic meshes.",
        ),
        Budget(
            key="set_piece",
            label="Large set piece or horizon element",
            tri_soft=(1_500, 12_000),
            tri_hard=18_000,
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

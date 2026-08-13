"""Game-data validation, per brief section 79.

The brief asks for offline tooling that checks broken asset paths, duplicate ids,
missing skills, invalid classes, invalid references and impossible battle
coordinates, because AI-generated content must be validated automatically.

Brief section 14 makes content data the primary authoring surface: adding ten
forest enemies should touch no engine code. That only works if a typo in a class
name is caught here rather than discovered as a silent no-op three hours into a
playthrough. Every check in this module exists because the failure it catches
would otherwise be invisible.

Standard library only, like the rest of the package, so it runs in CI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import budgets
from .validate import Finding, Severity

# ---------------------------------------------------------------------------
# Vocabularies the engine must implement. Extending content means extending
# these first, which is the point: an unregistered value is a typo until proven
# otherwise.
# ---------------------------------------------------------------------------

#: Brief section 39.
AI_BEHAVIOURS = {
    "aggressive_melee",
    "defensive_guard",
    "ranged_kiting",
    "healer",
    "boss",
    "protect_target",
    "hold_position",
    # Prologue-specific: soldiers who will not close the distance while they are
    # still hoping Rowan stands down.
    "hesitant",
}

#: Brief section 40.
OBJECTIVE_TYPES = {
    "defeat_all",
    "defeat_commander",
    "defeat_unit",
    "survive_turns",
    "escape",
    "reach_location",
    "protect_npc",
    "destroy_object",
    "prevent_escape",
    "rescue_units",
}

#: Brief section 41. Every scripted battle action the engine must support.
EVENT_ACTIONS = {
    "dialogue",
    "set_flag",
    "set_terrain",
    "set_objective",
    "set_ai",
    "spawn_unit",
    "spawn_decoration",
    "change_side",
    "clear_rule",
    "force_move",
    "flee_to_exit",
    "focus_camera",
    "screen_shake",
    "sound",
    "swap_prop",
}

EVENT_TRIGGERS = {
    "turn_start",
    "turn_end",
    "enemies_remaining",
    "unit_defeated",
    "unit_hp_below",
    "unit_reaches",
    "battle_start",
}

SIDES = {"player", "ally", "enemy", "hostile_to_all"}


class ContentError(RuntimeError):
    """A data file could not be read at all."""


@dataclass
class ContentSet:
    """Every game-data file, loaded and indexed."""

    root: str
    classes: dict[str, dict] = field(default_factory=dict)
    characters: dict[str, dict] = field(default_factory=dict)
    npcs: dict[str, dict] = field(default_factory=dict)
    enemies: dict[str, dict] = field(default_factory=dict)
    items: dict[str, dict] = field(default_factory=dict)
    equipment: dict[str, dict] = field(default_factory=dict)
    skills: dict[str, dict] = field(default_factory=dict)
    terrain: dict[str, dict] = field(default_factory=dict)
    terrain_by_symbol: dict[str, dict] = field(default_factory=dict)
    flags: dict[str, dict] = field(default_factory=dict)
    battles: dict[str, dict] = field(default_factory=dict)
    scenes: dict[str, dict] = field(default_factory=dict)
    expressions: set[str] = field(default_factory=set)
    #: Asset id -> the path the pipeline will write it to.
    catalog_assets: dict[str, str] = field(default_factory=dict)
    #: Every model path any catalog will produce, for reverse lookup.
    catalog_paths: set[str] = field(default_factory=set)

    def all_unit_ids(self) -> set[str]:
        return set(self.characters) | set(self.npcs) | set(self.enemies)


@dataclass
class ContentReport:
    findings: list[Finding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, severity: Severity, check: str, message: str) -> None:
        self.findings.append(Finding(severity, check, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARN]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        state = "PASS" if self.ok else "FAIL"
        inventory = ", ".join(f"{v} {k}" for k, v in sorted(self.counts.items()))
        return (
            f"{state}  {len(self.errors)} error(s), {len(self.warnings)} warning(s)\n"
            f"      {inventory}"
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise ContentError(f"missing data file: {path}") from None
    except json.JSONDecodeError as exc:
        raise ContentError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from None


def _index(rows: list, key: str = "id") -> dict[str, dict]:
    return {str(row[key]): row for row in rows if isinstance(row, dict) and key in row}


def load(data_root: str = "Content/Data", catalog_dir: str = "Tools/catalog") -> ContentSet:
    """Load every data file and catalog. Raises ContentError on unreadable files."""
    content = ContentSet(root=data_root)

    classes = _read_json(os.path.join(data_root, "classes.json"))
    content.classes = _index(classes.get("classes", []))

    characters = _read_json(os.path.join(data_root, "characters.json"))
    content.characters = _index(characters.get("characters", []))
    content.npcs = _index(characters.get("npcs", []))
    content.enemies = _index(characters.get("enemies", []))

    items = _read_json(os.path.join(data_root, "items.json"))
    content.items = _index(items.get("items", []))

    weapons = _read_json(os.path.join(data_root, "weapons.json"))
    for section in ("weapons", "armour", "shields"):
        content.equipment.update(_index(weapons.get(section, [])))

    skills = _read_json(os.path.join(data_root, "skills.json"))
    content.skills = _index(skills.get("skills", []))

    terrain = _read_json(os.path.join(data_root, "terrain.json"))
    content.terrain = _index(terrain.get("terrain", []))
    content.terrain_by_symbol = {
        str(row["symbol"]): row for row in terrain.get("terrain", []) if "symbol" in row
    }

    flags = _read_json(os.path.join(data_root, "flags.json"))
    content.flags = _index(flags.get("flags", []))

    battles_dir = os.path.join(data_root, "Battles")
    if os.path.isdir(battles_dir):
        for name in sorted(os.listdir(battles_dir)):
            if name.endswith(".json"):
                battle = _read_json(os.path.join(battles_dir, name))
                content.battles[str(battle.get("id", name))] = battle

    dialogue_dir = os.path.join(data_root, "Dialogue")
    if os.path.isdir(dialogue_dir):
        for name in sorted(os.listdir(dialogue_dir)):
            if not name.endswith(".json"):
                continue
            document = _read_json(os.path.join(dialogue_dir, name))
            content.expressions.update(document.get("expressions", []))
            for scene in document.get("scenes", []):
                content.scenes[str(scene.get("id", ""))] = scene

    if os.path.isdir(catalog_dir):
        for name in sorted(os.listdir(catalog_dir)):
            if not name.endswith(".json"):
                continue
            catalog = _read_json(os.path.join(catalog_dir, name))
            for entry in catalog.get("assets", []):
                asset_id = str(entry.get("id", ""))
                class_key = str(entry.get("class", ""))
                if not asset_id or class_key not in budgets.BUDGETS:
                    continue
                path = os.path.join(
                    "Content/Models", budgets.get(class_key).subdir, f"{asset_id}.glb"
                )
                content.catalog_assets[asset_id] = path.replace(os.sep, "/")
                content.catalog_paths.add(path.replace(os.sep, "/"))

    return content


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(content: ContentSet) -> ContentReport:
    """Run every content check."""
    report = ContentReport()
    report.counts = {
        "classes": len(content.classes),
        "characters": len(content.characters),
        "npcs": len(content.npcs),
        "enemies": len(content.enemies),
        "items": len(content.items),
        "equipment": len(content.equipment),
        "skills": len(content.skills),
        "terrain": len(content.terrain),
        "flags": len(content.flags),
        "battles": len(content.battles),
        "scenes": len(content.scenes),
        "assets": len(content.catalog_assets),
    }

    written: set[str] = set()
    _check_duplicate_ids(content, report)
    _check_classes(content, report)
    _check_characters(content, report)
    _check_items(content, report, written)
    for battle_id, battle in sorted(content.battles.items()):
        _check_battle(content, report, battle_id, battle, written)
    for scene_id, scene in sorted(content.scenes.items()):
        _check_scene(content, report, scene_id, scene, written)
    _check_flags(content, report, written)
    return report


def _check_duplicate_ids(content: ContentSet, report: ContentReport) -> None:
    """Ids must be unique across every namespace that shares a lookup.

    Characters, NPCs and enemies are all addressed as battle units, so an id
    reused between them makes a battle definition ambiguous.
    """
    seen: dict[str, str] = {}
    for namespace, table in (
        ("characters", content.characters),
        ("npcs", content.npcs),
        ("enemies", content.enemies),
    ):
        for unit_id in table:
            if unit_id in seen:
                report.add(
                    Severity.ERROR,
                    "duplicate_id",
                    f"unit id {unit_id!r} appears in both {seen[unit_id]} and {namespace}",
                )
            seen[unit_id] = namespace

    overlap = set(content.items) & set(content.equipment)
    if overlap:
        report.add(
            Severity.ERROR,
            "duplicate_id",
            f"id(s) used by both an item and a piece of equipment: {', '.join(sorted(overlap))}",
        )


def _check_classes(content: ContentSet, report: ContentReport) -> None:
    for class_id, definition in sorted(content.classes.items()):
        for skill in definition.get("skills", []):
            if skill not in content.skills:
                report.add(
                    Severity.ERROR,
                    "missing_skill",
                    f"class {class_id!r} grants unknown skill {skill!r}",
                )
        if not definition.get("movement"):
            report.add(Severity.ERROR, "invalid_class", f"class {class_id!r} has no movement value")
        # Promotions may legitimately point at classes that do not exist yet, but
        # a silent dangling promotion becomes an unreachable reward later.
        for promotion in definition.get("promotions", []):
            if promotion not in content.classes:
                report.add(
                    Severity.WARN,
                    "promotion_target",
                    f"class {class_id!r} promotes to {promotion!r}, which is not defined yet",
                )


def _check_characters(content: ContentSet, report: ContentReport) -> None:
    stat_keys = {"hp", "mp", "attack", "defense", "magic", "resistance", "agility"}

    for namespace, table in (
        ("character", content.characters),
        ("enemy", content.enemies),
    ):
        for unit_id, unit in sorted(table.items()):
            where = f"{namespace} {unit_id!r}"

            class_id = unit.get("class")
            if class_id not in content.classes:
                report.add(
                    Severity.ERROR, "invalid_class", f"{where} has unknown class {class_id!r}"
                )

            stats = unit.get("baseStats", {})
            missing = stat_keys - set(stats)
            if missing:
                report.add(
                    Severity.ERROR,
                    "invalid_stats",
                    f"{where} is missing base stats: {', '.join(sorted(missing))}",
                )
            for name, value in stats.items():
                if not isinstance(value, (int, float)) or value < 0:
                    report.add(
                        Severity.ERROR,
                        "invalid_stats",
                        f"{where} has a non-positive {name}: {value!r}",
                    )

            for skill in unit.get("skills", []):
                if skill not in content.skills:
                    report.add(
                        Severity.ERROR, "missing_skill", f"{where} has unknown skill {skill!r}"
                    )

            for slot, item_id in (unit.get("startingEquipment") or {}).items():
                if item_id not in content.equipment:
                    report.add(
                        Severity.ERROR,
                        "invalid_reference",
                        f"{where} equips unknown {slot} {item_id!r}",
                    )

            _check_model_path(content, report, where, unit.get("model"))

    for npc_id, npc in sorted(content.npcs.items()):
        _check_model_path(content, report, f"npc {npc_id!r}", npc.get("model"))


def _check_model_path(
    content: ContentSet, report: ContentReport, where: str, path: str | None
) -> None:
    """A model path must be something the asset pipeline will actually produce.

    Checking against the catalogs rather than the filesystem is deliberate: it
    catches a typo before the asset is generated, and it works in CI where the
    GLBs may not be committed yet.
    """
    if not path:
        report.add(Severity.ERROR, "broken_asset_path", f"{where} has no model path")
        return
    if path in content.catalog_paths:
        return
    if os.path.exists(path):
        report.add(
            Severity.WARN,
            "broken_asset_path",
            f"{where} model {path} exists on disk but no catalog produces it; "
            "hand-authored assets should still be catalogued for provenance",
        )
        return
    report.add(
        Severity.ERROR,
        "broken_asset_path",
        f"{where} model {path} is not produced by any catalog in Tools/catalog",
    )


def _check_items(content: ContentSet, report: ContentReport, written: set[str]) -> None:
    for item_id, item in sorted(content.items.items()):
        reveal = item.get("revealFlag")
        if reveal and reveal not in content.flags:
            report.add(
                Severity.ERROR,
                "undeclared_flag",
                f"item {item_id!r} reveals on flag {reveal!r}, which is not declared in flags.json",
            )
        if item.get("identified") is False and not item.get("unidentifiedName"):
            report.add(
                Severity.WARN,
                "invalid_reference",
                f"item {item_id!r} is unidentified but has no unidentifiedName to display",
            )


# ---------------------------------------------------------------------------
# Battles
# ---------------------------------------------------------------------------


def _check_battle(
    content: ContentSet,
    report: ContentReport,
    battle_id: str,
    battle: dict,
    written: set[str],
) -> None:
    where = f"battle {battle_id!r}"
    size = battle.get("size") or {}
    width, height = int(size.get("width", 0)), int(size.get("height", 0))
    if width <= 0 or height <= 0:
        report.add(Severity.ERROR, "invalid_battle", f"{where} has no valid size")
        return

    grid = _check_grid(content, report, where, battle, width, height)

    occupied: dict[tuple[int, int], str] = {}
    for group, key in (
        ("player_units", "character"),
        ("ally_units", None),
        ("enemy_units", None),
    ):
        for index, unit in enumerate(battle.get(group, [])):
            label = unit.get("id") or unit.get(key or "character") or f"{group}[{index}]"
            _check_unit(content, report, where, group, label, unit, grid, width, height, occupied)

    for index, prop in enumerate(battle.get("props", [])):
        asset = prop.get("asset")
        if asset and asset not in content.catalog_assets:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} prop[{index}] uses asset {asset!r}, which no catalog defines",
            )
        _check_position(report, where, f"prop {asset}", prop.get("position"), width, height)

    for objective in battle.get("objectives", []):
        _check_objective(content, report, where, objective)

    for rule_side in (battle.get("rules") or {}).get("non_lethal_sides", []):
        if rule_side not in SIDES:
            report.add(
                Severity.ERROR, "invalid_battle", f"{where} non-lethal side {rule_side!r} unknown"
            )

    battle_scoped: set[str] = set()
    for event in battle.get("events", []):
        _check_event(content, report, where, battle, event, grid, width, height,
                     written, battle_scoped)

    for tutorial in battle.get("tutorials", []):
        flag = tutorial.get("flag")
        if flag and flag not in battle_scoped and flag not in content.flags:
            report.add(
                Severity.ERROR,
                "undeclared_flag",
                f"{where} tutorial {tutorial.get('id')!r} waits on flag {flag!r}, "
                "which no event in this battle sets and flags.json does not declare",
            )
        unit = tutorial.get("unit")
        if unit and unit not in content.all_unit_ids():
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} tutorial {tutorial.get('id')!r} targets unknown unit {unit!r}",
            )

    for key in ("dialogue",):
        scene = (battle.get("on_victory") or {}).get(key)
        if scene and scene not in content.scenes:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} on_victory {key} references unknown scene {scene!r}",
            )

    for reward in (battle.get("rewards") or {}).get("items", []):
        item_id = reward.get("id")
        if item_id not in content.items and item_id not in content.equipment:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} rewards unknown item {item_id!r}",
            )

    for condition in battle.get("defeat_conditions", []):
        unit = condition.get("unit")
        if unit and unit not in content.all_unit_ids():
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} defeat condition references unknown unit {unit!r}",
            )


def _check_grid(
    content: ContentSet,
    report: ContentReport,
    where: str,
    battle: dict,
    width: int,
    height: int,
) -> list[str]:
    """Validate the terrain grid and return it, north row first."""
    grid = battle.get("terrain") or []
    if len(grid) != height:
        report.add(
            Severity.ERROR,
            "invalid_battle",
            f"{where} declares height {height} but the terrain grid has {len(grid)} row(s)",
        )
    unknown: set[str] = set()
    for index, row in enumerate(grid):
        if len(row) != width:
            report.add(
                Severity.ERROR,
                "invalid_battle",
                f"{where} terrain row {index} is {len(row)} characters, expected {width}",
            )
        for symbol in row:
            if symbol not in content.terrain_by_symbol:
                unknown.add(symbol)
    if unknown:
        report.add(
            Severity.ERROR,
            "invalid_battle",
            f"{where} terrain uses symbol(s) not defined in terrain.json: "
            + ", ".join(repr(s) for s in sorted(unknown)),
        )
    return grid


def _tile(grid: list[str], x: int, y: int, height: int) -> str | None:
    """Terrain symbol at (x, y). The grid is stored north row first."""
    row_index = height - 1 - y
    if not (0 <= row_index < len(grid)):
        return None
    row = grid[row_index]
    return row[x] if 0 <= x < len(row) else None


def _check_position(
    report: ContentReport,
    where: str,
    label: str,
    position: object,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    if not (isinstance(position, list) and len(position) == 2):
        report.add(
            Severity.ERROR,
            "impossible_coordinate",
            f"{where} {label} has no valid [x, y] position",
        )
        return None
    x, y = int(position[0]), int(position[1])
    if not (0 <= x < width and 0 <= y < height):
        report.add(
            Severity.ERROR,
            "impossible_coordinate",
            f"{where} {label} sits at [{x},{y}], outside the {width}x{height} grid",
        )
        return None
    return x, y


def _check_unit(
    content: ContentSet,
    report: ContentReport,
    where: str,
    group: str,
    label: str,
    unit: dict,
    grid: list[str],
    width: int,
    height: int,
    occupied: dict[tuple[int, int], str],
) -> None:
    reference = unit.get("character") or unit.get("enemy") or unit.get("npc")
    if reference is None:
        report.add(
            Severity.ERROR,
            "invalid_reference",
            f"{where} {group} {label!r} names no character, enemy or npc",
        )
    elif reference not in content.all_unit_ids():
        report.add(
            Severity.ERROR,
            "invalid_reference",
            f"{where} {group} {label!r} references unknown unit {reference!r}",
        )

    behaviour = unit.get("ai")
    if behaviour and behaviour not in AI_BEHAVIOURS:
        report.add(
            Severity.ERROR,
            "invalid_reference",
            f"{where} {group} {label!r} uses unknown AI behaviour {behaviour!r}; "
            f"register it in content.AI_BEHAVIOURS and implement it",
        )

    tile = _check_position(report, where, f"{group} {label!r}", unit.get("position"), width, height)
    if tile is None:
        return

    if tile in occupied:
        report.add(
            Severity.ERROR,
            "impossible_coordinate",
            f"{where} {group} {label!r} starts on {list(tile)}, already occupied by "
            f"{occupied[tile]!r}",
        )
    occupied[tile] = label

    symbol = _tile(grid, tile[0], tile[1], height)
    if symbol is None:
        return
    terrain = content.terrain_by_symbol.get(symbol)
    if terrain and terrain.get("blocked"):
        report.add(
            Severity.ERROR,
            "impossible_coordinate",
            f"{where} {group} {label!r} starts on {list(tile)}, which is "
            f"{terrain.get('name', symbol)!r} and impassable",
        )


def _check_objective(
    content: ContentSet, report: ContentReport, where: str, objective: dict
) -> None:
    kind = objective.get("type")
    if kind not in OBJECTIVE_TYPES:
        report.add(
            Severity.ERROR,
            "invalid_battle",
            f"{where} objective type {kind!r} unknown; register it in content.OBJECTIVE_TYPES",
        )
        return
    if kind == "defeat_unit" and not objective.get("unit"):
        report.add(Severity.ERROR, "invalid_battle", f"{where} defeat_unit objective names no unit")
    if kind == "survive_turns" and not objective.get("turns"):
        report.add(
            Severity.ERROR, "invalid_battle", f"{where} survive_turns objective has no turn count"
        )


def _check_event(
    content: ContentSet,
    report: ContentReport,
    where: str,
    battle: dict,
    event: dict,
    grid: list[str],
    width: int,
    height: int,
    written: set[str],
    battle_scoped: set[str],
) -> None:
    event_id = event.get("id", "<unnamed>")
    label = f"{where} event {event_id!r}"

    trigger = event.get("trigger") or {}
    if trigger.get("type") not in EVENT_TRIGGERS:
        report.add(
            Severity.ERROR,
            "invalid_battle",
            f"{label} has unknown trigger type {trigger.get('type')!r}",
        )
    trigger_unit = trigger.get("unit")
    if trigger_unit and trigger_unit not in content.all_unit_ids():
        report.add(
            Severity.ERROR,
            "invalid_reference",
            f"{label} triggers on unknown unit {trigger_unit!r}",
        )

    local_units = _battle_unit_ids(battle)
    # Units the event itself spawns become addressable by later actions.
    for action in event.get("actions", []):
        if action.get("type") == "spawn_unit" and action.get("id"):
            local_units.add(str(action["id"]))

    for action in event.get("actions", []):
        kind = action.get("type")
        if kind not in EVENT_ACTIONS:
            report.add(
                Severity.ERROR,
                "invalid_battle",
                f"{label} uses unknown action {kind!r}; register it in content.EVENT_ACTIONS "
                "and implement it, or the engine will silently do nothing",
            )
            continue

        if kind == "dialogue":
            scene = action.get("scene")
            if scene not in content.scenes:
                report.add(
                    Severity.ERROR,
                    "invalid_reference",
                    f"{label} plays unknown dialogue scene {scene!r}",
                )

        elif kind == "set_flag":
            flag = str(action.get("flag", ""))
            if action.get("scope") == "battle":
                battle_scoped.add(flag)
            else:
                written.add(flag)
                if flag not in content.flags:
                    report.add(
                        Severity.ERROR,
                        "undeclared_flag",
                        f"{label} sets flag {flag!r}, which is not declared in flags.json",
                    )

        elif kind == "set_terrain":
            terrain_id = action.get("terrain")
            if terrain_id not in content.terrain:
                report.add(
                    Severity.ERROR,
                    "invalid_reference",
                    f"{label} sets unknown terrain {terrain_id!r}",
                )
            for tile in action.get("tiles", []):
                _check_position(report, where, f"event {event_id!r} set_terrain", tile, width, height)

        elif kind == "set_objective":
            _check_objective(content, report, where, action.get("objective") or {})

        elif kind == "spawn_unit":
            reference = action.get("enemy") or action.get("character") or action.get("npc")
            if reference not in content.all_unit_ids():
                report.add(
                    Severity.ERROR,
                    "invalid_reference",
                    f"{label} spawns unknown unit {reference!r}",
                )
            side = action.get("side")
            if side and side not in SIDES:
                report.add(
                    Severity.ERROR, "invalid_battle", f"{label} spawns onto unknown side {side!r}"
                )
            _check_spawn_tile(content, report, label, action, grid, width, height, event)

        elif kind in ("change_side", "set_ai"):
            for unit in action.get("units", []):
                if unit not in local_units:
                    report.add(
                        Severity.ERROR,
                        "invalid_reference",
                        f"{label} {kind} references {unit!r}, which is not a unit in this battle",
                    )
            if kind == "set_ai":
                behaviour = action.get("ai")
                if behaviour not in AI_BEHAVIOURS:
                    report.add(
                        Severity.ERROR,
                        "invalid_reference",
                        f"{label} assigns unknown AI behaviour {behaviour!r}",
                    )
            else:
                side = action.get("to")
                if side not in SIDES:
                    report.add(
                        Severity.ERROR, "invalid_battle", f"{label} changes side to {side!r}"
                    )

        elif kind in ("force_move", "flee_to_exit"):
            unit = action.get("unit")
            if unit and unit not in local_units:
                report.add(
                    Severity.ERROR,
                    "invalid_reference",
                    f"{label} moves {unit!r}, which is not a unit in this battle",
                )
            if action.get("position") is not None:
                _check_position(
                    report, where, f"event {event_id!r} target", action.get("position"),
                    width, height,
                )

        elif kind == "swap_prop":
            for role in ("from", "to"):
                asset = action.get(role)
                if asset and asset not in content.catalog_assets:
                    report.add(
                        Severity.ERROR,
                        "invalid_reference",
                        f"{label} swaps prop {role} {asset!r}, which no catalog defines",
                    )

        elif kind == "spawn_decoration":
            for unit in action.get("units", []):
                if unit not in content.all_unit_ids():
                    report.add(
                        Severity.ERROR,
                        "invalid_reference",
                        f"{label} spawns unknown decoration unit {unit!r}",
                    )


def _check_spawn_tile(
    content: ContentSet,
    report: ContentReport,
    label: str,
    action: dict,
    grid: list[str],
    width: int,
    height: int,
    event: dict,
) -> None:
    """A unit must not spawn onto an impassable tile.

    An event may legitimately clear the tile first, so a preceding ``set_terrain``
    covering the same coordinate counts as making it passable. Getting this wrong
    is the sort of bug that only appears the one time the event fires.
    """
    position = action.get("position")
    if not (isinstance(position, list) and len(position) == 2):
        return
    x, y = int(position[0]), int(position[1])
    if not (0 <= x < width and 0 <= y < height):
        return

    cleared: set[tuple[int, int]] = set()
    for earlier in event.get("actions", []):
        if earlier is action:
            break
        if earlier.get("type") == "set_terrain":
            terrain = content.terrain.get(str(earlier.get("terrain")))
            if terrain and not terrain.get("blocked"):
                for tile in earlier.get("tiles", []):
                    if isinstance(tile, list) and len(tile) == 2:
                        cleared.add((int(tile[0]), int(tile[1])))

    if (x, y) in cleared:
        return
    symbol = _tile(grid, x, y, height)
    terrain = content.terrain_by_symbol.get(symbol or "")
    if terrain and terrain.get("blocked"):
        report.add(
            Severity.ERROR,
            "impossible_coordinate",
            f"{label} spawns onto [{x},{y}], which is {terrain.get('name', symbol)!r} and "
            "impassable, and no earlier action in this event clears it",
        )


def _battle_unit_ids(battle: dict) -> set[str]:
    out: set[str] = set()
    for group in ("player_units", "ally_units", "enemy_units"):
        for unit in battle.get(group, []):
            for key in ("id", "character", "enemy", "npc"):
                if unit.get(key):
                    out.add(str(unit[key]))
    return out


# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------


def _check_scene(
    content: ContentSet,
    report: ContentReport,
    scene_id: str,
    scene: dict,
    written: set[str],
) -> None:
    where = f"scene {scene_id!r}"
    if not scene_id:
        report.add(Severity.ERROR, "invalid_reference", "a dialogue scene has no id")
        return

    speakers = content.all_unit_ids()
    lines = list(scene.get("lines", []))
    for option in (scene.get("choice") or {}).get("options", []):
        lines.extend(option.get("lines", []))
        _collect_flag_writes(content, report, f"{where} choice", option.get("set_flag"), written)

    for index, line in enumerate(lines):
        speaker = line.get("speaker")
        if speaker is not None and speaker not in speakers:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} line {index} has unknown speaker {speaker!r}",
            )
        expression = line.get("portrait")
        if expression and content.expressions and expression not in content.expressions:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} line {index} uses undeclared expression {expression!r}",
            )
        if speaker is not None and not line.get("text"):
            report.add(
                Severity.WARN,
                "invalid_reference",
                f"{where} line {index} has a speaker but no text",
            )

    completion = scene.get("on_complete") or {}
    _collect_flag_writes(content, report, where, completion.get("set_flag"), written)

    battle = completion.get("start_battle")
    if battle and battle not in content.battles:
        report.add(
            Severity.ERROR,
            "invalid_reference",
            f"{where} starts unknown battle {battle!r}",
        )

    for key in ("add_party_member", "remove_party_member"):
        for member in completion.get(key, []):
            if member not in content.characters:
                report.add(
                    Severity.ERROR,
                    "invalid_reference",
                    f"{where} {key} references unknown character {member!r}",
                )

    item = completion.get("give_item")
    if item and item not in content.items and item not in content.equipment:
        report.add(
            Severity.ERROR, "invalid_reference", f"{where} gives unknown item {item!r}"
        )

    equip = completion.get("equip") or {}
    if equip:
        if equip.get("character") not in content.characters:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} equips onto unknown character {equip.get('character')!r}",
            )
        if equip.get("item") not in content.equipment:
            report.add(
                Severity.ERROR,
                "invalid_reference",
                f"{where} equips unknown equipment {equip.get('item')!r}",
            )


def _collect_flag_writes(
    content: ContentSet,
    report: ContentReport,
    where: str,
    payload: object,
    written: set[str],
) -> None:
    if not isinstance(payload, dict):
        return
    for flag, value in payload.items():
        written.add(flag)
        declaration = content.flags.get(flag)
        if declaration is None:
            report.add(
                Severity.ERROR,
                "undeclared_flag",
                f"{where} sets flag {flag!r}, which is not declared in flags.json",
            )
            continue
        allowed = declaration.get("allowed")
        if allowed and value not in allowed:
            report.add(
                Severity.ERROR,
                "undeclared_flag",
                f"{where} sets {flag!r} to {value!r}, not one of {allowed}",
            )
        expected = declaration.get("type")
        if expected == "bool" and not isinstance(value, bool):
            report.add(
                Severity.ERROR,
                "undeclared_flag",
                f"{where} sets bool flag {flag!r} to non-boolean {value!r}",
            )


def _check_flags(content: ContentSet, report: ContentReport, written: set[str]) -> None:
    """Report flags nobody sets and nobody reads.

    A flag with no writer and no declared reader is either dead weight or a
    payoff someone forgot to wire up. Both are worth surfacing, and neither is
    an error: brief section 45 flags are set across acts, and a prologue flag
    whose reader lives in Act IV is correct today.
    """
    for flag_id, declaration in sorted(content.flags.items()):
        has_writer = flag_id in written or bool(declaration.get("setBy"))
        has_reader = bool(declaration.get("readBy"))
        if not has_writer and not has_reader:
            report.add(
                Severity.WARN,
                "unused_flag",
                f"flag {flag_id!r} is never set and never read",
            )
        elif not has_writer:
            report.add(
                Severity.INFO,
                "unused_flag",
                f"flag {flag_id!r} has readers but nothing sets it yet",
            )

    for flag_id in sorted(written):
        declaration = content.flags.get(flag_id)
        if declaration is not None and not declaration.get("readBy"):
            report.add(
                Severity.WARN,
                "unused_flag",
                f"flag {flag_id!r} is set but nothing declares that it reads it",
            )

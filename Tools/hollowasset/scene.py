"""Compose a whole battle from the real game data and render it.

Godot cannot be installed in this environment, so this module is currently the
only way anybody sees what a Hollow Crown battle looks like. It is therefore not
a debug view of one asset: it reads Content/Data, resolves the same terrain,
character and class tables the C# rules read, places whatever assets have
actually been generated, and draws the board the way the player would see it.

What it is not: an engine. Movement range here is a view-only approximation of
Game.Rules/Tactical/Movement.cs, and that file remains the authority. This one
exists so a picture can be looked at, not so rules can be decided from it.

Everything it cannot find is reported and drawn anyway. Most of the catalog has
not been generated, and a battlefield that silently skips its missing units is a
picture of an empty field, which tells nobody anything.
"""

from __future__ import annotations

import glob
import json
import math
import os
from dataclasses import dataclass, field

from . import preview

#: Metres per grid cell. A hero is 1.5 m (budgets.py) and stands on one tile, so
#: a 1 m cell is what makes a unit read as a person on a square rather than a
#: figurine on a chessboard.
TILE = 1.0

#: Metres per terrain height level. terrain.json gives the hill height 1; at a
#: full metre the hill in battle 01 stood taller than the goblin holding it and
#: read as a plateau, so half a metre is the rise that still reads as high ground.
ELEVATION_STEP = 0.5

#: Depth of the slab under the lowest tile. Gives the board an edge to catch an
#: outline on, which is what stops it looking like a texture on the sky.
BOARD_SKIRT = 0.55

#: Half-width of the painted grid line, in metres. Both neighbours paint their
#: own half, so a line between two tiles is twice this.
GRID_BORDER = 0.035

#: Height that markers sit above the tile they belong to. Must stay under
#: preview.OUTLINE_DEPTH_FLOOR or the edge pass rings every marker.
MARKER_LIFT = 0.02

#: Rule 5 of docs/ANIME_DIRECTION.md: neighbouring materials get different hues,
#: not different shades of one. Grass, hill and forest are the test case — three
#: greens that have to stay apart after the toon ramp has collapsed the value
#: range, so they separate on hue and saturation rather than lightness.
TERRAIN_COLOURS: dict[str, tuple[int, int, int]] = {
    "grass": (108, 176, 76),
    "path": (206, 174, 116),
    "forest": (44, 124, 84),
    "rock": (146, 142, 158),
    "hill": (150, 186, 68),
    "fence": (166, 116, 62),
    "rubble": (150, 130, 116),
    "wall": (176, 178, 190),
    "obstacle": (128, 100, 74),
    "exit": (236, 200, 92),
}
#: Fallback for a terrain type added to terrain.json before it is given a colour
#: here. Magenta, because a silent grey would look deliberate.
UNKNOWN_TERRAIN_COLOUR = (232, 62, 200)

#: Terrain that is a solid object rather than ground, and how tall to build it.
#: These are terrain, not props: the battle files rely on them to block movement
#: whether or not a prop was ever generated for the tile.
TERRAIN_BLOCKS: dict[str, float] = {"fence": 0.95, "wall": 2.6, "obstacle": 1.1}

#: One saturated hue per side, per rule 5. Side is the single most important
#: thing to read off a tactical board, so it gets the strongest separation.
SIDE_COLOURS: dict[str, tuple[int, int, int]] = {
    "player": (70, 132, 236),
    "ally": (74, 200, 154),
    "enemy": (226, 72, 68),
}

#: Movement range overlay for the active unit.
MOVE_FILL = (78, 168, 244)
MOVE_EDGE = (156, 226, 255)
ACTIVE_EDGE = (255, 214, 92)

#: Sky, top to horizon. A dark background hides the dark outlines that rule 2
#: exists to produce, so the board sits against something bright enough to see
#: them against.
SKY = ((58, 82, 138), (150, 178, 196))

#: Placeholder unit heights in metres. Heroes and NPCs are 1.5 m from
#: budgets.py; the goblins are the catalog's "small hunched goblin ... low
#: crouched profile", so they are drawn shorter on purpose.
DEFAULT_UNIT_HEIGHT = 1.5
UNIT_HEIGHTS: dict[str, float] = {
    "goblin_raider": 1.35,
    "goblin_spearman": 1.4,
    "goblin_archer": 1.3,
    "wallstalker": 3.0,
}

#: Tactical camera. 40 degrees of pitch is the middle of the 35-45 band the board
#: reads best in: below 35 the far rows hide behind the near ones, above 45 the
#: units stop having a silhouette and become discs.
DEFAULT_YAW = 34.0
DEFAULT_PITCH = 40.0

DATA_ROOT = "Content/Data"
MODEL_ROOT = "Content/Models"


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_terrain(data_root: str = DATA_ROOT) -> dict[str, dict]:
    """Terrain types by symbol, exactly as the battle grids reference them."""
    entries = _load_json(os.path.join(data_root, "terrain.json"))["terrain"]
    return {str(entry["symbol"]): entry for entry in entries}


def load_cast(data_root: str = DATA_ROOT) -> dict[str, dict]:
    """Every character, npc and enemy by id.

    Flattened into one table because the battle files reference the three lists
    interchangeably: battle 02 spawns ``greenvale_soldier`` under an ``npc`` key
    while characters.json declares it under ``enemies``.
    """
    document = _load_json(os.path.join(data_root, "characters.json"))
    cast: dict[str, dict] = {}
    for section in ("characters", "npcs", "enemies"):
        for entry in document.get(section, []):
            cast[str(entry["id"])] = entry
    return cast


def load_classes(data_root: str = DATA_ROOT) -> dict[str, dict]:
    document = _load_json(os.path.join(data_root, "classes.json"))
    return {str(entry["id"]): entry for entry in document.get("classes", [])}


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------


@dataclass
class Grid:
    """A battle's terrain, indexed the way the game indexes it.

    x runs west to east and y runs SOUTH to north, matching Coord.cs. The battle
    file writes its rows north first, so row 0 of the JSON is y = height - 1.
    :meth:`parse` is the only place that flip happens, exactly as BattleGrid.cs
    keeps it to one method — get it wrong and the map is merely mirrored, which
    looks entirely plausible and is wrong in every tactical detail.
    """

    width: int
    height: int
    #: ``ids[y][x]`` -> terrain id.
    ids: list[list[str]]
    types: dict[str, dict]

    @classmethod
    def parse(cls, rows: list[str], by_symbol: dict[str, dict]) -> "Grid":
        if not rows:
            raise ValueError("a battle grid needs at least one row")
        height = len(rows)
        width = len(rows[0])
        ids: list[list[str]] = [[] for _ in range(height)]
        types: dict[str, dict] = {}
        for row_index, row in enumerate(rows):
            if len(row) != width:
                raise ValueError(
                    f"terrain row {row_index} is {len(row)} characters, expected {width}")
            y = height - 1 - row_index
            for symbol in row:
                entry = by_symbol.get(symbol)
                if entry is None:
                    raise ValueError(
                        f"terrain symbol {symbol!r} on row {row_index} is not in terrain.json")
                ids[y].append(str(entry["id"]))
                types[str(entry["id"])] = entry
        return cls(width=width, height=height, ids=ids, types=types)

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def terrain(self, x: int, y: int) -> dict | None:
        if not self.inside(x, y):
            return None
        return self.types[self.ids[y][x]]

    def terrain_id(self, x: int, y: int) -> str:
        return self.ids[y][x]

    def level(self, x: int, y: int) -> int:
        entry = self.terrain(x, y)
        return int(entry.get("height", 0)) if entry else 0

    def elevation(self, x: int, y: int) -> float:
        """Top of the tile in metres."""
        return self.level(x, y) * ELEVATION_STEP

    def move_cost(self, x: int, y: int) -> int:
        entry = self.terrain(x, y)
        return max(1, int(entry.get("move_cost", 1))) if entry else 1

    def passable(self, x: int, y: int, movement_type: str = "ground") -> bool:
        entry = self.terrain(x, y)
        if entry is None:
            return False
        if not entry.get("blocked", False):
            return True
        return movement_type in entry.get("passable_by", [])


def reachable(
    grid: Grid,
    origin: tuple[int, int],
    movement_points: int,
    movement_type: str = "ground",
    occupied: frozenset[tuple[int, int]] = frozenset(),
) -> dict[tuple[int, int], int]:
    """Tiles the unit can end its move on, and what each costs to reach.

    A view-only reimplementation of Game.Rules/Tactical/Movement.cs, which is the
    authority: if the two ever disagree, the C# is right and this is wrong. It is
    duplicated rather than shelled out to because the renderer must not depend on
    a .NET toolchain being present, and because a highlight that is approximately
    right is worth far more to a screenshot than no highlight at all.

    Dijkstra rather than a flood fill, for the reason Movement.cs gives: forest
    and hill cost 2 and roads cost 1, so fewest steps is not cheapest.
    """
    import heapq

    cost = {origin: 0}
    frontier = [(0, origin)]
    while frontier:
        current_cost, current = heapq.heappop(frontier)
        if current_cost > cost.get(current, current_cost):
            continue
        x, y = current
        for step in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not grid.passable(step[0], step[1], movement_type):
                continue
            if step != origin and step in occupied:
                continue
            total = current_cost + grid.move_cost(step[0], step[1])
            if total > movement_points or total >= cost.get(step, total + 1):
                continue
            cost[step] = total
            heapq.heappush(frontier, (total, step))

    cost.pop(origin, None)
    return cost


# ---------------------------------------------------------------------------
# The battle
# ---------------------------------------------------------------------------


@dataclass
class Unit:
    id: str
    name: str
    side: str
    x: int
    y: int
    model: str | None
    height: float
    movement: int
    movement_type: str
    hp: int


@dataclass
class Prop:
    asset: str
    x: int
    y: int
    rotation: float
    scale: float


@dataclass
class Battle:
    id: str
    name: str
    grid: Grid
    units: list[Unit]
    props: list[Prop]
    active: Unit | None
    #: Tile -> movement cost for the active unit.
    range_tiles: dict[tuple[int, int], int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def occupied(self) -> frozenset[tuple[int, int]]:
        return frozenset((unit.x, unit.y) for unit in self.units)


_SIDE_KEYS = (("player_units", "player"), ("ally_units", "ally"), ("enemy_units", "enemy"))


def load_battle(path: str, *, data_root: str = DATA_ROOT, active: str | None = None) -> Battle:
    """Read a battle file into everything the renderer needs to draw it."""
    document = _load_json(path)
    grid = Grid.parse(list(document["terrain"]), load_terrain(data_root))
    declared = document.get("size", {})
    warnings: list[str] = []
    if declared and (declared.get("width"), declared.get("height")) != (grid.width, grid.height):
        warnings.append(
            f"declared size {declared.get('width')}x{declared.get('height')} does not match the "
            f"{grid.width}x{grid.height} terrain grid; drawing the grid")

    cast = load_cast(data_root)
    classes = load_classes(data_root)

    units: list[Unit] = []
    for key, side in _SIDE_KEYS:
        for entry in document.get(key, []):
            # A unit names its data under whichever key fits its origin: heroes
            # under `character`, spawned enemies under `enemy`, borrowed NPCs
            # under `npc`. All three resolve against the same flattened cast.
            reference = str(entry.get("character") or entry.get("enemy") or entry.get("npc") or "")
            record = cast.get(reference, {})
            if not record:
                warnings.append(f"{side} unit {reference or '?'} is not in characters.json")
            stats = record.get("baseStats", {})
            class_entry = classes.get(str(record.get("class", "")), {})
            model = str(record.get("model", "")) or None
            x, y = (int(v) for v in entry["position"])
            units.append(Unit(
                id=str(entry.get("id") or reference),
                name=str(record.get("displayName") or reference or "?"),
                side=side,
                x=x,
                y=y,
                model=model,
                height=UNIT_HEIGHTS.get(reference, DEFAULT_UNIT_HEIGHT),
                movement=int(stats.get("movement") or class_entry.get("movement") or 4),
                movement_type=str(class_entry.get("movement_type", "ground")),
                hp=int(stats.get("hp", 0)),
            ))

    props = [
        Prop(
            asset=str(entry["asset"]),
            x=int(entry["position"][0]),
            y=int(entry["position"][1]),
            rotation=float(entry.get("rotation", 0.0)),
            scale=float(entry.get("scale", 1.0)),
        )
        for entry in document.get("props", [])
    ]

    chosen = None
    players = [unit for unit in units if unit.side == "player"]
    if active:
        chosen = next((unit for unit in units if active in (unit.id, unit.name.lower())), None)
        if chosen is None:
            warnings.append(
                f"no unit {active!r} in this battle; highlighting the first player unit")
    if chosen is None:
        chosen = players[0] if players else (units[0] if units else None)

    battle = Battle(
        id=str(document.get("id", os.path.basename(path))),
        name=str(document.get("name", "")),
        grid=grid,
        units=units,
        props=props,
        active=chosen,
        warnings=warnings,
    )
    if chosen is not None:
        battle.range_tiles = reachable(
            grid, (chosen.x, chosen.y), chosen.movement, chosen.movement_type,
            battle.occupied - {(chosen.x, chosen.y)},
        )
    return battle


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _shift(colour, factor: float) -> tuple[int, int, int]:
    """Same hue, different value. Integer channels so the result is equally
    usable as a triangle colour and as a PIL fill."""
    shifted = tuple(min(255, max(0, round(channel * factor))) for channel in colour)
    return shifted  # type: ignore[return-value]


class Builder:
    """Accumulates the scene's triangles, their material and their colour.

    Terrain is flat colour and assets carry textures, so triangles need a
    per-triangle material rather than one texture for the whole buffer; the
    optional fields on preview.Geometry are what carry it.
    """

    def __init__(self) -> None:
        self.triangles: list = []
        self.uvs: list = []
        self.colours: list = []
        self.texture_index: list = []
        self.textures: list = []

    def triangle(self, a, b, c, colour) -> None:
        self.triangles.append((a, b, c))
        self.uvs.append(((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)))
        self.colours.append(colour)
        self.texture_index.append(-1)

    def quad(self, a, b, c, d, colour) -> None:
        """One flat quad. Wind a-b-c-d anticlockwise seen from the front face."""
        self.triangle(a, b, c, colour)
        self.triangle(a, c, d, colour)

    def top(self, x0: float, x1: float, z0: float, z1: float, y: float, colour) -> None:
        """A horizontal face with its normal up. The winding is the whole point:
        the rasteriser culls back faces, so a floor wound the other way vanishes."""
        self.quad((x0, y, z1), (x1, y, z1), (x1, y, z0), (x0, y, z0), colour)

    def box(self, x0, x1, y0, y1, z0, z1, colour, *, top_colour=None) -> None:
        """An axis-aligned box with outward normals on all six faces."""
        lid = colour if top_colour is None else top_colour
        self.top(x0, x1, z0, z1, y1, lid)
        self.quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), colour)   # -Y
        self.quad((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), colour)   # +X
        self.quad((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0), colour)   # -X
        self.quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), colour)   # +Z
        self.quad((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), colour)   # -Z

    def lathe(self, profile, y_offset: float, centre, colour, *, segments: int = 12) -> None:
        """A surface of revolution from a list of (height, radius).

        Cheap, closed, and it silhouettes cleanly, which is the only thing a
        stand-in for a character that has not been generated has to do.
        """
        cx, cz = centre
        ring = [(math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments))
                for i in range(segments)]
        for (y0, r0), (y1, r1) in zip(profile, profile[1:]):
            for i in range(segments):
                cos0, sin0 = ring[i]
                cos1, sin1 = ring[(i + 1) % segments]
                self.quad(
                    (cx + cos0 * r0, y_offset + y0, cz + sin0 * r0),
                    (cx + cos0 * r1, y_offset + y1, cz + sin0 * r1),
                    (cx + cos1 * r1, y_offset + y1, cz + sin1 * r1),
                    (cx + cos1 * r0, y_offset + y0, cz + sin1 * r0),
                    colour)
        top_y, top_r = profile[-1]
        if top_r > 0:
            self.disc(centre, top_r, y_offset + top_y, colour, segments=segments)

    def disc(self, centre, radius: float, y: float, colour, *, segments: int = 16) -> None:
        cx, cz = centre
        for i in range(segments):
            a0 = 2 * math.pi * i / segments
            a1 = 2 * math.pi * (i + 1) / segments
            self.triangle(
                (cx, y, cz),
                (cx + math.cos(a1) * radius, y, cz + math.sin(a1) * radius),
                (cx + math.cos(a0) * radius, y, cz + math.sin(a0) * radius),
                colour)

    def mesh(self, geometry, *, offset, rotation: float, scale: float) -> None:
        """Place a loaded GLB. Rotation is degrees about +Y, as the battle file
        gives it; a uniform positive scale keeps the winding, so nothing has to
        be re-wound."""
        numpy, _, _ = preview._require()
        angle = math.radians(rotation)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        points = numpy.asarray(geometry.triangles, dtype=float) * scale
        x = points[:, :, 0] * cos_a + points[:, :, 2] * sin_a
        z = -points[:, :, 0] * sin_a + points[:, :, 2] * cos_a
        placed = numpy.stack([x + offset[0], points[:, :, 1] + offset[1], z + offset[2]], axis=2)

        slot = len(self.textures)
        has_texture = geometry.texture is not None
        if has_texture:
            self.textures.append(geometry.texture)
        for index in range(len(placed)):
            self.triangles.append(placed[index])
            self.uvs.append(geometry.uvs[index] if len(geometry.uvs) else
                            ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)))
            self.colours.append((196.0, 196.0, 196.0))
            self.texture_index.append(slot if has_texture else -1)

    def geometry(self):
        numpy, _, _ = preview._require()
        return preview.Geometry(
            triangles=numpy.array(self.triangles, dtype=float),
            uvs=numpy.array(self.uvs, dtype=float),
            texture=None,
            colours=numpy.array(self.colours, dtype=float),
            texture_index=numpy.array(self.texture_index, dtype=int),
            textures=self.textures,
        )


def cell_centre(x: int, y: int) -> tuple[float, float]:
    """Grid cell to world (X, Z).

    North is +Z and the camera looks along +Z, so north is the far edge of the
    picture and the map reads the same way up as the battle file is written.
    """
    return ((x + 0.5) * TILE, (y + 0.5) * TILE)


def find_model(asset: str, model_root: str = MODEL_ROOT) -> str | None:
    """Locate an asset id under Content/Models, wherever its class put it."""
    matches = sorted(glob.glob(os.path.join(model_root, "**", f"{asset}.glb"), recursive=True))
    return matches[0] if matches else None


def _terrain_colour(terrain_id: str):
    return TERRAIN_COLOURS.get(terrain_id, UNKNOWN_TERRAIN_COLOUR)


def _add_terrain(builder: Builder, battle: Battle) -> None:
    grid = battle.grid
    base = min(grid.elevation(x, y) for y in range(grid.height) for x in range(grid.width))
    base -= BOARD_SKIRT

    for y in range(grid.height):
        for x in range(grid.width):
            terrain_id = grid.terrain_id(x, y)
            top = grid.elevation(x, y)
            centre_x, centre_z = cell_centre(x, y)
            x0, x1 = centre_x - TILE / 2, centre_x + TILE / 2
            z0, z1 = centre_z - TILE / 2, centre_z + TILE / 2

            fill = _terrain_colour(terrain_id)
            border = _shift(fill, 0.62)
            in_range = (x, y) in battle.range_tiles
            if in_range:
                # A light tint plus a bright border. At the 0.45 mix this started
                # at, half the board changed terrain colour and the road under
                # the deployment stopped being a road; the border is what reads.
                fill = _mix(fill, MOVE_FILL, 0.3)
                border = MOVE_EDGE
            if battle.active is not None and (x, y) == (battle.active.x, battle.active.y):
                border = ACTIVE_EDGE

            # The grid line is painted into the tile top as five non-overlapping
            # faces rather than laid over it. A lifted overlay quad trips the
            # outline pass; a coplanar one z-fights, which the first version did
            # and which speckled every tile with white pinholes.
            inner_x0, inner_x1 = x0 + GRID_BORDER, x1 - GRID_BORDER
            inner_z0, inner_z1 = z0 + GRID_BORDER, z1 - GRID_BORDER
            builder.top(x0, x1, z0, inner_z0, top, border)
            builder.top(x0, x1, inner_z1, z1, top, border)
            builder.top(x0, inner_x0, inner_z0, inner_z1, top, border)
            builder.top(inner_x1, x1, inner_z0, inner_z1, top, border)
            builder.top(inner_x0, inner_x1, inner_z0, inner_z1, top, fill)

            # A side wall only where the ground actually drops. Boxing every tile
            # puts two coplanar back-to-back faces on every shared edge, which
            # z-fights and hands the outline pass a false crease on every seam.
            side = _shift(_terrain_colour(terrain_id), 0.78)
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbour = (x + dx, y + dz)
                floor = grid.elevation(*neighbour) if grid.inside(*neighbour) else base
                if floor >= top:
                    continue
                if dx == 1:
                    builder.quad((x1, floor, z1), (x1, floor, z0),
                                 (x1, top, z0), (x1, top, z1), side)
                elif dx == -1:
                    builder.quad((x0, floor, z0), (x0, floor, z1),
                                 (x0, top, z1), (x0, top, z0), side)
                elif dz == 1:
                    builder.quad((x0, floor, z1), (x1, floor, z1),
                                 (x1, top, z1), (x0, top, z1), side)
                else:
                    builder.quad((x1, floor, z0), (x0, floor, z0),
                                 (x0, top, z0), (x1, top, z0), side)

            block = TERRAIN_BLOCKS.get(terrain_id)
            if block:
                # The Crownwall runs unbroken along the north edge, so its tiles
                # butt together; a fence post or a cart does not, and an inset is
                # what stops four fence tiles reading as one solid bunker.
                inset = 0.0 if terrain_id == "wall" else 0.12
                body = _terrain_colour(terrain_id)
                builder.box(x0 + inset, x1 - inset, top, top + block, z0 + inset, z1 - inset,
                            body, top_colour=_shift(body, 1.08))


def _add_props(builder: Builder, battle: Battle, cache: dict, model_root: str) -> None:
    for prop in battle.props:
        path = find_model(prop.asset, model_root)
        if path is None:
            battle.warnings.append(
                f"prop {prop.asset} at [{prop.x},{prop.y}]: no GLB under {model_root}, not drawn")
            continue
        if path not in cache:
            cache[path] = preview.read_geometry(path)
        centre_x, centre_z = cell_centre(prop.x, prop.y)
        builder.mesh(cache[path],
                     offset=(centre_x, battle.grid.elevation(prop.x, prop.y), centre_z),
                     rotation=prop.rotation, scale=prop.scale)


#: Profile of the stand-in figure as (fraction of height, radius in metres):
#: feet, hips, chest, shoulder, neck, head, crown. Deliberately not a box — a box
#: at this camera angle is indistinguishable from a crate, and the one thing a
#: placeholder must never do is read as scenery. The head runs from 0.78 upward,
#: which is rule 4's proportion: about six and a half heads tall, not eight.
_PLACEHOLDER_PROFILE = [
    (0.00, 0.24), (0.08, 0.28), (0.52, 0.27), (0.62, 0.26),
    (0.70, 0.12), (0.78, 0.19), (0.96, 0.19), (1.00, 0.10),
]
#: Index of the neck in _PLACEHOLDER_PROFILE, where the head tint starts.
_PLACEHOLDER_NECK = 4


def _add_units(builder: Builder, battle: Battle, cache: dict, model_root: str) -> int:
    placeholders = 0
    for unit in battle.units:
        centre_x, centre_z = cell_centre(unit.x, unit.y)
        elevation = battle.grid.elevation(unit.x, unit.y)
        side_colour = SIDE_COLOURS.get(unit.side, (200, 200, 200))

        # Every unit gets a base disc, model or not. It is the selection marker a
        # tactical game draws anyway, and it is what ties a unit to its tile when
        # the model overhangs the cell.
        builder.disc((centre_x, centre_z), 0.44, elevation + MARKER_LIFT,
                     _shift(side_colour, 0.55))
        builder.disc((centre_x, centre_z), 0.34, elevation + MARKER_LIFT * 1.5, side_colour)

        path = unit.model if unit.model and os.path.exists(unit.model) else None
        if path is None and unit.model:
            path = find_model(os.path.splitext(os.path.basename(unit.model))[0], model_root)
        if path is None:
            placeholders += 1
            battle.warnings.append(
                f"{unit.side} unit {unit.name} ({unit.id}): {unit.model or 'no model declared'} "
                "not generated, drawing a placeholder")
            profile = [(fraction * unit.height, radius * (unit.height / DEFAULT_UNIT_HEIGHT))
                       for fraction, radius in _PLACEHOLDER_PROFILE]
            builder.lathe(profile[:_PLACEHOLDER_NECK + 1], elevation,
                          (centre_x, centre_z), side_colour)
            builder.lathe(profile[_PLACEHOLDER_NECK:], elevation,
                          (centre_x, centre_z), _shift(side_colour, 1.4))
            continue

        if path not in cache:
            cache[path] = preview.read_geometry(path)
        # Units face the enemy, which for the prologue means players look north
        # and everyone else looks south. Enough to stop a whole army standing in
        # the same direction; real facing is per-unit state the engine owns.
        builder.mesh(cache[path], offset=(centre_x, elevation, centre_z),
                     rotation=0.0 if unit.side == "enemy" else 180.0, scale=1.0)
    return placeholders


def build(battle: Battle, *, model_root: str = MODEL_ROOT) -> tuple[object, int]:
    """The whole scene as one Geometry, plus the number of placeholder units."""
    builder = Builder()
    cache: dict = {}
    _add_terrain(builder, battle)
    _add_props(builder, battle, cache, model_root)
    placeholders = _add_units(builder, battle, cache, model_root)
    return builder.geometry(), placeholders


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _sky(width: int, height: int, numpy):
    """A vertical gradient to render the board against, as a colour buffer the
    rasteriser starts from rather than a flat fill."""
    top = numpy.array(SKY[0], dtype=float)
    horizon = numpy.array(SKY[1], dtype=float)
    ramp = numpy.linspace(0.0, 1.0, height)[:, None]
    return numpy.broadcast_to((top + (horizon - top) * ramp)[:, None, :],
                              (height, width, 3)).copy()


def _font(size: int):
    """Pillow's bundled font at a usable size. No font file is shipped with the
    repository, and a scene shot should not depend on one being installed."""
    from PIL import ImageFont
    return ImageFont.load_default(size=size)


def _plate(draw, xy, text, font, *, fill, ink, pad: int = 5) -> None:
    """Text on a filled plate. A bare name tag lands on grass, sky and armour in
    the same shot and is unreadable on at least one of them."""
    left, top = xy
    box = draw.textbbox((0, 0), text, font=font)
    width, height = box[2] - box[0], box[3] - box[1]
    draw.rectangle([left - pad, top - pad, left + width + pad, top + height + pad + 3], fill=fill)
    draw.text((left - box[0], top - box[1]), text, font=font, fill=ink)


def render_scene(
    battle_path: str,
    output: str,
    *,
    size: int = 1200,
    yaw: float = DEFAULT_YAW,
    pitch: float = DEFAULT_PITCH,
    textured: bool = True,
    toon: bool = True,
    outline: bool = True,
    labels: bool = True,
    active: str | None = None,
    data_root: str = DATA_ROOT,
    model_root: str = MODEL_ROOT,
    log=print,
) -> str:
    """Compose one battle and write it out. Returns the output path."""
    numpy, Image, ImageDraw = preview._require()

    battle = load_battle(battle_path, data_root=data_root, active=active)
    geometry, placeholders = build(battle, model_root=model_root)

    header = max(46, size // 17)
    footer = max(52, size // 20)
    # A board rotated by the yaw projects as a diamond, so it needs more height
    # than a rectangle of the same grid would; 0.78 is what stops the far corner
    # touching the header on the 14-row North Meadow grid.
    view_height = max(240, int(size * 0.78))

    camera = preview.fit_camera(geometry, size, yaw, pitch, margin=size // 30,
                                height=view_height)
    board = preview.render(geometry, size, yaw, pitch, textured=textured, toon=toon,
                           outline=outline, camera=camera, height=view_height,
                           background=_sky(size, view_height, numpy))

    sheet = Image.new("RGB", (size, header + view_height + footer), (18, 22, 28))
    sheet.paste(board, (0, header))
    draw = ImageDraw.Draw(sheet)

    title_font = _font(max(16, size // 55))
    small_font = _font(max(12, size // 80))

    draw.text((16, header // 2 - size // 110), f"{battle.name}   [{battle.id}]",
              font=title_font, fill=preview.INK)
    counts = {side: sum(1 for unit in battle.units if unit.side == side)
              for _, side in _SIDE_KEYS}
    draw.text((16, header + view_height + footer // 3 - size // 150),
              f"{battle.grid.width}x{battle.grid.height} grid   "
              f"{counts['player']} player / {counts['ally']} ally / {counts['enemy']} enemy   "
              f"{len(battle.props)} prop(s)   {placeholders} placeholder unit(s)   "
              f"{len(geometry.triangles):,} triangles",
              font=small_font, fill=preview.FAINT)

    if battle.active is not None:
        active_text = (f"active: {battle.active.name}   move {battle.active.movement}   "
                       f"{len(battle.range_tiles)} tiles in range")
        draw.text((size - 16 - draw.textlength(active_text, font=small_font),
                   header // 2 - size // 150),
                  active_text, font=small_font, fill=MOVE_EDGE)

    if labels and battle.units:
        heads = numpy.array([
            [cell_centre(unit.x, unit.y)[0],
             battle.grid.elevation(unit.x, unit.y) + unit.height + 0.12,
             cell_centre(unit.x, unit.y)[1]]
            for unit in battle.units])
        projected = camera.project(heads)
        # Far units first, so a near unit's tag covers a far one rather than the
        # other way round -- the same order the depth buffer resolved them in.
        order = sorted(range(len(battle.units)), key=lambda i: -projected[i][2])
        plate_height = max(14, size // 62)
        placed: list[tuple[float, float, float]] = []
        for i in order:
            unit = battle.units[i]
            # Six units called "Greenvale Soldier" tell the reader nothing. The
            # battle file's own unit id is both shorter and the handle the script
            # and the event actions refer to them by.
            text = unit.name if unit.side == "player" else unit.id
            width = draw.textlength(text, font=small_font)
            left = float(projected[i][0]) - width / 2
            top = float(projected[i][1]) + header - plate_height
            # Three heroes deploy shoulder to shoulder, so their tags land on top
            # of each other unless the later ones are stepped up out of the way.
            for other_left, other_top, other_width in placed:
                if (abs(top - other_top) < plate_height
                        and left < other_left + other_width and other_left < left + width):
                    top = other_top - plate_height
            placed.append((left, top, width))
            _plate(draw, (left, top), text, small_font,
                   fill=_shift(SIDE_COLOURS[unit.side], 0.42), ink=(246, 248, 252))

    sheet.save(output)
    for warning in battle.warnings:
        log(f"warning: {warning}")
    return output

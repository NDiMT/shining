using HollowCrown.Rules.Combat;

namespace HollowCrown.Rules.Tactical;

/// <summary>
/// Which tiles an attack can reach, and who is standing on them.
/// </summary>
/// <remarks>
/// <para>
/// Split from <see cref="Movement"/> because reach and movement obey different
/// rules: movement pays terrain costs and stops at obstacles, while range is plain
/// Manhattan distance and crosses a fence without noticing it. Battle 01 teaches
/// exactly that difference — Tomas' spear reaches two tiles over the fence line he
/// cannot walk through.
/// </para>
/// <para>
/// Line of sight is <b>not</b> applied. <c>blocks_line_of_sight</c> exists in
/// terrain.json and is unused until the rule that consumes it is written; when it
/// arrives it belongs here, and the battle HUD picks it up for free.
/// </para>
/// </remarks>
public static class Targeting
{
    /// <summary>
    /// Every on-field tile between <paramref name="minRange"/> and
    /// <paramref name="maxRange"/> tiles of <paramref name="origin"/>, by Manhattan
    /// distance. The origin itself is excluded whenever <paramref name="minRange"/>
    /// is at least 1, which is every weapon the game has.
    /// </summary>
    public static IReadOnlyCollection<Coord> Ring(
        BattleGrid grid, Coord origin, int minRange, int maxRange)
    {
        if (minRange < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(minRange), minRange, "must not be negative");
        }

        var tiles = new List<Coord>();
        if (maxRange < minRange)
        {
            return tiles;
        }

        // Walk the bounding square rather than the whole grid: a range-2 weapon on
        // a 12x14 field would otherwise test 168 tiles to find 12.
        for (int dy = -maxRange; dy <= maxRange; dy++)
        {
            int remaining = maxRange - Math.Abs(dy);
            for (int dx = -remaining; dx <= remaining; dx++)
            {
                int distance = Math.Abs(dx) + Math.Abs(dy);
                if (distance < minRange)
                {
                    continue;
                }

                Coord at = origin.Offset(dx, dy);
                if (grid.Contains(at))
                {
                    tiles.Add(at);
                }
            }
        }

        return tiles;
    }

    /// <summary>Tiles a unit standing at <paramref name="origin"/> could strike.</summary>
    public static IReadOnlyCollection<Coord> AttackableFrom(
        BattleGrid grid, Coord origin, int range) => Ring(grid, origin, 1, range);

    /// <summary>Tiles the unit could strike without moving.</summary>
    public static IReadOnlyCollection<Coord> AttackableFrom(BattleGrid grid, Unit unit) =>
        AttackableFrom(grid, unit.Position, unit.WeaponRange);

    /// <summary>
    /// Everything the unit could strike this turn if it moved first: the union of
    /// its reach from where it stands and from every tile it can reach.
    /// </summary>
    /// <remarks>
    /// This is the number a player actually needs — "can that goblin get me" — and
    /// it is the overlay the battle HUD draws for an enemy under the cursor. It is
    /// computed rather than approximated by move + range, because terrain costs
    /// make the reachable set a shape rather than a diamond.
    /// </remarks>
    public static IReadOnlyCollection<Coord> ThreatRange(
        BattleGrid grid, ReachableSet reach, int range)
    {
        var tiles = new HashSet<Coord>();
        foreach (Coord from in reach.Tiles.Append(reach.Origin))
        {
            foreach (Coord at in Ring(grid, from, 1, range))
            {
                tiles.Add(at);
            }
        }

        return tiles;
    }

    /// <summary>The unit standing on a tile, if any. Defeated and fled units are gone.</summary>
    public static Unit? UnitAt(IEnumerable<Unit> units, Coord at) =>
        units.FirstOrDefault(u => u.Active && u.Position == at);

    /// <summary>Hostile units the attacker could strike right now, nearest first.</summary>
    /// <remarks>
    /// Ordered by distance so the presentation layer's default target is the
    /// obvious one, and so the order is stable between frames; ties break on id for
    /// the same determinism reason <see cref="TurnOrder"/> does it.
    /// </remarks>
    public static IReadOnlyList<Unit> TargetsInRange(Unit attacker, IEnumerable<Unit> units) =>
        units
            .Where(u => u.Active
                        && !ReferenceEquals(u, attacker)
                        && attacker.IsHostileTo(u)
                        && DamageModel.InWeaponRange(attacker, u))
            .OrderBy(u => attacker.Position.DistanceTo(u.Position))
            .ThenBy(u => u.Id, StringComparer.Ordinal)
            .ToList();
}

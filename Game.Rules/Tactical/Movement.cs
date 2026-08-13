namespace HollowCrown.Rules.Tactical;

/// <summary>Where a unit can reach, and how it gets there.</summary>
public sealed class ReachableSet
{
    private readonly Dictionary<Coord, int> _cost;
    private readonly Dictionary<Coord, Coord> _cameFrom;

    internal ReachableSet(Coord origin, Dictionary<Coord, int> cost, Dictionary<Coord, Coord> cameFrom)
    {
        Origin = origin;
        _cost = cost;
        _cameFrom = cameFrom;
    }

    public Coord Origin { get; }

    /// <summary>Every tile the unit can end its move on, excluding where it stands.</summary>
    public IReadOnlyCollection<Coord> Tiles => _cost.Keys;

    public bool CanReach(Coord at) => _cost.ContainsKey(at);

    public int? CostTo(Coord at) => _cost.TryGetValue(at, out int c) ? c : null;

    /// <summary>
    /// The tiles walked through to reach <paramref name="destination"/>, excluding
    /// the origin and including the destination. Empty if unreachable.
    /// </summary>
    public IReadOnlyList<Coord> PathTo(Coord destination)
    {
        if (!_cost.ContainsKey(destination))
        {
            return Array.Empty<Coord>();
        }

        var path = new List<Coord>();
        Coord step = destination;
        // The came-from chain is acyclic by construction; the bound is a guard
        // against a corrupted set rather than an expected case.
        for (int guard = 0; guard <= _cost.Count + 1; guard++)
        {
            path.Add(step);
            if (!_cameFrom.TryGetValue(step, out Coord previous))
            {
                break;
            }

            if (previous == Origin)
            {
                break;
            }

            step = previous;
        }

        path.Reverse();
        return path;
    }
}

/// <summary>
/// Movement range over weighted terrain.
/// </summary>
/// <remarks>
/// Dijkstra rather than a breadth-first flood, because terrain costs differ:
/// brief section 24 gives forest and hill a cost of 2 and roads a cost of 1, so
/// the cheapest route to a tile is not the one with the fewest steps.
/// </remarks>
public static class Movement
{
    public static ReachableSet Reachable(
        BattleGrid grid,
        Coord origin,
        int movementPoints,
        string movementType = "ground",
        Func<Coord, bool>? isOccupied = null)
    {
        var cost = new Dictionary<Coord, int> { [origin] = 0 };
        var cameFrom = new Dictionary<Coord, Coord>();
        var frontier = new PriorityQueue<Coord, int>();
        frontier.Enqueue(origin, 0);

        while (frontier.TryDequeue(out Coord current, out int currentCost))
        {
            // A tile can be queued more than once; skip the stale entries.
            if (cost.TryGetValue(current, out int best) && currentCost > best)
            {
                continue;
            }

            foreach (Coord next in current.Neighbours())
            {
                TerrainType? terrain = grid.TryGet(next);
                if (terrain is null || !terrain.IsPassableBy(movementType))
                {
                    continue;
                }

                // A unit may pass through nothing, but it may end on its own tile.
                if (isOccupied is not null && next != origin && isOccupied(next))
                {
                    continue;
                }

                int total = currentCost + Math.Max(1, terrain.MoveCost);
                if (total > movementPoints)
                {
                    continue;
                }

                if (cost.TryGetValue(next, out int existing) && existing <= total)
                {
                    continue;
                }

                cost[next] = total;
                cameFrom[next] = current;
                frontier.Enqueue(next, total);
            }
        }

        cost.Remove(origin);
        return new ReachableSet(origin, cost, cameFrom);
    }
}

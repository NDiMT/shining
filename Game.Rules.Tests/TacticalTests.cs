using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Core;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;
using Xunit;

namespace HollowCrown.Rules.Tests;

public sealed class BattleGridTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    [Fact]
    public void TheTerrainGridIsReadNorthRowFirst()
    {
        // Row 0 of the file is the highest Y. Getting this backwards would mirror
        // every battlefield vertically and put the Crownwall behind the player.
        var rows = new List<string> { "tt", "gg" };
        BattleGrid grid = BattleGrid.Parse(rows, Content.Terrain);

        Assert.Equal("forest", grid[new Coord(0, 1)].Id);   // north
        Assert.Equal("grass", grid[new Coord(0, 0)].Id);    // south
    }

    [Fact]
    public void RaggedGridsAreRejected()
    {
        ArgumentException error = Assert.Throws<ArgumentException>(
            () => BattleGrid.Parse(new List<string> { "gg", "g" }, Content.Terrain));
        Assert.Contains("row 1", error.Message);
    }

    [Fact]
    public void UnknownSymbolsAreRejectedWithTheSymbolNamed()
    {
        ArgumentException error = Assert.Throws<ArgumentException>(
            () => BattleGrid.Parse(new List<string> { "g?" }, Content.Terrain));
        Assert.Contains("'?'", error.Message);
    }

    [Fact]
    public void TerrainCanBeChangedAtRuntime()
    {
        // Battle 02's turn-3 event turns Crownwall into rubble so the Wallstalker
        // can come through. Without this the event cannot exist.
        BattleGrid grid = BattleGrid.Parse(new List<string> { "WW", "gg" }, Content.Terrain);
        var at = new Coord(0, 1);

        Assert.True(grid[at].Blocked);
        grid.SetTerrain(at, "rubble");
        Assert.False(grid[at].Blocked);
        Assert.Equal("rubble", grid[at].Id);
    }

    [Fact]
    public void OutOfBoundsReadsAreCaughtRatherThanWrapping()
    {
        BattleGrid grid = BattleGrid.Parse(new List<string> { "gg", "gg" }, Content.Terrain);
        Assert.Null(grid.TryGet(new Coord(5, 5)));
        Assert.Throws<ArgumentOutOfRangeException>(() => grid[new Coord(-1, 0)]);
    }
}

public sealed class MovementTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleGrid Grid(params string[] rows) =>
        BattleGrid.Parse(rows.ToList(), Content.Terrain);

    [Fact]
    public void MovementPointsBoundTheRangeOnFlatGround()
    {
        BattleGrid grid = Grid("ggggg", "ggggg", "ggggg", "ggggg", "ggggg");
        ReachableSet reach = Movement.Reachable(grid, new Coord(2, 2), 2);

        // A Manhattan diamond of radius 2, minus the origin.
        Assert.Equal(12, reach.Tiles.Count);
        Assert.True(reach.CanReach(new Coord(4, 2)));
        Assert.False(reach.CanReach(new Coord(2, 2)));
        Assert.Equal(2, reach.CostTo(new Coord(4, 2)));
    }

    [Fact]
    public void TerrainCostIsPaidPerTile()
    {
        // A hill costs 2, so with 2 points a unit reaches the hill but not past it.
        BattleGrid grid = Grid("ggg", "ghg", "ggg");
        ReachableSet reach = Movement.Reachable(grid, new Coord(0, 1), 2);

        Assert.Equal(2, reach.CostTo(new Coord(1, 1)));
        Assert.False(reach.CanReach(new Coord(2, 1)));
    }

    [Fact]
    public void ASingleForestTileIsStillWorthCuttingThrough()
    {
        // Direct: forest 2 + grass 1 = 3. Around: four grass = 4. Cutting through
        // wins, and a flood fill that ignored cost would agree by accident.
        BattleGrid grid = Grid("ggg", "gtg", "ggg");
        ReachableSet reach = Movement.Reachable(grid, new Coord(0, 1), 4);

        Assert.Equal(3, reach.CostTo(new Coord(2, 1)));
        Assert.Contains(new Coord(1, 1), reach.PathTo(new Coord(2, 1)));
    }

    [Fact]
    public void DijkstraTakesTheCheaperRouteNotTheShorterOne()
    {
        // Three forest tiles in the way. Straight through is 4 steps costing 7;
        // around is 6 steps costing 6. A breadth-first flood would take the short
        // expensive route, which is exactly the bug this guards.
        BattleGrid grid = Grid("ggggg", "gtttg", "ggggg");
        ReachableSet reach = Movement.Reachable(grid, new Coord(0, 1), 7);

        var destination = new Coord(4, 1);
        Assert.Equal(6, reach.CostTo(destination));

        IReadOnlyList<Coord> path = reach.PathTo(destination);
        Assert.Equal(6, path.Count);
        Assert.DoesNotContain(new Coord(1, 1), path);
        Assert.DoesNotContain(new Coord(2, 1), path);
        Assert.DoesNotContain(new Coord(3, 1), path);
    }

    [Fact]
    public void BlockedTerrainIsImpassable()
    {
        BattleGrid grid = Grid("ggg", "fff", "ggg");
        ReachableSet reach = Movement.Reachable(grid, new Coord(1, 0), 6);

        Assert.False(reach.CanReach(new Coord(1, 1)));
        Assert.False(reach.CanReach(new Coord(1, 2)));
    }

    [Fact]
    public void FlyingUnitsCrossFences()
    {
        BattleGrid grid = Grid("ggg", "fff", "ggg");
        ReachableSet flying = Movement.Reachable(grid, new Coord(1, 0), 6, movementType: "flying");
        Assert.True(flying.CanReach(new Coord(1, 2)));
    }

    [Fact]
    public void OccupiedTilesCannotBeEnteredOrPassedThrough()
    {
        BattleGrid grid = Grid("ggg", "ggg", "ggg");
        var blocker = new Coord(1, 1);
        ReachableSet reach = Movement.Reachable(
            grid, new Coord(1, 0), 2, isOccupied: c => c == blocker);

        Assert.False(reach.CanReach(blocker));
        // [1,2] is only two steps away through the blocker, so it must be out of
        // reach: units are obstacles, not scenery.
        Assert.False(reach.CanReach(new Coord(1, 2)));
    }

    [Fact]
    public void PathEndsAtTheDestinationAndExcludesTheOrigin()
    {
        BattleGrid grid = Grid("ggggg", "ggggg", "ggggg");
        var origin = new Coord(0, 0);
        ReachableSet reach = Movement.Reachable(grid, origin, 4);
        IReadOnlyList<Coord> path = reach.PathTo(new Coord(3, 0));

        Assert.Equal(3, path.Count);
        Assert.DoesNotContain(origin, path);
        Assert.Equal(new Coord(3, 0), path[^1]);
    }

    [Fact]
    public void AnUnreachableDestinationGivesAnEmptyPath()
    {
        BattleGrid grid = Grid("ggg", "fff", "ggg");
        ReachableSet reach = Movement.Reachable(grid, new Coord(0, 0), 3);
        Assert.Empty(reach.PathTo(new Coord(0, 2)));
    }
}

public sealed class TurnOrderTests
{
    private static Unit Fast(string id, int agility) =>
        Unit.Create(id, id, Side.Player, new Stats { Hp = 10, Agility = agility, Movement = 4 });

    [Fact]
    public void OrderIsByDescendingAgility()
    {
        var units = new[] { Fast("slow", 3), Fast("quick", 9), Fast("middling", 6) };
        var order = new TurnOrder();
        order.BeginRound(units);

        Assert.Equal(new[] { "quick", "middling", "slow" }, order.Order);
        Assert.Equal("quick", order.Current);
    }

    [Fact]
    public void TiesBreakOnIdSoReplaysDoNotDiverge()
    {
        // Brief section 74. Insertion order or a random tiebreak would make the
        // same seed produce a different battle.
        var forward = new[] { Fast("bravo", 7), Fast("alpha", 7) };
        var backward = new[] { Fast("alpha", 7), Fast("bravo", 7) };

        var first = new TurnOrder();
        first.BeginRound(forward);
        var second = new TurnOrder();
        second.BeginRound(backward);

        Assert.Equal(first.Order, second.Order);
        Assert.Equal("alpha", first.Current);
    }

    [Fact]
    public void DefeatedUnitsAreLeftOutOfTheNextRound()
    {
        Unit dead = Fast("dead", 8);
        Unit alive = Fast("alive", 4);
        dead.Defeated = true;

        var order = new TurnOrder();
        order.BeginRound(new[] { dead, alive });

        Assert.Equal(new[] { "alive" }, order.Order);
    }

    [Fact]
    public void AdvanceReportsTheEndOfTheRound()
    {
        var order = new TurnOrder();
        order.BeginRound(new[] { Fast("a", 5), Fast("b", 4) });

        Assert.True(order.Advance());
        Assert.Equal("b", order.Current);
        Assert.False(order.Advance());
        Assert.Null(order.Current);
    }

    [Fact]
    public void RemovingAUnitBeforeTheCursorDoesNotSkipTheNextOne()
    {
        // The fleeing goblin spearman leaves mid-round. Removing its entry without
        // adjusting the cursor would silently skip whoever came next.
        var order = new TurnOrder();
        order.BeginRound(new[] { Fast("a", 9), Fast("b", 8), Fast("c", 7) });
        order.Advance();                       // now on "b"
        Assert.Equal("b", order.Current);

        order.Remove("a");
        Assert.Equal("b", order.Current);      // still "b", not "c"
    }
}

public sealed class RngTests
{
    [Fact]
    public void TheSameSeedProducesTheSameSequence()
    {
        var first = new Rng(12345);
        var second = new Rng(12345);
        int[] a = Enumerable.Range(0, 50).Select(_ => first.Next(1000)).ToArray();
        int[] b = Enumerable.Range(0, 50).Select(_ => second.Next(1000)).ToArray();
        Assert.Equal(a, b);
    }

    [Fact]
    public void DifferentSeedsDiverge()
    {
        var first = new Rng(1);
        var second = new Rng(2);
        int[] a = Enumerable.Range(0, 20).Select(_ => first.Next(1000)).ToArray();
        int[] b = Enumerable.Range(0, 20).Select(_ => second.Next(1000)).ToArray();
        Assert.NotEqual(a, b);
    }

    [Fact]
    public void DrawsAreCountedForTheReplayRecord()
    {
        var rng = new Rng(7);
        rng.Next(10);
        rng.Range(1, 6);
        Assert.True(rng.Draws >= 2);
    }

    [Fact]
    public void RangeStaysInsideItsBounds()
    {
        var rng = new Rng(99);
        for (int i = 0; i < 2000; i++)
        {
            int roll = rng.Range(3, 7);
            Assert.InRange(roll, 3, 7);
        }
    }

    [Fact]
    public void ChanceIsRoughlyFairAtTheEdges()
    {
        var rng = new Rng(2024);
        Assert.False(rng.Chance(0));
        Assert.True(rng.Chance(100));

        int hits = Enumerable.Range(0, 10_000).Count(_ => rng.Chance(25));
        Assert.InRange(hits, 2200, 2800);
    }

    [Fact]
    public void ForkedStreamsAreIndependentButReproducible()
    {
        // So an unrelated system drawing randomness cannot shift a battle's rolls.
        var parent = new Rng(555);
        Rng a = parent.Fork(1);
        Rng b = parent.Fork(1);
        Rng c = parent.Fork(2);

        Assert.Equal(a.Next(10_000), b.Next(10_000));
        Assert.NotEqual(new Rng(555).Fork(1).Next(10_000), c.Next(10_000));
    }

    [Fact]
    public void ZeroOrNegativeBoundsAreRejected()
    {
        var rng = new Rng(1);
        Assert.Throws<ArgumentOutOfRangeException>(() => rng.Next(0));
        Assert.Throws<ArgumentOutOfRangeException>(() => rng.Range(5, 4));
    }
}

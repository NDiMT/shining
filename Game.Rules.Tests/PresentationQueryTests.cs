using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;
using Xunit;

namespace HollowCrown.Rules.Tests;

/// <summary>
/// The queries the Godot battle scene calls, tested without an engine.
/// </summary>
/// <remarks>
/// Everything the presentation layer needs that can be expressed as a number or a
/// set of coordinates lives in Game.Rules precisely so it can be covered here.
/// What is left in Game.Godot is node wiring, and node wiring cannot be verified
/// without the editor — so the less of it there is, the less of the scene is
/// unverified. docs/GODOT_SCENE.md draws that line explicitly.
/// </remarks>
public sealed class GridLayoutTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleGrid Grid(params string[] rows) =>
        BattleGrid.Parse(rows.ToList(), Content.Terrain);

    private static BattleDefinition NorthMeadow() => BattleLoader.Load(
        Path.Combine(TestPaths.Data, "Battles", "battle_north_meadow.json"), Content);

    [Fact]
    public void NorthIsNegativeZ()
    {
        // The failure this exists to catch: a mirrored battlefield still looks like
        // a plausible battlefield. North Meadow puts the player on the road in the
        // south and the goblins in the north, so if this flips, the first battle
        // plays with the camera behind the enemy line and nobody notices for weeks.
        BattleGrid grid = Grid("gg", "gg", "gg");
        var layout = new GridLayout(grid);

        WorldPoint south = layout.Centre(new Coord(0, 0));
        WorldPoint north = layout.Centre(new Coord(0, 2));

        Assert.True(north.Z < south.Z);
    }

    [Fact]
    public void EastIsPositiveX()
    {
        var layout = new GridLayout(Grid("ggg"));
        Assert.True(layout.Centre(new Coord(2, 0)).X > layout.Centre(new Coord(0, 0)).X);
    }

    [Fact]
    public void TheFileIsReadNorthRowFirstAllTheWayToWorldSpace()
    {
        // BattleGrid.Parse already flips the rows; this pins the whole chain, from
        // the row a human edits to the metres the scene builder places a tile at.
        BattleGrid grid = Grid(
            "tt",   // written first, therefore the NORTH row
            "gg");
        var layout = new GridLayout(grid);

        Coord forest = grid.AllCoords().Single(c => grid[c].Id == "forest" && c.X == 0);
        Coord grass = grid.AllCoords().Single(c => grid[c].Id == "grass" && c.X == 0);

        Assert.True(layout.Centre(forest).Z < layout.Centre(grass).Z);
    }

    [Fact]
    public void TheFieldIsCentredOnTheOrigin()
    {
        // The camera orbits about (0,0,0), so a field that is not centred there
        // makes every orbit look like it is swinging around a corner of the map.
        var layout = new GridLayout(Grid("gggg", "gggg"));

        float minX = layout.Centre(new Coord(0, 0)).X;
        float maxX = layout.Centre(new Coord(3, 0)).X;
        Assert.Equal(0.0, (double)(minX + maxX), 4);
    }

    [Fact]
    public void HeightLevelsBecomeMetres()
    {
        // terrain.json gives hill height 1 and everything else 0.
        BattleGrid grid = Grid("hg");
        var layout = new GridLayout(grid);

        Assert.Equal((double)GridLayout.DefaultHeightStep, (double)layout.Centre(new Coord(0, 0)).Y, 4);
        Assert.Equal(0.0, (double)layout.Centre(new Coord(1, 0)).Y, 4);
    }

    [Fact]
    public void EveryTileOfTheRealBattleRoundTrips()
    {
        // Mouse picking is Centre() inverted. If they disagree anywhere, clicking a
        // tile selects its neighbour, which is the kind of bug that reads as "the
        // controls feel wrong" rather than as an error.
        BattleDefinition battle = NorthMeadow();
        var layout = new GridLayout(battle.Grid);

        foreach (Coord at in battle.Grid.AllCoords())
        {
            WorldPoint centre = layout.Centre(at);
            Assert.Equal(at, layout.Resolve(centre.X, centre.Z));
            Assert.Equal(at, layout.Clamp(centre.X, centre.Z));
        }
    }

    [Fact]
    public void PointsInsideATileResolveToThatTile()
    {
        var layout = new GridLayout(Grid("gg", "gg"), tileSize: 2.0f);
        WorldPoint centre = layout.Centre(new Coord(1, 1));

        // Just inside each edge of the 2 m tile.
        Assert.Equal(new Coord(1, 1), layout.Resolve(centre.X + 0.9f, centre.Z + 0.9f));
        Assert.Equal(new Coord(1, 1), layout.Resolve(centre.X - 0.9f, centre.Z - 0.9f));
    }

    [Fact]
    public void PointsOffTheFieldResolveToNothingButClampBackOn()
    {
        var layout = new GridLayout(Grid("gg", "gg"));

        Assert.Null(layout.Resolve(500f, 0f));

        // Far east and far north is the north-east corner: north is -Z.
        Assert.Equal(new Coord(1, 1), layout.Clamp(500f, -500f));
        Assert.Equal(new Coord(0, 0), layout.Clamp(-500f, 500f));
    }

    [Fact]
    public void TheFieldMeasuresTilesTimesTileSize()
    {
        var layout = new GridLayout(NorthMeadow().Grid);

        Assert.Equal(24.0, (double)layout.FieldWidth, 4);   // 12 tiles
        Assert.Equal(28.0, (double)layout.FieldDepth, 4);   // 14 tiles
    }

    [Fact]
    public void ATileSizeOfZeroIsRejectedRatherThanDividedBy()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => new GridLayout(Grid("g"), tileSize: 0f));
    }
}

public sealed class TargetingTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleGrid Grid(params string[] rows) =>
        BattleGrid.Parse(rows.ToList(), Content.Terrain);

    [Fact]
    public void RangeIsAManhattanDiamondWithoutTheCentre()
    {
        BattleGrid grid = Grid("ggggg", "ggggg", "ggggg", "ggggg", "ggggg");
        IReadOnlyCollection<Coord> tiles = Targeting.AttackableFrom(grid, new Coord(2, 2), 2);

        Assert.Equal(12, tiles.Count);
        Assert.DoesNotContain(new Coord(2, 2), tiles);
        Assert.Contains(new Coord(2, 4), tiles);
        Assert.DoesNotContain(new Coord(3, 3), tiles.Where(t => t.DistanceTo(new Coord(2, 2)) > 2));
    }

    [Fact]
    public void RangeIsClippedToTheField()
    {
        BattleGrid grid = Grid("gg", "gg");
        IReadOnlyCollection<Coord> tiles = Targeting.AttackableFrom(grid, new Coord(0, 0), 1);

        Assert.Equal(2, tiles.Count);
        Assert.All(tiles, t => Assert.True(grid.Contains(t)));
    }

    [Fact]
    public void RangeIgnoresTerrainBecauseASpearReachesOverAFence()
    {
        // Battle 01's fence at [2,6]-[3,7] blocks movement and nothing else. Tomas
        // standing beside it must still be able to hit what is on the far side, or
        // the weapon-range tutorial teaches the wrong lesson.
        BattleGrid grid = Grid("ggg", "fff", "ggg");
        IReadOnlyCollection<Coord> tiles = Targeting.AttackableFrom(grid, new Coord(1, 0), 2);

        Assert.Contains(new Coord(1, 1), tiles);   // the fence tile itself
        Assert.Contains(new Coord(1, 2), tiles);   // beyond it
    }

    [Fact]
    public void AMinimumRangeCarvesOutTheCentre()
    {
        BattleGrid grid = Grid("ggggg", "ggggg", "ggggg", "ggggg", "ggggg");
        IReadOnlyCollection<Coord> tiles = Targeting.Ring(grid, new Coord(2, 2), 2, 2);

        Assert.Equal(8, tiles.Count);
        Assert.All(tiles, t => Assert.Equal(2, t.DistanceTo(new Coord(2, 2))));
    }

    [Fact]
    public void AnEmptyRangeIsEmptyRatherThanAnError()
    {
        BattleGrid grid = Grid("gg", "gg");
        Assert.Empty(Targeting.Ring(grid, new Coord(0, 0), 3, 2));
        Assert.Throws<ArgumentOutOfRangeException>(
            () => Targeting.Ring(grid, new Coord(0, 0), -1, 2));
    }

    [Fact]
    public void ThreatRangeCoversEverythingAMoveThenAttackCouldReach()
    {
        // "Can that goblin get me this turn." One move point on flat ground plus a
        // range-1 weapon reaches two tiles away, which a plain attack ring does not.
        BattleGrid grid = Grid("ggggg", "ggggg", "ggggg", "ggggg", "ggggg");
        var origin = new Coord(2, 2);
        ReachableSet reach = Movement.Reachable(grid, origin, movementPoints: 1);

        IReadOnlyCollection<Coord> threat = Targeting.ThreatRange(grid, reach, range: 1);

        // Two tiles away in a straight line: one step, then a range-1 swing.
        Assert.Contains(new Coord(2, 4), threat);
        Assert.Contains(new Coord(2, 0), threat);
        Assert.Contains(origin, threat);           // it can step aside and hit back

        // Four tiles away by Manhattan distance, so out of reach either way.
        Assert.DoesNotContain(new Coord(0, 0), threat);
    }

    [Fact]
    public void ThreatRangeRespectsTerrainCostRatherThanStepCount()
    {
        // Forest costs 2. With 2 move points the unit can enter the forest but not
        // cross it, so the tile beyond is out of reach even though it is two steps.
        BattleGrid grid = Grid("ggg", "gtg", "ggg", "ggg");
        var origin = new Coord(1, 0);
        ReachableSet reach = Movement.Reachable(grid, origin, movementPoints: 2);

        IReadOnlyCollection<Coord> threat = Targeting.ThreatRange(grid, reach, range: 1);

        Assert.Contains(new Coord(1, 2), threat);        // reachable forest, +1 reach
        Assert.DoesNotContain(new Coord(1, 3), threat);  // needs 3 points to stand adjacent
    }

    [Fact]
    public void UnitsAreFoundByTileAndDefeatedOnesAreNot()
    {
        var units = new List<Unit>
        {
            Unit.Create("a", "A", Side.Player, default),
            Unit.Create("b", "B", Side.Enemy, default),
        };
        units[0].Position = new Coord(1, 1);
        units[1].Position = new Coord(2, 2);

        Assert.Equal("a", Targeting.UnitAt(units, new Coord(1, 1))!.Id);
        Assert.Null(Targeting.UnitAt(units, new Coord(3, 3)));

        units[1].Defeated = true;
        Assert.Null(Targeting.UnitAt(units, new Coord(2, 2)));
    }

    [Fact]
    public void TargetsInRangeUseTheRealBattleAndComeBackNearestFirst()
    {
        BattleDefinition battle = BattleLoader.Load(
            Path.Combine(TestPaths.Data, "Battles", "battle_north_meadow.json"), Content);

        Unit tomas = battle.Units.First(u => u.Id == "tomas");
        Assert.Equal(2, tomas.WeaponRange);      // the spear that teaches weapon range

        // Nothing is in reach at deployment: the player line is south on the road,
        // the goblins are seven rows north.
        Assert.Empty(Targeting.TargetsInRange(tomas, battle.Units));

        Unit raider = battle.Units.First(u => u.Id == "raider_1");
        tomas.Position = raider.Position.Offset(0, -2);

        IReadOnlyList<Unit> targets = Targeting.TargetsInRange(tomas, battle.Units);
        Assert.Contains(targets, u => u.Id == "raider_1");
        Assert.All(targets, u => Assert.Equal(Side.Enemy, u.Side));
    }
}

public sealed class PropPlacementTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleDefinition NorthMeadow() => BattleLoader.Load(
        Path.Combine(TestPaths.Data, "Battles", "battle_north_meadow.json"), Content);

    [Fact]
    public void NorthMeadowsPropsLoad()
    {
        BattleDefinition battle = NorthMeadow();

        Assert.Equal(11, battle.Props.Count);
        Assert.Contains(battle.Props, p => p.AssetId == "prop_merchant_cart_overturned");
        Assert.Equal(4, battle.Props.Count(p => p.AssetId == "prop_fence_section"));
    }

    [Fact]
    public void AnAbsentScaleIsOneRatherThanZero()
    {
        // A defaulted 0 would shrink every prop without a scale field to nothing,
        // and the scene would look empty rather than broken.
        PropPlacement tree = NorthMeadow().Props.First(p => p.AssetId == "veg_tree_oak_a");
        Assert.Equal(1.0, tree.Scale, 6);

        PropPlacement scaled = NorthMeadow().Props.First(
            p => p.AssetId == "veg_rock_a" && p.Position == new Coord(10, 10));
        Assert.Equal(0.8, scaled.Scale, 6);
    }

    [Fact]
    public void RotationSurvivesAsWritten()
    {
        PropPlacement cart = NorthMeadow().Props.First(
            p => p.AssetId == "prop_merchant_cart_overturned");

        Assert.Equal(25.0, cart.RotationDegrees, 6);
        Assert.Equal(new Coord(5, 8), cart.Position);
    }

    [Fact]
    public void APropOffTheEdgeIsRejectedWithItsNameAndTile()
    {
        // Props are parsed in the rules layer rather than in the scene builder so
        // that this fails at load, next to the same check on units, rather than
        // producing a tree hanging in space that nobody notices in a screenshot.
        // A prop off the grid almost always means the file was edited against the
        // wrong axis.
        string path = Path.Combine(Path.GetTempPath(), $"prop_offgrid_{Guid.NewGuid():N}.json");
        File.WriteAllText(path, """
        {
          "id": "test_offgrid",
          "size": { "width": 2, "height": 2 },
          "terrain": ["gg", "gg"],
          "props": [{ "asset": "veg_tree_oak_a", "position": [0, 9] }]
        }
        """);

        try
        {
            ContentException error = Assert.Throws<ContentException>(
                () => BattleLoader.Load(path, Content));
            Assert.Contains("veg_tree_oak_a", error.Message);
            Assert.Contains("[0,9]", error.Message);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void EveryPropSitsOnTheField()
    {
        BattleDefinition battle = NorthMeadow();
        Assert.All(battle.Props, p => Assert.True(battle.Grid.Contains(p.Position)));
    }

    [Fact]
    public void ThePropsAgreeWithTheTerrainUnderneathThem()
    {
        // The cart is set dressing for the two 'o' obstacle tiles, and the fence
        // models for the 'f' tiles. Nothing enforces that pairing at load time —
        // props carry no rules — so this is the check that they have not drifted.
        BattleDefinition battle = NorthMeadow();

        PropPlacement cart = battle.Props.First(p => p.AssetId == "prop_merchant_cart_overturned");
        Assert.Equal("obstacle", battle.Grid[cart.Position].Id);

        foreach (PropPlacement fence in battle.Props.Where(p => p.AssetId == "prop_fence_section"))
        {
            Assert.Equal("fence", battle.Grid[fence.Position].Id);
        }
    }
}

public sealed class UnitPresentationDataTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    [Fact]
    public void SpawnedUnitsCarryTheirClassAndModel()
    {
        // The battle HUD names the class, and the scene builder needs the model
        // path to know whether it can load a mesh or must fall back to a
        // placeholder. Both come from content, so neither belongs in Godot.
        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(5, 1));

        Assert.Equal("swordsman", rowan.ClassId);
        Assert.Equal("Swordsman", rowan.ClassName);
        Assert.Equal("Content/Models/Characters/hero_rowan.glb", rowan.ModelPath);
    }

    [Fact]
    public void EnemiesCarryThemToo()
    {
        Unit raider = Content.Spawn("goblin_raider", Side.Enemy, new Coord(4, 9), "raider_1");

        Assert.Equal("Goblin Raider", raider.ClassName);
        Assert.Equal("Content/Models/Enemies/enemy_goblin_raider.glb", raider.ModelPath);
    }

    [Fact]
    public void EveryPrologueDefinitionNamesAModel()
    {
        // Not that the file exists — most of the catalog has not been generated —
        // but that something is named, so a missing mesh is a missing *asset* and
        // never a missing *reference*.
        foreach (CharacterDefinition definition in
                 Content.Characters.Values.Concat(Content.Enemies.Values))
        {
            Assert.False(string.IsNullOrWhiteSpace(definition.ModelPath),
                $"{definition.Id} has no model path");
        }
    }
}

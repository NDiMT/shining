using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;
using Xunit;

namespace HollowCrown.Rules.Tests;

/// <summary>
/// The prologue's shipped battle files, loaded by the real loader.
/// </summary>
/// <remarks>
/// These are the regression guard between the two halves of the project. The
/// Python tooling validates <c>Content/Data</c> offline; this loads the same files
/// through the engine's own code. If they ever disagree about the grid, the
/// coordinate convention or a reference, one of them is wrong and the build says
/// so.
/// </remarks>
public sealed class RealBattleTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleDefinition Load(string file) =>
        BattleLoader.Load(Path.Combine(TestPaths.Data, "Battles", file), Content);

    [Fact]
    public void NorthMeadowLoads()
    {
        BattleDefinition battle = Load("battle_north_meadow.json");

        Assert.Equal("battle_north_meadow", battle.Id);
        Assert.Equal(12, battle.Grid.Width);
        Assert.Equal(14, battle.Grid.Height);

        // Script: Rowan, Maeve, Tomas against 4 raiders, 2 spearmen, 1 archer.
        Assert.Equal(3, battle.Units.Count(u => u.Side == Side.Player));
        Assert.Equal(7, battle.Units.Count(u => u.Side == Side.Enemy));
    }

    [Fact]
    public void NorthMeadowHasTheScriptedComposition()
    {
        BattleDefinition battle = Load("battle_north_meadow.json");
        string[] players = battle.Units
            .Where(u => u.Side == Side.Player)
            .Select(u => u.Id)
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToArray();

        Assert.Equal(new[] { "maeve", "rowan", "tomas" }, players);
        Assert.Equal(4, battle.Units.Count(u => u.Id.StartsWith("raider", StringComparison.Ordinal)));
        Assert.Equal(2, battle.Units.Count(u => u.Id.StartsWith("spearman", StringComparison.Ordinal)));
        Assert.Single(battle.Units.Where(u => u.Id.StartsWith("archer", StringComparison.Ordinal)));
    }

    [Fact]
    public void EveryUnitStartsOnAPassableTile()
    {
        // The Python validator asserts the same thing about the same file. Two
        // independent implementations agreeing is the point.
        foreach (string file in new[] { "battle_north_meadow.json", "battle_the_breach.json" })
        {
            BattleDefinition battle = Load(file);
            foreach (Unit unit in battle.Units)
            {
                TerrainType terrain = battle.Grid[unit.Position];
                Assert.False(terrain.Blocked,
                    $"{file}: {unit.Id} starts on {terrain.Name} at {unit.Position}");
            }
        }
    }

    [Fact]
    public void NoTwoUnitsShareATile()
    {
        foreach (string file in new[] { "battle_north_meadow.json", "battle_the_breach.json" })
        {
            BattleDefinition battle = Load(file);
            Assert.Equal(battle.Units.Count, battle.Units.Select(u => u.Position).Distinct().Count());
        }
    }

    [Fact]
    public void TheHillIsWhereTheArcherTutorialExpectsIt()
    {
        // The script has the archer take the hill to teach height. If the hill
        // moves, the tutorial stops making sense.
        BattleDefinition battle = Load("battle_north_meadow.json");
        TerrainType hill = battle.Grid[new Coord(5, 11)];

        Assert.Equal("hill", hill.Id);
        Assert.Equal(1, hill.Height);
    }

    [Fact]
    public void TheNorthEdgeIsAnEscapeRoute()
    {
        // The fleeing spearman leaves north, toward the Wall.
        BattleDefinition battle = Load("battle_north_meadow.json");
        for (int x = 0; x < battle.Grid.Width; x++)
        {
            Assert.True(battle.Grid[new Coord(x, 13)].IsExit);
        }
    }

    [Fact]
    public void EveryPlayerUnitCanActOnTurnOne()
    {
        // A unit walled in at deployment would be a silently broken battle.
        BattleDefinition battle = Load("battle_north_meadow.json");
        var occupied = battle.Units.Select(u => u.Position).ToHashSet();

        foreach (Unit unit in battle.Units.Where(u => u.Side == Side.Player))
        {
            ReachableSet reach = Movement.Reachable(
                battle.Grid, unit.Position, unit.MovementPoints,
                unit.MovementType, c => occupied.Contains(c));
            Assert.NotEmpty(reach.Tiles);
        }
    }

    [Fact]
    public void TheBreachIsNonLethalForItsHumanEnemies()
    {
        // Script, SPECIAL BATTLE RULE. Rowan must not become a murderer in his
        // first hour.
        BattleDefinition battle = Load("battle_the_breach.json");

        Assert.True(battle.IsNonLethalFor(Side.Enemy));
        Assert.False(battle.IsNonLethalFor(Side.Player));
    }

    [Fact]
    public void TheBreachStartsAsASurvivalObjective()
    {
        BattleDefinition battle = Load("battle_the_breach.json");
        ObjectiveDefinition objective = Assert.Single(battle.Objectives);

        Assert.Equal("survive_turns", objective.Type);
        Assert.Equal(3, objective.Turns);
    }

    [Fact]
    public void TheBreachHasAnImpassableCrownwallAlongItsNorthEdge()
    {
        BattleDefinition battle = Load("battle_the_breach.json");
        for (int x = 0; x < battle.Grid.Width; x++)
        {
            TerrainType wall = battle.Grid[new Coord(x, battle.Grid.Height - 1)];
            Assert.True(wall.Blocked, $"[{x},{battle.Grid.Height - 1}] should be Crownwall");
            Assert.Empty(wall.PassableBy);          // not even flying units
        }
    }

    [Fact]
    public void TheWallstalkerCanBeSpawnedOnceItsTileIsCleared()
    {
        // The turn-3 event converts [6,10] from Crownwall to rubble and then spawns
        // the beast there. Prove both halves work, in that order.
        BattleDefinition battle = Load("battle_the_breach.json");
        var spawn = new Coord(6, 10);

        Assert.True(battle.Grid[spawn].Blocked);
        battle.Grid.SetTerrain(spawn, "rubble");
        Assert.False(battle.Grid[spawn].Blocked);

        Unit beast = Content.Spawn("wallstalker", Side.HostileToAll, spawn);
        Assert.Equal(60, beast.MaxHp);
        Assert.Equal(8, beast.Armour.Front);
        Assert.Equal(0, beast.Armour.Rear);
    }

    [Fact]
    public void TheWallstalkerIsHostileToEveryone()
    {
        // On turn 3 the Greenvale soldiers become allies against it, so the beast
        // must count both sides as enemies.
        Unit beast = Content.Spawn("wallstalker", Side.HostileToAll, Coord.Zero);
        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(1, 0));
        Unit varric = Content.Spawn("varric", Side.Ally, new Coord(2, 0));

        Assert.True(beast.IsHostileTo(rowan));
        Assert.True(beast.IsHostileTo(varric));
        Assert.False(rowan.IsHostileTo(varric));
    }

    [Fact]
    public void AMalformedBattleFailsWithTheFileNamed()
    {
        ContentException error = Assert.Throws<ContentException>(
            () => BattleLoader.Load(Path.Combine(TestPaths.Data, "Battles", "nope.json"), Content));
        Assert.Contains("nope.json", error.Message);
    }
}

public sealed class ContentDatabaseTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    [Fact]
    public void TheShippedContentLoads()
    {
        Assert.NotEmpty(Content.Terrain);
        Assert.NotEmpty(Content.Classes);
        Assert.NotEmpty(Content.Characters);
        Assert.NotEmpty(Content.Enemies);
        Assert.NotEmpty(Content.Weapons);
        Assert.NotEmpty(Content.Skills);
    }

    [Fact]
    public void TerrainRulesComeFromDataNotFromCode()
    {
        TerrainType forest = Content.Terrain.Single(t => t.Id == "forest");
        Assert.Equal(2, forest.MoveCost);
        Assert.Equal(2, forest.DefenseBonus);
        Assert.True(forest.BlocksLineOfSight);

        TerrainType wall = Content.Terrain.Single(t => t.Id == "wall");
        Assert.True(wall.Blocked);
        Assert.Empty(wall.PassableBy);
    }

    [Fact]
    public void SpawningAppliesClassArmourAndStartingEquipment()
    {
        Unit tomas = Content.Spawn("tomas", Side.Player, Coord.Zero);
        Assert.Equal("soldier_spear", tomas.Weapon?.Id);
        Assert.Equal(2, tomas.ArmourDefense);          // guard_mail

        Unit beast = Content.Spawn("wallstalker", Side.Enemy, Coord.Zero);
        Assert.Equal(new DirectionalArmour(8, 2, 0), beast.Armour);
    }

    [Fact]
    public void UnknownDefinitionsFailWithAUsefulMessage()
    {
        ContentException error = Assert.Throws<ContentException>(
            () => Content.Spawn("gandalf", Side.Player, Coord.Zero));
        Assert.Contains("gandalf", error.Message);
        Assert.Contains("characters.json", error.Message);
    }

    [Fact]
    public void MissingDataDirectoryFailsWithThePathNamed()
    {
        ContentException error = Assert.Throws<ContentException>(
            () => ContentDatabase.Load("/nonexistent/Content/Data"));
        Assert.Contains("terrain.json", error.Message);
    }
}

using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Core;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;
using Xunit;

namespace HollowCrown.Rules.Tests;

/// <summary>
/// The prologue script states exact numbers. These tests hold the rules to them.
/// </summary>
/// <remarks>
/// This is the whole point of keeping the rules free of Godot: the script says
/// "Damage number: 8", and that claim is now a build-breaking assertion rather
/// than a hope. If someone retunes Rowan's attack or a raider's defence, the
/// build tells them they changed the script's opening beat.
///
/// They load the real Content/Data, so they also prove the loader and the data
/// agree.
/// </remarks>
public sealed class PrologueNumbersTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleGrid FlatGrass(int width = 8, int height = 8)
    {
        var rows = Enumerable.Repeat(new string('g', width), height).ToList();
        return BattleGrid.Parse(rows, Content.Terrain);
    }

    [Fact]
    public void RowanOpeningHitOnARaiderDealsExactlyEight()
    {
        BattleGrid grid = FlatGrass();
        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(2, 2));
        Unit raider = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 3));

        DamageForecast forecast = DamageModel.ForecastPhysical(rowan, raider, grid);

        // Script, BATTLE TUTORIAL: "Damage number: 8".
        // Attack 8 + Iron Sword 3 - Raider defence 3 = 8.
        Assert.Equal(8, forecast.Damage);
        Assert.False(forecast.Lethal);
    }

    [Fact]
    public void RowanNeedsTwoHitsToKillARaider()
    {
        BattleGrid grid = FlatGrass();
        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(2, 2));
        Unit raider = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 3));
        var rng = new Rng(1);

        DamageModel.Apply(raider, DamageModel.ForecastPhysical(rowan, raider, grid), rng, false);
        Assert.False(raider.Defeated);
        Assert.Equal(4, raider.Hp);

        DamageModel.Apply(raider, DamageModel.ForecastPhysical(rowan, raider, grid), rng, false);
        Assert.True(raider.Defeated);
    }

    [Fact]
    public void SparkDealsElevenAndTakesTwoCastsToKillARaider()
    {
        Unit maeve = Content.Spawn("maeve", Side.Player, new Coord(2, 2));
        Unit raider = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 4));
        Skill spark = Assert.Single(maeve.Skills.Where(s => s.Id == "spark"));

        DamageForecast forecast = DamageModel.ForecastSkill(maeve, raider, spark);

        // Power 6 + magic 4 + staff 2 - resistance 1 = 11, against 12 HP.
        // Deliberately not lethal in one cast: an apprentice must not out-damage
        // the protagonist in the tutorial battle.
        Assert.Equal(11, forecast.Damage);
        Assert.False(forecast.Lethal);
        Assert.Equal(3, spark.Cost);
        Assert.Equal(3, spark.Range);
    }

    [Fact]
    public void MaeveHasFourCastsOfSpark()
    {
        Unit maeve = Content.Spawn("maeve", Side.Player, Coord.Zero);
        Skill spark = maeve.FindSkill("spark")!;
        Assert.Equal(12, maeve.Mp);
        Assert.Equal(4, maeve.Mp / spark.Cost);
    }

    [Fact]
    public void TomasSpearReachesTwoTiles()
    {
        Unit tomas = Content.Spawn("tomas", Side.Player, new Coord(2, 2));
        Unit far = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 4));
        Unit tooFar = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 5), "raider_far");

        // The script uses Tomas to teach weapon range, so 2 is load-bearing.
        Assert.Equal(2, tomas.WeaponRange);
        Assert.True(DamageModel.InWeaponRange(tomas, far));
        Assert.False(DamageModel.InWeaponRange(tomas, tooFar));
    }

    [Theory]
    // Wallstalker defence 6, plus class directional armour 8 / 2 / 0.
    // Rowan's 11 attack power against each: the positioning lesson, in numbers.
    //
    // Mind the axis. Y increases NORTHWARD, so an attacker at dy = +1 stands north
    // of a north-facing beast and meets its armoured front, while dy = -1 is
    // behind it. Writing this table the other way round is how it was got wrong
    // the first time.
    [InlineData(Heading.North, 0, 1, Facing.Front, 1)]
    [InlineData(Heading.North, 1, 0, Facing.Flank, 3)]
    [InlineData(Heading.North, -1, 0, Facing.Flank, 3)]
    [InlineData(Heading.North, 0, -1, Facing.Rear, 5)]
    [InlineData(Heading.South, 0, -1, Facing.Front, 1)]
    [InlineData(Heading.East, 1, 0, Facing.Front, 1)]
    [InlineData(Heading.East, -1, 0, Facing.Rear, 5)]
    public void WallstalkerArmourMakesFlankingTheOnlySensiblePlay(
        Heading facing, int dx, int dy, Facing expectedFacing, int expectedDamage)
    {
        BattleGrid grid = FlatGrass(10, 10);
        Unit beast = Content.Spawn("wallstalker", Side.Enemy, new Coord(5, 5));
        beast.Heading = facing;
        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(5 + dx, 5 + dy));

        DamageForecast forecast = DamageModel.ForecastPhysical(rowan, beast, grid);

        Assert.Equal(expectedFacing, forecast.Facing);
        Assert.Equal(expectedDamage, forecast.Damage);
    }

    [Fact]
    public void AFrontalAttackOnTheWallstalkerIsFiveTimesWorseThanARearOne()
    {
        BattleGrid grid = FlatGrass(10, 10);
        Unit beast = Content.Spawn("wallstalker", Side.Enemy, new Coord(5, 5));
        beast.Heading = Heading.North;

        // North is +Y, so the unit standing at a higher Y is the one in front of it.
        Unit front = Content.Spawn("rowan", Side.Player, new Coord(5, 6), "front");
        Unit rear = Content.Spawn("rowan", Side.Player, new Coord(5, 4), "rear");

        int frontDamage = DamageModel.ForecastPhysical(front, beast, grid).Damage;
        int rearDamage = DamageModel.ForecastPhysical(rear, beast, grid).Damage;

        Assert.Equal(5, rearDamage / frontDamage);
    }

    [Fact]
    public void GoblinsThreatenRowanRatherThanTicklingHim()
    {
        // Measured during prototyping: at defence 6 every goblin hit landed on the
        // minimum-damage floor, so the prologue's first battle had no threat at
        // all. Four damage per hit is the fix, and it is worth locking in.
        BattleGrid grid = FlatGrass();
        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(2, 2));
        Unit raider = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 3));

        DamageForecast onRowan = DamageModel.ForecastPhysical(raider, rowan, grid);

        Assert.Equal(4, onRowan.Damage);
        Assert.True(onRowan.Damage > DamageModel.MinimumDamage,
            "a goblin landing on the damage floor means the stats are wrong, not that the floor is");
        Assert.Equal(6, (int)Math.Ceiling(rowan.Hp / (double)onRowan.Damage));
    }

    [Fact]
    public void MaeveIsTheSquishiestAndTomasIsTheWall()
    {
        BattleGrid grid = FlatGrass();
        Unit raider = Content.Spawn("goblin_raider", Side.Enemy, new Coord(2, 3));

        Unit maeve = Content.Spawn("maeve", Side.Player, new Coord(2, 2));
        Unit tomas = Content.Spawn("tomas", Side.Player, new Coord(2, 2), "tomas_probe");

        int onMaeve = DamageModel.ForecastPhysical(raider, maeve, grid).Damage;
        int onTomas = DamageModel.ForecastPhysical(raider, tomas, grid).Damage;

        // Three hits down Maeve, which is what teaches the player to keep her
        // behind Rowan — the thing Aldric orders in scene 04.
        Assert.Equal(3, (int)Math.Ceiling(maeve.Hp / (double)onMaeve));
        Assert.True(onTomas < onMaeve, "Tomas must be the obvious unit to put in front");
    }

    [Fact]
    public void TerrainDefenceReducesDamage()
    {
        var rows = new List<string> { "gg", "gt" };   // forest at [1,0]
        BattleGrid grid = BattleGrid.Parse(rows, Content.Terrain);

        Unit rowan = Content.Spawn("rowan", Side.Player, new Coord(0, 0));
        Unit inTheOpen = Content.Spawn("goblin_raider", Side.Enemy, new Coord(0, 1), "open");
        Unit inForest = Content.Spawn("goblin_raider", Side.Enemy, new Coord(1, 0), "forest");

        int open = DamageModel.ForecastPhysical(rowan, inTheOpen, grid).Damage;
        int forest = DamageModel.ForecastPhysical(rowan, inForest, grid).Damage;

        Assert.Equal(8, open);
        Assert.Equal(6, forest);                       // forest gives +2 defence
        Assert.Equal(2, DamageModel.ForecastPhysical(rowan, inForest, grid).TerrainDefense);
    }

    [Fact]
    public void HeightGivesTheAttackerAPoint()
    {
        var rows = new List<string> { "hg", "gg" };     // hill at [0,1]
        BattleGrid grid = BattleGrid.Parse(rows, Content.Terrain);

        Unit high = Content.Spawn("goblin_archer", Side.Enemy, new Coord(0, 1), "high");
        Unit low = Content.Spawn("goblin_archer", Side.Enemy, new Coord(1, 1), "low");
        Unit target = Content.Spawn("rowan", Side.Player, new Coord(1, 0));

        int fromHill = DamageModel.ForecastPhysical(high, target, grid).Damage;
        int fromFlat = DamageModel.ForecastPhysical(low, target, grid).Damage;

        Assert.Equal(1, DamageModel.ForecastPhysical(high, target, grid).HeightBonus);
        Assert.Equal(fromFlat + 1, fromHill);
    }
}

internal static class TestPaths
{
    /// <summary>
    /// Path to the repository's Content/Data, found by walking up from the test
    /// assembly. The tests deliberately read the real shipped content rather than
    /// fixtures, so they fail if the data and the rules drift apart.
    /// </summary>
    public static string Data { get; } = Locate();

    private static string Locate()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            string candidate = Path.Combine(directory.FullName, "Content", "Data");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException(
            "could not find Content/Data above " + AppContext.BaseDirectory);
    }
}

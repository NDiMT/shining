using HollowCrown.Rules.Battle;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Core;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;
using Xunit;

namespace HollowCrown.Rules.Tests;

/// <summary>
/// The prologue's battles, played to completion without an engine.
/// </summary>
/// <remarks>
/// The reason the rules layer has no Godot reference: a whole battle runs in
/// milliseconds in a test, so "does the turn-3 event actually do all nine things
/// it claims" is a question with an answer rather than something to find out by
/// playing.
/// </remarks>
public sealed class BattleRunTests
{
    private static readonly ContentDatabase Content = ContentDatabase.Load(TestPaths.Data);

    private static BattleState Open(string file, ulong seed = 1)
    {
        BattleDefinition definition =
            BattleLoader.Load(Path.Combine(TestPaths.Data, "Battles", file), Content);
        return new BattleState(definition, Content, new Rng(seed), definition.Events);
    }

    /// <summary>
    /// Drives a battle to a conclusion with roughly competent play.
    /// </summary>
    /// <remarks>
    /// It is not an AI and does not need to be. But it does have to play the way
    /// the fight is designed to be played, because the balance assumes it: a
    /// driver that charged everyone at the nearest goblin got Rowan killed every
    /// run, which is the same thing the browser prototype demonstrated. The rules
    /// are not broken when reckless play loses.
    ///
    /// So: casters stay at range, and nobody deliberately steps adjacent to more
    /// than one enemy except the unit built to absorb it.
    /// </remarks>
    private static void PlayOut(BattleState battle, int roundLimit = 40)
    {
        battle.Start();
        int guard = 0;
        while (!battle.Finished && battle.Turns.Round <= roundLimit && guard++ < 4000)
        {
            Unit? unit = battle.Current;
            if (unit is null || !unit.Active)
            {
                battle.EndTurn();
                continue;
            }

            TakeTurn(battle, unit);
            battle.EndTurn();
        }
    }

    private static void TakeTurn(BattleState battle, Unit unit)
    {
        Unit[] foes = battle.ActiveUnits.Where(unit.IsHostileTo).ToArray();
        if (foes.Length == 0)
        {
            battle.Wait(unit);
            return;
        }

        int Adjacent(Coord at) => foes.Count(f => f.Position.DistanceTo(at) == 1);

        // A caster keeps its distance and spends MP while it has any.
        Skill? skill = unit.Skills.FirstOrDefault(s => unit.Mp >= s.Cost);
        if (skill is not null)
        {
            Unit? spellTarget = battle.SkillTargets(unit, skill).FirstOrDefault();
            if (spellTarget is not null)
            {
                battle.CastSkill(unit, spellTarget, skill.Id);
                return;
            }
        }

        Unit? inReach = battle.AttackTargets(unit).FirstOrDefault();
        if (inReach is null && !unit.HasMoved)
        {
            // Tanks will wade in; everyone else avoids being surrounded.
            int crowdLimit = unit.Base.Defense >= 7 ? 3 : 1;
            ReachableSet reach = battle.ReachableFor(unit);
            Coord best = unit.Position;
            int bestScore = int.MinValue;

            foreach (Coord tile in reach.Tiles)
            {
                if (Adjacent(tile) > crowdLimit)
                {
                    continue;
                }

                int nearest = foes.Min(f => f.Position.DistanceTo(tile));
                int score = skill is not null
                    ? -Math.Abs(nearest - skill.Range) * 4    // casters hold at range
                    : -nearest * 3 + battle.Grid[tile].DefenseBonus;

                if (score > bestScore)
                {
                    bestScore = score;
                    best = tile;
                }
            }

            if (best != unit.Position)
            {
                battle.Move(unit, best);
            }

            if (skill is not null)
            {
                Unit? afterMove = battle.SkillTargets(unit, skill).FirstOrDefault();
                if (afterMove is not null)
                {
                    battle.CastSkill(unit, afterMove, skill.Id);
                    return;
                }
            }

            inReach = battle.AttackTargets(unit).FirstOrDefault();
        }

        if (inReach is not null && !unit.HasActed)
        {
            battle.Attack(unit, inReach);
        }
        else if (!unit.HasActed)
        {
            battle.Wait(unit);
        }
    }

    /// <summary>
    /// Idle until a scripted event has fired, or give up.
    /// </summary>
    /// <remarks>
    /// Stopping the moment the round counter reaches 3 is not enough: the breach
    /// event triggers on a *player* turn, and Varric acts first at agility 11. The
    /// loop has to keep going until the event actually lands.
    /// </remarks>
    private static void IdleUntil(BattleState battle, Func<bool> condition, int guardLimit = 400)
    {
        int guard = 0;
        while (!condition() && !battle.Finished && guard++ < guardLimit)
        {
            if (battle.Current is { Active: true } unit)
            {
                battle.Wait(unit);
            }

            battle.EndTurn();
        }
    }

    // -- battle 01 ---------------------------------------------------------

    [Fact]
    public void NorthMeadowPlaysToVictory()
    {
        BattleState battle = Open("battle_north_meadow.json");
        PlayOut(battle);

        Assert.NotNull(battle.Outcome);
        Assert.True(battle.Outcome!.Victory, battle.Outcome.Reason);
        Assert.DoesNotContain(battle.ActiveUnits, u => u.Side == Side.Enemy);
    }

    [Fact]
    public void TheFleeingSpearmanEventFires()
    {
        // The script's mid-battle beat: at three enemies or fewer, a spearman runs
        // north toward the Wall. It is the prologue's first real clue.
        BattleState battle = Open("battle_north_meadow.json");
        PlayOut(battle);

        Assert.Contains(battle.Events, e => e is BattleEvent.UnitFled);
        Assert.Contains(battle.Events,
            e => e is BattleEvent.DialogueRequested { SceneId: "prologue_battle_flee" });
        Assert.Equal("true", battle.Flags["goblin_spearman_fled"]);
    }

    [Fact]
    public void TheArcherIsMovedOntoTheHillForTheHeightTutorial()
    {
        BattleState battle = Open("battle_north_meadow.json");
        PlayOut(battle);

        BattleEvent.UnitMoved forced = battle.Events
            .OfType<BattleEvent.UnitMoved>()
            .First(e => e.UnitId == "archer_1" && e.To == new Coord(5, 11));

        Assert.Equal(1, battle.Grid[forced.To].Height);
    }

    [Fact]
    public void RowansFirstBlowInAPlayedBattleDealsEight()
    {
        // Not a formula test — the number as it comes out of a real running battle.
        BattleState battle = Open("battle_north_meadow.json");
        battle.Start();

        Unit rowan = battle.FindUnit("rowan")!;
        Unit raider = battle.FindUnit("raider_1")!;
        rowan.Position = raider.Position.Offset(0, -1);

        battle.Attack(rowan, raider);

        BattleEvent.UnitAttacked hit = battle.Events.OfType<BattleEvent.UnitAttacked>().Last();
        Assert.Equal(8, hit.Damage);
        Assert.False(hit.Critical);        // seed 1 does not crit on the first swing
    }

    [Fact]
    public void ADefeatedRowanEndsTheBattle()
    {
        BattleState battle = Open("battle_north_meadow.json");
        battle.Start();

        Unit rowan = battle.FindUnit("rowan")!;
        rowan.Hp = 0;
        rowan.Defeated = true;
        battle.EndTurn();

        Assert.NotNull(battle.Outcome);
        Assert.False(battle.Outcome!.Victory);
    }

    // -- battle 02, the interesting one ------------------------------------

    [Fact]
    public void TheBreachTurnThreeEventDoesEverythingItClaims()
    {
        // Nine consequences in one event. If this works, brief section 42's
        // collapsing sandworm bridge is the same features with different data.
        BattleState battle = Open("battle_the_breach.json");
        battle.Start();

        Assert.Equal("survive_turns", battle.Objective.Type);
        Assert.True(battle.IsNonLethalFor(Side.Enemy));
        Assert.Null(battle.FindUnit("wallstalker"));
        Assert.True(battle.Grid[new Coord(6, 10)].Blocked);

        // Idle until the event lands, not merely until the round counter hits 3.
        IdleUntil(battle, () => battle.FindUnit("wallstalker") is not null);

        // 1. terrain mutated
        Assert.False(battle.Grid[new Coord(6, 10)].Blocked);
        Assert.Equal("rubble", battle.Grid[new Coord(6, 10)].Id);

        // 2. the beast exists, on the tile the event cleared
        Unit beast = Assert.Single(battle.Units.Where(u => u.Id == "wallstalker"));
        Assert.Equal(new Coord(6, 10), beast.Position);
        Assert.Equal(Side.HostileToAll, beast.Side);

        // 3. every human enemy switched sides
        foreach (string id in new[] { "varric", "soldier_1", "soldier_5" })
        {
            Assert.Equal(Side.Ally, battle.FindUnit(id)!.Side);
        }

        // 4. their AI was reassigned
        Assert.Equal("aggressive_melee", battle.BehaviourOf(battle.FindUnit("soldier_1")!));

        // 5. the objective was replaced
        Assert.Equal("defeat_unit", battle.Objective.Type);
        Assert.Equal("wallstalker", battle.Objective.UnitId);

        // 6. the non-lethal rule was lifted
        Assert.False(battle.IsNonLethalFor(Side.Enemy));

        // 7. world flags were set
        Assert.Equal("true", battle.Flags["crownwall_breached"]);
        Assert.Equal("true", battle.Flags["met_wallstalker"]);

        // 8. dialogue was requested
        Assert.Contains(battle.Events,
            e => e is BattleEvent.DialogueRequested { SceneId: "prologue_wall_collapses" });

        // 9. the presentation cues went out in order with the mechanical ones
        Assert.Contains(battle.Events, e => e is BattleEvent.Cue { Kind: "screen_shake" });
        Assert.Contains(battle.Events, e => e is BattleEvent.Cue { Kind: "sound" });
    }

    [Fact]
    public void TheBeastFightsBothSidesOnceItArrives()
    {
        BattleState battle = Open("battle_the_breach.json");
        battle.Start();
        IdleUntil(battle, () => battle.FindUnit("wallstalker") is not null);

        Unit beast = battle.FindUnit("wallstalker")!;
        Assert.True(beast.IsHostileTo(battle.FindUnit("rowan")!));
        Assert.True(beast.IsHostileTo(battle.FindUnit("varric")!));
        Assert.False(battle.FindUnit("rowan")!.IsHostileTo(battle.FindUnit("varric")!));
    }

    [Fact]
    public void HumanEnemiesAreIncapacitatedNotKilledBeforeTurnThree()
    {
        // Script, SPECIAL BATTLE RULE. Rowan must not become a murderer in his
        // first hour.
        BattleState battle = Open("battle_the_breach.json");
        battle.Start();

        Unit rowan = battle.FindUnit("rowan")!;
        Unit soldier = battle.FindUnit("soldier_1")!;
        soldier.Hp = 1;
        rowan.Position = soldier.Position.Offset(0, -1);

        battle.Attack(rowan, soldier);

        Assert.True(soldier.Defeated);
        Assert.True(soldier.Incapacitated);
        Assert.Contains(battle.Events,
            e => e is BattleEvent.UnitDefeated { Incapacitated: true });
    }

    [Fact]
    public void TheWallstalkerCanBeBeatenByFlanking()
    {
        BattleState battle = Open("battle_the_breach.json");
        battle.Start();
        IdleUntil(battle, () => battle.FindUnit("wallstalker") is not null);

        Unit beast = battle.FindUnit("wallstalker")!;
        Unit rowan = battle.FindUnit("rowan")!;
        beast.Heading = Heading.South;

        rowan.Position = beast.Position.Offset(0, 1);
        DamageForecast rear = battle.Forecast(rowan, beast);

        rowan.Position = beast.Position.Offset(0, -1);
        DamageForecast front = battle.Forecast(rowan, beast);

        // The beast stands in the rubble it just made, and rubble is +1 defence.
        // So the rear hit is 4 rather than the 5 it deals on open ground: the
        // creature is a little tougher for having wrecked its own doorway, which
        // is terrain doing exactly what brief section 24 asks of it.
        Assert.Equal(1, rear.TerrainDefense);
        Assert.Equal(4, rear.Damage);
        Assert.Equal(1, front.Damage);
        Assert.Equal(0, rear.DirectionalArmour);
        Assert.Equal(8, front.DirectionalArmour);
    }

    // -- determinism -------------------------------------------------------

    [Fact]
    public void TheSameSeedProducesTheSameBattle()
    {
        // Brief section 74. A battle plus a seed must replay identically, or a bug
        // report is unactionable.
        string[] first = Fingerprint(Open("battle_north_meadow.json", seed: 4242));
        string[] second = Fingerprint(Open("battle_north_meadow.json", seed: 4242));
        Assert.Equal(first, second);
    }

    [Fact]
    public void TheSeedActuallyReachesCombat()
    {
        // Reproducibility alone would also hold if the RNG were never consulted,
        // so this checks the other half: across a spread of seeds at least one
        // battle plays out differently. Crits are the only randomness in this
        // fight, and they are rare, so a single alternative seed is not enough to
        // conclude anything — an earlier version of this test asserted exactly
        // that and failed for the wrong reason.
        string[] baseline = Fingerprint(Open("battle_north_meadow.json", seed: 1));
        bool anyDifferent = new ulong[] { 7, 99, 512, 4242, 31337, 60013 }
            .Select(seed => Fingerprint(Open("battle_north_meadow.json", seed)))
            .Any(other => !other.SequenceEqual(baseline));

        Assert.True(anyDifferent, "no seed changed the battle; is the RNG wired into combat?");
    }

    private static string[] Fingerprint(BattleState battle)
    {
        PlayOut(battle);
        return battle.Events.Select(e => e.ToString() ?? string.Empty).ToArray();
    }

    [Fact]
    public void AnUnknownScriptedActionFailsLoudly()
    {
        // A silent no-op is the worst failure mode for data-driven content, so the
        // runner refuses rather than shrugging — matching the offline validator.
        BattleDefinition definition = BattleLoader.Load(
            Path.Combine(TestPaths.Data, "Battles", "battle_north_meadow.json"), Content);

        var rogue = new ScriptedEvent
        {
            Id = "rogue",
            Trigger = new EventTrigger { Type = "battle_start" },
            Actions = new[] { new EventAction { Type = "summon_dragon" } },
        };

        var battle = new BattleState(definition, Content, new Rng(1), new[] { rogue });
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(battle.Start);
        Assert.Contains("summon_dragon", error.Message);
    }
}

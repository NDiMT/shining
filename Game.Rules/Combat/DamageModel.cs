using HollowCrown.Rules.Core;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Rules.Combat;

/// <summary>What an attack would do, before it is committed.</summary>
/// <remarks>
/// Brief section 28 requires the expected damage to be previewed before the
/// player confirms, so the calculation has to be a pure function that the UI can
/// call speculatively. Resolving an attack uses the same function.
/// </remarks>
public readonly record struct DamageForecast
{
    public required int Damage { get; init; }
    public required bool Lethal { get; init; }
    public required Facing Facing { get; init; }
    public int TerrainDefense { get; init; }
    public int DirectionalArmour { get; init; }
    public int HeightBonus { get; init; }
    public int CriticalChance { get; init; }

    /// <summary>Damage if the blow crits. Brief section 27 wants crits to feel exciting.</summary>
    public int CriticalDamage => (int)Math.Round(Damage * CriticalMultiplier);

    public const double CriticalMultiplier = 1.5;
}

public readonly record struct AttackResult
{
    public required int Damage { get; init; }
    public required bool Critical { get; init; }
    public required bool Defeated { get; init; }
    public required Facing Facing { get; init; }
}

/// <summary>
/// The damage model. Brief section 28: keep it understandable.
/// </summary>
/// <remarks>
/// <para>
/// Physical: <c>Attack + Weapon + Height − (Defense + Armour + Terrain + Directional)</c>,
/// floored at <see cref="MinimumDamage"/>.
/// </para>
/// <para>
/// Magical: <c>Power + Magic + Weapon − Resistance</c>, floored the same way.
/// Terrain defence does not apply to magic; hiding in a forest should not stop
/// lightning.
/// </para>
/// <para>
/// The floor exists so an attack is never pointless, and it has teeth: measured
/// during prototyping, Rowan at defence 6 against a goblin's 7 attack power hit
/// the floor on every single blow, which made the prologue's first battle
/// threatless. The floor is a safety net, not a balance tool — when many attacks
/// land on it, the stats are wrong.
/// </para>
/// </remarks>
public static class DamageModel
{
    public const int MinimumDamage = 1;

    /// <summary>Flat bonus for attacking from higher ground. Brief section 25.</summary>
    public const int HeightAdvantage = 1;

    public static DamageForecast ForecastPhysical(
        Unit attacker, Unit target, BattleGrid grid)
    {
        Facing facing = target.Heading.FacingFrom(target.Position, attacker.Position);
        int terrainDefense = grid[target.Position].DefenseBonus;
        int directional = target.Armour.For(facing);
        int height = HeightBonus(grid, attacker.Position, target.Position);

        int raw = attacker.AttackPower + height
                  - (target.Base.Defense + target.ArmourDefense + terrainDefense + directional);

        int damage = Math.Max(MinimumDamage, raw);
        return new DamageForecast
        {
            Damage = damage,
            Lethal = damage >= target.Hp,
            Facing = facing,
            TerrainDefense = terrainDefense,
            DirectionalArmour = directional,
            HeightBonus = height,
            CriticalChance = attacker.Weapon?.Critical ?? 0,
        };
    }

    public static DamageForecast ForecastSkill(Unit attacker, Unit target, Skill skill)
    {
        int raw = skill.Power + attacker.MagicPower - target.Base.Resistance;
        int damage = Math.Max(MinimumDamage, raw);
        return new DamageForecast
        {
            Damage = damage,
            Lethal = damage >= target.Hp,
            Facing = Facing.Front,
            CriticalChance = 0,
        };
    }

    public static int HeightBonus(BattleGrid grid, Coord attacker, Coord target) =>
        grid[attacker].Height > grid[target].Height ? HeightAdvantage : 0;

    /// <summary>
    /// Apply a forecast to the target. The caller has already decided whether the
    /// battle's rules make a defeat lethal.
    /// </summary>
    public static AttackResult Apply(
        Unit target, DamageForecast forecast, Rng rng, bool nonLethal)
    {
        bool critical = rng.Chance(forecast.CriticalChance);
        int damage = critical ? forecast.CriticalDamage : forecast.Damage;

        target.Hp = Math.Max(0, target.Hp - damage);
        bool defeated = target.Hp == 0;
        if (defeated)
        {
            target.Defeated = true;
            target.Incapacitated = nonLethal;
        }

        return new AttackResult
        {
            Damage = damage,
            Critical = critical,
            Defeated = defeated,
            Facing = forecast.Facing,
        };
    }

    /// <summary>Whether <paramref name="target"/> is within reach of a weapon attack.</summary>
    public static bool InWeaponRange(Unit attacker, Unit target) =>
        attacker.Position.DistanceTo(target.Position) <= attacker.WeaponRange;

    public static bool InSkillRange(Unit attacker, Unit target, Skill skill) =>
        attacker.Position.DistanceTo(target.Position) <= skill.Range;
}

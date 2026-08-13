using HollowCrown.Rules.Tactical;

namespace HollowCrown.Rules.Combat;

public enum Side
{
    Player,
    Ally,
    Enemy,
    HostileToAll,
}

/// <summary>The stat block. Brief section 29; every stat here has a use in battle.</summary>
public readonly record struct Stats
{
    public int Hp { get; init; }
    public int Mp { get; init; }
    public int Attack { get; init; }
    public int Defense { get; init; }
    public int Magic { get; init; }
    public int Resistance { get; init; }
    public int Agility { get; init; }
    public int Movement { get; init; }
}

/// <summary>Extra defence by the side an attack lands on. The Wallstalker's armour.</summary>
public readonly record struct DirectionalArmour(int Front, int Flank, int Rear)
{
    public static readonly DirectionalArmour None = new(0, 0, 0);

    public int For(Facing facing) => facing switch
    {
        Facing.Front => Front,
        Facing.Flank => Flank,
        Facing.Rear => Rear,
        _ => 0,
    };
}

/// <summary>A weapon's contribution. Brief section 36.</summary>
public sealed record Weapon
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public int Attack { get; init; }
    public int Magic { get; init; }
    public int Range { get; init; } = 1;
    public int Critical { get; init; }
}

/// <summary>A skill. Brief section 37.</summary>
public sealed record Skill
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public int Cost { get; init; }
    public int Range { get; init; } = 1;
    public int Power { get; init; }
    public string Element { get; init; } = "none";
}

/// <summary>
/// A unit in a battle: its identity, its numbers and its current state.
/// </summary>
/// <remarks>
/// Mutable on purpose. A battle is a small, single-threaded simulation and the
/// presentation layer reads state after each resolved action; an immutable design
/// here would buy nothing and cost clarity.
/// </remarks>
public sealed class Unit
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required Side Side { get; set; }
    public required Stats Base { get; init; }
    public Weapon? Weapon { get; set; }
    public int ArmourDefense { get; set; }
    public DirectionalArmour Armour { get; init; } = DirectionalArmour.None;
    public IReadOnlyList<Skill> Skills { get; init; } = Array.Empty<Skill>();
    public string MovementType { get; init; } = "ground";
    public string AiBehaviour { get; init; } = "aggressive_melee";
    public bool IsCommander { get; init; }
    public bool IsBoss { get; init; }

    public Coord Position { get; set; }
    public Heading Heading { get; set; } = Heading.North;
    public int Hp { get; set; }
    public int Mp { get; set; }

    /// <summary>Defeated. Whether that means dead depends on the battle's rules.</summary>
    public bool Defeated { get; set; }

    /// <summary>Left the battlefield alive, like the fleeing goblin spearman.</summary>
    public bool Fled { get; set; }

    /// <summary>Reduced to 0 HP under a non-lethal rule, so recoverable afterwards.</summary>
    public bool Incapacitated { get; set; }

    public bool HasMoved { get; set; }
    public bool HasActed { get; set; }

    public bool Active => !Defeated && !Fled;

    public int MaxHp => Base.Hp;

    public int MaxMp => Base.Mp;

    public int AttackPower => Base.Attack + (Weapon?.Attack ?? 0);

    public int MagicPower => Base.Magic + (Weapon?.Magic ?? 0);

    public int WeaponRange => Weapon?.Range ?? 1;

    public int MovementPoints => Base.Movement;

    public static Unit Create(string id, string name, Side side, Stats stats)
    {
        var unit = new Unit { Id = id, Name = name, Side = side, Base = stats };
        unit.Hp = stats.Hp;
        unit.Mp = stats.Mp;
        return unit;
    }

    public bool IsHostileTo(Unit other)
    {
        if (Side == Side.HostileToAll || other.Side == Side.HostileToAll)
        {
            return !ReferenceEquals(this, other);
        }

        bool mine = Side is Side.Player or Side.Ally;
        bool theirs = other.Side is Side.Player or Side.Ally;
        return mine != theirs;
    }

    public Skill? FindSkill(string id) =>
        Skills.FirstOrDefault(s => string.Equals(s.Id, id, StringComparison.Ordinal));
}

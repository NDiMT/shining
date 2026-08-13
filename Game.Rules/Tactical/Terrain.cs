namespace HollowCrown.Rules.Tactical;

/// <summary>
/// One terrain type, loaded from Content/Data/terrain.json.
/// </summary>
/// <remarks>
/// Brief section 24 requires terrain to meaningfully affect battles and to be
/// data-driven, so nothing here is hard-coded: the engine knows that terrain has
/// a movement cost and a defence bonus, not that grass costs 1.
/// </remarks>
public sealed record TerrainType
{
    public required string Id { get; init; }
    public required char Symbol { get; init; }
    public required string Name { get; init; }

    /// <summary>Movement points to enter this tile.</summary>
    public int MoveCost { get; init; } = 1;

    /// <summary>Added to the occupant's defence.</summary>
    public int DefenseBonus { get; init; }

    /// <summary>Added to the occupant's evasion, as a percentage.</summary>
    public int EvasionBonus { get; init; }

    /// <summary>Elevation level. Higher ground gives ranged attackers an edge.</summary>
    public int Height { get; init; }

    /// <summary>Impassable except to the movement types in <see cref="PassableBy"/>.</summary>
    public bool Blocked { get; init; }

    public IReadOnlyList<string> PassableBy { get; init; } = Array.Empty<string>();

    public bool BlocksLineOfSight { get; init; }

    /// <summary>Escape objectives and fleeing units leave through these.</summary>
    public bool IsExit { get; init; }

    public bool IsPassableBy(string movementType) =>
        !Blocked || PassableBy.Contains(movementType);
}

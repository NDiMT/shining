namespace HollowCrown.Rules.Battle;

/// <summary>When a scripted battle event fires. Brief section 41.</summary>
public sealed record EventTrigger
{
    public required string Type { get; init; }
    public int Turn { get; init; }
    public string? Side { get; init; }
    public int Count { get; init; }
    public string Comparison { get; init; } = "eq";
    public string? UnitId { get; init; }
}

/// <summary>
/// One action inside a scripted event.
/// </summary>
/// <remarks>
/// Fields are deliberately a flat union rather than a subclass per action. The
/// set is small, it mirrors the JSON one-to-one, and keeping it flat means adding
/// an action to the data format is one case in the runner rather than a new type
/// plus a parser plus a visitor.
/// </remarks>
public sealed record EventAction
{
    public required string Type { get; init; }
    public string? Scene { get; init; }
    public string? Flag { get; init; }
    public string? Value { get; init; }
    public string? Terrain { get; init; }
    public IReadOnlyList<(int X, int Y)> Tiles { get; init; } = Array.Empty<(int, int)>();
    public string? UnitId { get; init; }
    public string? SpawnId { get; init; }
    public string? DefinitionId { get; init; }
    public (int X, int Y)? Position { get; init; }
    public string? SideName { get; init; }
    public IReadOnlyList<string> UnitIds { get; init; } = Array.Empty<string>();
    public string? Ai { get; init; }
    public string? Rule { get; init; }
    public ObjectiveSpec? Objective { get; init; }
    public string? Sound { get; init; }
    public double Intensity { get; init; }
}

public sealed record ObjectiveSpec
{
    public required string Type { get; init; }
    public string? Description { get; init; }
    public string? UnitId { get; init; }
    public int Turns { get; init; }
}

public sealed record ScriptedEvent
{
    public required string Id { get; init; }
    public required EventTrigger Trigger { get; init; }
    public required IReadOnlyList<EventAction> Actions { get; init; }

    /// <summary>Fire at most once. Most story beats want this.</summary>
    public bool Once { get; init; }

    /// <summary>Set by the runner once it has fired, for <see cref="Once"/>.</summary>
    public bool HasFired { get; set; }
}

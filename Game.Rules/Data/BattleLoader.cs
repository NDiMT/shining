using System.Text.Json;
using System.Text.Json.Serialization;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Rules.Data;

/// <summary>A battle, loaded from Content/Data/Battles.</summary>
public sealed record BattleDefinition
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required BattleGrid Grid { get; init; }
    public required IReadOnlyList<Unit> Units { get; init; }
    public required IReadOnlyList<ObjectiveDefinition> Objectives { get; init; }
    public IReadOnlyList<ObjectiveDefinition> DefeatConditions { get; init; } =
        Array.Empty<ObjectiveDefinition>();
    public IReadOnlyList<Battle.ScriptedEvent> Events { get; init; } =
        Array.Empty<Battle.ScriptedEvent>();
    public IReadOnlyList<PropPlacement> Props { get; init; } = Array.Empty<PropPlacement>();
    public IReadOnlyList<string> NonLethalSides { get; init; } = Array.Empty<string>();
    public string? Scene { get; init; }
    public string? Music { get; init; }
    public string? VictoryDialogue { get; init; }
    public int XpPerUnit { get; init; }
    public int Gold { get; init; }

    public bool IsNonLethalFor(Side side) =>
        NonLethalSides.Contains(side.ToString().ToLowerInvariant());
}

public sealed record ObjectiveDefinition
{
    public required string Type { get; init; }
    public string? Description { get; init; }
    public string? UnitId { get; init; }
    public int Turns { get; init; }
}

/// <summary>
/// One piece of set dressing placed on the battlefield: a cart, a tree, a fence.
/// </summary>
/// <remarks>
/// <para>
/// Props carry no rules. A prop that blocks movement blocks it because the tile
/// underneath it is <c>obstacle</c> or <c>fence</c> in the terrain grid, never
/// because a model is standing there — which is why the North Meadow cart sits on
/// the two 'o' tiles and the fence sections on 'f' tiles. Keeping the two
/// independent means a missing GLB changes how the battle looks and never how it
/// plays, and it is why the whole scene can be built before the art exists.
/// </para>
/// <para>
/// It is parsed here rather than in the presentation layer because it is content,
/// it is validated with the rest of the battle file, and a prop off the edge of
/// the grid should fail the same load that a unit off the edge fails.
/// </para>
/// </remarks>
public sealed record PropPlacement
{
    /// <summary>Catalog asset id, without a path or extension: <c>veg_tree_oak_a</c>.</summary>
    public required string AssetId { get; init; }

    public required Coord Position { get; init; }

    /// <summary>
    /// Degrees clockwise from north, seen from above — the sense a person editing a
    /// map thinks in. 0 leaves the model in its authored orientation.
    /// </summary>
    public double RotationDegrees { get; init; }

    /// <summary>Uniform scale. Non-uniform scale is not offered: it breaks the outline hull.</summary>
    public double Scale { get; init; } = 1.0;

    public string? Notes { get; init; }
}

/// <summary>
/// Reads a battle file into a playable <see cref="BattleDefinition"/>.
/// </summary>
/// <remarks>
/// Brief section 41 wants scripted events data-driven. Events are parsed as raw
/// records here and executed by the battle runner rather than being interpreted
/// at load: the loader's job is to fail loudly on anything malformed, not to
/// decide what an action means.
/// </remarks>
public static class BattleLoader
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    public static BattleDefinition Load(string path, ContentDatabase content)
    {
        BattleJson json;
        try
        {
            using FileStream stream = File.OpenRead(path);
            json = JsonSerializer.Deserialize<BattleJson>(stream, JsonOptions)
                   ?? throw new ContentException($"{path} deserialised to null");
        }
        catch (FileNotFoundException)
        {
            throw new ContentException($"missing battle file: {path}");
        }
        catch (JsonException exception)
        {
            throw new ContentException($"{path}: {exception.Message}", exception);
        }

        if (json.Terrain is null || json.Size is null)
        {
            throw new ContentException($"{path}: a battle needs both 'size' and 'terrain'");
        }

        if (json.Terrain.Count != json.Size.Height)
        {
            throw new ContentException(
                $"{path}: size.height is {json.Size.Height} but the terrain grid has " +
                $"{json.Terrain.Count} rows");
        }

        BattleGrid grid = BattleGrid.Parse(json.Terrain, content.Terrain);
        if (grid.Width != json.Size.Width)
        {
            throw new ContentException(
                $"{path}: size.width is {json.Size.Width} but terrain rows are {grid.Width} wide");
        }

        var units = new List<Unit>();
        AddUnits(units, json.PlayerUnits, Side.Player, content, grid, path);
        AddUnits(units, json.AllyUnits, Side.Ally, content, grid, path);
        AddUnits(units, json.EnemyUnits, Side.Enemy, content, grid, path);

        var objectives = (json.Objectives ?? new List<ObjectiveJson>())
            .Select(o => new ObjectiveDefinition
            {
                Type = o.Type ?? throw new ContentException($"{path}: objective without a type"),
                Description = o.Description,
                UnitId = o.Unit,
                Turns = o.Turns,
            })
            .ToList();

        return new BattleDefinition
        {
            Id = json.Id ?? Path.GetFileNameWithoutExtension(path),
            Name = json.Name ?? json.Id ?? "Battle",
            Grid = grid,
            Units = units,
            Objectives = objectives,
            DefeatConditions = (json.DefeatConditions ?? new List<ObjectiveJson>())
                .Select(c => new ObjectiveDefinition
                {
                    Type = c.Type ?? "unit_defeated",
                    Description = c.Description,
                    UnitId = c.Unit,
                })
                .ToList(),
            Events = ParseEvents(json.Events, path),
            Props = ParseProps(json.Props, grid, path),
            NonLethalSides = (IReadOnlyList<string>?)json.Rules?.NonLethalSides
                             ?? Array.Empty<string>(),
            Scene = json.Scene,
            Music = json.Music,
            VictoryDialogue = json.OnVictory?.Dialogue,
            XpPerUnit = json.Rewards?.XpPerUnit ?? 0,
            Gold = json.Rewards?.Gold ?? 0,
        };
    }

    /// <summary>
    /// Turn the JSON prop list into placements the scene builder can instance.
    /// </summary>
    /// <remarks>
    /// Strict about position, permissive about the asset: whether
    /// <c>veg_tree_oak_b</c> has been generated yet is not a content error, because
    /// most of the catalog has not been. A prop off the edge of the grid is,
    /// because it means the file was edited against the wrong axis.
    /// </remarks>
    private static IReadOnlyList<PropPlacement> ParseProps(
        List<PropJson>? source, BattleGrid grid, string path)
    {
        var result = new List<PropPlacement>();
        foreach (PropJson json in source ?? new List<PropJson>())
        {
            if (string.IsNullOrWhiteSpace(json.Asset))
            {
                throw new ContentException($"{path}: a prop names no asset");
            }

            if (json.Position is null || json.Position.Count != 2)
            {
                throw new ContentException($"{path}: prop '{json.Asset}' has no [x, y] position");
            }

            var at = new Coord(json.Position[0], json.Position[1]);
            if (!grid.Contains(at))
            {
                throw new ContentException(
                    $"{path}: prop '{json.Asset}' sits at {at}, outside the " +
                    $"{grid.Width}x{grid.Height} grid");
            }

            double scale = json.Scale ?? 1.0;
            if (scale <= 0.0)
            {
                throw new ContentException(
                    $"{path}: prop '{json.Asset}' has scale {scale}, which would make it invisible");
            }

            result.Add(new PropPlacement
            {
                AssetId = json.Asset!,
                Position = at,
                RotationDegrees = json.Rotation,
                Scale = scale,
                Notes = json.Notes,
            });
        }

        return result;
    }

    /// <summary>
    /// Turn the JSON event list into typed scripted events.
    /// </summary>
    /// <remarks>
    /// Deliberately permissive about *fields* and strict about *shape*: an action
    /// keeps whatever the JSON gave it, and whether the type is one the engine
    /// implements is decided when it runs, so the error names the action rather
    /// than a parse position.
    /// </remarks>
    private static IReadOnlyList<Battle.ScriptedEvent> ParseEvents(
        List<EventJson>? source, string path)
    {
        var result = new List<Battle.ScriptedEvent>();
        foreach (EventJson json in source ?? new List<EventJson>())
        {
            if (json.Trigger?.Type is null)
            {
                throw new ContentException(
                    $"{path}: event '{json.Id}' has no trigger type");
            }

            var actions = new List<Battle.EventAction>();
            foreach (ActionJson action in json.Actions ?? new List<ActionJson>())
            {
                if (action.Type is null)
                {
                    throw new ContentException($"{path}: event '{json.Id}' has a typeless action");
                }

                actions.Add(new Battle.EventAction
                {
                    Type = action.Type,
                    Scene = action.Scene,
                    Flag = action.Flag,
                    Value = action.Value is { } value ? CanonicalValue(value) : null,
                    Terrain = action.Terrain,
                    Tiles = (action.Tiles ?? new List<List<int>>())
                        .Where(t => t.Count == 2)
                        .Select(t => (t[0], t[1]))
                        .ToList(),
                    UnitId = action.Unit,
                    SpawnId = action.Id,
                    DefinitionId = action.Enemy ?? action.Character ?? action.Npc,
                    Position = action.Position is { Count: 2 }
                        ? (action.Position[0], action.Position[1])
                        : null,
                    SideName = action.Side ?? action.To,
                    UnitIds = (IReadOnlyList<string>?)action.Units ?? Array.Empty<string>(),
                    Ai = action.Ai,
                    Rule = action.Rule,
                    Sound = action.Id,
                    Intensity = action.Intensity,
                    Objective = action.Objective is null ? null : new Battle.ObjectiveSpec
                    {
                        Type = action.Objective.Type
                               ?? throw new ContentException(
                                   $"{path}: event '{json.Id}' sets an objective with no type"),
                        Description = action.Objective.Description,
                        UnitId = action.Objective.Unit,
                        Turns = action.Objective.Turns,
                    },
                });
            }

            result.Add(new Battle.ScriptedEvent
            {
                Id = json.Id ?? "unnamed",
                Once = json.Once,
                Trigger = new Battle.EventTrigger
                {
                    Type = json.Trigger.Type,
                    Turn = json.Trigger.Turn,
                    Side = json.Trigger.Side,
                    Count = json.Trigger.Count,
                    Comparison = json.Trigger.Comparison ?? "eq",
                    UnitId = json.Trigger.Unit,
                },
                Actions = actions,
            });
        }

        return result;
    }

    /// <summary>
    /// Render a JSON value the way the rest of the project writes it.
    /// </summary>
    /// <remarks>
    /// <c>JsonElement.ToString()</c> renders a boolean as "True", which does not
    /// match the lowercase literals in flags.json's <c>allowed</c> lists and would
    /// have written "True" into save files. Worth a helper rather than a cast.
    /// </remarks>
    private static string CanonicalValue(System.Text.Json.JsonElement value) => value.ValueKind switch
    {
        System.Text.Json.JsonValueKind.True => "true",
        System.Text.Json.JsonValueKind.False => "false",
        System.Text.Json.JsonValueKind.Null => string.Empty,
        System.Text.Json.JsonValueKind.String => value.GetString() ?? string.Empty,
        _ => value.GetRawText(),
    };

    private static void AddUnits(
        List<Unit> into,
        List<BattleUnitJson>? source,
        Side side,
        ContentDatabase content,
        BattleGrid grid,
        string path)
    {
        foreach (BattleUnitJson entry in source ?? new List<BattleUnitJson>())
        {
            string? definitionId = entry.Character ?? entry.Enemy ?? entry.Npc;
            if (definitionId is null)
            {
                throw new ContentException(
                    $"{path}: a {side} unit names no character, enemy or npc");
            }

            if (entry.Position is null || entry.Position.Count != 2)
            {
                throw new ContentException($"{path}: '{definitionId}' has no [x, y] position");
            }

            var at = new Coord(entry.Position[0], entry.Position[1]);
            if (!grid.Contains(at))
            {
                throw new ContentException(
                    $"{path}: '{definitionId}' starts at {at}, outside the " +
                    $"{grid.Width}x{grid.Height} grid");
            }

            TerrainType terrain = grid[at];
            if (terrain.Blocked)
            {
                throw new ContentException(
                    $"{path}: '{definitionId}' starts at {at}, which is {terrain.Name} " +
                    "and impassable");
            }

            if (into.Any(u => u.Position == at))
            {
                throw new ContentException($"{path}: two units both start at {at}");
            }

            Unit unit = content.Spawn(definitionId, side, at, entry.Id ?? definitionId);
            if (entry.HpPercent is > 0 and < 100)
            {
                unit.Hp = Math.Max(1, unit.MaxHp * entry.HpPercent.Value / 100);
            }

            into.Add(unit);
        }
    }
}

internal sealed class BattleJson
{
    public string? Id { get; set; }
    public string? Name { get; set; }
    public string? Scene { get; set; }
    public string? Music { get; set; }
    public SizeJson? Size { get; set; }
    public List<string>? Terrain { get; set; }
    public List<ObjectiveJson>? Objectives { get; set; }
    [JsonPropertyName("player_units")] public List<BattleUnitJson>? PlayerUnits { get; set; }
    [JsonPropertyName("ally_units")] public List<BattleUnitJson>? AllyUnits { get; set; }
    [JsonPropertyName("enemy_units")] public List<BattleUnitJson>? EnemyUnits { get; set; }
    public RulesJson? Rules { get; set; }
    public RewardsJson? Rewards { get; set; }
    [JsonPropertyName("on_victory")] public OnVictoryJson? OnVictory { get; set; }
    [JsonPropertyName("defeat_conditions")] public List<ObjectiveJson>? DefeatConditions { get; set; }
    public List<EventJson>? Events { get; set; }
    public List<PropJson>? Props { get; set; }
}

internal sealed class PropJson
{
    public string? Asset { get; set; }
    public List<int>? Position { get; set; }
    public double Rotation { get; set; }

    /// <summary>Nullable so an absent scale defaults to 1 rather than to 0.</summary>
    public double? Scale { get; set; }
    public string? Notes { get; set; }
}

internal sealed class EventJson
{
    public string? Id { get; set; }
    public bool Once { get; set; }
    public TriggerJson? Trigger { get; set; }
    public List<ActionJson>? Actions { get; set; }
}

internal sealed class TriggerJson
{
    public string? Type { get; set; }
    public int Turn { get; set; }
    public string? Side { get; set; }
    public int Count { get; set; }
    public string? Comparison { get; set; }
    public string? Unit { get; set; }
}

internal sealed class ActionJson
{
    public string? Type { get; set; }
    public string? Scene { get; set; }
    public string? Flag { get; set; }
    public System.Text.Json.JsonElement? Value { get; set; }
    public string? Terrain { get; set; }
    public List<List<int>>? Tiles { get; set; }
    public string? Unit { get; set; }
    public List<string>? Units { get; set; }
    public string? Id { get; set; }
    public string? Enemy { get; set; }
    public string? Character { get; set; }
    public string? Npc { get; set; }
    public List<int>? Position { get; set; }
    public string? Side { get; set; }
    public string? To { get; set; }
    public string? Ai { get; set; }
    public string? Rule { get; set; }
    public double Intensity { get; set; }
    public ObjectiveJson? Objective { get; set; }
}

internal sealed class SizeJson
{
    public int Width { get; set; }
    public int Height { get; set; }
}

internal sealed class ObjectiveJson
{
    public string? Id { get; set; }
    public string? Type { get; set; }
    public string? Description { get; set; }
    public string? Unit { get; set; }
    public int Turns { get; set; }
}

internal sealed class BattleUnitJson
{
    public string? Id { get; set; }
    public string? Character { get; set; }
    public string? Enemy { get; set; }
    public string? Npc { get; set; }
    public List<int>? Position { get; set; }
    public string? Ai { get; set; }
    [JsonPropertyName("hp_percent")] public int? HpPercent { get; set; }
    [JsonPropertyName("is_commander")] public bool IsCommander { get; set; }
}

internal sealed class RulesJson
{
    [JsonPropertyName("non_lethal_sides")] public List<string>? NonLethalSides { get; set; }
}

internal sealed class RewardsJson
{
    [JsonPropertyName("xp_per_unit")] public int XpPerUnit { get; set; }
    public int Gold { get; set; }
}

internal sealed class OnVictoryJson
{
    public string? Dialogue { get; set; }
}

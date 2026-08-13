using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// Puts the battle's units on their deployment cells.
/// </summary>
/// <remarks>
/// Deployment comes from the battle file through <c>BattleLoader</c>, which has
/// already refused to load if a unit starts off the grid, on an impassable tile,
/// or on top of another unit. Nothing here re-checks any of that; if it did, the
/// two checks would drift and the useful error would be the one that did not run.
/// </remarks>
public sealed class UnitBuilder
{
    private readonly GridSpace _space;
    private readonly ModelLibrary _models;
    private readonly ToonLook _look;

    public UnitBuilder(GridSpace space, ModelLibrary models, ToonLook look)
    {
        _space = space;
        _models = models;
        _look = look;
    }

    /// <summary>How many units got a real mesh rather than a placeholder.</summary>
    public int Modelled { get; private set; }

    public int Placeholders => PlaceholderIds.Count;

    /// <summary>
    /// Units standing in as a placeholder, so the HUD can say so per unit.
    /// </summary>
    /// <remarks>
    /// Tracked here rather than re-derived from the model path later: whether a
    /// GLB loaded is something only the loader knows, and a second guess made from
    /// the filename would eventually disagree with it.
    /// </remarks>
    public HashSet<string> PlaceholderIds { get; } = new(StringComparer.Ordinal);

    public Dictionary<string, UnitVisual> Build(IReadOnlyList<Unit> units, Node3D into)
    {
        var visuals = new Dictionary<string, UnitVisual>(StringComparer.Ordinal);

        foreach (Unit unit in units)
        {
            string definitionId = DefinitionIdOf(unit);
            Node3D? model = unit.ModelPath is null ? null : _models.Instance(unit.ModelPath);
            float height;

            if (model is null)
            {
                model = PlaceholderUnit.Build(unit, definitionId, _look);
                height = PlaceholderUnit.HeightFor(unit.ClassId);
                PlaceholderIds.Add(unit.Id);
            }
            else
            {
                SceneryTrim.Measure(model, definitionId, _space.TileSize);

                // A generated character is recoloured per role rather than
                // regenerated — the provenance record for npc_guard_greenvale plans
                // for exactly that reuse across the guard squad, battle 02's enemies
                // and their later selves as allies.
                ToonMaterialiser.Apply(model, _look, ToonLook.CharacterHue(unit.Id, definitionId));
                height = PlaceholderUnit.HeightFor(unit.ClassId);
                Modelled++;
            }

            var visual = new UnitVisual();
            into.AddChild(visual);
            visual.Initialise(unit, model, _space, height);

            // The two lines face each other at deployment: the player's party is on
            // the road in the south, the goblins seven rows north of them.
            unit.Heading = unit.Side == Side.Enemy ? Heading.South : Heading.North;
            visual.FaceHeading(unit.Heading);

            visuals[unit.Id] = visual;
        }

        return visuals;
    }

    /// <summary>
    /// The content definition a unit was spawned from, recovered from its model
    /// path.
    /// </summary>
    /// <remarks>
    /// Battle files give enemies instance ids — <c>raider_1</c>, <c>spearman_2</c> —
    /// so the unit id cannot be used to look up a faction colour. The model path is
    /// the definition's own, and it survives on the unit for this reason.
    /// </remarks>
    private static string DefinitionIdOf(Unit unit)
    {
        if (unit.ModelPath is null)
        {
            return unit.Id;
        }

        string stem = Path.GetFileNameWithoutExtension(unit.ModelPath);
        foreach (string prefix in new[] { "enemy_", "hero_", "npc_", "boss_" })
        {
            if (stem.StartsWith(prefix, StringComparison.Ordinal))
            {
                return stem[prefix.Length..];
            }
        }

        return stem;
    }
}

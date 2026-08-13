using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Data;

namespace HollowCrown.Presentation.Battle;

/// <summary>How the set dressing went in.</summary>
public readonly record struct PropReport(int Placed, int Skipped, int SlabsRemoved);

/// <summary>
/// Instances the battle file's props onto the field.
/// </summary>
/// <remarks>
/// Props are decoration only — what blocks a unit is the terrain symbol under the
/// prop, not the model (see <see cref="PropPlacement"/>). That is what makes it
/// safe to skip a missing GLB: the cart at [5,8] is still impassable with no cart
/// there, because the tile is 'o'. The battle plays identically whether nine props
/// or none are on screen, which is the property that lets the whole scene be built
/// before the art exists.
/// </remarks>
public sealed class PropBuilder
{
    private readonly GridSpace _space;
    private readonly ModelLibrary _models;
    private readonly ToonLook _look;

    public PropBuilder(GridSpace space, ModelLibrary models, ToonLook look)
    {
        _space = space;
        _models = models;
        _look = look;
    }

    public PropReport Build(IReadOnlyList<PropPlacement> props, Node3D into)
    {
        int placed = 0;
        int skipped = 0;
        int slabs = 0;

        foreach (PropPlacement prop in props)
        {
            Node3D? model = _models.Instance(prop.AssetId);
            if (model is null)
            {
                // ModelLibrary has already warned, once per asset rather than once
                // per placement — four missing fence sections are one problem.
                skipped++;
                continue;
            }

            // Measured before it is scaled or added to the tree, so a 7.79 m ground
            // slab is never on screen even for a frame.
            TrimReport trim = SceneryTrim.Measure(model, prop.AssetId, _space.TileSize);
            slabs += trim.SlabsRemoved;

            ToonMaterialiser.Apply(model, _look);

            var anchor = new Node3D
            {
                Name = $"Prop_{prop.AssetId}_{prop.Position.X}_{prop.Position.Y}",
                Position = _space.Centre(prop.Position),
                Scale = Vector3.One * (float)prop.Scale,
            };

            // PropPlacement.RotationDegrees is clockwise from north seen from above,
            // the sense a person editing a map thinks in. A positive rotation about
            // Godot's +Y axis turns east towards north, which is anticlockwise on
            // that map, hence the negation.
            anchor.RotateY(-Mathf.DegToRad((float)prop.RotationDegrees));

            anchor.AddChild(model);
            into.AddChild(anchor);
            placed++;
        }

        return new PropReport(placed, skipped, slabs);
    }
}

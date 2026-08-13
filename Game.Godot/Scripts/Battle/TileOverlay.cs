using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// One layer of coloured tiles: movement range, attack range, threat range.
/// </summary>
/// <remarks>
/// A <see cref="MultiMesh"/> rather than a node per tile. The movement overlay
/// changes every time the selection or the cursor moves, and rebuilding forty
/// nodes per hover is how a tactical UI acquires a stutter that nobody can find
/// later. The instance buffer is allocated once at the size of the grid and only
/// <see cref="MultiMesh.VisibleInstanceCount"/> changes afterwards.
/// </remarks>
public sealed partial class TileOverlay : MultiMeshInstance3D
{
    private GridSpace _space = null!;
    private float _lift;

    public void Initialise(GridSpace space, BattleGrid grid, Color colour, float alpha, float lift)
    {
        _space = space;
        _lift = lift;

        var mesh = new PlaneMesh
        {
            // Inset from the tile so the terrain colour still shows around the
            // highlight. A highlight that covers the tile hides what the tile is,
            // and terrain is half the tactical information on screen.
            Size = new Vector2(space.TileSize * 0.82f, space.TileSize * 0.82f),
        };

        Multimesh = new MultiMesh
        {
            TransformFormat = MultiMesh.TransformFormatEnum.Transform3D,
            Mesh = mesh,
            InstanceCount = grid.Width * grid.Height,
            VisibleInstanceCount = 0,
        };

        MaterialOverride = ToonLook.Overlay(colour, alpha);
        // Overlays are UI lying on the ground: they must not receive the cast
        // shadow of the unit standing on them, or the highlight changes colour
        // under the thing it is highlighting.
        CastShadow = ShadowCastingSetting.Off;
    }

    public void Show(IEnumerable<Coord> tiles)
    {
        int index = 0;
        foreach (Coord at in tiles)
        {
            if (index >= Multimesh.InstanceCount)
            {
                break;
            }

            Multimesh.SetInstanceTransform(
                index,
                new Transform3D(Basis.Identity, _space.Centre(at, _lift)));
            index++;
        }

        Multimesh.VisibleInstanceCount = index;
    }

    public void Clear() => Multimesh.VisibleInstanceCount = 0;
}

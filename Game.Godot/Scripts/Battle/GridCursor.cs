using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// The tile the player is pointing at.
/// </summary>
/// <remarks>
/// A square frame rather than a filled quad, so it can sit on top of a movement
/// or attack highlight without hiding which one is underneath. It slides between
/// tiles instead of snapping: the movement is what tells the eye which direction
/// the cursor came from when it jumps three tiles on a mouse move.
/// </remarks>
public sealed partial class GridCursor : Node3D
{
    private const float Thickness = 0.08f;
    private const float Lift = 0.06f;

    private GridSpace _space = null!;
    private Vector3 _target;

    public Coord Cell { get; private set; }

    public void Initialise(GridSpace space, Coord start)
    {
        _space = space;
        Cell = start;
        _target = space.Centre(start, Lift);
        Position = _target;

        float side = space.TileSize * 0.94f;
        var bar = new BoxMesh { Size = new Vector3(side, 0.02f, Thickness) };
        StandardMaterial3D material = ToonLook.Overlay(ToonLook.Bone, 0.95f);

        // Four edges of one square. Reusing a single mesh for all four keeps this
        // to one draw batch and one material.
        for (int edge = 0; edge < 4; edge++)
        {
            float offset = side * 0.5f;
            Vector3 position = edge switch
            {
                0 => new Vector3(0f, 0f, -offset),
                1 => new Vector3(0f, 0f, offset),
                2 => new Vector3(-offset, 0f, 0f),
                _ => new Vector3(offset, 0f, 0f),
            };

            var piece = new MeshInstance3D
            {
                Name = $"Edge{edge}",
                Mesh = bar,
                Position = position,
                MaterialOverride = material,
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            };

            if (edge >= 2)
            {
                piece.RotateY(Mathf.Pi * 0.5f);
            }

            AddChild(piece);
        }
    }

    public void MoveTo(Coord cell)
    {
        Cell = cell;
        _target = _space.Centre(cell, Lift);
    }

    public override void _Process(double delta)
    {
        Position = Position.Lerp(_target, Mathf.Min(1f, 22f * (float)delta));
    }
}

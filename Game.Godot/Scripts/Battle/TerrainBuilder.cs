using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// Builds the battlefield out of the terrain grid.
/// </summary>
/// <remarks>
/// Nothing here is hand placed. The tile at [5,11] is a hill because
/// terrain.json says 'h' has height 1 and the battle file has an 'h' there, and
/// changing either file changes the scene with no engine work — brief section 14's
/// requirement, and the reason the grid is built rather than modelled.
/// </remarks>
public sealed class TerrainBuilder
{
    /// <summary>Gap between neighbouring tiles, in metres.</summary>
    /// <remarks>
    /// 6 cm on a 2 m tile. The dark ground plane shows through the gaps, which
    /// draws the grid for free — no overlay, no lines, no extra draw call. It also
    /// keeps ANIME_DIRECTION rule 2 off the terrain: an inverted hull on 168 tiles
    /// would outline every tile individually and turn the field into graph paper,
    /// which is the "every crease becomes a line" failure the spec warns about.
    /// </remarks>
    private const float Gutter = 0.06f;

    /// <summary>How far a tile block extends below its top surface.</summary>
    private const float Skirt = 0.6f;

    private readonly GridSpace _space;
    private readonly ToonLook _look;

    public TerrainBuilder(GridSpace space, ToonLook look)
    {
        _space = space;
        _look = look;
    }

    public void Build(BattleGrid grid, Node3D into)
    {
        // One BoxMesh per height level, shared by every tile at that level: the
        // mesh differs only in how far the block drops to the base plane.
        var meshes = new Dictionary<int, BoxMesh>();

        foreach (Coord at in grid.AllCoords())
        {
            TerrainType terrain = grid[at];
            float top = terrain.Height * _space.HeightStep;

            if (!meshes.TryGetValue(terrain.Height, out BoxMesh? mesh))
            {
                mesh = new BoxMesh
                {
                    Size = new Vector3(
                        _space.TileSize - Gutter,
                        Skirt + top,
                        _space.TileSize - Gutter),
                };
                meshes[terrain.Height] = mesh;
            }

            var tile = new MeshInstance3D
            {
                Name = $"Tile_{at.X}_{at.Y}_{terrain.Id}",
                Mesh = mesh,
                // Box origin is its centre, so the block hangs from its top face
                // down to the base plane at -Skirt.
                Position = _space.Centre(at) - new Vector3(0f, (Skirt + top) * 0.5f, 0f),
                // ground: true takes ToonSettings.GroundBands rather than the
                // spec's default three — see that field for why the ground wants
                // one more band than a character does.
                MaterialOverride = _look.Flat(ToonLook.TerrainColour(terrain.Id),
                                              outlined: false, ground: true),
            };

            into.AddChild(tile);
        }

        into.AddChild(BuildBasePlane());
    }

    /// <summary>
    /// The dark plane the tiles sit on, seen through the gutters as grid lines.
    /// </summary>
    private MeshInstance3D BuildBasePlane()
    {
        return new MeshInstance3D
        {
            Name = "BasePlane",
            Mesh = new PlaneMesh
            {
                // A tile wider than the field on each side so the edge of the world
                // is a dark border rather than a hard cut to the background colour.
                Size = new Vector2(
                    _space.FieldWidth + (_space.TileSize * 2f),
                    _space.FieldDepth + (_space.TileSize * 2f)),
            },
            Position = new Vector3(0f, -Skirt, 0f),
            MaterialOverride = _look.Flat(ToonLook.DarkLine, outlined: false),
        };
    }
}

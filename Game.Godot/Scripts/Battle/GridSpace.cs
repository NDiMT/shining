using Godot;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// The bridge between grid coordinates and Godot's world space.
/// </summary>
/// <remarks>
/// <para>
/// All the arithmetic is in <see cref="GridLayout"/>, in Game.Rules, where it is
/// unit tested — <c>GridLayoutTests</c> pins the axis mapping against the real
/// North Meadow file. This class only puts the results into
/// <see cref="Vector3"/> and adds the one thing that genuinely needs the engine:
/// turning a mouse ray into a tile.
/// </para>
/// <para>
/// <b>The mapping, restated because it is the easiest thing in the project to get
/// backwards.</b> The battle file's terrain array is written north row first, so
/// array row 0 is <c>y = height - 1</c>; <c>BattleGrid.Parse</c> performs that
/// flip once and nothing else repeats it. From there:
/// </para>
/// <code>
///   grid +X  (west to east)   ->  world +X
///   grid +Y  (south to north)  ->  world -Z
///   terrain height level       ->  world +Y, 0.5 m per level
/// </code>
/// <para>
/// So the camera's default seat is to the <i>south</i> of the field looking north,
/// and the player's deployment row on the North Meadow road is nearest the
/// viewer. Mirror this and the battlefield still looks entirely plausible, which
/// is what makes it worth stating three times.
/// </para>
/// </remarks>
public sealed class GridSpace
{
    private readonly BattleGrid _grid;

    public GridSpace(BattleGrid grid, float tileSize = GridLayout.DefaultTileSize)
    {
        _grid = grid;
        Layout = new GridLayout(grid, tileSize);
    }

    public GridLayout Layout { get; }

    public float TileSize => Layout.TileSize;

    public float HeightStep => Layout.HeightStep;

    /// <summary>Centre of a tile's top surface.</summary>
    public Vector3 Centre(Coord at) => ToVector(Layout.Centre(at));

    /// <summary>Centre of a tile's top surface, raised by <paramref name="lift"/> metres.</summary>
    public Vector3 Centre(Coord at, float lift)
    {
        Vector3 centre = Centre(at);
        centre.Y += lift;
        return centre;
    }

    /// <summary>The middle of the whole field, at ground level. The camera's pivot.</summary>
    public Vector3 FieldCentre => Vector3.Zero;

    public float FieldWidth => Layout.FieldWidth;

    public float FieldDepth => Layout.FieldDepth;

    /// <summary>Terrain height of a tile in metres.</summary>
    public float HeightOf(Coord at) => _grid[at].Height * HeightStep;

    private static Vector3 ToVector(WorldPoint point) => new(point.X, point.Y, point.Z);

    /// <summary>
    /// Which tile a camera ray lands on, or null if it misses the field.
    /// </summary>
    /// <remarks>
    /// A plane intersection rather than a physics raycast, because a battlefield
    /// of static tiles does not need 168 collision shapes to answer a question
    /// that is one division.
    ///
    /// It resolves twice. The first hit is against the ground plane at y = 0,
    /// which is right for every tile except a hill; the second re-intersects at
    /// that tile's own height. At the camera's 48° pitch a 0.5 m hill offsets the
    /// hit by about 0.45 m — nearly a quarter of a 2 m tile — so without the second
    /// pass the tile below a hill is picked instead of the hill itself, and only
    /// on hills, which is a maddening bug to reproduce.
    /// </remarks>
    public Coord? Pick(Camera3D camera, Vector2 screenPosition)
    {
        Vector3 from = camera.ProjectRayOrigin(screenPosition);
        Vector3 direction = camera.ProjectRayNormal(screenPosition);

        Coord? first = HitAtHeight(from, direction, 0f);
        if (first is null)
        {
            return null;
        }

        float height = HeightOf(first.Value);
        if (height == 0f)
        {
            return first;
        }

        return HitAtHeight(from, direction, height) ?? first;
    }

    private Coord? HitAtHeight(Vector3 from, Vector3 direction, float height)
    {
        var plane = new Plane(Vector3.Up, height);
        Vector3? hit = plane.IntersectsRay(from, direction);
        return hit is null ? null : Layout.Resolve(hit.Value.X, hit.Value.Z);
    }

    /// <summary>
    /// The nearest tile to a ray, clamped onto the field, for a cursor that should
    /// stop at the edge rather than disappear off it.
    /// </summary>
    public Coord PickClamped(Camera3D camera, Vector2 screenPosition, Coord fallback)
    {
        Vector3 from = camera.ProjectRayOrigin(screenPosition);
        Vector3 direction = camera.ProjectRayNormal(screenPosition);
        Vector3? hit = new Plane(Vector3.Up, 0f).IntersectsRay(from, direction);
        return hit is null ? fallback : Layout.Clamp(hit.Value.X, hit.Value.Z);
    }
}

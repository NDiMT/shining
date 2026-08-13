namespace HollowCrown.Rules.Tactical;

/// <summary>A point in the presentation layer's world space, in metres.</summary>
/// <remarks>
/// Deliberately not a vector type with arithmetic on it. This is a handoff value:
/// the presentation layer converts it to whatever the engine's vector type is on
/// arrival and does its maths there.
/// </remarks>
public readonly record struct WorldPoint(float X, float Y, float Z);

/// <summary>
/// Where a grid coordinate sits in world space, in metres.
/// </summary>
/// <remarks>
/// <para>
/// This lives in the rules layer for two reasons, neither of them presentation
/// creep. First, ANIME_DIRECTION.md rule 4 fixes the relationship in the other
/// direction — "heights do not change, a hero is still 1.7m, because the tactical
/// grid, the movement costs and the camera all depend on it" — so the metre size
/// of a tile is a rule about the game, not a rendering preference. Second, it is
/// the one piece of the scene-building path that can be unit tested without an
/// engine, and it is the piece most likely to be silently wrong: a mirrored map
/// still looks like a plausible battlefield.
/// </para>
/// <para>
/// The mapping, which is the whole point of the class:
/// </para>
/// <list type="bullet">
///   <item>grid X runs west to east, and maps to world <b>+X</b>.</item>
///   <item>grid Y runs south to north, and maps to world <b>−Z</b>, because the
///   engine this feeds (Godot 4) is Y-up with −Z pointing away from a camera
///   sitting at the default orientation. A camera placed south of the field
///   therefore looks north, which is how the battle files are drawn and read.</item>
///   <item>terrain height level maps to world <b>+Y</b>, one
///   <see cref="HeightStep"/> per level.</item>
/// </list>
/// <para>
/// The field is centred on the world origin so the camera can orbit about
/// <c>(0, 0, 0)</c> without carrying an offset everywhere.
/// </para>
/// </remarks>
public sealed class GridLayout
{
    /// <summary>Metres across one tile.</summary>
    /// <remarks>
    /// 2 m. A hero is 1.7 m (ANIME_DIRECTION rule 4), so a 2 m tile leaves a unit
    /// standing clear of its neighbours' shoulders at the tactical camera's angle,
    /// which is what keeps twelve units on screen readable per STYLE_GUIDE section 3.
    /// </remarks>
    public const float DefaultTileSize = 2.0f;

    /// <summary>Metres per terrain height level.</summary>
    /// <remarks>
    /// 0.5 m. terrain.json gives hill height 1 and everything else 0, so this is
    /// the only rise on the North Meadow field. Half a metre is visible as a step
    /// under a 45° camera without a unit on the hill hiding the unit behind it.
    /// </remarks>
    public const float DefaultHeightStep = 0.5f;

    private readonly BattleGrid _grid;

    public GridLayout(BattleGrid grid, float tileSize = DefaultTileSize,
                      float heightStep = DefaultHeightStep)
    {
        if (tileSize <= 0f)
        {
            throw new ArgumentOutOfRangeException(nameof(tileSize), tileSize, "must be positive");
        }

        _grid = grid;
        TileSize = tileSize;
        HeightStep = heightStep;
    }

    public float TileSize { get; }

    public float HeightStep { get; }

    public int Width => _grid.Width;

    public int Height => _grid.Height;

    /// <summary>West-to-east extent of the whole field, in metres.</summary>
    public float FieldWidth => _grid.Width * TileSize;

    /// <summary>South-to-north extent of the whole field, in metres.</summary>
    public float FieldDepth => _grid.Height * TileSize;

    /// <summary>
    /// The centre of a tile's top surface, using the tile's own terrain height.
    /// </summary>
    public WorldPoint Centre(Coord at) => Centre(at, _grid[at].Height);

    /// <summary>
    /// The centre of a tile at an explicit height level, for tiles being animated
    /// or for a cursor that hovers above the surface.
    /// </summary>
    public WorldPoint Centre(Coord at, int heightLevel) => new(
        (at.X + 0.5f - (_grid.Width * 0.5f)) * TileSize,
        heightLevel * HeightStep,
        -(at.Y + 0.5f - (_grid.Height * 0.5f)) * TileSize);

    /// <summary>
    /// Which tile a world-space point on the ground plane falls in, or null if it
    /// falls off the field.
    /// </summary>
    /// <remarks>
    /// The inverse of <see cref="Centre(Coord)"/>, and the mouse-picking path: the
    /// presentation layer intersects the cursor ray with the ground plane and asks
    /// this what was clicked. Y is ignored because a hill tile is picked by where
    /// it sits on the field, not by how tall it is.
    /// </remarks>
    public Coord? Resolve(float worldX, float worldZ)
    {
        int x = (int)MathF.Floor((worldX / TileSize) + (_grid.Width * 0.5f));
        int y = (int)MathF.Floor((-worldZ / TileSize) + (_grid.Height * 0.5f));
        var at = new Coord(x, y);
        return _grid.Contains(at) ? at : null;
    }

    /// <summary>
    /// The nearest tile to a world-space point, clamped onto the field.
    /// </summary>
    /// <remarks>
    /// Used by the grid cursor, which should stop at the edge rather than vanish
    /// when the pointer leaves the battlefield.
    /// </remarks>
    public Coord Clamp(float worldX, float worldZ)
    {
        int x = (int)MathF.Floor((worldX / TileSize) + (_grid.Width * 0.5f));
        int y = (int)MathF.Floor((-worldZ / TileSize) + (_grid.Height * 0.5f));
        return new Coord(
            Math.Clamp(x, 0, _grid.Width - 1),
            Math.Clamp(y, 0, _grid.Height - 1));
    }
}

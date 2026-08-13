namespace HollowCrown.Rules.Tactical;

/// <summary>
/// The battlefield: terrain per tile, mutable so scripted events can change it.
/// </summary>
/// <remarks>
/// Battle 02's turn-3 event converts Crownwall tiles to rubble so the Wallstalker
/// can come through, so terrain has to be writable at runtime rather than baked
/// at load. Brief section 41 wants scripted events data-driven, and this is the
/// surface they act on.
/// </remarks>
public sealed class BattleGrid
{
    private readonly string[] _terrainIds;
    private readonly IReadOnlyDictionary<string, TerrainType> _types;

    private BattleGrid(int width, int height, string[] terrainIds,
                       IReadOnlyDictionary<string, TerrainType> types)
    {
        Width = width;
        Height = height;
        _terrainIds = terrainIds;
        _types = types;
    }

    public int Width { get; }

    public int Height { get; }

    /// <summary>
    /// Build a grid from a battle file's terrain rows.
    /// </summary>
    /// <param name="rows">
    /// Terrain rows as written in JSON: <b>north row first</b>, so
    /// <c>rows[0]</c> is <c>Y = Height - 1</c>. This method is the only place
    /// that flip happens.
    /// </param>
    /// <param name="types">Terrain types by symbol.</param>
    public static BattleGrid Parse(IReadOnlyList<string> rows, IReadOnlyList<TerrainType> types)
    {
        if (rows.Count == 0)
        {
            throw new ArgumentException("a battle grid needs at least one row", nameof(rows));
        }

        int height = rows.Count;
        int width = rows[0].Length;
        for (int i = 0; i < rows.Count; i++)
        {
            if (rows[i].Length != width)
            {
                throw new ArgumentException(
                    $"terrain row {i} is {rows[i].Length} characters, expected {width}", nameof(rows));
            }
        }

        var bySymbol = new Dictionary<char, TerrainType>();
        foreach (TerrainType type in types)
        {
            bySymbol[type.Symbol] = type;
        }

        var byId = new Dictionary<string, TerrainType>(StringComparer.Ordinal);
        foreach (TerrainType type in types)
        {
            byId[type.Id] = type;
        }

        var ids = new string[width * height];
        for (int row = 0; row < height; row++)
        {
            int y = height - 1 - row;
            for (int x = 0; x < width; x++)
            {
                char symbol = rows[row][x];
                if (!bySymbol.TryGetValue(symbol, out TerrainType? type))
                {
                    throw new ArgumentException(
                        $"terrain symbol '{symbol}' at row {row} column {x} is not defined in terrain.json",
                        nameof(rows));
                }

                ids[(y * width) + x] = type.Id;
            }
        }

        return new BattleGrid(width, height, ids, byId);
    }

    public bool Contains(Coord at) =>
        at.X >= 0 && at.Y >= 0 && at.X < Width && at.Y < Height;

    public TerrainType this[Coord at]
    {
        get
        {
            if (!Contains(at))
            {
                throw new ArgumentOutOfRangeException(
                    nameof(at), at, $"outside the {Width}x{Height} grid");
            }

            return _types[_terrainIds[(at.Y * Width) + at.X]];
        }
    }

    public TerrainType? TryGet(Coord at) => Contains(at) ? this[at] : null;

    /// <summary>Replace a tile's terrain. Used by scripted battle events.</summary>
    public void SetTerrain(Coord at, string terrainId)
    {
        if (!Contains(at))
        {
            throw new ArgumentOutOfRangeException(nameof(at), at, "outside the grid");
        }

        if (!_types.ContainsKey(terrainId))
        {
            throw new ArgumentException($"unknown terrain '{terrainId}'", nameof(terrainId));
        }

        _terrainIds[(at.Y * Width) + at.X] = terrainId;
    }

    public IEnumerable<Coord> AllCoords()
    {
        for (int y = 0; y < Height; y++)
        {
            for (int x = 0; x < Width; x++)
            {
                yield return new Coord(x, y);
            }
        }
    }
}

namespace HollowCrown.Rules.Tactical;

/// <summary>
/// A battle grid coordinate. X runs west to east, Y runs SOUTH to NORTH.
/// </summary>
/// <remarks>
/// The Y direction matters and is easy to get wrong. Battle JSON writes its
/// terrain grid north row first, so row 0 of the file is the highest Y. The
/// conversion happens once, in <see cref="BattleGrid.Parse"/>, and nowhere else.
/// </remarks>
public readonly record struct Coord(int X, int Y)
{
    public static readonly Coord Zero = new(0, 0);

    /// <summary>Manhattan distance, which is the game's notion of range.</summary>
    public int DistanceTo(Coord other) => Math.Abs(X - other.X) + Math.Abs(Y - other.Y);

    public Coord Offset(int dx, int dy) => new(X + dx, Y + dy);

    /// <summary>The four orthogonal neighbours. Movement and range are never diagonal.</summary>
    public IEnumerable<Coord> Neighbours()
    {
        yield return new Coord(X + 1, Y);
        yield return new Coord(X - 1, Y);
        yield return new Coord(X, Y + 1);
        yield return new Coord(X, Y - 1);
    }

    public override string ToString() => $"[{X},{Y}]";
}

/// <summary>Which side of a unit an attack lands on. Drives directional armour.</summary>
public enum Facing
{
    Front,
    Flank,
    Rear,
}

/// <summary>The cardinal direction a unit is looking.</summary>
public enum Heading
{
    North,
    East,
    South,
    West,
}

public static class HeadingExtensions
{
    /// <summary>
    /// Where an attack from <paramref name="from"/> lands on a unit at
    /// <paramref name="target"/> that is looking along <paramref name="heading"/>.
    /// </summary>
    /// <remarks>
    /// The Wallstalker's whole tutorial rests on this: armoured 8 from the front,
    /// 2 from a flank, 0 from behind. Attacks are orthogonal, so the answer is
    /// always exactly one of the three cases.
    /// </remarks>
    public static Facing FacingFrom(this Heading heading, Coord target, Coord from)
    {
        int dx = from.X - target.X;
        int dy = from.Y - target.Y;

        // The dominant axis decides; a tie means a diagonal, which range never
        // produces, but treating it as a flank is the safe reading.
        bool verticalDominant = Math.Abs(dy) > Math.Abs(dx);
        if (Math.Abs(dy) == Math.Abs(dx))
        {
            return Facing.Flank;
        }

        Heading attackFrom = verticalDominant
            ? (dy > 0 ? Heading.North : Heading.South)
            : (dx > 0 ? Heading.East : Heading.West);

        if (attackFrom == heading)
        {
            return Facing.Front;
        }

        return Opposite(heading) == attackFrom ? Facing.Rear : Facing.Flank;
    }

    public static Heading Opposite(this Heading heading) => heading switch
    {
        Heading.North => Heading.South,
        Heading.South => Heading.North,
        Heading.East => Heading.West,
        Heading.West => Heading.East,
        _ => throw new ArgumentOutOfRangeException(nameof(heading), heading, null),
    };

    /// <summary>The heading a unit takes when it turns to face a target.</summary>
    public static Heading Towards(Coord from, Coord target)
    {
        int dx = target.X - from.X;
        int dy = target.Y - from.Y;
        if (Math.Abs(dy) >= Math.Abs(dx))
        {
            return dy >= 0 ? Heading.North : Heading.South;
        }

        return dx >= 0 ? Heading.East : Heading.West;
    }
}

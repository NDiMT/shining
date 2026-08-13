namespace HollowCrown.Rules.Combat;

/// <summary>
/// Individual initiative by agility. Brief section 21's preferred option, chosen
/// there because it gives units personality and makes ordering tactical.
/// </summary>
/// <remarks>
/// Ties break on unit id, not on insertion order or a random draw. That is a
/// determinism requirement (brief section 74): the same battle with the same seed
/// has to produce the same order every time, or a replay diverges on turn one.
/// </remarks>
public sealed class TurnOrder
{
    private readonly List<string> _order = new();
    private int _index;

    public int Round { get; private set; } = 1;

    public IReadOnlyList<string> Order => _order;

    public int Index => _index;

    /// <summary>The unit id whose turn it is, or null if the round is spent.</summary>
    public string? Current => _index >= 0 && _index < _order.Count ? _order[_index] : null;

    /// <summary>Rebuild the order for a new round from the units still in play.</summary>
    public void BeginRound(IEnumerable<Unit> units)
    {
        _order.Clear();
        _order.AddRange(units
            .Where(u => u.Active)
            .OrderByDescending(u => u.Base.Agility)
            .ThenBy(u => u.Id, StringComparer.Ordinal)
            .Select(u => u.Id));
        _index = 0;
    }

    /// <summary>
    /// Advance to the next unit. Returns false when the round is over, at which
    /// point the caller should call <see cref="BeginRound"/> again.
    /// </summary>
    public bool Advance()
    {
        _index++;
        return _index < _order.Count;
    }

    public void NextRound(IEnumerable<Unit> units)
    {
        Round++;
        BeginRound(units);
    }

    /// <summary>
    /// Drop a unit that left play mid-round so the order does not stall on it.
    /// </summary>
    /// <remarks>
    /// Removing an entry before the cursor would shift every later index by one
    /// and silently skip a unit, so the cursor is adjusted to compensate.
    /// </remarks>
    public void Remove(string unitId)
    {
        int at = _order.IndexOf(unitId);
        if (at < 0)
        {
            return;
        }

        _order.RemoveAt(at);
        if (at < _index)
        {
            _index--;
        }
    }
}

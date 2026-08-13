namespace HollowCrown.Rules.Core;

/// <summary>
/// Seeded randomness. Brief section 74 wants battles deterministic enough to
/// debug, save and replay, and that is an architectural property rather than a
/// feature: it only holds if every random draw in the game comes through an
/// injected instance of this.
/// </summary>
/// <remarks>
/// Never call <c>System.Random</c> or <c>Random.Shared</c> at a call site. A
/// battle plus a seed plus an input log must reproduce exactly, which is what
/// makes a bug report actionable.
///
/// The generator is xorshift128+ rather than <c>System.Random</c> because the
/// framework's algorithm is explicitly not guaranteed stable across .NET
/// versions. A save that replays differently after a runtime upgrade would be a
/// miserable bug to chase.
/// </remarks>
public sealed class Rng
{
    private ulong _s0;
    private ulong _s1;

    public Rng(ulong seed)
    {
        Seed = seed;
        // SplitMix64 to spread a small seed across the state; a zero state would
        // make xorshift produce nothing but zeroes.
        _s0 = SplitMix(ref seed);
        _s1 = SplitMix(ref seed);
        if (_s0 == 0 && _s1 == 0)
        {
            _s1 = 0x9E3779B97F4A7C15;
        }
    }

    /// <summary>The seed this instance was created from, for save files and bug reports.</summary>
    public ulong Seed { get; }

    /// <summary>Number of draws taken. Part of the replay record.</summary>
    public long Draws { get; private set; }

    private static ulong SplitMix(ref ulong x)
    {
        x += 0x9E3779B97F4A7C15;
        ulong z = x;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EB;
        return z ^ (z >> 31);
    }

    private ulong Next()
    {
        Draws++;
        ulong s1 = _s0;
        ulong s0 = _s1;
        _s0 = s0;
        s1 ^= s1 << 23;
        _s1 = s1 ^ s0 ^ (s1 >> 17) ^ (s0 >> 26);
        return _s1 + s0;
    }

    /// <summary>Uniform integer in [0, exclusiveMax).</summary>
    public int Next(int exclusiveMax)
    {
        if (exclusiveMax <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(exclusiveMax), exclusiveMax, "must be positive");
        }

        // Rejection sampling, so the distribution stays uniform rather than
        // biasing low values the way a plain modulo does.
        ulong limit = ulong.MaxValue - (ulong.MaxValue % (ulong)exclusiveMax);
        ulong draw;
        do
        {
            draw = Next();
        }
        while (draw >= limit);

        return (int)(draw % (ulong)exclusiveMax);
    }

    /// <summary>Uniform integer in [inclusiveMin, inclusiveMax].</summary>
    public int Range(int inclusiveMin, int inclusiveMax)
    {
        if (inclusiveMax < inclusiveMin)
        {
            throw new ArgumentOutOfRangeException(nameof(inclusiveMax), "max below min");
        }

        return inclusiveMin + Next(inclusiveMax - inclusiveMin + 1);
    }

    /// <summary>True with the given percentage chance. 0 never, 100 always.</summary>
    public bool Chance(int percent) => percent > 0 && Next(100) < percent;

    /// <summary>
    /// A derived generator for an independent stream.
    /// </summary>
    /// <remarks>
    /// Lets one battle's damage rolls stay reproducible even if an unrelated
    /// system starts drawing from its own stream, which otherwise shifts every
    /// later draw and breaks replay.
    /// </remarks>
    public Rng Fork(ulong salt) => new(Seed ^ (salt * 0x9E3779B97F4A7C15));
}

using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Rules.Battle;

/// <summary>
/// Something that happened in a battle, for the presentation layer to play back.
/// </summary>
/// <remarks>
/// This is the seam between rules and presentation. The rules decide what
/// happened and emit it; Godot decides how it looks — camera moves, hit-stop,
/// particles, sound. Brief section 92's battle-speed options then change playback
/// only, never the rules, which is why fast mode cannot alter an outcome.
///
/// Records rather than an enum plus a bag of fields: a handler that switches on
/// the type gets exactly the data that event carries.
/// </remarks>
public abstract record BattleEvent
{
    public sealed record BattleStarted(string BattleId, string Objective) : BattleEvent;

    public sealed record RoundStarted(int Round, IReadOnlyList<string> Order) : BattleEvent;

    public sealed record TurnStarted(string UnitId, Side Side) : BattleEvent;

    public sealed record UnitMoved(string UnitId, Coord From, Coord To, IReadOnlyList<Coord> Path)
        : BattleEvent;

    public sealed record UnitAttacked(
        string AttackerId,
        string TargetId,
        int Damage,
        bool Critical,
        Facing Facing,
        bool Defeated) : BattleEvent;

    public sealed record SkillCast(
        string CasterId,
        string TargetId,
        string SkillId,
        int Damage,
        bool Defeated) : BattleEvent;

    public sealed record UnitDefeated(string UnitId, bool Incapacitated) : BattleEvent;

    public sealed record UnitFled(string UnitId) : BattleEvent;

    public sealed record UnitWaited(string UnitId) : BattleEvent;

    public sealed record UnitSpawned(string UnitId, Coord At, Side Side) : BattleEvent;

    public sealed record SideChanged(string UnitId, Side From, Side To) : BattleEvent;

    public sealed record TerrainChanged(Coord At, string TerrainId) : BattleEvent;

    public sealed record ObjectiveChanged(string Description) : BattleEvent;

    public sealed record RuleCleared(string Rule) : BattleEvent;

    public sealed record FlagSet(string Flag, string Value) : BattleEvent;

    /// <summary>A scripted event asked for dialogue. The rules do not read it.</summary>
    public sealed record DialogueRequested(string SceneId) : BattleEvent;

    /// <summary>Purely presentational cues: camera, shake, sound, prop swaps.</summary>
    public sealed record Cue(string Kind, string Value, Coord? At = null) : BattleEvent;

    public sealed record BattleEnded(bool Victory, string Reason) : BattleEvent;
}

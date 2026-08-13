using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Core;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Rules.Battle;

public sealed record BattleOutcome(bool Victory, string Reason);

/// <summary>
/// A battle in progress. The whole tactical loop of brief section 22, plus the
/// scripted events of section 41.
/// </summary>
/// <remarks>
/// Everything here is engine-free, so a battle can be played to completion in a
/// test in milliseconds. That is what makes it possible to assert that the
/// prologue's turn-3 event does all nine of the things it claims to.
///
/// The class mutates itself and appends to <see cref="Events"/>. Presentation
/// drains that queue and animates it; the rules never wait for animation, which
/// keeps brief section 92's speed options free.
/// </remarks>
public sealed class BattleState
{
    private readonly List<BattleEvent> _events = new();
    private readonly List<ScriptedEvent> _scripted;
    private readonly HashSet<string> _nonLethalSides;
    private readonly Dictionary<string, string> _flags = new(StringComparer.Ordinal);
    private readonly ContentDatabase _content;
    private readonly List<Unit> _units;

    public BattleState(
        BattleDefinition definition,
        ContentDatabase content,
        Rng rng,
        IEnumerable<ScriptedEvent>? scripted = null)
    {
        Definition = definition;
        _content = content;
        Rng = rng;
        Grid = definition.Grid;
        _units = definition.Units.ToList();
        _nonLethalSides = new HashSet<string>(definition.NonLethalSides, StringComparer.OrdinalIgnoreCase);
        _scripted = (scripted ?? Array.Empty<ScriptedEvent>()).ToList();
        Objective = definition.Objectives.FirstOrDefault()
                    ?? new ObjectiveDefinition { Type = "defeat_all", Description = "Defeat all enemies" };
    }

    public BattleDefinition Definition { get; }
    public BattleGrid Grid { get; }
    public Rng Rng { get; }
    public TurnOrder Turns { get; } = new();
    public ObjectiveDefinition Objective { get; private set; }
    public BattleOutcome? Outcome { get; private set; }
    public IReadOnlyList<Unit> Units => _units;
    public IReadOnlyList<BattleEvent> Events => _events;
    public IReadOnlyDictionary<string, string> Flags => _flags;

    public bool Finished => Outcome is not null;

    public Unit? Current =>
        Turns.Current is null ? null : _units.FirstOrDefault(u => u.Id == Turns.Current);

    public IEnumerable<Unit> ActiveUnits => _units.Where(u => u.Active);

    /// <summary>Take everything emitted since the last drain.</summary>
    public IReadOnlyList<BattleEvent> DrainEvents()
    {
        var drained = _events.ToList();
        _events.Clear();
        return drained;
    }

    public Unit? FindUnit(string id) => _units.FirstOrDefault(u => u.Id == id);

    public bool IsNonLethalFor(Side side) => _nonLethalSides.Contains(side.ToString());

    // -- lifecycle ---------------------------------------------------------

    public void Start()
    {
        Emit(new BattleEvent.BattleStarted(Definition.Id, Objective.Description ?? Objective.Type));
        FireTriggers("battle_start", null);
        Turns.BeginRound(ActiveUnits);
        Emit(new BattleEvent.RoundStarted(Turns.Round, Turns.Order));
        BeginTurn();
    }

    private void BeginTurn()
    {
        if (Finished)
        {
            return;
        }

        Unit? unit = Current;
        while (unit is not null && !unit.Active)
        {
            if (!Turns.Advance())
            {
                NextRound();
                return;
            }

            unit = Current;
        }

        if (unit is null)
        {
            NextRound();
            return;
        }

        unit.HasMoved = false;
        unit.HasActed = false;
        FireTriggers("turn_start", unit.Side);
        if (Finished)
        {
            return;
        }

        // A trigger may have removed this unit, so re-check before announcing it.
        if (Current is { Active: true } active)
        {
            Emit(new BattleEvent.TurnStarted(active.Id, active.Side));
        }
        else
        {
            EndTurn();
        }
    }

    private void NextRound()
    {
        if (Finished)
        {
            return;
        }

        Turns.NextRound(ActiveUnits);
        if (Turns.Order.Count == 0)
        {
            Finish(false, "no units left able to act");
            return;
        }

        Emit(new BattleEvent.RoundStarted(Turns.Round, Turns.Order));
        CheckObjectives();
        if (!Finished)
        {
            BeginTurn();
        }
    }

    /// <summary>End the active unit's turn and advance.</summary>
    public void EndTurn()
    {
        if (Finished)
        {
            return;
        }

        CheckObjectives();
        if (Finished)
        {
            return;
        }

        if (!Turns.Advance())
        {
            NextRound();
            return;
        }

        BeginTurn();
    }

    // -- player and AI actions --------------------------------------------

    public ReachableSet ReachableFor(Unit unit)
    {
        var occupied = ActiveUnits.Where(u => u != unit).Select(u => u.Position).ToHashSet();
        return Movement.Reachable(
            Grid, unit.Position, unit.MovementPoints, unit.MovementType, occupied.Contains);
    }

    public bool CanMove(Unit unit, Coord to) =>
        !unit.HasMoved && !Finished && ReachableFor(unit).CanReach(to);

    public void Move(Unit unit, Coord to)
    {
        if (unit.HasMoved)
        {
            throw new InvalidOperationException($"{unit.Id} has already moved this turn");
        }

        ReachableSet reach = ReachableFor(unit);
        if (!reach.CanReach(to))
        {
            throw new InvalidOperationException($"{unit.Id} cannot reach {to}");
        }

        Coord from = unit.Position;
        IReadOnlyList<Coord> path = reach.PathTo(to);
        unit.Position = to;
        unit.HasMoved = true;
        Emit(new BattleEvent.UnitMoved(unit.Id, from, to, path));
    }

    public IEnumerable<Unit> AttackTargets(Unit unit) =>
        ActiveUnits.Where(t => unit.IsHostileTo(t) && DamageModel.InWeaponRange(unit, t));

    public IEnumerable<Unit> SkillTargets(Unit unit, Skill skill) =>
        ActiveUnits.Where(t => unit.IsHostileTo(t) && DamageModel.InSkillRange(unit, t, skill));

    public DamageForecast Forecast(Unit attacker, Unit target) =>
        DamageModel.ForecastPhysical(attacker, target, Grid);

    public void Attack(Unit attacker, Unit target)
    {
        if (attacker.HasActed)
        {
            throw new InvalidOperationException($"{attacker.Id} has already acted this turn");
        }

        if (!DamageModel.InWeaponRange(attacker, target))
        {
            throw new InvalidOperationException($"{target.Id} is out of range");
        }

        // A unit turns to face what it attacks, which is what lets the player
        // manoeuvre around a boss's armoured front rather than having facing
        // handed to them.
        attacker.Heading = HeadingExtensions.Towards(attacker.Position, target.Position);

        DamageForecast forecast = Forecast(attacker, target);
        AttackResult result = DamageModel.Apply(
            target, forecast, Rng, IsNonLethalFor(target.Side));

        attacker.HasActed = true;
        Emit(new BattleEvent.UnitAttacked(
            attacker.Id, target.Id, result.Damage, result.Critical, result.Facing, result.Defeated));

        if (result.Defeated)
        {
            OnDefeated(target);
        }
    }

    public void CastSkill(Unit caster, Unit target, string skillId)
    {
        if (caster.HasActed)
        {
            throw new InvalidOperationException($"{caster.Id} has already acted this turn");
        }

        Skill skill = caster.FindSkill(skillId)
            ?? throw new InvalidOperationException($"{caster.Id} does not know '{skillId}'");

        if (caster.Mp < skill.Cost)
        {
            throw new InvalidOperationException(
                $"{caster.Id} needs {skill.Cost} MP for {skill.Name} and has {caster.Mp}");
        }

        if (!DamageModel.InSkillRange(caster, target, skill))
        {
            throw new InvalidOperationException($"{target.Id} is out of range of {skill.Name}");
        }

        DamageForecast forecast = DamageModel.ForecastSkill(caster, target, skill);
        AttackResult result = DamageModel.Apply(
            target, forecast, Rng, IsNonLethalFor(target.Side));

        caster.Mp -= skill.Cost;
        caster.HasActed = true;
        Emit(new BattleEvent.SkillCast(
            caster.Id, target.Id, skill.Id, result.Damage, result.Defeated));

        if (result.Defeated)
        {
            OnDefeated(target);
        }
    }

    public void Wait(Unit unit)
    {
        unit.HasActed = true;
        Emit(new BattleEvent.UnitWaited(unit.Id));
    }

    private void OnDefeated(Unit unit)
    {
        Emit(new BattleEvent.UnitDefeated(unit.Id, unit.Incapacitated));
        Turns.Remove(unit.Id);
        FireTriggers("unit_defeated", null, unit.Id);
        FireTriggers("enemies_remaining", null);
    }

    // -- objectives --------------------------------------------------------

    private void CheckObjectives()
    {
        if (Finished)
        {
            return;
        }

        foreach (ObjectiveDefinition condition in Definition.DefeatConditions)
        {
            if (condition.UnitId is not null && FindUnit(condition.UnitId) is { Active: false })
            {
                Finish(false, condition.Description ?? $"{condition.UnitId} fell");
                return;
            }
        }

        switch (Objective.Type)
        {
            case "defeat_all":
                if (!ActiveUnits.Any(u => u.Side is Side.Enemy or Side.HostileToAll))
                {
                    Finish(true, "all enemies defeated");
                }

                break;

            case "defeat_unit":
            case "defeat_commander":
                if (Objective.UnitId is not null && FindUnit(Objective.UnitId) is null or { Active: false })
                {
                    Finish(true, $"{Objective.UnitId} defeated");
                }

                break;

            case "survive_turns":
                if (Turns.Round > Objective.Turns)
                {
                    Finish(true, $"survived {Objective.Turns} turns");
                }

                break;
        }
    }

    private void Finish(bool victory, string reason)
    {
        Outcome = new BattleOutcome(victory, reason);
        Emit(new BattleEvent.BattleEnded(victory, reason));
    }

    // -- scripted events ---------------------------------------------------

    private void FireTriggers(string type, Side? side, string? unitId = null)
    {
        // Copy first: an action may spawn a unit or change an objective, and
        // mutating the list while walking it would be a lurking bug.
        foreach (ScriptedEvent scripted in _scripted.ToList())
        {
            if (scripted.HasFired && scripted.Once)
            {
                continue;
            }

            if (!Matches(scripted.Trigger, type, side, unitId))
            {
                continue;
            }

            scripted.HasFired = true;
            foreach (EventAction action in scripted.Actions)
            {
                Execute(action);
            }

            CheckObjectives();
        }
    }

    private bool Matches(EventTrigger trigger, string type, Side? side, string? unitId)
    {
        if (!string.Equals(trigger.Type, type, StringComparison.Ordinal))
        {
            return false;
        }

        switch (type)
        {
            case "turn_start":
                if (trigger.Turn > 0 && trigger.Turn != Turns.Round)
                {
                    return false;
                }

                if (trigger.Side is not null &&
                    !string.Equals(trigger.Side, side?.ToString(), StringComparison.OrdinalIgnoreCase))
                {
                    return false;
                }

                return true;

            case "unit_defeated":
                return trigger.UnitId is null || trigger.UnitId == unitId;

            case "enemies_remaining":
                int remaining = ActiveUnits.Count(u => u.Side == Side.Enemy);
                return trigger.Comparison switch
                {
                    "lte" => remaining <= trigger.Count,
                    "gte" => remaining >= trigger.Count,
                    "lt" => remaining < trigger.Count,
                    "gt" => remaining > trigger.Count,
                    _ => remaining == trigger.Count,
                };

            case "battle_start":
                return true;

            default:
                return false;
        }
    }

    private void Execute(EventAction action)
    {
        switch (action.Type)
        {
            case "set_terrain":
                foreach ((int x, int y) in action.Tiles)
                {
                    var at = new Coord(x, y);
                    Grid.SetTerrain(at, action.Terrain!);
                    Emit(new BattleEvent.TerrainChanged(at, action.Terrain!));
                }

                break;

            case "spawn_unit":
            {
                Side side = ParseSide(action.SideName) ?? Side.Enemy;
                var at = new Coord(action.Position!.Value.X, action.Position.Value.Y);
                Unit spawned = _content.Spawn(
                    action.DefinitionId!, side, at, action.SpawnId ?? action.DefinitionId!);
                _units.Add(spawned);
                Turns.Remove(spawned.Id);
                Emit(new BattleEvent.UnitSpawned(spawned.Id, at, side));
                break;
            }

            case "change_side":
            {
                Side to = ParseSide(action.SideName)
                          ?? throw new InvalidOperationException($"unknown side '{action.SideName}'");
                foreach (string id in action.UnitIds)
                {
                    if (FindUnit(id) is { } unit)
                    {
                        Side from = unit.Side;
                        unit.Side = to;
                        Emit(new BattleEvent.SideChanged(unit.Id, from, to));
                    }
                }

                break;
            }

            case "set_objective":
                Objective = new ObjectiveDefinition
                {
                    Type = action.Objective!.Type,
                    Description = action.Objective.Description,
                    UnitId = action.Objective.UnitId,
                    Turns = action.Objective.Turns,
                };
                Emit(new BattleEvent.ObjectiveChanged(
                    Objective.Description ?? Objective.Type));
                break;

            case "clear_rule":
                if (string.Equals(action.Rule, "non_lethal_sides", StringComparison.Ordinal))
                {
                    _nonLethalSides.Clear();
                }

                Emit(new BattleEvent.RuleCleared(action.Rule ?? string.Empty));
                break;

            case "set_flag":
                _flags[action.Flag!] = action.Value ?? "true";
                Emit(new BattleEvent.FlagSet(action.Flag!, action.Value ?? "true"));
                break;

            case "force_move":
                if (FindUnit(action.UnitId!) is { } moved && action.Position is { } target)
                {
                    Coord from = moved.Position;
                    var to = new Coord(target.X, target.Y);
                    moved.Position = to;
                    Emit(new BattleEvent.UnitMoved(moved.Id, from, to, new[] { to }));
                }

                break;

            case "flee_to_exit":
                if (FindUnit(action.UnitId!) is { } fleeing)
                {
                    fleeing.Fled = true;
                    Turns.Remove(fleeing.Id);
                    Emit(new BattleEvent.UnitFled(fleeing.Id));
                }

                break;

            case "set_ai":
                // AI behaviour lives on the unit definition, which is immutable, so
                // the runner keeps overrides beside it.
                foreach (string id in action.UnitIds)
                {
                    AiOverrides[id] = action.Ai!;
                }

                break;

            case "dialogue":
                Emit(new BattleEvent.DialogueRequested(action.Scene!));
                break;

            // Presentation-only. The rules do not care, but the events must reach
            // Godot in order, interleaved with the mechanical ones.
            case "focus_camera":
                Emit(new BattleEvent.Cue("focus_camera", string.Empty,
                    action.Position is { } p ? new Coord(p.X, p.Y) : null));
                break;

            case "screen_shake":
                Emit(new BattleEvent.Cue("screen_shake",
                    action.Intensity.ToString(System.Globalization.CultureInfo.InvariantCulture)));
                break;

            case "sound":
                Emit(new BattleEvent.Cue("sound", action.Sound ?? string.Empty));
                break;

            case "swap_prop":
            case "spawn_decoration":
                Emit(new BattleEvent.Cue(action.Type, action.Value ?? string.Empty));
                break;

            default:
                // Matches the offline validator's stance: an unregistered action is
                // a typo until proven otherwise, and a silent no-op is the worst
                // possible failure for data-driven content.
                throw new InvalidOperationException(
                    $"unknown scripted action '{action.Type}'. Register it here and in " +
                    "Tools/hollowasset/content.py, or the data and the engine will drift.");
        }
    }

    /// <summary>AI behaviour overrides applied by scripted events.</summary>
    public Dictionary<string, string> AiOverrides { get; } = new(StringComparer.Ordinal);

    public string BehaviourOf(Unit unit) =>
        AiOverrides.TryGetValue(unit.Id, out string? behaviour) ? behaviour : unit.AiBehaviour;

    private static Side? ParseSide(string? name) => name?.ToLowerInvariant() switch
    {
        "player" => Side.Player,
        "ally" => Side.Ally,
        "enemy" => Side.Enemy,
        "hostile_to_all" => Side.HostileToAll,
        _ => null,
    };

    private void Emit(BattleEvent battleEvent) => _events.Add(battleEvent);
}

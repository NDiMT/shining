using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Presentation.UI;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Core;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// The North Meadow battle, built from <c>battle_north_meadow.json</c>.
/// </summary>
/// <remarks>
/// <para>
/// Nothing on this battlefield is hand placed. The terrain, the elevation, the
/// props, the deployment and every number in the HUD come from
/// <c>Content/Data</c> through <c>Game.Rules</c>. Point the loader at
/// <c>battle_the_breach.json</c> and a different battle builds — which is brief
/// section 14's requirement that content changes touch no engine code, and the
/// only way milestone 6 can ship a battle rather than a diorama.
/// </para>
/// <para>
/// The division of labour is ARCHITECTURE.md's: the rules layer decides, this
/// layer shows. Movement range is <see cref="Movement.Reachable"/>, reach is
/// <see cref="Targeting"/>, damage is <see cref="DamageModel"/>, and none of them
/// are reimplemented here — a second implementation is a second set of numbers,
/// and the tested one would not be the one the player sees.
/// </para>
/// <para>
/// NOT YET RUN: Godot could not be installed in the environment this was written
/// in. docs/GODOT_SCENE.md lists what is verified by test and what needs the
/// editor opened once.
/// </para>
/// </remarks>
public sealed partial class BattleScene : Node3D
{
    /// <summary>Which battle file to build. Data-driven, so battle 02 needs no code.</summary>
    [Export] public string BattleFile { get; set; } = "battle_north_meadow.json";

    /// <summary>
    /// Battle seed. Brief section 74: every draw comes from one injected generator,
    /// so a battle plus a seed plus an input log reproduces exactly.
    /// </summary>
    [Export] public int Seed { get; set; } = 20260813;

    // ANIME_DIRECTION rule 1 asks for a tunable ramp, and rule 2 for a tunable
    // outline. These are the shader uniforms surfaced in the inspector, so the
    // look can be dialled in with the game running rather than by editing a file
    // and restarting. The shaders carry the same defaults.
    [Export] public int ToonBands { get; set; } = 3;
    [Export] public int GroundBands { get; set; } = 4;
    [Export] public float Terminator { get; set; } = 0.42f;
    [Export] public float RimEdge { get; set; } = 0.88f;
    [Export] public float ShadowLevel { get; set; } = 0.42f;
    [Export] public float LightGain { get; set; } = 1.0f;
    [Export] public float OutlineWidthMetres { get; set; } = 0.05f;
    [Export] public float OutlineDistanceFalloff { get; set; } = 0.55f;

    private Rng _rng = null!;

    private BattleDefinition _battle = null!;
    private GridSpace _space = null!;
    private ToonLook _look = null!;
    private ModelLibrary _models = null!;
    private TurnOrder _turns = null!;

    private Dictionary<string, UnitVisual> _visuals = new(StringComparer.Ordinal);
    private TacticalCamera _camera = null!;
    private BattleHud _hud = null!;
    private GridCursor _cursor = null!;
    private TileOverlay _moveOverlay = null!;
    private TileOverlay _attackOverlay = null!;
    private TileOverlay _threatOverlay = null!;

    private HashSet<string> _placeholders = new(StringComparer.Ordinal);
    private Unit? _selected;
    private ReachableSet? _reach;
    private int _round = 1;
    private bool _failed;

    public override void _Ready()
    {
        // Constructed here rather than in a field initialiser: Godot applies
        // [Export] values after the object exists, so a generator seeded in the
        // constructor would ignore whatever the scene sets Seed to.
        _rng = new Rng((ulong)Seed);

        _camera = GetNode<TacticalCamera>("CameraRig");
        _hud = GetNode<BattleHud>("Hud");

        try
        {
            ContentDatabase content = ContentDatabase.Load(ContentPaths.Data);
            _battle = BattleLoader.Load(Path.Combine(ContentPaths.Battles, BattleFile), content);
        }
        catch (ContentException exception)
        {
            // Brief section 75: development builds fail loudly and informatively.
            // An empty battlefield with an error in the log beats a crash on start,
            // because the log is where the answer is.
            GD.PushError($"could not load {BattleFile}: {exception.Message}");
            _failed = true;
            return;
        }

        _space = new GridSpace(_battle.Grid);
        _camera.Frame(_space);

        // Built after the camera is framed: the outline width is tuned in pixels at
        // the distance the game is actually played from (ANIME_DIRECTION rule 2),
        // and that distance is derived from the size of this battle's grid.
        _look = new ToonLook(_camera.RestDistance, new ToonSettings
        {
            Bands = ToonBands,
            GroundBands = GroundBands,
            Terminator = Terminator,
            RimEdge = RimEdge,
            ShadowLevel = ShadowLevel,
            LightGain = LightGain,
            OutlineWidthMetres = OutlineWidthMetres,
            OutlineDistanceFalloff = OutlineDistanceFalloff,
        });
        _models = new ModelLibrary();

        BuildField();
        BuildOverlays();

        _turns = new TurnOrder();
        _turns.BeginRound(_battle.Units);

        _hud.ShowBattle(_battle, _round);
        _hud.ShowUnit(null, null, null);

        // Open on the player's line rather than on the geometric centre of the
        // field: the first thing a player should see is their own party.
        Unit? first = _battle.Units.FirstOrDefault(u => u.Side == Side.Player);
        if (first is not null)
        {
            _camera.FocusOn(_space.Centre(first.Position));
        }
    }

    private void BuildField()
    {
        var terrain = new Node3D { Name = "Terrain" };
        AddChild(terrain);
        new TerrainBuilder(_space, _look).Build(_battle.Grid, terrain);

        var props = new Node3D { Name = "Props" };
        AddChild(props);
        PropReport propReport = new PropBuilder(_space, _models, _look).Build(_battle.Props, props);

        var units = new Node3D { Name = "Units" };
        AddChild(units);
        var unitBuilder = new UnitBuilder(_space, _models, _look);
        _visuals = unitBuilder.Build(_battle.Units, units);
        _placeholders = unitBuilder.PlaceholderIds;

        _hud.ShowLoadReport(
            propReport.Placed, propReport.Skipped,
            unitBuilder.Modelled, unitBuilder.Placeholders,
            propReport.SlabsRemoved, _models.Missing);

        GD.Print(
            $"{_battle.Name}: {_battle.Grid.Width}x{_battle.Grid.Height} tiles, " +
            $"{propReport.Placed} props placed and {propReport.Skipped} skipped, " +
            $"{unitBuilder.Modelled} units modelled and {unitBuilder.Placeholders} on placeholders, " +
            $"{_models.Available} GLBs available.");
    }

    private void BuildOverlays()
    {
        var overlays = new Node3D { Name = "Overlays" };
        AddChild(overlays);

        // Drawn in this order and at these heights so they stack predictably: the
        // threat range of an enemy is the widest and lowest, the unit's own reach
        // sits above it, and the cursor frame is above everything.
        _threatOverlay = Layer(overlays, "ThreatRange", ToonLook.ThreatHighlight, 0.20f, 0.02f);
        _moveOverlay = Layer(overlays, "MoveRange", ToonLook.MoveHighlight, 0.34f, 0.03f);
        _attackOverlay = Layer(overlays, "AttackRange", ToonLook.AttackHighlight, 0.30f, 0.04f);

        _cursor = new GridCursor { Name = "Cursor" };
        overlays.AddChild(_cursor);

        Unit? first = _battle.Units.FirstOrDefault(u => u.Side == Side.Player);
        _cursor.Initialise(_space, first?.Position ?? new Coord(0, 0));
    }

    private TileOverlay Layer(Node3D parent, string name, Color colour, float alpha, float lift)
    {
        var layer = new TileOverlay { Name = name };
        parent.AddChild(layer);
        layer.Initialise(_space, _battle.Grid, colour, alpha, lift);
        return layer;
    }

    // -----------------------------------------------------------------------
    // Input
    // -----------------------------------------------------------------------

    public override void _UnhandledInput(InputEvent @event)
    {
        if (_failed)
        {
            return;
        }

        if (@event is InputEventMouseMotion motion)
        {
            MoveCursor(_space.PickClamped(_camera.Camera, motion.Position, _cursor.Cell));
            return;
        }

        if (@event is InputEventMouseButton { ButtonIndex: MouseButton.Left, Pressed: true } click)
        {
            Coord? cell = _space.Pick(_camera.Camera, click.Position);
            if (cell is not null)
            {
                MoveCursor(cell.Value);
                Activate(cell.Value);
            }

            return;
        }

        if (@event is InputEventMouseButton { ButtonIndex: MouseButton.Right, Pressed: true })
        {
            Select(null);
            return;
        }

        if (@event is not InputEventKey { Pressed: true, Echo: false } key)
        {
            return;
        }

        switch (key.Keycode)
        {
            case Key.Up:
                Nudge(new Vector2I(0, 1));
                break;
            case Key.Down:
                Nudge(new Vector2I(0, -1));
                break;
            case Key.Left:
                Nudge(new Vector2I(-1, 0));
                break;
            case Key.Right:
                Nudge(new Vector2I(1, 0));
                break;
            case Key.Enter or Key.KpEnter:
                Activate(_cursor.Cell);
                break;
            case Key.Tab:
                CycleSelection();
                break;
            case Key.F:
                _camera.FocusOn(_space.Centre(_cursor.Cell));
                break;
            case Key.Q:
                _camera.SnapYaw(-1);
                break;
            case Key.E:
                _camera.SnapYaw(1);
                break;
            case Key.R:
                _camera.ResetView(_space);
                break;
            case Key.Space:
                EndRound();
                break;
        }
    }

    /// <summary>Move the cursor one tile in a screen direction.</summary>
    private void Nudge(Vector2I screenDirection)
    {
        Vector2I step = _camera.ScreenToGrid(screenDirection);
        var next = new Coord(_cursor.Cell.X + step.X, _cursor.Cell.Y + step.Y);
        if (_battle.Grid.Contains(next))
        {
            MoveCursor(next);
        }
    }

    private void MoveCursor(Coord cell)
    {
        if (cell == _cursor.Cell)
        {
            return;
        }

        _cursor.MoveTo(cell);
        RefreshInspector();
    }

    /// <summary>
    /// Click, or Enter: select, move, or attack, in that order of preference.
    /// </summary>
    /// <remarks>
    /// One verb on one button. The alternative — a menu after every move, as brief
    /// section 26 will eventually want — needs the turn loop of milestone 4 under
    /// it. What is here is the smallest thing that lets a person confirm the scene
    /// works: select a unit, watch the range appear, move it, hit something.
    /// </remarks>
    private void Activate(Coord cell)
    {
        Unit? occupant = Targeting.UnitAt(_battle.Units, cell);

        if (_selected is not null && occupant is not null && _selected.IsHostileTo(occupant)
            && DamageModel.InWeaponRange(_selected, occupant) && !_selected.HasActed)
        {
            Attack(_selected, occupant);
            return;
        }

        if (occupant is not null && occupant.Side != Side.Enemy && !occupant.HasActed)
        {
            Select(occupant);
            return;
        }

        if (_selected is not null && _reach is not null && _reach.CanReach(cell)
            && occupant is null && !_selected.HasMoved)
        {
            MoveUnit(_selected, cell);
            return;
        }

        // Clicking an enemy leaves the selection alone and lets the inspector do
        // the talking, which is how a player finds out what they are walking into
        // without losing the unit they were about to move.
        if (occupant is null or { Side: Side.Enemy })
        {
            RefreshInspector();
            return;
        }

        Select(occupant);
    }

    /// <summary>
    /// Step through the player's units that still have something to do.
    /// </summary>
    /// <remarks>
    /// Ordered by unit id rather than by initiative, because <see cref="TurnOrder"/>
    /// is not enforced yet (milestone 4) and an order that changes between presses
    /// would be worse than a fixed one. The camera follows, because a cycle that
    /// selects a unit off screen is a cycle nobody uses twice.
    /// </remarks>
    private void CycleSelection()
    {
        List<Unit> candidates = _battle.Units
            .Where(u => u.Active && u.Side != Side.Enemy && !u.HasActed)
            .OrderBy(u => u.Id, StringComparer.Ordinal)
            .ToList();

        if (candidates.Count == 0)
        {
            _hud.SetStatus("Every unit has acted. Space ends the round.");
            return;
        }

        int index = _selected is null
            ? 0
            : (candidates.FindIndex(u => u.Id == _selected.Id) + 1) % candidates.Count;

        Unit next = candidates[index];
        Select(next);
        MoveCursor(next.Position);
        _camera.FocusOn(_space.Centre(next.Position));
    }

    private void Select(Unit? unit)
    {
        if (_selected is not null && _visuals.TryGetValue(_selected.Id, out UnitVisual? previous))
        {
            previous.SetSelected(false);
        }

        _selected = unit;
        _reach = null;

        if (unit is not null)
        {
            _visuals[unit.Id].SetSelected(true);
            _reach = Movement.Reachable(
                _battle.Grid,
                unit.Position,
                unit.HasMoved ? 0 : unit.MovementPoints,
                unit.MovementType,
                IsOccupied);
        }

        RefreshOverlays();
        RefreshInspector();
    }

    private bool IsOccupied(Coord at) => Targeting.UnitAt(_battle.Units, at) is not null;

    private void MoveUnit(Unit unit, Coord destination)
    {
        IReadOnlyList<Coord> path = _reach!.PathTo(destination);
        if (path.Count == 0)
        {
            return;
        }

        // The rules move first and the visual catches up. Doing it the other way
        // round would mean the rules state is briefly a lie, and every query made
        // during the walk — including the AI's, later — would read the old tile.
        unit.Position = destination;
        unit.HasMoved = true;
        unit.Heading = HeadingExtensions.Towards(path.Count > 1 ? path[^2] : _reach.Origin, destination);

        _visuals[unit.Id].WalkAlong(path);

        // Re-select to recompute the ranges from where it now stands.
        Select(unit);
        _hud.SetStatus($"{unit.Name} moved to {destination}.");
    }

    private void Attack(Unit attacker, Unit target)
    {
        attacker.Heading = HeadingExtensions.Towards(attacker.Position, target.Position);
        _visuals[attacker.Id].FaceHeading(attacker.Heading);

        DamageForecast forecast = DamageModel.ForecastPhysical(attacker, target, _battle.Grid);
        AttackResult result = DamageModel.Apply(
            target, forecast, _rng, _battle.IsNonLethalFor(attacker.Side));

        attacker.HasActed = true;
        attacker.HasMoved = true;

        _visuals[attacker.Id].Refresh();
        _visuals[target.Id].Refresh();

        if (result.Defeated)
        {
            _turns.Remove(target.Id);
        }

        _hud.SetStatus(
            $"{attacker.Name} hits {target.Name} for {result.Damage}" +
            (result.Critical ? " (critical)" : string.Empty) +
            (result.Defeated ? $". {target.Name} is defeated." : $". {target.Hp} HP left."));

        Select(attacker);
    }

    /// <summary>
    /// End the round: everyone acts again next round.
    /// </summary>
    /// <remarks>
    /// A placeholder for milestone 4's turn loop, not a substitute for it. There is
    /// no AI here and no per-unit initiative gate — <see cref="TurnOrder"/> is built
    /// and displayed but not yet enforced — so this is one button that makes the
    /// scene playable for more than one round.
    /// </remarks>
    private void EndRound()
    {
        foreach (Unit unit in _battle.Units)
        {
            unit.HasMoved = false;
            unit.HasActed = false;
        }

        _round++;
        _turns.NextRound(_battle.Units);
        Select(null);

        foreach (UnitVisual visual in _visuals.Values)
        {
            visual.Refresh();
        }

        _hud.ShowBattle(_battle, _round);
        _hud.SetStatus($"Round {_round}.");
    }

    // -----------------------------------------------------------------------
    // Overlays and the info panel
    // -----------------------------------------------------------------------

    private void RefreshOverlays()
    {
        if (_selected is null || _reach is null)
        {
            _moveOverlay.Clear();
            _attackOverlay.Clear();
            RefreshThreat();
            return;
        }

        _moveOverlay.Show(_reach.Tiles);

        // Everything the unit could hit this turn, minus the tiles already coloured
        // as movement. Two overlays on one tile would blend into a third colour
        // that means nothing.
        var reachable = new HashSet<Coord>(_reach.Tiles) { _reach.Origin };
        IEnumerable<Coord> attack = Targeting
            .ThreatRange(_battle.Grid, _reach, _selected.WeaponRange)
            .Where(t => !reachable.Contains(t));

        _attackOverlay.Show(attack);
        RefreshThreat();
    }

    /// <summary>Show an enemy's reach when the cursor is over it and nothing is selected.</summary>
    private void RefreshThreat()
    {
        Unit? hovered = Targeting.UnitAt(_battle.Units, _cursor.Cell);
        if (_selected is not null || hovered is null || hovered.Side != Side.Enemy)
        {
            _threatOverlay.Clear();
            return;
        }

        ReachableSet reach = Movement.Reachable(
            _battle.Grid, hovered.Position, hovered.MovementPoints, hovered.MovementType, IsOccupied);
        _threatOverlay.Show(Targeting.ThreatRange(_battle.Grid, reach, hovered.WeaponRange));
    }

    private void RefreshInspector()
    {
        Unit? hovered = Targeting.UnitAt(_battle.Units, _cursor.Cell);
        Unit? subject = hovered ?? _selected;

        DamageForecast? forecast = null;
        Unit? target = null;
        if (_selected is not null && hovered is not null && _selected.IsHostileTo(hovered)
            && DamageModel.InWeaponRange(_selected, hovered))
        {
            // Brief section 28: the damage is previewed before the player commits,
            // by the same function that will resolve it.
            forecast = DamageModel.ForecastPhysical(_selected, hovered, _battle.Grid);
            subject = _selected;
            target = hovered;
        }

        _hud.ShowUnit(subject, _battle.Grid, forecast, target,
                      subject is not null && _placeholders.Contains(subject.Id));
        RefreshThreat();
    }
}

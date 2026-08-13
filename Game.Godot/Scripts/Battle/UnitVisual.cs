using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// One unit on screen: its mesh, its nameplate, and its walk.
/// </summary>
/// <remarks>
/// <para>
/// It owns no rules. <see cref="Unit"/> is the authority on where the unit is and
/// how much health it has; this node's job is to catch up with that state and make
/// it legible. Moving a unit sets <c>Unit.Position</c> immediately and then asks
/// this to walk there, which is ARCHITECTURE.md's stated pattern — the rules
/// resolve, the presentation plays back — and it is what makes brief section 92's
/// battle-speed options a playback change rather than a rules change.
/// </para>
/// </remarks>
public sealed partial class UnitVisual : Node3D
{
    /// <summary>Metres per second along a path.</summary>
    /// <remarks>
    /// 4.5 m/s crosses a 2 m tile in a little under half a second, so Rowan's
    /// six-point move plays in about two and a half seconds — fast enough not to
    /// stall a turn, slow enough that the route taken is readable, which is the
    /// whole reason to animate the move rather than teleport.
    /// </remarks>
    private const float WalkSpeed = 4.5f;

    private readonly Queue<Vector3> _waypoints = new();

    private GridSpace _space = null!;
    private Label3D _plate = null!;
    private MeshInstance3D _selectionRing = null!;
    private Node3D _body = null!;

    public Unit Unit { get; private set; } = null!;

    /// <summary>True while the walk animation is still playing.</summary>
    public bool IsMoving => _waypoints.Count > 0;

    public void Initialise(Unit unit, Node3D body, GridSpace space, float height)
    {
        Unit = unit;
        _space = space;
        _body = body;
        Name = $"Unit_{unit.Id}";
        Position = space.Centre(unit.Position);

        AddChild(body);

        Color sideColour = unit.Side == Side.Enemy
            ? ToonLook.AttackHighlight
            : ToonLook.MoveHighlight;

        _selectionRing = new MeshInstance3D
        {
            Name = "SelectionRing",
            Mesh = new TorusMesh { InnerRadius = 0.62f, OuterRadius = 0.78f },
            Position = new Vector3(0f, 0.05f, 0f),
            MaterialOverride = ToonLook.Overlay(ToonLook.Bone, 0.9f),
            Visible = false,
        };
        AddChild(_selectionRing);

        // A side band on the ground under every unit, not just the selected one.
        // Twelve placeholders in two hues is readable; twelve placeholders where
        // only one of them says which side it is on is not.
        AddChild(new MeshInstance3D
        {
            Name = "SideRing",
            Mesh = new TorusMesh { InnerRadius = 0.80f, OuterRadius = 0.90f },
            Position = new Vector3(0f, 0.04f, 0f),
            MaterialOverride = ToonLook.Overlay(sideColour, 0.85f),
        });

        _plate = new Label3D
        {
            Name = "Nameplate",
            Position = new Vector3(0f, height + 0.45f, 0f),
            Billboard = BaseMaterial3D.BillboardModeEnum.Enabled,
            NoDepthTest = true,
            FontSize = 48,
            PixelSize = 0.006f,
            Modulate = ToonLook.Bone,
            OutlineModulate = ToonLook.DarkLine,
            OutlineSize = 16,
        };
        AddChild(_plate);

        FaceHeading(unit.Heading);
        Refresh();
    }

    /// <summary>Bring the nameplate and visibility back in line with the rules state.</summary>
    public void Refresh()
    {
        _plate.Text = $"{Unit.Name}\n{Unit.Hp}/{Unit.MaxHp}";

        // A unit that has already acted is dimmed rather than hidden, because the
        // player still needs to see where it is standing.
        float fade = Unit.HasActed ? 0.45f : 1.0f;
        _plate.Modulate = new Color(ToonLook.Bone, fade);

        Visible = Unit.Active;
    }

    public void SetSelected(bool selected) => _selectionRing.Visible = selected;

    /// <summary>
    /// Walk the route the rules layer computed, tile by tile.
    /// </summary>
    /// <remarks>
    /// The path comes from <c>ReachableSet.PathTo</c> and is not recomputed here.
    /// A presentation-side path would eventually disagree with the one the movement
    /// cost was charged for, and the unit would visibly walk through a fence it
    /// paid to go around.
    /// </remarks>
    public void WalkAlong(IReadOnlyList<Coord> path)
    {
        _waypoints.Clear();
        foreach (Coord step in path)
        {
            _waypoints.Enqueue(_space.Centre(step));
        }
    }

    /// <summary>Put the unit at its rules position at once, for scripted teleports.</summary>
    public void SnapToPosition()
    {
        _waypoints.Clear();
        Position = _space.Centre(Unit.Position);
    }

    public void FaceHeading(Heading heading)
    {
        // Models face -Z as authored, which is grid north (see GridSpace). Rotating
        // about +Y turns north towards west, so east is a quarter turn negative.
        float yaw = heading switch
        {
            Heading.North => 0f,
            Heading.East => -Mathf.Pi * 0.5f,
            Heading.South => Mathf.Pi,
            Heading.West => Mathf.Pi * 0.5f,
            _ => 0f,
        };

        _body.Rotation = new Vector3(0f, yaw, 0f);
    }

    public override void _Process(double delta)
    {
        if (_waypoints.Count == 0)
        {
            return;
        }

        Vector3 target = _waypoints.Peek();
        Vector3 toTarget = target - Position;

        // Yaw only: a unit walking onto a hill should climb it, not lean back.
        var flat = new Vector3(toTarget.X, 0f, toTarget.Z);
        if (flat.LengthSquared() > 0.0001f)
        {
            _body.Rotation = new Vector3(0f, Mathf.Atan2(-flat.X, -flat.Z), 0f);
        }

        float step = WalkSpeed * (float)delta;
        if (toTarget.Length() <= step)
        {
            Position = target;
            _waypoints.Dequeue();
            if (_waypoints.Count == 0)
            {
                FaceHeading(Unit.Heading);
            }

            return;
        }

        Position += toTarget.Normalized() * step;
    }
}

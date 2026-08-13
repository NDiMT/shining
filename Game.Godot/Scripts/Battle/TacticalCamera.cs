using Godot;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// The battle camera: three-quarter from above, orbiting a pivot on the field.
/// </summary>
/// <remarks>
/// <para>
/// The camera is placed rather than animated in the editor, because the field it
/// has to frame comes from the battle file and the next battle is 20 × 20 rather
/// than 12 × 14. <see cref="Frame"/> derives the resting distance from the grid.
/// </para>
/// <para>
/// It sets the child camera's transform outright each frame instead of nesting
/// yaw and pitch nodes. Two reasons: the smoothing then has one place to happen,
/// and a focus request is a change to three numbers rather than a change to a
/// hierarchy that something else might also be writing to.
/// </para>
/// </remarks>
public sealed partial class TacticalCamera : Node3D
{
    /// <summary>
    /// Degrees above the horizon at rest.
    /// </summary>
    /// <remarks>
    /// 48°. Shallow enough that units keep a vertical silhouette — STYLE_GUIDE
    /// section 3's readable features are mostly vertical, a cape, a spear, a bow —
    /// and steep enough that the row behind is not hidden by the row in front on a
    /// 14-deep grid.
    /// </remarks>
    [Export] public float RestPitchDegrees { get; set; } = 48f;

    /// <summary>Degrees east of due south, so the view is three-quarter rather than flat on.</summary>
    [Export] public float RestYawDegrees { get; set; } = 30f;

    [Export] public float MinPitchDegrees { get; set; } = 18f;
    [Export] public float MaxPitchDegrees { get; set; } = 82f;
    [Export] public float MinDistance { get; set; } = 8f;
    [Export] public float MaxDistance { get; set; } = 70f;

    /// <summary>Metres per second of pan, and the fraction of the gap closed per second.</summary>
    [Export] public float PanSpeed { get; set; } = 16f;
    [Export] public float Smoothing { get; set; } = 12f;

    private Camera3D _camera = null!;
    private Vector3 _pivot;
    private Vector3 _pivotTarget;
    private float _yaw;
    private float _pitch;
    private float _distance = 26f;
    private float _distanceTarget = 26f;
    private bool _orbiting;

    /// <summary>The resting distance, which the outline shader uses as its reference.</summary>
    public float RestDistance { get; private set; } = 26f;

    public Camera3D Camera => _camera;

    public override void _Ready()
    {
        _camera = GetNode<Camera3D>("Camera");
        _yaw = Mathf.DegToRad(RestYawDegrees);
        _pitch = Mathf.DegToRad(RestPitchDegrees);
        ApplyTransform();
    }

    /// <summary>
    /// Sit the camera where the whole battlefield is on screen.
    /// </summary>
    /// <remarks>
    /// A heuristic, not a solved fit: the longer side of the field times 0.95,
    /// which puts a 12 × 14 grid of 2 m tiles at 26.6 m. The exact framing depends
    /// on the viewport's aspect ratio and on the camera's field of view, so this is
    /// one of the numbers to look at with the editor open rather than one to
    /// believe on paper.
    /// </remarks>
    public void Frame(GridSpace space)
    {
        RestDistance = Mathf.Clamp(
            MathF.Max(space.FieldWidth, space.FieldDepth) * 0.95f, MinDistance, MaxDistance);
        _distance = RestDistance;
        _distanceTarget = RestDistance;
        _pivot = space.FieldCentre;
        _pivotTarget = _pivot;
        ApplyTransform();
    }

    /// <summary>Slide the pivot onto a point — a focused cell, or a scripted event's camera call.</summary>
    public void FocusOn(Vector3 point) => _pivotTarget = point;

    /// <summary>Back to the opening framing, which is the reliable way out of a lost camera.</summary>
    public void ResetView(GridSpace space)
    {
        _yaw = Mathf.DegToRad(RestYawDegrees);
        _pitch = Mathf.DegToRad(RestPitchDegrees);
        _distanceTarget = RestDistance;
        _pivotTarget = space.FieldCentre;
    }

    /// <summary>Snap the orbit by a quarter turn, the way a tile-based game usually rotates.</summary>
    public void SnapYaw(int quarterTurns) => _yaw += Mathf.Pi * 0.5f * quarterTurns;

    /// <summary>
    /// A grid direction rotated into the camera's frame.
    /// </summary>
    /// <remarks>
    /// Pressing "up" has to move the cursor away from the viewer whichever way the
    /// camera is facing, or every orbit makes the keyboard controls feel inverted.
    /// The yaw is snapped to the nearest quarter turn, so the mapping is always one
    /// of four whole-tile directions rather than a diagonal.
    /// </remarks>
    public Vector2I ScreenToGrid(Vector2I screenDirection)
    {
        int quadrant = Mathf.PosMod(Mathf.RoundToInt(_yaw / (Mathf.Pi * 0.5f)), 4);
        Vector2I direction = screenDirection;
        for (int turn = 0; turn < quadrant; turn++)
        {
            // One quarter turn of the camera to the east moves screen-up onto
            // grid-west, so the pair rotates as (x, y) -> (-y, x).
            direction = new Vector2I(-direction.Y, direction.X);
        }

        return direction;
    }

    public override void _UnhandledInput(InputEvent @event)
    {
        if (@event is InputEventMouseButton button)
        {
            switch (button.ButtonIndex)
            {
                case MouseButton.WheelUp when button.Pressed:
                    _distanceTarget = Mathf.Clamp(_distanceTarget * 0.88f, MinDistance, MaxDistance);
                    break;
                case MouseButton.WheelDown when button.Pressed:
                    _distanceTarget = Mathf.Clamp(_distanceTarget / 0.88f, MinDistance, MaxDistance);
                    break;
                case MouseButton.Middle:
                    _orbiting = button.Pressed;
                    break;
            }

            return;
        }

        if (@event is InputEventMouseMotion motion && _orbiting)
        {
            _yaw -= motion.Relative.X * 0.006f;
            _pitch = Mathf.Clamp(
                _pitch + (motion.Relative.Y * 0.006f),
                Mathf.DegToRad(MinPitchDegrees),
                Mathf.DegToRad(MaxPitchDegrees));
        }
    }

    public override void _Process(double delta)
    {
        float step = (float)delta;

        // Keys are polled rather than bound through the InputMap because this
        // project has no InputMap yet; binding one is a project.godot edit that
        // should be made with the editor open rather than hand-written. Same for
        // gamepad, which brief section 26 will want.
        var pan = Vector3.Zero;
        if (Input.IsKeyPressed(Key.W))
        {
            pan.Z -= 1f;
        }

        if (Input.IsKeyPressed(Key.S))
        {
            pan.Z += 1f;
        }

        if (Input.IsKeyPressed(Key.A))
        {
            pan.X -= 1f;
        }

        if (Input.IsKeyPressed(Key.D))
        {
            pan.X += 1f;
        }

        if (pan != Vector3.Zero)
        {
            // Pan along the ground in the direction the camera is facing, not along
            // the world axes: panning "left" must mean left on screen.
            Vector3 forward = new Vector3(-Mathf.Sin(_yaw), 0f, -Mathf.Cos(_yaw)).Normalized();
            var right = new Vector3(-forward.Z, 0f, forward.X);
            _pivotTarget += ((forward * -pan.Z) + (right * pan.X)) * PanSpeed * step;
        }

        float blend = Mathf.Min(1f, Smoothing * step);
        _pivot = _pivot.Lerp(_pivotTarget, blend);
        _distance = Mathf.Lerp(_distance, _distanceTarget, blend);
        ApplyTransform();
    }

    private void ApplyTransform()
    {
        if (_camera is null)
        {
            return;
        }

        // Yaw 0 puts the camera due south of the pivot at +Z, looking north — the
        // orientation the battle files are drawn in (see GridSpace).
        var offset = new Vector3(
            Mathf.Sin(_yaw) * Mathf.Cos(_pitch),
            Mathf.Sin(_pitch),
            Mathf.Cos(_yaw) * Mathf.Cos(_pitch));

        Vector3 eye = _pivot + (offset * _distance);
        _camera.GlobalTransform = new Transform3D(Basis.Identity, eye)
            .LookingAt(_pivot, Vector3.Up);
    }
}

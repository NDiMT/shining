using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation.UI;

/// <summary>
/// The battle HUD: objective, unit information, damage preview, controls.
/// </summary>
/// <remarks>
/// <para>
/// Built in code rather than in the <c>.tscn</c>, so that the layout is one
/// readable file rather than sixty lines of serialised anchors, and so that every
/// number it shows is fetched from <c>Game.Rules</c> at the point it is displayed.
/// The HUD computes nothing: the damage preview is
/// <see cref="DamageModel.ForecastPhysical"/>, which is the same call the attack
/// itself makes, because brief section 28 requires the previewed number and the
/// dealt number to be the same number.
/// </para>
/// <para>
/// Everything is laid out with containers and spacers rather than anchor offsets.
/// Container layout is the part of Godot's UI that behaves the same at every
/// resolution without being tested at every resolution, which matters when the
/// engine cannot be run.
/// </para>
/// </remarks>
public sealed partial class BattleHud : CanvasLayer
{
    private RichTextLabel _objective = null!;
    private RichTextLabel _load = null!;
    private RichTextLabel _unit = null!;
    private RichTextLabel _controls = null!;

    public override void _Ready()
    {
        var root = new Control { Name = "Root", MouseFilter = Control.MouseFilterEnum.Ignore };
        root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        AddChild(root);

        var margins = new MarginContainer { Name = "Margins", MouseFilter = Control.MouseFilterEnum.Ignore };
        margins.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        foreach (string side in new[] { "left", "top", "right", "bottom" })
        {
            margins.AddThemeConstantOverride($"margin_{side}", 28);
        }

        root.AddChild(margins);

        var rows = new VBoxContainer { Name = "Rows", MouseFilter = Control.MouseFilterEnum.Ignore };
        margins.AddChild(rows);

        HBoxContainer top = Row(rows);
        _objective = Panel(top, 380);
        Spacer(top);
        _load = Panel(top, 360);

        var gap = new Control
        {
            Name = "Gap",
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        rows.AddChild(gap);

        HBoxContainer bottom = Row(rows);
        _unit = Panel(bottom, 400);
        Spacer(bottom);
        _controls = Panel(bottom, 300);

        _controls.Text = Controls();
        ShowUnit(null, null, null);
    }

    public void ShowBattle(BattleDefinition battle, int round)
    {
        string objectives = string.Join(
            "\n", battle.Objectives.Select(o => $"  • {o.Description ?? o.Type}"));

        _objective.Text =
            $"[b]{battle.Name}[/b]\n" +
            $"[color=#8A8F98]{battle.Grid.Width} × {battle.Grid.Height} — round {round}[/color]\n" +
            objectives;
    }

    /// <summary>The load report: what the scene actually found on disk.</summary>
    /// <remarks>
    /// On screen rather than only in the console because the answer changes every
    /// time the asset pipeline runs, and "which of these are placeholders" is the
    /// first question anyone looking at a screenshot of this scene will ask.
    /// </remarks>
    public void ShowLoadReport(int props, int propsSkipped, int modelled, int placeholders,
                               int slabsRemoved, IReadOnlyCollection<string> missing)
    {
        string missingList = missing.Count == 0
            ? string.Empty
            : "\n[color=#8A8F98]" + string.Join(", ", missing.Take(6)) +
              (missing.Count > 6 ? $", +{missing.Count - 6} more" : string.Empty) + "[/color]";

        _load.Text =
            "[b]Assets[/b]\n" +
            $"props placed {props}, skipped {propsSkipped}\n" +
            $"units modelled {modelled}, placeholder {placeholders}\n" +
            $"ground slabs removed {slabsRemoved}" +
            missingList;
    }

    /// <summary>
    /// The selected or hovered unit, with the terrain it is standing on.
    /// </summary>
    /// <remarks>
    /// Terrain defence and evasion are shown even though battle 01 does not teach
    /// them — the battle file's own comment says they are "active but not
    /// explained". Showing the number is how a player who goes looking finds it.
    /// </remarks>
    public void ShowUnit(Unit? unit, BattleGrid? grid, DamageForecast? forecast,
                         Unit? target = null, bool placeholder = false)
    {
        if (unit is null)
        {
            _unit.Text = "[color=#8A8F98]No unit selected.\nClick a unit to select it.[/color]";
            return;
        }

        TerrainType? terrain = grid?[unit.Position];
        string colour = unit.Side == Side.Enemy ? "#A83A3A" : "#3E6FB0";

        var text = new System.Text.StringBuilder();
        text.Append($"[color={colour}][b]{unit.Name}[/b][/color]  ");
        text.Append($"[color=#8A8F98]{unit.ClassName} — {unit.Side}[/color]\n");
        text.Append($"HP {unit.Hp}/{unit.MaxHp}   MP {unit.Mp}/{unit.MaxMp}\n");
        text.Append($"ATK {unit.AttackPower}  DEF {unit.Base.Defense + unit.ArmourDefense}  ");
        text.Append($"MAG {unit.MagicPower}  RES {unit.Base.Resistance}\n");
        text.Append($"AGI {unit.Base.Agility}  MOV {unit.MovementPoints}  ");
        text.Append($"{unit.Weapon?.Name ?? "unarmed"} (range {unit.WeaponRange})\n");

        if (terrain is not null)
        {
            text.Append($"[color=#8A8F98]{terrain.Name} at {unit.Position} — ");
            text.Append($"move {terrain.MoveCost}, def +{terrain.DefenseBonus}, ");
            text.Append($"eva +{terrain.EvasionBonus}%, height {terrain.Height}[/color]\n");
        }

        if (placeholder)
        {
            string file = unit.ModelPath is null ? "no model named" : Path.GetFileName(unit.ModelPath);
            text.Append($"[color=#FF00C8]placeholder mesh — {file} not generated[/color]\n");
        }

        if (forecast is { } preview && target is not null)
        {
            text.Append($"\n[b]→ {target.Name}[/b]  ");
            text.Append($"[color=#A83A3A]{preview.Damage} damage[/color]");
            text.Append(preview.Lethal ? "  [color=#D07A2C]lethal[/color]" : string.Empty);
            text.Append($"\n[color=#8A8F98]{preview.Facing} hit");
            if (preview.HeightBonus > 0)
            {
                text.Append($", +{preview.HeightBonus} height");
            }

            if (preview.TerrainDefense > 0)
            {
                text.Append($", −{preview.TerrainDefense} terrain");
            }

            if (preview.CriticalChance > 0)
            {
                text.Append($", {preview.CriticalChance}% crit for {preview.CriticalDamage}");
            }

            text.Append("[/color]");
        }

        _unit.Text = text.ToString();
    }

    public void SetStatus(string line) => _controls.Text = Controls() + "\n[color=#D8CFB8]" + line + "[/color]";

    private static string Controls() =>
        "[b]Controls[/b]\n" +
        "[color=#8A8F98]click — select / move / attack\n" +
        "arrows — cursor    tab — next unit\n" +
        "middle drag — orbit    wheel — zoom\n" +
        "WASD — pan    Q/E — turn    F — focus\n" +
        "R — reset view    space — end round[/color]";

    private static HBoxContainer Row(Node parent)
    {
        var row = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        parent.AddChild(row);
        return row;
    }

    private static void Spacer(Node parent) => parent.AddChild(new Control
    {
        SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
        MouseFilter = Control.MouseFilterEnum.Ignore,
    });

    /// <summary>A panel in the game's own dark, with a text label inside it.</summary>
    private static RichTextLabel Panel(Node parent, int width)
    {
        var style = new StyleBoxFlat
        {
            // The same near-black the terrain's base plane uses, at 85% so the
            // battlefield reads through the panel rather than being cut out of it.
            BgColor = new Color(ToonLook.DarkLine, 0.85f),
            ContentMarginLeft = 16,
            ContentMarginTop = 12,
            ContentMarginRight = 16,
            ContentMarginBottom = 12,
            CornerRadiusTopLeft = 4,
            CornerRadiusTopRight = 4,
            CornerRadiusBottomLeft = 4,
            CornerRadiusBottomRight = 4,
        };

        var panel = new PanelContainer();
        panel.AddThemeStyleboxOverride("panel", style);
        parent.AddChild(panel);

        var label = new RichTextLabel
        {
            BbcodeEnabled = true,
            FitContent = true,
            ScrollActive = false,
            CustomMinimumSize = new Vector2(width, 0),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddChild(label);
        return label;
    }
}

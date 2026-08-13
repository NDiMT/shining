using Godot;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Data;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Presentation;

/// <summary>
/// Milestone 1's proof: the engine loads the real prologue content through
/// <c>Game.Rules</c> and reports what it found.
/// </summary>
/// <remarks>
/// Deliberately small. It renders nothing and plays nothing — it answers one
/// question, which is whether the data path works end to end inside Godot:
/// Content/Data on disk, through the rules layer, to a battle a human can read.
///
/// Milestone 2 replaces the text with the tactical grid and the pipeline's real
/// models. Everything below the <c>Game.Rules</c> boundary is already tested
/// without an engine, so what has to be proven here is only the wiring.
/// </remarks>
public partial class Main : Node
{
    private RichTextLabel _output = null!;

    public override void _Ready()
    {
        _output = GetNode<RichTextLabel>("%Output");

        try
        {
            string dataRoot = ResolveDataRoot();
            Report($"[b]Content root[/b]  {dataRoot}");

            ContentDatabase content = ContentDatabase.Load(dataRoot);
            Report($"Loaded {content.Classes.Count} classes, " +
                   $"{content.Characters.Count} characters, {content.Enemies.Count} enemies, " +
                   $"{content.Weapons.Count} weapons, {content.Skills.Count} skills, " +
                   $"{content.Terrain.Count} terrain types.");

            BattleDefinition battle = BattleLoader.Load(
                Path.Combine(dataRoot, "Battles", "battle_north_meadow.json"), content);

            Report($"\n[b]{battle.Name}[/b]  {battle.Grid.Width}x{battle.Grid.Height}");
            foreach (ObjectiveDefinition objective in battle.Objectives)
            {
                Report($"  objective: {objective.Description ?? objective.Type}");
            }

            var order = new TurnOrder();
            order.BeginRound(battle.Units);
            Report("\n[b]Turn order by agility[/b]");
            foreach (string id in order.Order)
            {
                Unit unit = battle.Units.First(u => u.Id == id);
                Report($"  {unit.Name,-18} {unit.Side,-6} agi {unit.Base.Agility}  " +
                       $"hp {unit.Hp}/{unit.MaxHp}  at {unit.Position}");
            }

            Unit rowan = battle.Units.First(u => u.Id == "rowan");
            Unit raider = battle.Units.First(u => u.Id == "raider_1");
            DamageForecast forecast = DamageModel.ForecastPhysical(rowan, raider, battle.Grid);
            Report($"\nRowan would deal [b]{forecast.Damage}[/b] to a Goblin Raider " +
                   "— the number the prologue script states.");
        }
        catch (ContentException exception)
        {
            // Brief section 75: development builds fail loudly and informatively.
            Report($"\n[color=red][b]Content error[/b]\n{exception.Message}[/color]");
            GD.PushError(exception.Message);
        }
    }

    private void Report(string line)
    {
        GD.Print(line.Replace("[b]", string.Empty).Replace("[/b]", string.Empty));
        _output.AppendText(line + "\n");
    }

    /// <summary>
    /// Find Content/Data by walking up from the project directory.
    /// </summary>
    /// <remarks>
    /// Content/Data sits outside the Godot project on purpose (see
    /// ARCHITECTURE.md): it is the game's content contract, edited by humans and
    /// AI sessions and validated offline, not an engine resource. That keeps hot
    /// reload trivial and stops Godot's importer from owning the game's data.
    ///
    /// Exported builds will need the folder shipped alongside the executable;
    /// that packaging step arrives with milestone 10.
    /// </remarks>
    private static string ResolveDataRoot()
    {
        string start = ProjectSettings.GlobalizePath("res://");
        var directory = new DirectoryInfo(start);
        while (directory is not null)
        {
            string candidate = Path.Combine(directory.FullName, "Content", "Data");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new ContentException($"could not find Content/Data above {start}");
    }
}

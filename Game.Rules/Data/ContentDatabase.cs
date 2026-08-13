using System.Text.Json;
using System.Text.Json.Serialization;
using HollowCrown.Rules.Combat;
using HollowCrown.Rules.Tactical;

namespace HollowCrown.Rules.Data;

/// <summary>
/// Everything under Content/Data, loaded and cross-referenced.
/// </summary>
/// <remarks>
/// Brief section 14: content is data, and adding ten forest enemies must touch no
/// engine code. This class is the boundary — the only place that knows the JSON
/// shape. Everything above it works with <see cref="Unit"/>, <see cref="Weapon"/>
/// and <see cref="TerrainType"/>.
///
/// The same files are checked offline by <c>hollowasset validate-content</c>, so
/// broken references are caught before the game runs. This loader still fails
/// loudly rather than silently substituting defaults: brief section 75 wants
/// development builds to fail informatively.
/// </remarks>
public sealed class ContentDatabase
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };

    private ContentDatabase(
        IReadOnlyList<TerrainType> terrain,
        IReadOnlyDictionary<string, ClassDefinition> classes,
        IReadOnlyDictionary<string, CharacterDefinition> characters,
        IReadOnlyDictionary<string, CharacterDefinition> enemies,
        IReadOnlyDictionary<string, Weapon> weapons,
        IReadOnlyDictionary<string, int> armour,
        IReadOnlyDictionary<string, Skill> skills)
    {
        Terrain = terrain;
        Classes = classes;
        Characters = characters;
        Enemies = enemies;
        Weapons = weapons;
        Armour = armour;
        Skills = skills;
    }

    public IReadOnlyList<TerrainType> Terrain { get; }
    public IReadOnlyDictionary<string, ClassDefinition> Classes { get; }
    public IReadOnlyDictionary<string, CharacterDefinition> Characters { get; }
    public IReadOnlyDictionary<string, CharacterDefinition> Enemies { get; }
    public IReadOnlyDictionary<string, Weapon> Weapons { get; }
    public IReadOnlyDictionary<string, int> Armour { get; }
    public IReadOnlyDictionary<string, Skill> Skills { get; }

    public static ContentDatabase Load(string dataRoot)
    {
        var terrainFile = ReadJson<TerrainFile>(Path.Combine(dataRoot, "terrain.json"));
        var classFile = ReadJson<ClassFile>(Path.Combine(dataRoot, "classes.json"));
        var characterFile = ReadJson<CharacterFile>(Path.Combine(dataRoot, "characters.json"));
        var weaponFile = ReadJson<WeaponFile>(Path.Combine(dataRoot, "weapons.json"));
        var skillFile = ReadJson<SkillFile>(Path.Combine(dataRoot, "skills.json"));

        var terrain = terrainFile.Terrain.Select(t => new TerrainType
        {
            Id = Require(t.Id, "terrain id"),
            Symbol = Require(t.Symbol, "terrain symbol")[0],
            Name = t.Name ?? t.Id!,
            MoveCost = t.MoveCost,
            DefenseBonus = t.DefenseBonus,
            EvasionBonus = t.EvasionBonus,
            Height = t.Height,
            Blocked = t.Blocked,
            PassableBy = (IReadOnlyList<string>?)t.PassableBy ?? Array.Empty<string>(),
            BlocksLineOfSight = t.BlocksLineOfSight,
            IsExit = t.IsExit,
        }).ToList();

        var weapons = new Dictionary<string, Weapon>(StringComparer.Ordinal);
        foreach (WeaponJson w in weaponFile.Weapons ?? new List<WeaponJson>())
        {
            weapons[Require(w.Id, "weapon id")] = new Weapon
            {
                Id = w.Id!,
                Name = w.Name ?? w.Id!,
                Attack = w.Attack,
                Magic = w.Magic,
                Range = Math.Max(1, w.Range),
                Critical = w.Critical,
            };
        }

        var armour = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (WeaponJson a in weaponFile.Armour ?? new List<WeaponJson>())
        {
            armour[Require(a.Id, "armour id")] = a.Defense;
        }

        foreach (WeaponJson s in weaponFile.Shields ?? new List<WeaponJson>())
        {
            armour[Require(s.Id, "shield id")] = s.Defense;
        }

        var skills = new Dictionary<string, Skill>(StringComparer.Ordinal);
        foreach (SkillJson s in skillFile.Skills ?? new List<SkillJson>())
        {
            skills[Require(s.Id, "skill id")] = new Skill
            {
                Id = s.Id!,
                Name = s.Name ?? s.Id!,
                Cost = s.Cost,
                Range = Math.Max(1, s.Range),
                Power = s.Power,
                Element = s.Element ?? "none",
            };
        }

        var classes = new Dictionary<string, ClassDefinition>(StringComparer.Ordinal);
        foreach (ClassJson c in classFile.Classes ?? new List<ClassJson>())
        {
            classes[Require(c.Id, "class id")] = new ClassDefinition
            {
                Id = c.Id!,
                Name = c.Name ?? c.Id!,
                Movement = c.Movement,
                MovementType = c.MovementType ?? "ground",
                SkillIds = (IReadOnlyList<string>?)c.Skills ?? Array.Empty<string>(),
                Armour = c.DirectionalArmour is null
                    ? DirectionalArmour.None
                    : new DirectionalArmour(
                        c.DirectionalArmour.Front,
                        c.DirectionalArmour.Flank,
                        c.DirectionalArmour.Rear),
            };
        }

        var characters = ToDefinitions(characterFile.Characters, classes);
        var enemies = ToDefinitions(characterFile.Enemies, classes);

        return new ContentDatabase(terrain, classes, characters, enemies, weapons, armour, skills);
    }

    private static Dictionary<string, CharacterDefinition> ToDefinitions(
        List<CharacterJson>? source, IReadOnlyDictionary<string, ClassDefinition> classes)
    {
        var result = new Dictionary<string, CharacterDefinition>(StringComparer.Ordinal);
        foreach (CharacterJson c in source ?? new List<CharacterJson>())
        {
            string id = Require(c.Id, "character id");
            StatsJson stats = c.BaseStats
                ?? throw new ContentException($"character '{id}' has no baseStats");

            if (c.Class is null || !classes.ContainsKey(c.Class))
            {
                throw new ContentException(
                    $"character '{id}' has unknown class '{c.Class}'. " +
                    "Run `hollowasset validate-content` to find every broken reference at once.");
            }

            result[id] = new CharacterDefinition
            {
                Id = id,
                DisplayName = c.DisplayName ?? id,
                ClassId = c.Class,
                Level = Math.Max(1, c.Level),
                Stats = new Stats
                {
                    Hp = stats.Hp,
                    Mp = stats.Mp,
                    Attack = stats.Attack,
                    Defense = stats.Defense,
                    Magic = stats.Magic,
                    Resistance = stats.Resistance,
                    Agility = stats.Agility,
                    Movement = stats.Movement > 0 ? stats.Movement : classes[c.Class].Movement,
                },
                SkillIds = (IReadOnlyList<string>?)c.Skills ?? Array.Empty<string>(),
                ModelPath = c.Model,
                WeaponId = c.StartingEquipment?.Weapon,
                ArmourId = c.StartingEquipment?.Armour,
                Ai = c.Ai ?? "aggressive_melee",
                IsBoss = c.IsBoss,
                Xp = c.Xp,
            };
        }

        return result;
    }

    /// <summary>Instantiate a battle-ready unit from a definition.</summary>
    public Unit Spawn(string definitionId, Side side, Coord at, string? instanceId = null)
    {
        CharacterDefinition definition =
            Characters.TryGetValue(definitionId, out CharacterDefinition? c) ? c
            : Enemies.TryGetValue(definitionId, out CharacterDefinition? e) ? e
            : throw new ContentException(
                $"no character or enemy definition '{definitionId}' in characters.json");

        ClassDefinition klass = Classes[definition.ClassId];

        var skills = new List<Skill>();
        foreach (string skillId in definition.SkillIds.Concat(klass.SkillIds).Distinct(StringComparer.Ordinal))
        {
            if (!Skills.TryGetValue(skillId, out Skill? skill))
            {
                throw new ContentException($"'{definitionId}' references unknown skill '{skillId}'");
            }

            skills.Add(skill);
        }

        var unit = new Unit
        {
            Id = instanceId ?? definitionId,
            Name = definition.DisplayName,
            Side = side,
            Base = definition.Stats,
            Armour = klass.Armour,
            Skills = skills,
            ClassId = klass.Id,
            ClassName = klass.Name,
            ModelPath = definition.ModelPath,
            MovementType = klass.MovementType,
            AiBehaviour = definition.Ai,
            IsBoss = definition.IsBoss,
            Position = at,
        };

        if (definition.WeaponId is not null)
        {
            if (!Weapons.TryGetValue(definition.WeaponId, out Weapon? weapon))
            {
                throw new ContentException(
                    $"'{definitionId}' equips unknown weapon '{definition.WeaponId}'");
            }

            unit.Weapon = weapon;
        }

        if (definition.ArmourId is not null)
        {
            if (!Armour.TryGetValue(definition.ArmourId, out int defense))
            {
                throw new ContentException(
                    $"'{definitionId}' equips unknown armour '{definition.ArmourId}'");
            }

            unit.ArmourDefense = defense;
        }

        unit.Hp = unit.MaxHp;
        unit.Mp = unit.MaxMp;
        return unit;
    }

    private static T ReadJson<T>(string path)
    {
        if (!File.Exists(path))
        {
            throw new ContentException($"missing data file: {path}");
        }

        try
        {
            using FileStream stream = File.OpenRead(path);
            return JsonSerializer.Deserialize<T>(stream, JsonOptions)
                   ?? throw new ContentException($"{path} deserialised to null");
        }
        catch (JsonException exception)
        {
            throw new ContentException($"{path}: {exception.Message}", exception);
        }
    }

    private static string Require(string? value, string what) =>
        string.IsNullOrWhiteSpace(value)
            ? throw new ContentException($"missing {what}")
            : value;
}

public sealed class ContentException : Exception
{
    public ContentException(string message) : base(message)
    {
    }

    public ContentException(string message, Exception inner) : base(message, inner)
    {
    }
}

public sealed record ClassDefinition
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public int Movement { get; init; } = 5;
    public string MovementType { get; init; } = "ground";
    public IReadOnlyList<string> SkillIds { get; init; } = Array.Empty<string>();
    public DirectionalArmour Armour { get; init; } = DirectionalArmour.None;
}

public sealed record CharacterDefinition
{
    public required string Id { get; init; }
    public required string DisplayName { get; init; }
    public required string ClassId { get; init; }
    public int Level { get; init; } = 1;
    public required Stats Stats { get; init; }
    public IReadOnlyList<string> SkillIds { get; init; } = Array.Empty<string>();

    /// <summary>Repository-relative model path, as written in characters.json.</summary>
    public string? ModelPath { get; init; }
    public string? WeaponId { get; init; }
    public string? ArmourId { get; init; }
    public string Ai { get; init; } = "aggressive_melee";
    public bool IsBoss { get; init; }
    public int Xp { get; init; }
}

// ---------------------------------------------------------------------------
// JSON shapes. Deliberately dumb mirrors of the files; all validation and
// defaulting happens above so these stay easy to diff against the data.
// ---------------------------------------------------------------------------

internal sealed class TerrainFile
{
    public List<TerrainJson> Terrain { get; set; } = new();
}

internal sealed class TerrainJson
{
    public string? Id { get; set; }
    public string? Symbol { get; set; }
    public string? Name { get; set; }
    [JsonPropertyName("move_cost")] public int MoveCost { get; set; } = 1;
    [JsonPropertyName("defense_bonus")] public int DefenseBonus { get; set; }
    [JsonPropertyName("evasion_bonus")] public int EvasionBonus { get; set; }
    public int Height { get; set; }
    public bool Blocked { get; set; }
    [JsonPropertyName("passable_by")] public List<string>? PassableBy { get; set; }
    [JsonPropertyName("blocks_line_of_sight")] public bool BlocksLineOfSight { get; set; }
    [JsonPropertyName("is_exit")] public bool IsExit { get; set; }
}

internal sealed class ClassFile
{
    public List<ClassJson>? Classes { get; set; }
}

internal sealed class ClassJson
{
    public string? Id { get; set; }
    public string? Name { get; set; }
    public int Movement { get; set; } = 5;
    [JsonPropertyName("movement_type")] public string? MovementType { get; set; }
    public List<string>? Skills { get; set; }
    [JsonPropertyName("directional_armour")] public DirectionalArmourJson? DirectionalArmour { get; set; }
}

internal sealed class DirectionalArmourJson
{
    public int Front { get; set; }
    public int Flank { get; set; }
    public int Rear { get; set; }
}

internal sealed class CharacterFile
{
    public List<CharacterJson>? Characters { get; set; }
    public List<CharacterJson>? Enemies { get; set; }
}

internal sealed class CharacterJson
{
    public string? Id { get; set; }
    public string? DisplayName { get; set; }
    public string? Class { get; set; }
    public int Level { get; set; } = 1;
    public StatsJson? BaseStats { get; set; }
    public string? Model { get; set; }
    public List<string>? Skills { get; set; }
    public EquipmentJson? StartingEquipment { get; set; }
    public string? Ai { get; set; }
    public bool IsBoss { get; set; }
    public int Xp { get; set; }
}

internal sealed class StatsJson
{
    public int Hp { get; set; }
    public int Mp { get; set; }
    public int Attack { get; set; }
    public int Defense { get; set; }
    public int Magic { get; set; }
    public int Resistance { get; set; }
    public int Agility { get; set; }
    public int Movement { get; set; }
}

internal sealed class EquipmentJson
{
    public string? Weapon { get; set; }
    public string? Armour { get; set; }
    public string? Accessory { get; set; }
}

internal sealed class WeaponFile
{
    public List<WeaponJson>? Weapons { get; set; }
    public List<WeaponJson>? Armour { get; set; }
    public List<WeaponJson>? Shields { get; set; }
}

internal sealed class WeaponJson
{
    public string? Id { get; set; }
    public string? Name { get; set; }
    public int Attack { get; set; }
    public int Magic { get; set; }
    public int Defense { get; set; }
    public int Range { get; set; } = 1;
    public int Critical { get; set; }
}

internal sealed class SkillFile
{
    public List<SkillJson>? Skills { get; set; }
}

internal sealed class SkillJson
{
    public string? Id { get; set; }
    public string? Name { get; set; }
    public int Cost { get; set; }
    public int Range { get; set; } = 1;
    public int Power { get; set; }
    public string? Element { get; set; }
}

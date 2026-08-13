using Godot;
using HollowCrown.Presentation.Look;
using HollowCrown.Rules.Combat;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// The stand-in for a character whose GLB has not been generated yet.
/// </summary>
/// <remarks>
/// <para>
/// Every unit in the North Meadow battle uses one today: characters.json names a
/// model for all ten of them and none of those files exist — the only generated
/// character is <c>npc_guard_greenvale</c>, who is not in this battle.
/// </para>
/// <para>
/// It is built to be <b>obviously</b> a placeholder and still useful. Obvious,
/// because the base ring is a colour that appears in no palette in STYLE_GUIDE.md,
/// so a screenshot can never be mistaken for finished art. Useful, because it
/// carries the two properties the tactical camera actually reads at distance:
/// the class silhouette family from STYLE_GUIDE.md section 3 — cape, spear,
/// sleeves, bow — and the one dominant hue per character from section 2. That
/// makes the scene testable as a scene: if twelve of these cannot be told apart at
/// tactical distance, twelve finished models with the same silhouettes will not be
/// either, and that is worth learning before the meshes are paid for.
/// </para>
/// </remarks>
public static class PlaceholderUnit
{
    /// <summary>
    /// Heads tall, from ANIME_DIRECTION.md rule 4: "a hero is about six and a half
    /// heads tall rather than eight". The head size is derived from the height
    /// rather than chosen, so the proportion rule survives any height change.
    /// </summary>
    private const float HeadsTall = 6.5f;

    /// <summary>
    /// Metres. Rule 4 again: "heights do not change — a hero is still 1.7m, because
    /// the tactical grid, the movement costs and the camera all depend on it".
    /// </summary>
    public const float HeroHeight = 1.7f;

    public static float HeightFor(string classId) => classId switch
    {
        // Placeholder judgements, not content: only the 1.7 m human is fixed by the
        // spec. When the real meshes arrive their own heights win.
        "goblin_raider" or "goblin_spearman" or "goblin_archer" => 1.35f,
        "aberration" => 2.6f,
        _ => HeroHeight,
    };

    public static Node3D Build(Unit unit, string definitionId, ToonLook look)
    {
        float height = HeightFor(unit.ClassId);
        float head = height / HeadsTall;
        Color hue = ToonLook.CharacterHue(unit.Id, definitionId);

        var root = new Node3D { Name = $"Placeholder_{unit.Id}" };

        // Body: a capsule from the ankles to the neck. Wide enough to read as a
        // mass at tactical distance, which section 89 of the brief asks for and
        // section 3 of the style guide restates as silhouette families.
        float bodyHeight = height - head;
        float radius = height * 0.16f;
        root.AddChild(new MeshInstance3D
        {
            Name = "Body",
            Mesh = new CapsuleMesh { Radius = radius, Height = bodyHeight },
            Position = new Vector3(0f, bodyHeight * 0.5f, 0f),
            MaterialOverride = look.Flat(hue),
        });

        root.AddChild(new MeshInstance3D
        {
            Name = "Head",
            Mesh = new SphereMesh { Radius = head * 0.5f, Height = head },
            Position = new Vector3(0f, height - (head * 0.5f), 0f),
            MaterialOverride = look.Flat(hue.Lightened(0.25f)),
        });

        AddClassCue(root, unit.ClassId, height, radius, hue, look);

        // The marker. Flat on the ground so it is visible from the tactical camera
        // and never hidden behind the unit it belongs to.
        root.AddChild(new MeshInstance3D
        {
            Name = "MissingModelRing",
            Mesh = new TorusMesh { InnerRadius = radius * 1.5f, OuterRadius = radius * 1.9f },
            Position = new Vector3(0f, 0.03f, 0f),
            MaterialOverride = look.Flat(ToonLook.MissingAssetMarker, outlined: false),
        });

        return root;
    }

    /// <summary>
    /// One readable feature per class, from STYLE_GUIDE.md section 3's table.
    /// </summary>
    /// <remarks>
    /// One, not several. The style guide's readability test covers the face and
    /// asks whether the class is still nameable, and a silhouette with three cues
    /// fails it as surely as one with none — it becomes a blob of detail.
    /// </remarks>
    private static void AddClassCue(
        Node3D root, string classId, float height, float radius, Color hue, ToonLook look)
    {
        Color iron = new("7A8189");       // shared neutral, STYLE_GUIDE section 2

        switch (classId)
        {
            case "swordsman":
                // Cape and a single pauldron. The cape is the readable half.
                root.AddChild(new MeshInstance3D
                {
                    Name = "Cape",
                    Mesh = new BoxMesh { Size = new Vector3(radius * 2.1f, height * 0.5f, 0.06f) },
                    Position = new Vector3(0f, height * 0.45f, radius * 0.9f),
                    MaterialOverride = look.Flat(hue.Darkened(0.25f)),
                });
                break;

            case "soldier":
            case "goblin_spearman":
                // The spear that teaches weapon range in battle 01: reach 2.
                root.AddChild(new MeshInstance3D
                {
                    Name = "Spear",
                    Mesh = new CylinderMesh
                    {
                        TopRadius = 0.03f,
                        BottomRadius = 0.03f,
                        Height = height * 1.25f,
                    },
                    Position = new Vector3(radius * 1.3f, height * 0.62f, 0f),
                    MaterialOverride = look.Flat(iron),
                });
                break;

            case "apprentice_mage":
                // Sleeve mass and a tapering robe.
                root.AddChild(new MeshInstance3D
                {
                    Name = "Robe",
                    Mesh = new CylinderMesh
                    {
                        TopRadius = radius * 0.9f,
                        BottomRadius = radius * 1.8f,
                        Height = height * 0.5f,
                    },
                    Position = new Vector3(0f, height * 0.25f, 0f),
                    MaterialOverride = look.Flat(hue.Darkened(0.2f)),
                });
                break;

            case "goblin_archer":
                // Bow arc, stood on edge so the arc is the silhouette.
                var bow = new MeshInstance3D
                {
                    Name = "Bow",
                    Mesh = new TorusMesh { InnerRadius = height * 0.28f, OuterRadius = height * 0.32f },
                    Position = new Vector3(radius * 1.4f, height * 0.6f, 0f),
                    MaterialOverride = look.Flat(ToonLook.GoblinAccent),
                };
                bow.RotateZ(Mathf.Pi * 0.5f);
                root.AddChild(bow);
                break;

            case "aberration":
                // A boss gets one element no rank-and-file unit has. Horns.
                for (int side = -1; side <= 1; side += 2)
                {
                    root.AddChild(new MeshInstance3D
                    {
                        Name = $"Horn{side}",
                        Mesh = new PrismMesh { Size = new Vector3(0.12f, height * 0.3f, 0.12f) },
                        Position = new Vector3(side * radius * 0.6f, height * 1.02f, 0f),
                        MaterialOverride = look.Flat(new Color("E0C07A")),   // pale gold
                    });
                }

                break;

            default:
                // Guards, officers, goblin raiders: a round shield.
                var shield = new MeshInstance3D
                {
                    Name = "Shield",
                    Mesh = new CylinderMesh
                    {
                        TopRadius = height * 0.16f,
                        BottomRadius = height * 0.16f,
                        Height = 0.05f,
                    },
                    Position = new Vector3(-radius * 1.2f, height * 0.55f, 0f),
                    MaterialOverride = look.Flat(iron),
                };
                shield.RotateZ(Mathf.Pi * 0.5f);
                root.AddChild(shield);
                break;
        }
    }
}

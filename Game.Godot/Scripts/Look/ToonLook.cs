using Godot;

namespace HollowCrown.Presentation.Look;

/// <summary>
/// The tunable half of the anime look, in one place.
/// </summary>
/// <remarks>
/// ANIME_DIRECTION.md rule 1 asks for the band count and thresholds to be
/// adjustable without editing code. The shaders declare them as uniforms, which
/// makes them adjustable without editing <i>C#</i>; this record carries them from
/// <c>[Export]</c> properties on the battle scene, which makes them adjustable
/// without editing anything at all — the inspector, with the game running.
///
/// The defaults here are the shader defaults repeated. That duplication is
/// deliberate: a look tuned in the inspector has to be written back somewhere, and
/// two obvious places beat one hidden one.
/// </remarks>
public readonly record struct ToonSettings
{
    /// <summary>Bands on characters and props. Three is the spec's default.</summary>
    public int Bands { get; init; } = 3;

    /// <summary>
    /// Bands on terrain. Four, because a 24 × 28 m ground surface lit by one
    /// directional light barely varies in N·L, and two bands across it read as a
    /// sheet of flat colour rather than as ground.
    /// </summary>
    public int GroundBands { get; init; } = 4;

    public float Terminator { get; init; } = 0.42f;
    public float MidEdge { get; init; } = 0.70f;
    public float RimEdge { get; init; } = 0.88f;
    public float ShadowLevel { get; init; } = 0.42f;
    public float RimLevel { get; init; } = 1.30f;

    /// <summary>See the toon shader's note: the one knob for overall brightness.</summary>
    public float LightGain { get; init; } = 1.0f;

    public float OutlineWidthMetres { get; init; } = 0.05f;
    public float OutlineDistanceFalloff { get; init; } = 0.55f;
    public float OutlineMinPixels { get; init; } = 1.5f;
    public float OutlineMaxPixels { get; init; } = 5.0f;

    public ToonSettings()
    {
    }
}

/// <summary>
/// The one place that builds anime-look materials, and the one place that holds
/// the palette.
/// </summary>
/// <remarks>
/// <para>
/// Materials are built in code rather than saved as <c>.tres</c> files because
/// every one of them is derived: a terrain material is the toon shader plus a
/// colour from a table, a unit material is the toon shader plus a hue from
/// STYLE_GUIDE.md section 2. Hand-maintaining thirty resource files that differ by
/// one colour is how a palette drifts.
/// </para>
/// <para>
/// Rules 1 and 2 of ANIME_DIRECTION.md live in the two shaders. This class only
/// decides which colours go through them, and it caches by colour so a hundred
/// grass tiles share one material and one shader compilation.
/// </para>
/// </remarks>
public sealed class ToonLook
{
    public const string ToonShaderPath = "res://Shaders/toon.gdshader";
    public const string OutlineShaderPath = "res://Shaders/outline.gdshader";

    // ---------------------------------------------------------------------
    // Palette. Terrain hues are chosen for rule 5 — neighbouring materials get
    // different HUES, not different shades of one — which is why forest is a
    // blue-green against grass's yellow-green rather than simply darker. Cel
    // shading collapses value range by design, so value cannot do this work.
    // Neutrals marked below are STYLE_GUIDE.md section 2's shared set.
    // ---------------------------------------------------------------------
    private static readonly Dictionary<string, Color> TerrainColours = new()
    {
        ["grass"] = new Color("6FA34B"),
        ["path"] = new Color("C2A26B"),
        ["forest"] = new Color("35704F"),
        ["rock"] = new Color("8A8F98"),
        ["hill"] = new Color("A8873F"),
        ["fence"] = new Color("6B4F3A"),      // leather neutral
        ["rubble"] = new Color("7A6E60"),
        ["wall"] = new Color("7A8189"),       // iron neutral
        ["obstacle"] = new Color("8E5A34"),
        ["exit"] = new Color("3A8A8A"),       // teal: reads as a way out
    };

    /// <summary>Accent hue per character, from STYLE_GUIDE.md section 2.</summary>
    /// <remarks>
    /// Tomas is not in the published table — the two unclaimed hues nearest his
    /// role are ochre and teal — so he is tinted ochre <b>for the placeholder mesh
    /// only</b>. STYLE_GUIDE.md owns the real assignment and this must follow it
    /// once his model exists; the rule that matters here is the one it does obey,
    /// that no two characters in a party share a hue.
    /// </remarks>
    private static readonly Dictionary<string, Color> CharacterHues = new()
    {
        ["rowan"] = new Color("3E6FB0"),      // tabard blue
        ["maeve"] = new Color("6B4E9E"),      // violet
        ["tomas"] = new Color("C08A3E"),      // ochre, unclaimed
        ["aldric"] = new Color("A83A3A"),     // deep red
        ["varric"] = new Color("A83A3A"),
    };

    /// <summary>Faction primaries, from STYLE_GUIDE.md section 2.</summary>
    private static readonly Dictionary<string, Color> FactionColours = new()
    {
        ["goblin"] = new Color("7C9B4E"),     // sickly green
        ["vaelor"] = new Color("5A6472"),     // cold steel
        ["fragment"] = new Color("3A2C4E"),   // void violet
    };

    public static readonly Color GoblinAccent = new("8E4430");    // rust red
    public static readonly Color DarkLine = new("2A2620");
    public static readonly Color Bone = new("D8CFB8");
    public static readonly Color MoveHighlight = new("3E6FB0");
    public static readonly Color AttackHighlight = new("A83A3A");
    public static readonly Color ThreatHighlight = new("D07A2C");  // ember orange

    /// <summary>
    /// The colour a placeholder is marked with. Deliberately outside every palette
    /// in STYLE_GUIDE.md so that "this asset does not exist yet" can never be
    /// mistaken for an art decision in a screenshot.
    /// </summary>
    public static readonly Color MissingAssetMarker = new("FF00C8");

    private readonly Shader _toon;
    private readonly Shader _outline;
    private readonly Dictionary<string, ShaderMaterial> _cache = new();

    public ToonLook(float cameraReferenceDistance, ToonSettings settings)
    {
        _toon = GD.Load<Shader>(ToonShaderPath);
        _outline = GD.Load<Shader>(OutlineShaderPath);
        CameraReferenceDistance = cameraReferenceDistance;
        Settings = settings;
    }

    public ToonSettings Settings { get; }

    /// <summary>
    /// The distance the outline shader treats as its reference, in metres. Fed
    /// from the camera's resting distance so the tuned pixel width is the width
    /// seen at the angle the game is actually played from.
    /// </summary>
    public float CameraReferenceDistance { get; }

    public static Color TerrainColour(string terrainId) =>
        TerrainColours.TryGetValue(terrainId, out Color colour)
            ? colour
            // An unknown terrain type must be visible as unknown rather than
            // silently grey: terrain.json can gain entries without touching code.
            : MissingAssetMarker;

    public static Color CharacterHue(string unitId, string definitionId)
    {
        if (CharacterHues.TryGetValue(unitId, out Color colour))
        {
            return colour;
        }

        if (definitionId.StartsWith("goblin", StringComparison.Ordinal))
        {
            return FactionColours["goblin"];
        }

        return FactionColours.TryGetValue(definitionId, out Color faction)
            ? faction
            : Bone;
    }

    /// <summary>
    /// A flat-colour toon material with the outline hull attached, cached by colour.
    /// </summary>
    public ShaderMaterial Flat(Color colour, bool outlined = true, bool ground = false)
    {
        string key = $"{colour.ToHtml(true)}|{outlined}|{ground}";
        if (_cache.TryGetValue(key, out ShaderMaterial? cached))
        {
            return cached;
        }

        var material = new ShaderMaterial { Shader = _toon };
        material.SetShaderParameter("albedo_colour", colour);
        material.SetShaderParameter("use_albedo_texture", false);
        ApplyRamp(material, ground ? Settings.GroundBands : Settings.Bands);
        if (outlined)
        {
            material.NextPass = Outline();
        }

        _cache[key] = material;
        return material;
    }

    private void ApplyRamp(ShaderMaterial material, int bands)
    {
        material.SetShaderParameter("band_count", bands);
        material.SetShaderParameter("terminator", Settings.Terminator);
        material.SetShaderParameter("mid_edge", Settings.MidEdge);
        material.SetShaderParameter("rim_edge", Settings.RimEdge);
        material.SetShaderParameter("shadow_level", Settings.ShadowLevel);
        material.SetShaderParameter("rim_level", Settings.RimLevel);
        material.SetShaderParameter("light_gain", Settings.LightGain);
    }

    /// <summary>
    /// A toon material that keeps an imported mesh's own albedo map.
    /// </summary>
    /// <remarks>
    /// Rule 3 makes this the right default for generated assets: their textures
    /// carry hue and material and no lighting, which is exactly what the toon ramp
    /// wants underneath it. Throwing the map away and flat-colouring the mesh would
    /// discard the painted detail the style guide asks the generator for.
    /// </remarks>
    public ShaderMaterial Textured(Texture2D? albedo, Color tint)
    {
        var material = new ShaderMaterial { Shader = _toon };
        material.SetShaderParameter("albedo_colour", tint);
        material.SetShaderParameter("use_albedo_texture", albedo is not null);
        if (albedo is not null)
        {
            material.SetShaderParameter("albedo_texture", albedo);
        }

        ApplyRamp(material, Settings.Bands);
        material.NextPass = Outline();
        return material;
    }

    /// <summary>The inverted-hull pass. A fresh instance per material: it is the
    /// <c>next_pass</c> of exactly one material and sharing it across materials
    /// makes a later per-object width tweak impossible.</summary>
    public ShaderMaterial Outline()
    {
        var material = new ShaderMaterial { Shader = _outline };
        material.SetShaderParameter("outline_colour", DarkLine);
        material.SetShaderParameter("reference_distance", CameraReferenceDistance);
        material.SetShaderParameter("width_metres", Settings.OutlineWidthMetres);
        material.SetShaderParameter("distance_falloff", Settings.OutlineDistanceFalloff);
        material.SetShaderParameter("min_pixels", Settings.OutlineMinPixels);
        material.SetShaderParameter("max_pixels", Settings.OutlineMaxPixels);
        return material;
    }

    /// <summary>
    /// A flat unshaded translucent material for the tile overlays.
    /// </summary>
    /// <remarks>
    /// Not the toon shader: a movement highlight is a UI element lying on the
    /// ground, and shading it would make the same overlay read as two different
    /// colours depending on which side of the terminator the tile under it fell.
    /// </remarks>
    public static StandardMaterial3D Overlay(Color colour, float alpha)
    {
        return new StandardMaterial3D
        {
            AlbedoColor = new Color(colour, alpha),
            ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
            Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
            CullMode = BaseMaterial3D.CullModeEnum.Disabled,
            // Overlays sit 2 cm above the tile top, which is enough to avoid
            // z-fighting but not enough to survive a unit standing on the tile;
            // depth writing off keeps them from occluding each other.
            NoDepthTest = false,
            DepthDrawMode = BaseMaterial3D.DepthDrawModeEnum.Disabled,
        };
    }
}

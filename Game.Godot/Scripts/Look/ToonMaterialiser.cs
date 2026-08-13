using Godot;

namespace HollowCrown.Presentation.Look;

/// <summary>
/// Puts every mesh of an imported model under the anime shaders.
/// </summary>
/// <remarks>
/// <para>
/// A GLB arrives carrying <c>StandardMaterial3D</c>s with PBR inputs. Left alone
/// they would be lit by Godot's default shading, which is a smooth gradient — the
/// exact thing ANIME_DIRECTION.md rule 1 exists to remove, and it would sit next
/// to correctly cel-shaded terrain in the same frame.
/// </para>
/// <para>
/// The albedo map is kept and everything else is dropped. That is rule 3 read
/// forwards: the texture carries hue and material and no lighting, so it is the
/// right input to the ramp, while the metallic, roughness and normal maps are
/// listed in the spec's ban table as costing texture memory for nothing under cel
/// shading.
/// </para>
/// </remarks>
public static class ToonMaterialiser
{
    /// <summary>
    /// Re-materialise every surface under <paramref name="model"/>.
    /// </summary>
    /// <param name="tint">
    /// Multiplied into the albedo. White leaves a textured asset as authored;
    /// a faction colour is how one guard mesh becomes a whole squad, which the
    /// provenance record for <c>npc_guard_greenvale</c> explicitly plans for.
    /// </param>
    public static void Apply(Node model, ToonLook look, Color? tint = null)
    {
        Color multiply = tint ?? Colors.White;

        if (model is MeshInstance3D instance && instance.Mesh is not null)
        {
            for (int surface = 0; surface < instance.Mesh.GetSurfaceCount(); surface++)
            {
                Texture2D? albedo = null;
                if (instance.GetActiveMaterial(surface) is BaseMaterial3D existing)
                {
                    albedo = existing.AlbedoTexture;
                }

                instance.SetSurfaceOverrideMaterial(surface, look.Textured(albedo, multiply));
            }
        }

        foreach (Node child in model.GetChildren())
        {
            Apply(child, look, tint);
        }
    }
}

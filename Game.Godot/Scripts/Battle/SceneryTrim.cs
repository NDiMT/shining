using Godot;

namespace HollowCrown.Presentation.Battle;

/// <summary>What was found, and what was done about it, when a model was measured.</summary>
public readonly record struct TrimReport(
    string AssetId,
    float FootprintMetres,
    float HeightMetres,
    int SlabsRemoved,
    bool OversizedAfterTrim)
{
    public bool WorthReporting => SlabsRemoved > 0 || OversizedAfterTrim;
}

/// <summary>
/// Measures an imported model and strips the ground it arrived standing on.
/// </summary>
/// <remarks>
/// <para>
/// docs/ASSET_PIPELINE.md records the problem in measurements:
/// <c>building_house_small_a</c> came back on a 7.79 × 7.79 m ground slab with two
/// bonus trees, <c>prop_barrel_a</c> surrounded by grass tufts and pebbles across
/// 32 extra mesh islands, <c>veg_tree_oak_a</c> on a grass disc — and all three had
/// "ground plane" and "scenery around the object" in the avoid clause at generation
/// time. Avoid tokens do not stop it.
/// </para>
/// <para>
/// The scene must not silently accept that. A 7.79 m slab is nearly four tiles
/// wide on a 2 m grid, so a house dropped on the North Meadow field would carpet
/// the battlefield in a second, subtly different, ground surface — and the terrain
/// underneath would go on costing 1 movement point, so it would look like terrain
/// and behave like nothing. That is worse than an obviously missing model.
/// </para>
/// <para>
/// <b>What this can and cannot fix.</b> It removes whole mesh <i>nodes</i> that
/// measure like a ground slab. It cannot fix <c>veg_tree_oak_a</c>, whose grass
/// disc is fused to the trunk in a single island — the pipeline doc says the same
/// thing, that a fused disc needs Blender or a better prompt. So a model that is
/// still oversized after trimming is reported rather than mangled: the honest
/// outcome is a loud line in the log naming the measurement, not a heuristic that
/// deletes half a tree.
/// </para>
/// </remarks>
public static class SceneryTrim
{
    /// <summary>Thickest a mesh can be and still be called a slab.</summary>
    /// <remarks>
    /// 25 cm. The house's slab measured 56 triangles across 7.79 m, so it is
    /// essentially a plane; a quarter of a metre leaves room for a slightly domed
    /// disc without reaching anything that could be a wall, a step or a cart bed.
    /// </remarks>
    private const float SlabMaxHeight = 0.25f;

    /// <summary>How far above the model's base a slab may sit and still be its base.</summary>
    private const float SlabBaseTolerance = 0.25f;

    /// <summary>
    /// Measure <paramref name="model"/>, remove any ground slabs, and report.
    /// </summary>
    /// <param name="tileSize">Metres per grid tile — what "too wide" is measured against.</param>
    /// <param name="trim">
    /// False measures and reports without changing the model, which is what to use
    /// the first time a newly generated asset is looked at.
    /// </param>
    public static TrimReport Measure(Node3D model, string assetId, float tileSize, bool trim = true)
    {
        var meshes = new List<MeshInstance3D>();
        Collect(model, model, Transform3D.Identity, meshes, out var boxes);

        if (meshes.Count == 0)
        {
            return new TrimReport(assetId, 0f, 0f, 0, false);
        }

        Aabb whole = boxes[0];
        for (int i = 1; i < boxes.Count; i++)
        {
            whole = whole.Merge(boxes[i]);
        }

        int removed = 0;
        for (int i = 0; i < meshes.Count; i++)
        {
            if (!IsGroundSlab(boxes[i], whole, tileSize))
            {
                continue;
            }

            GD.PushWarning(
                $"{assetId}: removing a {boxes[i].Size.X:0.0} x {boxes[i].Size.Z:0.0} m ground " +
                $"slab ('{meshes[i].Name}'). Generated assets arrive with scenery attached — " +
                "see docs/ASSET_PIPELINE.md. The grid draws the ground here.");

            removed++;
            if (trim)
            {
                meshes[i].QueueFree();
            }
        }

        // Recompute the footprint over what survives, so the oversize warning is
        // about the subject rather than about the slab that was just removed.
        Aabb remaining = default;
        bool any = false;
        for (int i = 0; i < meshes.Count; i++)
        {
            if (trim && IsGroundSlab(boxes[i], whole, tileSize))
            {
                continue;
            }

            remaining = any ? remaining.Merge(boxes[i]) : boxes[i];
            any = true;
        }

        float footprint = any ? MathF.Max(remaining.Size.X, remaining.Size.Z) : 0f;
        bool oversized = footprint > tileSize * 1.5f;
        if (oversized)
        {
            GD.PushWarning(
                $"{assetId}: still {footprint:0.0} m across after trimming, against a " +
                $"{tileSize:0.0} m tile. If that is fused scenery it cannot be fixed in " +
                "engine — docs/ASSET_PIPELINE.md, veg_tree_oak_a's grass disc is the known case.");
        }

        return new TrimReport(assetId, footprint, any ? remaining.Size.Y : 0f, removed, oversized);
    }

    private static bool IsGroundSlab(Aabb box, Aabb whole, float tileSize)
    {
        bool thin = box.Size.Y <= SlabMaxHeight;
        bool wide = MathF.Max(box.Size.X, box.Size.Z) >= tileSize * 1.5f;
        bool atTheBase = box.Position.Y <= whole.Position.Y + SlabBaseTolerance;
        return thin && wide && atTheBase;
    }

    /// <summary>
    /// Gather every mesh under <paramref name="node"/> with its bounds expressed in
    /// the model root's space.
    /// </summary>
    /// <remarks>
    /// Transforms are accumulated by hand rather than read from
    /// <c>GlobalTransform</c> so a model can be measured before it is added to the
    /// scene tree — which is when it should be measured, so a slab is never on
    /// screen even for one frame.
    /// </remarks>
    private static void Collect(
        Node node, Node3D root, Transform3D accumulated,
        List<MeshInstance3D> meshes, out List<Aabb> boxes)
    {
        boxes = new List<Aabb>();
        Walk(node, root, accumulated, meshes, boxes);
    }

    private static void Walk(
        Node node, Node3D root, Transform3D accumulated,
        List<MeshInstance3D> meshes, List<Aabb> boxes)
    {
        Transform3D here = accumulated;
        if (node is Node3D spatial && !ReferenceEquals(node, root))
        {
            here = accumulated * spatial.Transform;
        }

        if (node is MeshInstance3D mesh && mesh.Mesh is not null)
        {
            meshes.Add(mesh);
            boxes.Add(Transform(here, mesh.Mesh.GetAabb()));
        }

        foreach (Node child in node.GetChildren())
        {
            Walk(child, root, here, meshes, boxes);
        }
    }

    /// <summary>
    /// An AABB through a transform, by its eight corners.
    /// </summary>
    /// <remarks>
    /// Rotating a box makes its axis-aligned bounds grow, so transforming only the
    /// position and size would under-measure any model whose slab is not axis
    /// aligned — which is the case the moment a prop carries a rotation.
    /// </remarks>
    private static Aabb Transform(Transform3D transform, Aabb box)
    {
        Vector3 min = box.Position;
        Vector3 size = box.Size;
        var result = new Aabb(transform * min, Vector3.Zero);

        for (int corner = 1; corner < 8; corner++)
        {
            var offset = new Vector3(
                (corner & 1) != 0 ? size.X : 0f,
                (corner & 2) != 0 ? size.Y : 0f,
                (corner & 4) != 0 ? size.Z : 0f);
            result = result.Expand(transform * (min + offset));
        }

        return result;
    }
}

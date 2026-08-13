using Godot;

namespace HollowCrown.Presentation.Battle;

/// <summary>
/// Finds and loads the generated GLBs under <c>Content/Models</c>.
/// </summary>
/// <remarks>
/// <para>
/// <b>Why runtime glTF rather than the editor importer.</b> <c>Content/</c> is
/// outside the Godot project by design (ARCHITECTURE.md), and Godot cannot
/// reference a path above <c>res://</c>, so the models are parsed at load with
/// <see cref="GltfDocument"/> instead of being imported. The cost is real: no
/// import-time compression, no LOD generation, and parsing on the loading screen
/// rather than at build time. The benefit is that the content contract stays one
/// tree that the Python tooling and the engine both read, and that a regenerated
/// asset appears without an import step. If load times become a problem the fix is
/// a build step that copies <c>Content/Models</c> into <c>res://</c>, not moving
/// the content.
/// </para>
/// <para>
/// <b>Missing assets are the normal case, not an error.</b> Six GLBs of a catalog
/// of dozens exist today. Every lookup therefore returns a result rather than
/// throwing, every miss is reported once, and the scene builder substitutes
/// something visibly marked.
/// </para>
/// </remarks>
public sealed class ModelLibrary
{
    private readonly Dictionary<string, string> _paths = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Node3D?> _loaded = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _missing = new(StringComparer.OrdinalIgnoreCase);

    public ModelLibrary()
    {
        if (!Directory.Exists(ContentPaths.Models))
        {
            GD.PushWarning($"no model directory at {ContentPaths.Models}; everything will be a placeholder");
            return;
        }

        // Indexed by file stem rather than by directory, because the battle files
        // and characters.json disagree about how to name an asset — battle props
        // use a bare id, characters.json uses a repository-relative path — and the
        // stem is the part they always share.
        foreach (string file in Directory.EnumerateFiles(
                     ContentPaths.Models, "*.glb", SearchOption.AllDirectories))
        {
            _paths[Path.GetFileNameWithoutExtension(file)] = file;
        }
    }

    /// <summary>Asset ids asked for that do not exist on disk. For the load report.</summary>
    public IReadOnlyCollection<string> Missing => _missing;

    public int Available => _paths.Count;

    public bool Has(string assetId) => _paths.ContainsKey(Stem(assetId));

    /// <summary>
    /// A fresh instance of an asset, or null if it has not been generated yet.
    /// </summary>
    /// <remarks>
    /// The parsed scene is kept and duplicated per use: the four fence sections in
    /// battle 01 are one file, and parsing a 22,000-triangle oak four times because
    /// it appears four times would be a self-inflicted load time.
    /// </remarks>
    public Node3D? Instance(string assetId)
    {
        string stem = Stem(assetId);
        if (!_loaded.TryGetValue(stem, out Node3D? prototype))
        {
            prototype = Parse(stem);
            _loaded[stem] = prototype;
        }

        return prototype?.Duplicate() as Node3D;
    }

    private Node3D? Parse(string stem)
    {
        if (!_paths.TryGetValue(stem, out string? path))
        {
            if (_missing.Add(stem))
            {
                GD.PushWarning($"asset '{stem}' has not been generated yet; substituting a placeholder");
            }

            return null;
        }

        var document = new GltfDocument();
        var state = new GltfState();
        Error error = document.AppendFromFile(path, state);
        if (error != Error.Ok)
        {
            // A corrupt or half-written GLB must not take the battle down with it.
            GD.PushError($"could not read {path}: {error}");
            _missing.Add(stem);
            return null;
        }

        if (document.GenerateScene(state) is not Node3D root)
        {
            GD.PushError($"{path} contains no 3D scene root");
            _missing.Add(stem);
            return null;
        }

        root.Name = stem;
        return root;
    }

    /// <summary>
    /// The asset id from either a bare id or a repository-relative model path.
    /// </summary>
    private static string Stem(string assetId) =>
        assetId.Contains('/') || assetId.Contains('\\')
            ? Path.GetFileNameWithoutExtension(assetId)
            : assetId;
}

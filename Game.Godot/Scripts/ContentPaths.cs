using Godot;

namespace HollowCrown.Presentation;

/// <summary>
/// Where the game's content lives on disk.
/// </summary>
/// <remarks>
/// <para>
/// <c>Content/</c> sits <b>outside</b> the Godot project on purpose
/// (ARCHITECTURE.md): it is the game's content contract, edited by humans and AI
/// sessions and validated offline by <c>hollowasset validate-content</c>, not an
/// engine resource. Nothing here may assume <c>res://</c>.
/// </para>
/// <para>
/// The consequence is that models are read with <see cref="GltfDocument"/> at
/// runtime rather than through the editor importer — see
/// <see cref="ModelLibrary"/>. That is a real trade-off and it is written up in
/// docs/GODOT_SCENE.md rather than left implicit.
/// </para>
/// </remarks>
public static class ContentPaths
{
    /// <summary>The repository root: the first directory above the project holding Content/Data.</summary>
    public static string Repository { get; } = Locate();

    public static string Data => Path.Combine(Repository, "Content", "Data");

    public static string Models => Path.Combine(Repository, "Content", "Models");

    public static string Battles => Path.Combine(Data, "Battles");

    private static string Locate()
    {
        string start = ProjectSettings.GlobalizePath("res://");
        var directory = new DirectoryInfo(start);
        while (directory is not null)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "Content", "Data")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        // Brief section 75: development builds fail loudly and informatively. An
        // exported build will need Content/ shipped beside the executable, which
        // is a milestone 10 packaging step and not solved here.
        throw new DirectoryNotFoundException(
            $"could not find Content/Data above {start}. The Godot project expects to " +
            "run from inside the repository until export packaging exists.");
    }
}

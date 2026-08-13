# Hollow Engine — technology recommendation

Answers brief section 110, items 1–8. **Nothing here is implemented yet.** Item 9
says not to build the engine before the architecture is approved, and item 10
says to start Milestone 1 once it is. This document is what needs approving.

What *is* implemented is the asset pipeline (`Tools/hollowasset`, brief sections
53–55 and 79), because it is independent of every choice below, it was the part
unblocked by having a working Meshy key, and it produces the content the engine
will need on day one.

---

## Executive summary

| Decision | Recommendation | Why |
| --- | --- | --- |
| Language | C++20, MSVC | Brief section 11 |
| Platform layer | **SDL3** | One dependency covers window, input, gamepad, GPU, audio device, filesystem, threads |
| Rendering abstraction | **SDL_GPU** with the D3D12 backend | No second backend to write; ships inside SDL3 |
| Shaders | HLSL authored, compiled offline to DXIL via SDL_shadercross | Windows-only target makes this a single output format |
| Model format | glTF 2.0 / GLB via **cgltf** | Brief section 12; cgltf is one file |
| Images | **stb_image** | Brief section 12 |
| Audio | **miniaudio** | Do not buy FMOD. See below |
| Math | Hand-rolled in `Core/Math` | ~600 lines, fully understood, no template bloat |
| JSON | **nlohmann/json**, isolated to one translation unit | Ergonomics win for a data-driven game; compile cost contained |
| Collision | Hand-rolled AABB / sphere / ray / grid | Brief section 12 — no rigid-body engine needed |
| Debug UI | **Dear ImGui** (SDL3 + SDL_GPU backends) | Brief section 12 |
| Game UI | Custom immediate-mode layer on the renderer's 2D path | Brief section 12 — ImGui does not ship as game UI |
| Tests | **doctest** | Single header, fast compile, brief section 73 |
| Build | CMake + FetchContent for SDL3, vendored single headers | Simpler than vcpkg for a solo developer |
| Steam | Steamworks behind a platform abstraction, stubbed by default | Brief section 67 |

Total third-party surface: **SDL3 + six single-header libraries.** That is the
"smallest practical stack" item 2 asks for.

---

## The rendering abstraction (item 3)

**Recommendation: SDL_GPU, D3D12 backend, Windows only.**

The brief lists four options. Assessed against development velocity and
maintainability rather than technical prestige:

| Option | Verdict |
| --- | --- |
| **SDL_GPU** | **Chosen.** Ships in SDL3, so the platform layer and the graphics API are one dependency with one build and one release cadence. Modern explicit API, no second backend to maintain. |
| bgfx | The strongest alternative and genuinely defensible. More battle-tested, more backends, a mature shader toolchain. Rejected because it brings its own build system and `shaderc` toolchain, and its platform breadth is value this project will never spend. |
| Direct3D 12 | Thousands of lines of descriptor, barrier and fence boilerplate before the first triangle. Wrong shape of work for a one-director-plus-AI team. |
| Vulkan | The same objection, more so. |

### The trade-off, stated plainly

SDL_GPU is younger than bgfx. The mitigation is cheap and worth doing regardless:
keep it behind a thin internal interface — roughly *create buffer, create
texture, create pipeline, begin pass, bind, draw, end pass, submit* — so a swap
to bgfx is a contained rewrite of one module rather than a project-wide one. Do
not let SDL_GPU types leak into gameplay code.

### The near-term risk

SDL_GPU does not accept shader source. It takes per-backend bytecode: DXIL for
D3D12, SPIR-V for Vulkan, MSL for Metal. Windows-only means DXIL alone, which is
manageable, but the shader build step must exist from Milestone 2 rather than
being bolted on later. Author in HLSL, compile offline with SDL_shadercross as a
CMake custom command, ship the bytecode.

Verify current SDL3 and SDL_GPU release status before Milestone 1; the API has
been stable since SDL 3.2 but confirm rather than assume.

---

## Library notes where the choice is not obvious (item 4)

**Audio — do not buy FMOD.** Brief section 12 asks for this to be evaluated
before adding commercial middleware. miniaudio is a single header covering
playback, mixing, positional audio and format decoding. Buses, fades, crossfades
and music transitions (brief section 51) are a few hundred lines on top of it,
and that layer is small, testable and ours. FMOD earns its licence on games with
complex adaptive audio and a dedicated audio designer; brief section 50 wants
memorable melodies and leitmotifs, which is a composition problem, not a
middleware one. Revisit only if adaptive music becomes a genuine bottleneck.

**Math — hand-rolled.** vec2/3/4, mat4, quat, plus transform and intersection
helpers is about 600 lines. Rejecting glm is a deliberate call: brief section 11
asks to avoid unnecessary template complexity, and glm's compile-time cost and
template depth buy generality this project does not use. Hand-rolled math is
also trivially unit-testable, which brief section 73 wants anyway. Write the
tests alongside it in Milestone 1.

**JSON — nlohmann, contained.** Brief section 14 makes data-driven content a
top-three requirement, and hot-reloadable JSON is the daily-driver workflow. Its
compile-time cost is real, so confine the include to a single `Assets/Json.cpp`
and expose a narrow interface. If compile times become painful, swapping the
parser behind that interface is a one-file change.

**cgltf over tinygltf.** One C file, no dependencies, handles GLB directly.
tinygltf pulls in its own JSON and stb. Our GLBs come from a pipeline we control
and are validated before import, so the simpler loader is sufficient.

**No ECS.** Brief section 82 is right. A battle holds tens of units, a scene
holds hundreds of props. Handles plus plain structs plus a few typed arrays will
outperform the maintenance cost of an ECS at this scale. Revisit only if profiling
says so.

---

## Major technical risks (item 5)

Ordered by expected damage, not likelihood.

### 1. Content volume, not code — the risk that actually kills this project

25–40 hours of gameplay, seven acts, 25–35 recruitable characters, and towns and
dungeons for each. The engine is a few months of tractable work. The content is
years unless it is measured and controlled.

*Mitigation:* treat the vertical slice as a measurement instrument. When
Greenvale is finished, record what fifteen minutes of polished content actually
cost in hours and credits, multiply honestly, and adjust the act structure to
what that number supports. Brief section 100 already permits this. Doing the
arithmetic after Act I is how the schedule gets set by evidence instead of hope.

### 2. Animation retargeting to the shared skeleton

Brief section 56's shared skeleton is what makes 25–35 characters affordable —
one animation set, reused. But Meshy rigs each model individually, so its
skeletons are per-model, not canonical. Bridging that is the single most
under-specified step in the pipeline.

*Mitigation:* solve it once, early, on a throwaway character, before the cast is
generated. Either a Blender retarget script that maps Meshy joints onto the
canonical skeleton, or an engine-side bone remap table. Prove it on two different
characters sharing one clip. `validate.py` already enforces the canonical bone
list and has an alias table for naming differences, which is the groundwork; the
retarget itself is not written. If this is deferred until twenty characters
exist, it becomes twenty problems.

### 3. Shader toolchain friction

Covered above. Cheap if handled in Milestone 2, annoying if deferred.

### 4. Save format migration

Brief section 46 asks for versioning and migration, and it is right to call the
save system a major subsystem. Retrofitting versioning after players have saves
is expensive and public. Design `saveVersion` and a migration chain in Milestone
9, with round-trip tests, before any content depends on it.

### 5. Determinism

Brief section 74 wants reproducible battles. This is an architectural property,
not a feature: one seeded RNG service, injected, never `random_device` at call
sites. Free if designed in at Milestone 5, invasive to retrofit afterwards.

### 6. AI-session continuity

The project's stated model is heavy AI assistance with a human director. That
makes documentation a load-bearing structural element rather than politeness.
Brief section 15 asks the right question — will another session understand this
in six months — and the answer decays silently unless docs are updated in the
same commit as the code.

### 7. Perceived AI-generated quality

Brief section 68 is the commercial risk. Consistency, not sophistication, is what
separates a finished indie RPG from an experiment. The style guide and the
validator exist to enforce consistency mechanically, because taste applied
per-asset over three years will drift and taste encoded in one file will not.

---

## Repository structure (item 6)

Brief section 13's layout, with the deviations noted:

```
/CMakeLists.txt
/Engine                     was /HollowEngine — shorter paths, same meaning
    /Core                   logging, math, files, time, RNG, handles
    /Platform               SDL3 window, input, gamepad
    /Graphics               SDL_GPU wrapper, renderer, materials, shaders
    /Audio
    /Assets                 GLB, textures, JSON, hot reload
    /Animation
    /World                  scenes, entities, collision
    /UI
    /Debug                  ImGui panels, dev console
/Game                       was /HollowGame
    /Tactical  /RPG  /Exploration  /Dialogue  /Quests
    /Characters  /Items  /Skills  /AI  /Save  /Steam
/Content
    /Models     /Characters /Enemies /Props /Weapons /Vegetation /Buildings
    /Animations /Textures /Materials /Maps /References
    /Data       characters.json, classes.json, items.json, skills.json, …
    /Audio      /Music /SFX /Ambience
    /Provenance assets.jsonl
/Tools
    /hollowasset            asset generation, validation, provenance
/Tests
/ThirdParty                 vendored single headers
/Shaders                    HLSL source; DXIL is a build artifact
/docs
/Build                      generated, git-ignored
```

Three deviations from the brief's sketch, each with a reason:

- `/Engine` and `/Game` instead of `/HollowEngine` and `/HollowGame`. Shorter
  include paths, no information lost.
- `/Content/Models` is split by asset type, matching the pipeline's output
  directories so generated assets land in their final home with no move step.
- `/Shaders` is top-level rather than under `/Graphics`, because HLSL source is
  build input with its own compile step, not C++.

---

## The smallest executable prototype (item 8)

Brief section 70, unchanged, because it is already the right target — one
complete gameplay loop and nothing else:

```
window -> 3D scene -> camera -> ground -> one character -> battle grid
       -> select character -> highlight reachable tiles -> click tile
       -> character walks -> select enemy -> attack animation
       -> enemy loses HP -> enemy dies
```

Everything in that chain is load-bearing for the whole game. Nothing in it is
throwaway. It is reached at Milestone 5.

The first *visible* result, per brief section 110, is narrower and comes at
Milestone 2: a Windows executable that opens a window, initialises graphics,
renders a low-poly scene with a movable camera, and logs in structured
categories.

---

## First ten milestones (item 7)

Each ends in something that runs. No milestone is a refactor.

| # | Milestone | Done when |
| --- | --- | --- |
| 1 | **Foundation.** CMake, SDL3 via FetchContent, main loop, structured logging (brief section 76), file paths, seeded RNG, math + tests | `cmake --build build` produces an exe that opens a window, logs, and closes cleanly. Math tests pass |
| 2 | **First light.** SDL_GPU device, HLSL→DXIL build step, camera, mesh + texture draw, directional light | A low-poly scene renders at 1080p with a movable camera. *This is the brief's first visible result* |
| 3 | **Asset import.** cgltf GLB loading, stb_image textures, material system, the pipeline's real barrel and tree on screen | Generated assets load by path and render correctly, wrong scale and orientation reported not crashed |
| 4 | **Characters.** Skeleton, skinned mesh, animation playback and blending, root-motion policy | A rigged character idles and walks with blending |
| 5 | **Tactical grid — the prototype loop.** Tiles, terrain data, selection, A\*, movement range, attack, HP, death, debug visualisation | **Brief section 70's loop runs end to end.** Foundation validated |
| 6 | **Combat systems.** Agility turn order, damage model, crits, elements, status effects, rule-based enemy AI, AI debug scores | Two AI-driven sides fight to a conclusion without input |
| 7 | **Data layer.** JSON characters, classes, skills, items, battles; hot reload; `validate_*` content tooling | A battle is defined entirely in data. Adding ten enemies touches no C++ |
| 8 | **Battle UI and feel.** Battle HUD, damage preview, menus, gamepad navigation, attack camera, hit-stop, impact particles, sound layer | A battle feels good, not merely correct. Brief sections 26–27 |
| 9 | **Exploration and save.** Third-person movement, NPCs, dialogue, chests, shops, world flags, versioned saves with migration and round-trip tests | Walk Greenvale, talk, loot, save, reload, continue |
| 10 | **Vertical slice.** Greenvale content, the goblin commander battle, music, VFX, polish | Fifteen minutes a stranger can play unaided. Trailer material |

Milestones 1–5 are engine. From 6 onward, engine and content advance together.

---

## What is not being built

Brief section 105, restated so it is checkable in review: no multiplayer, no
live service, no procedural worlds, no rigid-body physics, no ray tracing, no
facial mocap, no visual scripting engine, no general-purpose editor, no mod
support during initial development.

Also, deliberately deferred rather than rejected: ECS (section 82),
multithreading beyond asset loading (section 84), Lua (section 87), and a visual
map editor (section 64). Each waits for demonstrated pain, not anticipated pain.

---

## What needs a decision before Milestone 1

1. **Approve or reject SDL_GPU.** The only choice here that is expensive to
   reverse later, and the only one where bgfx is a genuinely close call.
2. **Confirm no FMOD.** Recurring cost, so it is a director's call, not a
   programmer's.
3. **Accept the retargeting risk as a Milestone 4 spike** rather than something
   discovered at character twenty.
4. **Confirm the vertical slice doubles as the schedule measurement**, and that
   the act structure may shrink based on what it measures.

On approval, Milestone 1 starts and produces a compiling executable.

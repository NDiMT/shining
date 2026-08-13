"""Hollow Crown asset tooling.

Offline Python utilities that generate, validate and account for the game's 3D
assets. Runtime code is C++ (brief section 11); this package is strictly a
pipeline tool and never ships in the game build.

Standard library only, with one optional exception: ``postprocess`` uses Pillow
for texture downscaling if it is installed, and reports the skip if it is not.
Everything else — generation, validation, provenance — needs nothing installed,
which is what lets the validator run in CI and in a fresh AI session unchanged.

See docs/ASSET_PIPELINE.md for the workflow and docs/STYLE_GUIDE.md for the art
direction the prompts encode.
"""

__all__ = [
    "animations",
    "budgets",
    "glb",
    "meshy",
    "pipeline",
    "postprocess",
    "provenance",
    "style",
    "validate",
]

__version__ = "0.1.0"

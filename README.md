# Hollow Crown

A low-poly 3D fantasy tactical RPG, built on a custom engine (Hollow Engine) for
commercial release on Steam. Seven kingdoms, seven crowns that are really seals,
and a party of strange heroes collected across a continent.

Spiritually a successor to classic grid-based tactical JRPG adventures —
Shining Force II is the touchstone for the feel. See
[docs/STYLE_GUIDE.md](docs/STYLE_GUIDE.md) for what that means concretely, and
what it deliberately does not mean.

---

## Current state

Built on **Godot 4** with gameplay rules in a pure C# library. See
[ARCHITECTURE.md](ARCHITECTURE.md) for that decision and what it cost.

The engine is **not started**. The first hour of the game is fully specified as
data and assets, which is what milestone 1 will be built against.

| Area | State |
| --- | --- |
| [Asset pipeline](docs/ASSET_PIPELINE.md) | **Working.** Meshy generation, budget enforcement, GLB validation, provenance |
| [Style guide](docs/STYLE_GUIDE.md) | Palette, silhouette families, readability test, IP boundary |
| [Prologue plan](docs/PROLOGUE_PRODUCTION.md) | Beat map, 60 assets catalogued, production order |
| Prologue data | **Complete and validated.** 2 battles, 28 dialogue scenes, 12 world flags |
| Prologue assets | 60 defined, 1 generated and validated |
| [Architecture](ARCHITECTURE.md) | Godot 4 + C#. Five open decisions listed |
| Game code | Not started — milestone 1 |

---

## Repository layout

```
ARCHITECTURE.md        Technology recommendation (brief section 110)
docs/
  PROLOGUE_PRODUCTION.md  The first hour: beats, assets, data, open questions
  STYLE_GUIDE.md          Art direction, palette, IP boundary
  ASSET_PIPELINE.md       How assets are made and validated
  ASSET_PROVENANCE.md     Generated. Do not edit by hand
Content/
  Data/                classes, characters, items, weapons, skills, terrain,
                       flags, Battles/, Dialogue/  <- the game, as data
  Models/              Generated GLBs, by asset type
  References/          Approved concept art for named characters
  Provenance/          assets.jsonl — the asset database
Tools/
  hollowasset/         Asset generation and validation (Python, no deps)
  catalog/             Asset definitions. Add assets by editing these
Tests/                 Tool and content tests
```

`Game.Rules/` and `Game.Godot/` arrive with milestone 1. The planned layout is in
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## Working on assets

Requires Python 3.11+ and nothing else. Pillow is optional and only enables
texture downscaling; the validator is standard library only on purpose, so it
runs in CI and in a fresh AI session with nothing installed.

```sh
export MESHY_API_KEY=...        # never commit this
export PYTHONPATH=Tools
pip install Pillow              # optional; enables texture downscaling

python -m hollowasset budgets                                     # the rules
python -m hollowasset prompt Tools/catalog/prologue_cast.json      # spends nothing
python -m hollowasset generate Tools/catalog/prologue_cast.json --dry-run
python -m hollowasset generate Tools/catalog/greenvale_props.json --id prop_barrel_a
python -m hollowasset validate --catalog Tools/catalog/greenvale_props.json
python -m hollowasset validate-content                             # game data
```

Adding an asset means editing a JSON file in `Tools/catalog/`, never writing
code. Art direction lives in `Tools/hollowasset/style.py` so the whole game can
be restyled from one place.

Full workflow, including how named characters go through approved concept art:
[docs/ASSET_PIPELINE.md](docs/ASSET_PIPELINE.md).

---

## Working on game content

The prologue is data. Battles, dialogue, characters, items and world flags all
live in `Content/Data`, and every reference between them is checked:

```sh
python -m hollowasset validate-content --verbose
python -m unittest discover -s Tests          # 91 tests, no network, no credits
```

The validator catches broken asset paths, duplicate ids, unknown classes and
skills, units standing on impassable tiles, dialogue speakers who do not exist,
undeclared flags, and scripted battle events that would silently do nothing.
Adding a new event action or AI behaviour means registering it in
`Tools/hollowasset/content.py` first — that is deliberate, so a typo cannot pass
for a feature.

What the first hour needs and in what order:
[docs/PROLOGUE_PRODUCTION.md](docs/PROLOGUE_PRODUCTION.md).

---

## Principles

From the master brief, and worth repeating because every decision is measured
against them:

- **We are making Hollow Crown**, not an engine for hypothetical future games.
  If the game does not need a feature, it does not get built.
- **Simple geometry, rich atmosphere.** Quality comes from silhouette, palette,
  light, animation and sound — not polygon count.
- **Content is data.** Adding ten forest enemies should touch no C++.
- **Visible polish beats invisible sophistication.** Good hit effects matter more
  than a clever renderer.
- **AI is a production multiplier, not the product's identity.** Human creative
  direction controls character design, story, pacing, music and art style.
- **Generated content is not assumed correct.** That is why the validator exists
  and why it fails builds.

---

## Secrets

No API keys in the repository, ever. The asset tooling reads `MESHY_API_KEY` from
the environment and never writes it to logs, provenance records or generated
documentation.

If a key is exposed anywhere — a commit, an issue, a chat, a log — rotate it in
the provider's dashboard and treat the old one as burned.

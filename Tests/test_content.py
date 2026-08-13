"""Tests for the game-data validator.

Each test builds a minimal but valid content tree on disk, breaks exactly one
thing, and asserts the validator catches it. Building the tree rather than
pointing at Content/Data keeps the suite hermetic: it cannot be broken by an
edit to the real prologue data, and it proves each check independently.

    python -m unittest discover -s Tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Tools"))

from hollowasset import content  # noqa: E402
from hollowasset.validate import Severity  # noqa: E402


def minimal() -> dict[str, Any]:
    """A small, valid content set: one hero, one enemy, one battle, one scene."""
    return {
        "classes": {
            "classes": [
                {
                    "id": "swordsman",
                    "name": "Swordsman",
                    "movement": 6,
                    "skills": [],
                    "promotions": [],
                },
                {
                    "id": "goblin_raider",
                    "name": "Goblin Raider",
                    "movement": 5,
                    "skills": [],
                    "promotions": [],
                },
            ]
        },
        "characters": {
            "characters": [
                {
                    "id": "rowan",
                    "displayName": "Rowan",
                    "class": "swordsman",
                    "level": 1,
                    "baseStats": {
                        "hp": 22, "mp": 4, "attack": 8, "defense": 6,
                        "magic": 2, "resistance": 4, "agility": 7,
                    },
                    "model": "Content/Models/Characters/hero_rowan.glb",
                    "startingEquipment": {"weapon": "iron_sword"},
                }
            ],
            "npcs": [
                {"id": "guard", "displayName": "Guard",
                 "model": "Content/Models/Characters/npc_guard_greenvale.glb"}
            ],
            "enemies": [
                {
                    "id": "goblin_raider",
                    "displayName": "Goblin Raider",
                    "class": "goblin_raider",
                    "level": 1,
                    "baseStats": {
                        "hp": 12, "mp": 0, "attack": 6, "defense": 3,
                        "magic": 0, "resistance": 1, "agility": 7,
                    },
                    "model": "Content/Models/Enemies/enemy_goblin_raider.glb",
                    "ai": "aggressive_melee",
                }
            ],
        },
        "items": {"items": [{"id": "herb", "name": "Herb", "category": "consumable"}]},
        "weapons": {
            "weapons": [
                {"id": "iron_sword", "name": "Iron Sword", "type": "sword",
                 "attack": 3, "range": 1}
            ]
        },
        "skills": {
            "skills": [
                {"id": "spark", "name": "Spark", "cost": 3, "range": 3, "power": 6,
                 "element": "lightning"}
            ]
        },
        "terrain": {
            "terrain": [
                {"id": "grass", "symbol": "g", "name": "Grass", "move_cost": 1},
                {"id": "wall", "symbol": "W", "name": "Wall", "move_cost": 0,
                 "blocked": True, "walkable": False},
                {"id": "rubble", "symbol": "u", "name": "Rubble", "move_cost": 2},
            ]
        },
        "flags": {
            "flags": [
                {"id": "battle_won", "type": "bool", "default": False,
                 "setBy": ["battle_test"], "readBy": ["later"]},
                {"id": "tone", "type": "string", "default": "",
                 "allowed": ["kind", "harsh"], "setBy": ["scene_test"], "readBy": ["later"]},
            ]
        },
        "battles": {
            "battle_test": {
                "id": "battle_test",
                "name": "Test",
                "size": {"width": 4, "height": 4},
                "terrain": ["WWWW", "gggg", "gggg", "gggg"],
                "objectives": [{"type": "defeat_all", "description": "Win"}],
                "player_units": [{"character": "rowan", "position": [1, 0]}],
                "enemy_units": [
                    {"id": "raider_1", "enemy": "goblin_raider", "position": [2, 1],
                     "ai": "aggressive_melee"}
                ],
                "events": [
                    {
                        "id": "victory_flag",
                        "trigger": {"type": "turn_start", "turn": 2},
                        "actions": [{"type": "set_flag", "flag": "battle_won", "value": True}],
                    }
                ],
                "rewards": {"items": [{"id": "herb", "chance": 1.0}]},
            }
        },
        "dialogue": {
            "expressions": ["neutral", "smile"],
            "scenes": [
                {
                    "id": "scene_test",
                    "lines": [{"speaker": "rowan", "portrait": "neutral", "text": "Hello."}],
                    "on_complete": {"set_flag": {"tone": "kind"}, "start_battle": "battle_test"},
                }
            ],
        },
        "catalog": {
            "region": "greenvale",
            "assets": [
                {"id": "hero_rowan", "class": "hero", "subject": "a swordsman"},
                {"id": "npc_guard_greenvale", "class": "npc", "subject": "a guard"},
                {"id": "enemy_goblin_raider", "class": "enemy_humanoid", "subject": "a goblin"},
            ],
        },
    }


class ContentFixture:
    """Writes a content set to a temporary directory."""

    def __init__(self, tree: dict[str, Any]):
        self.tree = tree
        self.root = ""

    def __enter__(self) -> tuple[str, str]:
        self.root = tempfile.mkdtemp()
        data = os.path.join(self.root, "Data")
        catalogs = os.path.join(self.root, "catalog")
        os.makedirs(os.path.join(data, "Battles"))
        os.makedirs(os.path.join(data, "Dialogue"))
        os.makedirs(catalogs)

        for name in ("classes", "characters", "items", "weapons", "skills", "terrain", "flags"):
            with open(os.path.join(data, f"{name}.json"), "w", encoding="utf-8") as handle:
                json.dump(self.tree[name], handle)
        for battle_id, battle in self.tree["battles"].items():
            with open(os.path.join(data, "Battles", f"{battle_id}.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(battle, handle)
        with open(os.path.join(data, "Dialogue", "scenes.json"), "w", encoding="utf-8") as handle:
            json.dump(self.tree["dialogue"], handle)
        with open(os.path.join(catalogs, "test.json"), "w", encoding="utf-8") as handle:
            json.dump(self.tree["catalog"], handle)
        return data, catalogs

    def __exit__(self, *_) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def run(tree: dict[str, Any]) -> content.ContentReport:
    with ContentFixture(tree) as (data, catalogs):
        return content.validate(content.load(data, catalogs))


def codes(report: content.ContentReport, severity: Severity = Severity.ERROR) -> set[str]:
    return {f.check for f in report.findings if f.severity is severity}


class TestBaseline(unittest.TestCase):
    def test_the_minimal_set_passes(self):
        report = run(minimal())
        self.assertTrue(report.ok, [str(f) for f in report.findings])

    def test_counts_are_reported(self):
        report = run(minimal())
        self.assertEqual(report.counts["characters"], 1)
        self.assertEqual(report.counts["battles"], 1)
        self.assertEqual(report.counts["scenes"], 1)


class TestReferenceChecks(unittest.TestCase):
    def test_unknown_class_on_a_character(self):
        tree = minimal()
        tree["characters"]["characters"][0]["class"] = "wizard"
        self.assertIn("invalid_class", codes(run(tree)))

    def test_unknown_skill_on_a_character(self):
        tree = minimal()
        tree["characters"]["characters"][0]["skills"] = ["fireball"]
        self.assertIn("missing_skill", codes(run(tree)))

    def test_unknown_skill_on_a_class(self):
        tree = minimal()
        tree["classes"]["classes"][0]["skills"] = ["meteor"]
        self.assertIn("missing_skill", codes(run(tree)))

    def test_unknown_starting_equipment(self):
        tree = minimal()
        tree["characters"]["characters"][0]["startingEquipment"] = {"weapon": "excalibur"}
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_missing_base_stats(self):
        tree = minimal()
        del tree["characters"]["characters"][0]["baseStats"]["agility"]
        self.assertIn("invalid_stats", codes(run(tree)))

    def test_duplicate_id_across_namespaces(self):
        tree = minimal()
        tree["characters"]["npcs"].append(
            {"id": "rowan", "displayName": "Fake Rowan",
             "model": "Content/Models/Characters/hero_rowan.glb"}
        )
        self.assertIn("duplicate_id", codes(run(tree)))

    def test_model_path_no_catalog_produces(self):
        tree = minimal()
        tree["characters"]["characters"][0]["model"] = "Content/Models/Characters/hero_ghost.glb"
        self.assertIn("broken_asset_path", codes(run(tree)))

    def test_model_path_matching_a_catalog_passes(self):
        """The check is against catalogs, not the filesystem, so it works in CI
        before any asset has been generated."""
        report = run(minimal())
        self.assertNotIn("broken_asset_path", codes(report))


class TestBattleChecks(unittest.TestCase):
    def test_grid_row_wrong_length(self):
        tree = minimal()
        tree["battles"]["battle_test"]["terrain"] = ["WWWW", "ggg", "gggg", "gggg"]
        self.assertIn("invalid_battle", codes(run(tree)))

    def test_grid_wrong_row_count(self):
        tree = minimal()
        tree["battles"]["battle_test"]["terrain"] = ["WWWW", "gggg"]
        self.assertIn("invalid_battle", codes(run(tree)))

    def test_unknown_terrain_symbol(self):
        tree = minimal()
        tree["battles"]["battle_test"]["terrain"] = ["WWWW", "gggg", "gg?g", "gggg"]
        report = run(tree)
        self.assertIn("invalid_battle", codes(report))
        self.assertTrue(any("'?'" in str(f) for f in report.errors))

    def test_unit_outside_the_grid(self):
        tree = minimal()
        tree["battles"]["battle_test"]["player_units"][0]["position"] = [9, 9]
        self.assertIn("impossible_coordinate", codes(run(tree)))

    def test_unit_on_an_impassable_tile(self):
        tree = minimal()
        # y=3 is the north row, which is solid wall in the fixture.
        tree["battles"]["battle_test"]["player_units"][0]["position"] = [1, 3]
        report = run(tree)
        self.assertIn("impossible_coordinate", codes(report))
        self.assertTrue(any("impassable" in str(f) for f in report.errors))

    def test_two_units_on_the_same_tile(self):
        tree = minimal()
        tree["battles"]["battle_test"]["enemy_units"][0]["position"] = [1, 0]
        report = run(tree)
        self.assertIn("impossible_coordinate", codes(report))
        self.assertTrue(any("occupied" in str(f) for f in report.errors))

    def test_a_pure_npc_cannot_be_a_battle_unit(self):
        """Existing is not the same as spawnable. An npcs entry has only a model
        and a portrait; a unit that fights needs a class and base stats.

        Found by the C# loader refusing to spawn greenvale_soldier after this
        validator had already passed the same battle file."""
        tree = minimal()
        tree["battles"]["battle_test"]["ally_units"] = [
            {"id": "helper", "npc": "guard", "position": [0, 1]}
        ]
        report = run(tree)
        self.assertIn("invalid_reference", codes(report))
        self.assertTrue(any("npcs" in str(f) for f in report.errors))

    def test_unknown_ai_behaviour(self):
        tree = minimal()
        tree["battles"]["battle_test"]["enemy_units"][0]["ai"] = "galaxy_brain"
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_unknown_objective_type(self):
        tree = minimal()
        tree["battles"]["battle_test"]["objectives"] = [{"type": "win_somehow"}]
        self.assertIn("invalid_battle", codes(run(tree)))

    def test_survive_objective_without_turns(self):
        tree = minimal()
        tree["battles"]["battle_test"]["objectives"] = [{"type": "survive_turns"}]
        self.assertIn("invalid_battle", codes(run(tree)))

    def test_unknown_event_action(self):
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [{"type": "summon_dragon"}]
        report = run(tree)
        self.assertIn("invalid_battle", codes(report))
        self.assertTrue(any("silently do nothing" in str(f) for f in report.errors))

    def test_unknown_event_trigger(self):
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["trigger"] = {"type": "vibes"}
        self.assertIn("invalid_battle", codes(run(tree)))

    def test_event_dialogue_scene_must_exist(self):
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "dialogue", "scene": "scene_nonexistent"}
        ]
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_spawn_onto_impassable_tile_fails(self):
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "spawn_unit", "id": "boss", "enemy": "goblin_raider",
             "position": [1, 3], "side": "enemy"}
        ]
        report = run(tree)
        self.assertIn("impossible_coordinate", codes(report))

    def test_spawn_is_allowed_after_the_tile_is_cleared(self):
        """The Wallstalker spawns onto a Crownwall tile that the same event
        converts to rubble one action earlier. That must validate."""
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "set_terrain", "tiles": [[1, 3]], "terrain": "rubble"},
            {"type": "spawn_unit", "id": "boss", "enemy": "goblin_raider",
             "position": [1, 3], "side": "enemy"},
        ]
        report = run(tree)
        self.assertNotIn("impossible_coordinate", codes(report))

    def test_spawn_before_clearing_still_fails(self):
        """Same two actions, wrong order. Ordering is the whole point."""
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "spawn_unit", "id": "boss", "enemy": "goblin_raider",
             "position": [1, 3], "side": "enemy"},
            {"type": "set_terrain", "tiles": [[1, 3]], "terrain": "rubble"},
        ]
        self.assertIn("impossible_coordinate", codes(run(tree)))

    def test_change_side_on_a_unit_not_in_the_battle(self):
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "change_side", "units": ["ghost_unit"], "to": "ally"}
        ]
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_change_side_can_target_a_unit_spawned_by_the_same_event(self):
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "spawn_unit", "id": "boss", "enemy": "goblin_raider",
             "position": [2, 2], "side": "enemy"},
            {"type": "change_side", "units": ["boss"], "to": "ally"},
        ]
        self.assertNotIn("invalid_reference", codes(run(tree)))

    def test_unknown_reward_item(self):
        tree = minimal()
        tree["battles"]["battle_test"]["rewards"]["items"] = [{"id": "elixir", "chance": 1.0}]
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_tutorial_flag_must_be_set_somewhere(self):
        tree = minimal()
        tree["battles"]["battle_test"]["tutorials"] = [
            {"trigger": "flag", "flag": "never_set_anywhere", "id": "t", "text": "hi"}
        ]
        self.assertIn("undeclared_flag", codes(run(tree)))

    def test_battle_scoped_flag_satisfies_a_tutorial(self):
        """A flag only meaningful inside one battle should not have to be
        declared globally in flags.json."""
        tree = minimal()
        tree["battles"]["battle_test"]["events"][0]["actions"] = [
            {"type": "set_flag", "flag": "took_the_hill", "value": True, "scope": "battle"}
        ]
        tree["battles"]["battle_test"]["tutorials"] = [
            {"trigger": "flag", "flag": "took_the_hill", "id": "t", "text": "height helps"}
        ]
        report = run(tree)
        self.assertNotIn("undeclared_flag", codes(report))


class TestDialogueChecks(unittest.TestCase):
    def test_unknown_speaker(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["lines"][0]["speaker"] = "gandalf"
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_narration_speaker_may_be_null(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["lines"] = [
            {"speaker": None, "direction": "The wind picks up."}
        ]
        self.assertNotIn("invalid_reference", codes(run(tree)))

    def test_undeclared_expression(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["lines"][0]["portrait"] = "smouldering"
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_unknown_battle_from_a_scene(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["on_complete"]["start_battle"] = "battle_nope"
        self.assertIn("invalid_reference", codes(run(tree)))

    def test_undeclared_flag_from_a_scene(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["on_complete"]["set_flag"] = {"mystery_flag": True}
        self.assertIn("undeclared_flag", codes(run(tree)))

    def test_flag_value_outside_allowed_set(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["on_complete"]["set_flag"] = {"tone": "sarcastic"}
        report = run(tree)
        self.assertIn("undeclared_flag", codes(report))
        self.assertTrue(any("not one of" in str(f) for f in report.errors))

    def test_bool_flag_set_to_a_string(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["on_complete"]["set_flag"] = {"battle_won": "yes"}
        self.assertIn("undeclared_flag", codes(run(tree)))

    def test_choice_option_flags_are_checked(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["choice"] = {
            "options": [
                {"id": "a", "label": "A", "lines": [], "set_flag": {"tone": "nope"}}
            ]
        }
        self.assertIn("undeclared_flag", codes(run(tree)))

    def test_party_member_must_be_a_character(self):
        tree = minimal()
        tree["dialogue"]["scenes"][0]["on_complete"]["add_party_member"] = ["guard"]
        report = run(tree)
        self.assertIn("invalid_reference", codes(report))


class TestFlagChecks(unittest.TestCase):
    def test_flag_never_set_and_never_read_warns(self):
        tree = minimal()
        tree["flags"]["flags"].append(
            {"id": "orphan", "type": "bool", "default": False, "setBy": [], "readBy": []}
        )
        report = run(tree)
        self.assertIn("unused_flag", codes(report, Severity.WARN))

    def test_flag_with_a_declared_reader_and_no_setter_is_only_info(self):
        """A prologue flag whose payoff lives in Act IV is correct today."""
        tree = minimal()
        tree["flags"]["flags"].append(
            {"id": "future_payoff", "type": "bool", "default": False,
             "setBy": [], "readBy": ["act_four"]}
        )
        report = run(tree)
        self.assertTrue(report.ok)
        self.assertTrue(any(
            f.check == "unused_flag" and "future_payoff" in f.message
            and f.severity is Severity.INFO
            for f in report.findings
        ))


class TestLoading(unittest.TestCase):
    def test_missing_file_raises_a_clear_error(self):
        with ContentFixture(minimal()) as (data, catalogs):
            os.unlink(os.path.join(data, "classes.json"))
            with self.assertRaises(content.ContentError) as caught:
                content.load(data, catalogs)
        self.assertIn("classes.json", str(caught.exception))

    def test_malformed_json_names_the_line(self):
        with ContentFixture(minimal()) as (data, catalogs):
            with open(os.path.join(data, "items.json"), "w", encoding="utf-8") as handle:
                handle.write('{"items": [ {"id": "broken" ')
            with self.assertRaises(content.ContentError) as caught:
                content.load(data, catalogs)
        self.assertIn("line", str(caught.exception))


class TestRealPrologueData(unittest.TestCase):
    """The shipped prologue data must validate. This is the regression guard
    that stops an edit to Content/Data from silently breaking the first hour."""

    def setUp(self):
        self.repo = os.path.join(os.path.dirname(__file__), "..")
        self.data = os.path.join(self.repo, "Content", "Data")
        if not os.path.isdir(self.data):
            self.skipTest("Content/Data not present")

    def test_prologue_content_validates(self):
        loaded = content.load(self.data, os.path.join(self.repo, "Tools", "catalog"))
        report = content.validate(loaded)
        self.assertTrue(report.ok, "\n".join(str(f) for f in report.errors))

    def test_prologue_has_the_expected_shape(self):
        loaded = content.load(self.data, os.path.join(self.repo, "Tools", "catalog"))
        self.assertIn("battle_north_meadow", loaded.battles)
        self.assertIn("battle_the_breach", loaded.battles)
        self.assertIn("rowan", loaded.characters)
        self.assertIn("maeve", loaded.characters)
        self.assertIn("wallstalker", loaded.enemies)
        # The script's closing state, per POST-PROLOGUE PLAYER STATE.
        for flag in (
            "crownwall_breached",
            "rowan_traitor",
            "refugees_entered_greenvale",
            "met_wallstalker",
            "aldric_helped_escape",
            "tomas_remained_greenvale",
        ):
            self.assertIn(flag, loaded.flags, f"prologue must declare {flag}")


if __name__ == "__main__":
    unittest.main()

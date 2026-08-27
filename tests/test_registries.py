"""The registries have to agree with each other.

Nothing here talks to the client, but these are the references the battle engine
resolves at runtime: an encounter naming a template that does not exist, or a
template knowing a skill nobody defined, is a crash in the middle of a fight.
"""

from __future__ import annotations

import pytest

from backend.validation.registries import load_registries


@pytest.fixture(scope="module")
def reg():
    return load_registries()


def test_every_encounter_member_resolves_to_a_template(reg):
    for encounter_id, encounter in reg.encounters.items():
        for member in encounter["members"]:
            assert member["template"] in reg.enemy_templates, \
                f"{encounter_id} summons unknown template {member['template']!r}"


def test_every_template_skill_resolves(reg):
    for template_id, template in reg.enemy_templates.items():
        for skill in template.get("skills", []):
            assert skill in reg.skills, f"{template_id} knows unknown skill {skill!r}"


def test_every_template_carries_the_stats_the_formulas_read(reg):
    for template_id, template in reg.enemy_templates.items():
        for stat in ("hp", "atk", "def", "agi", "mag", "xp"):
            assert isinstance(template.get(stat), int), f"{template_id} is missing {stat}"


def test_skills_declare_a_known_kind_and_target(reg):
    kinds = {"physical", "magic", "heal", "guard"}
    targets = {"one_enemy", "all_enemies", "one_ally", "all_allies", "self"}
    for skill_id, skill in reg.skills.items():
        assert skill["kind"] in kinds, f"{skill_id} has unknown kind {skill['kind']!r}"
        assert skill["target"] in targets, f"{skill_id} has unknown target {skill['target']!r}"
        assert isinstance(skill.get("mp"), int)


def test_consumables_declare_an_effect_the_engine_implements(reg):
    implemented = {"heal_hp", "heal_mp", "cure", "revive"}
    for item_id, item in reg.items.items():
        if item.get("kind") != "consumable":
            continue
        assert item.get("effect") in implemented, \
            f"{item_id} has effect {item.get('effect')!r}, which no battle code handles"

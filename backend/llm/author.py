"""The two authoring calls, and what happens when they go wrong (design doc 4.2-4.5).

The ladder, in order:

    1. author  -> validate -> commit
    2. repair  -> validate -> commit      (one round-trip, errors appended)
    3. placeholder package                (deterministic template fill)

"A failed LLM call must degrade to a boring zone, never to a crash or a broken
gate." Step 3 is the M2 package, which is already known to validate, so there is
always something committable.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from ..packaging.assemble import assemble, slot_ids
from ..procgen.layout import Layout
from ..validation.registries import load_registries
from ..validation.validator import validate_zone_package
from .config import authoring_enabled, build_provider, role_config
from .provider import LLMError

PROMPTS = pathlib.Path(__file__).parent / "prompts"


def _prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (slug or "item")[:60]


# --- outline (design doc 4.2) ----------------------------------------------

async def author_outline(premise: str | None, *, provider=None) -> dict:
    from .schemas import outline_schema

    provider = provider or build_provider("outline")
    user = (
        f"Premise to build on: {premise}\n"
        if premise
        else "Invent the premise yourself.\n"
    ) + (
        "\nThe game has three playable areas, in this order: a starting town, "
        "the upper floor of a flooded mine reached from that town, and a deeper "
        "floor below it. Your beats should move through those places in order."
    )
    completion = await provider.complete(
        system=_prompt("outline"),
        user=user,
        schema=outline_schema(),
        max_tokens=role_config("outline").max_tokens,
    )
    return completion.data


def apply_outline(ledger: dict, data: dict, zone_order: list[str]) -> None:
    """Write the outline into the ledger, and turn its named key items into real
    obligations with concrete zones attached.

    The model names what must exist and which beat it gates. The *engine*
    decides which zone holds it: the zone immediately before the one that needs
    it. That is the whole Fire Key mechanism, and the model never touches it.
    """
    beats = []
    for index, beat in enumerate(data.get("beats", [])):
        beats.append({
            "id": beat.get("id") or f"b{index + 1}",
            "summary": beat["summary"],
            "zone_hint": beat.get("zone_hint", ""),
            "status": "active" if index == 0 else "pending",
        })

    ledger["premise"] = data.get("premise") or ledger.get("premise") or ""
    ledger["outline"] = {
        "tone": data["tone"],
        "antagonist": data["antagonist"],
        "beats": beats,
    }

    beat_zone = {beat["id"]: zone_order[min(i, len(zone_order) - 1)] for i, beat in enumerate(beats)}

    obligations, defined = [], []
    for obligation in data.get("obligations", []):
        item_id = slugify(obligation["name"])
        gates = obligation.get("gates_beat")
        required_by = beat_zone.get(gates, zone_order[-1])
        obligations.append({
            "id": f"obl_{item_id}"[:64],
            "kind": "key_item",
            "name": obligation["name"],
            "item_id": item_id,
            "gates_beat": gates if gates in beat_zone else beats[-1]["id"],
            "required_by": required_by,
            "must_place_before": required_by,
            "placed_in": None,
            "status": "open",
        })
        defined.append({
            "id": item_id,
            "name": obligation["name"],
            "kind": "key_item",
            "description": f"Needed to pass {required_by}.",
        })

    ledger["obligations"] = obligations
    ledger["defined_items"] = defined

    for member, seed in zip(ledger["party"], data.get("party_seed", [])):
        if seed.get("name"):
            member["name"] = seed["name"][:24]


def gate_zone(ledger: dict, obligation: dict, zone_order: list[str]) -> str | None:
    """Which zone holds the locked door.

    `required_by` names the zone the key lets you *into*, so the door itself
    stands in the zone before it — that is the side of the threshold the player
    is on while they still need the key.
    """
    required_by = obligation.get("required_by")
    if not zone_order:
        return None
    if required_by not in zone_order:
        return zone_order[0]
    return zone_order[max(0, zone_order.index(required_by) - 1)]


def planned_placement(ledger: dict, obligation: dict, zone_order: list[str]) -> str | None:
    """Which zone physically contains the key.

    Strictly before the zone holding the door wherever the map allows it, so
    finding the key and using it are separated by at least one place. Clamped to
    the first zone rather than going negative: a key that would have to exist
    before the game starts instead sits in the starting town.
    """
    gate = gate_zone(ledger, obligation, zone_order)
    if gate is None:
        return None
    return zone_order[max(0, zone_order.index(gate) - 1)]


def gates_in(ledger: dict, zone_id: str, zone_order: list[str]) -> dict:
    """Locked doors this zone must contain, keyed by the zone they lead into.

    Engine-owned end to end: the outline says a key must exist, the engine
    decides where the key sits and which threshold it opens. The model is never
    consulted about either.
    """
    gates = {}
    for obligation in ledger.get("obligations", []):
        if obligation.get("kind") != "key_item":
            continue
        if gate_zone(ledger, obligation, zone_order) != zone_id:
            continue
        target = obligation.get("required_by")
        if target == zone_id:
            continue          # nothing to lock: the door would be into itself
        gates[target] = {
            "requires_item": obligation["item_id"],
            "consumes": False,
            "locked_text": f"The way on is sealed. It wants the {obligation['name']}.",
            "obligation_id": obligation["id"],
        }
    return gates


# --- zone authoring (design doc 4.3) ---------------------------------------

@dataclass
class Authored:
    package: dict
    status: str  # authored | repaired | placeholder
    attempts: int = 0
    cost: float = 0.0
    notes: list[str] = field(default_factory=list)


def _context(ledger: dict, zone_id: str, layout: Layout, obligations: list[dict]) -> str:
    """Everything the model is allowed to know, assembled by the engine and
    never by the model (design doc 4.3)."""
    zone = ledger["zones"][zone_id]
    outline = ledger.get("outline", {})
    active = next((b for b in outline.get("beats", []) if b.get("status") == "active"), None)

    lines = [
        f"Tone: {outline.get('tone', 'unspecified')}",
        f"Premise: {ledger.get('premise', '')}",
        f"Antagonist: {outline.get('antagonist', {}).get('name', '?')} — "
        f"{outline.get('antagonist', {}).get('motive', '')}",
        "",
        f"This place: a {zone['kind']}, {layout.width}x{layout.height} tiles.",
    ]
    if active:
        lines.append(f"Where the story is right now: {active['summary']}")

    neighbours = []
    for direction, target in (zone.get("exits") or {}).items():
        other = ledger["zones"].get(target, {})
        summary = other.get("summary") or "not yet visited — say nothing specific about it"
        neighbours.append(f"  - {direction}: {target} ({other.get('kind', '?')}) — {summary}")
    if neighbours:
        lines += ["", "Places you can walk to from here:", *neighbours]

    visited = [
        f"  - {z['id']}: {z['summary']}"
        for z in ledger["zones"].values()
        if z.get("committed") and z.get("summary") and z["id"] != zone_id
    ]
    if visited:
        lines += ["", "Places the party has already been:", *visited[:3]]

    if obligations:
        lines += ["", "You MUST place these here — the game is unwinnable otherwise:"]
        for obligation in obligations:
            lines.append(
                f"  - the {obligation['name']} (item id `{obligation['item_id']}`), which opens the "
                f"way through {obligation['required_by']}. Put it in a chest, or have someone hand "
                f"it over. It must end up in the party's hands."
            )

    lines += ["", "Slots to fill (positions are fixed; you decide who and what):"]
    for slot, slot_id in zip(layout.slots, slot_ids(layout)):
        lines.append(f"  - {slot_id} ({slot.kind}) — {slot.hint or 'no particular hint'}")

    known = sorted((ledger.get("flags") or {}).keys())
    if known:
        lines += ["", f"Flags that already exist and can be tested: {', '.join(known)}"]

    return "\n".join(lines)


async def author_zone(ledger: dict, zone_id: str, layout: Layout, *, provider=None,
                      repair_provider=None, zone_order: list[str] | None = None) -> Authored:
    from .schemas import zone_author_schema

    kind = ledger["zones"][zone_id]["kind"]
    zone_order = zone_order or list(ledger["zones"].keys())

    due = [
        o for o in ledger.get("obligations", [])
        if o.get("status") == "open" and planned_placement(ledger, o, zone_order) == zone_id
    ]
    fulfills = [o["id"] for o in due]

    must_place = [{"item_id": o["item_id"], "name": o["name"]} for o in due if o.get("item_id")]
    placeholder = assemble(layout, zone_id, kind, fulfills=fulfills, must_place=must_place)
    if not layout.slots:
        return Authored(placeholder, "placeholder", notes=["zone has no slots to fill"])
    # An explicitly supplied provider means a caller (or a test) has already
    # decided; only consult config when discovering one for ourselves.
    if provider is None and not authoring_enabled():
        return Authored(placeholder, "placeholder", notes=["no LLM configured; committed placeholders"])

    registries = load_registries()
    ids = slot_ids(layout)
    schema = zone_author_schema(
        slot_ids=ids,
        sprite_tags=sorted(registries.sprite_tags),
        items=sorted(registries.item_ids(ledger)),
        flags=sorted((ledger.get("flags") or {}).keys()),
    )
    context = _context(ledger, zone_id, layout, due)

    provider = provider or build_provider("zone_author")
    notes: list[str] = []
    cost = 0.0
    attempts = 0
    last_errors = ""

    for attempt in range(2):
        attempts += 1
        active = provider if attempt == 0 else (repair_provider or build_provider("fallback"))
        user = context if attempt == 0 else (
            context
            + "\n\nYour previous answer was rejected by the engine's validator. "
            "Fix exactly these problems and return the whole thing again:\n"
            + last_errors
        )
        try:
            completion = await active.complete(
                system=_prompt("zone_author"),
                user=user,
                schema=schema,
                max_tokens=role_config("zone_author").max_tokens,
            )
        except LLMError as exc:
            notes.append(f"attempt {attempts} ({getattr(active, 'name', '?')}): {exc}")
            last_errors = str(exc)[:800]
            continue

        cost += completion.cost
        package = _merge(layout, zone_id, kind, fulfills, completion.data, ledger)
        report = validate_zone_package(package, ledger)
        if report.ok:
            for issue in report.warnings:
                notes.append(f"warning: {issue.code} {issue.path}")
            return Authored(package, "authored" if attempt == 0 else "repaired", attempts, cost, notes)

        last_errors = "\n".join(f"  [{i.code}] {i.path}: {i.message}" for i in report.errors[:12])
        codes: dict[str, int] = {}
        for issue in report.errors:
            codes[issue.code] = codes.get(issue.code, 0) + 1
        notes.append(
            f"attempt {attempts} failed validation: "
            + ", ".join(f"{code}x{n}" for code, n in sorted(codes.items()))
        )

    notes.append("fell back to placeholders after a failed repair round-trip")
    return Authored(placeholder, "placeholder", attempts, cost, notes)


def _merge(layout: Layout, zone_id: str, kind: str, fulfills: list[str], data: dict,
           ledger: dict) -> dict:
    """Turn a model response into a Zone Package.

    Any flag the author used but did not declare is declared for it. The
    alternative is a repair round-trip over a bookkeeping slip, which is a poor
    use of the one repair we allow — but it does mean a typo becomes a new flag,
    so every auto-declaration is surfaced in the package for the shell to show.
    """
    fills = {}
    for fill in data.get("fills", []):
        fill = dict(fill)
        fill["script"] = normalize_script(fill.get("script"))
        fills[fill["slot_id"]] = fill

    used: set[str] = set()
    for fill in fills.values():
        _collect_flags(fill.get("script", []), used)
    known = set((ledger.get("flags") or {}).keys())
    declared = list(dict.fromkeys(list(data.get("declares_flags") or []) + sorted(used - known)))

    return assemble(
        layout, zone_id, kind,
        fulfills=fulfills,
        fills=fills,
        summary=data.get("summary"),
        declares_flags=declared,
        # Design doc 4.5: proposals arrive in their own field and stay inert.
        proposals=data.get("proposals") or [],
    )


def normalize_script(script):
    """Undo the artefacts of strict JSON Schema.

    Strict mode requires *every* declared property, so a model with nothing to
    put in `speaker` writes an empty string rather than omitting it — and the
    event command vocabulary only accepts null or a real name. Same for the
    `else` branch of an IF_FLAG with nothing to say.

    Left alone this fails validation on essentially every zone and burns the one
    repair round-trip on punctuation. It is the engine's job to normalise its own
    schema's side effects, not the author's job to work around them.
    """
    out = []
    for command in script or []:
        if not isinstance(command, dict):
            continue
        command = dict(command)

        speaker = command.get("speaker")
        if isinstance(speaker, str) and not speaker.strip():
            command["speaker"] = None

        for branch in ("then", "else", "on_win", "on_lose"):
            if branch in command:
                nested = normalize_script(command.get(branch))
                if nested:
                    command[branch] = nested
                elif branch == "else":
                    command.pop(branch)  # optional; an empty one is just absent
                else:
                    command[branch] = [{"op": "END"}]

        if isinstance(command.get("options"), list):
            options = []
            for option in command["options"]:
                if not isinstance(option, dict):
                    continue
                nested = normalize_script(option.get("script"))
                options.append({"label": option.get("label", "..."), "script": nested or [{"op": "END"}]})
            command["options"] = options

        out.append(command)
    return out


def _collect_flags(script, into: set) -> None:
    for command in script or []:
        if not isinstance(command, dict):
            continue
        if command.get("op") in ("SET_FLAG", "IF_FLAG") and isinstance(command.get("flag"), str):
            into.add(command["flag"])
        for key in ("then", "else", "on_win", "on_lose"):
            _collect_flags(command.get(key), into)
        for option in command.get("options") or []:
            if isinstance(option, dict):
                _collect_flags(option.get("script"), into)

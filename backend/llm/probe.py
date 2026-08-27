"""Try an LLM endpoint against the schemas this project actually uses.

    python -m backend.llm.probe --list --provider lmstudio --base-url http://HOST:1234/v1
    python -m backend.llm.probe --provider lmstudio --model qwen/qwen3.8-27b --base-url ...
    python -m backend.llm.probe --role zone_author        # whatever llm.yaml says
    python -m backend.llm.probe --compare                 # every configured role

Two things decide whether a model is usable here, and neither is obvious from a
model card:

  1. Does it honour a *nested* json_schema? The event-command palette is deeply
     nested, and a model that quietly ignores it returns HTTP 200 with prose.
     That is what ruled Anthropic models out through OpenRouter.
  2. How much of its budget goes on reasoning? A local reasoning model can spend
     a thousand tokens thinking and then have no room left to answer.

Both are reported below, per schema, with wall-clock timing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ..packaging.assemble import slot_ids
from ..procgen.town import generate as generate_town
from ..validation.registries import load_registries
from ..world import new_game
from .config import build_provider, load_config, load_env, role_config
from .openai_compatible import OpenAICompatibleProvider
from .provider import LLMError
from .schemas import outline_schema, zone_author_schema

SEED = 8471029

OUTLINE_USER = (
    "Premise: a river town whose mine flooded and the water came back warm.\n"
    "The game has four playable areas; the first is the town."
)


def zone_case():
    """A real slot list from a real generated town, not a toy."""
    ledger = new_game.create(SEED)
    zone = ledger["zones"]["zone_town_01"]
    kinds = {z: v["kind"] for z, v in ledger["zones"].items()}
    layout = generate_town(SEED, "zone_town_01", zone["exits"], kinds)
    ids = slot_ids(layout)
    registries = load_registries()
    schema = zone_author_schema(
        slot_ids=ids,
        sprite_tags=sorted(registries.sprite_tags),
        items=sorted(registries.item_ids(ledger)),
        flags=[],
    )
    user = (
        "Fill every slot for a river town whose mine flooded nine days ago and "
        "whose water came back warm.\nSlots:\n"
        + "\n".join(f"  - {sid}" for sid in ids)
    )
    return schema, user, len(ids)


async def run_case(provider, label, system, user, schema, max_tokens):
    try:
        completion = await provider.complete(
            system=system, user=user, schema=schema, max_tokens=max_tokens
        )
    except LLMError as error:
        return {"label": label, "ok": False, "detail": str(error)}
    overhead = (
        f"{completion.reasoning_tokens} reasoning"
        if completion.reasoning_tokens
        else "no reasoning"
    )
    return {
        "label": label,
        "ok": True,
        "seconds": completion.seconds,
        "tokens": completion.completion_tokens,
        "overhead": overhead,
        "cost": completion.cost,
        "sample": completion.data,
    }


def describe(result) -> str:
    if not result["ok"]:
        return f"  {result['label']:<14} FAILED  {result['detail'][:150]}"
    cost = f" ${result['cost']:.4f}" if result["cost"] else ""
    return (
        f"  {result['label']:<14} ok   {result['seconds']:6.1f}s  "
        f"{result['tokens']:>5} out ({result['overhead']}){cost}"
    )


async def probe(provider, name: str, max_tokens: int) -> bool:
    print(f"\n{name}")
    print("-" * len(name))

    schema, user, slot_count = zone_case()
    results = [
        await run_case(
            provider, "outline",
            "You are a story architect. Reply only with JSON matching the schema.",
            OUTLINE_USER, outline_schema(), max_tokens,
        ),
        await run_case(
            provider, f"zone ({slot_count} slots)",
            "You write NPC dialogue for a 16-bit JRPG. Reply only with JSON matching the schema.",
            user, schema, max_tokens,
        ),
    ]
    for result in results:
        print(describe(result))

    zone = results[1]
    if zone["ok"]:
        fills = zone["sample"].get("fills", [])
        print(f"\n  filled {len(fills)}/{slot_count} slots. First line:")
        for fill in fills[:1]:
            line = next(
                (c.get("text") for c in fill.get("script", []) if c.get("op") == "SHOW_TEXT"),
                "(no dialogue)",
            )
            print(f'    {fill.get("display_name")}: "{line}"')
    return all(r["ok"] for r in results)


async def main(argv=None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="probe", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", help="probe a role from llm.yaml")
    parser.add_argument("--compare", action="store_true", help="probe every configured role")
    parser.add_argument("--provider", help="openrouter | lmstudio | llamacpp | vllm | ollama")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--list", action="store_true", help="list the endpoint's models and exit")
    args = parser.parse_args(argv)

    if args.list:
        base = args.base_url
        if not base:
            print("--list needs --base-url", file=sys.stderr)
            return 2
        models = await OpenAICompatibleProvider("", base_url=base, timeout=args.timeout).models()
        print(f"{len(models)} models at {base}:")
        for model in models:
            print("  ", model)
        return 0

    if args.compare:
        config = load_config()
        ok = True
        for role in ("outline", "zone_author", "fallback"):
            if role not in config:
                continue
            spec = role_config(role, config)
            ok &= await probe(build_provider(role, config), f"{role}: {spec.provider} {spec.model}",
                              max(spec.max_tokens, args.max_tokens))
        return 0 if ok else 1

    if args.role:
        config = load_config()
        spec = role_config(args.role, config)
        ok = await probe(build_provider(args.role, config),
                         f"{args.role}: {spec.provider} {spec.model}",
                         max(spec.max_tokens, args.max_tokens))
        return 0 if ok else 1

    if not (args.provider and args.model):
        parser.error("give --role, --compare, or both --provider and --model")

    provider = build_provider("_probe", {
        "_probe": {
            "provider": args.provider,
            "model": args.model,
            "max_tokens": args.max_tokens,
            **({"base_url": args.base_url} if args.base_url else {}),
            "timeout": args.timeout,
        }
    })
    ok = await probe(provider, f"{args.provider}: {args.model}", args.max_tokens)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

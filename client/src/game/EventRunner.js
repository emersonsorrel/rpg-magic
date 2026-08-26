/**
 * The Event Runner: a plain interpreter for the closed command vocabulary
 * (design doc 3.3). Deliberately framework-free -- no Phaser, no React, no DOM --
 * so it can be unit-tested headlessly. Per design doc 10 these are the
 * highest-value tests in the project.
 *
 * Everything that touches the world goes through a host object:
 *
 *   showText({ speaker, text })            -> Promise<void>
 *   showChoice({ speaker, prompt, labels })-> Promise<number>   index into labels
 *   getFlag(flag)                          -> boolean
 *   setFlag(flag, value)                   -> void
 *   giveItem(itemId, qty)                  -> void
 *   takeItem(itemId, qty)                  -> void
 *   startBattle(encounterId)               -> Promise<"win"|"lose">
 *   warp({ toZone, toX, toY })             -> Promise<void>
 *   moveEntity(entityId, path)             -> Promise<void>
 *   playSfx(sfxTag)                        -> void
 *   wait(frames)                           -> Promise<void>
 *
 * Swap the host and the same scripts run in a terminal, in a test, or over a
 * Phaser dialogue box.
 */

/** Mirrors MAX_NESTING_DEPTH in backend/validation/validator.py. */
export const MAX_NESTING_DEPTH = 3;

export class UnknownOpError extends Error {
  constructor(op) {
    super(`'${op}' is not in the event command vocabulary`);
    this.name = "UnknownOpError";
    this.op = op;
  }
}

export class EventRunner {
  constructor(host) {
    this.host = host;
    this.running = false;
  }

  /**
   * Run a script to completion. Resolves true if the script halted early
   * (END, WARP, or an unhandled battle loss), false if it ran off the end.
   */
  async run(script, depth = 1) {
    if (depth > MAX_NESTING_DEPTH) {
      throw new RangeError(
        `script nesting depth ${depth} exceeds the cap of ${MAX_NESTING_DEPTH}`
      );
    }
    if (!Array.isArray(script)) return false;

    const outermost = depth === 1;
    if (outermost) {
      if (this.running) throw new Error("EventRunner is already running a script");
      this.running = true;
    }
    try {
      for (const command of script) {
        if (await this.step(command, depth)) return true;
      }
      return false;
    } finally {
      if (outermost) this.running = false;
    }
  }

  /** Execute one command. Resolves true when the whole script should stop. */
  async step(command, depth) {
    const { host } = this;
    switch (command.op) {
      case "SHOW_TEXT":
        await host.showText({
          speaker: command.speaker ?? null,
          text: command.text,
        });
        return false;

      case "SHOW_CHOICE": {
        const index = await host.showChoice({
          speaker: command.speaker ?? null,
          prompt: command.prompt,
          labels: command.options.map((option) => option.label),
        });
        const chosen = command.options[index];
        if (!chosen) {
          throw new RangeError(
            `showChoice returned ${index}, outside 0..${command.options.length - 1}`
          );
        }
        return this.run(chosen.script, depth + 1);
      }

      case "SET_FLAG":
        host.setFlag(command.flag, command.value);
        return false;

      case "IF_FLAG": {
        const branch = host.getFlag(command.flag) ? command.then : command.else;
        return branch ? this.run(branch, depth + 1) : false;
      }

      case "GIVE_ITEM":
        host.giveItem(command.item_id, command.qty);
        return false;

      case "TAKE_ITEM":
        host.takeItem(command.item_id, command.qty);
        return false;

      case "START_BATTLE": {
        const outcome = await host.startBattle(command.encounter_id);
        const branch = outcome === "win" ? command.on_win : command.on_lose;
        // A loss with no on_lose handler stops the script: the party wiped, so
        // whatever the rest of this cutscene intended no longer applies.
        if (!branch) return outcome !== "win";
        return this.run(branch, depth + 1);
      }

      case "WARP":
        await host.warp({
          toZone: command.to_zone,
          toX: command.to_x,
          toY: command.to_y,
        });
        return true; // the zone is gone; nothing after this is meaningful

      case "MOVE_ENTITY":
        await host.moveEntity(command.entity_id, command.path);
        return false;

      case "PLAY_SFX":
        host.playSfx(command.sfx_tag);
        return false;

      case "WAIT":
        await host.wait(command.frames);
        return false;

      case "END":
        return true;

      default:
        throw new UnknownOpError(command.op);
    }
  }
}

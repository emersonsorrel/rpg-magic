/**
 * Client-side view of the World Ledger (design doc 3.1).
 *
 * At M1 this is loaded from the canned fixture and lives only in memory. From M5
 * it is the save file, serialized straight back to the backend. It owns exactly
 * the facts that must survive leaving a zone -- flags, inventory, party, position
 * -- and nothing about presentation.
 */

export class WorldState {
  constructor(ledger) {
    this.ledger = structuredClone(ledger);
    // Entity ids whose `once` script has already fired. Client-side only at M1;
    // this needs a home in the ledger schema when save/load lands in M5.
    this.spent = new Set();
    this.listeners = new Set();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  #changed() {
    for (const listener of this.listeners) listener(this);
  }

  // --- flags -------------------------------------------------------------

  get flags() {
    return this.ledger.flags;
  }

  getFlag(flag) {
    return Boolean(this.ledger.flags[flag]);
  }

  setFlag(flag, value) {
    this.ledger.flags[flag] = Boolean(value);
    this.#changed();
  }

  /** Merge a zone's `declares_flags` in as false. Called on zone entry. */
  declareFlags(names = []) {
    let added = false;
    for (const name of names) {
      if (!(name in this.ledger.flags)) {
        this.ledger.flags[name] = false;
        added = true;
      }
    }
    if (added) this.#changed();
  }

  // --- inventory ---------------------------------------------------------

  get inventory() {
    return this.ledger.inventory;
  }

  countItem(itemId) {
    return this.ledger.inventory.find((s) => s.item_id === itemId)?.qty ?? 0;
  }

  giveItem(itemId, qty = 1) {
    const stack = this.ledger.inventory.find((s) => s.item_id === itemId);
    if (stack) stack.qty = Math.min(99, stack.qty + qty);
    else this.ledger.inventory.push({ item_id: itemId, qty });
    this.#changed();
  }

  takeItem(itemId, qty = 1) {
    const index = this.ledger.inventory.findIndex((s) => s.item_id === itemId);
    if (index === -1) return false;
    const stack = this.ledger.inventory[index];
    if (stack.qty <= qty) this.ledger.inventory.splice(index, 1);
    else stack.qty -= qty;
    this.#changed();
    return true;
  }

  // --- obligations -------------------------------------------------------

  /** Record that a key has been used on the door it was placed for. */
  consumeObligation(itemId) {
    const obligation = (this.ledger.obligations ?? []).find((o) => o.item_id === itemId);
    if (!obligation || obligation.status === "consumed") return false;
    obligation.status = "consumed";
    this.#changed();
    return true;
  }

  // --- one-shot entities -------------------------------------------------

  isSpent(entityId) {
    return this.spent.has(entityId);
  }

  markSpent(entityId) {
    this.spent.add(entityId);
    this.#changed();
  }

  /** Nudge subscribers after something mutated the ledger in place. */
  touch() {
    this.#changed();
  }

  get party() {
    return this.ledger.party;
  }

  get zones() {
    return this.ledger.zones;
  }

  /** Where the party wakes up after a defeat: the first committed town. */
  get homeZone() {
    return Object.values(this.ledger.zones).find((z) => z.kind === "town" && z.spawn) ?? null;
  }

  /** The mutable slice — player progress, not authored content. */
  progressSnapshot() {
    return {
      party: this.ledger.party,
      inventory: this.ledger.inventory,
      flags: this.ledger.flags,
      player_position: this.ledger.player_position,
      // status only; the engine owns where an obligation lives.
      obligations: this.ledger.obligations,
    };
  }

  // --- position ----------------------------------------------------------

  get position() {
    return this.ledger.player_position;
  }

  setPosition(zone, x, y) {
    this.ledger.player_position = { zone, x, y };
  }
}

/**
 * Assemble an EventRunner host from world state plus a presentation layer.
 * The split is the point: `world` owns facts, `io` owns everything the player
 * sees or waits on. Tests pass a recording `io` and never touch Phaser.
 */
export function createHost(world, io) {
  return {
    showText: (payload) => io.showText(payload),
    showChoice: (payload) => io.showChoice(payload),
    startBattle: (encounterId) => io.startBattle(encounterId),
    warp: (destination) => io.warp(destination),
    moveEntity: (entityId, path) => io.moveEntity(entityId, path),
    playSfx: (sfxTag) => io.playSfx(sfxTag),
    wait: (frames) => io.wait(frames),

    getFlag: (flag) => world.getFlag(flag),
    setFlag: (flag, value) => world.setFlag(flag, value),
    giveItem: (itemId, qty) => world.giveItem(itemId, qty),
    takeItem: (itemId, qty) => world.takeItem(itemId, qty),
  };
}

/**
 * The seam between the shell and the game surface (design doc 6).
 *
 * "Don't try to drive Phaser's scene graph from React state -- React owns the
 * shell, Phaser owns the game surface. They communicate through a small event
 * emitter, not shared reactive state."
 *
 * At M1 the shell is plain DOM rather than React (the toolchain has no build
 * step yet), but the boundary is the one the design calls for, so swapping the
 * shell for React later touches only the shell.
 */
export class GameBus {
  #listeners = new Map();

  on(event, handler) {
    if (!this.#listeners.has(event)) this.#listeners.set(event, new Set());
    this.#listeners.get(event).add(handler);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    this.#listeners.get(event)?.delete(handler);
  }

  emit(event, payload) {
    for (const handler of this.#listeners.get(event) ?? []) {
      try {
        handler(payload);
      } catch (error) {
        // A broken listener must never take the game loop down with it.
        console.error(`GameBus listener for '${event}' threw:`, error);
      }
    }
  }
}

export const bus = new GameBus();

export const Events = {
  ZONE_LOADED: "zone:loaded",
  WORLD_CHANGED: "world:changed",
  DIALOGUE: "dialogue",
  SCRIPT_START: "script:start",
  SCRIPT_END: "script:end",
  LOG: "log",
};

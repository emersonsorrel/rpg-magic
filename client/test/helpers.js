/** A recording presentation layer. Everything the player would see or wait on
 *  lands in `log`; scripted answers come out of the queues. */
export function makeIo({ choices = [], battles = [] } = {}) {
  const io = {
    log: [],
    choiceQueue: [...choices],
    battleQueue: [...battles],

    async showText({ speaker, text }) {
      io.log.push({ kind: "text", speaker, text });
    },
    async showChoice({ prompt, labels }) {
      io.log.push({ kind: "choice", prompt, labels });
      if (!io.choiceQueue.length) throw new Error(`unscripted choice: ${prompt}`);
      return io.choiceQueue.shift();
    },
    async startBattle(encounterId) {
      io.log.push({ kind: "battle", encounterId });
      if (!io.battleQueue.length) throw new Error(`unscripted battle: ${encounterId}`);
      return io.battleQueue.shift();
    },
    async warp(destination) {
      io.log.push({ kind: "warp", ...destination });
    },
    async moveEntity(entityId, path) {
      io.log.push({ kind: "move", entityId, path });
    },
    playSfx(sfxTag) {
      io.log.push({ kind: "sfx", sfxTag });
    },
    async wait(frames) {
      io.log.push({ kind: "wait", frames });
    },

    texts() {
      return io.log.filter((e) => e.kind === "text").map((e) => e.text);
    },
    kinds() {
      return io.log.map((e) => e.kind);
    },
  };
  return io;
}

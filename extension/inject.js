// Runs in the PAGE context: wraps WebSocket and extracts price ticks.
(() => {
  if (window.__qxBrain) return;
  window.__qxBrain = true;

  const DEBUG = true;            // logs first 40 raw frames to the console
  let dbg = 0;
  const ASSET = /^[A-Za-z0-9_\/\-.]{3,24}$/;
  const dec = new TextDecoder();

  // GUESS: tick = [assetName, unixTime, price, ...] somewhere inside the JSON.
  // If the console shows a different frame layout, edit walk() only.
  function walk(x, out) {
    if (!Array.isArray(x)) return;
    if (x.length >= 3 && typeof x[0] === "string" && ASSET.test(x[0]) &&
        typeof x[1] === "number" && x[1] > 1e9 && typeof x[2] === "number") {
      out.push({ a: x[0], t: x[1], p: x[2] });
      return;
    }
    for (const y of x) walk(y, out);
  }

  function emit(text) {
    if (DEBUG && dbg < 40) { dbg++; console.log("[qx-brain] frame:", text.slice(0, 200)); }
    const i = text.search(/[\[{]/);
    if (i < 0) return;
    let j;
    try { j = JSON.parse(text.slice(i)); } catch { return; }
    const ticks = [];
    walk(j, ticks);
    if (ticks.length) window.postMessage({ src: "qx-brain", ticks }, "*");
  }

  function handle(d) {
    if (typeof d === "string") emit(d);
    else if (d instanceof ArrayBuffer) emit(dec.decode(d));
    else if (d instanceof Blob) d.text().then(emit);
  }

  window.WebSocket = new Proxy(window.WebSocket, {
    construct(Target, args) {
      const ws = new Target(...args);
      ws.addEventListener("message", (e) => handle(e.data));
      return ws;
    },
  });
})();

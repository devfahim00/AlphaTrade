// Isolated world: receives ticks from inject.js, talks to Python via background.js, draws overlay.
(() => {
  const buf = [];
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (e.source === window && d && d.src === "qx-brain") buf.push(...d.ticks);
  });

  let panel;
  function ensurePanel() {
    if (panel && panel.isConnected) return panel;
    panel = document.createElement("div");
    panel.style.cssText =
      "position:fixed;top:70px;right:12px;z-index:2147483647;width:260px;padding:10px 12px;" +
      "background:rgba(15,18,28,.93);color:#e8ecf4;font:12px/1.5 system-ui,sans-serif;" +
      "border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,.5);pointer-events:none";
    (document.body || document.documentElement).appendChild(panel);
    return panel;
  }
  const row = (text, color, size) => {
    const d = document.createElement("div");
    d.textContent = text;
    if (color) d.style.color = color;
    if (size) d.style.fontSize = size;
    return d;
  };
  const pct = (v) => (v == null ? "–" : (v * 100).toFixed(1) + "%");

  function render(r) {
    const p = ensurePanel();
    p.replaceChildren();
    if (!r || !r.ok) { p.append(row("QX Brain: Python server offline", "#ff8a8a")); return; }
    const s = r.state;
    if (!s || !s.asset) return;
    p.append(row(`${s.asset}   ${s.price ?? ""}`, "#9fb3d1"));
    const x = s.result;
    if (!x || x.status !== "ready") {
      p.append(row(`Warming up: ${s.candles}/${s.need} candles (${s.tf}s each)`, "#f5c26b"));
      return;
    }
    const col = x.signal === "CALL" ? "#3ddc84" : x.signal === "PUT" ? "#ff5c5c" : "#8b93a7";
    p.append(row(x.signal === "CALL" ? "CALL ▲" : x.signal === "PUT" ? "PUT ▼" : "WAIT", col, "22px"));
    if (x.signal !== "WAIT") p.append(row(`Set expiry: ${s.expiry_s}s`, "#e8ecf4"));
    p.append(row(x.reason, "#8b93a7"));
    if (x.best) {
      p.append(row(`Best: ${x.best.name}`));
      p.append(row(`Train WR ${pct(x.best.train.wr)} (n=${x.best.train.n})`));
      p.append(row(`Test WR  ${pct(x.best.test.wr)} (n=${x.best.test.n})`));
    }
    p.append(row(`Break-even WR: ${pct(x.breakeven)}`, "#f5c26b"));
    (s.pending || []).forEach((q) => {
      const left = Math.max(0, Math.round(q.exp - Date.now() / 1000));
      p.append(row(`Open: ${q.dir > 0 ? "CALL" : "PUT"} (${q.strategy}) ${left}s left`, "#9fb3d1"));
    });
    const live = Object.entries(s.live || {});
    if (live.length) {
      p.append(row("Live demo results:", "#9fb3d1"));
      live.forEach(([k, v]) => {
        const n = v.w + v.l;
        p.append(row(`${k}: ${v.w}W/${v.l}L ${n ? pct(v.w / n) : ""}`));
      });
    }
  }

  setInterval(() => {
    if (!buf.length) return;
    const ticks = buf.splice(0);
    try {
      chrome.runtime.sendMessage({ type: "ticks", ticks }, (resp) => {
        if (chrome.runtime.lastError) return;
        render(resp);
      });
    } catch (_) { /* extension reloaded */ }
  }, 500);
})();

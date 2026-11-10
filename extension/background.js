// Port is configurable via the extension's Options page (default 8765).
async function base() {
  const { port } = await chrome.storage.local.get({ port: 8765 });
  return `http://127.0.0.1:${port}`;
}

chrome.runtime.onMessage.addListener((m, _sender, send) => {
  if (m.type !== "ticks") return;
  base()
    .then((b) =>
      fetch(b + "/ticks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticks: m.ticks }),
      })
    )
    .then((r) => r.json())
    .then((state) => send({ ok: true, state }))
    .catch(() => send({ ok: false }));
  return true; // async response
});

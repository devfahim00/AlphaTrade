const API = "http://127.0.0.1:8765";
chrome.runtime.onMessage.addListener((m, _sender, send) => {
  if (m.type !== "ticks") return;
  fetch(API + "/ticks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticks: m.ticks }),
  })
    .then((r) => r.json())
    .then((state) => send({ ok: true, state }))
    .catch(() => send({ ok: false }));
  return true; // async response
});

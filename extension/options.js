const input = document.getElementById("port");
const msg = document.getElementById("msg");
chrome.storage.local.get({ port: 8765 }).then(({ port }) => (input.value = port));
document.getElementById("save").addEventListener("click", async () => {
  const port = parseInt(input.value, 10);
  if (!(port >= 1024 && port <= 65535)) { msg.textContent = " invalid port"; return; }
  await chrome.storage.local.set({ port });
  msg.textContent = " saved";
});

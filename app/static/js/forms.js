document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

const connectionState = document.getElementById("connection-state");
function updateConnectionState() {
  if (connectionState) connectionState.hidden = navigator.onLine;
}
window.addEventListener("online", updateConnectionState);
window.addEventListener("offline", updateConnectionState);
updateConnectionState();

document.addEventListener("submit", (event) => {
  if (event.defaultPrevented || event.target.method.toLowerCase() !== "post") return;
  if (!navigator.onLine) {
    event.preventDefault();
    updateConnectionState();
    return;
  }
  event.target.setAttribute("aria-busy", "true");
  if (event.submitter) event.submitter.textContent = "Saving…";
});

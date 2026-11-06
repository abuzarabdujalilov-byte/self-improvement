const button = document.querySelector("#ai-toggle");
const modal = document.querySelector("#ai-modal");
const panel = document.querySelector("#ai-panel");
if (button) {
  button.addEventListener("click", () => {
    const open = document.body.dataset.key === "yes";
    if (!open) {
      modal.hidden = !modal.hidden;
      return;
    }
    panel.hidden = !panel.hidden;
  });
}

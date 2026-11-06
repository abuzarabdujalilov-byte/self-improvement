const prompt = document.querySelector("#memory");
const field = document.querySelector("#answer");
if (prompt && field) {
  field.disabled = true;
  window.setTimeout(() => {
    prompt.textContent = "·";
    field.disabled = false;
    field.focus();
  }, 2200);
}

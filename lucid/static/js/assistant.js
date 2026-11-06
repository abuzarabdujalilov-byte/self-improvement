const form = document.querySelector("#composer");
if (form) {
  form.addEventListener("submit", () => {
    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "Sending…";
  });
}

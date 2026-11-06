const legalNode = document.querySelector("#legal");
const wrap = document.querySelector(".board-wrap");
const form = document.querySelector("#move-form");
const input = document.querySelector("#uci");
const legal = legalNode ? JSON.parse(legalNode.textContent || "{}") : {};

function paint(from) {
  document.querySelectorAll(".dot").forEach((dot) => dot.remove());
  document.querySelectorAll(".square.selected").forEach((square) => square.classList.remove("selected"));
  if (!from) return;
  from.square.classList.add("selected");
  (legal[from.name] || []).forEach((uci) => {
    const target = wrap.querySelector(`[data-square="${uci.slice(2, 4)}"]`);
    if (target) {
      const dot = document.createElement("span");
      dot.className = "dot";
      target.appendChild(dot);
    }
  });
}

if (wrap && form && wrap.dataset.live === "yes") {
  let from = null;
  wrap.querySelectorAll(".square").forEach((square) => {
    square.addEventListener("click", () => {
      const name = square.dataset.square;
      if (!from) {
        if (!legal[name]) return;
        from = { name, square };
        paint(from);
        return;
      }
      const choices = legal[from.name] || [];
      const match = choices.find((uci) => uci.startsWith(from.name + name));
      if (!match) {
        from = legal[name] ? { name, square } : null;
        paint(from);
        return;
      }
      input.value = match;
      form.submit();
    });
  });
}

function format(ms) {
  const safe = Math.max(0, ms);
  const total = Math.floor(safe / 1000);
  const minutes = String(Math.floor(total / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

const white = document.querySelector("#white-clock");
const black = document.querySelector("#black-clock");
if (white && black) {
  let whiteMs = Number(white.dataset.ms);
  let blackMs = Number(black.dataset.ms);
  const running = wrap && wrap.dataset.running === "yes";
  const tick = () => {
    white.querySelector("strong").textContent = format(whiteMs);
    black.querySelector("strong").textContent = format(blackMs);
  };
  tick();
  if (running) {
    const side = wrap.dataset.turn;
    const timer = setInterval(() => {
      if (side === "white") whiteMs -= 1000;
      else blackMs -= 1000;
      tick();
      if ((whiteMs <= 0 || blackMs <= 0) && form && input) {
        clearInterval(timer);
        input.value = "";
        form.submit();
      }
    }, 1000);
  }
}

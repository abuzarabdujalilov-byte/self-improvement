const wrap = document.querySelector(".board-wrap");
const form = document.querySelector("#move-form");
const input = document.querySelector("#uci");
if (wrap && form && wrap.dataset.live === "yes") {
  let from = null;
  wrap.querySelectorAll(".square").forEach((square) => {
    square.addEventListener("click", () => {
      const piece = square.dataset.piece || "";
      const name = square.dataset.square;
      if (!from) {
        if (!piece) return;
        const whitePiece = piece === piece.toUpperCase();
        if ((wrap.dataset.turn === "white") !== whitePiece) return;
        from = { name, piece, square };
        square.classList.add("selected");
        return;
      }
      if (name === from.name) {
        from.square.classList.remove("selected");
        from = null;
        return;
      }
      let uci = from.name + name;
      const pawn = from.piece.toLowerCase() === "p";
      const rank = name.slice(1);
      if (pawn && (rank === "8" || rank === "1")) uci += "q";
      input.value = uci;
      form.submit();
    });
  });
}

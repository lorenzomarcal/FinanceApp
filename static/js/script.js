/* Confirmação antes de excluir: o texto vem do atributo data-confirmar do formulário. */
document.addEventListener("submit", (evento) => {
  const mensagem = evento.target.dataset.confirmar;
  if (mensagem && !window.confirm(mensagem)) evento.preventDefault();
});

/* Avisos de sucesso somem sozinhos; erros ficam até a próxima página. */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".alert-success, .alert-info").forEach((alerta) => {
    setTimeout(() => {
      alerta.style.opacity = "0";
      setTimeout(() => alerta.remove(), 300);
    }, 4500);
  });
});

/* Máscaras de digitação: valores em reais e quantidades. */
function formatarMoeda(digitos) {
  const limpo = digitos.replace(/\D/g, "").replace(/^0+/, "").slice(0, 11);
  if (!limpo) return "";
  const centavos = limpo.padStart(3, "0");
  const inteiro = centavos.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return inteiro + "," + centavos.slice(-2);
}

/* Texto colado pode vir como "1500", "1500,5" ou "1.500,50": completa os centavos antes de mascarar. */
function digitosDeTextoColado(texto) {
  const limpo = texto.replace(/[^\d.,]/g, "");
  const decimal = limpo.match(/[.,](\d{1,2})$/);
  if (!decimal) return limpo.replace(/\D/g, "") + "00";
  return limpo.slice(0, decimal.index).replace(/\D/g, "") + decimal[1].padEnd(2, "0");
}

function formatarQuantidade(texto) {
  const partes = texto.replace(/\./g, ",").replace(/[^\d,]/g, "").split(",");
  const inteiro = partes[0].slice(0, 10);
  if (partes.length === 1) return inteiro;
  return (inteiro || "0") + "," + partes.slice(1).join("").slice(0, 6);
}

document.addEventListener("input", (evento) => {
  const campo = evento.target;
  if (!(campo instanceof HTMLInputElement)) return;
  if (campo.dataset.mascara === "moeda") campo.value = formatarMoeda(campo.value);
  else if (campo.dataset.mascara === "quantidade") campo.value = formatarQuantidade(campo.value);
});

document.addEventListener("paste", (evento) => {
  const campo = evento.target;
  if (!(campo instanceof HTMLInputElement) || campo.dataset.mascara !== "moeda") return;
  evento.preventDefault();
  campo.value = formatarMoeda(digitosDeTextoColado(evento.clipboardData.getData("text")));
});

/* Na carteira o mesmo campo serve para comprar e vender: Enter não escolhe por você. */
document.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter" && evento.target instanceof HTMLInputElement && "semEnter" in evento.target.dataset) {
    evento.preventDefault();
  }
});

/* Filtro da lista de movimentações. */
document.addEventListener("click", (evento) => {
  const botao = evento.target.closest("[data-filtro]");
  if (!botao) return;

  const filtro = botao.dataset.filtro;
  let visiveis = 0;

  document.querySelectorAll("#movimentacoes .entry").forEach((linha) => {
    const mostrar = filtro === "todas" || linha.dataset.tipo === filtro;
    linha.hidden = !mostrar;
    if (mostrar) visiveis += 1;
  });

  document.querySelectorAll("[data-filtro]").forEach((outro) => {
    outro.setAttribute("aria-pressed", String(outro === botao));
  });

  const vazio = document.getElementById("filtro-vazio");
  if (vazio) vazio.hidden = visiveis > 0;
});

/* "Usar na compra": leva o ticker pesquisado para o formulário de compra. */
document.addEventListener("click", (evento) => {
  const botao = evento.target.closest("[data-usar-ticker]");
  const formulario = document.getElementById("form-compra");
  if (!botao || !formulario) return;

  formulario.elements.ticker.value = botao.dataset.usarTicker;
  formulario.elements.tipo.value = botao.dataset.usarTipo;
  formulario.scrollIntoView({ block: "center" });
  formulario.elements.quantidade.focus({ preventScroll: true });
});

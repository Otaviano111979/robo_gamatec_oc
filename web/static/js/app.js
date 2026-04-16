(function () {
  const STORAGE_KEY = "tema";
  const toggle = document.getElementById("themeToggle");

  function aplicarTema(tema) {
    if (tema === "dark") {
      document.body.classList.add("dark");
    } else {
      document.body.classList.remove("dark");
    }
  }

  function obterTemaAtual() {
    return localStorage.getItem(STORAGE_KEY) || "light";
  }

  function alternarTema() {
    const atual = obterTemaAtual();
    const novo = atual === "dark" ? "light" : "dark";
    localStorage.setItem(STORAGE_KEY, novo);
    aplicarTema(novo);
  }

  aplicarTema(obterTemaAtual());

  if (toggle) {
    toggle.addEventListener("click", alternarTema);
  }
})();

let logPollingId = null;
let statusPollingId = null;
let processamentoPollingId = null;
let arquivoLogAtual = null;
let arquivoStatusAtual = null;

const STORAGE_OC_PROCESSANDO = "gamatec_oc_processando";
const STORAGE_OC_DESTAQUE = "gamatec_oc_destaque";
const STORAGE_OC_FINALIZADA = "gamatec_oc_finalizada";
const STORAGE_OC_MOVIDA = "gamatec_oc_movida";

const LIST_LIMIT = 10;
let ordemAtualFila = "recentes";
let mostrarTodas = false;

function setTexto(id, texto) {
  const el = document.getElementById(id);
  if (el) el.innerText = texto;
}

function getEl(id) {
  return document.getElementById(id);
}

function pararPollingLog() {
  if (logPollingId) {
    clearInterval(logPollingId);
    logPollingId = null;
  }
}

function pararPollingStatus() {
  if (statusPollingId) {
    clearInterval(statusPollingId);
    statusPollingId = null;
  }
}

function pararPollingProcessamento() {
  if (processamentoPollingId) {
    clearInterval(processamentoPollingId);
    processamentoPollingId = null;
  }
}

function scrollTerminalParaFim() {
  const terminal = getEl("terminal");
  if (terminal) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

function storageSet(key, value) {
  try {
    sessionStorage.setItem(key, value);
  } catch (e) {
    console.warn("Falha ao salvar no storage.", e);
  }
}

function storageGet(key) {
  try {
    return sessionStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

function storageRemove(key) {
  try {
    sessionStorage.removeItem(key);
  } catch (e) {
    console.warn("Falha ao remover do storage.", e);
  }
}

function salvarOCEmProcessamento(nomeArquivo) {
  storageSet(STORAGE_OC_PROCESSANDO, nomeArquivo);
}

function obterOCEmProcessamento() {
  return storageGet(STORAGE_OC_PROCESSANDO);
}

function limparOCEmProcessamento() {
  storageRemove(STORAGE_OC_PROCESSANDO);
}

function salvarOCDestaque(nomeArquivo) {
  storageSet(STORAGE_OC_DESTAQUE, nomeArquivo);
}

function obterOCDestaque() {
  return storageGet(STORAGE_OC_DESTAQUE);
}

function limparOCDestaque() {
  storageRemove(STORAGE_OC_DESTAQUE);
}

function salvarOCFinalizada(nomeArquivo) {
  storageSet(STORAGE_OC_FINALIZADA, nomeArquivo);
}

function obterOCFinalizada() {
  return storageGet(STORAGE_OC_FINALIZADA);
}

function limparOCFinalizada() {
  storageRemove(STORAGE_OC_FINALIZADA);
}

function salvarOCMovida(nomeArquivo) {
  storageSet(STORAGE_OC_MOVIDA, nomeArquivo);
}

function obterOCMovida() {
  return storageGet(STORAGE_OC_MOVIDA);
}

function limparOCMovida() {
  storageRemove(STORAGE_OC_MOVIDA);
}

function removerClassesAtivasDaTabela() {
  document.querySelectorAll("[data-oc-row]").forEach((row) => {
    row.classList.remove("oc-row-active");
    row.classList.remove("oc-row-finished");
    row.classList.remove("oc-row-archived");
  });
}

function aplicarClasseNaLinha(nomeArquivo, classe) {
  const row = document.querySelector(`[data-oc-row="${CSS.escape(nomeArquivo)}"]`);
  if (row) {
    row.classList.add(classe);
  }
}

function marcarLinhaAtiva(nomeArquivo) {
  removerClassesAtivasDaTabela();
  aplicarClasseNaLinha(nomeArquivo, "oc-row-active");
}

function marcarLinhaConcluida(nomeArquivo) {
  removerClassesAtivasDaTabela();
  aplicarClasseNaLinha(nomeArquivo, "oc-row-finished");
}

function marcarLinhaMovida(nomeArquivo) {
  removerClassesAtivasDaTabela();
  aplicarClasseNaLinha(nomeArquivo, "oc-row-archived");
}

function desabilitarBotaoProcessar(nomeArquivo) {
  const botao = document.querySelector(`[data-processar-arquivo="${CSS.escape(nomeArquivo)}"]`);
  if (!botao) return;

  botao.classList.add("disabled");
  botao.classList.add("is-loading");
  botao.setAttribute("aria-disabled", "true");
  botao.setAttribute("data-bloqueado", "true");
  botao.innerText = "Processando...";
}

function desabilitarBotaoMover(nomeArquivo) {
  const botao = document.querySelector(`[data-mover-arquivo="${CSS.escape(nomeArquivo)}"]`);
  if (!botao) return;

  botao.classList.add("is-loading-move");
  botao.setAttribute("data-bloqueado", "true");
  botao.textContent = "Movendo...";
}

function desabilitarBotaoRemover(nomeArquivo) {
  const botao = document.querySelector(`[data-remover-arquivo="${CSS.escape(nomeArquivo)}"]`);
  if (!botao) return;

  botao.classList.add("disabled");
  botao.classList.add("is-loading");
  botao.setAttribute("data-bloqueado", "true");
  botao.textContent = "Removendo...";
}

function aplicarModoProcessandoNoPainel(ativo) {
  if (!ativo) vortexLoadingOff();
  const inspector = document.querySelector(".inspector-card");
  const compact = document.querySelector(".compact-card");
  const listCard = document.querySelector(".list-card");
  const badge = getEl("monitor-badge");

  [inspector, compact, listCard].forEach((el) => {
    if (!el) return;
    el.classList.add("live-card");
    if (ativo) {
      el.classList.add("processing-card");
    } else {
      el.classList.remove("processing-card");
    }
  });

  if (badge) {
    badge.classList.remove("success-state", "neutral-state");
    badge.textContent = ativo ? "Monitorando processo" : "Monitoramento";
  }
}

function aplicarConclusaoNoPainel(nomeArquivo, data) {
  const badge = getEl("monitor-badge");
  const banner = getEl("completion-banner");
  const inspector = document.querySelector(".inspector-card");
  const cardPlanilha = getEl("panel-card-planilha");
  const cardMovimento = getEl("panel-card-movimento");

  if (badge) {
    badge.textContent = "Concluído";
    badge.classList.add("success-state");
    badge.classList.remove("neutral-state");
  }

  if (banner) {
    banner.classList.remove("hidden-banner");
    banner.textContent = "Concluído agora";
    setTimeout(() => {
      banner.classList.add("hidden-banner");
    }, 3500);
  }

  if (inspector) {
    inspector.classList.add("completion-flash");
    setTimeout(() => {
      inspector.classList.remove("completion-flash");
    }, 1400);
  }

  // atualiza o titulo da aba para avisar mesmo com o navegador minimizado
  const nomeResumido = nomeArquivo.length > 30
    ? nomeArquivo.substring(0, 30) + "..."
    : nomeArquivo;

  document.title = "✅ Concluído — " + nomeResumido;

  // restaura o titulo original apos 30 segundos
  setTimeout(() => {
    document.title = "Dashboard | AGENTE EXTRACT";
  }, 30000);

  if (cardPlanilha) {
    if (data && data.tem_planilha) {
      cardPlanilha.classList.add("panel-success");
      cardPlanilha.classList.remove("panel-neutral");
    } else {
      cardPlanilha.classList.remove("panel-success");
    }
  }

  if (cardMovimento) {
    if (data && data.em_processados) {
      cardMovimento.classList.add("panel-neutral");
    } else {
      cardMovimento.classList.remove("panel-neutral");
    }
  }

  salvarOCDestaque(nomeArquivo);
  salvarOCFinalizada(nomeArquivo);
}

function aplicarMovidoNoPainel(nomeArquivo) {
  const badge = getEl("monitor-badge");
  const banner = getEl("completion-banner");
  const cardMovimento = getEl("panel-card-movimento");

  if (badge) {
    badge.textContent = "Movido para Processados";
    badge.classList.add("neutral-state");
    badge.classList.remove("success-state");
  }

  if (banner) {
    banner.classList.remove("hidden-banner");
    banner.textContent = "PDF movido para Processados";
    setTimeout(() => {
      banner.classList.add("hidden-banner");
    }, 3500);
  }

  if (cardMovimento) {
    cardMovimento.classList.add("panel-neutral");
  }

  salvarOCDestaque(nomeArquivo);
  salvarOCMovida(nomeArquivo);
}

function registrarEfeitoLiveCards() {
  const cards = document.querySelectorAll(".ios-card, .status-card");

  cards.forEach((card) => {
    card.classList.add("live-card");

    card.addEventListener("mousemove", (event) => {
      const rect = card.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 100;
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      card.style.setProperty("--mx", `${x}%`);
      card.style.setProperty("--my", `${y}%`);
    });

    card.addEventListener("mouseleave", () => {
      card.style.setProperty("--mx", "50%");
      card.style.setProperty("--my", "50%");
    });
  });
}

function atualizarPainelPorEstado(data) {
  const cardPlanilha = getEl("panel-card-planilha");
  const cardMovimento = getEl("panel-card-movimento");
  const badge = getEl("monitor-badge");

  if (cardPlanilha) {
    cardPlanilha.classList.toggle("panel-success", Boolean(data.tem_planilha));
  }

  if (cardMovimento) {
    cardMovimento.classList.toggle("panel-neutral", Boolean(data.em_processados));
  }

  if (badge && !data.processando) {
    badge.classList.remove("success-state", "neutral-state");
    badge.textContent = "Monitoramento";
  }
}

async function carregarLogTecnico(nomeArquivo) {
  try {
    const resp = await fetch("/logs/" + encodeURIComponent(nomeArquivo), {
      cache: "no-store"
    });

    const texto = await resp.text();
    const terminal = getEl("terminal");

    if (terminal) {
      terminal.innerText = texto || "Sem logs ainda.";
      scrollTerminalParaFim();
    }
  } catch (e) {
    setTexto("terminal", "Erro ao carregar log técnico.");
  }
}

async function carregarStatusOC(nomeArquivo) {
  try {
    const resp = await fetch("/status-oc/" + encodeURIComponent(nomeArquivo), {
      cache: "no-store"
    });

    const data = await resp.json();

    setTexto("status-arquivo", nomeArquivo);
    setTexto("status-geral", data.status_label || "Sem informação");
    setTexto("status-planilha", data.planilha_label || "Sem informação");
    setTexto("status-movimento", data.movimento_label || "Sem informação");
    setTexto("status-output", data.resumo || "Sem resumo disponível.");

    atualizarPainelPorEstado(data);
    aplicarModoProcessandoNoPainel(Boolean(data.processando));
  } catch (e) {
    setTexto("status-geral", "Erro");
    setTexto("status-planilha", "Erro");
    setTexto("status-movimento", "Erro");
    setTexto("status-output", "Erro ao carregar status da OC.");
    aplicarModoProcessandoNoPainel(false);
  }
}

async function consultarStatusProcessamento(nomeArquivo) {
  try {
    const resp = await fetch("/status-oc/" + encodeURIComponent(nomeArquivo), {
      cache: "no-store"
    });

    if (!resp.ok) return;

    const data = await resp.json();

    setTexto("status-arquivo", nomeArquivo);
    setTexto("status-geral", data.status_label || "Sem informação");
    setTexto("status-planilha", data.planilha_label || "Sem informação");
    setTexto("status-movimento", data.movimento_label || "Sem informação");
    setTexto("status-output", data.resumo || "Sem resumo disponível.");

    atualizarPainelPorEstado(data);

    if (data.processando === true) {
      marcarLinhaAtiva(nomeArquivo);
      desabilitarBotaoProcessar(nomeArquivo);
      aplicarModoProcessandoNoPainel(true);
      return;
    }

    aplicarModoProcessandoNoPainel(false);
    aplicarConclusaoNoPainel(nomeArquivo, data);
    limparOCEmProcessamento();
    pararPollingProcessamento();
    window.location.reload();
  } catch (e) {
    console.warn("Falha ao consultar status automático da OC.", e);
    aplicarModoProcessandoNoPainel(false);
  }
}

function iniciarMonitoramentoConclusao(nomeArquivo) {
  salvarOCEmProcessamento(nomeArquivo);
  marcarLinhaAtiva(nomeArquivo);
  desabilitarBotaoProcessar(nomeArquivo);
  pararPollingProcessamento();
  aplicarModoProcessandoNoPainel(true);

  consultarStatusProcessamento(nomeArquivo);

  processamentoPollingId = setInterval(() => {
    consultarStatusProcessamento(nomeArquivo);
  }, 2000);
}

async function iniciarProcessamentoViaAPI(nomeArquivo) {
  vortexLoading("Extraindo itens da OC...", 20);
  try {
    const resp = await fetch("/api/processar-oc/" + encodeURIComponent(nomeArquivo), {
      method: "POST",
      cache: "no-store",
      headers: {
        "X-Requested-With": "XMLHttpRequest"
      }
    });

    const data = await resp.json();

    if (!resp.ok || !data.ok) {
      alert(data.mensagem || "Falha ao iniciar processamento.");
      return;
    }

    setTexto("status-arquivo", nomeArquivo);
    setTexto("status-geral", "Processando");
    setTexto("status-planilha", "Ainda não gerada");
    setTexto("status-movimento", "Em processamento");
    setTexto("status-output", "Processamento iniciado pela interface web...");

    window.ativarAutoRefreshLogs(nomeArquivo);
    window.ativarAutoRefreshStatus(nomeArquivo);
    iniciarMonitoramentoConclusao(nomeArquivo);
    vortexLoadingMsg("Processando — aguarde...", 50);
  } catch (e) {
    console.error(e);
    alert("Erro ao iniciar processamento da OC.");
  }
}

async function removerDaLista(nomeArquivo) {
  try {
    desabilitarBotaoRemover(nomeArquivo);

    const resp = await fetch("/api/remover-da-lista/" + encodeURIComponent(nomeArquivo), {
      method: "POST",
      cache: "no-store",
      headers: {
        "X-Requested-With": "XMLHttpRequest"
      }
    });

    const data = await resp.json();

    if (!resp.ok || !data.ok) {
      alert(data.mensagem || "Falha ao remover da lista.");
      window.location.reload();
      return;
    }

    const row = document.querySelector(`[data-oc-row="${CSS.escape(nomeArquivo)}"]`);
    if (row) {
      row.remove();
    }

    aplicarFiltrosFila();
  } catch (e) {
    console.error(e);
    alert("Erro ao remover OC da lista.");
    window.location.reload();
  }
}

function obterLinhasFila() {
  return Array.from(document.querySelectorAll("#oc-table-body [data-oc-row]"));
}

function ordenarLinhas(linhas) {
  return [...linhas].sort((a, b) => {
    const ta = Number(a.getAttribute("data-timestamp-ref") || "0");
    const tb = Number(b.getAttribute("data-timestamp-ref") || "0");

    if (ordemAtualFila === "antigos") {
      return ta - tb;
    }

    return tb - ta;
  });
}

function atualizarTextoFila(totalFiltradas, totalVisiveis, temFiltroAtivo) {
  const info = getEl("fila-info");
  const badge = getEl("fila-count");

  if (badge) {
    badge.textContent = `${totalVisiveis} visível(is)`;
  }

  if (!info) return;

  if (totalFiltradas === 0) {
    info.textContent = "Nenhuma OC encontrada com o filtro atual.";
    return;
  }

  if (mostrarTodas) {
    if (temFiltroAtivo) {
      info.textContent = `Mostrando ${totalVisiveis} de ${totalFiltradas} OCs filtradas.`;
    } else {
      info.textContent = `Mostrando ${totalVisiveis} de ${totalFiltradas} OCs.`;
    }
    return;
  }

  if (temFiltroAtivo) {
    info.textContent = `Mostrando ${totalVisiveis} de ${totalFiltradas} OCs filtradas.`;
  } else {
    info.textContent = `Mostrando ${totalVisiveis} de ${totalFiltradas} OCs.`;
  }
}

function atualizarEstadoBotoesLista(totalFiltradas) {
  const btnVerTodas = getEl("btn-ver-todas");
  const btnVoltar10 = getEl("btn-voltar-10");

  if (!btnVerTodas || !btnVoltar10) return;

  if (mostrarTodas) {
    btnVerTodas.style.display = "none";
    btnVoltar10.style.display = totalFiltradas > LIST_LIMIT ? "" : "none";
  } else {
    btnVerTodas.style.display = totalFiltradas > LIST_LIMIT ? "" : "none";
    btnVoltar10.style.display = "none";
  }
}

function aplicarFiltrosFila() {
  const linhas = obterLinhasFila();
  const filtroNumero = (getEl("filtro-oc")?.value || "").trim().toLowerCase();
  const filtroData = (getEl("filtro-data")?.value || "").trim();
  const corpo = getEl("oc-table-body");

  if (!corpo) return;

  linhas.forEach((row) => {
    row.style.display = "none";
  });

  let filtradas = linhas.filter((row) => {
    const nome = (row.getAttribute("data-nome") || "").toLowerCase();
    const numero = (row.getAttribute("data-numero-oc") || "").toLowerCase();
    const dataRef = row.getAttribute("data-data-ref") || "";

    const passouNumero = !filtroNumero || numero.includes(filtroNumero) || nome.includes(filtroNumero);
    const passouData = !filtroData || dataRef === filtroData;

    return passouNumero && passouData;
  });

  const totalFiltradas = filtradas.length;
  const temFiltroAtivo = Boolean(filtroNumero || filtroData);

  filtradas = ordenarLinhas(filtradas);

  const visiveis = mostrarTodas ? filtradas : filtradas.slice(0, LIST_LIMIT);

  visiveis.forEach((row) => {
    row.style.display = "";
    corpo.appendChild(row);
  });

  atualizarTextoFila(totalFiltradas, visiveis.length, temFiltroAtivo);
  atualizarEstadoBotoesLista(totalFiltradas);
}

window.ativarAutoRefreshLogs = function (nomeArquivo) {
  arquivoLogAtual = nomeArquivo;
  pararPollingLog();
  carregarLogTecnico(nomeArquivo);

  logPollingId = setInterval(() => {
    if (!arquivoLogAtual) return;
    carregarLogTecnico(arquivoLogAtual);
  }, 1500);
};

window.ativarAutoRefreshStatus = function (nomeArquivo) {
  arquivoStatusAtual = nomeArquivo;
  pararPollingStatus();
  carregarStatusOC(nomeArquivo);

  statusPollingId = setInterval(() => {
    if (!arquivoStatusAtual) return;
    carregarStatusOC(arquivoStatusAtual);
  }, 2000);
};

window.verStatus = function (arq) {
  salvarOCDestaque(arq);
  marcarLinhaAtiva(arq);

  setTexto("status-arquivo", arq);
  setTexto("status-geral", "Consultando...");
  setTexto("status-planilha", "Consultando...");
  setTexto("status-movimento", "Consultando...");
  setTexto("status-output", "Carregando status...");

  window.ativarAutoRefreshStatus(arq);
};

window.verLogTecnico = function (arq) {
  salvarOCDestaque(arq);
  marcarLinhaAtiva(arq);

  const terminal = getEl("terminal");
  if (terminal) {
    terminal.classList.remove("hidden-log");
    terminal.innerText = "Carregando log técnico...";
  }

  window.ativarAutoRefreshLogs(arq);
};

window.alternarLogTecnico = function () {
  const terminal = getEl("terminal");
  if (!terminal) return;
  terminal.classList.toggle("hidden-log");
};

function registrarInterceptacaoProcessar() {
  document.addEventListener("click", function (event) {
    const alvo = event.target.closest("[data-processar-arquivo]");
    if (!alvo) return;

    const nomeArquivo = alvo.getAttribute("data-processar-arquivo");
    const bloqueado = alvo.getAttribute("data-bloqueado") === "true";

    if (!nomeArquivo || bloqueado) {
      event.preventDefault();
      return;
    }

    event.preventDefault();
    alvo.setAttribute("data-bloqueado", "true");
    iniciarProcessamentoViaAPI(nomeArquivo);
  });
}

function registrarInterceptacaoMover() {
  document.addEventListener("click", function (event) {
    const alvo = event.target.closest("[data-mover-arquivo]");
    if (!alvo) return;

    const nomeArquivo = alvo.getAttribute("data-mover-arquivo");
    const bloqueado = alvo.getAttribute("data-bloqueado") === "true";

    if (!nomeArquivo || bloqueado) {
      event.preventDefault();
      return;
    }

    alvo.setAttribute("data-bloqueado", "true");
    desabilitarBotaoMover(nomeArquivo);
    salvarOCMovida(nomeArquivo);
    salvarOCDestaque(nomeArquivo);
  });
}

function registrarInterceptacaoRemover() {
  document.addEventListener("click", function (event) {
    const alvo = event.target.closest("[data-remover-arquivo]");
    if (!alvo) return;

    const nomeArquivo = alvo.getAttribute("data-remover-arquivo");
    const bloqueado = alvo.getAttribute("data-bloqueado") === "true";

    if (!nomeArquivo || bloqueado) {
      event.preventDefault();
      return;
    }

    event.preventDefault();
    alvo.setAttribute("data-bloqueado", "true");
    removerDaLista(nomeArquivo);
  });
}

function registrarFiltrosFila() {
  const filtroOc = getEl("filtro-oc");
  const filtroData = getEl("filtro-data");
  const btnRecentes = getEl("ordenar-recente");
  const btnAntigos = getEl("ordenar-antigo");
  const btnLimpar = getEl("limpar-filtros");
  const btnVerTodas = getEl("btn-ver-todas");
  const btnVoltar10 = getEl("btn-voltar-10");

  if (filtroOc) {
    filtroOc.addEventListener("input", () => {
      mostrarTodas = false;
      aplicarFiltrosFila();
    });
  }

  if (filtroData) {
    filtroData.addEventListener("change", () => {
      mostrarTodas = false;
      aplicarFiltrosFila();
    });
  }

  if (btnRecentes) {
    btnRecentes.addEventListener("click", function () {
      ordemAtualFila = "recentes";
      aplicarFiltrosFila();
    });
  }

  if (btnAntigos) {
    btnAntigos.addEventListener("click", function () {
      ordemAtualFila = "antigos";
      aplicarFiltrosFila();
    });
  }

  if (btnVerTodas) {
    btnVerTodas.addEventListener("click", function () {
      mostrarTodas = true;
      aplicarFiltrosFila();
    });
  }

  if (btnVoltar10) {
    btnVoltar10.addEventListener("click", function () {
      mostrarTodas = false;
      aplicarFiltrosFila();
    });
  }

  if (btnLimpar) {
    btnLimpar.addEventListener("click", function () {
      ordemAtualFila = "recentes";
      mostrarTodas = false;
      if (filtroOc) filtroOc.value = "";
      if (filtroData) filtroData.value = "";
      aplicarFiltrosFila();
    });
  }

  aplicarFiltrosFila();
}

function restaurarMonitoramentoAoReabrirPagina() {
  const nomeArquivo = obterOCEmProcessamento();
  if (!nomeArquivo) {
    aplicarModoProcessandoNoPainel(false);
    return;
  }

  window.ativarAutoRefreshStatus(nomeArquivo);
  window.ativarAutoRefreshLogs(nomeArquivo);
  iniciarMonitoramentoConclusao(nomeArquivo);
}

function restaurarDestaqueAoCarregar() {
  const nomeMovido = obterOCMovida();
  if (nomeMovido) {
    marcarLinhaMovida(nomeMovido);
    aplicarMovidoNoPainel(nomeMovido);
    limparOCMovida();
    return;
  }

  const nomeFinalizado = obterOCFinalizada();
  if (nomeFinalizado) {
    marcarLinhaConcluida(nomeFinalizado);
    const rowFinal = document.querySelector(`[data-oc-row="${CSS.escape(nomeFinalizado)}"]`);
    const data = rowFinal ? {
      tem_planilha: rowFinal.getAttribute("data-tem-planilha") === "true",
      em_processados: rowFinal.getAttribute("data-em-processados") === "true"
    } : null;

    aplicarConclusaoNoPainel(nomeFinalizado, data);

    setTimeout(() => {
      const row = document.querySelector(`[data-oc-row="${CSS.escape(nomeFinalizado)}"]`);
      if (row) row.classList.remove("oc-row-finished");
    }, 6000);

    limparOCFinalizada();
    return;
  }

  const nomeArquivo = obterOCDestaque();
  if (!nomeArquivo) return;

  const row = document.querySelector(`[data-oc-row="${CSS.escape(nomeArquivo)}"]`);
  if (!row) {
    limparOCDestaque();
    return;
  }

  if (obterOCEmProcessamento() === nomeArquivo) {
    row.classList.add("oc-row-active");
  }
}

// =========================
// VORTEX LOADING
// =========================
function vortexLoading(msg, progresso) {
  const overlay = document.getElementById("vortex-loading");
  const msgEl   = document.getElementById("vlo-msg");
  const barEl   = document.getElementById("vlo-bar");
  if (overlay) overlay.classList.add("ativo");
  if (msgEl)   msgEl.textContent = (msg || "PROCESSANDO...").toUpperCase();
  if (barEl && progresso != null) barEl.style.width = progresso + "%";
}

function vortexLoadingMsg(msg, progresso) {
  const msgEl = document.getElementById("vlo-msg");
  const barEl = document.getElementById("vlo-bar");
  if (msgEl) msgEl.textContent = (msg || "").toUpperCase();
  if (barEl && progresso != null) barEl.style.width = progresso + "%";
}

function vortexLoadingOff() {
  const overlay = document.getElementById("vortex-loading");
  if (overlay) overlay.classList.remove("ativo");
}

// =========================
// CALIBRAÇÃO VIA INTERFACE
// =========================
let calibracaoPontos = [];
let calibracaoIndiceAtual = 0;
let calibracaoOCPendente = null;

function abrirModalCalibracao(ocPendente) {
  calibracaoOCPendente = ocPendente || null;
  calibracaoIndiceAtual = 0;
  calibracaoPontos = [];

  const modal = document.getElementById("modal-calibracao");
  document.getElementById("calib-intro").style.display = "";
  document.getElementById("calib-passo").style.display = "none";
  document.getElementById("calib-concluido").style.display = "none";

  if (modal) modal.style.display = "flex";
}

function fecharModalCalibracao() {
  const modal = document.getElementById("modal-calibracao");
  if (modal) modal.style.display = "none";
}

function fecharCalibracaoEAbrirAutomacao() {
  fecharModalCalibracao();
  if (calibracaoOCPendente) {
    abrirModalAutomacao(calibracaoOCPendente);
  }
}

async function iniciarCalibracao() {
  try {
    const resp = await fetch("/api/calibracao/pontos", { cache: "no-store" });
    const data = await resp.json();
    calibracaoPontos = data.pontos || [];
    calibracaoIndiceAtual = 0;

    document.getElementById("calib-intro").style.display = "none";
    document.getElementById("calib-passo").style.display = "";

    mostrarPassoCalibracao();
  } catch (e) {
    alert("Erro ao carregar pontos de calibração.");
  }
}

function mostrarPassoCalibracao() {
  const ponto = calibracaoPontos[calibracaoIndiceAtual];
  const total = calibracaoPontos.length;
  const numero = calibracaoIndiceAtual + 1;

  document.getElementById("calib-numero").textContent = `Ponto ${numero} de ${total}`;
  document.getElementById("calib-descricao").textContent = ponto.label;
  document.getElementById("calib-progresso-label").textContent = `Ponto ${numero} de ${total}`;

  const pct = ((calibracaoIndiceAtual) / total) * 100;
  document.getElementById("calib-barra").style.width = pct + "%";

  const feedback = document.getElementById("calib-feedback");
  feedback.style.display = "none";
  feedback.textContent = "";

  const btn = document.getElementById("btn-capturar");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "🎯 Capturar";
  }
}

function contarRegressiva(segundos, elementoFeedback) {
  return new Promise((resolve) => {
    let restante = segundos;

    function tick() {
      if (elementoFeedback) {
        elementoFeedback.innerHTML =
          `⏳ Posicione o mouse no GAMATEC...<br>` +
          `<span style="font-size:28px; font-weight:700; letter-spacing:2px;">${restante}</span>`;
      }

      if (restante <= 0) {
        resolve();
        return;
      }

      restante--;
      setTimeout(tick, 1000);
    }

    tick();
  });
}

async function capturarPonto() {
  const ponto = calibracaoPontos[calibracaoIndiceAtual];
  const btn = document.getElementById("btn-capturar");
  const feedback = document.getElementById("calib-feedback");
  const ESPERA = 5; // segundos para posicionar o mouse

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Vá para o GAMATEC agora!";
  }

  if (feedback) {
    feedback.style.display = "";
    feedback.className = "calib-feedback calib-feedback-aguardando";
  }

  // contagem regressiva visual
  await contarRegressiva(ESPERA, feedback);

  if (feedback) {
    feedback.textContent = "📸 Capturando posição...";
  }

  try {
    const resp = await fetch(`/api/calibracao/capturar/${ponto.id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ espera: 0 }), // ja esperamos no frontend
      cache: "no-store"
    });

    const data = await resp.json();

    if (!data.ok) {
      if (feedback) {
        feedback.className = "calib-feedback calib-feedback-erro";
        feedback.textContent = "❌ " + data.mensagem;
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = "🎯 Tentar novamente";
      }
      return;
    }

    if (feedback) {
      feedback.className = "calib-feedback calib-feedback-ok";
      feedback.textContent = `✅ Capturado: (${data.x}, ${data.y})`;
    }

    // avança para o próximo ponto após 1 segundo
    setTimeout(() => {
      calibracaoIndiceAtual++;

      if (calibracaoIndiceAtual >= calibracaoPontos.length) {
        salvarCalibracao();
      } else {
        mostrarPassoCalibracao();
      }
    }, 1000);

  } catch (e) {
    if (feedback) {
      feedback.className = "calib-feedback calib-feedback-erro";
      feedback.textContent = "❌ Erro ao capturar ponto.";
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🎯 Tentar novamente";
    }
  }
}

async function salvarCalibracao() {
  document.getElementById("calib-passo").style.display = "none";

  try {
    const resp = await fetch("/api/calibracao/salvar", {
      method: "POST",
      cache: "no-store"
    });
    const data = await resp.json();

    if (!data.ok) {
      alert("Erro ao salvar calibração: " + data.mensagem);
      document.getElementById("calib-passo").style.display = "";
      return;
    }

    // mostra tela de concluído
    document.getElementById("calib-concluido").style.display = "";

    const resumo = document.getElementById("calib-resumo-pontos");
    if (resumo) {
      resumo.innerHTML = `
        <p style="font-size:13px; color:var(--subtext);">
          ✔ ${calibracaoPontos.length} pontos capturados<br>
          ✔ Passo de linha: ${data.passo_linha}px<br>
          ✔ Arquivo salvo em: saida/calibracao_gamatec.json
        </p>`;
    }

    // atualiza botão do modal de automação se estiver aberto
    const btnIniciar = document.getElementById("btn-iniciar-automacao");
    if (btnIniciar) {
      btnIniciar.disabled = false;
      btnIniciar.textContent = "▶ Iniciar Automação";
    }

  } catch (e) {
    alert("Erro ao salvar calibração.");
    document.getElementById("calib-passo").style.display = "";
  }
}

async function resetarCalibracao() {
  if (!confirm("Resetar a calibração? Você precisará refazer o processo.")) return;

  try {
    await fetch("/api/calibracao/resetar", { method: "POST", cache: "no-store" });
    abrirModalCalibracao(calibracaoOCPendente);
  } catch (e) {
    alert("Erro ao resetar calibração.");
  }
}

// =========================
// AUTOMAÇÃO GAMATEC
// =========================
let automacaoOCAtual = null;
let automacaoPollingId = null;

function abrirModalAutomacao(nomeOC) {
  automacaoOCAtual = nomeOC;

  const modal = document.getElementById("modal-automacao");
  const nomeEl = document.getElementById("automacao-nome-oc");
  const infoBox = document.getElementById("automacao-info-box");
  const statusWrap = document.getElementById("automacao-status-wrap");
  const resultadoWrap = document.getElementById("automacao-resultado-wrap");
  const footer = document.getElementById("automacao-footer");
  const btnIniciar = document.getElementById("btn-iniciar-automacao");

  if (nomeEl) nomeEl.textContent = nomeOC;
  if (infoBox) infoBox.style.display = "";
  if (statusWrap) statusWrap.style.display = "none";
  if (resultadoWrap) resultadoWrap.style.display = "none";
  if (footer) footer.style.display = "";
  if (btnIniciar) {
    btnIniciar.disabled = false;
    btnIniciar.textContent = "▶ Iniciar Automação";
  }

  // limpa aviso de calibracao anterior antes de verificar novamente
  const avisoAnterior = document.getElementById("calib-aviso-automacao");
  if (avisoAnterior) avisoAnterior.remove();

  if (modal) modal.style.display = "flex";

  // verifica se calibracao existe
  verificarCalibracao();
}

async function verificarCalibracao() {
  try {
    const resp = await fetch("/api/verificar-calibracao", { cache: "no-store" });
    const data = await resp.json();
    const btnIniciar = document.getElementById("btn-iniciar-automacao");
    const infoBox = document.getElementById("automacao-info-box");

    // remove aviso anterior para evitar duplicação
    const avisoAnterior = document.getElementById("calib-aviso-automacao");
    if (avisoAnterior) avisoAnterior.remove();

    if (!data.calibrado) {
      if (btnIniciar) {
        btnIniciar.disabled = true;
        btnIniciar.textContent = "⚠️ Calibração necessária";
      }
      if (infoBox) {
        const aviso = document.createElement("div");
        aviso.id = "calib-aviso-automacao"; // id fixo para poder remover depois
        aviso.className = "flash-msg flash-erro";
        aviso.style.marginTop = "10px";
        aviso.innerHTML = `⚠️ Calibração não encontrada.
          <br><button class="ios-button small primary" style="margin-top:8px;"
            onclick="fecharModalAutomacaoECalibar()">🎯 Calibrar agora</button>`;
        infoBox.appendChild(aviso);
      }
    }
  } catch (e) {
    console.warn("Nao foi possivel verificar calibracao.", e);
  }
}

function fecharModalAutomacaoECalibar() {
  // fecha o modal de automacao primeiro para evitar sobreposicao
  const nomeOC = automacaoOCAtual;
  fecharModalAutomacao();
  // pequena pausa para garantir que o modal fechou antes de abrir o proximo
  setTimeout(() => {
    abrirModalCalibracao(nomeOC);
  }, 150);
}

function fecharModalAutomacao() {
  pararPollingAutomacao();
  const modal = document.getElementById("modal-automacao");
  if (modal) modal.style.display = "none";
  automacaoOCAtual = null;
}

function pararPollingAutomacao() {
  if (automacaoPollingId) {
    clearInterval(automacaoPollingId);
    automacaoPollingId = null;
  }
}

async function iniciarAutomacao() {
  if (!automacaoOCAtual) return;

  const btnIniciar = document.getElementById("btn-iniciar-automacao");
  const infoBox = document.getElementById("automacao-info-box");
  const statusWrap = document.getElementById("automacao-status-wrap");
  const logEl = document.getElementById("automacao-log");
  const statusLabel = document.getElementById("automacao-status-label");
  const footer = document.getElementById("automacao-footer");

  vortexLoading("Iniciando automação GAMATEC...", 10);

  if (btnIniciar) {
    btnIniciar.disabled = true;
    btnIniciar.textContent = "Iniciando...";
  }

  try {
    const resp = await fetch("/api/iniciar-automacao/" + encodeURIComponent(automacaoOCAtual), {
      method: "POST",
      cache: "no-store"
    });
    const data = await resp.json();

    if (!data.ok) {
      alert(data.mensagem || "Falha ao iniciar automação.");
      if (btnIniciar) {
        btnIniciar.disabled = false;
        btnIniciar.textContent = "▶ Iniciar Automação";
      }
      return;
    }

    if (infoBox) infoBox.style.display = "none";
    if (statusWrap) statusWrap.style.display = "";
    if (footer) footer.style.display = "none";
    if (logEl) logEl.textContent = "Automação iniciada. Aguardando resposta do GAMATEC...";
    if (statusLabel) statusLabel.textContent = "🔄 Executando...";

    automacaoPollingId = setInterval(consultarStatusAutomacao, 2000);

  } catch (e) {
    alert("Erro ao iniciar automação.");
    if (btnIniciar) {
      btnIniciar.disabled = false;
      btnIniciar.textContent = "▶ Iniciar Automação";
    }
  }
}

async function consultarStatusAutomacao() {
  if (!automacaoOCAtual) return;

  try {
    const resp = await fetch("/api/status-automacao/" + encodeURIComponent(automacaoOCAtual), {
      cache: "no-store"
    });
    const data = await resp.json();

    const logEl = document.getElementById("automacao-log");
    const statusLabel = document.getElementById("automacao-status-label");

    if (logEl && data.log) {
      logEl.textContent = data.log;
      logEl.scrollTop = logEl.scrollHeight;
    }

    if (data.automatizando) {
      if (statusLabel) statusLabel.textContent = "🔄 Executando...";
      return;
    }

    // automação terminou
    pararPollingAutomacao();

    const status = data.status;

    if (status && status.itens) {
      exibirResultadoAutomacao(status);
    } else {
      if (statusLabel) statusLabel.textContent = "✅ Finalizado";
      exibirResultadoSimples();
    }

  } catch (e) {
    console.warn("Falha ao consultar status da automação.", e);
  }
}

function exibirResultadoAutomacao(status) {
  const statusWrap = document.getElementById("automacao-status-wrap");
  const resultadoWrap = document.getElementById("automacao-resultado-wrap");
  const resumoEl = document.getElementById("automacao-resumo-itens");
  const statusLabel = document.getElementById("automacao-status-label");

  if (statusLabel) statusLabel.textContent = "✅ Concluído — revise abaixo";
  if (statusWrap) statusWrap.style.display = "";
  if (resultadoWrap) resultadoWrap.style.display = "";

  if (!resumoEl || !status.itens) return;

  const itens = status.itens;
  let html = '<table class="ios-table automacao-tabela-resultado"><thead><tr>';
  html += '<th>Código</th><th>Descrição</th><th>Preço OC</th><th>Final GAMATEC</th><th>Desconto</th><th>Status</th>';
  html += '</tr></thead><tbody>';

  itens.forEach(function(item) {
    const ok = item.status === "SUCESSO_VALIDADO" || item.status === "ITEM_OK_VALIDAR_E_SEGUIR";
    const statusClass = ok ? "status-pill status-ok" : "status-pill status-warning";
    const statusTexto = ok ? "✅ OK" : "⚠️ Revisar";

    html += `<tr>
      <td>${item.codigo || "—"}</td>
      <td>${item.descricao || "—"}</td>
      <td>R$ ${item.preco_alvo != null ? Number(item.preco_alvo).toFixed(2) : "—"}</td>
      <td>R$ ${item.preco_final != null ? Number(item.preco_final).toFixed(2) : "—"}</td>
      <td>${item.desconto != null ? Number(item.desconto).toFixed(2) + "%" : "—"}</td>
      <td><span class="${statusClass}">${statusTexto}</span></td>
    </tr>`;
  });

  html += '</tbody></table>';
  resumoEl.innerHTML = html;
}

function exibirResultadoSimples() {
  const resultadoWrap = document.getElementById("automacao-resultado-wrap");
  const resumoEl = document.getElementById("automacao-resumo-itens");
  if (resultadoWrap) resultadoWrap.style.display = "";
  if (resumoEl) resumoEl.innerHTML = '<p class="automacao-instrucao">Automação finalizada. Verifique o log técnico para detalhes.</p>';
}

function confirmarAutomacao() {
  fecharModalAutomacao();
}

// fechar modal clicando fora
document.addEventListener("click", function(e) {
  const modal = document.getElementById("modal-automacao");
  if (modal && e.target === modal) {
    fecharModalAutomacao();
  }
});

// =========================
// PAINEL DE OCs COM ERRO
// =========================
async function carregarPainelErros() {
  try {
    const resp = await fetch("/api/listar-erros", { cache: "no-store" });
    const data = await resp.json();

    const card = document.getElementById("erros-card");
    const badge = document.getElementById("erros-count");
    const tbody = document.getElementById("erros-table-body");

    if (!card || !badge || !tbody) return;

    const arquivos = data.arquivos || [];

    badge.textContent = arquivos.length;

    if (arquivos.length === 0) {
      card.style.display = "none";
      return;
    }

    card.style.display = "";

    tbody.innerHTML = "";
    arquivos.forEach(function (arq) {
      const tr = document.createElement("tr");

      const tdNome = document.createElement("td");
      tdNome.innerHTML = `<strong>${arq.nome}</strong>`;

      const tdData = document.createElement("td");
      tdData.textContent = arq.data_ref || "-";

      const tdAcoes = document.createElement("td");
      tdAcoes.className = "actions-wrap";

      // usar data-nome para evitar problemas com caracteres especiais no onclick
      const btnReenviar = document.createElement("button");
      btnReenviar.className = "ios-button small primary";
      btnReenviar.type = "button";
      btnReenviar.textContent = "Reenviar";
      btnReenviar.dataset.nome = arq.nome;
      btnReenviar.addEventListener("click", function() {
        reenviarErro(this.dataset.nome, this);
      });

      const btnExcluir = document.createElement("button");
      btnExcluir.className = "ios-button small danger";
      btnExcluir.type = "button";
      btnExcluir.textContent = "Excluir";
      btnExcluir.dataset.nome = arq.nome;
      btnExcluir.addEventListener("click", function() {
        excluirErro(this.dataset.nome, this);
      });

      tdAcoes.appendChild(btnReenviar);
      tdAcoes.appendChild(btnExcluir);

      tr.appendChild(tdNome);
      tr.appendChild(tdData);
      tr.appendChild(tdAcoes);
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.warn("Falha ao carregar painel de erros.", e);
  }
}

async function reenviarErro(nomeArquivo, btn) {
  btn.disabled = true;
  btn.textContent = "Reenviando...";

  try {
    const resp = await fetch("/api/reenviar-erro", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo: nomeArquivo })
    });
    const data = await resp.json();

    if (data.ok) {
      await carregarPainelErros();
      window.location.reload();
    } else {
      alert(data.mensagem || "Falha ao reenviar.");
      btn.disabled = false;
      btn.textContent = "Reenviar";
    }
  } catch (e) {
    alert("Erro ao reenviar arquivo.");
    btn.disabled = false;
    btn.textContent = "Reenviar";
  }
}

async function excluirErro(nomeArquivo, btn) {
  if (!confirm("Excluir permanentemente " + nomeArquivo + "?")) return;

  btn.disabled = true;
  btn.textContent = "Excluindo...";

  try {
    const resp = await fetch("/api/excluir-erro", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo: nomeArquivo })
    });
    const data = await resp.json();

    if (data.ok) {
      await carregarPainelErros();
    } else {
      alert(data.mensagem || "Falha ao excluir.");
      btn.disabled = false;
      btn.textContent = "Excluir";
    }
  } catch (e) {
    alert("Erro ao excluir arquivo.");
    btn.disabled = false;
    btn.textContent = "Excluir";
  }
}

// =========================
// MENU COMPACTO DE AÇÕES
// =========================
function fecharMenus() {
  document.querySelectorAll(".acoes-menu.aberto").forEach(function (m) {
    m.classList.remove("aberto");
  });
}

function toggleMenu(btn) {
  const menu = btn.nextElementSibling;
  const estaAberto = menu.classList.contains("aberto");
  fecharMenus();
  if (!estaAberto) {
    menu.classList.add("aberto");
  }
}

// fecha menus ao clicar fora
document.addEventListener("click", function (e) {
  if (!e.target.closest(".acoes-menu-wrap")) {
    fecharMenus();
  }
});

document.addEventListener("DOMContentLoaded", function () {
  registrarInterceptacaoProcessar();
  registrarInterceptacaoMover();
  registrarInterceptacaoRemover();
  registrarEfeitoLiveCards();
  registrarFiltrosFila();
  restaurarMonitoramentoAoReabrirPagina();
  restaurarDestaqueAoCarregar();
  carregarPainelErros();
});

window.addEventListener("beforeunload", function () {
  pararPollingLog();
  pararPollingStatus();
  pararPollingProcessamento();
}); 
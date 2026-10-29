/* Calendário da sidebar: mês, feriados e destaques do dia selecionado. */
(function () {
  'use strict';

  var raiz = document.getElementById('calendario');
  if (!raiz) return;
  if (raiz.offsetParent === null) return; // barra horizontal em ecrã estreito

  var grade = document.getElementById('cal-grade');
  var rotulo = document.getElementById('cal-mes');
  var painel = document.getElementById('cal-destaques');
  var aviso = document.getElementById('cal-aviso');

  var MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
               'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
  var DIAS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];

  var hoje = new Date();
  var visivel = { ano: hoje.getFullYear(), mes: hoje.getMonth() + 1 };
  var selecionado = iso(hoje);
  var meses = {};
  var dias = {};
  var pedidos = {};
  var pedidoMes = 0;

  function pad(numero) {
    return (numero < 10 ? '0' : '') + numero;
  }

  function iso(data) {
    return data.getFullYear() + '-' + pad(data.getMonth() + 1) + '-' + pad(data.getDate());
  }

  function chaveMes() {
    return visivel.ano + '-' + pad(visivel.mes);
  }

  function dadosMes() {
    return meses[chaveMes()];
  }

  function elemento(tag, classe, texto) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function mostrarAviso(texto) {
    if (!aviso) return;
    aviso.textContent = texto;
    aviso.hidden = false;
  }

  function esconderAviso() {
    if (!aviso) return;
    aviso.hidden = true;
  }

  function carregarMes() {
    if (dadosMes()) {
      renderizar();
      return;
    }
    var meu = ++pedidoMes;
    var chave = chaveMes();
    var ano = visivel.ano;
    var mes = visivel.mes;

    fetch('/api/calendario?ano=' + ano + '&mes=' + mes, { cache: 'no-store' })
      .then(function (resposta) {
        return resposta.json();
      })
      .then(function (dados) {
        if (meu !== pedidoMes) return;
        if (!dados || !dados.ok) throw new Error('sem dados');
        meses[chave] = {
          feriados: dados.feriados || {},
          comemorativas: dados.comemorativas || {},
        };
        if (dados.completo === false) {
          mostrarAviso('Sem ligação — a mostrar o que já está guardado.');
        } else {
          esconderAviso();
        }
        if (chave === chaveMes()) renderizar();
      })
      .catch(function () {
        if (meu !== pedidoMes) return;
        mostrarAviso('Calendário indisponível sem ligação.');
        if (chave === chaveMes()) renderizar();
      });
  }

  function carregarDia() {
    var data = selecionado;
    if (dias[data] || pedidos[data]) return;
    pedidos[data] = true;

    fetch('/api/calendario/dia?data=' + encodeURIComponent(data), { cache: 'no-store' })
      .then(function (resposta) {
        return resposta.json();
      })
      .then(function (dados) {
        if (!dados || !dados.ok) throw new Error('sem dados');
        dias[data] = dados;
      })
      .catch(function () {
        dias[data] = { ok: false, falhou: true };
      })
      .then(function () {
        delete pedidos[data];
        if (data === selecionado) renderizarDestaques();
      });
  }

  function renderizar() {
    rotulo.textContent = MESES[visivel.mes - 1] + ' ' + visivel.ano;
    grade.replaceChildren();

    var dados = dadosMes() || { feriados: {}, comemorativas: {} };
    var primeiro = new Date(visivel.ano, visivel.mes - 1, 1);
    var total = new Date(visivel.ano, visivel.mes, 0).getDate();
    var hojeIso = iso(new Date());

    for (var vazio = 0; vazio < primeiro.getDay(); vazio++) {
      grade.appendChild(elemento('span', 'cal-dia is-fora'));
    }

    for (var dia = 1; dia <= total; dia++) {
      var data = visivel.ano + '-' + pad(visivel.mes) + '-' + pad(dia);
      var feriados = dados.feriados[data] || [];
      var comemorativas = dados.comemorativas[data] || [];
      var botao = document.createElement('button');

      botao.type = 'button';
      botao.className = 'cal-dia';
      botao.textContent = dia;
      botao.dataset.data = data;
      if (data === hojeIso) botao.classList.add('is-hoje');
      if (data === selecionado) botao.classList.add('is-sel');
      if (feriados.length) botao.classList.add('tem-feriado');
      else if (comemorativas.length) botao.classList.add('tem-data');
      botao.setAttribute('aria-pressed', data === selecionado ? 'true' : 'false');
      if (data === hojeIso) botao.setAttribute('aria-current', 'date');

      var nomes = feriados.map(function (item) { return item.nome; });
      botao.setAttribute('aria-label', dia + ' de ' + MESES[visivel.mes - 1] +
        (nomes.length ? ' — ' + nomes.join(', ') : ''));

      grade.appendChild(botao);
    }

    renderizarDestaques();
  }

  function grupo(titulo, itens, montar) {
    var bloco = elemento('div', 'cal-grupo');
    bloco.appendChild(elemento('div', 'cal-grupo-titulo', titulo));
    itens.forEach(function (item) {
      bloco.appendChild(montar(item));
    });
    return bloco;
  }

  function itemComEtiqueta(item) {
    var linha = elemento('div', 'cal-item');
    linha.appendChild(elemento('span', 'cal-item-nome', item.nome));
    if (item.rotulo) {
      var etiqueta = elemento('span', 'cal-badge is-feriado', item.rotulo);
      linha.appendChild(etiqueta);
    }
    return linha;
  }

  function itemEfemeride(item) {
    var linha = elemento('div', 'cal-efem');
    linha.appendChild(elemento('span', 'cal-efem-ano', item.ano));
    linha.appendChild(elemento('span', 'cal-efem-texto', item.texto));
    return linha;
  }

  function renderizarDestaques() {
    var data = selecionado;
    var partes = data.split('-');
    var dia = new Date(Number(partes[0]), Number(partes[1]) - 1, Number(partes[2]));
    var dadosDoDia = dias[data];
    var dados = dadosMes() || { feriados: {}, comemorativas: {} };
    var feriados = (dadosDoDia && dadosDoDia.feriados) || dados.feriados[data] || [];
    var comemorativas = (dadosDoDia && dadosDoDia.comemorativas) || dados.comemorativas[data] || [];
    var anoAtual = new Date().getFullYear();

    painel.replaceChildren();

    var titulo = elemento('div', 'cal-destaques-titulo',
      dia.getDate() + ' de ' + MESES[dia.getMonth()] + (dia.getFullYear() !== anoAtual ? ' de ' + dia.getFullYear() : ''));
    titulo.appendChild(elemento('small', '', DIAS[dia.getDay()]));
    painel.appendChild(titulo);

    var temDestaque = feriados.length || comemorativas.length;

    if (feriados.length) {
      painel.appendChild(grupo('Feriados', feriados, itemComEtiqueta));
    }
    if (comemorativas.length) {
      painel.appendChild(grupo('Datas importantes', comemorativas, itemComEtiqueta));
    }

    if (!dadosDoDia) {
      painel.appendChild(elemento('p', 'cal-vazio', 'A procurar acontecimentos…'));
      carregarDia();
      return;
    }

    var efemerides = dadosDoDia.efemerides || [];
    if (efemerides.length) {
      painel.appendChild(grupo('Acontecimentos', efemerides, itemEfemeride));
      temDestaque = true;
    } else if (dadosDoDia.falhou || dadosDoDia.completo === false) {
      painel.appendChild(elemento('p', 'cal-vazio', 'Acontecimentos indisponíveis sem ligação.'));
    }

    if (!temDestaque) {
      painel.appendChild(elemento('p', 'cal-vazio', 'Sem destaques para este dia.'));
    }
  }

  rotulo.addEventListener('click', function () {
    var hoje = new Date();
    visivel = { ano: hoje.getFullYear(), mes: hoje.getMonth() + 1 };
    selecionado = iso(hoje);
    carregarMes();
    renderizar();
  });

  raiz.querySelectorAll('[data-cal-mes]').forEach(function (botao) {
    botao.addEventListener('click', function () {
      var delta = Number(botao.getAttribute('data-cal-mes'));
      var alvo = new Date(visivel.ano, visivel.mes - 1 + delta, 1);
      visivel = { ano: alvo.getFullYear(), mes: alvo.getMonth() + 1 };
      if (selecionado.slice(0, 7) !== chaveMes()) {
        selecionado = chaveMes() + '-01';
      }
      carregarMes();
      renderizar();
    });
  });

  grade.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-data]');
    if (!botao) return;
    selecionado = botao.dataset.data;
    renderizar();
    carregarDia();
  });

  renderizar();
  carregarMes();
  carregarDia();
})();

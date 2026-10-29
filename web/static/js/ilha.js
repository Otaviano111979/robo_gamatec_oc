/* Ilha da sidebar: tempo de Goiânia, mercado e notícias do setor. */
(function () {
  'use strict';

  var raiz = document.getElementById('ilha');
  if (!raiz) return;
  if (raiz.offsetParent === null) return; // barra horizontal (ecrã estreito)

  var botao = document.getElementById('ilha-botao');
  var cartao = document.getElementById('ilha-cartao');
  var elPilulaIcone = document.getElementById('ilha-pilula-icone');
  var elTemp = document.getElementById('ilha-temp-txt');
  var elCot = document.getElementById('ilha-cot');
  var elBolsa = document.getElementById('ilha-bolsa');
  var elRelogio = document.getElementById('ilha-relogio');
  var elTempo = document.getElementById('ilha-tempo');
  var elDias = document.getElementById('ilha-dias');
  var elMercado = document.getElementById('ilha-mercado');
  var elNoticias = document.getElementById('ilha-noticias');
  var elAtualizado = document.getElementById('ilha-atualizado');
  var botaoAtualizar = document.getElementById('ilha-atualizar');

  var ICONES = {
    sol: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    'sol-nublado': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3"/><path d="M9 2.5v1M4.6 8h-1M13.4 8h1M5.8 4.8l-.7-.7M12.2 11.2l-.7-.7"/><path d="M18 20H9.5a3.5 3.5 0 0 1-.4-6.98A4.8 4.8 0 0 1 18 13.1a3.6 3.6 0 0 1 0 6.9z"/></svg>',
    nublado: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H7a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 10.4a4.3 4.3 0 0 1 .5 8.6z"/></svg>',
    chuva: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 15H7a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 6.4a4.3 4.3 0 0 1 .5 8.6z"/><path d="M8 18v2M12 18v3M16 18v2"/></svg>',
    trovoada: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 15H7a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 6.4a4.3 4.3 0 0 1 .5 8.6z"/><path d="m13 16-3 3.5h3L11 23"/></svg>',
    nevoeiro: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17.5 13H7a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 4.4a4.3 4.3 0 0 1 .5 8.6z"/><path d="M4 17h16M6 20h12"/></svg>',
    neve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 15H7a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 6.4a4.3 4.3 0 0 1 .5 8.6z"/><path d="M8 19h.01M12 21h.01M16 19h.01"/></svg>'
  };

  var dados = null;
  var ocupado = false;
  var ultimaCarga = 0;

  function icone(nome) {
    return ICONES[nome] || ICONES.nublado;
  }

  function numero(valor, casas) {
    return Number(valor).toLocaleString('pt-BR', {
      minimumFractionDigits: casas,
      maximumFractionDigits: casas
    });
  }

  function variacao(valor) {
    var sinal = valor > 0 ? '+' : (valor < 0 ? '\u2212' : '');
    return sinal + numero(Math.abs(valor), 2) + '%';
  }

  function hora(iso) {
    var data = new Date(iso);
    if (isNaN(data.getTime())) return '—';
    return data.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  function quando(iso) {
    if (!iso) return '';
    var data = new Date(iso);
    if (isNaN(data.getTime())) return '';
    var minutos = Math.round((Date.now() - data.getTime()) / 60000);
    if (minutos < 1) return 'agora';
    if (minutos < 60) return 'há ' + minutos + ' min';
    if (minutos < 24 * 60) return 'há ' + Math.round(minutos / 60) + ' h';
    if (minutos < 48 * 60) return 'ontem';
    return data.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  }

  function elemento(tag, classe, texto) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function urlSegura(url) {
    try {
      var alvo = new URL(url);
      return (alvo.protocol === 'http:' || alvo.protocol === 'https:') ? alvo.href : null;
    } catch (erro) {
      return null;
    }
  }

  function pintarPilula(info) {
    var tempo = info.tempo;
    if (tempo) {
      elPilulaIcone.innerHTML = icone(tempo.agora.icone);
      elTemp.textContent = tempo.agora.temp + '\u00b0';
    }
    var mercado = info.mercado || [];
    var dolar = mercado.filter(function (item) { return item.nome === 'Dólar'; })[0];
    var ibov = mercado.filter(function (item) { return item.nome === 'IBOV'; })[0];
    elCot.textContent = dolar ? 'US$ ' + numero(dolar.valor, 2) : '\u2014';
    elBolsa.textContent = ibov ? 'IBOV ' + numero(ibov.valor, 0) : '\u2014';
  }

  function pintarTempo(tempo) {
    elTempo.replaceChildren();
    elDias.replaceChildren();
    if (!tempo) {
      elTempo.appendChild(elemento('p', 'ilha-vazio', 'Tempo indisponível agora.'));
      return;
    }
    var agora = tempo.agora;
    var bloco = elemento('div', 'ilha-agora');
    var iconeAgora = elemento('span', 'ilha-agora-icone');
    iconeAgora.innerHTML = icone(agora.icone);
    var texto = elemento('div', 'ilha-agora-texto');
    texto.appendChild(elemento('div', 'ilha-agora-graus', agora.temp + '\u00b0'));
    texto.appendChild(elemento('div', 'ilha-agora-desc', agora.descricao));
    var extra = elemento('div', 'ilha-agora-extra');
    extra.appendChild(elemento('div', '', 'Sente ' + agora.sensacao + '\u00b0'));
    extra.appendChild(elemento('div', '', agora.umidade + '% umidade'));
    extra.appendChild(elemento('div', '', agora.vento + ' km/h'));
    bloco.appendChild(iconeAgora);
    bloco.appendChild(texto);
    bloco.appendChild(extra);
    elTempo.appendChild(bloco);

    (tempo.dias || []).forEach(function (dia) {
      var celula = elemento('div', 'ilha-dia');
      celula.appendChild(elemento('strong', '', dia.rotulo));
      var iconeDia = elemento('span', 'ilha-dia-icone');
      iconeDia.innerHTML = icone(dia.icone);
      iconeDia.title = dia.descricao;
      celula.appendChild(iconeDia);
      var temps = elemento('div');
      temps.appendChild(elemento('span', 'ilha-dia-max', dia.max + '\u00b0'));
      temps.appendChild(document.createTextNode(' '));
      temps.appendChild(elemento('span', 'ilha-dia-min', dia.min + '\u00b0'));
      celula.appendChild(temps);
      elDias.appendChild(celula);
    });
    if (tempo.desatualizado) elDias.title = 'Previsão de uma leitura anterior';
  }

  function pintarMercado(mercado, desatualizado) {
    elMercado.replaceChildren();
    if (!mercado || !mercado.length) {
      elMercado.appendChild(elemento('p', 'ilha-vazio', 'Mercado indisponível agora.'));
      return;
    }
    mercado.forEach(function (ativo) {
      var caixa = elemento('div', 'ilha-ativo');
      caixa.appendChild(elemento('div', 'ilha-ativo-nome', ativo.nome));
      caixa.appendChild(elemento('div', 'ilha-ativo-valor', numero(ativo.valor, ativo.casas)));
      var varEl = elemento('div', 'ilha-ativo-var', variacao(ativo.variacao));
      if (ativo.variacao > 0) varEl.classList.add('is-alta');
      if (ativo.variacao < 0) varEl.classList.add('is-baixa');
      caixa.appendChild(varEl);
      elMercado.appendChild(caixa);
    });
    if (desatualizado) elMercado.title = 'Valores de uma leitura anterior';
  }

  function pintarNoticias(noticias, desatualizado) {
    elNoticias.replaceChildren();
    if (!noticias || !noticias.length) {
      elNoticias.appendChild(elemento('p', 'ilha-vazio', 'Sem notícias agora.'));
      return;
    }
    noticias.forEach(function (noticia) {
      var alvo = urlSegura(noticia.url);
      if (!alvo) return;
      var link = elemento('a', 'ilha-noticia');
      link.href = alvo;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.appendChild(elemento('div', 'ilha-noticia-titulo', noticia.titulo));
      var meta = [noticia.fonte, quando(noticia.publicada)].filter(Boolean).join(' \u00b7 ');
      link.appendChild(elemento('div', 'ilha-noticia-fonte', meta));
      elNoticias.appendChild(link);
    });
    if (desatualizado) elNoticias.title = 'Manchetes de uma leitura anterior';
  }

  function pintarRodape(info) {
    elAtualizado.classList.remove('is-aviso');
    if (info.desatualizado) {
      elAtualizado.classList.add('is-aviso');
      elAtualizado.textContent = 'Sem ligação \u00b7 última leitura ' + hora(info.atualizado);
    } else {
      elAtualizado.textContent = 'Atualizado às ' + hora(info.atualizado);
    }
  }

  function pintar(info) {
    pintarPilula(info);
    pintarTempo(info.tempo);
    pintarMercado(info.mercado || [], info.mercado_desatualizado);
    pintarNoticias(info.noticias || [], info.noticias_desatualizado);
    pintarRodape(info);
  }

  function relogio() {
    try {
      elRelogio.textContent = new Intl.DateTimeFormat('pt-BR', {
        timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit'
      }).format(new Date());
    } catch (erro) {
      elRelogio.textContent = '';
    }
  }

  async function carregar(forcar) {
    if (ocupado) return;
    ocupado = true;
    botaoAtualizar.classList.add('is-ocupado');
    if (!dados) raiz.dataset.estado = 'carregando';
    try {
      var resposta = await fetch('/api/ilha' + (forcar ? '?forcar=1' : ''), {
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      });
      if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
      var json = await resposta.json();
      if (!json || !json.ok) throw new Error('sem dados');
      dados = json;
      ultimaCarga = Date.now();
      pintar(json);
      raiz.dataset.estado = 'pronto';
    } catch (erro) {
      raiz.dataset.estado = dados ? 'pronto' : 'erro';
      elAtualizado.classList.add('is-aviso');
      elAtualizado.textContent = dados
        ? 'Sem ligação \u00b7 última leitura ' + hora(dados.atualizado)
        : 'Sem ligação';
    } finally {
      ocupado = false;
      botaoAtualizar.classList.remove('is-ocupado');
    }
  }

  function estaFixo() {
    return raiz.classList.contains('is-fixo');
  }

  function fixar(estado) {
    raiz.classList.toggle('is-fixo', estado);
    botao.setAttribute('aria-expanded', estado ? 'true' : 'false');
  }

  botao.addEventListener('click', function (evento) {
    evento.preventDefault();
    fixar(!estaFixo());
  });

  document.addEventListener('keydown', function (evento) {
    if (evento.key === 'Escape' && estaFixo()) {
      fixar(false);
      botao.focus();
    }
  });

  document.addEventListener('click', function (evento) {
    if (estaFixo() && !raiz.contains(evento.target)) fixar(false);
  });

  botaoAtualizar.addEventListener('click', function () {
    carregar(true);
  });

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && Date.now() - ultimaCarga > 600000) carregar(false);
  });

  relogio();
  setInterval(relogio, 30000);

  var iniciar = function () { carregar(false); };
  if ('requestIdleCallback' in window) {
    requestIdleCallback(iniciar, { timeout: 2000 });
  } else {
    setTimeout(iniciar, 300);
  }
  setInterval(function () {
    if (!document.hidden) carregar(false);
  }, 600000);
})();

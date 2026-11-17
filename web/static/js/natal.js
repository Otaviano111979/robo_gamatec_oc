/* Vortex Sync — Tema de Natal
   Liga por padrão entre 01/dez e 06/jan. Fora da época, liga
   manualmente pelo botão da sidebar e desliga sozinho após 06/jan. */
(function () {
  "use strict";

  var CHAVE = "natal";

  function emEpoca(d) {
    var m = d.getMonth() + 1, dia = d.getDate();
    return m === 12 || (m === 1 && dia <= 6);
  }

  function ativo() {
    var pref = null;
    try { pref = localStorage.getItem(CHAVE); } catch (e) {}
    if (emEpoca(new Date())) return pref !== "0";
    if (pref === "1") {
      // ligado manualmente: válido até 06/jan; depois disso reseta
      if (new Date().getMonth() + 1 === 1 && new Date().getDate() > 6) {
        try { localStorage.removeItem(CHAVE); } catch (e) {}
        return false;
      }
      return true;
    }
    return false;
  }

  function aplicar() {
    var ligado = ativo();
    document.documentElement.classList.toggle("natal", ligado);
    if (ligado) { criarNeve(); criarGuirlanda(); }
    else { removerNeve(); removerGuirlanda(); }
    var btn = document.getElementById("natalToggle");
    if (btn) {
      btn.setAttribute("aria-pressed", ligado ? "true" : "false");
      btn.title = ligado ? "Desligar tema de Natal" : "Ligar tema de Natal";
    }
  }

  function criarNeve() {
    if (document.querySelector(".natal-neve")) return;
    var camada = document.createElement("div");
    camada.className = "natal-neve";
    camada.setAttribute("aria-hidden", "true");
    var total = window.innerWidth < 900 ? 8 : 14;
    for (var i = 0; i < total; i++) {
      var f = document.createElement("span");
      f.className = "floco" + (i % 5 === 0 ? " grande" : "");
      var tamanho = i % 5 === 0 ? 5 + Math.random() * 3 : 2 + Math.random() * 2.5;
      f.style.width = f.style.height = tamanho.toFixed(1) + "px";
      f.style.left = (Math.random() * 100).toFixed(2) + "%";
      f.style.animationDuration = (18 + Math.random() * 14).toFixed(1) + "s, " + (3 + Math.random() * 3).toFixed(1) + "s";
      f.style.animationDelay = (-Math.random() * 28).toFixed(1) + "s, " + (-Math.random() * 4).toFixed(1) + "s";
      f.style.setProperty("--ond", (10 + Math.random() * 26).toFixed(0) + "px");
      camada.appendChild(f);
    }
    document.body.appendChild(camada);
  }
  function removerNeve() {
    var c = document.querySelector(".natal-neve");
    if (c) c.remove();
  }

  function criarGuirlanda() {
    if (document.querySelector(".natal-guirlanda")) return;
    var sb = document.querySelector(".sidebar");
    if (!sb) return;
    var g = document.createElement("div");
    g.className = "natal-guirlanda";
    g.setAttribute("aria-hidden", "true");
    sb.insertBefore(g, sb.firstChild);
  }
  function removerGuirlanda() {
    var g = document.querySelector(".natal-guirlanda");
    if (g) g.remove();
  }

  function alternar() {
    var ligado = !document.documentElement.classList.contains("natal");
    try { localStorage.setItem(CHAVE, ligado ? "1" : "0"); } catch (e) {}
    aplicar();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", aplicar);
  } else {
    aplicar();
  }

  document.addEventListener("click", function (ev) {
    if (ev.target.closest("#natalToggle")) alternar();
  });
})();

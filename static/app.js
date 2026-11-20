const NOMES_DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const TITULO = document.title;
const RAIO_ANEL = 276.46;
const REDUZIR = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let usuario = null;
let timers = [];
let horariosNovos = [];
let alertasAtivos = false;
let audioCtx = null;
let idsVistos = new Set();
let assinaturas = {};
let dash = null, histCache = [], pctAnterior = 0;
const anteriores = {};
const posicionadores = [];

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

function h(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const f of filhos.flat()) if (f != null) e.append(f);   // texto sempre como texto (seguro)
  return e;
}

/* ---------- utilidades visuais ---------- */
function toast(msg, tipo = "ok") {
  const t = h("div", { class: "toast " + tipo, role: "status" }, msg);
  $("#toasts").append(t);
  setTimeout(() => { t.classList.add("saindo"); setTimeout(() => t.remove(), 320); }, 3600);
}

function carregando(btn, ligado) {
  btn.disabled = ligado;
  btn.classList.toggle("carregando", ligado);
}

function tremer(el) {
  el.classList.remove("tremer"); void el.offsetWidth; el.classList.add("tremer");
}

function animarNumero(el, de, para, sufixo = "%") {
  if (REDUZIR) { el.textContent = para + sufixo; return; }
  const ini = performance.now(), dur = 900;
  (function passo(agora) {
    const t = Math.min(1, (agora - ini) / dur), e = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(de + (para - de) * e) + sufixo;
    if (t < 1) requestAnimationFrame(passo);
  })(ini);
}

function confete(x, y) {
  if (REDUZIR) return;
  const cores = ["#5b9bff", "#38bdf8", "#a78bfa", "#ffd166", "#34d399"];
  for (let i = 0; i < 26; i++) {
    const p = h("span", { class: "confete" });
    p.style.left = x + "px"; p.style.top = y + "px"; p.style.background = cores[i % cores.length];
    document.body.append(p);
    const ang = Math.random() * Math.PI * 2, dist = 60 + Math.random() * 110;
    p.animate([
      { transform: "translate(0,0) rotate(0)", opacity: 1 },
      { transform: `translate(${Math.cos(ang) * dist}px, ${Math.sin(ang) * dist + 70}px) rotate(${Math.random() * 720}deg)`, opacity: 0 },
    ], { duration: 800 + Math.random() * 400, easing: "cubic-bezier(.2,.7,.3,1)" }).onfinish = () => p.remove();
  }
}

function sairDaTela(el, fn) {            // anima a saída e só depois executa a ação
  el.classList.add("saindo");
  setTimeout(fn, 280);
}

/* ---------- abas com indicador deslizante ---------- */
function ligarAbas(nav, aoMudar) {
  const botoes = [...nav.querySelectorAll("button[data-alvo]")];
  const ind = nav.querySelector(".indicador");
  const posicionar = () => {
    const a = nav.querySelector("button.ativa");
    if (a && a.offsetWidth) { ind.style.left = a.offsetLeft + "px"; ind.style.width = a.offsetWidth + "px"; }
  };
  botoes.forEach((b) => b.addEventListener("click", () => {
    botoes.forEach((x) => {
      x.classList.toggle("ativa", x === b);
      const p = document.getElementById(x.dataset.alvo);
      p.hidden = x !== b;
      if (x === b) { p.style.animation = "none"; void p.offsetWidth; p.style.animation = ""; }
    });
    posicionar();
    if (aoMudar) aoMudar(b.dataset.alvo);
  }));
  posicionar();
  posicionadores.push(posicionar);
}
window.addEventListener("resize", () => posicionadores.forEach((f) => f()));

/* ---------- API ---------- */
async function api(url, metodo = "GET", corpo) {
  const r = await fetch(url, {
    method: metodo, headers: { "Content-Type": "application/json" },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (r.status === 204) return null;
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && usuario) { mostrarAuth(); toast("Sua sessão expirou. Entre de novo.", "erro"); }
    throw new Error(dados.erro || "Algo deu errado.");
  }
  return dados;
}

async function acao(fn, btn) {
  if (btn) carregando(btn, true);
  try { await fn(); } catch (e) { toast(e.message, "erro"); }
  finally { if (btn) carregando(btn, false); }
  if (usuario) atualizarTudo();
}

/* ---------- telas ---------- */
function mostrarAuth() {
  pararSom();
  usuario = null;
  timers.forEach(clearInterval); timers = [];
  idsVistos = new Set(); assinaturas = {}; dash = null; histCache = [];
  document.title = TITULO;
  $("#tela-app").hidden = true;
  $("#tela-auth").hidden = false;
  posicionadores.forEach((f) => f());
}

function mostrarApp(u) {
  usuario = u;
  $("#tela-auth").hidden = true;
  $("#tela-app").hidden = false;
  $("#avatar").textContent = u.nome.trim().charAt(0).toUpperCase();
  $("#nome-usuario").textContent = u.nome.split(" ")[0];
  atualizarHero(); tickRelogio();
  $("#email-topo").textContent = u.email;
  atualizarPerfil();
  iniciarPerfilSom();
  posicionadores.forEach((f) => f());
  atualizarTudo();
  timers.push(setInterval(() => carregarAlarmes().catch(() => {}), 10000));
  timers.push(setInterval(() => { carregarDashboard().catch(() => {}); carregarHistorico().catch(() => {}); }, 60000));
  timers.push(setInterval(atualizarResumo, 30000));
  timers.push(setInterval(tickRelogio, 1000));
}

/* ---------- login / cadastro ---------- */
ligarAbas($("#abas-auth"), (alvo) => setTimeout(() => {
  const painel = document.getElementById(alvo);
  const campo = painel.querySelector(".passo.ativo input") || painel.querySelector("input");
  if (campo) campo.focus();
}, 80));

$$(".ver-senha").forEach((b) => b.addEventListener("click", () => {
  const campo = document.getElementById(b.dataset.alvo);
  campo.type = campo.type === "password" ? "text" : "password";
  b.textContent = campo.type === "password" ? "👁" : "🙈";
}));

function erroForm(form, msg) {
  form.querySelector(".msg-erro").textContent = msg;
  tremer($("#cartao-auth"));
}

$("#form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, btn = f.querySelector("button.principal");
  f.querySelector(".msg-erro").textContent = "";
  carregando(btn, true);
  try {
    const u = await api("/api/login", "POST", { email: $("#login-email").value, senha: $("#login-senha").value });
    f.reset(); mostrarApp(u);
  } catch (e) { erroForm(f, e.message); }
  finally { carregando(btn, false); }
});

/* ---------- cadastro em passos ---------- */
const fCad = $("#form-cadastro");
const PASSOS_CAD = ["Seu nome", "Seu e-mail", "Sua senha"];
const MSG_PASSO = ["Digite seu nome para continuar.", "Digite um e-mail válido para continuar."];
const DOMINIOS = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com.br", "icloud.com"];
const ERROS_DOMINIO = { "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmal.com": "gmail.com", "gmail.con": "gmail.com",
  "hotmial.com": "hotmail.com", "hotmail.con": "hotmail.com", "outlok.com": "outlook.com", "outlook.con": "outlook.com", "yaho.com.br": "yahoo.com.br" };
let passoCad = 0;

const nomeValido = () => $("#cad-nome").value.trim().length >= 2;
const emailValido = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);
const emailOk = () => emailValido($("#cad-email").value.trim());
const senhaOk = () => { const a = $("#cad-senha").value; return a.length >= 8 && a.length <= 128 && a === $("#cad-senha2").value; };
const VALIDA_PASSO = [nomeValido, emailOk, senhaOk];

function marcarCampo(idBox, estado) {            // estado: "ok" | "erro" | ""
  const box = document.getElementById(idBox);
  box.classList.toggle("ok", estado === "ok");
  box.classList.toggle("erro", estado === "erro");
  box.querySelector(".status").textContent = estado === "ok" ? "✓" : estado === "erro" ? "✕" : "";
}

function marcarProntoCad() {                     // o botão "pulsa" quando o passo está certo
  const pronto = VALIDA_PASSO[passoCad]();
  $("#cad-seguir").classList.toggle("pronto", pronto);
  $("#cad-enviar").classList.toggle("pronto", pronto);
}

function atualizarPassoCad(dir = 1, animar = true) {
  fCad.style.setProperty("--dx", (dir >= 0 ? 26 : -26) + "px");
  fCad.querySelectorAll(".passo").forEach((p) => {
    const ativo = +p.dataset.passo === passoCad;
    p.classList.toggle("ativo", ativo);
    if (ativo && animar) { p.style.animation = "none"; void p.offsetWidth; p.style.animation = ""; }
  });
  $$("#cad-passos i").forEach((b, i) => { b.classList.toggle("feito", i < passoCad); b.classList.toggle("atual", i === passoCad); });
  $("#cad-passo-txt").textContent = "Passo " + (passoCad + 1) + " de " + PASSOS_CAD.length;
  $("#cad-passo-nome").textContent = PASSOS_CAD[passoCad];
  const ultimo = passoCad === PASSOS_CAD.length - 1;
  $("#cad-voltar").hidden = passoCad === 0;
  $("#cad-seguir").hidden = ultimo;
  $("#cad-enviar").hidden = !ultimo;
  fCad.querySelector(".msg-erro").textContent = "";
  marcarProntoCad();
  if (animar) setTimeout(() => { const c = fCad.querySelector('.passo[data-passo="' + passoCad + '"] input'); if (c) c.focus(); }, 120);
}

function seguirCad() {
  if (!VALIDA_PASSO[passoCad]()) return erroForm(fCad, MSG_PASSO[passoCad]);
  passoCad++; atualizarPassoCad(1);
}
function voltarCad() { if (passoCad > 0) { passoCad--; atualizarPassoCad(-1); } }

$("#cad-seguir").addEventListener("click", seguirCad);
$("#cad-voltar").addEventListener("click", voltarCad);
fCad.addEventListener("keydown", (ev) => {      // Enter avança o passo (e envia no último)
  if (ev.key !== "Enter" || ev.target.tagName === "BUTTON") return;
  ev.preventDefault();
  if (passoCad < PASSOS_CAD.length - 1) seguirCad(); else fCad.requestSubmit();
});

$("#cad-nome").addEventListener("input", () => {
  const v = $("#cad-nome").value.trim(), primeiro = v.split(/\s+/)[0];
  $("#cad-saudacao").textContent = v.length >= 2 ? "Prazer, " + primeiro + "! 👋" : "Vamos começar! Como podemos te chamar?";
  marcarCampo("box-nome", v.length >= 2 ? "ok" : "");
  fCad.querySelector(".msg-erro").textContent = "";
  marcarProntoCad();
});

function atualizarEmailCad() {
  const v = $("#cad-email").value.trim(), arroba = v.indexOf("@");
  const local = arroba === -1 ? v : v.slice(0, arroba);
  const dom = arroba === -1 ? "" : v.slice(arroba + 1).toLowerCase();
  const aviso = $("#cad-email-aviso");
  let opcoes = [], msg = "", cls = "aviso-linha";
  if (ERROS_DOMINIO[dom]) {
    opcoes = [local + "@" + ERROS_DOMINIO[dom]];
    msg = "Será que você quis dizer " + opcoes[0] + "?"; cls += " erro";
  } else if (local && !dom.includes(".")) {
    opcoes = DOMINIOS.filter((d) => d.startsWith(dom)).slice(0, 4).map((d) => local + "@" + d);
  } else if (emailValido(v)) {
    msg = "Perfeito! Esse e-mail parece certo."; cls += " ok";
  }
  $("#cad-sugestoes").replaceChildren(...opcoes.map((o) => h("button", { type: "button", onclick: () => {
    $("#cad-email").value = o; atualizarEmailCad(); $("#cad-email").focus();
  } }, o)));
  aviso.className = cls; aviso.textContent = msg;
  marcarCampo("box-email", emailValido(v) ? "ok" : "");
  fCad.querySelector(".msg-erro").textContent = "";
  marcarProntoCad();
}
$("#cad-email").addEventListener("input", atualizarEmailCad);

function atualizarSenhaCad() {
  const a = $("#cad-senha").value, b = $("#cad-senha2").value;
  const r = { len: a.length >= 8, caixa: /[a-z]/.test(a) && /[A-Z]/.test(a), num: /\d/.test(a), sim: /[^A-Za-z0-9]/.test(a) };
  medirForca(a);
  $$("#cad-requisitos li").forEach((li) => li.classList.toggle("ok", !!r[li.dataset.r]));
  const aviso = $("#cad-senha-aviso");
  if (!b) { aviso.className = "aviso-linha"; aviso.textContent = ""; marcarCampo("box-senha2", ""); }
  else if (a === b) { aviso.className = "aviso-linha ok"; aviso.textContent = "As senhas conferem ✓"; marcarCampo("box-senha2", "ok"); }
  else { aviso.className = "aviso-linha erro"; aviso.textContent = "As senhas ainda não são iguais."; marcarCampo("box-senha2", "erro"); }
  fCad.querySelector(".msg-erro").textContent = "";
  marcarProntoCad();
}
$("#cad-senha").addEventListener("input", atualizarSenhaCad);
$("#cad-senha2").addEventListener("input", atualizarSenhaCad);
atualizarPassoCad(1, false);

function reiniciarCadastro() {
  passoCad = 0; atualizarPassoCad(-1, false);
  ["box-nome", "box-email", "box-senha2"].forEach((id) => marcarCampo(id, ""));
  $("#cad-saudacao").textContent = "Vamos começar! Como podemos te chamar?";
  $("#cad-sugestoes").replaceChildren();
  $("#cad-email-aviso").textContent = ""; $("#cad-senha-aviso").textContent = "";
  $$("#cad-requisitos li").forEach((li) => li.classList.remove("ok"));
  medirForca("");
}

fCad.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, btn = $("#cad-enviar");
  f.querySelector(".msg-erro").textContent = "";
  if (!nomeValido()) { passoCad = 0; atualizarPassoCad(-1); return erroForm(f, MSG_PASSO[0]); }
  if (!emailOk()) { passoCad = 1; atualizarPassoCad(-1); return erroForm(f, MSG_PASSO[1]); }
  const senha = $("#cad-senha").value;
  if (senha.length < 8) return erroForm(f, "A senha precisa ter pelo menos 8 caracteres.");
  if (senha !== $("#cad-senha2").value) return erroForm(f, "As senhas não são iguais.");
  carregando(btn, true);
  try {
    const u = await api("/api/cadastro", "POST", { nome: $("#cad-nome").value.trim(), email: $("#cad-email").value.trim(), senha });
    const r = btn.getBoundingClientRect();
    f.reset(); reiniciarCadastro(); mostrarApp(u);
    confete(r.left + r.width / 2, r.top);
    toast("Conta criada! Bem-vindo(a) ao LembraMed!, " + u.nome.split(" ")[0] + " 🎉");
  } catch (e) {
    if (/e-mail/i.test(e.message)) { passoCad = 1; atualizarPassoCad(-1); }   // problema no e-mail: volta para esse passo
    erroForm(f, e.message);
  } finally { carregando(btn, false); }
});

function medirForca(senha) {
  let pts = 0;
  if (senha.length >= 8) pts++;
  if (senha.length >= 12) pts++;
  if (/[a-z]/.test(senha) && /[A-Z]/.test(senha)) pts++;
  if (/\d/.test(senha)) pts++;
  if (/[^A-Za-z0-9]/.test(senha)) pts++;
  if (!senha) pts = 0;
  const niveis = [["0%", "transparent", "\u00a0"], ["20%", "#c0392b", "Muito fraca"], ["40%", "#e67e22", "Fraca"],
                  ["60%", "#f1c40f", "Média"], ["80%", "#2bb87a", "Boa"], ["100%", "#1f8a5b", "Forte"]];
  const [larg, cor, txt] = niveis[pts];
  $("#forca-barra").style.width = larg; $("#forca-barra").style.background = cor;
  $("#forca-texto").textContent = txt;
}

$("#btn-sair").addEventListener("click", async () => {
  try { await api("/api/logout", "POST"); } catch (e) {}
  mostrarAuth();
  toast("Até logo! 👋");
});

/* ---------- tema ---------- */
function aplicarTema(t) {
  document.documentElement.dataset.tema = t;
  $("#btn-tema").textContent = t === "escuro" ? "☀️" : "🌙";
}
(function iniciarTema() {
  let t = null;
  try { t = localStorage.getItem("tema"); } catch (e) {}
  aplicarTema(t || "escuro");
})();
$("#btn-tema").addEventListener("click", () => {
  const novo = document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro";
  aplicarTema(novo);
  try { localStorage.setItem("tema", novo); } catch (e) {}
});

/* ---------- helpers de dados ---------- */
function descreverDias(d) { return d === "0123456" ? "todos os dias" : [...d].map((n) => NOMES_DIAS[+n]).join(", "); }
function dataLocalISO(d = new Date()) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function mudou(chave, dados) {            // só redesenha (e anima) quando algo mudou de verdade
  const s = JSON.stringify(dados);
  if (assinaturas[chave] === s) return false;
  assinaturas[chave] = s; return true;
}

/* ---------- alarmes ---------- */
/* ---------- som do alarme ---------- */
const SONS = [
  ["horizonte", "🌅 Horizonte", "celular"], ["galaxia", "🌌 Galáxia", "celular"], ["flor", "🌸 Flor da manhã", "celular"],
  ["marimba", "🎹 Marimba", "celular"], ["radar", "📡 Radar", "celular"], ["cristal", "💎 Reflexo", "celular"],
  ["harpa", "🎶 Harpa", "celular"], ["bolhas", "🫧 Bolhas", "celular"],
  ["telefone", "📞 Telefone", "classico"], ["bip", "🔔 Bip", "classico"], ["sino", "🛎️ Sino", "classico"],
  ["sirene", "🚨 Sirene", "classico"], ["digital", "⌚ Digital", "classico"], ["suave", "🎵 Suave", "classico"],
  ["despertador", "⏰ Despertador", "classico"], ["alerta", "⚠️ Alerta urgente", "classico"], ["pulso", "💓 Pulso", "classico"],
];
const GRUPOS_SOM = [["celular", "Estilo celular"], ["classico", "Clássicos"]];
const DURACOES = [[5, "5 s"], [10, "10 s"], [20, "20 s"], [30, "30 s"], [60, "1 min"], ["ate", "Até confirmar"]];
const SOM_PADRAO = { tipo: "horizonte", altura: 50, volume: 70, duracao: 20 };
let somCfg = { ...SOM_PADRAO };
let somAtual = null;

function chaveSom() { return "somAlarme:" + (usuario ? usuario.id : "0"); }
function carregarSomCfg() {
  let v = {};
  try { v = JSON.parse(localStorage.getItem(chaveSom())) || {}; } catch (e) {}
  if (usuario && usuario.prefs_som && usuario.prefs_som.tipo) v = usuario.prefs_som; // a conta vale em qualquer aparelho
  const num = (x, min, max, pad_) => (Number.isFinite(+x) && x !== null ? Math.min(max, Math.max(min, +x)) : pad_);
  somCfg = {
    tipo: SONS.some(([k]) => k === v.tipo) ? v.tipo : SOM_PADRAO.tipo,
    altura: num(v.altura, 0, 100, SOM_PADRAO.altura),
    volume: num(v.volume, 0, 100, SOM_PADRAO.volume),
    duracao: DURACOES.some(([k]) => k === v.duracao) ? v.duracao : SOM_PADRAO.duracao,
    voz: v.voz !== false,                                   // anunciar o remédio por voz (ligado por padrão)
  };
}
function salvarSomCfg() {
  try { localStorage.setItem(chaveSom(), JSON.stringify(somCfg)); } catch (e) {}
  api("/api/eu/som", "PUT", somCfg).then(u => { usuario = u; }).catch(() => {});
  const el = $("#som-salvo"); el.textContent = "Salvo ✓";
  clearTimeout(salvarSomCfg.t); salvarSomCfg.t = setTimeout(() => (el.textContent = ""), 1500);
}

function garantirAudio() {
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
}

function nota(ctx, destino, t, dur, freq, onda, pico) {
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = onda; o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(pico, t + 0.015);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g); g.connect(destino); o.start(t); o.stop(t + dur + 0.02);
}

// Vozes de instrumento (síntese aditiva): cada nota soma alguns parciais com envelopes diferentes.
function parcial(ctx, saidas, t, freq, onda, pico, atk, dur) {
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = onda; o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.linearRampToValueAtTime(pico, t + atk);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g); saidas.forEach((x) => g.connect(x));
  o.start(t); o.stop(t + dur + 0.05);
}
const TIMBRES = {
  marimba: (c, s, t, f, p, k) => { parcial(c, s, t, f, "sine", p, 0.003, 0.5 * k); parcial(c, s, t, f * 4, "sine", p * 0.3, 0.002, 0.1 * k); },
  piano: (c, s, t, f, p, k) => { parcial(c, s, t, f, "triangle", p, 0.005, 1.2 * k); parcial(c, s, t, f * 2, "sine", p * 0.35, 0.004, 0.6 * k); parcial(c, s, t, f * 3, "sine", p * 0.12, 0.003, 0.3 * k); },
  cristal: (c, s, t, f, p, k) => { parcial(c, s, t, f, "sine", p, 0.003, 1.5 * k); parcial(c, s, t, f * 2.76, "sine", p * 0.28, 0.002, 0.7 * k); parcial(c, s, t, f * 5.4, "sine", p * 0.1, 0.002, 0.35 * k); },
  harpa: (c, s, t, f, p, k) => { parcial(c, s, t, f, "triangle", p, 0.002, 0.9 * k); parcial(c, s, t, f * 2, "sine", p * 0.3, 0.002, 0.45 * k); },
};
// Toca uma sequência: notas em semitons a partir do Dó 5 (null = pausa); passo 0 = acorde. e = barramento de eco.
function seq(c, d, e, t, timbre, m, notas, passo, pico, k = 1) {
  notas.forEach((st, i) => { if (st !== null) TIMBRES[timbre](c, [d, e], t + i * passo, 523.25 * m * Math.pow(2, st / 12), pico, k); });
}

// Cada som é um "ciclo" que se repete durante o tempo escolhido. m = multiplicador da altura (0,5x a 2x).
const CICLOS = {
  bip: { periodo: 1.4, tocar: (c, d, t, m) => [0, 1, 2].forEach((i) => nota(c, d, t + i * 0.38, 0.28, 880 * m, "triangle", 0.8)) },
  sino: { periodo: 3.2, tocar: (c, d, t, m) => [[1, 1], [2.76, 0.45], [5.4, 0.2]].forEach(([r, p]) => nota(c, d, t, 2.6, 660 * m * r, "sine", p * 0.8)) },
  sirene: { periodo: 1.8, tocar: (c, d, t, m) => {
    const o = c.createOscillator(), g = c.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(500 * m, t); o.frequency.linearRampToValueAtTime(950 * m, t + 0.9); o.frequency.linearRampToValueAtTime(500 * m, t + 1.8);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.6, t + 0.05);
    g.gain.setValueAtTime(0.6, t + 1.7); g.gain.exponentialRampToValueAtTime(0.0001, t + 1.8);
    o.connect(g); g.connect(d); o.start(t); o.stop(t + 1.85);
  } },
  digital: { periodo: 1.0, tocar: (c, d, t, m) => [0, 1, 2, 3].forEach((i) => nota(c, d, t + i * 0.13, 0.07, 1000 * m, "square", 0.25)) },
  suave: { periodo: 3.0, tocar: (c, d, t, m) => [1, 1.26, 1.5].forEach((r, i) => nota(c, d, t + i * 0.5, 0.9, 523 * m * r, "sine", 0.7)) },
  despertador: { periodo: 2.0, tocar: (c, d, t, m) => { for (let i = 0; i < 16; i++) nota(c, d, t + i * 0.05, 0.035, 1400 * m, "square", 0.22); } },
  horizonte: { periodo: 5.0, tocar: (c, d, t, m, e) => {
    seq(c, d, e, t, "piano", m, [4, 7, 12, 11, 9, 7, 9, 11, 12, 16, 14, 12, 11, 9, 7, 4], 0.2, 0.55);
    seq(c, d, e, t, "piano", m, [-12, null, null, null, -5], 0.4, 0.45, 1.4);
  } },
  galaxia: { periodo: 4.2, tocar: (c, d, t, m, e) => {
    seq(c, d, e, t, "cristal", m, [0, 7, 12, 16, 19, 24, 19, 16], 0.16, 0.5, 1.6);
    seq(c, d, e, t + 1.4, "cristal", m, [28, 24, 31], 0.22, 0.3, 1.2);
  } },
  flor: { periodo: 3.6, tocar: (c, d, t, m, e) => {
    [[0, [12, 16, 19]], [0.5, [14, 17, 21]], [1.0, [16, 19, 23]], [1.5, [19, 23, 26]]]
      .forEach(([dt, acorde]) => seq(c, d, e, t + dt, "cristal", m, acorde, 0, 0.38, 1.3));
  } },
  marimba: { periodo: 2.6, tocar: (c, d, t, m, e) => seq(c, d, e, t, "marimba", m, [0, 4, 7, 12, 7, 4, 0, 4, 7, 12, 16, 12], 0.12, 0.75) },
  radar: { periodo: 2.0, tocar: (c, d, t, m, e) => [0, 0.34].forEach((dt) => {
    const ini = t + dt, o = c.createOscillator(), g = c.createGain();
    o.type = "sine"; o.frequency.setValueAtTime(700 * m, ini); o.frequency.exponentialRampToValueAtTime(1500 * m, ini + 0.22);
    g.gain.setValueAtTime(0.0001, ini); g.gain.exponentialRampToValueAtTime(0.7, ini + 0.03); g.gain.exponentialRampToValueAtTime(0.0001, ini + 0.5);
    o.connect(g); g.connect(d); g.connect(e); o.start(ini); o.stop(ini + 0.55);
  }) },
  cristal: { periodo: 3.4, tocar: (c, d, t, m, e) => seq(c, d, e, t, "cristal", m, [12, 7, 16, 14, 19, 16], 0.3, 0.55, 1.3) },
  harpa: { periodo: 3.6, tocar: (c, d, t, m, e) => {
    seq(c, d, e, t, "harpa", m, [-5, 0, 4, 7, 12, 16, 19, 24], 0.085, 0.5);
    seq(c, d, e, t + 1.1, "harpa", m, [19, 16, 12, 7, 4, 0], 0.12, 0.45);
  } },
  bolhas: { periodo: 2.2, tocar: (c, d, t, m, e) => [0, 0.14, 0.33, 0.5, 0.78].forEach((dt, i) => {
    const ini = t + dt, f0 = (520 + i * 110) * m, o = c.createOscillator(), g = c.createGain();
    o.type = "sine"; o.frequency.setValueAtTime(f0, ini); o.frequency.exponentialRampToValueAtTime(f0 * 1.9, ini + 0.09);
    g.gain.setValueAtTime(0.0001, ini); g.gain.exponentialRampToValueAtTime(0.65, ini + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, ini + 0.18);
    o.connect(g); g.connect(d); g.connect(e); o.start(ini); o.stop(ini + 0.2);
  }) },
  telefone: { periodo: 3.0, tocar: (c, d, t, m) => [0, 0.6].forEach((dt) => {
    const ini = t + dt, g = c.createGain(), trem = c.createGain(), lfo = c.createOscillator(), lg = c.createGain();
    g.gain.setValueAtTime(0.0001, ini); g.gain.linearRampToValueAtTime(0.45, ini + 0.02);
    g.gain.setValueAtTime(0.45, ini + 0.38); g.gain.linearRampToValueAtTime(0.0001, ini + 0.42);
    trem.gain.value = 0.5; lfo.frequency.value = 25; lg.gain.value = 0.5; lfo.connect(lg); lg.connect(trem.gain);
    for (const f of [440, 480]) { const o = c.createOscillator(); o.type = "sine"; o.frequency.value = f * m; o.connect(g); o.start(ini); o.stop(ini + 0.45); }
    g.connect(trem); trem.connect(d); lfo.start(ini); lfo.stop(ini + 0.45);
  }) },
  alerta: { periodo: 1.2, tocar: (c, d, t, m) => [0, 0.55].forEach((off) =>
    [900, 1100, 1320].forEach((f, i) => nota(c, d, t + off + i * 0.15, 0.12, f * m, "square", 0.22))) },
  pulso: { periodo: 1.3, tocar: (c, d, t, m) => [0, 0.24].forEach((dt, i) => {
    const ini = t + dt;
    [[1, "sine", 0.95], [2, "triangle", 0.3]].forEach(([mul, onda, pico]) => {
      const o = c.createOscillator(), g = c.createGain();
      o.type = onda; o.frequency.setValueAtTime(260 * m * mul, ini); o.frequency.exponentialRampToValueAtTime(90 * m * mul, ini + 0.16);
      g.gain.setValueAtTime(0.0001, ini); g.gain.exponentialRampToValueAtTime(pico * (i ? 0.75 : 1), ini + 0.015); g.gain.exponentialRampToValueAtTime(0.0001, ini + 0.3);
      o.connect(g); g.connect(d); o.start(ini); o.stop(ini + 0.32);
    });
  }) },
};

function atualizarBotaoSilenciar() { $("#btn-silenciar").hidden = !somAtual; }

function pararSom() {
  if (somAtual) somAtual.parar();
  if ("speechSynthesis" in window) speechSynthesis.cancel();   // silenciar também interrompe a voz
}

// ---------- voz: fala qual remédio tomar e a dosagem ----------
function textoDoAlarme(lista) {
  const partes = lista.map((a) => a.nome + (a.dosagem ? ", " + a.dosagem : ""));
  return "Hora do remédio. " + partes.map((p) => "Tome " + p + ".").join(" ");
}
function falar(texto) {
  if (!("speechSynthesis" in window) || !somCfg.voz) return false;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(texto);
  u.lang = "pt-BR"; u.rate = 0.9; u.volume = 1;
  const v = speechSynthesis.getVoices().find((x) => x.lang && x.lang.toLowerCase().startsWith("pt"));
  if (v) u.voice = v;
  speechSynthesis.speak(u);
  return true;
}
function falarAlarmes(lista) {
  if (!lista.length) return;
  setTimeout(() => falar(textoDoAlarme(lista)), 2500);   // logo depois do início do alarme sonoro
}

function iniciarSom(cfg, segundos) {
  pararSom();
  garantirAudio();
  const ctx = audioCtx, mestre = ctx.createGain(), comp = ctx.createDynamicsCompressor();
  mestre.gain.value = (cfg.volume / 100) * 0.7;
  comp.threshold.value = -8; comp.knee.value = 8; comp.ratio.value = 6;     // evita estourar quando várias notas soam juntas
  mestre.connect(comp); comp.connect(ctx.destination);
  const eco = ctx.createGain(), atraso = ctx.createDelay(1), retorno = ctx.createGain();   // eco compartilhado: dá "ar" aos toques melódicos
  eco.gain.value = 0.32; atraso.delayTime.value = 0.26; retorno.gain.value = 0.32;
  eco.connect(atraso); atraso.connect(retorno); retorno.connect(atraso); atraso.connect(mestre);
  const ciclo = CICLOS[cfg.tipo] || CICLOS.bip, mult = Math.pow(2, (cfg.altura - 50) / 50);
  const fim = ctx.currentTime + segundos;
  let prox = ctx.currentTime + 0.05;
  const agendar = () => { while (prox < fim && prox < ctx.currentTime + 3) { ciclo.tocar(ctx, mestre, prox, mult, eco); prox += ciclo.periodo; } };
  const timer = setInterval(agendar, 400);
  agendar();
  const objeto = { parar() {
    clearInterval(timer); clearTimeout(fimTimer);
    mestre.gain.cancelScheduledValues(ctx.currentTime); mestre.gain.setTargetAtTime(0, ctx.currentTime, 0.03);
    setTimeout(() => { mestre.disconnect(); comp.disconnect(); }, 400);
    if (somAtual === objeto) { somAtual = null; atualizarBotaoSilenciar(); }
  } };
  const fimTimer = setTimeout(() => clearInterval(timer), segundos * 1000);
  somAtual = objeto; atualizarBotaoSilenciar();
  return objeto;
}

function iniciarSomAlarme() {
  iniciarSom(somCfg, somCfg.duracao === "ate" ? 300 : somCfg.duracao);
}
function previaSom(segundos = 2.5) { iniciarSom(somCfg, segundos); }

function atualizarStatusSom() {
  $("#som-status").textContent = alertasAtivos
    ? "Som dos alarmes ativado nesta página ✓"
    : "Som desativado nesta página. Clique em “Ativar som e aviso no navegador” na aba Hoje.";
}

function montarSons() {                      // lista de sons separada por grupos
  const box = $("#seg-som");
  box.replaceChildren(...GRUPOS_SOM.flatMap(([grupo, titulo]) => [
    h("div", { class: "grupo-som-titulo" }, titulo),
    h("div", { class: "seg" }, SONS.filter((x) => x[2] === grupo).map(([valor, rotulo]) => {
      const b = h("button", { type: "button", class: valor === somCfg.tipo ? "ativa" : "" }, rotulo);
      b.addEventListener("click", () => {
        box.querySelectorAll("button").forEach((x) => x.classList.toggle("ativa", x === b));
        somCfg.tipo = valor; salvarSomCfg(); previaSom();
      });
      return b;
    })),
  ]));
}

function iniciarPerfilSom() {
  carregarSomCfg();
  $("#voz-ativa").checked = somCfg.voz;
  montarSons();
  montarSeg("seg-duracao", DURACOES, somCfg.duracao, (v) => { somCfg.duracao = v; salvarSomCfg(); });
  for (const [id, chave] of [["#som-altura", "altura"], ["#som-volume", "volume"]]) {
    const el = $(id); el.value = somCfg[chave];
    el.oninput = () => { somCfg[chave] = +el.value; salvarSomCfg(); };
    el.onchange = () => previaSom();
  }
  atualizarStatusSom();
}

$("#btn-testar-som").addEventListener("click", () => previaSom(somCfg.duracao === "ate" ? 6 : Math.min(somCfg.duracao, 8)));
$("#btn-parar-som").addEventListener("click", pararSom);
$("#voz-ativa").addEventListener("change", (e) => { somCfg.voz = e.target.checked; salvarSomCfg(); });
$("#btn-testar-voz").addEventListener("click", () => {
  const ok = "speechSynthesis" in window;
  const antes = somCfg.voz; somCfg.voz = true;
  if (ok) falar(textoDoAlarme([{ nome: "Exemplo de remédio", dosagem: "1 comprimido" }]));
  somCfg.voz = antes;
  toast(ok ? "Falando… se não ouviu nada, aumente o volume do aparelho." : "Este navegador não tem voz.");
});
$("#btn-silenciar").addEventListener("click", pararSom);

function avisarNavegador(novos) {
  if (!alertasAtivos || !novos.length) return;
  iniciarSomAlarme();
  falarAlarmes(novos);
  if (navigator.vibrate) navigator.vibrate([400, 200, 400, 200, 400]);   // ajuda quem não escuta o alarme
  for (const a of novos) if ("Notification" in window && Notification.permission === "granted")
    new Notification("LembraMed! 💊 Hora do remédio", { body: a.nome + (a.dosagem ? " — " + a.dosagem : "") + " (" + a.hora + ")" });
}

async function carregarAlarmes() {
  const lista = await api("/alarmes/pendentes");
  avisarNavegador(lista.filter((a) => !idsVistos.has(a.id)));   // novo, ou voltou depois de adiado
  idsVistos = new Set(lista.map((a) => a.id));
  if (!lista.length) pararSom();                                // nada mais tocando: silencia
  document.title = lista.length ? "(" + lista.length + ") Hora do remédio!" : TITULO;
  if (!mudou("alarmes", lista)) return;

  const box = $("#alarmes");
  box.replaceChildren();
  if (!lista.length) { box.append(h("p", { class: "vazio" }, "Nenhum alarme no momento. 🎉")); return; }
  lista.forEach((a, i) => {
    const minutos = h("select", { style: "width:auto" }, [5, 10, 15, 30].map((m) => h("option", { value: m }, m + " min")));
    minutos.value = "10";
    const card = h("div", { class: "alarme", style: "animation-delay:" + i * 80 + "ms" },
      h("div", { class: "nome" }, h("span", { class: "sino" }, "🔔"), " " + a.nome + (a.dosagem ? " — " + a.dosagem : "")),
      h("div", { class: "detalhe" }, "Horário: " + a.hora + (a.observacoes ? " · " + a.observacoes : "")),
      h("div", { class: "linha" },
        h("button", { class: "principal", onclick: (ev) => {
          const r = ev.currentTarget.getBoundingClientRect();
          confete(r.left + r.width / 2, r.top + r.height / 2);
          acao(() => api("/registros/" + a.id + "/tomado", "POST").then(() => toast("Boa! Dose registrada ✔")));
        } }, "✔ Já tomei"),
        h("span", { class: "pequeno" }, "ou adiar"), minutos,
        h("button", { onclick: () => acao(() => api("/registros/" + a.id + "/adiar", "POST", { minutos: +minutos.value })
          .then(() => toast("Adiado por " + minutos.value + " min ⏳"))) }, "Adiar")));
    box.append(card);
  });
}

/* ---------- dashboard de cronogramas ---------- */
function fmtData(iso) { return iso.slice(8, 10) + "/" + iso.slice(5, 7); }

async function carregarDashboard() {
  dash = await api("/api/dashboard");
  atualizarResumo();
  if (!mudou("dash", dash)) return;
  desenharStats(); desenharSemana(); desenharTratamentos();
}

function contar(id, para, sufixo = "") {
  const el = document.getElementById(id);
  animarNumero(el, anteriores[id] || 0, para, sufixo);
  anteriores[id] = para;
}

function desenharStats() {
  const a = dash.adesao;
  if (a.pct === null) { $("#st-adesao").textContent = "—"; anteriores["st-adesao"] = 0; }
  else contar("st-adesao", a.pct, "%");
  contar("st-ativos", dash.tratamentos.filter((t) => !t.concluido).length);
  $("#st-doses").textContent = a.tomadas + "/" + a.esperadas;
}

function desenharSemana() {
  const box = $("#semana");
  box.replaceChildren();
  const porDia = {};
  for (const d of dash.doses) (porDia[d.data] = porDia[d.data] || []).push(d);
  const rot = { tomado: "Tomado", perdido: "Perdido", pendente: "Pendente", futuro: "Agendado" };
  dash.semana_datas.forEach((iso, i) => {
    const doses = porDia[iso] || [];
    box.append(h("div", { class: "dia-col" + (iso === dash.hoje ? " hoje" : "") + (iso < dash.hoje ? " passado" : ""), style: "--i:" + i },
      h("div", { class: "dia-topo" }, h("b", {}, NOMES_DIAS[i]), h("span", {}, fmtData(iso))),
      doses.length ? doses.map((d) =>
        h("div", { class: "dose st-" + d.status, title: d.nome + (d.dosagem ? " — " + d.dosagem : "") + " · " + rot[d.status] },
          h("span", { class: "dose-h" }, d.hora), h("span", { class: "dose-n" }, d.nome), d.status === "tomado" ? "✓" : ""))
        : h("p", { class: "dia-vazio" }, "—")));
  });
}

function desenharTratamentos() {
  const box = $("#medicamentos");
  box.replaceChildren();
  if (!dash.tratamentos.length) {
    box.append(h("p", { class: "vazio" }, "Nenhum cronograma ainda. Clique em “Novo cronograma”."));
    return;
  }
  dash.tratamentos.forEach((m, i) => {
    let etiqueta;
    if (m.concluido) etiqueta = h("span", { class: "etiqueta fim" }, "Concluído");
    else if (m.aguardando) etiqueta = h("span", { class: "etiqueta ag" }, "Começa em " + fmtData(m.data_inicio));
    else if (m.intervalo_horas) etiqueta = h("span", { class: "etiqueta" }, "A cada " + m.intervalo_horas + " h");
    else if (m.continuo) etiqueta = h("span", { class: "etiqueta" }, "Uso contínuo");
    else etiqueta = h("span", { class: "etiqueta" }, "Dia " + m.dia_atual + " de " + m.total_dias);

    const chips = m.horarios.map((x) => {
      const chip = h("span", { class: "chip", title: descreverDias(x.dias_semana) }, x.hora + " · " + descreverDias(x.dias_semana));
      chip.append(h("button", { title: "Remover horário", onclick: () => sairDaTela(chip, () => acao(() => api("/horarios/" + x.id, "DELETE"))) }, "×"));
      return chip;
    });
    const fill = h("i");
    const pct = m.doses_total ? Math.round((m.doses_tomadas / m.doses_total) * 100)
      : m.total_dias ? Math.round(((m.concluido ? m.total_dias : m.dia_atual) / m.total_dias) * 100) : 0;
    const card = h("div", { class: "med entra", style: "--i:" + i },
      h("div", { class: "med-topo" },
        h("div", {}, h("strong", {}, m.nome), m.dosagem ? " — " + m.dosagem : "", etiqueta,
          m.observacoes ? h("div", { class: "pequeno" }, m.observacoes) : null,
          m.data_fim ? h("div", { class: "pequeno" }, fmtData(m.data_inicio) + " a " + fmtData(m.data_fim) + (m.doses_total ? " · " + m.doses_tomadas + " de " + m.doses_total + " doses tomadas" : "")) : null),
        h("button", { class: "perigo", onclick: () => {
          if (confirm("Remover " + m.nome + "?")) sairDaTela(card, () => acao(() => api("/medicamentos/" + m.med_id, "DELETE").then(() => toast("Cronograma removido"))));
        } }, "Remover")),
      (m.doses_total || m.total_dias) ? h("div", { class: "barra" }, fill) : null,
      m.intervalo_horas
        ? h("div", {}, h("span", { class: "pequeno" }, "Próximas: "),
            m.proximas.length ? m.proximas.map((x) => h("span", { class: "dose-chip" }, rotuloDose(new Date(x.data + "T" + x.hora + ":00"))))
              : h("span", { class: "pequeno" }, m.concluido ? "Tratamento concluído" : "—"))
        : h("div", {}, chips.length ? chips : h("span", { class: "pequeno" }, "Sem horários")));
    box.append(card);
    setTimeout(() => (fill.style.width = pct + "%"), 80);
  });
}

/* ---------- histórico ---------- */
let histTodos = [], histDias = 30;

async function carregarHistorico() {
  histTodos = await api("/historico?dias=30");
  if (!mudou("hist", histTodos)) return;
  desenharHistorico();
}

function desenharHistorico() {
  const desde = addDias(dataLocalISO(), -histDias);
  const itens = histTodos.filter((i) => i.data_prevista >= desde);
  const cont = (st) => itens.filter((i) => i.status === st).length;
  const tom = cont("tomado"), per = cont("perdido"), pen = cont("pendente");
  $("#hist-resumo").textContent = itens.length
    ? "Últimos " + histDias + " dias: " + tom + " tomadas · " + per + " perdidas" + (pen ? " · " + pen + " pendentes" : "") +
      " · adesão " + Math.round((tom / (tom + per + pen)) * 100) + "%"
    : "";
  const box = $("#historico");
  box.replaceChildren();
  if (!itens.length) { box.append(h("p", { class: "vazio" }, "Ainda não há registros neste período.")); return; }
  const rotulo = { tomado: "Tomado ✓", perdido: "Perdido", pendente: "Pendente" };
  box.append(h("div", { style: "overflow-x:auto" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Dia", "Hora", "Remédio", "Situação"].map((t) => h("th", {}, t)))),
    h("tbody", {}, itens.map((i, n) => h("tr", { style: "--i:" + Math.min(n, 15) },
      h("td", {}, fmtData(i.data_prevista)),
      h("td", {}, i.hora),
      h("td", {}, i.nome + (i.dosagem ? " (" + i.dosagem + ")" : "")),
      h("td", {}, h("span", { class: "badge b-" + i.status }, rotulo[i.status])))))
  )));
}

/* ---------- resumo do dia + próxima dose ---------- */
function atualizarResumo() {
  if (!usuario || !dash) return;
  const hoje = dash.doses.filter((d) => d.data === dash.hoje);
  const previstos = hoje.length, tomados = hoje.filter((d) => d.status === "tomado").length;
  const pct = previstos ? Math.round((tomados / previstos) * 100) : 0;
  $("#anel-prog").style.strokeDashoffset = RAIO_ANEL * (1 - pct / 100);
  if (pct !== pctAnterior) { animarNumero($("#anel-num"), pctAnterior, pct); pctAnterior = pct; }
  else $("#anel-num").textContent = pct + "%";
  $("#resumo-texto").textContent = previstos
    ? tomados + " de " + previstos + (previstos === 1 ? " dose" : " doses") + " tomadas hoje."
    : "Nenhuma dose prevista para hoje.";

  desenharProxima();
}

function desenharProxima() {
  const el = $("#proximo"), hero = $("#hero-proxima"), p = dash && dash.proxima;
  if (!usuario || !p) { el.hidden = true; hero.hidden = true; return; }
  const quando = new Date(p.quando), agora = new Date();
  const min = Math.max(1, Math.round((quando - agora) / 60000));
  const amanha = dataLocalISO(new Date(agora.getTime() + 86400000));
  let em;
  if (min < 60) em = "em " + min + " min";
  else if (p.data === dataLocalISO(agora)) em = "em " + Math.floor(min / 60) + " h " + (min % 60) + " min";
  else em = p.data === amanha ? "amanhã" : NOMES_DIAS[(quando.getDay() + 6) % 7];
  const txt = "⏭ Próxima: " + p.nome + " às " + p.hora + " (" + em + ")";
  for (const x of [el, hero]) { x.hidden = false; if (x.textContent !== txt) x.textContent = txt; }
}

function atualizarHero() {
  if (!usuario) return;
  const d = new Date(), hr = d.getHours();
  const [saud, emoji] = hr < 5 ? ["Boa madrugada", "🌌"] : hr < 12 ? ["Bom dia", "☀️"] : hr < 18 ? ["Boa tarde", "🌤️"] : ["Boa noite", "🌙"];
  $("#ola").textContent = saud + ", " + usuario.nome.split(" ")[0];
  $("#ola-emoji").textContent = emoji;
  const dt = d.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  $("#hero-data").textContent = dt.charAt(0).toUpperCase() + dt.slice(1);
}

function tickRelogio() {
  const d = new Date();
  $("#rel-hm").textContent = pad(d.getHours()) + ":" + pad(d.getMinutes());
  $("#rel-s").textContent = ":" + pad(d.getSeconds());
  desenharProxima();
  if (d.getSeconds() === 0) atualizarHero();
}

/* ---------- assistente de novo cronograma ---------- */
const FREQS = [[1, "1× ao dia"], [2, "2× ao dia"], [3, "3× ao dia"], [4, "4× ao dia"], [6, "6× ao dia"], [0, "Personalizado"]];
const W = { modo: "intervalo", x: 6, agora: true, n: 3, dur: "periodo", custom: [] };
const pad = (n) => String(n).padStart(2, "0");
const diasSelecionados = () => $$("#dias input:checked").map((c) => c.value);

function addDias(iso, n) {
  const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return dataLocalISO(d);
}

function calcularHorarios() {
  if (W.n === 0) return [...W.custom].sort();
  const [a, b] = ($("#c-primeiro").value || "08:00").split(":").map(Number);
  const passo = 24 / W.n, set = new Set();
  for (let k = 0; k < W.n; k++) {
    const min = (a * 60 + b + Math.round(k * passo * 60)) % 1440;
    set.add(pad(Math.floor(min / 60)) + ":" + pad(min % 60));
  }
  return [...set].sort();
}

function calcularPeriodo() {
  const ini = $("#c-inicio").value || dataLocalISO();
  if (W.dur === "continuo") return { ini, fim: null, dias: null };
  const n = Math.max(1, Math.min(365, parseInt($("#c-dias-n").value, 10) || 1));
  return { ini, fim: addDias(ini, n - 1), dias: n };
}

function primeiraDose() {
  if (W.agora) { const d = new Date(); d.setSeconds(0, 0); return d; }
  const dt = $("#c-pd-data").value, hr = $("#c-pd-hora").value;
  return dt && hr ? new Date(dt + "T" + hr + ":00") : null;
}
const isoLocal = (d) => dataLocalISO(d) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
function rotuloDose(d, com_as = false) {
  const dia = dataLocalISO(d), hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
  const nome = dia === dataLocalISO() ? (com_as ? "hoje" : "Hoje")
    : dia === dataLocalISO(new Date(Date.now() + 86400000)) ? (com_as ? "amanhã" : "Amanhã") : fmtData(dia);
  return nome + (com_as ? " às " : " ") + hm;
}

function atualizarPreview() {
  const interv = W.modo === "intervalo";
  $("#bloco-intervalo").hidden = !interv; $("#bloco-fixo").hidden = interv;
  $("#bloco-inicio").hidden = interv; $("#bloco-dias-sem").hidden = interv;
  $("#bloco-pd-escolher").hidden = W.agora;
  $("#bloco-primeiro").hidden = W.n === 0; $("#bloco-custom").hidden = W.n !== 0;
  $("#bloco-periodo").hidden = W.dur === "continuo";
  const nome = $("#nome").value.trim() || "o remédio";
  const chips = $("#prev-doses"), trilho = $("#trilho-pontos");
  chips.replaceChildren();
  let relogio = [], txt = "";

  if (interv) {
    const p = primeiraDose();
    const n = W.dur === "continuo" ? null : Math.max(1, Math.min(365, parseInt($("#c-dias-n").value, 10) || 1));
    const total = n ? Math.ceil((n * 24) / W.x) : null;
    if (!p) txt = "Escolha a data e a hora da primeira dose.";
    else {
      const passo = W.x * 3600000, mostrar = Math.min(total || 8, 8);
      const lista = Array.from({ length: mostrar }, (_, k) => new Date(p.getTime() + k * passo));
      chips.append(...lista.map((d, k) => h("span", { class: "dose-chip" + (k === 0 ? " primeira" : "") }, (k === 0 ? "1ª · " : "") + rotuloDose(d))));
      chips.append(h("span", { class: "dose-chip mais" }, total ? (total > mostrar ? "+" + (total - mostrar) + " doses" : "") : "…"));
      if (!chips.lastChild.textContent) chips.lastChild.remove();
      for (let k = 0; k * W.x < 24; k++) { const d = new Date(p.getTime() + k * passo); relogio.push(pad(d.getHours()) + ":" + pad(d.getMinutes())); }
      relogio.sort();
      txt = "Tomar " + nome + " de " + W.x + " em " + W.x + (W.x === 1 ? " hora" : " horas") + ", começando " + rotuloDose(p, true) + ". "
        + (total ? "Total de " + total + " doses em " + n + (n === 1 ? " dia." : " dias.") : "Uso contínuo.");
    }
  } else {
    relogio = calcularHorarios();
    const per = calcularPeriodo(), sel = diasSelecionados();
    txt = relogio.length ? "Tomar " + nome + " " + relogio.length + "× ao dia: " + relogio.join(", ") + ". " : "Escolha ao menos um horário. ";
    if (per.fim) {
      let dosesTotal = 0;
      for (let i = 0; i < per.dias; i++) {
        const d = new Date(addDias(per.ini, i) + "T12:00:00");
        if (sel.includes(String((d.getDay() + 6) % 7))) dosesTotal += relogio.length;
      }
      txt += "Por " + per.dias + (per.dias === 1 ? " dia" : " dias") + " (" + fmtData(per.ini) + " a " + fmtData(per.fim) + "), total de " + dosesTotal + " doses.";
    } else txt += "Uso contínuo a partir de " + fmtData(per.ini) + ".";
  }

  while (trilho.children.length < relogio.length) trilho.append(h("span", { class: "ponto" }));
  while (trilho.children.length > relogio.length) trilho.lastChild.remove();
  relogio.forEach((hr, i) => {
    const [a, b] = hr.split(":").map(Number), el = trilho.children[i];
    el.style.left = ((a * 60 + b) / 1440) * 100 + "%"; el.dataset.h = hr;
  });
  $("#prev-texto").textContent = txt;
}

function montarSeg(id, opcoes, ativo, aoClicar) {
  const box = document.getElementById(id);
  box.replaceChildren(...opcoes.map(([valor, rotulo]) => {
    const b = h("button", { type: "button", class: valor === ativo ? "ativa" : "" }, rotulo);
    b.addEventListener("click", () => { [...box.children].forEach((x) => x.classList.toggle("ativa", x === b)); aoClicar(valor); atualizarPreview(); });
    return b;
  }));
}

function desenharChipsNovos() {
  $("#chips-novos").replaceChildren(...W.custom.map((hr, i) =>
    h("span", { class: "chip" }, hr, h("button", { title: "Remover", onclick: () => { W.custom.splice(i, 1); desenharChipsNovos(); atualizarPreview(); } }, "×"))));
}

function abrirForm(abrir) {
  $("#form-novo-box").classList.toggle("aberto", abrir);
  $("#btn-novo").hidden = abrir;
  atualizarFab();
  if (abrir) {
    const agora = new Date();
    $("#c-inicio").value = dataLocalISO(); $("#c-inicio").min = dataLocalISO();
    $("#c-pd-data").value = dataLocalISO(); $("#c-pd-data").min = dataLocalISO();
    $("#c-pd-hora").value = pad(agora.getHours()) + ":" + pad(agora.getMinutes());
    atualizarPreview(); setTimeout(() => $("#nome").focus(), 350);
  }
}

(function iniciarAssistente() {
  montarSeg("seg-modo", [["intervalo", "⏱ A cada X horas"], ["fixo", "🕒 Horários fixos por dia"]], W.modo, (v) => (W.modo = v));
  montarSeg("seg-x", Array.from({ length: 12 }, (_, i) => [i + 1, i + 1 + " h"]), W.x, (v) => (W.x = v));
  montarSeg("seg-pd", [[true, "⚡ Agora"], [false, "Escolher horário"]], W.agora, (v) => (W.agora = v));
  montarSeg("seg-freq", FREQS, W.n, (v) => (W.n = v));
  montarSeg("seg-dur", [["periodo", "Por período"], ["continuo", "Uso contínuo"]], W.dur, (v) => (W.dur = v));
  montarSeg("seg-dias-rapidos", [3, 5, 7, 10, 14, 30].map((n) => [n, n + " dias"]), 7, (v) => ($("#c-dias-n").value = v));
  $("#dias").append(...NOMES_DIAS.map((nome, i) => h("label", {}, h("input", { type: "checkbox", value: i, checked: "" }), nome)));
  ["#nome", "#c-primeiro", "#c-inicio", "#c-dias-n", "#dias", "#c-pd-data", "#c-pd-hora"].forEach((s) => $(s).addEventListener("input", atualizarPreview));
  $("#c-dias-n").addEventListener("input", () => $$("#seg-dias-rapidos button").forEach((b) => b.classList.toggle("ativa", b.textContent === $("#c-dias-n").value + " dias")));
  $("#btn-novo").addEventListener("click", () => abrirForm(true));
  $("#btn-cancelar").addEventListener("click", () => abrirForm(false));
  $("#btn-add-hora").addEventListener("click", () => {
    const v = $("#hora").value;
    if (!v) return toast("Escolha um horário primeiro.", "erro");
    if (!W.custom.includes(v)) W.custom.push(v);
    $("#hora").value = ""; desenharChipsNovos(); atualizarPreview();
  });
  $("#btn-salvar").addEventListener("click", (ev) => acao(async () => {
    const nome = $("#nome").value.trim();
    if (!nome) throw new Error("Digite o nome do remédio.");
    const base = { nome, dosagem: $("#dosagem").value.trim() || null, observacoes: $("#obs").value.trim() || null,
      estoque: $("#estoque-novo").value.trim() || null, estoque_aviso: $("#estoque-aviso-novo").value.trim() || 5 };
    if (W.modo === "intervalo") {
      const p = primeiraDose();
      if (!p) throw new Error("Escolha a data e a hora da primeira dose.");
      const dias = W.dur === "continuo" ? null : Math.max(1, Math.min(365, parseInt($("#c-dias-n").value, 10) || 1));
      await api("/medicamentos", "POST", { ...base, intervalo_horas: W.x, primeira_dose: isoLocal(p), dias });
    } else {
      const hs = calcularHorarios(), per = calcularPeriodo(), dias = diasSelecionados().join("");
      if (!hs.length) throw new Error("Escolha ao menos um horário.");
      if (!dias) throw new Error("Marque pelo menos um dia da semana.");
      await api("/medicamentos", "POST", { ...base, horarios: hs, dias_semana: dias, data_inicio: per.ini, data_fim: per.fim });
    }
    ["#nome", "#dosagem", "#obs", "#hora"].forEach((s) => ($(s).value = ""));
    W.custom = []; desenharChipsNovos(); abrirForm(false);
    const r = $("#btn-novo").getBoundingClientRect(); confete(r.left + r.width / 2, r.top);
    toast("Cronograma criado! 📅");
  }, ev.currentTarget));
  atualizarPreview();
})();

/* ---------- alertas do navegador ---------- */
$("#btn-alertas").addEventListener("click", async () => {
  garantirAudio();
  if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
  alertasAtivos = true; previaSom();
  $("#status-alertas").textContent = "Ativado ✓ (vale enquanto esta página estiver aberta)";
  atualizarStatusSom();
});

/* ---------- perfil / push ---------- */
function atualizarPerfil() {
  $("#topico").value = usuario.ntfy_topico || "";
  const selo = $("#selo-push");
  selo.className = "selo " + (usuario.ntfy_topico ? "on" : "off");
  selo.textContent = usuario.ntfy_topico ? "ativo ✓" : "não configurado";
}
$("#btn-gerar").addEventListener("click", () => {
  const b = new Uint8Array(5); crypto.getRandomValues(b);
  const sufixo = [...b].map((x) => x.toString(36).padStart(2, "0")).join("").slice(0, 8);
  const base = usuario.nome.split(" ")[0].toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, "") || "usuario";
  $("#topico").value = "remedio-" + base + "-" + sufixo;
});
$("#btn-salvar-topico").addEventListener("click", (ev) => acao(async () => {
  usuario = await api("/api/eu", "PUT", { ntfy_topico: $("#topico").value });
  atualizarPerfil(); toast(usuario.ntfy_topico ? "Tópico salvo ✓" : "Push desligado");
}, ev.currentTarget));
$("#btn-teste").addEventListener("click", (ev) => acao(async () => {
  await api("/api/eu/teste-push", "POST"); toast("Teste enviado! Olhe seu celular 📲");
}, ev.currentTarget));

/* ---------- navegação do app e início ---------- */
/* ---------- menu lateral: troca de abas com animação ---------- */
const ORDEM_ABAS = ["aba-hoje", "aba-crono", "aba-historico", "aba-estoque", "aba-perfil"];
let abaAtual = "aba-hoje", timerAba = null;

function posicionarMenu() {
  const a = $("#menu button.ativa"), ind = $("#menu-ind");
  if (!a || !a.offsetWidth) return;
  if (matchMedia("(max-width: 899px)").matches) {
    ind.style.transform = "translateX(" + a.offsetLeft + "px)"; ind.style.width = a.offsetWidth + "px"; ind.style.height = "";
  } else {
    ind.style.transform = "translateY(" + a.offsetTop + "px)"; ind.style.height = a.offsetHeight + "px"; ind.style.width = "";
  }
}

function atualizarFab() {
  const escondido = !["aba-hoje", "aba-crono"].includes(abaAtual) || $("#form-novo-box").classList.contains("aberto");
  $("#fab").classList.toggle("oculto", escondido);
}

function irParaAba(id) {
  if (id === abaAtual) return;
  if (id === "aba-estoque") carregarEstoque().catch(() => {});
  $("#conteudo").dataset.dir = ORDEM_ABAS.indexOf(id) > ORDEM_ABAS.indexOf(abaAtual) ? "dir" : "esq";
  abaAtual = id;
  $$("#menu button").forEach((b) => b.classList.toggle("ativa", b.dataset.alvo === id));
  posicionarMenu(); atualizarFab();
  clearTimeout(timerAba);
  ORDEM_ABAS.map((x) => document.getElementById(x)).filter((x) => !x.hidden).forEach((x) => x.classList.add("saindo-aba"));
  timerAba = setTimeout(() => ORDEM_ABAS.forEach((x) => {
    const el = document.getElementById(x); el.hidden = x !== id; el.classList.remove("saindo-aba");
  }), 170);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$$("#menu button").forEach((b) => b.addEventListener("click", () => irParaAba(b.dataset.alvo)));
posicionadores.push(posicionarMenu);

$("#fab").addEventListener("click", () => {
  irParaAba("aba-crono");
  setTimeout(() => { abrirForm(true); $("#form-novo-box").scrollIntoView({ behavior: "smooth", block: "center" }); }, 260);
});

document.addEventListener("pointerdown", (e) => {            // efeito de onda nos botões principais
  const b = e.target.closest("button.principal, .menu button, .fab");
  if (!b || b.disabled) return;
  const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2;
  const o = h("span", { class: "ripple" });
  o.style.width = o.style.height = d + "px";
  o.style.left = e.clientX - r.left - d / 2 + "px"; o.style.top = e.clientY - r.top - d / 2 + "px";
  b.append(o); setTimeout(() => o.remove(), 700);
});
montarSeg("seg-hist", [[7, "7 dias"], [15, "15 dias"], [30, "30 dias"]], histDias, (v) => { histDias = v; desenharHistorico(); });

function atualizarTudo() {
  carregarAlarmes().catch(() => {});
  carregarDashboard().catch(() => {});
  carregarHistorico().catch(() => {});
  if (abaAtual === "aba-estoque") carregarEstoque().catch(() => {});
}

(async function iniciar() {
  try { mostrarApp(await api("/api/eu")); } catch (e) { mostrarAuth(); }
})();

// Acessibilidade: letra grande / alto contraste (salvo no navegador)
(function(){
  const r=document.documentElement;
  try{ if(localStorage.lm_grande==='1') r.classList.add('letra-grande'); if(localStorage.lm_contraste==='1') r.classList.add('alto-contraste'); }catch(e){}
  window.alternarAcessibilidade=function(tipo){
    const c=tipo==='grande'?'letra-grande':'alto-contraste';
    const on=r.classList.toggle(c);
    try{ localStorage[tipo==='grande'?'lm_grande':'lm_contraste']=on?'1':'0'; }catch(e){}
  };
})();
// Service worker (PWA)
if('serviceWorker' in navigator){ navigator.serviceWorker.register('/sw.js').catch(()=>{}); }

// ---------- extras: acessibilidade, cuidador, estoque, PDF, esqueci a senha ----------
async function montarExtras() {
  const aba = $("#aba-perfil");
  if (!aba || !usuario) return;
  let box = $("#extras");
  if (!box) { box = document.createElement("div"); box.id = "extras"; aba.appendChild(box); }
  const esc = x => String(x ?? "").replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  box.innerHTML = `
    <div class="cartao">
      <h2>♿ Acessibilidade</h2>
      <p class="pequeno" style="margin-top:0">Deixa o texto maior ou aumenta o contraste das cores. A escolha fica salva neste aparelho.</p>
      <div class="linha">
        <button type="button" onclick="alternarAcessibilidade('grande')">🔠 Letra grande</button>
        <button type="button" onclick="alternarAcessibilidade('contraste')">◐ Alto contraste</button>
      </div>
    </div>
    <div class="cartao">
      <h2>👪 Cuidador ou familiar</h2>
      <p class="pequeno" style="margin-top:0">Se você perder uma dose, essa pessoa recebe um aviso no celular. Ela precisa assinar o tópico no app ntfy.</p>
      <label for="cuidador-topico">Tópico ntfy da pessoa</label>
      <input type="text" id="cuidador-topico" maxlength="64" autocomplete="off" value="${esc(usuario.cuidador_topico)}" placeholder="ex.: familia-maria-8392">
      <div class="linha" style="margin-top:12px"><button type="button" class="principal" id="cuidador-salvar">Salvar</button></div>
      <p class="pequeno">Deixe em branco para desligar o aviso.</p>
    </div>
    <div class="cartao">
      <h2>🖨️ Histórico para o médico</h2>
      <p class="pequeno" style="margin-top:0">Abre uma página com os últimos 30 dias. Use Imprimir → Salvar como PDF.</p>
      <div class="linha"><a class="btn" href="/api/historico/imprimir?dias=30" target="_blank" rel="noopener">Abrir histórico</a></div>
    </div>`;
  $("#cuidador-salvar").onclick = async () => {
    try { usuario = await api("/api/eu/cuidador", "PUT", { cuidador_topico: $("#cuidador-topico").value }); toast("Cuidador salvo ✓"); }
    catch (e) { toast(e.message || "Erro ao salvar"); }
  };
}
const _atualizarPerfilBase = atualizarPerfil;
atualizarPerfil = function () { _atualizarPerfilBase(); montarExtras(); };

// "Esqueci a senha" na tela de login + tela de nova senha pelo link do e-mail
(function () {
  const f = document.getElementById("form-login");
  if (f) {
    const a = document.createElement("a");
    a.href = "#"; a.textContent = "Esqueci minha senha"; a.className = "pequeno";
    a.onclick = async ev => {
      ev.preventDefault();
      const email = prompt("Digite o e-mail da sua conta:", document.getElementById("login-email")?.value || "");
      if (!email) return;
      try { const r = await api("/api/esqueci-senha", "POST", { email }); alert(r.mensagem); } catch (e) { alert(e.message); }
    };
    f.appendChild(a);
  }
  const m = location.hash.match(/^#redefinir=(.+)$/);
  if (m) {
    const senha = prompt("Digite a nova senha (mínimo 8 caracteres):");
    if (senha) api("/api/redefinir-senha", "POST", { token: m[1], senha })
      .then(() => alert("Senha alterada! Entre com a nova senha."), e => alert(e.message))
      .finally(() => history.replaceState(null, "", location.pathname));
  }
})();

// ---------- aba Estoque ----------
async function carregarEstoque() {
  const meds = await api("/medicamentos");
  const esc = x => String(x ?? "").replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  const porDia = m => (m.intervalo_horas ? 24 / m.intervalo_horas : (m.horarios || []).length);
  const baixos = meds.filter(m => m.estoque != null && m.estoque <= m.estoque_aviso);
  $("#estoque-resumo").textContent = !meds.length ? "Nenhum remédio cadastrado ainda."
    : baixos.length ? "⚠️ Repor em breve: " + baixos.map(m => m.nome).join(", ")
    : "Tudo certo com o estoque dos remédios que você controla.";
  $("#estoque-lista").innerHTML = meds.map(m => {
    const controla = m.estoque != null, baixo = controla && m.estoque <= m.estoque_aviso;
    const dias = controla && porDia(m) > 0 ? Math.floor(m.estoque / porDia(m)) : null;
    const pct = controla ? Math.min(100, Math.round(100 * m.estoque / Math.max(m.estoque_aviso * 3, 1))) : 0;
    return `<div class="cartao" data-med="${m.id}">
      <h2>${esc(m.nome)} <small class="pequeno">${esc(m.dosagem)}</small>
        <span class="badge ${!controla ? "b-pendente" : baixo ? "b-perdido" : "b-tomado"}">${!controla ? "sem controle" : baixo ? "repor em breve" : "ok"}</span></h2>
      ${controla ? `<p style="font-size:1.6em;margin:.2em 0"><b>${m.estoque}</b> <span class="pequeno">restantes${dias !== null ? " · dura cerca de " + dias + (dias === 1 ? " dia" : " dias") : ""}</span></p>
        <div style="height:8px;border-radius:6px;background:rgba(128,128,160,.25);overflow:hidden"><div style="height:100%;width:${pct}%;background:${baixo ? "#f87171" : "#34d399"}"></div></div>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-top:10px">
        <label>Quantidade atual<input type="number" min="0" data-f="estoque" value="${m.estoque ?? ""}" placeholder="não controlar" style="width:120px"></label>
        <label>Avisar com<input type="number" min="0" data-f="aviso" value="${m.estoque_aviso ?? 5}" style="width:80px"></label>
        <button type="button" class="btn" data-acao="salvar">Salvar</button>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-top:8px">
        <label>Comprei<input type="number" min="1" data-f="repor" placeholder="ex.: 30" style="width:100px"></label>
        <button type="button" class="btn" data-acao="repor">+ Repor</button>
      </div></div>`;
  }).join("");
  $$("#estoque-lista [data-acao]").forEach(b => b.addEventListener("click", async () => {
    const card = b.closest("[data-med]"), campo = n => card.querySelector(`[data-f="${n}"]`).value;
    let estoque = campo("estoque");
    if (b.dataset.acao === "repor") {
      const n = parseInt(campo("repor"), 10);
      if (!(n > 0)) return toast("Digite quantos comprimidos você comprou");
      estoque = (parseInt(estoque, 10) || 0) + n;
    }
    try {
      await api(`/api/medicamentos/${card.dataset.med}/estoque`, "PUT", { estoque, aviso: campo("aviso") || 5 });
      toast("Estoque salvo ✓"); carregarEstoque();
    } catch (e) { toast(e.message || "Erro ao salvar"); }
  }));
}

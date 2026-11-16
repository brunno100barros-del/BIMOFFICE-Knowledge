/* BIMOFFICE Knowledge — interface (JavaScript puro, sem dependências).
 * Regras: só mostra dados reais vindos da API; sem backend, explica o que falta.
 * Textos dos documentos são DADOS: sempre escapados antes de exibir. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ utilidades
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (n) => `<svg><use href="#i-${n}"/></svg>`;
  const store = {
    get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
    set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* sem armazenamento */ } },
  };
  const fmtDate = (s) => {
    if (!s) return "—";
    const d = new Date(String(s).replace(" ", "T") + (String(s).includes("Z") ? "" : "Z"));
    return isNaN(d) ? s : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
  };
  const sourceLabel = (d) => d.source === "gdrive"
    ? `Google Drive${d.source_ref && d.source_ref.folder ? " · " + d.source_ref.folder : ""}`
    : "Upload manual";
  const STOP = new Set("a o os as de da do das dos e em no na nos nas um uma com para por que se ser será serão são sobre entre".split(" "));

  // mensagens de erro da API: texto simples, {message: ...} ou lista de validação
  function detailText(d) {
    if (!d) return "";
    if (typeof d === "string") return d;
    if (d.message) return d.message;
    if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
    return JSON.stringify(d);
  }

  // baixa um Blob com nome de arquivo (o link precisa estar na página para o navegador respeitar o nome)
  // nome de arquivo seguro em qualquer sistema: sem acentos nem travessões (o CONTEÚDO não muda)
  const safeFilename = (n) => String(n).normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[\u2013\u2014]/g, "-")
    .replace(/[^\w.\-() ]+/g, "_");
  function saveBlob(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = safeFilename(filename);
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 60000);
  }

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    const box = $("#toasts");
    while (box.children.length >= 3) box.firstElementChild.remove(); // no máximo 3 avisos na tela
    box.appendChild(el);
    setTimeout(() => el.remove(), 4800);
  }

  // ------------------------------------------------------------------ API
  const API = {
    base: "",
    token: "",
    online: false,
    cfg: null,
    resolveBase() {
      const saved = store.get("bimoffice-api");
      if (saved !== null) return saved.replace(/\/+$/, "");
      const c = window.BIMOFFICE_CONFIG || {};
      if (c.apiBase) return String(c.apiBase).replace(/\/+$/, "");
      if (/^https?:$/.test(location.protocol) && !location.hostname.endsWith("github.io")) return location.origin;
      return "";
    },
    headers(extra = {}) {
      const h = { ...extra };
      if (this.token) h.Authorization = `Bearer ${this.token}`;
      return h;
    },
    demo: false,
    manifest: null,
    async req(path, opts = {}) {
      if (this.demo) return Demo.req(path, opts);
      if (!this.base) throw new Error("Nenhum backend configurado.");
      let r;
      try {
        r = await fetch(this.base + path, { ...opts, headers: this.headers(opts.headers) });
      } catch (e) {
        throw new Error("Não foi possível falar com o backend (desligado ou bloqueado).");
      }
      if (!r.ok) {
        let detail = `Erro ${r.status}`;
        try { const j = await r.json(); detail = detailText(j.detail) || detail; } catch { /* corpo não-JSON */ }
        const err = new Error(detail);
        err.status = r.status;
        if (r.status === 401 && this.cfg && this.cfg.auth_mode === "on" && path !== "/api/auth/login") {
          this.online = "login"; this.user = null;
          setTimeout(() => { renderBanner(); render(); }, 0);   // sessão expirada: pede login de novo
        }
        throw err;
      }
      return r.status === 204 ? null : r.json();
    },
    get(p) { return this.req(p); },
    post(p, body) { return this.req(p, { method: "POST", ...(body ? { body: JSON.stringify(body), headers: { "Content-Type": "application/json" } } : {}) }); },
    del(p) { return this.req(p, { method: "DELETE" }); },
    originalUrl(id, inline) {
      if (this.demo) return Demo.fileUrl(`/api/library/documents/${id}/original`);
      return `${this.base}/api/library/documents/${id}/original${inline ? "?inline=true" : ""}`;
    },
    upload(file, meta, onProgress, path = "/api/library/documents") {
      return new Promise((resolve, reject) => {
        if (this.demo) { reject(new Error(Demo.RO)); return; }
        const fd = new FormData();
        fd.append("file", file, file.name);
        Object.entries(meta).forEach(([k, v]) => v && fd.append(k, v));
        const xhr = new XMLHttpRequest();
        xhr.open("POST", this.base + path);
        if (this.token) xhr.setRequestHeader("Authorization", `Bearer ${this.token}`);
        xhr.upload.onprogress = (e) => e.lengthComputable && onProgress("upload", e.loaded / e.total);
        xhr.upload.onload = () => onProgress("processing", 1);
        xhr.onload = () => {
          let j = null;
          try { j = JSON.parse(xhr.responseText); } catch { /* vazio */ }
          if (xhr.status >= 200 && xhr.status < 300) resolve(j);
          else reject(new Error(detailText(j && j.detail) || `Erro ${xhr.status}`));
        };
        xhr.onerror = () => reject(new Error("Falha de conexão com o backend."));
        xhr.send(fd);
      });
    },
  };

  // ------------------------------------------------------------------ demonstração estática
  // Respostas REAIS do backend para o projeto exemplo, gravadas em demo/ (scripts/exemplo/gerar_demo_estatico.py).
  // Somente leitura: nada é gerado no navegador e a pesquisa semântica NÃO é simulada.
  const Demo = {
    RO: "Demonstração somente leitura: para enviar arquivos, editar, gerar ou aprovar, instale o programa (iniciar.bat).",
    cache: {},
    active() { try { return sessionStorage.getItem("bimoffice-demo") === "1"; } catch { return false; } },
    set(on) { try { on ? sessionStorage.setItem("bimoffice-demo", "1") : sessionStorage.removeItem("bimoffice-demo"); } catch { /* */ } },
    async file(name) {
      if (!this.cache[name]) {
        const r = await fetch(`demo/${name}`);
        if (!r.ok) throw new Error("Arquivo da demonstração não encontrado.");
        this.cache[name] = await r.json();
      }
      return this.cache[name];
    },
    fileUrl(route) { const f = API.manifest && API.manifest.routes[route]; return f ? `demo/${f}` : "#"; },
    async req(path, opts = {}) {
      if ((opts.method || "GET") !== "GET") throw new Error(this.RO);
      const [p, qs] = path.split("?");
      const q = new URLSearchParams(qs || "");
      const routes = API.manifest.routes;
      if (p === "/api/search") throw new Error("A pesquisa semântica roda no programa instalado (modelo de IA local). Na demonstração ela não é simulada — instale o programa para pesquisar.");
      if (p === "/api/jobs") return [];
      let m = p.match(/^\/api\/ifc-models\/(\d+)\/elements$/);
      if (m) {
        const all = (await this.file(routes[p])).items;
        const miss = q.get("missing"), st = q.get("storey"), term = (q.get("q") || "").toLowerCase();
        const items = all.filter((e) => (!q.get("discipline") || e.discipline === q.get("discipline"))
          && (!q.get("ifc_class") || e.ifc_class === q.get("ifc_class"))
          && (!st || (st === "(sem pavimento)" ? !e.storey : e.storey === st))
          && (!term || [e.name, e.global_id, e.type_name].some((x) => (x || "").toLowerCase().includes(term)))
          && (!miss || (miss === "any" ? e.missing.length : e.missing.includes(miss))));
        const limit = +(q.get("limit") || 100), offset = +(q.get("offset") || 0);
        return { total: items.length, limit, offset, items: items.slice(offset, offset + limit) };
      }
      m = p.match(/^\/api\/ifc-elements\/(\d+)$/);
      if (m) {
        for (const [k, f] of Object.entries(routes)) {
          if (!k.startsWith("elements_detail:")) continue;
          const d = (await this.file(f))[m[1]];
          if (d) return d;
        }
        throw new Error("Elemento não encontrado.");
      }
      if (p === "/api/library/documents") {
        const t = (q.get("q") || "").toLowerCase();
        return (await this.file(routes[p])).filter((d) => (!q.get("file_type") || d.file_type === q.get("file_type"))
          && (!q.get("unit") || d.unit === q.get("unit")) && (!q.get("discipline") || d.discipline === q.get("discipline"))
          && (!t || [d.title, d.original_filename, d.description].some((x) => (x || "").toLowerCase().includes(t))));
      }
      if (routes[p] && routes[p].endsWith(".json")) return this.file(routes[p]);
      throw new Error("Esta informação não faz parte da demonstração (precisa do programa instalado).");
    },
    async start() {
      const r = await fetch("demo/manifest.json");
      if (!r.ok) throw new Error("Demonstração não disponível nesta página.");
      API.manifest = await r.json();
      API.demo = true;
      API.cfg = await this.file(API.manifest.routes["/api/config"]);
      API.online = true;
    },
  };

  // abre o original com a senha (se houver) sem expor o token na URL
  async function openOriginal(doc, inline) {
    try {
      if (API.demo) {
        const r = await fetch(API.originalUrl(doc.id || doc.document_id));
        if (!r.ok) throw new Error("Arquivo não disponível na demonstração.");
        saveBlob(await r.blob(), doc.original_filename || "documento");
        return;
      }
      if (!API.token) { window.open(API.originalUrl(doc.id || doc.document_id, inline), "_blank", "noopener"); return; }
      const r = await fetch(API.originalUrl(doc.id || doc.document_id, inline), { headers: API.headers() });
      if (!r.ok) throw new Error(`Erro ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      if (inline) window.open(url, "_blank", "noopener");
      else saveBlob(await (await fetch(url)).blob(), doc.original_filename || "documento");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { toast(e.message, "err"); }
  }
  const openDoc = (d) => openOriginal(d, (d.file_type || "docx") === "pdf");

  // ------------------------------------------------------------------ conexão
  async function connect() {
    API.base = API.resolveBase();
    API.token = store.get("bimoffice-token", "") || "";
    const el = $("#conn");
    API.online = false;
    API.cfg = null;
    API.demo = false;
    if (Demo.active()) {
      try { await Demo.start(); } catch (e) { Demo.set(false); toast(e.message, "err"); }
    }
    if (!API.demo && API.base) {
      try {
        API.cfg = await API.get("/api/config");
        API.online = true;
        if (API.cfg.auth_required && !API.token) API.online = "auth";
        API.user = null;
        if (API.cfg.auth_mode === "on") {
          try { API.user = await API.get("/api/auth/me"); } catch { API.online = "login"; }
        }
      } catch { /* offline */ }
    }
    el.classList.toggle("on", API.online === true);
    el.classList.toggle("off", API.online !== true);
    $(".conn-text", el).textContent = API.demo ? "Demonstração · projeto exemplo"
      : API.online === true ? `Backend conectado · v${API.cfg.version}`
      : API.online === "auth" ? "Backend exige senha" : API.online === "login" ? "Faça login" : "Sem backend";
    const who = $("#who");
    who.hidden = !API.user;
    if (API.user) $("#whoName").textContent = `${API.user.name || API.user.email} · ${API.user.role}`;
    renderBanner();
  }

  function renderBanner() {
    const b = $("#banner");
    if (API.demo) {
      b.innerHTML = `<div class="notice info">${icon("info")}<div><b>Demonstração somente leitura — projeto EXEMPLO (dados fictícios).</b>
        Tudo o que você vê aqui foi produzido pelo sistema real (leitura do IFC, inventário, memorial e sugestões) e gravado nesta página.
        Para enviar seus arquivos, editar, gerar memoriais e pesquisar por significado, instale o programa.
        <div class="actions" style="margin-top:8px"><a class="btn sm" href="#/projeto/1">${icon("cube")}Projeto exemplo</a>
        <a class="btn sm" href="#/memoriais">${icon("file")}Memorial gerado</a>
        <button class="btn sm" id="demoOff">${icon("x")}Sair da demonstração</button></div></div></div>`;
      $("#demoOff").onclick = async () => { Demo.set(false); await connect(); location.hash = "#/dashboard"; render(); };
      return;
    }
    if (API.online === true || API.online === "login") { b.innerHTML = ""; return; }
    const pages = location.hostname.endsWith("github.io");
    b.innerHTML = `<div class="notice ${API.online === "auth" ? "err" : ""}">${icon("plug")}<div>
      ${API.online === "auth"
        ? "<b>O backend exige senha.</b> Informe a senha da API em <a href='#/config'>Configurações</a>."
        : `<b>Nenhum backend conectado.</b> A interface está ativa, mas importar, listar e pesquisar memoriais
           dependem do backend FastAPI (processamento de DOCX/PDF, banco SQLite e modelo E5 local).
           ${pages ? "Para usar de verdade, rode o <code>iniciar.bat</code> no seu computador e informe <code>http://127.0.0.1:8000</code> em" : "Verifique se o backend está ligado ou ajuste o endereço em"}
           <a href="#/config">Configurações</a>. Nenhum dado é simulado.
           <div class="actions" style="margin-top:8px"><button class="btn sm primary" id="demoOn">${icon("cube")}Abrir demonstração com o projeto exemplo</button></div>`}
      </div></div>`;
    const on = $("#demoOn");
    if (on) on.onclick = async () => {
      Demo.set(true);
      await connect();
      if (API.demo) { location.hash = "#/projeto/1"; render(); }
    };
  }

  const needBackend = (what) => `<div class="card empty">${icon("plug")}<h3>${esc(what)} depende do backend</h3>
    <p>Conecte um backend em <a href="#/config">Configurações</a> para ver dados reais.</p></div>`;

  // ------------------------------------------------------------------ tema
  const THEMES = ["system", "light", "dark"];
  const THEME_LABEL = { system: "Tema: automático", light: "Tema: claro", dark: "Tema: escuro" };
  function applyTheme(t) {
    const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    $("#themeLabel").textContent = THEME_LABEL[t];
  }
  function setTheme(t) { store.set("bimoffice-theme", t); applyTheme(t); }
  $("#themeBtn").addEventListener("click", () => {
    const cur = store.get("bimoffice-theme", "system");
    setTheme(THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(store.get("bimoffice-theme", "system")));
  applyTheme(store.get("bimoffice-theme", "system"));

  // ------------------------------------------------------------------ roteador
  const routes = {};
  let routeSeq = 0; // muda a cada navegação (para parar atualizações automáticas da tela anterior)
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, "") || "dashboard";
    const [path, qs] = h.split("?");
    const [name, arg] = path.split("/");
    return { name, arg, params: new URLSearchParams(qs || "") };
  }
  async function render() {
    routeSeq++;
    dispose3d();
    const dr = document.getElementById("drawer");
    if (dr) dr.classList.remove("open");
    const r = parseHash();
    const fn = API.online === "login" ? routes.login : (routes[r.name] || routes.dashboard);
    const navName = { documento: "biblioteca", projeto: "projetos", memorial: "memoriais" }[r.name] || r.name;
    document.body.classList.toggle("wide", r.name === "modelo3d");
    $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === navName));
    const view = $("#view");
    view.style.animation = "none"; void view.offsetWidth; view.style.animation = "";
    try { await fn(view, r); }
    catch (e) { view.innerHTML = `<div class="notice err">${icon("alert")}<div><b>Erro:</b> ${esc(e.message)}</div></div>`; }
  }
  window.addEventListener("hashchange", render);

  // ------------------------------------------------------------------ componentes
  function docCard(d) {
    return `<article class="card doc" data-id="${d.id}">
      <div class="top"><span class="badge ${esc(d.file_type)}">${esc((d.file_type || "docx").toUpperCase())}</span>
        <span class="badge src">${esc(sourceLabel(d))}</span></div>
      <div><h3>${esc(d.title)}</h3><p class="file">${esc(d.original_filename)}</p></div>
      <dl class="facts">
        <dt>Importado</dt><dd>${fmtDate(d.created_at)}</dd>
        ${d.unit ? `<dt>Unidade</dt><dd>${esc(d.unit)}</dd>` : ""}
        ${d.project ? `<dt>Obra</dt><dd>${esc(d.project)}</dd>` : ""}
        ${d.discipline ? `<dt>Disciplina</dt><dd>${esc(d.discipline)}</dd>` : ""}
        <dt>Conteúdo</dt><dd>${d.n_sections} seções · ${d.n_chunks} trechos</dd>
      </dl>
      ${d.tags && d.tags.length ? `<div class="chips">${d.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="row-actions">${docActions(d)}</div>
    </article>`;
  }
  function docActions(d) {
    if (d.deleted_at) return `<button class="btn sm" data-act="restore" data-id="${d.id}">${icon("restore")}Restaurar</button>`;
    return `<a class="btn sm" href="#/documento/${d.id}">${icon("book")}Abrir</a>
      <button class="btn sm" data-act="original" data-id="${d.id}" title="${d.file_type === "pdf" ? "Abrir o PDF original" : "Baixar o DOCX original"}">${icon("external")}Original</button>
      <button class="btn sm danger" data-act="delete" data-id="${d.id}" title="Mover para a lixeira">${icon("trash")}Excluir</button>`;
  }
  function bindDocActions(root, docs, after) {
    root.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]");
      if (!b) return;
      const d = docs.find((x) => String(x.id) === b.dataset.id);
      if (!d) return;
      if (b.dataset.act === "original") openDoc(d);
      if (b.dataset.act === "delete") {
        if (!confirm(`Mover «${d.title}» para a lixeira?\n\nO arquivo original não é apagado e o documento pode ser restaurado.`)) return;
        try { await API.del(`/api/library/documents/${d.id}`); toast("Documento movido para a lixeira.", "ok"); after(); }
        catch (err) { toast(err.message, "err"); }
      }
      if (b.dataset.act === "restore") {
        try { await API.post(`/api/library/documents/${d.id}/restore`); toast("Documento restaurado.", "ok"); after(); }
        catch (err) { toast(err.message, "err"); }
      }
    });
  }
  const options = (vals, cur, label) => `<option value="">${label}</option>` +
    (vals || []).map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");

  // ------------------------------------------------------------------ Dashboard
  routes.dashboard = async (view) => {
    let st = null;
    if (API.online === true) { try { st = await API.get("/api/library/stats"); } catch (e) { toast(e.message, "err"); } }
    const n = (v) => (st ? v : "—");
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">SENAI/RO · Setor BIM Office</p>
        <h1>Inteligência documental para memoriais</h1>
        <p class="sub">Encontre, pelo significado, o que já foi especificado em obras anteriores — sempre com a origem de cada trecho.</p></div></div>
      <section class="card hero">
        <form class="searchbar" id="heroSearch" role="search">
          ${icon("search")}<input name="q" placeholder="Ex.: revestimento cerâmico nas paredes dos sanitários" aria-label="Pesquisa semântica" autocomplete="off">
          <button class="btn primary" type="submit">Pesquisar</button>
        </form>
        <div class="actions">
          <button class="btn" data-import ${API.online === true ? "" : "disabled"}>${icon("upload")}Importar documentos</button>
          <a class="btn" href="#/drive">${icon("cloud")}Conectar Google Drive</a>
        </div>
      </section>
      <section class="grid stats">
        <div class="card stat"><span class="ico">${icon("book")}</span><span class="num">${n(st && st.documents_total)}</span><span class="lbl">Documentos na biblioteca</span>${st && st.documents_in_trash ? `<span class="hint">${st.documents_in_trash} na lixeira</span>` : ""}</div>
        <div class="card stat"><span class="ico">${icon("file")}</span><span class="num">${n(st && st.documents_docx)}</span><span class="lbl">Memoriais DOCX</span></div>
        <div class="card stat"><span class="ico">${icon("file")}</span><span class="num">${n(st && st.documents_pdf)}</span><span class="lbl">Memoriais PDF</span></div>
        <div class="card stat"><span class="ico">${icon("search")}</span><span class="num">${n(st && st.chunks_total)}</span><span class="lbl">Trechos pesquisáveis</span>
          ${st ? `<span class="hint">${st.chunks_with_vectors} com pesquisa por significado</span>` : ""}</div>
      </section>
      <section class="card">
        <div class="page-head"><h2>Adicionados recentemente</h2><a href="#/biblioteca">Ver biblioteca →</a></div>
        <div id="recent" style="margin-top:14px"></div>
      </section>`;
    $("#heroSearch").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = e.target.q.value.trim();
      if (q) location.hash = `#/pesquisa?q=${encodeURIComponent(q)}`;
    });
    const rec = $("#recent");
    if (!st) rec.innerHTML = `<p class="muted">Sem backend conectado: nenhum documento para mostrar.</p>`;
    else if (!st.recent.length) rec.innerHTML = `<div class="empty">${icon("upload")}<h3>Biblioteca vazia</h3><p>Importe os primeiros memoriais DOCX ou PDF.</p></div>`;
    else {
      rec.innerHTML = `<div class="table-wrap"><table class="docs-table"><tbody>${st.recent.map((d) => `
        <tr><td><span class="badge ${esc(d.file_type)}">${esc(d.file_type.toUpperCase())}</span></td>
        <td class="t"><a href="#/documento/${d.id}">${esc(d.title)}</a></td>
        <td class="muted">${esc(d.unit || "—")}</td><td class="muted">${fmtDate(d.created_at)}</td></tr>`).join("")}</tbody></table></div>`;
    }
  };

  // ------------------------------------------------------------------ Biblioteca
  routes.biblioteca = async (view, r) => {
    const p = r.params;
    const mode = store.get("bimoffice-lib-view", "cards");
    const trash = p.get("lixeira") === "1";
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">Biblioteca</p><h1>${trash ? "Lixeira" : "Memoriais da biblioteca"}</h1>
        <p class="sub">${trash ? "Documentos excluídos. Os arquivos originais continuam guardados e podem ser restaurados." : "Os arquivos originais ficam guardados intactos (somente leitura). Editar a biblioteca nunca altera um memorial em elaboração."}</p></div>
        <div class="actions"><a class="btn" href="#/biblioteca${trash ? "" : "?lixeira=1"}">${icon(trash ? "book" : "trash")}${trash ? "Voltar à biblioteca" : "Lixeira"}</a>
        <button class="btn primary" data-import ${API.online === true ? "" : "disabled"}>${icon("upload")}Importar</button></div></div>
      <form class="card toolbar" id="libFilters">
        <input type="search" name="q" placeholder="Filtrar por título ou nome do arquivo" value="${esc(p.get("q") || "")}">
        <select name="file_type"><option value="">Todos os tipos</option><option value="docx" ${p.get("file_type") === "docx" ? "selected" : ""}>DOCX</option><option value="pdf" ${p.get("file_type") === "pdf" ? "selected" : ""}>PDF</option></select>
        <select name="unit" id="fUnit"><option value="">Todas as unidades</option></select>
        <select name="discipline" id="fDisc"><option value="">Todas as disciplinas</option></select>
        <span class="seg"><button type="button" class="icon-btn ${mode === "cards" ? "on" : ""}" data-mode="cards" aria-label="Ver em cartões">${icon("grid")}</button>
        <button type="button" class="icon-btn ${mode === "list" ? "on" : ""}" data-mode="list" aria-label="Ver em lista">${icon("list")}</button></span>
      </form>
      <div id="libList"></div>`;
    if (API.online !== true) { $("#libList").innerHTML = needBackend("A biblioteca"); return; }
    const form = $("#libFilters");
    try {
      const st = await API.get("/api/library/stats");
      $("#fUnit").innerHTML = options(st.facets.unit, p.get("unit"), "Todas as unidades");
      $("#fDisc").innerHTML = options(st.facets.discipline, p.get("discipline"), "Todas as disciplinas");
    } catch { /* filtros ficam vazios */ }
    const apply = () => {
      const qs = new URLSearchParams();
      new FormData(form).forEach((v, k) => v && qs.set(k, v));
      if (trash) qs.set("lixeira", "1");
      history.replaceState(null, "", `#/biblioteca${qs.toString() ? "?" + qs : ""}`);
      load();
    };
    let t;
    form.addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(apply, e.target.type === "search" ? 300 : 0); });
    form.addEventListener("submit", (e) => e.preventDefault());
    $$("[data-mode]", form).forEach((b) => b.addEventListener("click", () => { store.set("bimoffice-lib-view", b.dataset.mode); render(); }));

    async function load() {
      const qs = new URLSearchParams();
      new FormData(form).forEach((v, k) => v && qs.set(k, v));
      if (trash) qs.set("include_deleted", "true");
      let docs, err;
      try { docs = await API.get(`/api/library/documents?${qs}`); } catch (e) { err = e; }
      const box = $("#libList");
      if (!box) return; // o usuário mudou de tela enquanto carregava
      if (err) { box.innerHTML = `<div class="notice err">${icon("alert")}<div>${esc(err.message)}</div></div>`; return; }
      if (trash) docs = docs.filter((d) => d.deleted_at);
      if (!docs.length) {
        box.innerHTML = `<div class="card empty">${icon(trash ? "trash" : "book")}<h3>${trash ? "Lixeira vazia" : "Nenhum documento encontrado"}</h3>
          <p>${trash ? "" : "Importe memoriais DOCX ou PDF, ou ajuste os filtros."}</p></div>`;
        return;
      }
      box.innerHTML = store.get("bimoffice-lib-view", "cards") === "list"
        ? `<div class="card table-wrap"><table class="docs-table"><thead><tr><th>Tipo</th><th>Documento</th><th>Origem</th><th>Unidade</th><th>Importado</th><th></th></tr></thead><tbody>
           ${docs.map((d) => `<tr><td><span class="badge ${esc(d.file_type)}">${esc(d.file_type.toUpperCase())}</span></td>
             <td><div class="t">${esc(d.title)}</div><div class="muted small">${esc(d.original_filename)}</div></td>
             <td>${esc(sourceLabel(d))}</td><td>${esc(d.unit || "—")}</td><td>${fmtDate(d.created_at)}</td>
             <td><div class="actions">${docActions(d)}</div></td></tr>`).join("")}</tbody></table></div>`
        : `<div class="docs-cards">${docs.map(docCard).join("")}</div>`;
      bindDocActions(box.firstElementChild, docs, load);
    }
    load();
  };

  // ------------------------------------------------------------------ Documento
  routes.documento = async (view, r) => {
    if (API.online !== true) { view.innerHTML = needBackend("O documento"); return; }
    const id = parseInt(r.arg, 10);
    const [d, sections, chunks] = await Promise.all([
      API.get(`/api/library/documents/${id}`),
      API.get(`/api/library/documents/${id}/sections`),
      API.get(`/api/library/documents/${id}/chunks`),
    ]);
    const pageLbl = d.file_type === "pdf" ? "pág." : "pág. ≈";
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow"><a href="#/biblioteca">← Biblioteca</a></p><h1>${esc(d.title)}</h1>
        <p class="sub">${esc(d.original_filename)}</p></div>
        <div class="actions" id="docActs">
          <button class="btn" data-act="original" data-id="${d.id}">${icon("external")}${d.file_type === "pdf" ? "Abrir PDF original" : "Baixar DOCX original"}</button>
          <button class="btn" id="reindexBtn">${icon("refresh")}Reindexar</button>
          <button class="btn danger" data-act="delete" data-id="${d.id}">${icon("trash")}Excluir</button></div></div>
      <section class="card"><dl class="kv">
        <dt>Tipo</dt><dd><span class="badge ${esc(d.file_type)}">${esc(d.file_type.toUpperCase())}</span></dd>
        <dt>Origem</dt><dd>${esc(sourceLabel(d))}</dd>
        <dt>Unidade</dt><dd>${esc(d.unit || "—")}</dd><dt>Obra</dt><dd>${esc(d.project || "—")}</dd>
        <dt>Disciplina</dt><dd>${esc(d.discipline || "—")}</dd><dt>Importado em</dt><dd>${fmtDate(d.created_at)}</dd>
        <dt>Conteúdo</dt><dd>${d.n_sections} seções · ${d.n_chunks} trechos</dd>
        <dt>Impressão digital</dt><dd><code>${esc(d.sha256.slice(0, 16))}…</code> (detecta duplicados)</dd></dl></section>
      <div class="doc-view">
        <nav class="card outline" aria-label="Seções"><h3>Seções detectadas</h3>
          ${sections.length ? `<ol>${sections.map((s) => `<li><a href="javascript:void 0" data-path="${esc(s.path)}" style="padding-left:${8 + (s.level - 1) * 14}px">${esc(s.title)}</a></li>`).join("")}</ol>`
            : `<p class="muted small" style="margin-top:8px">Nenhum título detectado.</p>`}</nav>
        <div class="grid">${chunks.map((c) => `<article class="card chunk" data-path="${esc(c.section_path)}">
          <span class="path">${esc(c.section_path)} · ${pageLbl} ${c.est_page ?? "—"}</span><div class="text">${esc(c.text)}</div></article>`).join("")}</div>
      </div>`;
    bindDocActions($("#docActs"), [d], () => { location.hash = "#/biblioteca"; });
    $(".outline").addEventListener("click", (e) => {
      const a = e.target.closest("[data-path]");
      if (!a) return;
      const target = $$(".chunk").find((c) => c.dataset.path === a.dataset.path || c.dataset.path.startsWith(a.dataset.path + " > "));
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      else toast("Esta seção não tem texto próprio (só subtítulos).");
    });
    $("#reindexBtn").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try { await API.post(`/api/library/documents/${id}/reindex`); toast("Documento reindexado.", "ok"); render(); }
      catch (err) { toast(err.message, "err"); e.target.disabled = false; }
    });
  };

  // ------------------------------------------------------------------ Pesquisa
  function highlight(text, q) {
    const words = [...new Set(q.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").match(/[a-z0-9]{4,}/g) || [])].filter((w) => !STOP.has(w));
    let html = esc(text);
    if (!words.length) return html;
    const plain = html.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    // marca por posição no texto sem acento, preservando o texto original
    const marks = [];
    words.forEach((w) => { let i = 0; while ((i = plain.indexOf(w, i)) !== -1) { marks.push([i, i + w.length]); i += w.length; } });
    if (!marks.length || plain.length !== html.length) return html;
    marks.sort((a, b) => a[0] - b[0]);
    let out = "", last = 0;
    for (const [s, e] of marks) { if (s < last) continue; out += html.slice(last, s) + "<mark>" + html.slice(s, e) + "</mark>"; last = e; }
    return out + html.slice(last);
  }
  routes.pesquisa = async (view, r) => {
    const p = r.params;
    const q = p.get("q") || "";
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">Pesquisa semântica</p><h1>Pesquise pelo significado</h1>
        <p class="sub">Combina o modelo de IA local (E5, pelo sentido) com a busca por palavras (FTS5). Escreva como falaria: “paredes dos banheiros com cerâmica”.</p></div></div>
      <form class="card hero" id="sForm" role="search">
        <div class="searchbar">${icon("search")}<input name="q" value="${esc(q)}" placeholder="Descreva o serviço ou especificação que procura" aria-label="Pesquisa" autocomplete="off">
          <button class="btn primary" type="submit">Pesquisar</button></div>
        <div class="form-grid">
          <label>Modo<select name="mode">
            <option value="hybrid" ${p.get("mode") !== "semantic" && p.get("mode") !== "text" ? "selected" : ""}>Híbrido (significado + palavras)</option>
            <option value="semantic" ${p.get("mode") === "semantic" ? "selected" : ""}>Só significado</option>
            <option value="text" ${p.get("mode") === "text" ? "selected" : ""}>Só palavras</option></select></label>
          <label>Unidade<select name="unit" id="sUnit"><option value="">Todas</option></select></label>
          <label>Obra<select name="project" id="sProj"><option value="">Todas</option></select></label>
          <label>Disciplina<select name="discipline" id="sDisc"><option value="">Todas</option></select></label>
        </div>
      </form>
      <div id="sOut"></div>`;
    const form = $("#sForm");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const qs = new URLSearchParams();
      new FormData(form).forEach((v, k) => v && !(k === "mode" && v === "hybrid") && qs.set(k, v));
      location.hash = `#/pesquisa?${qs}`;
    });
    if (API.online !== true) { $("#sOut").innerHTML = needBackend("A pesquisa"); return; }
    try {
      const st = await API.get("/api/library/stats");
      $("#sUnit").innerHTML = options(st.facets.unit, p.get("unit"), "Todas");
      $("#sProj").innerHTML = options(st.facets.project, p.get("project"), "Todas");
      $("#sDisc").innerHTML = options(st.facets.discipline, p.get("discipline"), "Todas");
    } catch { /* sem filtros */ }
    if (!q) { $("#sOut").innerHTML = ""; form.q.focus(); return; }
    const out = $("#sOut");
    out.innerHTML = `<div class="card empty"><svg class="spin"><use href="#i-refresh"/></svg><p>Pesquisando… (a 1ª pesquisa após ligar o backend carrega o modelo e leva alguns segundos)</p></div>`;
    const qs = new URLSearchParams({ q, limit: "20" });
    ["mode", "unit", "project", "discipline"].forEach((k) => p.get(k) && qs.set(k, p.get(k)));
    let res;
    try { res = await API.get(`/api/search?${qs}`); }
    catch (e) { out.innerHTML = `<div class="notice err">${icon("alert")}<div>${esc(e.message)}</div></div>`; return; }
    const warn = res.warnings.map((w) => `<div class="notice">${icon("alert")}<div>${esc(w)}</div></div>`).join("");
    const head = `<div class="notice info">${icon("search")}<div><b>${res.results.length} trecho(s)</b> ordenados por <b>relevância relativa</b>
      (100 = 1º lugar no significado e nas palavras; ≤ 50 = só uma das buscas encontrou). <b>Não é probabilidade nem equivalência técnica</b>:
      revise sempre o trecho antes de reutilizar.${res.semantic_used ? ` Modelo: <code>${esc(res.model)}</code>.` : ""}</div></div>`;
    if (!res.results.length) { out.innerHTML = warn + `<div class="card empty">${icon("search")}<h3>Nenhum trecho encontrado</h3><p>Tente outras palavras ou remova filtros.</p></div>`; return; }
    out.innerHTML = `<div class="grid">${warn}${head}${res.results.map((x, i) => `
      <article class="card result">
        <div class="meta">
          <div class="origin"><strong>${esc(x.document_title)}</strong>
            <span class="path">${esc(x.original_filename)} · <span class="badge ${esc(x.file_type)}">${esc(x.file_type.toUpperCase())}</span>
              ${x.unit ? ` · ${esc(x.unit)}` : ""}${x.project ? ` · ${esc(x.project)}` : ""}${x.discipline ? ` · ${esc(x.discipline)}` : ""}</span>
            <span class="path">Seção: ${esc(x.section_path)} · ${x.file_type === "pdf" ? "pág." : "pág. ≈"} ${x.est_page ?? "—"}</span></div>
          <div class="rel"><span class="val">${x.relative_relevance}</span><span class="bar"><i style="width:${x.relative_relevance}%"></i></span>
            <span class="badge ${x.found_by.length > 1 ? "both" : "one"}">${x.found_by.length > 1 ? "significado + palavras" : x.found_by[0] === "semântica" ? "só significado" : "só palavras"}</span></div>
        </div>
        <div class="text">${highlight(x.text, q)}</div>
        <div class="actions"><a class="btn sm" href="#/documento/${x.document_id}">${icon("book")}Abrir documento</a>
          <button class="btn sm" data-orig="${i}">${icon("external")}Original</button>
          <button class="btn sm" data-copy="${i}" title="Copia o trecho com a referência de origem">${icon("copy")}Copiar com origem</button></div>
      </article>`).join("")}</div>`;
    out.addEventListener("click", async (e) => {
      const o = e.target.closest("[data-orig]");
      if (o) openDoc(res.results[+o.dataset.orig]);
      const c = e.target.closest("[data-copy]");
      if (c) {
        const x = res.results[+c.dataset.copy];
        const ref = `[Origem: ${x.document_title} (${x.original_filename}) — ${x.section_path}${x.unit ? " — " + x.unit : ""}${x.project ? " — " + x.project : ""}]`;
        try { await navigator.clipboard.writeText(`${x.text}\n\n${ref}`); toast("Trecho copiado com a origem. Revise antes de usar.", "ok"); }
        catch { toast("Não foi possível copiar (permissão do navegador).", "err"); }
      }
    });
  };

  // ------------------------------------------------------------------ Projetos (IFC)
  const DISCS = ["Arquitetura", "Estrutura", "Estrutura metálica", "Hidrossanitário", "Elétrica", "Climatização", "Instalações (indefinida)", "Outros", "Pendente"];
  const FILE_DISCS = ["", "Arquitetura", "Estrutura", "Estrutura metálica", "Hidrossanitário", "Elétrica", "Climatização", "Outras"];
  const fmtNum = (v, d = 2) => (typeof v === "number" ? v.toLocaleString("pt-BR", { maximumFractionDigits: d }) : "—");
  const fmtSize = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
  const METHOD = {
    explicito: ["Explícito no IFC", "m-exp"], atributo: ["Atributo do elemento", "m-exp"],
    geometrico: ["Calculado pela geometria", "m-geo"], regra: ["Calculado por regra", "m-rule"],
  };
  const methodBadge = (m) => { const [l, c] = METHOD[m] || [m, ""]; return `<span class="badge ${c}">${esc(l)}</span>`; };
  const STATUS_CLS = { "explícito": "m-exp", "calculado": "m-geo", "não encontrado": "m-miss" };
  const confBadge = (c) => `<span class="badge conf-${c === "alta" ? "hi" : c === "média" ? "mid" : "lo"}">confiança ${esc(c)}</span>`;

  routes.projetos = async (view) => {
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">Projetos</p><h1>Projetos de engenharia</h1>
        <p class="sub">Reúna os arquivos de cada obra (IFC, PDF, DOCX e imagens). Os modelos IFC são lidos automaticamente e viram um inventário técnico com a origem de cada informação.</p></div></div>
      <form class="card" id="newProj"><h2>Novo projeto</h2>
        <div class="form-grid" style="margin-top:12px">
          <label>Nome do projeto *<input name="name" required placeholder="ex.: Reforma do Bloco de Salas"></label>
          <label>Localização<input name="location" placeholder="ex.: SENAI Porto Velho/RO"></label>
          <label>Descrição<input name="description" placeholder="opcional"></label>
          <div class="actions" style="align-self:end"><button class="btn primary" ${API.online === true ? "" : "disabled"}>${icon("cube")}Criar projeto</button></div>
        </div></form>
      <div id="projList"></div>`;
    if (API.online !== true) { $("#projList").innerHTML = needBackend("Os projetos"); return; }
    $("#newProj").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = Object.fromEntries(new FormData(e.target));
      try { const p = await API.post("/api/projects", fd); toast("Projeto criado.", "ok"); location.hash = `#/projeto/${p.id}`; }
      catch (err) { toast(err.message, "err"); }
    });
    const list = await API.get("/api/projects");
    $("#projList").innerHTML = list.length ? `<div class="docs-cards">${list.map((p) => `
      <a class="card doc proj" href="#/projeto/${p.id}">
        <div class="top"><span class="badge src">${icon("cube")}${p.ifc_models} modelo(s) IFC</span><span class="muted small">${fmtDate(p.updated_at)}</span></div>
        <h3>${esc(p.name)}</h3>
        <p class="file">${esc(p.location || "Sem localização")}</p>
        ${p.description ? `<p class="muted small">${esc(p.description)}</p>` : ""}
        <div class="chips">${Object.entries(p.file_counts).map(([k, n]) => `<span class="chip">${n} ${esc(k.toUpperCase())}</span>`).join("") || `<span class="chip">sem arquivos</span>`}</div>
      </a>`).join("")}</div>`
      : `<div class="card empty">${icon("cube")}<h3>Nenhum projeto ainda</h3><p>Crie o primeiro projeto acima e envie os modelos IFC.</p></div>`;
  };

  routes.projeto = async (view, r) => {
    if (API.online !== true) { view.innerHTML = needBackend("O projeto"); return; }
    const pid = parseInt(r.arg, 10);
    const seq = routeSeq;
    const [p, files, models] = await Promise.all([
      API.get(`/api/projects/${pid}`), API.get(`/api/projects/${pid}/files`), API.get(`/api/projects/${pid}/ifc-models`),
    ]);
    const selModel = models.find((m) => String(m.id) === r.params.get("modelo")) || models[0];
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow"><a href="#/projetos">← Projetos</a></p><h1>${esc(p.name)}</h1>
        <p class="sub">${esc([p.location, p.description].filter(Boolean).join(" · ") || "Sem descrição")}</p></div>
        <div class="actions"><button class="btn danger" id="delProj">${icon("trash")}Excluir projeto</button></div></div>
      <section class="card">
        <div class="page-head"><h2>Arquivos do projeto</h2><span class="muted small">IFC até ${API.cfg.ifc && API.cfg.ifc.max_mb || "?"} MB · PDF/DOCX/imagem até ${API.cfg.max_upload_mb} MB</span></div>
        ${API.cfg.ifc && !API.cfg.ifc.available ? `<div class="notice err" style="margin-top:12px">${icon("alert")}<div><b>Leitor IFC indisponível neste backend:</b> ${esc(API.cfg.ifc.reason)}</div></div>` : ""}
        <div class="up-row">
          <label class="drop small-drop" id="pDrop"><input type="file" id="pFiles" multiple accept=".ifc,.pdf,.docx,.png,.jpg,.jpeg">
            ${icon("upload")}<strong>Arraste IFC, PDF, DOCX ou imagens</strong><span>vários de uma vez · DWG: exporte como IFC/PDF</span></label>
          <label>Disciplina dos arquivos (opcional)<select id="pDisc">${FILE_DISCS.map((d) => `<option value="${esc(d)}">${d || "— não informar —"}</option>`).join("")}</select></label>
        </div>
        <ul class="up-list" id="pUp"></ul>
        <div class="table-wrap"><table class="docs-table" id="filesTbl"><thead><tr><th>Tipo</th><th>Arquivo</th><th>Versão</th><th>Disciplina</th><th>Situação</th><th></th></tr></thead>
          <tbody>${files.length ? files.map(fileRow).join("") : `<tr><td colspan="6" class="muted">Nenhum arquivo ainda.</td></tr>`}</tbody></table></div>
      </section>
      <section class="card" id="teamSec" hidden></section>
      <section class="card" id="memSec"><div class="page-head"><div><h2>Memoriais descritivos</h2>
        <p class="muted small">Gerados por capítulos a partir do modelo IFC (só dados do modelo) + sugestões da biblioteca de memoriais.</p></div>
        <button class="btn primary" id="genMem" ${models.length ? "" : "disabled title='Processe um modelo IFC primeiro'"}>${icon("file")}Gerar memorial descritivo</button></div>
        <div id="memOfProj" style="margin-top:12px"></div></section>
      <section id="inv"></section>
      <details class="card"><summary><h2 style="display:inline">Histórico do projeto</h2></summary><div id="hist" style="margin-top:12px"></div></details>`;

    $("#delProj").addEventListener("click", async () => {
      if (!confirm(`Excluir o projeto «${p.name}»? Os arquivos originais continuam guardados.`)) return;
      try { await API.del(`/api/projects/${pid}`); toast("Projeto excluído.", "ok"); location.hash = "#/projetos"; } catch (e) { toast(e.message, "err"); }
    });
    $("details.card").addEventListener("toggle", async (e) => {
      if (!e.target.open) return;
      const h = await API.get(`/api/projects/${pid}/history`);
      $("#hist").innerHTML = `<ul class="hist">${h.map((x) => `<li><span class="muted small">${esc(x.at)}</span> <b>${esc(x.event)}</b>
        <span class="muted small">${esc(Object.entries(x.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))}</span></li>`).join("")}</ul>`;
    });

    // ações dos arquivos
    $("#filesTbl").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-f]");
      if (!b) return;
      const fid = b.dataset.id;
      const f = files.find((x) => String(x.id) === fid);
      try {
        if (b.dataset.f === "orig") await openProjectFile(pid, f);
        if (b.dataset.f === "cancel") { await API.post(`/api/jobs/${b.dataset.job}/cancel`); toast("Cancelamento solicitado."); }
        if (b.dataset.f === "reproc") { await API.post(`/api/projects/${pid}/files/${fid}/reprocess`); toast("Reprocessamento na fila.", "ok"); render(); }
        if (b.dataset.f === "del" && confirm(`Remover «${f.original_filename}» do projeto?`)) { await API.del(`/api/projects/${pid}/files/${fid}`); toast("Arquivo removido.", "ok"); render(); }
      } catch (err) { toast(err.message, "err"); }
    });

    // envio de vários arquivos
    const drop = $("#pDrop");
    const sendFiles = async (list) => {
      const items = [...list].map((file) => ({ file, msg: "Aguardando", state: "wait", pct: 0 }));
      const draw = () => { $("#pUp").innerHTML = items.map((q) => `<li class="up-item ${q.state}">${icon(q.state === "ok" ? "check" : q.state === "err" ? "alert" : "file")}
        <span class="name">${esc(q.file.name)}</span><span class="muted small">${fmtSize(q.file.size)}</span>
        <span class="progress"><i class="${q.indet ? "indet" : ""}" style="width:${q.indet ? "" : Math.round(q.pct * 100) + "%"}"></i></span><span class="st">${esc(q.msg)}</span></li>`).join(""); };
      draw();
      for (const q of items) {
        q.state = "busy"; draw();
        try {
          const res = await API.upload(q.file, { discipline: $("#pDisc").value }, (phase, pct) => {
            if (phase === "upload") { q.pct = pct; q.msg = `Enviando… ${Math.round(pct * 100)}%`; } else { q.indet = true; q.msg = "Conferindo o arquivo…"; }
            draw();
          }, `/api/projects/${pid}/files`);
          q.state = "ok"; q.indet = false; q.pct = 1;
          q.msg = res.job ? `Recebido (versão ${res.file.version}). Leitura do IFC em segundo plano — acompanhe na tabela.` : `Recebido (versão ${res.file.version}) e guardado no projeto.`;
        } catch (err) { q.state = "err"; q.indet = false; q.msg = err.message; }
        draw();
      }
      setTimeout(() => routeSeq === seq && render(), 600);
    };
    $("#pFiles").addEventListener("change", (e) => { sendFiles(e.target.files); e.target.value = ""; });
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => sendFiles(e.dataTransfer.files));

    teamSection($("#teamSec"), pid).catch(() => {});
    // memoriais do projeto
    API.get(`/api/projects/${pid}/memorials`).then((ms) => {
      const box = $("#memOfProj");
      if (!box || routeSeq !== seq) return; // o usuário já mudou de tela
      box.innerHTML = ms.length ? `<ul class="plain">${ms.map((x) => `<li><a href="#/memorial/${x.id}">${esc(x.title)}</a>
        <span class="muted small">· ${x.n_approved || 0} de ${x.n_chapters} capítulos aprovados · ${fmtDate(x.updated_at)}</span></li>`).join("")}</ul>`
        : `<p class="muted small">Nenhum memorial gerado ainda.</p>`;
    }).catch(() => {});
    $("#genMem").addEventListener("click", async (e) => {
      const msel = $("#modelSel");
      const modelId = msel ? parseInt(msel.value, 10) : (models[0] && models[0].id);
      e.currentTarget.disabled = true;
      e.currentTarget.lastChild.textContent = "Gerando capítulos…";
      try { const mm = await API.post(`/api/projects/${pid}/memorials`, { model_id: modelId }); toast("Memorial gerado. Revise cada capítulo.", "ok"); location.hash = `#/memorial/${mm.id}`; }
      catch (err) { toast(err.message, "err"); render(); }
    });

    // acompanhamento das tarefas (segundo plano)
    const active = files.some((f) => f.last_job && ["na fila", "executando"].includes(f.last_job.status));
    if (active) pollJobs(pid, seq);

    // inventário IFC
    const inv = $("#inv");
    if (!models.length) {
      inv.innerHTML = `<div class="card empty">${icon("layers")}<h3>Nenhum modelo IFC processado</h3><p>Envie um arquivo .ifc (IFC2X3, IFC4 ou IFC4X3). A leitura acontece em segundo plano.</p></div>`;
      return;
    }
    renderInventory(inv, pid, models, selModel);
  };

  function fileRow(f) {
    const j = f.last_job;
    const running = j && ["na fila", "executando"].includes(j.status);
    const st = f.kind !== "ifc" ? `<span class="muted small">guardado (leitura na Fase 2)</span>`
      : running ? `<div class="job" data-job="${j.id}"><span class="small">${esc(j.message || j.status)}</span><span class="progress"><i style="width:${Math.round(j.progress * 100)}%"></i></span></div>`
      : f.status === "processado" ? `<span class="badge m-exp">processado · ${f.ifc_model ? f.ifc_model.n_elements : 0} elementos</span>`
      : f.status === "erro" ? `<span class="badge m-miss" title="${esc(f.error)}">erro</span> <span class="small">${esc(f.error || "")}</span>`
      : `<span class="badge">${esc(f.status)}</span>`;
    return `<tr data-row="${f.id}"><td><span class="badge ${f.kind === "ifc" ? "ifc" : esc(f.kind)}">${esc(f.kind.toUpperCase())}</span></td>
      <td><div class="t">${esc(f.original_filename)}</div><div class="muted small">${fmtSize(f.size_bytes)} · ${fmtDate(f.created_at)}</div></td>
      <td>v${f.version}${f.previous_file_id ? ` <span class="muted small">(substitui v${f.version - 1})</span>` : ""}</td><td>${esc(f.discipline || "—")}</td><td>${st}</td>
      <td><div class="actions">
        ${running ? `<button class="btn sm" data-f="cancel" data-id="${f.id}" data-job="${j.id}">${icon("x")}Cancelar</button>` : ""}
        <button class="btn sm" data-f="orig" data-id="${f.id}">${icon("external")}Original</button>
        ${f.kind === "ifc" && !running ? `<button class="btn sm" data-f="reproc" data-id="${f.id}" title="Ler o IFC novamente">${icon("refresh")}</button>` : ""}
        <button class="btn sm danger" data-f="del" data-id="${f.id}" title="Remover do projeto">${icon("trash")}</button></div></td></tr>`;
  }

  async function openProjectFile(pid, f) {
    try {
      const url = API.demo ? Demo.fileUrl(`/api/projects/${pid}/files/${f.id}/original`)
        : `${API.base}/api/projects/${pid}/files/${f.id}/original${f.kind === "pdf" || f.kind === "image" ? "?inline=true" : ""}`;
      const r = await fetch(url, { headers: API.headers() });
      if (!r.ok) throw new Error(`Erro ${r.status}`);
      const blobUrl = URL.createObjectURL(await r.blob());
      if (f.kind === "pdf" || f.kind === "image") window.open(blobUrl, "_blank", "noopener");
      else saveBlob(await (await fetch(blobUrl)).blob(), f.original_filename);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
    } catch (e) { toast(e.message, "err"); }
  }

  async function pollJobs(pid, seq) {
    if (routeSeq !== seq) return;
    let list;
    try { list = await API.get(`/api/jobs?project_id=${pid}`); } catch { return; }
    if (routeSeq !== seq) return;
    let stillActive = false;
    for (const j of list) {
      const box = document.querySelector(`.job[data-job="${j.id}"]`);
      if (!box) continue;
      if (["na fila", "executando"].includes(j.status)) {
        stillActive = true;
        $(".small", box).textContent = j.message || j.status;
        $(".progress i", box).style.width = `${Math.round(j.progress * 100)}%`;
      }
    }
    if (stillActive) setTimeout(() => pollJobs(pid, seq), 1200);
    else { toast("Processamento concluído.", "ok"); render(); }
  }

  function renderInventory(inv, pid, models, m) {
    const s = m.summary;
    const elsWithMissing = Object.values(s.missing_info || {}).length;
    inv.innerHTML = `
      <section class="card">
        <div class="page-head"><div><p class="eyebrow">Inventário técnico do modelo</p><h2>${esc(m.original_filename)} <span class="muted">v${m.version}</span></h2>
          <p class="muted small">${esc(m.schema_name)} · ${esc(m.header.originating_system || m.header.application || "aplicativo não informado")} · lido em ${fmtNum(m.parse_seconds)} s · ${fmtDate(m.processed_at)}</p></div>
          <div class="actions">${models.length > 1 ? `<select id="modelSel">${models.map((x) => `<option value="${x.id}" ${x.id === m.id ? "selected" : ""}>${esc(x.original_filename)} v${x.version} (${esc(x.schema_name)})</option>`).join("")}</select>` : ""}
          <a class="btn sm primary" href="#/modelo3d/${m.id}">${icon("layers")}Ver em 3D</a>
          <button class="btn sm" id="expInv">${icon("external")}Exportar JSON</button></div></div>
        <div class="grid stats" style="margin-top:16px">
          <div class="stat"><span class="num">${fmtNum(s.elements_total, 0)}</span><span class="lbl">Elementos</span><span class="hint">${s.auxiliary_ignored} auxiliares ignorados (aberturas etc.)</span></div>
          <div class="stat"><span class="num">${Object.keys(s.classes).length}</span><span class="lbl">Categorias IFC</span></div>
          <div class="stat"><span class="num">${s.storeys.length}</span><span class="lbl">Pavimentos</span></div>
          <div class="stat"><span class="num">${s.materials.length}</span><span class="lbl">Materiais</span></div>
          <div class="stat"><span class="num">${s.pending_classification}</span><span class="lbl">Sem disciplina definida</span><span class="hint">${s.elements_with_suggestion} com sugestão pelo nome</span></div>
        </div>
        ${(s.warnings || []).map((w) => `<div class="notice" style="margin-top:12px">${icon("alert")}<div>${esc(w)}</div></div>`).join("")}
        ${s.read_errors ? `<div class="notice err" style="margin-top:12px">${icon("alert")}<div>${s.read_errors} elemento(s) com erro de leitura.</div></div>` : ""}
      </section>
      <div class="inv-grid">
        <section class="card"><h3>Disciplinas</h3><p class="muted small">Classificação por regras (classe IFC, tipo, sistema, propriedades, material). Nome sozinho nunca classifica.</p>
          <table class="docs-table"><thead><tr><th>Disciplina</th><th>Total</th><th>Alta</th><th>Média</th><th>Baixa</th></tr></thead><tbody>
          ${Object.entries(s.disciplines).map(([d, v]) => `<tr><td><a href="javascript:void 0" data-filter="discipline" data-v="${esc(d)}">${esc(d)}</a></td><td><b>${v.total}</b></td><td>${v.alta}</td><td>${v["média"]}</td><td>${v.baixa}</td></tr>`).join("")}</tbody></table></section>
        <section class="card"><h3>Pavimentos</h3><table class="docs-table"><thead><tr><th>Pavimento</th><th>Cota</th><th>Elementos</th></tr></thead><tbody>
          ${s.storeys.map((x) => `<tr><td><a href="javascript:void 0" data-filter="storey" data-v="${esc(x.name)}">${esc(x.name)}</a></td><td>${x.elevation_m == null ? "—" : fmtNum(x.elevation_m) + " m"}</td><td>${x.elements}</td></tr>`).join("")}</tbody></table></section>
        <section class="card"><h3>Materiais</h3><table class="docs-table"><thead><tr><th>Material</th><th>Elementos</th></tr></thead><tbody>
          ${s.materials.slice(0, 15).map((x) => `<tr><td>${esc(x.name)}</td><td>${x.elements}</td></tr>`).join("") || `<tr><td colspan="2" class="muted">Nenhum material associado no IFC.</td></tr>`}</tbody></table>
          ${s.materials.length > 15 ? `<p class="muted small">+ ${s.materials.length - 15} materiais</p>` : ""}</section>
        <section class="card"><h3>Informações ausentes</h3><p class="muted small">Itens que um memorial normalmente precisa e que <b>não estão</b> no IFC. Nada foi inventado.</p>
          <div class="chips" style="margin-top:10px">${Object.entries(s.missing_info).map(([k, n]) => `<a class="chip miss" href="javascript:void 0" data-filter="missing" data-v="${esc(k)}">${esc(k)}: ${n} elemento(s)</a>`).join("") || `<span class="chip">Nenhuma ausência detectada</span>`}</div>
          ${elsWithMissing ? `<p style="margin-top:10px"><a href="javascript:void 0" data-filter="missing" data-v="any">Ver todos os elementos com informação ausente →</a></p>` : ""}</section>
      </div>
      <section class="card"><h3>Quantidades por categoria</h3>
        <p class="muted small">Somatório por regra dos valores de cada elemento, <b>separado por método de origem</b> (explícito no IFC × calculado pela geometria). Aproximações para conferência — <b>não são quantitativos executivos</b>.</p>
        <div class="table-wrap"><table class="docs-table"><thead><tr><th>Categoria IFC</th><th>Quantidade</th><th>Total</th><th>Elementos</th><th>Origem</th></tr></thead><tbody>
        ${s.quantity_totals.filter((t) => t.unit !== "un").map((t) => `<tr><td>${esc(t.ifc_class)}</td><td>${esc(t.quantity)}</td><td><b>${fmtNum(t.total, 3)} ${esc(t.unit)}</b></td><td>${t.elements}</td><td>${methodBadge(t.method)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">Nenhuma quantidade disponível.</td></tr>`}</tbody></table></div>
        ${s.geometry ? `<p class="muted small" style="margin-top:8px">Cálculo geométrico: ${esc(s.geometry.status)} · ${s.geometry.computed || 0} elemento(s) em ${fmtNum(s.geometry.seconds || 0)} s${s.geometry.failed ? ` · ${s.geometry.failed} falha(s)` : ""}. ${esc(s.geometry.method || "")}</p>` : ""}</section>
      <section class="card" id="elemSec"><h3>Elementos</h3>
        <form class="toolbar" id="elFilter" style="padding:10px 0">
          <input type="search" name="q" placeholder="Nome, tipo ou GlobalId">
          <select name="discipline"><option value="">Todas as disciplinas</option>${DISCS.map((d) => `<option>${d}</option>`).join("")}</select>
          <select name="ifc_class"><option value="">Todas as categorias</option>${Object.keys(s.classes).sort().map((c) => `<option>${esc(c)}</option>`).join("")}</select>
          <select name="storey"><option value="">Todos os pavimentos</option>${s.storeys.map((x) => `<option>${esc(x.name)}</option>`).join("")}</select>
          <select name="missing"><option value="">Com ou sem ausências</option><option value="any">Com informação ausente</option>${Object.keys(s.missing_info).map((k) => `<option value="${esc(k)}">Sem ${esc(k)}</option>`).join("")}</select>
        </form>
        <div id="elTable"></div></section>`;
    const sel = $("#modelSel");
    if (sel) sel.addEventListener("change", () => { location.hash = `#/projeto/${pid}?modelo=${sel.value}`; });
    $("#expInv").addEventListener("click", async () => {
      try {
        const data = await API.get(`/api/ifc-models/${m.id}/export`);
        saveBlob(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
          `inventario_${m.original_filename.replace(/\.ifc$/i, "")}_v${m.version}.json`);
      } catch (e) { toast(e.message, "err"); }
    });
    const form = $("#elFilter");
    let offset = 0;
    const load = async () => {
      const qs = new URLSearchParams({ limit: "50", offset: String(offset) });
      new FormData(form).forEach((v, k) => v && qs.set(k, v));
      const box = $("#elTable");
      if (!box) return;
      let res;
      try { res = await API.get(`/api/ifc-models/${m.id}/elements?${qs}`); } catch (e) { if (!box.isConnected) return; box.innerHTML = `<div class="notice err">${icon("alert")}<div>${esc(e.message)}</div></div>`; return; }
      if (!box.isConnected) return; // a tela mudou enquanto carregava
      box.innerHTML = res.items.length ? `<div class="table-wrap"><table class="docs-table el-table"><thead><tr><th>Elemento</th><th>Categoria IFC</th><th>Pavimento</th><th>Disciplina</th><th>Ausente</th></tr></thead><tbody>
        ${res.items.map((x) => `<tr data-el="${x.id}" tabindex="0"><td><div class="t">${esc(x.name || "(sem nome)")}</div><div class="muted small">${esc(x.type_name || "")}</div></td>
          <td>${esc(x.ifc_class)}${x.predefined_type && x.predefined_type !== "NOTDEFINED" ? ` <span class="muted small">${esc(x.predefined_type)}</span>` : ""}</td><td>${esc(x.storey || "—")}</td>
          <td>${esc(x.discipline)} ${confBadge(x.confidence)}</td><td>${x.missing.map((k) => `<span class="chip miss">${esc(k)}</span>`).join(" ")}</td></tr>`).join("")}</tbody></table></div>
        <div class="pager"><span class="muted small">${res.offset + 1}–${res.offset + res.items.length} de ${res.total}</span>
          <button class="btn sm" id="pgPrev" ${res.offset ? "" : "disabled"}>Anterior</button><button class="btn sm" id="pgNext" ${res.offset + res.items.length < res.total ? "" : "disabled"}>Próxima</button></div>`
        : `<p class="muted">Nenhum elemento com esses filtros.</p>`;
      const prev = $("#pgPrev"), next = $("#pgNext");
      if (prev) prev.onclick = () => { offset = Math.max(0, offset - 50); load(); };
      if (next) next.onclick = () => { offset += 50; load(); };
    };
    form.addEventListener("input", () => { offset = 0; load(); });
    form.addEventListener("submit", (e) => e.preventDefault());
    inv.addEventListener("click", (e) => {
      const a = e.target.closest("[data-filter]");
      if (a) {
        ["discipline", "storey", "missing", "ifc_class"].forEach((k) => { form[k].value = ""; });
        form.q.value = "";
        const fieldVal = a.dataset.filter === "storey" && a.dataset.v === "(sem pavimento)" ? "" : a.dataset.v;
        if (form[a.dataset.filter].querySelector(`option[value="${CSS.escape(fieldVal)}"]`) || a.dataset.filter !== "storey") form[a.dataset.filter].value = fieldVal;
        offset = 0; load();
        $("#elemSec").scrollIntoView({ behavior: "smooth" });
      }
      const row = e.target.closest("[data-el]");
      if (row) openElement(row.dataset.el);
    });
    inv.addEventListener("keydown", (e) => { const row = e.target.closest("[data-el]"); if (row && e.key === "Enter") openElement(row.dataset.el); });
    load();
  }

  // ficha técnica do elemento (dados do IFC, com origem e método de cada quantidade)
  function elementSheet(el) {
    const psets = Object.entries(el.psets || {});
    return `
      <dl class="kv">
        <dt>GlobalId</dt><dd><code>${esc(el.global_id)}</code></dd>
        ${el.type_name ? `<dt>Tipo</dt><dd>${esc(el.type_name)} <span class="muted small">${esc(el.type_class || "")}</span></dd>` : ""}
        ${el.predefined_type ? `<dt>PredefinedType</dt><dd>${esc(el.predefined_type)}</dd>` : ""}
        ${el.tag ? `<dt>Tag</dt><dd>${esc(el.tag)}</dd>` : ""}
        ${el.description ? `<dt>Descrição</dt><dd>${esc(el.description)}</dd>` : ""}
        <dt>Pavimento</dt><dd>${esc(el.storey || "não encontrado")}</dd>
        ${el.systems && el.systems.length ? `<dt>Sistemas</dt><dd>${el.systems.map((s) => esc(`${s.name}${s.predefined ? " (" + s.predefined + ")" : ""}`)).join(", ")}</dd>` : ""}
        ${el.classification && el.classification.length ? `<dt>Classificação</dt><dd>${el.classification.map((c) => esc(`${c.system || ""} ${c.code || ""} ${c.name || ""}`)).join("; ")}</dd>` : ""}
      </dl>
      <div class="drawer-sec"><h3>Disciplina: ${esc(el.discipline)} ${confBadge(el.confidence)}</h3>
        <p class="muted small">Motivos: ${esc((el.reasons || []).join("; "))}</p>
        ${el.suggestion ? `<div class="notice" style="margin-top:8px">${icon("info")}<div><b>Sugestão inferida:</b> ${esc(el.suggestion.discipline)} — ${esc(el.suggestion.reason)}.</div></div>` : ""}</div>
      <div class="drawer-sec"><h3>Informações para o memorial</h3>
        <table class="docs-table"><tbody>${(el.checks || []).map((c) => `<tr><td>${esc(c.info)}</td><td><span class="badge ${STATUS_CLS[c.status] || ""}">${esc(c.status)}</span></td><td>${esc(c.value || "—")}${c.source ? ` <span class="muted small">(${esc(c.source)})</span>` : ""}</td></tr>`).join("") || `<tr><td class="muted">Sem verificação para esta categoria.</td></tr>`}</tbody></table></div>
      <div class="drawer-sec"><h3>Materiais</h3>${el.materials && el.materials.length ? `<ul class="plain">${el.materials.map((x) => `<li>${esc(x.name || "(sem nome)")}${x.thickness_m ? ` — ${fmtNum(x.thickness_m * 100, 1)} cm` : ""}${x.profile ? ` — perfil ${esc(x.profile)}` : ""} <span class="muted small">${esc(x.source)}</span></li>`).join("")}</ul>${el.material_set && el.material_set.name ? `<p class="muted small">Conjunto: ${esc(el.material_set.name)}</p>` : ""}` : `<p class="muted">Não encontrado no IFC.</p>`}</div>
      <div class="drawer-sec"><h3>Quantidades</h3>${el.quantities && el.quantities.length ? `<table class="docs-table"><thead><tr><th>Nome</th><th>Valor</th><th>Origem</th></tr></thead><tbody>
        ${el.quantities.map((q) => `<tr><td>${esc(q.name)}<div class="muted small">${esc(q.source || "")}</div></td><td><b>${fmtNum(q.value, 4)} ${esc(q.unit)}</b></td><td>${methodBadge(q.method)}${q.note ? `<div class="muted small">${esc(q.note)}</div>` : ""}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Nenhuma quantidade no IFC e nenhuma calculada.</p>`}</div>
      <div class="drawer-sec"><h3>Property Sets (${psets.length})</h3>${psets.map(([n, props]) => `<details><summary>${esc(n)}</summary><table class="docs-table"><tbody>
        ${Object.entries(props || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("")}</tbody></table></details>`).join("") || `<p class="muted">Nenhum Property Set.</p>`}</div>`
  }

  async function openElement(eid) {
    let el;
    try { el = await API.get(`/api/ifc-elements/${eid}`); } catch (e) { toast(e.message, "err"); return; }
    let d = $("#drawer");
    if (!d) {
      d = document.createElement("aside");
      d.id = "drawer"; d.className = "drawer glass-strong"; d.setAttribute("role", "dialog"); d.setAttribute("aria-label", "Detalhes do elemento");
      document.body.appendChild(d);
      d.addEventListener("click", (e) => { if (e.target.closest("[data-close-drawer]")) d.classList.remove("open"); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") d.classList.remove("open"); });
    }
    d.innerHTML = `
      <header class="modal-head"><div style="flex:1"><p class="eyebrow">${esc(el.ifc_class)}</p><h2>${esc(el.name || "(sem nome)")}</h2></div>
        <button class="icon-btn" data-close-drawer aria-label="Fechar">${icon("x")}</button></header>
      ${elementSheet(el)}`;
    requestAnimationFrame(() => d.classList.add("open"));
  }

  // ------------------------------------------------------------------ Memorial em elaboração
  async function downloadExport(mid, draft) {
    try {
      if (API.demo) {
        if (!draft) throw new Error(Demo.RO);
        const r = await fetch(Demo.fileUrl(`/api/memorials/${mid}/export?draft=true`));
        if (!r.ok) throw new Error("Minuta não disponível na demonstração.");
        saveBlob(await r.blob(), "Memorial descritivo - EXEMPLO - MINUTA.docx");
        toast("Minuta do exemplo baixada (gerada pelo sistema real; marcada como não revisada).", "ok");
        return;
      }
      const r = await fetch(`${API.base}/api/memorials/${mid}/export?draft=${draft}`, { headers: API.headers() });
      if (!r.ok) { let d = `Erro ${r.status}`; try { d = detailText((await r.json()).detail) || d; } catch { /* */ } throw new Error(d); }
      const cd = r.headers.get("content-disposition") || "";
      const m = cd.match(/filename\*=UTF-8''([^;]+)/);
      saveBlob(await r.blob(), m ? decodeURIComponent(m[1]) : `memorial${draft ? "_MINUTA" : ""}.docx`);
      toast(draft ? "Minuta exportada (marcada como não revisada)." : "Memorial final exportado.", "ok");
    } catch (e) { toast(e.message, "err"); }
  }

  routes.memoriais = async (view) => {
    view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Memorial em elaboração</p><h1>Memoriais descritivos</h1>
      <p class="sub">Gerados por capítulos a partir dos modelos IFC de cada projeto. Os textos de referência da biblioteca entram somente quando você escolhe; nada é exportado como final sem a sua aprovação.</p></div></div><div id="memList"></div>`;
    if (API.online !== true) { $("#memList").innerHTML = needBackend("O memorial"); return; }
    const list = await API.get("/api/memorials");
    $("#memList").innerHTML = list.length ? `<div class="docs-cards">${list.map((m) => `
      <a class="card doc proj" href="#/memorial/${m.id}"><div class="top"><span class="badge src">${icon("file")}${m.n_approved || 0} de ${m.n_chapters} aprovados</span>
        <span class="muted small">${fmtDate(m.updated_at)}</span></div><h3>${esc(m.title)}</h3><p class="file">${esc(m.project_name)}</p></a>`).join("")}</div>`
      : `<div class="card empty">${icon("file")}<h3>Nenhum memorial ainda</h3><p>Abra um <a href="#/projetos">projeto</a> com modelo IFC processado e clique em “Gerar memorial descritivo”.</p></div>`;
  };

  routes.memorial = async (view, r) => {
    if (API.online !== true) { view.innerHTML = needBackend("O memorial"); return; }
    const mid = parseInt(r.arg, 10);
    let m = await API.get(`/api/memorials/${mid}`);
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow"><a href="#/projeto/${m.project_id}">← Projeto</a> · Memorial em elaboração</p>
        <h1 id="memTitle">${esc(m.title)}</h1><p class="sub" id="memProg"></p></div>
        <div class="actions">${m.model_id ? `<a class="btn" href="#/modelo3d/${m.model_id}?memorial=${mid}">${icon("layers")}Memorial 3D</a>` : ""}
          <button class="btn" id="renMem">${icon("gear")}Renomear</button>
          <button class="btn" id="expDraft">${icon("external")}Exportar minuta (DOCX)</button>
          <button class="btn primary" id="expFinal">${icon("check")}Exportar final</button></div></div>
      <div class="notice info">${icon("info")}<div><b>Como funciona:</b> o texto de cada capítulo foi montado <b>só com dados do modelo IFC</b> (veja “Dados do IFC usados”).
        O que falta aparece em <b>Pendências</b>. Trechos dos memoriais de referência ficam em <b>Sugestões</b> e só entram quando você clica em “Inserir” — a origem e o texto original ficam guardados.
        Revise, ajuste e aprove cada capítulo; a exportação final exige todos aprovados.</div></div>
      <div class="mem-layout">
        <nav class="card outline mem-index" aria-label="Capítulos"><h3>Capítulos</h3><ol id="memIdx"></ol>
          <button class="btn sm" id="addCh" style="margin-top:10px">${icon("upload")}Novo capítulo</button></nav>
        <div id="memChs" class="grid"></div>
      </div>`;
    const draw = () => {
      $("#memProg").textContent = `${m.approved} de ${m.chapters.length} capítulos aprovados · atualizado ${fmtDate(m.updated_at)}`;
      $("#expFinal").disabled = !m.ready_for_final;
      $("#expFinal").title = m.ready_for_final ? "" : "Aprove todos os capítulos para exportar a versão final";
      $("#memIdx").innerHTML = m.chapters.map((c, i) => `<li><a href="javascript:void 0" data-go="${c.id}"><span class="st-dot ${c.status === "aprovado" ? "ok" : ""}"></span>${i + 1} ${esc(c.title)}</a></li>`).join("");
      $("#memChs").innerHTML = m.chapters.map((c, i) => chapterCard(c, i + 1, m)).join("");
    };
    draw();
    const wantCap = r.params.get("cap");
    if (wantCap) { const el = document.querySelector(`[data-ch="${CSS.escape(wantCap)}"]`); if (el) setTimeout(() => el.scrollIntoView({ block: "start" }), 50); }
    const reload = async () => { m = await API.get(`/api/memorials/${mid}`); draw(); };
    const replaceChapter = (c) => {
      const i = m.chapters.findIndex((x) => x.id === c.id);
      m.chapters[i] = c;
      m.approved = m.chapters.filter((x) => x.status === "aprovado").length;
      m.ready_for_final = m.approved === m.chapters.length;
      const el = document.querySelector(`[data-ch="${c.id}"]`);
      if (el) el.outerHTML = chapterCard(c, i + 1, m);
      $("#memProg").textContent = `${m.approved} de ${m.chapters.length} capítulos aprovados`;
      $("#expFinal").disabled = !m.ready_for_final;
      const dot = document.querySelector(`[data-go="${c.id}"] .st-dot`);
      if (dot) dot.classList.toggle("ok", c.status === "aprovado");
    };
    $("#expDraft").onclick = () => downloadExport(mid, true);
    $("#expFinal").onclick = () => downloadExport(mid, false);
    $("#renMem").onclick = async () => {
      const t = prompt("Título do memorial:", m.title);
      if (!t) return;
      try { m = { ...m, ...(await API.req(`/api/memorials/${mid}`, { method: "PATCH", body: JSON.stringify({ title: t }), headers: { "Content-Type": "application/json" } })) }; $("#memTitle").textContent = m.title; }
      catch (e) { toast(e.message, "err"); }
    };
    $("#addCh").onclick = async () => {
      const t = prompt("Título do novo capítulo:");
      if (!t) return;
      try { await API.post(`/api/memorials/${mid}/chapters`, { title: t }); await reload(); toast("Capítulo criado no fim do memorial.", "ok"); }
      catch (e) { toast(e.message, "err"); }
    };
    $("#memIdx").addEventListener("click", (e) => {
      const a = e.target.closest("[data-go]");
      if (a) document.querySelector(`[data-ch="${a.dataset.go}"]`).scrollIntoView({ behavior: "smooth", block: "start" });
    });
    const chs = $("#memChs");
    chs.addEventListener("input", (e) => {
      if (e.target.matches("textarea[data-text]")) {
        const card = e.target.closest("[data-ch]");
        $("[data-act=save]", card).disabled = false;
        e.target.style.height = "auto"; e.target.style.height = `${e.target.scrollHeight + 4}px`;
      }
    });
    chs.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]");
      if (!b) return;
      const card = b.closest("[data-ch]");
      const cid = card.dataset.ch;
      const c = m.chapters.find((x) => String(x.id) === cid);
      const patch = (body) => API.req(`/api/memorial-chapters/${cid}`, { method: "PATCH", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
      try {
        switch (b.dataset.act) {
          case "save": replaceChapter(await patch({ text: $("textarea[data-text]", card).value })); toast("Capítulo salvo (volta para rascunho até ser aprovado).", "ok"); break;
          case "approve": replaceChapter(await API.post(`/api/memorial-chapters/${cid}/approve?approved=${c.status !== "aprovado"}`)); break;
          case "rename": { const t = prompt("Título do capítulo:", c.title); if (t) replaceChapter(await patch({ title: t })); break; }
          case "insert": replaceChapter(await API.post(`/api/memorial-chapters/${cid}/insert-reference?chunk_id=${b.dataset.chunk}`)); toast("Trecho inserido no fim do capítulo. Adapte o texto ao projeto e revise.", "ok"); break;
          case "regen": {
            const replace = c.edited && confirm("O texto deste capítulo foi editado.\n\nOK = substituir pelo texto gerado agora do IFC (o atual fica no histórico).\nCancelar = manter o seu texto e atualizar só os dados/pendências.");
            replaceChapter(await API.post(`/api/memorial-chapters/${cid}/regenerate?replace_text=${replace}`)); toast("Capítulo regerado a partir do IFC.", "ok"); break;
          }
          case "sugq": { const q = $("input[data-sugq]", card).value.trim(); replaceChapter(await API.post(`/api/memorial-chapters/${cid}/suggestions?q=${encodeURIComponent(q)}`)); break; }
          case "up": case "down": m = await API.post(`/api/memorial-chapters/${cid}/move?direction=${b.dataset.act === "up" ? -1 : 1}`); draw(); break;
          case "del": if (confirm(`Remover o capítulo «${c.title}»? (o texto fica registrado no histórico do projeto)`)) { m = await API.del(`/api/memorial-chapters/${cid}`) || await API.get(`/api/memorials/${mid}`); await reload(); } break;
          case "hist": {
            const h = await API.get(`/api/memorial-chapters/${cid}/history`);
            $(".hist-box", card).innerHTML = `<ul class="hist">${h.map((x) => `<li><span class="muted small">${esc(x.at)}</span> <b>${esc(x.event)}</b>
              <details><summary class="small">ver texto desta versão</summary><div class="text small">${esc(x.text) || "<i>(vazio)</i>"}</div></details></li>`).join("")}</ul>`;
            break;
          }
          default: break;
        }
      } catch (err) { toast(err.message, "err"); }
    });
  };

  // ------------------------------------------------------------------ Memorial 3D (modelo IFC + capítulos)
  // Liga cada capítulo aos elementos do IFC pelo GlobalId (gravado na geração do memorial) e mostra a
  // ficha técnica de cada elemento. Só lê: nada aqui altera o IFC nem o memorial.
  let viewer3d = null;
  const dispose3d = () => { if (viewer3d) { try { viewer3d.dispose(); } catch { /* */ } viewer3d = null; } };

  async function pick3dTarget(r) {
    const mid = parseInt(r.params.get("memorial") || "", 10);
    if (r.arg) return { modelId: parseInt(r.arg, 10), mid: isNaN(mid) ? null : mid };
    const ms = await API.get("/api/memorials");            // sem modelo indicado: o memorial mais recente
    const withModel = ms.find((x) => x.model_id) || null;
    if (withModel) return { modelId: withModel.model_id, mid: withModel.id };
    const ps = await API.get("/api/projects");
    for (const p of ps) {
      const models = await API.get(`/api/projects/${p.id}/ifc-models`);
      if (models.length) return { modelId: models[0].id, mid: null };
    }
    return { modelId: null, mid: null };
  }

  // todos os elementos do modelo, em páginas (o servidor entrega no máximo 1000 por vez)
  async function allElements(modelId) {
    const items = [];
    for (let offset = 0; ; offset += 1000) {
      const pg = await API.get(`/api/ifc-models/${modelId}/elements?limit=1000&offset=${offset}`);
      items.push(...pg.items);
      if (!pg.items.length || items.length >= pg.total) return { total: pg.total, items };
    }
  }

  routes.modelo3d = async (view, r) => {
    if (API.online !== true) { view.innerHTML = needBackend("O modelo 3D"); return; }
    const seq = routeSeq;
    const { modelId, mid: askedMid } = await pick3dTarget(r);
    if (!modelId) {
      view.innerHTML = `<div class="card empty">${icon("cube")}<h3>Nenhum modelo IFC processado</h3><p>Envie um IFC em um projeto para vê-lo em 3D.</p></div>`;
      return;
    }
    const model = await API.get(`/api/ifc-models/${modelId}`);
    const [elist, mems] = await Promise.all([
      allElements(modelId),
      API.get(`/api/projects/${model.project_id}/memorials`),
    ]);
    const mid = askedMid || ((mems.find((x) => x.model_id === modelId) || {}).id) || null;
    const mem = mid ? await API.get(`/api/memorials/${mid}`) : null;
    if (routeSeq !== seq) return;
    const els = new Map(elist.items.map((e) => [e.global_id, e]));
    const chapters = mem ? mem.chapters : [];
    const chOf = (gid) => chapters.filter((c) => (c.element_ids || []).includes(gid));
    const otherVersion = mem && mem.model_id && mem.model_id !== modelId;

    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow"><a href="#/projeto/${model.project_id}">← Projeto</a>${mem ? ` · <a href="#/memorial/${mem.id}">Memorial</a>` : ""} · Memorial 3D</p>
        <h1>${esc(mem ? mem.title : model.original_filename)}</h1>
        <p class="sub">Modelo «${esc(model.original_filename)}» v${model.version} · ${model.n_elements} elementos · ${esc(model.schema_name)}</p></div></div>
      ${otherVersion ? `<div class="notice">${icon("alert")}<div>Este memorial foi gerado de <b>outra versão</b> do modelo. Os vínculos usam os GlobalIds daquela versão; elementos que não existem nesta aparecem como “não encontrados”.</div></div>` : ""}
      <div class="m3d" id="m3d">
        <aside class="card m3d-side" id="m3dCh" aria-label="Capítulos do memorial">
          <div class="m3d-side-head"><h3>Capítulos</h3><button class="icon-btn" data-toggle="m3dCh" title="Recolher" aria-label="Recolher capítulos">‹</button></div>
          ${mem ? `<p class="muted small">Clique num capítulo para destacar no 3D os elementos de onde o texto saiu.</p>
            <ol class="m3d-list">${chapters.map((c, i) => {
              const n = (c.element_ids || []).length;
              return `<li><button type="button" data-ch="${c.id}" ${n ? "" : "disabled"}><span class="st-dot ${c.status === "aprovado" ? "ok" : ""}"></span>
                <span class="t">${i + 1} ${esc(c.title)}</span><span class="badge" title="${n ? n + " elemento(s) do IFC" : "capítulo sem elementos do IFC"}">${n || "—"}</span></button></li>`;
            }).join("")}</ol>`
            : `<p class="muted small">Este modelo ainda não tem memorial. Gere um na página do projeto para ligar os capítulos ao 3D.</p>`}
        </aside>
        <section class="card m3d-view">
          <div class="m3d-tools">
            <button class="btn sm" data-v="all">${icon("cube")}Mostrar tudo</button>
            <button class="btn sm" data-v="fit">${icon("search")}Enquadrar</button>
            <select data-v="cam" aria-label="Vista"><option value="iso">Vista isométrica</option><option value="topo">Vista de topo</option><option value="frente">Vista frontal</option><option value="lado">Vista lateral</option></select>
            <select data-v="storey" aria-label="Pavimento"><option value="">Todos os pavimentos</option>${[...new Set(elist.items.map((e) => e.storey).filter(Boolean))].map((s) => `<option>${esc(s)}</option>`).join("")}</select>
            <select data-v="disc" aria-label="Disciplina"><option value="">Todas as disciplinas</option>${[...new Set(elist.items.map((e) => e.discipline).filter(Boolean))].sort().map((s) => `<option>${esc(s)}</option>`).join("")}</select>
            <label class="chk"><input type="checkbox" data-v="spaces"> Ambientes</label>
          </div>
          <div class="m3d-canvas" id="m3dCanvas"><div class="m3d-load muted" id="m3dLoad">Carregando o modelo 3D…</div></div>
          <p class="muted small m3d-help">Arraste para girar · botão direito ou Shift + arrastar para mover · roda do mouse para zoom · clique num elemento para ver a ficha.</p>
        </section>
        <aside class="card m3d-side" id="m3dInfo" aria-label="Detalhes"><div class="m3d-side-head"><h3>Detalhes</h3><button class="icon-btn" data-toggle="m3dInfo" title="Recolher" aria-label="Recolher detalhes">›</button></div>
          <div id="m3dBody"><p class="muted small">Selecione um capítulo ou clique num elemento do modelo.</p></div></aside>
      </div>`;

    const body = $("#m3dBody");
    let activeCh = null;
    const setActiveBtn = () => $$("#m3dCh [data-ch]").forEach((b) => b.classList.toggle("on", activeCh && b.dataset.ch === String(activeCh.id)));

    function showChapter(c, zoom = true) {
      activeCh = c;
      setActiveBtn();
      const ids = c.element_ids || [];
      const found = ids.filter((g) => viewer3d && viewer3d.has(g));
      const noShape = ids.filter((g) => !found.includes(g) && els.has(g));
      const missing = ids.filter((g) => !els.has(g));
      if (viewer3d) viewer3d.highlight(found, { zoom });
      viewer3d && viewer3d.select(null);
      body.innerHTML = `<p class="eyebrow">Capítulo</p><h2 class="m3d-h">${esc(c.title)}</h2>
        <p><span class="badge ${c.status === "aprovado" ? "m-exp" : "m-miss"}">${esc(c.status)}</span> ${c.edited ? `<span class="badge m-rule">adaptado pelo usuário</span>` : ""}</p>
        <p class="small"><b>${found.length}</b> elemento(s) destacado(s) no 3D${noShape.length ? ` · ${noShape.length} sem forma 3D no IFC` : ""}${missing.length ? ` · <b>${missing.length} não encontrado(s) nesta versão</b>` : ""}.</p>
        <div class="text small m3d-text">${esc(c.text) || "<i>(sem texto)</i>"}</div>
        ${mem ? `<p><a class="btn sm" href="#/memorial/${mem.id}?cap=${c.id}">${icon("file")}Abrir no editor do memorial</a></p>` : ""}
        <details class="ch-sec" open><summary>Elementos do capítulo (${ids.length})</summary><ul class="plain m3d-els">
          ${ids.map((g) => { const e = els.get(g); return `<li><button type="button" class="linkish" data-gid="${esc(g)}" ${e ? "" : "disabled"}>${esc(e ? (e.name || "(sem nome)") : g)}</button>
            <span class="muted small">${esc(e ? e.ifc_class : "não encontrado nesta versão")}${e && !(viewer3d && viewer3d.has(g)) ? " · sem forma 3D" : ""}</span></li>`; }).join("")}</ul></details>`;
    }

    async function showElement(gid, zoom = false) {
      const e = els.get(gid);
      if (!e) return;
      viewer3d && viewer3d.select(gid, { zoom });
      body.innerHTML = `<p class="muted small">Carregando a ficha…</p>`;
      let d;
      try { d = await API.get(`/api/ifc-elements/${e.id}`); } catch (err) { body.innerHTML = `<div class="notice err">${icon("alert")}<div>${esc(err.message)}</div></div>`; return; }
      const cs = chOf(gid);
      body.innerHTML = `<p class="eyebrow">${esc(d.ifc_class)}</p><h2 class="m3d-h">${esc(d.name || "(sem nome)")}</h2>
        <div class="drawer-sec"><h3>Descrito no memorial</h3>${mem ? (cs.length ? `<ul class="plain">${cs.map((c) => `<li><button type="button" class="linkish" data-goch="${c.id}">${esc(c.title)}</button>
          <span class="muted small">· ${esc(c.status)}</span></li>`).join("")}</ul>` : `<p class="muted small">Nenhum capítulo usa este elemento (veja as pendências do memorial).</p>`) : `<p class="muted small">Sem memorial para este modelo.</p>`}</div>
        ${elementSheet(d)}`;
    }

    view.addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-ch],[data-gid],[data-goch],[data-toggle],[data-v]");
      if (!t || t.tagName === "SELECT" || t.tagName === "INPUT") return;
      if (t.dataset.ch) showChapter(chapters.find((c) => String(c.id) === t.dataset.ch));
      else if (t.dataset.gid) showElement(t.dataset.gid, true);
      else if (t.dataset.goch) showChapter(chapters.find((c) => String(c.id) === t.dataset.goch));
      else if (t.dataset.toggle) $(`#${t.dataset.toggle}`).classList.toggle("collapsed");
      else if (t.dataset.v === "all") { activeCh = null; setActiveBtn(); $("[data-v=storey]").value = ""; $("[data-v=disc]").value = ""; viewer3d && (viewer3d.highlight(null, { zoom: false }), viewer3d.select(null), viewer3d.fit()); body.innerHTML = `<p class="muted small">Selecione um capítulo ou clique num elemento do modelo.</p>`; }
      else if (t.dataset.v === "fit") viewer3d && viewer3d.fit();
    });
    const filter = () => {
      const st = $("[data-v=storey]").value, di = $("[data-v=disc]").value;
      activeCh = null; setActiveBtn();
      if (!viewer3d) return;
      if (!st && !di) { viewer3d.highlight(null); return; }
      viewer3d.highlight(elist.items.filter((e) => (!st || e.storey === st) && (!di || e.discipline === di)).map((e) => e.global_id).filter((g) => viewer3d.has(g)));
    };
    $("[data-v=storey]").addEventListener("change", filter);
    $("[data-v=disc]").addEventListener("change", filter);
    $("[data-v=cam]").addEventListener("change", (ev) => viewer3d && viewer3d.view(ev.target.value));
    $("[data-v=spaces]").addEventListener("change", (ev) => viewer3d && viewer3d.setSpaces(ev.target.checked));

    // carrega o IFC original (o mesmo arquivo guardado no projeto) e desenha no navegador
    try {
      const url = API.demo ? Demo.fileUrl(`/api/projects/${model.project_id}/files/${model.file_id}/original`)
        : `${API.base}/api/projects/${model.project_id}/files/${model.file_id}/original`;
      const [mod, resp] = await Promise.all([import("./viewer3d.js"), fetch(url, { headers: API.headers() })]);
      if (!resp.ok) throw new Error(`não foi possível baixar o IFC (erro ${resp.status})`);
      const bytes = new Uint8Array(await resp.arrayBuffer());
      if (routeSeq !== seq) return;
      dispose3d();
      viewer3d = await mod.createViewer($("#m3dCanvas"), { onPick: (g) => (g ? showElement(g) : (viewer3d.select(null))) });
      const st = await viewer3d.load(bytes);
      if (routeSeq !== seq) { dispose3d(); return; }
      $("#m3dLoad").remove();
      window.__bim3d = { stats: st, viewer: viewer3d }; // usado nos testes automáticos
      const want = r.params.get("cap");
      const c = want && chapters.find((x) => String(x.id) === want);
      if (c) showChapter(c);
      else if (r.params.get("el")) showElement(r.params.get("el"), true);
    } catch (err) {
      const l = $("#m3dLoad");
      if (l) l.innerHTML = `<div class="notice err">${icon("alert")}<div><b>Não foi possível mostrar o 3D:</b> ${esc(err.message)}. Os capítulos e as fichas continuam disponíveis.</div></div>`;
    }
  };

  function chapterCard(c, n, m = {}) {
    const approved = c.status === "aprovado";
    const tables = (c.tables || []).filter((t) => t.rows && t.rows.length).map((t) => `
      <div class="table-wrap"><p class="small"><b>${esc(t.title)}</b> <span class="muted">(quadro gerado do IFC; exportado no Word)</span></p>
      <table class="docs-table"><thead><tr>${t.columns.map((x) => `<th>${esc(x)}</th>`).join("")}</tr></thead>
      <tbody>${t.rows.map((row) => `<tr>${row.map((x) => `<td>${esc(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`).join("");
    return `<article class="card chapter ${approved ? "is-approved" : ""}" data-ch="${c.id}">
      <header class="ch-head"><h2>${n} ${esc(c.title)}</h2>
        <span class="badge ${approved ? "m-exp" : "m-miss"}">${approved ? "aprovado" : "rascunho"}</span>
        ${c.edited ? `<span class="badge m-rule">adaptado pelo usuário</span>` : c.generated_text ? `<span class="badge m-geo">texto gerado do IFC</span>` : ""}
        <span class="ch-tools">
          <button class="icon-btn" data-act="up" title="Mover para cima" aria-label="Mover para cima">↑</button>
          <button class="icon-btn" data-act="down" title="Mover para baixo" aria-label="Mover para baixo">↓</button>
          <button class="icon-btn" data-act="rename" title="Renomear" aria-label="Renomear">${icon("gear")}</button>
          ${c.key !== "custom" ? `<button class="icon-btn" data-act="regen" title="Regerar a partir do IFC" aria-label="Regerar">${icon("refresh")}</button>` : ""}
          <button class="icon-btn" data-act="del" title="Remover capítulo" aria-label="Remover">${icon("trash")}</button></span></header>
      <textarea data-text ${API.demo ? "readonly" : ""} rows="${Math.min(22, Math.max(4, Math.ceil((c.text || "").length / 95) + (c.text || "").split("\n").length))}" placeholder="Sem texto. Redija aqui ou insira uma sugestão da biblioteca abaixo." aria-label="Texto do capítulo ${esc(c.title)}">${esc(c.text)}</textarea>
      <div class="actions"><button class="btn sm" data-act="save" disabled>${icon("check")}Salvar texto</button>
        <button class="btn sm ${approved ? "" : "primary"}" data-act="approve">${icon(approved ? "restore" : "check")}${approved ? "Reabrir para revisão" : "Aprovar capítulo"}</button>
        <button class="btn sm" data-act="hist">${icon("restore")}Histórico</button>
        ${m.model_id && (c.element_ids || []).length ? `<a class="btn sm" href="#/modelo3d/${m.model_id}?memorial=${m.id}&cap=${c.id}" title="Destacar no modelo 3D os elementos de onde este capítulo saiu">${icon("layers")}Ver no 3D (${c.element_ids.length})</a>` : ""}</div>
      ${tables}
      ${c.pending && c.pending.length ? `<div class="notice"><span>${icon("alert")}</span><div><b>Pendências (informação não encontrada no IFC):</b><ul class="plain">${c.pending.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div></div>` : ""}
      ${c.facts && c.facts.length ? `<details class="ch-sec"><summary>Dados do IFC usados (${c.facts.length})</summary>
        <table class="docs-table"><thead><tr><th>Informação</th><th>Valor</th><th>Método</th><th>Elementos</th></tr></thead><tbody>
        ${c.facts.map((f) => `<tr><td>${esc(f.descricao)}</td><td>${esc(f.valor)}</td><td class="small">${esc(f.metodo)}<div class="muted">${esc(f.origem)}</div></td><td>${f.elementos || "—"}</td></tr>`).join("")}</tbody></table></details>` : ""}
      ${c.key !== "pendencias" ? `<details class="ch-sec" ${!c.text ? "open" : ""}><summary>Sugestões da biblioteca (${(c.suggestions || []).length}) — só entram se você inserir</summary>
        <div class="sug-q"><input data-sugq value="${esc(c.query || "")}" aria-label="Buscar outras referências"><button class="btn sm" data-act="sugq">${icon("search")}Buscar</button></div>
        ${(c.suggestions || []).map((s) => `<div class="sug"><div class="sug-meta"><b>${esc(s.document_title)}</b> › ${esc(s.section_path)}
            <span class="badge ${s.found_by.length > 1 ? "both" : "one"}">relevância relativa ${s.relative_relevance}</span></div>
          <div class="text small">${esc(s.text)}</div>
          <button class="btn sm" data-act="insert" data-chunk="${s.chunk_id}">${icon("upload")}Inserir no capítulo</button></div>`).join("") || `<p class="muted small">Nenhuma sugestão (biblioteca vazia ou sem trechos parecidos).</p>`}</details>` : ""}
      ${c.inserted_refs && c.inserted_refs.length ? `<details class="ch-sec"><summary>Trechos de referência inseridos (${c.inserted_refs.length}) — origem e texto original</summary>
        ${c.inserted_refs.map((x) => `<div class="sug"><div class="sug-meta"><b>${esc(x.document_title)}</b> › ${esc(x.section_path)} <span class="muted small">${esc(x.original_filename || "")}${x.unit ? " · " + esc(x.unit) : ""}</span></div>
          <div class="text small">${esc(x.original_text)}</div></div>`).join("")}</details>` : ""}
      ${c.generated_text && c.edited ? `<details class="ch-sec"><summary>Comparar: texto gerado do IFC × texto atual</summary>
        <div class="cmp"><div><p class="small"><b>Gerado do IFC (original)</b></p><div class="text small">${esc(c.generated_text)}</div></div>
        <div><p class="small"><b>Atual (adaptado)</b></p><div class="text small">${esc(c.text)}</div></div></div></details>` : ""}
      <div class="hist-box"></div>
    </article>`;
  }

  // ------------------------------------------------------------------ Google Drive
  routes.drive = async (view) => {
    const g = API.cfg && API.cfg.gdrive;
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">Integração</p><h1>Google Drive</h1>
        <p class="sub">Alimentar a biblioteca a partir de uma pasta específica do Drive, escolhida por você — nunca o Drive inteiro.</p></div>
        <button class="btn primary" disabled title="${esc((g && g.reason) || "Requer backend conectado")}">${icon("cloud")}Conectar Google Drive</button></div>
      <div class="notice">${icon("alert")}<div><b>Ainda não disponível.</b> ${esc((g && g.reason) || "Requer um backend conectado e as credenciais OAuth do Google.")}
        O botão acima permanece desativado até a integração existir de verdade.</div></div>
      <section class="card"><h2>Como vai funcionar (Etapa 5)</h2>
        <ol class="steps" style="margin-top:16px">
          <li><div><b>Conectar</b> — login seguro do Google (OAuth 2.0). O sistema nunca vê sua senha; pede só permissão de leitura.</div></li>
          <li><div><b>Selecionar pasta</b> — você escolhe uma pasta; só ela é lida.</div></li>
          <li><div><b>Visualizar documentos</b> — DOCX, PDF e Google Docs com nome, tipo e data de modificação.</div></li>
          <li><div><b>Importar manualmente</b> — um a um ou em lote; Google Docs são exportados como DOCX. A origem (pasta e arquivo) fica registrada.</div></li>
          <li><div><b>Sincronizar manualmente</b> — detecta arquivos novos e modificados, sem duplicar.</div></li>
        </ol></section>
      <section class="card"><h2>O que precisa ser configurado</h2>
        <p class="muted" style="margin-top:8px">Um projeto no Google Cloud com a API do Drive ativada e uma credencial OAuth (ID do cliente e segredo).
        As credenciais ficam somente no backend, em variáveis de ambiente — nunca nesta página nem no GitHub.</p></section>`;
  };


  // ------------------------------------------------------------------ login (nuvem)
  routes.login = async (view) => {
    view.innerHTML = `<div class="login-wrap"><form class="card login-card" id="loginForm">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="14.44 19.52 40.52 27.33" class="cx-logo cx-logo-lg" aria-hidden="true" focusable="false"> <defs><clipPath id="cx-abertura-login"><path d="M15.27,41.9 C19.08,32.1 24.52,28.43 30.23,28.57 C37.44,28.7 44.58,31.83 49,37.54 C44.38,43.26 37.44,46.11 30.37,45.84 C24.11,45.57 18.67,44.21 15.27,41.9Z"/></clipPath></defs> <g class="cx-olho"> <g clip-path="url(#cx-abertura-login)"> <circle class="cx-iris" cx="30.03" cy="38.22" r="8.6"/> <circle class="cx-limbo" cx="30.03" cy="38.22" r="8.15" fill="none" stroke-width="0.9"/> <circle class="cx-pupila" cx="30.03" cy="38.52" r="3.2"/> <path class="cx-brilho" d="M27.03,33.92h2.5v2.1h-2.5z M30.13,33.92h4.7v2.1h-4.7z"/> </g> <path class="cx-inferior" d="M16.09,42.58 C19.08,44.62 24.52,45.84 30.37,45.98 C37.44,46.25 44.24,43.26 48.05,38.9" fill="none" stroke-width="0.55" stroke-linecap="round"/> <path class="cx-palpebra" d="M15.04,41.81 L15.62,40.37 L16.23,39.03 L16.85,37.77 L17.49,36.59 L18.16,35.5 L18.84,34.48 L19.55,33.54 L20.27,32.68 L21.01,31.9 L21.77,31.19 L22.55,30.55 L23.34,29.98 L24.16,29.48 L24.99,29.04 L25.83,28.68 L26.69,28.37 L27.56,28.14 L28.45,27.97 L29.35,27.86 L30.25,27.81 L31.36,27.81 L32.48,27.86 L33.59,27.95 L34.7,28.09 L35.8,28.27 L36.9,28.5 L37.99,28.77 L39.07,29.08 L40.13,29.45 L41.18,29.85 L42.21,30.3 L43.23,30.8 L44.22,31.34 L45.2,31.93 L46.14,32.57 L47.06,33.25 L47.95,33.98 L48.81,34.75 L49.64,35.57 L50.42,36.44 L51.65,39.58 L48.88,37.64 L48.2,36.8 L47.49,36.01 L46.73,35.26 L45.94,34.54 L45.12,33.87 L44.27,33.23 L43.39,32.64 L42.48,32.09 L41.55,31.57 L40.6,31.1 L39.62,30.67 L38.63,30.28 L37.62,29.94 L36.59,29.63 L35.55,29.37 L34.5,29.15 L33.44,28.98 L32.37,28.85 L31.3,28.76 L30.23,28.72 L29.38,28.73 L28.55,28.79 L27.71,28.92 L26.89,29.11 L26.07,29.36 L25.26,29.67 L24.46,30.06 L23.67,30.51 L22.9,31.03 L22.13,31.62 L21.38,32.29 L20.65,33.04 L19.93,33.86 L19.22,34.76 L18.54,35.75 L17.87,36.81 L17.22,37.97 L16.6,39.2 L15.99,40.53 L15.41,41.95Z"/> <path class="cx-cilios" d="M24.18,30.03 Q24.3,26.69 22.74,23.85 Q24.67,26.5 24.93,29.65Z M25.78,29.29 Q26.53,26.23 25.56,23.37 Q26.97,26.09 26.66,29Z M27.43,28.81 Q26.77,24.59 28.63,20.59 Q27.26,24.51 28.43,28.64Z M29.13,28.58 Q29.31,24.82 31.71,21.73 Q29.85,24.81 30.21,28.56Z M31.16,28.6 Q32.1,23.64 35.94,20.12 Q32.66,23.68 32.29,28.68Z M33.34,28.81 Q34.8,24.8 38.56,22.45 Q35.38,24.9 34.5,28.99Z M35.5,29.2 Q38.09,24.37 43.33,22.24 Q38.68,24.51 36.66,29.49Z M37.63,29.78 Q40.4,26.28 44.94,25.39 Q40.97,26.47 38.76,30.16Z M39.7,30.53 Q43.78,26.81 49.45,26.79 Q44.31,27.04 40.78,31.01Z M41.71,31.48 Q45.4,29.21 49.78,30.12 Q45.9,29.49 42.7,32.03Z M43.62,32.6 Q48.41,30.73 53.23,32.84 Q48.85,31.03 44.51,33.21Z M45.42,33.9 Q49.24,33.27 52.44,35.61 Q49.63,33.59 46.19,34.55Z M47.09,35.39 Q51.46,35.52 54.36,38.89 Q51.79,35.85 47.73,36.05Z M48.61,37.04 Q51.63,37.83 53.09,40.64 Q51.89,38.16 49.13,37.7Z"/> </g> </svg><h1>Entrar</h1>
      <p class="muted">BIMOFFICE Knowledge · acesso restrito à equipe do SENAI/RO</p>
      <label>E-mail<input name="email" type="email" autocomplete="username" required></label>
      <label>Senha<input name="password" type="password" autocomplete="current-password" required></label>
      <button class="btn primary" type="submit">${icon("check")}Entrar</button>
      <p class="muted small">Sem acesso? Peça ao administrador do sistema.</p></form></div>`;
    $("#loginForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      f.querySelector("button").disabled = true;
      try {
        const r = await API.post("/api/auth/login", { email: f.email.value, password: f.password.value });
        store.set("bimoffice-token", r.token);
        await connect();
        toast(`Bem-vindo(a), ${r.user.name || r.user.email}.`, "ok");
        render();
      } catch (err) { toast(err.message, "err"); f.querySelector("button").disabled = false; }
    });
  };
  $("#logoutBtn").addEventListener("click", async () => {
    try { await API.post("/api/auth/logout"); } catch { /* sessão já encerrada */ }
    store.set("bimoffice-token", null);
    await connect();
    render();
  });

  async function adminSections(box) {
    if (!(API.cfg && API.cfg.auth_mode === "on" && API.user && API.user.role === "admin")) { box.innerHTML = ""; return; }
    const [users, audit] = await Promise.all([API.get("/api/users"), API.get("/api/audit?limit=40")]);
    box.innerHTML = `<section class="card"><h2>Usuários</h2>
      <div class="table-wrap"><table class="docs-table"><thead><tr><th>E-mail</th><th>Nome</th><th>Papel</th><th>Situação</th><th></th></tr></thead><tbody>
      ${users.map((u) => `<tr><td>${esc(u.email)}</td><td>${esc(u.name)}</td>
        <td><select data-role="${u.id}">${["admin", "editor", "leitor"].map((r) => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select></td>
        <td>${u.active ? "ativo" : "<b>desativado</b>"}</td>
        <td><div class="actions"><button class="btn sm" data-act-u="toggle" data-id="${u.id}" data-active="${u.active}">${u.active ? "Desativar" : "Reativar"}</button>
        <button class="btn sm" data-act-u="pw" data-id="${u.id}">Nova senha</button></div></td></tr>`).join("")}</tbody></table></div>
      <form id="newUser" class="form-grid" style="margin-top:12px">
        <label>E-mail<input name="email" type="email" required></label><label>Nome<input name="name"></label>
        <label>Senha inicial (mín. 8)<input name="password" type="password" required minlength="8"></label>
        <label>Papel<select name="role"><option>leitor</option><option>editor</option><option>admin</option></select></label>
        <div class="actions" style="align-self:end"><button class="btn primary">Criar usuário</button></div></form>
      <p class="muted small" style="margin-top:8px">admin: tudo · editor: importa na biblioteca e cria projetos · leitor: só consulta. Em cada projeto, o dono define a equipe.</p></section>
      <section class="card"><h2>Auditoria (últimas alterações)</h2><div class="table-wrap"><table class="docs-table"><thead><tr><th>Quando (UTC)</th><th>Quem</th><th>Ação</th><th>Resultado</th></tr></thead><tbody>
      ${audit.map((a) => `<tr><td class="small">${esc(a.at)}</td><td>${esc(a.email || "—")}</td><td><code>${esc(a.action)}</code></td><td>${a.status ?? ""}</td></tr>`).join("")}</tbody></table></div></section>`;
    const reload = () => adminSections(box);
    $("#newUser", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await API.post("/api/users", Object.fromEntries(new FormData(e.target))); toast("Usuário criado.", "ok"); reload(); }
      catch (err) { toast(err.message, "err"); }
    });
    const patch = (id, body) => API.req(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
    box.addEventListener("change", async (e) => {
      const sel = e.target.closest("[data-role]");
      if (sel) { try { await patch(sel.dataset.role, { role: sel.value }); toast("Papel alterado.", "ok"); } catch (err) { toast(err.message, "err"); } }
    });
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act-u]");
      if (!b) return;
      try {
        if (b.dataset.actU === "toggle") await patch(b.dataset.id, { active: b.dataset.active !== "1" });
        if (b.dataset.actU === "pw") { const pw = prompt("Nova senha (mínimo 8 caracteres):"); if (!pw) return; await patch(b.dataset.id, { password: pw }); }
        toast("Usuário atualizado (sessões abertas foram encerradas).", "ok"); reload();
      } catch (err) { toast(err.message, "err"); }
    });
  }

  async function teamSection(box, pid) {
    if (!(API.cfg && API.cfg.auth_mode === "on")) { box.hidden = true; return; }
    const ms = await API.get(`/api/projects/${pid}/members`);
    box.hidden = false;
    box.innerHTML = `<h2>Equipe do projeto</h2><p class="muted small">dono: gerencia a equipe e pode excluir · editor: altera · leitor: só consulta</p>
      <ul class="plain">${ms.map((m) => `<li>${esc(m.name || m.email)} <span class="muted small">${esc(m.email)}</span> — <b>${esc(m.role)}</b>
        <button class="btn sm" data-rm="${m.user_id}">${icon("x")}</button></li>`).join("")}</ul>
      <form id="addMember" class="sug-q"><input name="email" type="email" placeholder="e-mail do usuário" required>
        <select name="role"><option>leitor</option><option>editor</option><option>dono</option></select><button class="btn sm">Adicionar</button></form>`;
    $("#addMember", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await API.post(`/api/projects/${pid}/members`, Object.fromEntries(new FormData(e.target))); teamSection(box, pid); }
      catch (err) { toast(err.message, "err"); }
    });
    box.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", async () => {
      try { await API.del(`/api/projects/${pid}/members/${b.dataset.rm}`); teamSection(box, pid); } catch (err) { toast(err.message, "err"); }
    }));
  }
  // ------------------------------------------------------------------ Configurações
  routes.config = async (view) => {
    const theme = store.get("bimoffice-theme", "system");
    view.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">Configurações</p><h1>Conexão e preferências</h1></div></div>
      <section class="card"><h2>Backend (API FastAPI)</h2>
        <p class="muted" style="margin:6px 0 14px">No seu computador: <code>http://127.0.0.1:8000</code>. Num servidor do SENAI: o endereço informado pela TI.</p>
        <form id="apiForm" class="form-grid">
          <label>Endereço do backend<input name="base" value="${esc(API.base)}" placeholder="http://127.0.0.1:8000"></label>
          <label>Senha da API (se o backend exigir)<input name="token" type="password" value="${esc(API.token)}" autocomplete="off" placeholder="em branco = sem senha"></label>
          <div class="actions" style="align-self:end"><button class="btn primary" type="submit">${icon("plug")}Salvar e testar</button>
            <button class="btn" type="button" id="apiReset">Padrão</button></div>
        </form>
        <p class="muted small" style="margin-top:10px">A senha fica guardada apenas neste navegador.</p>
        <div id="apiStatus" style="margin-top:14px"></div></section>
      <section class="card"><h2>Aparência</h2>
        <div class="seg" style="margin-top:12px" id="themeSeg">
          ${THEMES.map((t) => `<button type="button" class="btn sm ${t === theme ? "primary" : ""}" data-t="${t}">${THEME_LABEL[t].replace("Tema: ", "")}</button>`).join("")}</div></section>
      <section class="card"><h2>Pesquisa semântica</h2><div id="semStatus" style="margin-top:12px"></div></section>
      <div id="adminBox" class="grid"></div>
      <section class="card"><h2>Manutenção</h2>
        <div class="actions" style="margin-top:12px"><button class="btn" id="backupBtn" ${API.online === true ? "" : "disabled"}>${icon("restore")}Fazer backup do banco</button>
        <a class="btn" href="${esc(API.base)}/docs" target="_blank" rel="noopener" ${API.base ? "" : "hidden"}>${icon("external")}Documentação técnica da API</a></div></section>`;
    $("#apiForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      store.set("bimoffice-api", e.target.base.value.trim());
      store.set("bimoffice-token", e.target.token.value.trim() || null);
      await connect();
      toast(API.online === true ? "Backend conectado." : "Não foi possível conectar.", API.online === true ? "ok" : "err");
      render();
    });
    $("#apiReset").addEventListener("click", async () => { store.set("bimoffice-api", null); await connect(); render(); });
    $("#themeSeg").addEventListener("click", (e) => { const b = e.target.closest("[data-t]"); if (b) { setTheme(b.dataset.t); render(); } });
    $("#apiStatus").innerHTML = API.online === true
      ? `<dl class="kv"><dt>Situação</dt><dd style="color:var(--ok)">Conectado</dd><dt>Versão</dt><dd>${esc(API.cfg.version)}</dd>
         <dt>Formatos aceitos</dt><dd>${esc(API.cfg.allowed_extensions.join(", "))} · até ${API.cfg.max_upload_mb} MB</dd>
         <dt>Senha exigida</dt><dd>${API.cfg.auth_required ? "Sim" : "Não"}</dd></dl>`
      : `<div class="notice">${icon("alert")}<div>${API.online === "auth" ? "Backend encontrado, mas exige senha." : "Nenhum backend respondendo neste endereço."}</div></div>`;
    adminSections($("#adminBox")).catch((e) => toast(e.message, "err"));
    const sem = $("#semStatus");
    if (API.online !== true) { sem.innerHTML = `<p class="muted">Requer backend conectado.</p>`; return; }
    try {
      const s = await API.get("/api/search/status");
      const c = API.cfg.semantic;
      sem.innerHTML = `<dl class="kv"><dt>Modelo local</dt><dd><code>${esc(s.model)}</code></dd>
        <dt>Pacote instalado</dt><dd>${c.package_installed ? "Sim" : "Não — rode o iniciar.bat com Python 3.11–3.13"}</dd>
        <dt>Modelo baixado</dt><dd>${c.model_downloaded ? "Sim" : "Ainda não (baixa ~1 GB na 1ª indexação)"}</dd>
        <dt>Trechos com vetor</dt><dd>${s.chunks_indexed} de ${s.chunks_total}${s.chunks_pending ? ` · <b>${s.chunks_pending} pendentes</b>` : ""}</dd></dl>
        <div class="actions" style="margin-top:14px"><button class="btn" id="reidx">${icon("refresh")}Gerar vetores pendentes</button>
        <button class="btn" id="reidxAll">${icon("refresh")}Refazer todos</button></div>`;
      const run = async (force, btn) => {
        btn.disabled = true; btn.lastChild.textContent = "Processando…";
        try { const r = await API.post(`/api/search/reindex${force ? "?force=true" : ""}`); toast(`${r.indexed} trecho(s) indexado(s).`, "ok"); }
        catch (err) { toast(err.message, "err"); }
        render();
      };
      $("#reidx").addEventListener("click", (e) => run(false, e.currentTarget));
      $("#reidxAll").addEventListener("click", (e) => { if (confirm("Refazer os vetores de todos os trechos? Pode demorar.")) run(true, e.currentTarget); });
    } catch (e) { sem.innerHTML = `<div class="notice err">${icon("alert")}<div>${esc(e.message)}</div></div>`; }
    $("#backupBtn").addEventListener("click", async () => {
      try { const r = await API.post("/api/library/backup"); toast(`Backup criado: ${r.backup}`, "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  };

  // ------------------------------------------------------------------ Importação
  const modal = $("#importModal");
  let queue = [];
  let running = false;
  function openImport() {
    if (API.demo) { toast(Demo.RO, "err"); return; }
    if (API.online !== true) { toast("Conecte um backend para importar.", "err"); return; }
    queue = []; $("#upList").innerHTML = ""; $("#upSummary").textContent = ""; $("#upStart").disabled = true;
    modal.hidden = false;
  }
  function closeImport() {
    if (running && !confirm("A importação está em andamento. Fechar mesmo assim? (os arquivos já enviados continuam)")) return;
    modal.hidden = true;
    render();
  }
  document.addEventListener("click", (e) => { if (e.target.closest("[data-import]")) openImport(); });
  $$("[data-close]", modal).forEach((b) => b.addEventListener("click", closeImport));
  modal.addEventListener("click", (e) => { if (e.target === modal) closeImport(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeImport(); });

  function addFiles(files) {
    const allowed = (API.cfg && API.cfg.allowed_extensions) || [".docx", ".pdf"];
    for (const f of files) {
      const ext = "." + f.name.split(".").pop().toLowerCase();
      const item = { file: f, state: "wait", msg: "Aguardando" };
      if (!allowed.includes(ext)) { item.state = "err"; item.msg = "Tipo não aceito (somente DOCX e PDF)."; }
      else if (API.cfg && f.size > API.cfg.max_upload_mb * 1048576) { item.state = "err"; item.msg = `Maior que ${API.cfg.max_upload_mb} MB.`; }
      else if (queue.some((q) => q.file.name === f.name && q.file.size === f.size)) { toast(`«${f.name}» já está na lista.`); continue; }
      queue.push(item);
    }
    drawQueue();
  }
  function drawQueue() {
    $("#upList").innerHTML = queue.map((q, i) => `
      <li class="up-item ${q.state === "ok" ? "ok" : q.state === "err" ? "err" : q.state === "busy" ? "busy" : ""}" data-i="${i}">
        ${icon(q.state === "ok" ? "check" : q.state === "err" ? "alert" : "file")}
        <span class="name">${esc(q.file.name)}</span><span class="muted small">${(q.file.size / 1048576).toFixed(2)} MB</span>
        <span class="progress"><i class="${q.indet ? "indet" : ""}" style="width:${q.indet ? "" : Math.round((q.pct || 0) * 100) + "%"}"></i></span>
        <span class="st">${esc(q.msg)}</span></li>`).join("");
    const pending = queue.filter((q) => q.state === "wait").length;
    $("#upStart").disabled = running || !pending;
  }
  const drop = $("#drop");
  $("#fileInput").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  $("#upStart").addEventListener("click", async () => {
    running = true;
    const meta = { unit: $("#mUnit").value.trim(), project: $("#mProject").value.trim(), discipline: $("#mDisc").value.trim(), tags: $("#mTags").value.trim() };
    let ok = 0;
    for (const q of queue.filter((x) => x.state === "wait")) {
      q.state = "busy"; q.msg = "Enviando…"; q.pct = 0; drawQueue();
      try {
        const d = await API.upload(q.file, meta, (phase, pct) => {
          if (phase === "upload") { q.pct = pct; q.msg = `Enviando… ${Math.round(pct * 100)}%`; }
          else { q.indet = true; q.msg = "Processando: lendo seções, criando trechos e vetores…"; }
          drawQueue();
        });
        q.state = "ok"; q.indet = false; q.pct = 1; q.msg = `Importado: ${d.n_sections} seções, ${d.n_chunks} trechos.`; ok++;
      } catch (e) { q.state = "err"; q.indet = false; q.pct = 0; q.msg = e.message; }
      drawQueue();
    }
    running = false;
    drawQueue();
    const fail = queue.filter((x) => x.state === "err").length;
    const total = queue.filter((x) => x.state === "ok").length;
    $("#upSummary").textContent = `${total} importado(s)${fail ? `, ${fail} com erro (veja cada arquivo)` : ""}.`;
    if (ok) toast(`${ok} documento(s) importado(s).`, "ok");
  });

  // ------------------------------------------------------------------ início
  connect().then(render);
})();

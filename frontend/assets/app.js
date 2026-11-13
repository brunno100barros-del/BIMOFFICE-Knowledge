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

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    $("#toasts").appendChild(el);
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
    async req(path, opts = {}) {
      if (!this.base) throw new Error("Nenhum backend configurado.");
      let r;
      try {
        r = await fetch(this.base + path, { ...opts, headers: this.headers(opts.headers) });
      } catch (e) {
        throw new Error("Não foi possível falar com o backend (desligado ou bloqueado).");
      }
      if (!r.ok) {
        let detail = `Erro ${r.status}`;
        try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* corpo não-JSON */ }
        const err = new Error(detail);
        err.status = r.status;
        throw err;
      }
      return r.status === 204 ? null : r.json();
    },
    get(p) { return this.req(p); },
    post(p, body) { return this.req(p, { method: "POST", ...(body ? { body: JSON.stringify(body), headers: { "Content-Type": "application/json" } } : {}) }); },
    del(p) { return this.req(p, { method: "DELETE" }); },
    originalUrl(id, inline) { return `${this.base}/api/library/documents/${id}/original${inline ? "?inline=true" : ""}`; },
    upload(file, meta, onProgress) {
      return new Promise((resolve, reject) => {
        const fd = new FormData();
        fd.append("file", file, file.name);
        Object.entries(meta).forEach(([k, v]) => v && fd.append(k, v));
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${this.base}/api/library/documents`);
        if (this.token) xhr.setRequestHeader("Authorization", `Bearer ${this.token}`);
        xhr.upload.onprogress = (e) => e.lengthComputable && onProgress("upload", e.loaded / e.total);
        xhr.upload.onload = () => onProgress("processing", 1);
        xhr.onload = () => {
          let j = null;
          try { j = JSON.parse(xhr.responseText); } catch { /* vazio */ }
          if (xhr.status >= 200 && xhr.status < 300) resolve(j);
          else reject(new Error((j && j.detail) || `Erro ${xhr.status}`));
        };
        xhr.onerror = () => reject(new Error("Falha de conexão com o backend."));
        xhr.send(fd);
      });
    },
  };

  // abre o original com a senha (se houver) sem expor o token na URL
  async function openOriginal(doc, inline) {
    try {
      if (!API.token) { window.open(API.originalUrl(doc.id || doc.document_id, inline), "_blank", "noopener"); return; }
      const r = await fetch(API.originalUrl(doc.id || doc.document_id, inline), { headers: API.headers() });
      if (!r.ok) throw new Error(`Erro ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      if (inline) window.open(url, "_blank", "noopener");
      else { const a = document.createElement("a"); a.href = url; a.download = doc.original_filename || "documento"; a.click(); }
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
    if (API.base) {
      try {
        API.cfg = await API.get("/api/config");
        API.online = true;
        if (API.cfg.auth_required && !API.token) API.online = "auth";
      } catch { /* offline */ }
    }
    el.classList.toggle("on", API.online === true);
    el.classList.toggle("off", API.online !== true);
    $(".conn-text", el).textContent = API.online === true
      ? `Backend conectado · v${API.cfg.version}`
      : API.online === "auth" ? "Backend exige senha" : "Sem backend · demonstração";
    renderBanner();
  }

  function renderBanner() {
    const b = $("#banner");
    if (API.online === true) { b.innerHTML = ""; return; }
    const pages = location.hostname.endsWith("github.io");
    b.innerHTML = `<div class="notice ${API.online === "auth" ? "err" : ""}">${icon("plug")}<div>
      ${API.online === "auth"
        ? "<b>O backend exige senha.</b> Informe a senha da API em <a href='#/config'>Configurações</a>."
        : `<b>Modo demonstração: nenhum backend conectado.</b> A interface está ativa, mas importar, listar e pesquisar memoriais
           dependem do backend FastAPI (processamento de DOCX/PDF, banco SQLite e modelo E5 local).
           ${pages ? "Para usar de verdade, rode o <code>iniciar.bat</code> no seu computador e informe <code>http://127.0.0.1:8000</code> em" : "Verifique se o backend está ligado ou ajuste o endereço em"}
           <a href="#/config">Configurações</a>. Nenhum dado é simulado.`}
      </div></div>`;
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
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, "") || "dashboard";
    const [path, qs] = h.split("?");
    const [name, arg] = path.split("/");
    return { name, arg, params: new URLSearchParams(qs || "") };
  }
  async function render() {
    const r = parseHash();
    const fn = routes[r.name] || routes.dashboard;
    const navName = r.name === "documento" ? "biblioteca" : r.name;
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
      const box = $("#libList");
      let docs;
      try { docs = await API.get(`/api/library/documents?${qs}`); }
      catch (e) { box.innerHTML = `<div class="notice err">${icon("alert")}<div>${esc(e.message)}</div></div>`; return; }
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

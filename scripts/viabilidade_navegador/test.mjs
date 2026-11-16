const out = { ok: false, steps: {} }; window.__out = out;
const log = (...a) => { document.getElementById('log').textContent += a.join(' ') + '\n'; console.log(...a); };
const t = () => performance.now();
const ref = await (await fetch('/ref.json')).json();
const refIfc = await (await fetch('/ref_ifc.json')).json();

// ---------- 1) SQLite WASM com FTS5 (mesma tabela e tokenizador do backend) ----------
try {
  let t0 = t();
  const { default: sqlite3InitModule } = await import('/node_modules/@sqlite.org/sqlite-wasm/dist/index.mjs');
  const sqlite3 = await sqlite3InitModule();
  const db = new sqlite3.oo1.DB(':memory:');
  db.exec(`CREATE TABLE chunks(id INTEGER PRIMARY KEY, text TEXT, section_path TEXT);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(text, section_path, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2');`);
  for (const c of ref.chunks) {
    db.exec({ sql: 'INSERT INTO chunks VALUES (?,?,?)', bind: [c.id, c.text, c.section || ''] });
    db.exec({ sql: 'INSERT INTO chunks_fts(rowid,text,section_path) VALUES (?,?,?)', bind: [c.id, c.text, c.section || ''] });
  }
  const fts = {};
  for (const q of ref.queries) {
    fts[q] = db.selectValues(`SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 50`, [ref.fts[q]]);
  }
  window.__fts = fts;
  out.steps.sqlite = { ok: true, version: sqlite3.version.libVersion, ms: Math.round(t() - t0) };
  log('SQLite', sqlite3.version.libVersion, 'FTS5 ok');
} catch (e) { out.steps.sqlite = { ok: false, error: String(e) }; log('SQLite ERRO', e); }

// ---------- 2) E5 no navegador (transformers.js + ONNX) ----------
try {
  let t0 = t();
  const tf = await import('/node_modules/@huggingface/transformers/dist/transformers.js');
  tf.env.allowRemoteModels = false; tf.env.allowLocalModels = true; tf.env.backends.onnx.wasm.wasmPaths = '/node_modules/onnxruntime-web/dist/'; tf.env.localModelPath = '/models/';
  const ext = await tf.pipeline('feature-extraction', 'Xenova/multilingual-e5-base', { dtype: (new URLSearchParams(location.search).get('dtype') || 'q8'), device: 'wasm' });
  const loadMs = t() - t0;
  const emb = async (texts) => (await ext(texts, { pooling: 'mean', normalize: true })).tolist();
  const cos = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
  const [qv] = await emb(['query: ' + ref.queries[0]]);
  const [pv] = await emb(['passage: ' + ref.chunks[0].text]);
  const simQ = cos(qv, ref.sample_query_vec), simP = cos(pv, ref.sample_passage_vec);
  t0 = t();
  const P = [];
  for (const c of ref.chunks) P.push((await emb(['passage: ' + c.text]))[0]);
  const idxMs = t() - t0;
  // pesquisa híbrida igual ao backend: top-50 de cada, RRF k=60
  const res = {}; let top1 = 0, top3 = 0, overlap5 = 0, qms = 0;
  for (const q of ref.queries) {
    const t1 = t();
    const [v] = await emb(['query: ' + q]);
    const sem = ref.chunks.map((c, i) => [c.id, cos(v, P[i])]).sort((a, b) => b[1] - a[1]).slice(0, 50);
    const f = {};
    sem.forEach(([id], r) => f[id] = (f[id] || 0) + 1 / (60 + r + 1));
    (window.__fts?.[q] || []).forEach((id, r) => f[id] = (f[id] || 0) + 1 / (60 + r + 1));
    const ranked = Object.entries(f).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([id]) => +id);
    qms += t() - t1;
    const exp = ref.results[q].map(r => r.id);
    res[q] = { browser: ranked, python: exp };
    if (ranked[0] === exp[0]) top1++;
    if (exp.slice(0, 3).every(x => ranked.slice(0, 3).includes(x))) top3++;
    overlap5 += ranked.filter(x => exp.includes(x)).length;
  }
  out.steps.e5 = { ok: true, load_ms: Math.round(loadMs), index_33_ms: Math.round(idxMs), query_ms_avg: Math.round(qms / ref.queries.length),
    cos_vs_python_query: +simQ.toFixed(4), cos_vs_python_passage: +simP.toFixed(4),
    same_top1: `${top1}/${ref.queries.length}`, same_top3_set: `${top3}/${ref.queries.length}`,
    overlap_top5: `${overlap5}/${ref.queries.length * 5}`, res };
  log('E5 ok', JSON.stringify(out.steps.e5).slice(0, 300));
} catch (e) { out.steps.e5 = { ok: false, error: String(e && e.stack || e) }; log('E5 ERRO', e); }

// ---------- 3) IFC no navegador (web-ifc) comparado com o leitor Python ----------
try {
  const W = await import('web-ifc');
  const api = new W.IfcAPI(); api.SetWasmPath('/node_modules/web-ifc/', true);
  await api.Init();
  const AUX = new Set(['IFCOPENINGELEMENT', 'IFCOPENINGSTANDARDCASE', 'IFCVIRTUALELEMENT', 'IFCANNOTATION', 'IFCGRID', 'IFCSPATIALZONE', 'IFCVOIDINGFEATURE', 'IFCSURFACEFEATURE']);
  const val = (x) => (x && typeof x === 'object' && 'value' in x) ? x.value : x;
  const files = {};
  for (const name of Object.keys(refIfc)) {
    const t0 = t();
    const data = new Uint8Array(await (await fetch('/ifc/' + name)).arrayBuffer());
    const m = api.OpenModel(data);
    const schema = api.GetModelSchema(m);
    const types = api.GetAllTypesOfModel(m);
    const els = {};
    for (const ty of types) {
      const tname = api.GetNameFromTypeCode(ty.typeID).toUpperCase();
      const isEl = api.IsIfcElement(ty.typeID) || tname === 'IFCSPACE';
      if (!isEl || AUX.has(tname) || tname.includes('FEATUREELEMENTSUBTRACTION')) continue;
      const ids = api.GetLineIDsWithType(m, ty.typeID);
      for (let i = 0; i < ids.size(); i++) {
        const line = api.GetLine(m, ids.get(i));
        if (!line.GlobalId) continue;
        const own = await api.properties.getPropertySets(m, ids.get(i), true, false);
        let typePs = [];
        for (const ty of (await api.properties.getTypeProperties(m, ids.get(i), true)) || [])
          for (const h of (ty.HasPropertySets || [])) if (h && h.type) typePs.push(h);
        const psets = {};
        for (const p of [...typePs, ...own]) {  // ocorrência sobrescreve o tipo (como o IfcOpenShell)
          if (p.type !== W.IFCPROPERTYSET) continue;
          const o = psets[val(p.Name)] = psets[val(p.Name)] || {};
          for (const hp of (p.HasProperties || [])) if (hp && hp.NominalValue !== undefined) o[val(hp.Name)] = val(hp.NominalValue);
        }
        els[val(line.GlobalId)] = { cls: tname, name: val(line.Name), psets };
      }
    }
    let meshes = 0; api.StreamAllMeshes(m, () => meshes++);
    const exp = refIfc[name].elements;
    const gExp = Object.keys(exp), gGot = Object.keys(els);
    const missing = gExp.filter(g => !els[g]), extra = gGot.filter(g => !exp[g]);
    let psOk = 0, psTotal = 0, psDiff = [];
    for (const g of gExp) {
      if (!els[g]) continue;
      for (const [pn, props] of Object.entries(exp[g].psets || {})) for (const [k, v] of Object.entries(props || {})) {
        psTotal++;
        const got = els[g].psets?.[pn]?.[k];
        const same = (typeof v === 'number' && typeof got === 'number') ? Math.abs(v - got) < 1e-6 * Math.max(1, Math.abs(v)) :
          (typeof v === 'boolean') ? (got === v || got === (v ? 'T' : 'F')) : String(got) === String(v);
        if (same) psOk++; else if (psDiff.length < 4) psDiff.push(`${pn}.${k}: py=${JSON.stringify(v)} js=${JSON.stringify(got)}`);
      }
    }
    const extraCls = {}; for (const g of extra) extraCls[els[g].cls] = (extraCls[els[g].cls]||0)+1;
    files[name] = { schema, extraCls, elements_py: gExp.length, elements_js: gGot.length, missing: missing.length, extra: extra.length,
      class_mismatch: gExp.filter(g => els[g] && els[g].cls !== exp[g].cls.toUpperCase()).length,
      props_equal: `${psOk}/${psTotal}`, props_diff_examples: psDiff, meshes, ms: Math.round(t() - t0) };
    api.CloseModel(m);
    log('IFC', name, JSON.stringify(files[name]));
  }
  out.steps.ifc = { ok: true, version: api.GetVersion?.(), files };
} catch (e) { out.steps.ifc = { ok: false, error: String(e && e.stack || e) }; log('IFC ERRO', e); }
out.ok = true; log('FIM');

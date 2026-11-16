// Visualizador 3D de IFC no navegador (three.js + web-ifc, ver vendor/bim3d/LICENCAS.txt).
// Só MOSTRA o modelo: nada é alterado no arquivo IFC. Cada malha guarda o GlobalId do elemento,
// que liga o 3D aos capítulos do memorial e à ficha técnica.
let depsP = null;
const deps = () => (depsP ||= import(new URL("../vendor/bim3d/bim3d-deps.min.js", import.meta.url)));

export async function createViewer(host, { onPick } = {}) {
  const { THREE, OrbitControls, WebIFC } = await deps();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 5000);
  camera.position.set(30, 25, 30);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(40, 80, 30);
  scene.add(sun);
  const root = new THREE.Group();
  scene.add(root);

  const MAT = {
    hi: new THREE.MeshLambertMaterial({ color: 0xf08a24, side: THREE.DoubleSide }),
    sel: new THREE.MeshLambertMaterial({ color: 0x1f7aff, side: THREE.DoubleSide }),
    ghost: new THREE.MeshLambertMaterial({ color: 0x9aa3b2, transparent: true, opacity: 0.08, depthWrite: false }),
    space: new THREE.MeshLambertMaterial({ color: 0x3fb27f, transparent: true, opacity: 0.25, depthWrite: false }),
  };
  const matCache = new Map();
  const baseMat = (c) => {
    const k = `${c.x.toFixed(3)},${c.y.toFixed(3)},${c.z.toFixed(3)},${c.w.toFixed(3)}`;
    if (!matCache.has(k)) {
      matCache.set(k, new THREE.MeshLambertMaterial({ color: new THREE.Color(c.x, c.y, c.z), side: THREE.DoubleSide,
        transparent: c.w < 0.99, opacity: c.w, depthWrite: c.w >= 0.99 }));
    }
    return matCache.get(k);
  };

  const byGid = new Map(); // GlobalId -> [malhas]
  const spaces = new Set();
  let showSpaces = false, highlighted = null, selected = null;

  const render = () => renderer.render(scene, camera);
  controls.addEventListener("change", render);
  const resize = () => {
    const w = host.clientWidth || 600, h = host.clientHeight || 400;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    render();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(host);

  function paint() {
    for (const [gid, meshes] of byGid) {
      const isSpace = spaces.has(gid);
      for (const m of meshes) {
        m.visible = !isSpace || showSpaces || (highlighted && highlighted.has(gid)) || gid === selected;
        m.material = gid === selected ? MAT.sel
          : highlighted ? (highlighted.has(gid) ? MAT.hi : MAT.ghost)
          : isSpace ? MAT.space : m.userData.base;
      }
    }
    render();
  }

  function box(gids) {
    const b = new THREE.Box3();
    const list = gids ? [...gids] : [...byGid.keys()].filter((g) => !spaces.has(g) || showSpaces);
    for (const g of list) for (const m of byGid.get(g) || []) if (m.visible) b.expandByObject(m);
    return b;
  }

  function fit(gids) {
    const b = box(gids && gids.size !== undefined ? gids : gids ? new Set(gids) : null);
    if (b.isEmpty()) return false;
    const c = b.getCenter(new THREE.Vector3()), r = Math.max(b.getSize(new THREE.Vector3()).length() / 2, 3.5);
    const dir = camera.position.clone().sub(controls.target).normalize();
    if (!isFinite(dir.x) || dir.length() < 0.5) dir.set(1, 0.8, 1).normalize();
    camera.position.copy(c.clone().add(dir.multiplyScalar(r / Math.sin((camera.fov * Math.PI) / 360) * 1.05)));
    camera.near = Math.max(r / 500, 0.01);
    camera.far = r * 200 + 100;
    camera.updateProjectionMatrix();
    controls.target.copy(c);
    controls.update();
    render();
    return true;
  }

  // clique (sem arrastar) seleciona o elemento sob o cursor
  const ray = new THREE.Raycaster();
  let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const targets = [];
    for (const [, ms] of byGid) for (const m of ms) if (m.visible && m.material !== MAT.ghost) targets.push(m);
    const hit = ray.intersectObjects(targets, false)[0] || null;
    if (onPick) onPick(hit ? hit.object.userData.gid : null);
  });

  const api = {
    stats: { meshes: 0, elements: 0, seconds: 0 },
    async load(bytes) {
      const t0 = performance.now();
      const ifc = new WebIFC.IfcAPI();
      ifc.SetWasmPath(new URL("../vendor/bim3d/", import.meta.url).href, true);
      await ifc.Init();
      const model = ifc.OpenModel(bytes, { COORDINATE_TO_ORIGIN: true });
      const onMesh = (fm) => {
        let gid;
        try { gid = ifc.GetLine(model, fm.expressID).GlobalId.value; } catch { return; }
        if (ifc.GetLineType(model, fm.expressID) === WebIFC.IFCSPACE) spaces.add(gid);
        const list = byGid.get(gid) || [];
        for (let i = 0; i < fm.geometries.size(); i++) {
          const pg = fm.geometries.get(i);
          const g = ifc.GetGeometry(model, pg.geometryExpressID);
          const v = ifc.GetVertexArray(g.GetVertexData(), g.GetVertexDataSize());
          const ix = ifc.GetIndexArray(g.GetIndexData(), g.GetIndexDataSize());
          const pos = new Float32Array(v.length / 2), nor = new Float32Array(v.length / 2);
          for (let k = 0, j = 0; k < v.length; k += 6, j += 3) {
            pos[j] = v[k]; pos[j + 1] = v[k + 1]; pos[j + 2] = v[k + 2];
            nor[j] = v[k + 3]; nor[j + 1] = v[k + 4]; nor[j + 2] = v[k + 5];
          }
          const geom = new THREE.BufferGeometry();
          geom.setAttribute("position", new THREE.BufferAttribute(pos, 3));
          geom.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
          geom.setIndex(new THREE.BufferAttribute(ix, 1));
          const mesh = new THREE.Mesh(geom, baseMat(pg.color));
          mesh.matrixAutoUpdate = false;
          mesh.matrix.fromArray(pg.flatTransformation);
          mesh.userData = { gid, base: mesh.material };
          root.add(mesh);
          list.push(mesh);
          g.delete();
          api.stats.meshes++;
        }
        if (list.length) byGid.set(gid, list);
      };
      ifc.StreamAllMeshes(model, onMesh);
      // o web-ifc não desenha ambientes (IfcSpace) por padrão: pedimos à parte (ficam ocultos até ligar "Ambientes")
      const sv = ifc.GetLineIDsWithType(model, WebIFC.IFCSPACE), sids = [];
      for (let i = 0; i < sv.size(); i++) sids.push(sv.get(i));
      if (sids.length) ifc.StreamMeshes(model, sids, onMesh);
      ifc.CloseModel(model);
      root.updateMatrixWorld(true);
      api.stats.elements = byGid.size;
      api.stats.seconds = (performance.now() - t0) / 1000;
      paint();
      fit();
      return api.stats;
    },
    has: (gid) => byGid.has(gid),
    gids: () => [...byGid.keys()],
    highlight(gids, { zoom = true } = {}) {
      highlighted = gids && gids.length ? new Set(gids) : null;
      paint();
      if (zoom) fit(highlighted);
    },
    select(gid, { zoom = false } = {}) {
      selected = gid || null;
      paint();
      if (zoom && gid) fit(new Set([gid]));
    },
    setSpaces(on) { showSpaces = !!on; paint(); },
    fit: (gids) => fit(gids ? new Set(gids) : null),
    view(name) {
      const b = box(null);
      if (b.isEmpty()) return;
      const c = b.getCenter(new THREE.Vector3()), d = b.getSize(new THREE.Vector3()).length();
      const dirs = { iso: [1, 0.8, 1], topo: [0.0001, 1, 0], frente: [0, 0.25, 1], lado: [1, 0.25, 0] };
      const v = dirs[name] || dirs.iso;
      camera.position.copy(c.clone().add(new THREE.Vector3(...v).normalize().multiplyScalar(d)));
      controls.target.copy(c);
      controls.update();
      fit(null);
    },
    snapshot: () => renderer.domElement.toDataURL("image/png"),
    dispose() {
      ro.disconnect();
      controls.dispose();
      root.traverse((o) => o.geometry && o.geometry.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
  resize();
  return api;
}

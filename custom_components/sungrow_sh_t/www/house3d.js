/*
 * The house in 3D: lit, shaded, with soft shadows, and power moving through it.
 * three.js (MIT) ships with the integration in ./vendor; nothing is fetched from the internet.
 */
import * as THREE from "./vendor/three.module.min.js";

const COL = { solar: 0xf2a93b, battery: 0x22b5a6, grid: 0x5b8def, home: 0x9b87f5, ev: 0x3fb37f };

const THEME = {
  light: { wall: 0xf4f5f7, wallSide: 0xe6e9ee, trim: 0xd9dde3, roof: 0x3a3f48, panel: 0x1d2635, ground: 0xe9edf2, glass: 0x9fb2c8, lit: 0xffd48a, car: 0x4f6b88, sky: 0xf2f6ff, groundLight: 0xc9ced6, sun: 2.6, hemi: 1.35, shadow: 0.22 },
  dark: { wall: 0x5a6270, wallSide: 0x4a515d, trim: 0x343a44, roof: 0x22262d, panel: 0x18202e, ground: 0x232932, glass: 0x3b4757, lit: 0xffc970, car: 0x6b8bb0, sky: 0xb8c8e6, groundLight: 0x252a31, sun: 2.0, hemi: 1.25, shadow: 0.4 },
};

function mat(color, rough = 0.8, metal = 0, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal, ...extra });
}

function box(w, h, d, m, x, y, z, cast = true) {
  const g = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  g.position.set(x, y, z);
  g.castShadow = cast;
  g.receiveShadow = true;
  return g;
}

/* a rounded box, for the battery modules and the car body */
function rounded(w, h, d, r, m) {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  const g = new THREE.ExtrudeGeometry(s, { depth: d - 2 * r * 0.6, bevelEnabled: true, bevelThickness: r * 0.6, bevelSize: r * 0.6, bevelSegments: 3, curveSegments: 6 });
  g.translate(0, 0, -(d - 2 * r * 0.6) / 2);
  const mesh = new THREE.Mesh(g, m);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

/* solar cell texture: dark glass with a fine silver grid */
function panelTexture() {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 384;
  const g = c.getContext("2d");
  const grad = g.createLinearGradient(0, 0, 256, 384);
  grad.addColorStop(0, "#202b3d"); grad.addColorStop(1, "#141b27");
  g.fillStyle = grad; g.fillRect(0, 0, 256, 384);
  g.strokeStyle = "rgba(170,190,215,.28)"; g.lineWidth = 2;
  for (let i = 1; i < 6; i++) { g.beginPath(); g.moveTo((256 / 6) * i, 0); g.lineTo((256 / 6) * i, 384); g.stroke(); }
  for (let i = 1; i < 10; i++) { g.beginPath(); g.moveTo(0, (384 / 10) * i); g.lineTo(256, (384 / 10) * i); g.stroke(); }
  g.strokeStyle = "rgba(220,228,240,.6)"; g.lineWidth = 6; g.strokeRect(0, 0, 256, 384);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

/* moving light along a flow: dashes that travel, as a texture on a tube */
function dashTexture() {
  const c = document.createElement("canvas");
  c.width = 128; c.height = 8;
  const g = c.getContext("2d");
  const grad = g.createLinearGradient(0, 0, 128, 0);
  grad.addColorStop(0, "rgba(255,255,255,0)"); grad.addColorStop(0.55, "rgba(255,255,255,.95)"); grad.addColorStop(0.7, "rgba(255,255,255,0)"); grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 128, 8);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping;
  return t;
}


/* ------------------------------------------------------------------ */
/* The car, as one smooth lofted body (a compact hatch), coloured by    */
/* zone: paint, roof, glass, lights, arches; colours are options.       */
/* ------------------------------------------------------------------ */

function smoothstep(a, b, x) { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); }

/* monotone-ish cubic through key points [s, y] */
function profile(points) {
  return (s) => {
    for (let i = 0; i < points.length - 1; i++) {
      const [s0, y0] = points[i], [s1, y1] = points[i + 1];
      if (s <= s1) { const t = smoothstep(s0, s1, s); return y0 + (y1 - y0) * t; }
    }
    return points[points.length - 1][1];
  };
}

export function buildCar({ paint = "#f4f5f7", roof = "#0d0e10", glass = "#38475a" } = {}) {
  const LEN = 3.95, HW = 0.9; // length, half width (metres)
  const top = profile([[0, 0.78], [0.03, 1.05], [0.1, 1.40], [0.16, 1.47], [0.55, 1.47], [0.62, 1.40], [0.72, 1.06], [0.8, 0.98], [0.94, 0.90], [1, 0.62]]);
  const bottom = profile([[0, 0.48], [0.06, 0.34], [0.14, 0.30], [0.86, 0.30], [0.95, 0.34], [1, 0.46]]);
  const belt = profile([[0, 0.9], [0.1, 0.98], [0.6, 1.0], [0.72, 1.0], [1, 0.9]]);
  const wheels = [[-1.28, 0.36], [1.3, 0.36]];
  // the surface at (s along the car, th around it)
  const at = (s, th) => {
    const x = -LEN / 2 + LEN * s;
    const end = Math.pow(Math.max(0, 1 - Math.pow(Math.abs(s - 0.5) / 0.5, 6)), 0.5);
    const yt = top(s), yb = bottom(s), mid = (yt + yb) / 2, hh = (yt - yb) / 2, bl = belt(s);
    const c = Math.cos(th), sn = Math.sin(th), n = 4.6;
    let z = Math.sign(c) * Math.pow(Math.abs(c), 2 / n) * HW;
    let y = mid + Math.sign(sn) * Math.pow(Math.abs(sn), 2 / n) * hh;
    if (y > bl) z *= 1 - 0.2 * Math.pow((y - bl) / Math.max(0.05, yt - bl), 1.3);
    z *= 0.55 + 0.45 * end;
    y = yb + (y - yb) * (0.35 + 0.65 * end);
    return { x, y, z, c, yt, bl };
  };
  // colour zones, worked out per texel (so edges are crisp)
  const C = (h) => new THREE.Color(h);
  const zc = { paint: C(paint), roof: C(roof), glass: C(glass), head: C("#f6f8ff"), tail: C("#d8262f"), arch: C("#22252b"), sill: C("#2b2e34") };
  const zone = (s, th) => {
    const { x, y, z, c, yt, bl } = at(s, th);
    for (const [wx, wy] of wheels) if (Math.hypot(x - wx, y - wy) < 0.47 && Math.abs(z) > 0.55) return zc.arch;
    if (y < 0.4) return zc.sill;
    if (s > 0.955 && y > 0.64 && y < 0.8 && Math.abs(z) > 0.22) return zc.head;
    if (s < 0.04 && y > 0.8 && y < 0.96 && Math.abs(z) > 0.28) return zc.tail;
    const upper = y > bl + 0.025, side = Math.abs(c) > 0.42;
    if (!upper) return zc.paint;
    if (side) return s > 0.07 && s < 0.66 && y < yt - 0.075 ? zc.glass : zc.roof; // side windows, pillars in roof black
    if (s > 0.16 && s < 0.56) return zc.roof;
    if (s >= 0.56 && s < 0.76) return zc.glass; // windscreen
    if (s > 0.025 && s <= 0.16) return zc.glass; // rear window
    return zc.paint;
  };
  const TW = 640, TH = 320, SS = 2;
  const cv = document.createElement("canvas"); cv.width = TW; cv.height = TH;
  const g2 = cv.getContext("2d"), img = g2.createImageData(TW, TH);
  for (let v = 0; v < TH; v++) for (let u = 0; u < TW; u++) {
    let r = 0, gg = 0, b = 0;
    for (let a = 0; a < SS; a++) for (let q = 0; q < SS; q++) {
      const k = zone((u + (a + 0.5) / SS) / TW, ((v + (q + 0.5) / SS) / TH) * Math.PI * 2);
      r += k.r; gg += k.g; b += k.b;
    }
    const o = (v * TW + u) * 4, n2 = SS * SS;
    img.data[o] = 255 * r / n2; img.data[o + 1] = 255 * gg / n2; img.data[o + 2] = 255 * b / n2; img.data[o + 3] = 255;
  }
  g2.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.LinearSRGBColorSpace; // the colours above are already linear
  tex.anisotropy = 8;
  // the mesh
  const nS = 160, nT = 96;
  const pos = [], uvs = [], idx = [];
  for (let i = 0; i <= nS; i++) {
    for (let j = 0; j <= nT; j++) {
      const s = i / nS, t = j / nT, p = at(s, t * Math.PI * 2);
      pos.push(p.x, p.y, p.z); uvs.push(s, t);
    }
  }
  for (let i = 0; i < nS; i++) for (let j = 0; j < nT; j++) {
    const a = i * (nT + 1) + j, b = a + nT + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  tex.flipY = false;
  const body = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ map: tex, roughness: 0.3, metalness: 0.05, clearcoat: 1, clearcoatRoughness: 0.05 }));
  body.castShadow = body.receiveShadow = true;
  const car = new THREE.Group();
  car.add(body);
  const tyreM = new THREE.MeshStandardMaterial({ color: 0x15171b, roughness: 0.9 });
  const rimM = new THREE.MeshStandardMaterial({ color: 0xd9dde3, roughness: 0.2, metalness: 0.95 });
  const prof = [];
  for (let k = 0; k <= 16; k++) { const a = -Math.PI / 2 + (Math.PI * k) / 16; prof.push(new THREE.Vector2(0.26 + 0.08 * Math.cos(a), 0.1 * Math.sin(a))); }
  const tyreG = new THREE.LatheGeometry(prof, 40); tyreG.rotateX(Math.PI / 2);
  for (const [wx] of wheels) {
    for (const zs of [1, -1]) {
      const w = new THREE.Group();
      const tyre = new THREE.Mesh(tyreG, tyreM); tyre.castShadow = true; w.add(tyre);
      const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.05, 32), rimM); disc.rotation.x = Math.PI / 2; disc.position.z = zs * 0.07; w.add(disc);
      for (let k = 0; k < 5; k++) {
        const sp = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.2, 0.03), rimM);
        sp.position.set(Math.cos((k * 2 * Math.PI) / 5) * 0.1, Math.sin((k * 2 * Math.PI) / 5) * 0.1, zs * 0.1);
        sp.rotation.z = (k * 2 * Math.PI) / 5 + Math.PI / 2;
        w.add(sp);
      }
      w.position.set(wx, 0.36, zs * (HW - 0.04));
      car.add(w);
    }
  }
  return car;
}

/* a soft studio environment, so paint and glass reflect something */
export function studioEnvironment(renderer, dark) {
  const env = new THREE.Scene();
  const sky = new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), new THREE.MeshBasicMaterial({ side: THREE.BackSide, vertexColors: true }));
  const cs = [];
  const top = new THREE.Color(dark ? 0x3a4458 : 0xeef3fb), bot = new THREE.Color(dark ? 0x0c0e12 : 0x8a919c);
  const p = sky.geometry.attributes.position;
  for (let i = 0; i < p.count; i++) { const t = (p.getY(i) / 50 + 1) / 2; const c = bot.clone().lerp(top, Math.pow(t, 0.8)); cs.push(c.r, c.g, c.b); }
  sky.geometry.setAttribute("color", new THREE.Float32BufferAttribute(cs, 3));
  env.add(sky);
  for (const [x, y, z, w, h] of [[0, 30, 0, 40, 20], [35, 12, 10, 10, 20], [-30, 15, -15, 14, 10]]) {
    const box = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }));
    box.position.set(x, y, z); box.lookAt(0, 0, 0); env.add(box);
  }
  const pm = new THREE.PMREMGenerator(renderer);
  const tex = pm.fromScene(env, 0.04).texture;
  pm.dispose();
  return tex;
}

/* The car: Kenney's "hatchback-sports" (Car Kit 3.1, CC0, www.kenney.nl), repainted:
   to the card's car colours (white with a black roof unless set). Loaded once, after the house. */
async function loadCar(scene, { x, z, paint, roof }) {
  try {
    const { GLTFLoader } = await import("./vendor/GLTFLoader.js");
    const gltf = await new GLTFLoader().loadAsync(new URL("./models/hatchback-sports.glb", import.meta.url).href);
    const car = gltf.scene;
    // repaint the atlas: the paint swatch takes the new colour, keeping its shading
    let map = null;
    car.traverse((o) => { if (o.isMesh && o.material && o.material.map) map = o.material.map; });
    let darkUV = null;
    if (map && map.image) {
      const img = map.image, cv = document.createElement("canvas");
      cv.width = img.width; cv.height = img.height;
      const g = cv.getContext("2d"); g.drawImage(img, 0, 0);
      const px = g.getImageData(0, 0, cv.width, cv.height), d = px.data;
      const to = new THREE.Color(paint);
      let darkest = 1e9;
      for (let i = 0; i < d.length; i += 4) {
        const r = d[i], gg = d[i + 1], b = d[i + 2];
        const isPaint = gg > r + 25 && gg > b + 10; // the kit's green body paint
        if (isPaint) {
          const k = Math.min(1.08, Math.max(0.78, gg / 175)); // keep the swatch's own shading
          d[i] = Math.min(255, to.r * 255 * k); d[i + 1] = Math.min(255, to.g * 255 * k); d[i + 2] = Math.min(255, to.b * 255 * k);
        }
        const lum = r + gg + b;
        if (lum < darkest) { darkest = lum; darkUV = [((i / 4) % cv.width + 0.5) / cv.width, (Math.floor(i / 4 / cv.width) + 0.5) / cv.height]; }
      }
      g.putImageData(px, 0, 0);
      const tex = new THREE.CanvasTexture(cv);
      tex.colorSpace = THREE.SRGBColorSpace; tex.flipY = map.flipY; tex.magFilter = THREE.NearestFilter;
      car.traverse((o) => { if (o.isMesh) o.material = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.32, metalness: 0.15 }); });
      // the roof: upward faces near the top take the darkest swatch
      car.traverse((o) => {
        if (!o.isMesh || o.name !== "body" || !darkUV) return;
        const geo = o.geometry, pos = geo.attributes.position, nrm = geo.attributes.normal, uv = geo.attributes.uv;
        geo.computeBoundingBox();
        const top = geo.boundingBox.max.y;
        for (let i = 0; i < pos.count; i++) {
          if (pos.getY(i) > top * 0.86 && nrm.getY(i) > 0.75) uv.setXY(i, darkUV[0], darkUV[1]);
        }
        uv.needsUpdate = true;
      });
    }
    car.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    const scale = 4.2 / 2.85; // the model is 2.85 long; a compact hatch is about 4.2 m
    car.scale.setScalar(scale);
    car.position.set(x, 0, z);
    car.rotation.y = Math.PI;
    scene.add(car);
  } catch (err) {
    console.warn("sungrow: car model unavailable", err);
  }
}

export function mountHouse(container, opts = {}) {
  const { dark = false, ev = false } = opts;
  const T = THEME[dark ? "dark" : "light"];
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = dark ? 1.15 : 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);
  Object.assign(renderer.domElement.style, { position: "absolute", inset: "0", width: "100%", height: "100%" });

  const scene = new THREE.Scene();
  scene.environment = studioEnvironment(renderer, dark);
  scene.environmentIntensity = dark ? 0.35 : 0.55;
  const camera = new THREE.PerspectiveCamera(26, 1, 0.5, 400);

  // light: open sky, a warm low sun with soft shadows, and a cool fill
  scene.add(new THREE.HemisphereLight(T.sky, T.groundLight, T.hemi));
  const sun = new THREE.DirectionalLight(0xfff1dc, T.sun);
  sun.position.set(-14, 26, 18);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -22, right: 22, top: 22, bottom: -22, near: 1, far: 80 });
  sun.shadow.radius = 6;
  sun.shadow.bias = -0.0004;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xc8d8ff, dark ? 0.35 : 0.55);
  fill.position.set(20, 10, -6);
  scene.add(fill);

  // ground: a soft round plot that fades into the card
  const groundTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 512;
    const g = c.getContext("2d");
    const col = new THREE.Color(T.ground);
    const rgb = `${Math.round(col.r * 255)},${Math.round(col.g * 255)},${Math.round(col.b * 255)}`;
    const r = g.createRadialGradient(256, 256, 40, 256, 256, 256);
    r.addColorStop(0, `rgba(${rgb},1)`); r.addColorStop(0.62, `rgba(${rgb},.9)`); r.addColorStop(1, `rgba(${rgb},0)`);
    g.fillStyle = r; g.fillRect(0, 0, 512, 512);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const ground = new THREE.Mesh(new THREE.CircleGeometry(30, 64), new THREE.MeshStandardMaterial({ map: groundTex, transparent: true, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);
  const shadowCatcher = new THREE.Mesh(new THREE.CircleGeometry(24, 64), new THREE.ShadowMaterial({ opacity: T.shadow }));
  shadowCatcher.rotation.x = -Math.PI / 2;
  shadowCatcher.position.y = 0.01;
  shadowCatcher.receiveShadow = true;
  scene.add(shadowCatcher);

  const house = new THREE.Group();
  scene.add(house);
  const wallM = mat(T.wall, 0.9), sideM = mat(T.wallSide, 0.9), trimM = mat(T.trim, 0.8), roofM = mat(T.roof, 0.55, 0.1);
  const L = 11, D = 7, H = 3.6, R = 6.0; // length (x), depth (z), wall height, ridge height

  // body: a gable prism, length along x
  const shape = new THREE.Shape([new THREE.Vector2(-D / 2, 0), new THREE.Vector2(D / 2, 0), new THREE.Vector2(D / 2, H), new THREE.Vector2(0, R), new THREE.Vector2(-D / 2, H)]);
  const bodyG = new THREE.ExtrudeGeometry(shape, { depth: L, bevelEnabled: false });
  bodyG.rotateY(Math.PI / 2);
  bodyG.translate(-L / 2, 0, 0);
  const body = new THREE.Mesh(bodyG, [sideM, wallM]);
  body.castShadow = body.receiveShadow = true;
  house.add(body);
  house.add(box(L + 0.1, 0.25, D + 0.1, trimM, 0, 0.12, 0, false)); // plinth

  // roof: two slopes with overhang, and a ridge cap
  const slope = Math.atan2(R - H, D / 2);
  const run = Math.hypot(D / 2 + 0.55, (R - H) * (D / 2 + 0.55) / (D / 2));
  for (const side of [1, -1]) {
    const r = box(L + 0.9, 0.16, run, roofM, 0, 0, 0);
    r.position.set(0, H + (R - H) / 2 + 0.02, side * (D / 4 + 0.27));
    r.rotation.x = side * slope;
    house.add(r);
  }
  house.add(box(L + 0.95, 0.12, 0.3, roofM, 0, R + 0.06, 0));

  // solar panels on the slope facing the camera (+z): 2 rows x 6
  const pTex = panelTexture();
  const pM = new THREE.MeshStandardMaterial({ map: pTex, roughness: 0.22, metalness: 0.35, emissive: new THREE.Color(0x1b2a44), emissiveIntensity: 0 });
  const nrm = new THREE.Vector3(0, Math.cos(slope), Math.sin(slope)); // the front slope's outward normal
  for (let row = 0; row < 2; row++) {
    for (let col = 0; col < 6; col++) {
      const t = 0.27 + row * 0.44; // 0 at the ridge, 1 at the wall top
      const p = box(1.62, 0.06, 1.4, pM, -4.3 + col * 1.72, 0, 0, false);
      p.position.set(-4.3 + col * 1.72, R - (R - H) * t, (D / 2) * t).addScaledVector(nrm, 0.36); // roof top is ~0.25 above the slope line
      p.rotation.x = slope;
      house.add(p);
    }
  }

  // windows, lit by the house's own use; front door
  const glassM = new THREE.MeshStandardMaterial({ color: T.glass, roughness: 0.15, metalness: 0.1, emissive: new THREE.Color(T.lit), emissiveIntensity: 0 });
  const frameM = mat(T.trim, 0.7);
  const windows = [];
  for (const x of [2.2, 4.3]) {
    house.add(box(1.7, 1.75, 0.06, frameM, x, 1.95, D / 2 + 0.02, false));
    const w = box(1.5, 1.55, 0.05, glassM, x, 1.95, D / 2 + 0.05, false);
    windows.push(w); house.add(w);
  }
  house.add(box(0.06, 1.75, 1.6, frameM, L / 2 + 0.02, 1.95, -1.6, false));
  const sideWin = box(0.05, 1.55, 1.4, glassM, L / 2 + 0.05, 1.95, -1.6, false);
  windows.push(sideWin); house.add(sideWin);
  house.add(box(0.08, 2.3, 1.15, mat(dark ? 0x4a5260 : 0x8d98a8, 0.6), L / 2 + 0.04, 1.15, 1.6, false));

  // battery towers along the left of the front wall, with a status light each
  const batM = mat(0xf7f8fa, 0.55), batEdge = mat(0xd5dae2, 0.6);
  const ledM = new THREE.MeshBasicMaterial({ color: COL.battery });
  for (let i = 0; i < 4; i++) {
    const x = -4.9 + i * 0.95;
    for (let k = 0; k < 4; k++) {
      const m = rounded(0.82, 0.48, 0.55, 0.06, k === 3 ? batM : batM);
      m.position.set(x, 0.3 + k * 0.52, D / 2 + 0.42);
      house.add(m);
    }
    const cap = rounded(0.82, 0.14, 0.55, 0.05, batEdge);
    cap.position.set(x, 2.38, D / 2 + 0.42);
    house.add(cap);
    house.add(box(0.36, 0.035, 0.02, ledM, x, 2.2, D / 2 + 0.71, false));
  }

  // two inverters on the wall
  const invM = mat(0xfbfbfc, 0.45), screenM = mat(0x26303d, 0.3), invLed = new THREE.MeshBasicMaterial({ color: COL.ev });
  for (const x of [-0.9, 0.45]) {
    const inv = rounded(1.05, 1.3, 0.3, 0.07, invM);
    inv.position.set(x, 2.05, D / 2 + 0.2);
    house.add(inv);
    house.add(box(0.6, 0.22, 0.02, screenM, x, 2.3, D / 2 + 0.37, false));
    house.add(box(0.12, 0.04, 0.02, invLed, x, 1.75, D / 2 + 0.37, false));
  }

  // meter and grid connection on the right-hand wall
  house.add(box(0.2, 0.9, 0.7, mat(0xe1e5ea, 0.6), L / 2 + 0.1, 1.9, 2.75));
  // the grid connection: a street pillar at the boundary, the line underground to the meter
  const pillarM = mat(dark ? 0x4f6f5a : 0x6f8f7a, 0.55);
  const pillar = rounded(0.7, 1.1, 0.5, 0.08, pillarM);
  pillar.position.set(L / 2 + 2.2, 0.55, 0.6);
  scene.add(pillar);
  scene.add(box(0.04, 0.05, 0.5, mat(0xe9edf2, 0.5), L / 2 + 2.56, 0.95, 0.6, false));
  const wirePts = [new THREE.Vector3(L / 2 + 1.85, 0.06, 0.8), new THREE.Vector3(L / 2 + 1.0, 0.06, 1.8), new THREE.Vector3(L / 2 + 0.35, 0.06, 2.75), new THREE.Vector3(L / 2 + 0.2, 1.45, 2.75)];

  // the car and its charger, on the driveway to the left
  let car = null;
  if (ev && opts.carModel) {
    car = new THREE.Group();
    const paint = new THREE.MeshStandardMaterial({ color: T.car, roughness: 0.3, metalness: 0.55 });
    const glass = new THREE.MeshStandardMaterial({ color: 0x2a3746, roughness: 0.05, metalness: 0.85 });
    const trimDark = mat(0x1b1e23, 0.6);
    const W = 1.82;
    const extrude = (shape, depth, bevel, m) => {
      const g = new THREE.ExtrudeGeometry(shape, { depth: depth - 2 * bevel, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 5, curveSegments: 24 });
      g.translate(0, 0, -(depth - 2 * bevel) / 2);
      const mesh = new THREE.Mesh(g, m);
      mesh.castShadow = mesh.receiveShadow = true;
      return mesh;
    };
    // lower body: short sloped bonnet, wheel arches, high belt line, steep tail
    const b = new THREE.Shape();
    b.moveTo(-1.96, 0.42);
    b.lineTo(-1.70, 0.42); b.absarc(-1.28, 0.40, 0.42, Math.PI, 0, true);
    b.lineTo(0.86, 0.42); b.absarc(1.28, 0.40, 0.42, Math.PI, 0, true);
    b.lineTo(1.94, 0.42);
    b.bezierCurveTo(2.06, 0.46, 2.08, 0.66, 2.02, 0.78);  // front bumper
    b.bezierCurveTo(1.9, 0.9, 1.5, 0.94, 0.95, 1.03);     // bonnet rising to the windscreen
    b.lineTo(-1.82, 1.06);                                  // belt line
    b.bezierCurveTo(-1.98, 1.04, -2.03, 0.96, -2.02, 0.8); // tail
    b.lineTo(-2.0, 0.5);
    b.quadraticCurveTo(-1.99, 0.42, -1.96, 0.42);
    car.add(extrude(b, W, 0.06, paint));
    // glass cabin running most of the length
    const c = new THREE.Shape();
    c.moveTo(0.95, 1.02);
    c.bezierCurveTo(0.7, 1.2, 0.45, 1.42, 0.2, 1.47);       // raked windscreen
    c.lineTo(-1.38, 1.5);                                    // roof line
    c.bezierCurveTo(-1.62, 1.49, -1.8, 1.3, -1.86, 1.06);   // hatch
    c.lineTo(0.95, 1.02);
    car.add(extrude(c, W - 0.14, 0.05, glass));
    // painted roof shell over the glass
    const r = new THREE.Shape();
    r.moveTo(0.22, 1.47); r.lineTo(-1.36, 1.5); r.lineTo(-1.38, 1.57); r.lineTo(0.16, 1.54); r.lineTo(0.22, 1.47);
    car.add(extrude(r, W - 0.1, 0.04, paint));
    // wheels with rims
    const tyre = mat(0x15171b, 0.92), rim = new THREE.MeshStandardMaterial({ color: 0xd3d8de, roughness: 0.22, metalness: 0.9 });
    for (const x of [1.28, -1.28]) {
      for (const z of [W / 2 - 0.13, -W / 2 + 0.13]) {
        const t = new THREE.Mesh(new THREE.CylinderGeometry(0.37, 0.37, 0.27, 40), tyre);
        t.rotation.x = Math.PI / 2; t.position.set(x, 0.37, z); t.castShadow = true; car.add(t);
        const h = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.28, 32), rim);
        h.rotation.x = Math.PI / 2; h.position.set(x, 0.37, z); car.add(h);
      }
    }
    // light bars and a dark sill
    car.add(box(0.04, 0.06, W - 0.55, new THREE.MeshBasicMaterial({ color: 0xf4f7ff }), 2.04, 0.8, 0, false));
    car.add(box(0.04, 0.06, W - 0.35, new THREE.MeshBasicMaterial({ color: 0xff4d4d }), -2.03, 0.92, 0, false));
    car.add(box(2.4, 0.1, W + 0.005, trimDark, 0, 0.47, 0, false));
    car.position.set(-L / 2 - 3.2, 0, 4.6);
    car.rotation.y = Math.PI / 2 + 0.12;
    scene.add(car);
    // wall charger on the house's left gable
    const charger = rounded(0.5, 0.75, 0.22, 0.08, mat(0xf2f4f7, 0.4));
    charger.position.set(-L / 2 - 0.14, 1.6, 2.6);
    charger.rotation.y = -Math.PI / 2;
    scene.add(charger);
    scene.add(box(0.03, 0.1, 0.12, invLed, -L / 2 - 0.26, 1.75, 2.6, false));
  }

  if (ev && opts.carModel === "kenney") loadCar(scene, { x: -L / 2 - 3.2, z: 4.4, paint: opts.carPaint || "#f4f5f7", roof: opts.carRoof || "#15171b" });
  else if (ev) {
    const car = buildCar({ paint: opts.carPaint || "#f4f5f7", roof: opts.carRoof || "#121418" });
    car.position.set(-L / 2 - 3.2, 0, 4.4);
    car.rotation.y = Math.PI / 2 - 0.08; // nose towards the street, side to the camera
    scene.add(car);
  }
  if (ev) {
    // the charging bay: a painted outline on the driveway, and the wall charger
    const lineM = new THREE.MeshBasicMaterial({ color: dark ? 0x5b6574 : 0xc3cad4 });
    const bx = -L / 2 - 3.2, bz = 4.4;
    for (const [w, d, x, z] of [[2.6, 0.06, bx, bz - 2.6], [2.6, 0.06, bx, bz + 2.6], [0.06, 5.2, bx - 1.3, bz]]) {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, 0.01, d), lineM); m.position.set(x, 0.012, z); scene.add(m);
    }
    const charger = rounded(0.5, 0.75, 0.22, 0.08, mat(0xf2f4f7, 0.4));
    charger.position.set(-L / 2 - 0.14, 1.6, 2.6);
    charger.rotation.y = -Math.PI / 2;
    scene.add(charger);
    scene.add(box(0.03, 0.1, 0.12, invLed, -L / 2 - 0.26, 1.75, 2.6, false));
  }

  // flows: a faint fixed tube for each route, and travelling light along it
  const dash = dashTexture();
  const routes = {
    solar: [[1.2, R - 0.6, 1.2], [1.2, H + 0.25, D / 2 + 0.45], [0.45, 2.75, D / 2 + 0.38]],
    battery: [[-3.6, 2.45, D / 2 + 0.75], [-2.2, 2.55, D / 2 + 0.5], [-0.9, 2.45, D / 2 + 0.38]],
    home: [[0.45, 1.35, D / 2 + 0.38], [1.4, 0.55, D / 2 + 0.12], [L / 2 - 0.3, 0.55, D / 2 + 0.12], [L / 2 + 0.12, 0.55, 2.2]],
    grid: wirePts.map((v) => [v.x, v.y, v.z]),
    ev: [[-0.9, 1.4, D / 2 + 0.38], [-L / 2 + 0.2, 0.5, D / 2 + 0.12], [-L / 2 - 0.2, 1.3, 2.6]],
  };
  const flows = {};
  for (const [k, pts] of Object.entries(routes)) {
    if (k === "ev" && !ev) continue;
    const curve = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(...p)));
    const base = new THREE.Mesh(new THREE.TubeGeometry(curve, 64, 0.045, 8), new THREE.MeshBasicMaterial({ color: COL[k], transparent: true, opacity: 0.18, depthWrite: false }));
    const tex = dash.clone(); tex.needsUpdate = true;
    tex.repeat.set(Math.max(2, Math.round(curve.getLength() / 1.6)), 1);
    const glow = new THREE.Mesh(new THREE.TubeGeometry(curve, 96, 0.09, 10), new THREE.MeshBasicMaterial({ color: COL[k], map: tex, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    scene.add(base, glow);
    flows[k] = { tex, glow, speed: 0, dir: 1 };
  }

  // frame the scene to the card's shape
  const focus = new URLSearchParams(location.search).get("sgfocus");  // preview only: look at one object
  const target = focus === "car" ? new THREE.Vector3(-L / 2 - 3.2, 0.8, 4.6) : new THREE.Vector3(ev ? -1.4 : 0.6, 2.0, 2.0);
  function resize() {
    const w = container.clientWidth || 1, h = container.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // keep the whole plot in view whatever the shape: pull back on narrow cards
    const dist = focus === "car" ? 9 : (ev ? 29 : 25) / Math.min(1.0, Math.max(0.5, camera.aspect / 2.2));
    const az = -0.62, el = 0.42;
    camera.position.set(target.x + dist * Math.sin(-az) * Math.cos(el), target.y + dist * Math.sin(el), target.z + dist * Math.cos(az) * Math.cos(el));
    camera.lookAt(target);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(container);
  resize();

  let visible = true;
  const io = new IntersectionObserver((e) => { visible = e[0].isIntersecting; });
  io.observe(container);
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let last = performance.now(), raf = 0, t0 = performance.now();
  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (!visible) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    for (const f of Object.values(flows)) f.tex.offset.x -= f.dir * f.speed * dt;
    if (!reduce) {
      const a = Math.sin((now - t0) / 9000) * 0.012;
      camera.position.applyAxisAngle(new THREE.Vector3(0, 1, 0), a - (camera.userData.a || 0));
      camera.userData.a = a;
      camera.lookAt(target);
    }
    renderer.render(scene, camera);
  }
  raf = requestAnimationFrame(frame);

  return {
    update({ solar, home, grid, battery, ev: evKw }) {
      const set = (k, kw, forward) => {
        const f = flows[k];
        if (!f) return;
        const a = Math.abs(kw || 0);
        f.glow.material.opacity = a < 0.03 ? 0 : Math.min(1, 0.45 + a / 20);
        f.speed = a < 0.03 ? 0 : 0.35 + Math.min(2.2, Math.log2(1 + a) * 0.45);
        f.dir = forward ? 1 : -1;
      };
      set("solar", solar, true);
      set("battery", battery, (battery || 0) >= 0);
      set("home", home, true);
      set("grid", grid, (grid || 0) >= 0);
      set("ev", evKw, true);
      const lit = Math.min(1, Math.max(0, (home || 0) / 3));
      glassM.emissiveIntensity = 0.15 + lit * 1.1;
      pM.emissiveIntensity = Math.min(0.9, Math.max(0, (solar || 0) / 25));
      ledM.color.set((battery || 0) < -0.03 ? COL.solar : COL.battery);
    },
    destroy() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}

/*
 * Sungrow SH-T cards: the live power flow through the house, and the day curve.
 * No dependencies. Served by the integration; uses only this install's own entities.
 */

const PALETTE = {
  solar: "#F2A93B",
  battery: "#22B5A6",
  grid: "#5B8DEF",
  home: "#9B87F5",
  import: "#EF6461",
  export: "#3FB37F",
};

const fmt = (kw, digits = 2) => {
  if (kw === null || kw === undefined || Number.isNaN(kw)) return { num: "—", unit: "" };
  const a = Math.abs(kw);
  if (a < 1) return { num: Math.round(a * 1000).toString(), unit: "W" };
  return { num: a.toFixed(a >= 100 ? 0 : digits), unit: "kW" };
};

const num = (hass, id) => {
  const s = id && hass.states[id];
  if (!s || s.state === "unavailable" || s.state === "unknown") return null;
  const v = parseFloat(s.state);
  return Number.isFinite(v) ? v : null;
};

const sum = (hass, ids) => {
  const vals = (ids || []).map((i) => num(hass, i)).filter((v) => v !== null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
};

/* ------------------------------------------------------------------ */
/* isometric scene                                                     */
/* ------------------------------------------------------------------ */

const S = 26; // scale, px per unit
const C30 = Math.cos(Math.PI / 6);
const OX = 470;
const OY = 150;
const iso = (x, y, z) => [OX + (x - y) * C30 * S, OY + (x + y) * 0.5 * S - z * S];
const pts = (...p) => p.map((q) => iso(...q).map((n) => n.toFixed(1)).join(",")).join(" ");
const path = (...p) => "M" + p.map((q) => iso(...q).map((n) => n.toFixed(1)).join(" ")).join(" L");

function box(x0, y0, z0, x1, y1, z1, cls) {
  // visible faces only: top (z1), right (x1), front-left (y1)
  return `
    <polygon class="${cls}-top" points="${pts([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1])}"/>
    <polygon class="${cls}-r" points="${pts([x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1])}"/>
    <polygon class="${cls}-l" points="${pts([x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1])}"/>`;
}

function scene() {
  // main house: x 0..W, y 0..D, walls to H, gable ridge along x at y M, height R
  let s = "";
  const [gx, gy] = iso(6.2, 6.2, 0);
  s += `<ellipse class="ground" cx="${gx}" cy="${gy}" rx="330" ry="96"/>`;
  // walls
  s += `<polygon class="wall-l" points="${pts([0, D, 0], [W, D, 0], [W, D, H], [0, D, H])}"/>`;
  s += `<polygon class="wall-r" points="${pts([W, 0, 0], [W, D, 0], [W, D, H], [W, M, R], [W, 0, H])}"/>`;
  s += `<polyline class="plinth" points="${pts([0, D, 0.12], [W, D, 0.12], [W, 0, 0.12])}"/>`;
  // front window (lit when the house is using power), side window and door
  s += `<polygon class="window" points="${pts([7.3, D, 1.3], [9.4, D, 1.3], [9.4, D, 3.2], [7.3, D, 3.2])}"/>`;
  s += `<polyline class="frame" points="${pts([8.35, D, 1.3], [8.35, D, 3.2])}"/>`;
  s += `<polygon class="window" points="${pts([W, 1.2, 1.4], [W, 3.0, 1.4], [W, 3.0, 3.1], [W, 1.2, 3.1])}"/>`;
  s += `<polygon class="fdoor" points="${pts([W, 4.4, 0.02], [W, 5.5, 0.02], [W, 5.5, 2.6], [W, 4.4, 2.6])}"/>`;
  // roof: visible slope, its edge, and the gable fascia
  const o = 0.45, g = 0.18, eave = H - 0.3;
  s += `<polygon class="soffit" points="${pts([W, 0, H], [W, M, R], [W, D, H], [W + g, D + o, eave], [W + g, M, R + 0.05], [W + g, -o, eave])}"/>`;
  s += `<polygon class="roof" points="${pts([-g, M, R], [W + g, M, R], [W + g, D + o, eave], [-g, D + o, eave])}"/>`;
  s += `<polygon class="roof-side" points="${pts([-g, D + o, eave], [W + g, D + o, eave], [W + g, D + o, eave - 0.22], [-g, D + o, eave - 0.22])}"/>`;
  s += `<polyline class="fascia" points="${pts([W + g, -o, eave], [W + g, M, R], [W + g, D + o, eave])}"/>`;
  // solar panels: 2 rows x 6 on the visible slope
  const slope = (t) => [M + (D + o - M) * t, R - (R - eave) * t];
  for (let row = 0; row < 2; row++) {
    for (let col = 0; col < 6; col++) {
      const x0 = 0.55 + col * 1.6, x1 = x0 + 1.48;
      const t0 = 0.1 + row * 0.43, t1 = t0 + 0.39;
      const [ya, za] = slope(t0), [yb, zb] = slope(t1);
      s += `<polygon class="panel" points="${pts([x0, ya, za + 0.04], [x1, ya, za + 0.04], [x1, yb, zb + 0.04], [x0, yb, zb + 0.04])}"/>`;
      for (const f of [1 / 3, 2 / 3]) {
        const xm = x0 + (x1 - x0) * f;
        s += `<polyline class="panel-line" points="${pts([xm, ya, za + 0.05], [xm, yb, zb + 0.05])}"/>`;
      }
    }
  }
  // battery towers against the front wall
  for (let i = 0; i < 4; i++) {
    const x = 0.45 + i * 0.95;
    s += box(x, D + 0.1, 0, x + 0.82, D + 0.85, 2.2, "bat");
    for (let k = 1; k < 4; k++) {
      s += `<polyline class="bat-line" points="${pts([x, D + 0.85, (2.2 / 4) * k], [x + 0.82, D + 0.85, (2.2 / 4) * k])}"/>`;
    }
  }
  // two inverters on the wall
  for (const x of [4.45, 5.8]) {
    s += box(x, D, 1.4, x + 1.15, D + 0.32, 3.05, "inv");
    s += `<polygon class="inv-screen" points="${pts([x + 0.2, D + 0.33, 2.45], [x + 0.95, D + 0.33, 2.45], [x + 0.95, D + 0.33, 2.8], [x + 0.2, D + 0.33, 2.8])}"/>`;
    const [lx, ly] = iso(x + 0.57, D + 0.33, 1.85);
    s += `<circle class="inv-led" cx="${lx}" cy="${ly}" r="2.6"/>`;
  }
  // meter on the side wall, and the grid pole
  s += box(W, 5.85, 1.5, W + 0.22, 6.55, 2.5, "meter");
  s += box(15.2, 4.2, 0, 15.45, 4.45, 6.6, "pole");
  s += `<polyline class="pole-arm" points="${pts([15.32, 3.4, 6.2], [15.32, 5.2, 6.2])}"/>`;
  s += `<path class="wire" d="M${iso(15.32, 5.0, 6.15).join(" ")} Q${iso(12.6, 5.9, 3.6).join(" ")} ${iso(W + 0.22, 6.2, 2.5).join(" ")}"/>`;
  return s;
}

const W = 10, D = 7, H = 4, R = 6.4, M = D / 2;

/* The drawing's frame, worked out from every point the scene draws (the soft
   ground shadow excluded), with room left at the sides for the corner numbers. */
const SCENE_VIEWBOX = (() => {
  const nums = [...scene().matchAll(/(?:points|d)="([^"]+)"/g)]
    .flatMap((m) => m[1].match(/-?\d+(?:\.\d+)?/g).map(Number));
  const xs = nums.filter((_, i) => i % 2 === 0), ys = nums.filter((_, i) => i % 2 === 1);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const w = x1 - x0, h = y1 - y0, padX = w * 0.34, padY = h * 0.08;
  return `${(x0 - padX).toFixed(0)} ${(y0 - padY).toFixed(0)} ${(w + 2 * padX).toFixed(0)} ${(h + 2 * padY).toFixed(0)}`;
})();

/* flow routes, in scene units: from -> to for a positive value */
const ROUTES = {
  solar: [[5.6, 5.1, 5.55], [5.6, D + 0.45, 3.72], [5.6, D + 0.32, 3.05]],
  battery: [[2.3, D + 0.85, 2.2], [3.6, D + 0.6, 2.3], [4.45, D + 0.32, 2.25]],
  home: [[6.95, D + 0.32, 1.6], [6.95, D + 0.1, 0.9], [W, D, 0.9], [W, 4.95, 0.9]],
  grid: [[15.32, 5.0, 6.15], [13.6, 5.55, 4.4], [12.0, 5.95, 3.1], [W + 0.22, 6.2, 2.5]],
};

/* ------------------------------------------------------------------ */

const FLOW_STYLE = `
  :host { display: block; min-width: 0; max-width: 100%; }
  ha-card { display: block; border-radius: var(--ha-card-border-radius, 16px); overflow: hidden; position: relative; padding: 0; background: var(--sg-bg); }
  .wrap { position: relative; width: 100%; height: clamp(340px, 44vw, 520px); }
  svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .gl { position: absolute; inset: 0; }
  [hidden] { display: none !important; }
  .has3d svg { display: none; }
  .loading3d svg { visibility: hidden; } /* the drawing is the fallback: never shown while the 3D house loads */
  .c-ev { right: 4%; top: 30%; text-align: right; } .c-ev .l { justify-content: flex-end; }
  .ground { fill: var(--sg-ground); filter: blur(14px); }
  .plinth { stroke: var(--sg-plinth); stroke-width: 2; fill: none; }
  .roof-side { fill: var(--sg-roof-edge); }
  .soffit { fill: var(--sg-soffit); }
  .fascia { fill: none; stroke: var(--sg-roof-edge); stroke-width: 4; stroke-linejoin: round; stroke-linecap: round; }
  .garage-top { fill: var(--sg-roof-flat); } .garage-r { fill: var(--sg-wall-r); } .garage-l { fill: var(--sg-wall-l); }
  .wall-l { fill: var(--sg-wall-l); } .wall-r { fill: var(--sg-wall-r); }
  .door { fill: var(--sg-door); } .door-line { stroke: var(--sg-door-line); stroke-width: 1; fill: none; }
  .fdoor { fill: var(--sg-fdoor); }
  .window { fill: var(--sg-window); transition: fill .6s; } .window.lit { fill: var(--sg-window-lit); filter: drop-shadow(0 0 6px var(--sg-window-glow)); }
  .frame { stroke: var(--sg-wall-r); stroke-width: 1.5; }
  .roof { fill: var(--sg-roof); }
  .panel { fill: var(--sg-panel); stroke: var(--sg-panel-edge); stroke-width: 1; }
  .panel.on { fill: var(--sg-panel-on); }
  .panel-line { stroke: var(--sg-panel-edge); stroke-width: .8; }
  .chimney-top { fill: var(--sg-roof-edge); } .chimney-r { fill: var(--sg-wall-r); } .chimney-l { fill: var(--sg-wall-l); }
  .inv-top, .inv-r, .inv-l, .bat-top, .bat-r, .bat-l, .meter-top, .meter-r, .meter-l { stroke: var(--sg-edge); stroke-width: .8; stroke-linejoin: round; }
  .inv-top { fill: #fbfcfd; } .inv-r { fill: #cdd4de; } .inv-l { fill: #eef1f5; }
  .inv-led { fill: ${PALETTE.export}; filter: drop-shadow(0 0 3px ${PALETTE.export}); }
  .inv-screen { fill: #2a3240; }
  .bat-top { fill: #fbfcfd; } .bat-r { fill: #cfd5de; } .bat-l { fill: #eceff3; }
  .bat-line { stroke: #c3cad4; stroke-width: 1; }
  .meter-top { fill: #e9edf2; } .meter-r { fill: #bfc7d2; } .meter-l { fill: #dfe4ea; }
  .pole-top { fill: #8a94a6; } .pole-r { fill: #6b7487; } .pole-l { fill: #8a94a6; }
  .pole-arm { stroke: #6b7487; stroke-width: 3; stroke-linecap: round; fill: none; }
  .wire { stroke: var(--sg-wire); stroke-width: 1.2; fill: none; }
  .flow-base { fill: none; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; opacity: .18; }
  .flow { fill: none; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 2 14; animation: run var(--sg-dur, 2s) linear infinite; animation-direction: var(--sg-dir, normal); filter: drop-shadow(0 0 3px var(--sg-glow)); transition: opacity .4s, stroke-width .4s; }
  .flow.idle { opacity: 0; }
  @keyframes run { to { stroke-dashoffset: -32; } }
  .callout { position: absolute; display: grid; gap: 2px; font-family: var(--paper-font-body1_-_font-family, "Inter", system-ui, sans-serif); color: var(--sg-text); }
  .callout .v { font-size: clamp(22px, 3.6vw, 38px); font-weight: 300; letter-spacing: -.02em; line-height: 1; font-variant-numeric: tabular-nums; }
  .callout .u { font-size: .42em; font-weight: 500; margin-left: 3px; letter-spacing: 0; color: var(--sg-muted); }
  .callout .l { font-size: 13px; font-weight: 500; color: var(--sg-muted); letter-spacing: .02em; display: flex; align-items: center; gap: 6px; }
  .callout .l i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .callout .s { font-size: 12px; color: var(--sg-muted); }
  .c-solar { left: 4%; top: 6%; } .c-home { right: 4%; top: 6%; text-align: right; } .c-home .l { justify-content: flex-end; }
  .c-bat { left: 4%; bottom: 7%; } .c-grid { right: 4%; bottom: 7%; text-align: right; } .c-grid .l { justify-content: flex-end; }
  .soc { display: inline-flex; align-items: center; gap: 6px; margin-left: 10px; font-size: .5em; font-weight: 500; vertical-align: middle; color: var(--sg-text); }
  .soc b { display: inline-block; width: 30px; height: 13px; border: 1.5px solid var(--sg-muted); border-radius: 3px; position: relative; padding: 1px; }
  .soc b::after { content: ""; position: absolute; right: -4px; top: 3px; width: 2px; height: 5px; background: var(--sg-muted); border-radius: 0 1px 1px 0; }
  .soc b span { display: block; height: 100%; background: ${PALETTE.battery}; border-radius: 1px; }
  .chip { position: absolute; left: 50%; top: 4.5%; transform: translateX(-50%); font: 500 12px/1 var(--paper-font-body1_-_font-family, system-ui); color: var(--sg-muted); background: var(--sg-chip); padding: 7px 12px; border-radius: 999px; display: flex; gap: 8px; align-items: center; white-space: nowrap; }
  .chip i { width: 7px; height: 7px; border-radius: 50%; background: ${PALETTE.export}; }
  .chip.stale i { background: ${PALETTE.import}; }
  .towers { display: flex; gap: 5px; margin-top: 7px; }
  .tower { width: 26px; height: 6px; border-radius: 3px; background: var(--sg-track); position: relative; overflow: hidden; }
  .tower span { position: absolute; left: 0; top: 0; bottom: 0; background: ${PALETTE.battery}; border-radius: 3px; transition: width .6s; }
  @media (max-width: 560px) { .chip { top: auto; bottom: 1%; } }
`;

const THEMES = {
  light: {
    "--sg-bg": "linear-gradient(180deg, #e6ecf3 0%, #f3f6f9 55%, #eef1f5 100%)", "--sg-edge": "rgba(40,55,80,.22)",
    "--sg-ground": "rgba(30,40,60,.10)", "--sg-plinth": "#cdd4dd", "--sg-soffit": "#c5cdd8", "--sg-wall-l": "#fdfdfe", "--sg-wall-r": "#dbe2ea", "--sg-roof-flat": "#e6eaef",
    "--sg-roof": "#3a404c", "--sg-roof-edge": "#2a2f38", "--sg-panel": "#222a37", "--sg-panel-on": "#26324a", "--sg-panel-edge": "#3d4a61",
    "--sg-door": "#e7ebf0", "--sg-door-line": "#cfd6df", "--sg-fdoor": "#c9d1db", "--sg-window": "#c9d3df", "--sg-window-lit": "#ffe7b3",
    "--sg-window-glow": "rgba(255,200,100,.55)", "--sg-wire": "#9aa3b2", "--sg-text": "#1d2430", "--sg-muted": "#6a7385",
    "--sg-chip": "rgba(255,255,255,.75)", "--sg-track": "rgba(30,40,60,.10)", "--sg-glow": "rgba(255,255,255,.6)",
  },
  dark: {
    "--sg-bg": "linear-gradient(180deg, #151a22 0%, #1a2029 60%, #161b22 100%)", "--sg-edge": "rgba(0,0,0,.25)",
    "--sg-ground": "rgba(0,0,0,.45)", "--sg-plinth": "#1a1f26", "--sg-soffit": "#1b2028", "--sg-wall-l": "#2b323d", "--sg-wall-r": "#222831", "--sg-roof-flat": "#262c35",
    "--sg-roof": "#0f1217", "--sg-roof-edge": "#0a0c10", "--sg-panel": "#1a2232", "--sg-panel-on": "#1f2c45", "--sg-panel-edge": "#34425c",
    "--sg-door": "#262c35", "--sg-door-line": "#1d222a", "--sg-fdoor": "#1d222a", "--sg-window": "#3a4352", "--sg-window-lit": "#ffd98a",
    "--sg-window-glow": "rgba(255,190,90,.65)", "--sg-wire": "#5d6678", "--sg-text": "#eef1f6", "--sg-muted": "#9aa3b4",
    "--sg-chip": "rgba(255,255,255,.06)", "--sg-track": "rgba(255,255,255,.10)", "--sg-glow": "rgba(0,0,0,0)",
  },
};

const DEFAULTS = {
  pv: ["sensor.sungrow_inverter_1_pv_power", "sensor.sungrow_inverter_2_pv_power"],
  home: "sensor.sungrow_logger_load_power",
  grid: "sensor.sungrow_logger_grid_power",
  battery: "sensor.sungrow_logger_battery_power",
  soc: "sensor.sungrow_logger_battery_level",
  towers: ["sensor.sungrow_battery_tower_1_battery_level", "sensor.sungrow_battery_tower_2_battery_level", "sensor.sungrow_battery_tower_3_battery_level", "sensor.sungrow_battery_tower_4_battery_level"],
  mode: "select.sungrow_logger_ems_mode",
};

class SungrowFlowCard extends HTMLElement {
  setConfig(config) {
    this._cfg = { ...DEFAULTS, ...(config || {}) };
    this._built = false;
  }

  static getStubConfig() { return {}; }
  getCardSize() { return 9; }
  getGridOptions() { return { columns: "full" }; }

  _build() {
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    const flows = Object.entries(ROUTES).map(([k, r]) => {
      const d = path(...r);
      return `<path class="flow-base" d="${d}" stroke="${PALETTE[k]}"/><path class="flow idle" id="f-${k}" d="${d}" stroke="${PALETTE[k]}"/>`;
    }).join("");
    root.innerHTML = `
      <style>${FLOW_STYLE}</style>
      <ha-card>
        <div class="wrap">
          <div class="gl" id="gl"></div>
          <svg id="svg" viewBox="0 0 1000 560" preserveAspectRatio="xMidYMid meet" aria-label="Power flow through the house">
            <g id="scene">${scene()}${flows}</g>
          </svg>
          <div class="chip" id="chip"><i></i><span id="mode">—</span></div>
          <div class="callout c-solar"><div class="v" id="v-solar">—</div><div class="l"><i style="background:${PALETTE.solar}"></i>Solar</div><div class="s" id="s-solar"></div></div>
          <div class="callout c-home"><div class="v" id="v-home">—</div><div class="l"><i style="background:${PALETTE.home}"></i>Home</div></div>
          <div class="callout c-bat"><div class="v"><span id="v-bat">—</span><span class="soc"><b><span id="soc-bar"></span></b><span id="soc">—</span></span></div><div class="l"><i style="background:${PALETTE.battery}"></i><span id="l-bat">Battery</span></div><div class="towers" id="towers"></div></div>
          <div class="callout c-ev" id="c-ev" hidden><div class="v" id="v-ev">—</div><div class="l"><i style="background:${PALETTE.export}"></i><span id="l-ev">Car</span></div></div>
          <div class="callout c-grid"><div class="v" id="v-grid">—</div><div class="l"><i id="grid-dot" style="background:${PALETTE.grid}"></i><span id="l-grid">Grid</span></div></div>
        </div>
      </ha-card>`;
    this._el = (id) => root.getElementById(id);
    this._el("svg").setAttribute("viewBox", SCENE_VIEWBOX);
    this._el("towers").innerHTML = (this._cfg.towers || []).map((_, i) => `<div class="tower"><span id="t${i}"></span></div>`).join("");
    this._built = true;
    this._mount3d();
  }

  async _mount3d() {
    if (this._cfg.flat || this._house) return;
    const wrap = this._el("svg").closest(".wrap");
    wrap.classList.add("loading3d");
    try {
      const v = new URL(import.meta.url).search;
      const { mountHouse } = await import(new URL(`./house3d.js${v}`, import.meta.url).href);
      const dark = !!(this._hass && this._hass.themes && this._hass.themes.darkMode);
      this._house = mountHouse(this._el("gl"), { dark, ev: this._cfg.car !== false });
      wrap.classList.add("has3d");
      this._dark = dark;
      if (this._hass) this.hass = this._hass;
    } catch (err) {
      console.warn("sungrow: 3D house unavailable, using the drawing", err);
    } finally {
      wrap.classList.remove("loading3d");
    }
  }

  disconnectedCallback() {
    if (this._house) { this._house.destroy(); this._house = null; this._built = false; }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    const darkNow = !!(hass.themes && hass.themes.darkMode);
    if (this._house && darkNow !== this._dark) {  // theme switched: rebuild the scene in the other light
      this._house.destroy(); this._house = null;
      this._el("svg").closest(".wrap").classList.remove("has3d");
      this._mount3d();
    }
    const c = this._cfg;
    const dark = !!(hass.themes && hass.themes.darkMode);
    const theme = THEMES[dark ? "dark" : "light"];
    for (const [k, v] of Object.entries(theme)) this.style.setProperty(k, v);

    const solar = sum(hass, c.pv);
    const home = num(hass, c.home);
    const grid = num(hass, c.grid); // + import
    const bat = num(hass, c.battery); // + discharge
    const soc = num(hass, c.soc);

    const put = (id, kw) => {
      const f = fmt(kw);
      this._el(id).innerHTML = `${f.num}<span class="u">${f.unit}</span>`;
    };
    put("v-solar", solar);
    put("v-home", home);
    put("v-grid", grid);
    const fb = fmt(bat);
    this._el("v-bat").innerHTML = `${fb.num}<span class="u">${fb.unit}</span>`;
    this._el("soc").textContent = soc === null ? "—" : `${soc.toFixed(0)}%`;
    this._el("soc-bar").style.width = `${Math.max(0, Math.min(100, soc || 0))}%`;
    this._el("l-bat").textContent = bat === null ? "Battery" : bat > 0.02 ? "Battery · discharging" : bat < -0.02 ? "Battery · charging" : "Battery · idle";
    this._el("l-grid").textContent = grid === null ? "Grid" : grid > 0.02 ? "Grid · importing" : grid < -0.02 ? "Grid · exporting" : "Grid · balanced";
    this._el("grid-dot").style.background = grid === null ? PALETTE.grid : grid > 0.02 ? PALETTE.import : grid < -0.02 ? PALETTE.export : PALETTE.grid;
    const parts = (c.pv || []).map((id, i) => {
      const v = num(hass, id);
      return v === null ? null : `Inverter ${i + 1}  ${fmt(v).num} ${fmt(v).unit}`;
    }).filter(Boolean);
    this._el("s-solar").textContent = parts.length > 1 ? parts.join("   ·   ") : "";

    (c.towers || []).forEach((id, i) => {
      const v = num(hass, id);
      const el = this._el(`t${i}`);
      if (el) { el.style.width = `${Math.max(0, Math.min(100, v || 0))}%`; el.parentElement.title = `Tower ${i + 1}: ${v === null ? "—" : v.toFixed(0) + "%"}`; }
    });

    const ms = c.mode && hass.states[c.mode];
    this._el("mode").textContent = ms ? `EMS · ${ms.state}` : "Live";
    const newest = [c.home, c.grid, c.battery].map((id) => hass.states[id]).filter(Boolean)
      .map((s) => Date.parse(s.last_reported || s.last_updated)).reduce((a, b) => Math.max(a, b), 0);
    this._el("chip").classList.toggle("stale", !newest || Date.now() - newest > 60000);

    // flows: direction and speed follow the power
    const flow = (key, kw, forward) => {
      const el = this._el(`f-${key}`);
      if (!el) return;
      const a = Math.abs(kw || 0);
      el.classList.toggle("idle", a < 0.03);
      const dur = Math.max(0.45, 3.2 - Math.log2(1 + a) * 0.65);
      el.style.setProperty("--sg-dur", `${dur.toFixed(2)}s`);
      el.style.setProperty("--sg-dir", forward ? "normal" : "reverse");
      el.style.strokeWidth = (2.2 + Math.min(4, a / 5)).toFixed(1);
    };
    flow("solar", solar, true);
    flow("battery", bat, (bat || 0) >= 0); // discharging: battery -> inverter
    flow("home", home, true);
    flow("grid", grid, (grid || 0) >= 0); // importing: pole -> house

    const evKw = num(hass, c.ev);
    if (c.ev) {
      this._el("c-ev").hidden = false;
      const fe = fmt(evKw);
      this._el("v-ev").innerHTML = `${fe.num}<span class="u">${fe.unit}</span>`;
      const evSoc = num(hass, c.ev_soc);
      this._el("l-ev").textContent = `Car${(evKw || 0) > 0.05 ? " · charging" : ""}${evSoc === null ? "" : ` · ${evSoc.toFixed(0)}%`}`;
    }
    if (this._house) this._house.update({ solar, home, grid, battery: bat, ev: evKw });
    const lit = (home || 0) > 0.05;
    this.shadowRoot.querySelectorAll(".window").forEach((w) => w.classList.toggle("lit", lit));
    this.shadowRoot.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", (solar || 0) > 0.05));
  }
}

/* ------------------------------------------------------------------ */
/* day curve                                                            */
/* ------------------------------------------------------------------ */

const DAY_STYLE = `
  :host { display: block; min-width: 0; max-width: 100%; }
  ha-card { display: block; border-radius: var(--ha-card-border-radius, 16px); padding: 18px 20px 14px; background: var(--sg-card, var(--ha-card-background, var(--card-background-color))); }
  header { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; font-family: var(--paper-font-body1_-_font-family, system-ui); }
  h2 { margin: 0; font-size: 15px; font-weight: 600; color: var(--primary-text-color); letter-spacing: .01em; }
  .totals { display: flex; gap: 22px; flex-wrap: wrap; }
  .t { display: grid; gap: 2px; }
  .t b { font-size: 20px; font-weight: 400; color: var(--primary-text-color); font-variant-numeric: tabular-nums; letter-spacing: -.01em; }
  .t b small { font-size: 11px; font-weight: 500; color: var(--secondary-text-color); margin-left: 2px; }
  .t span { font-size: 11.5px; color: var(--secondary-text-color); display: flex; gap: 6px; align-items: center; }
  .t span i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
  svg { width: 100%; height: 240px; display: block; overflow: visible; }
  .grid line { stroke: var(--divider-color, rgba(127,127,127,.18)); stroke-width: 1; }
  .axis text { font: 11px var(--paper-font-body1_-_font-family, system-ui); fill: var(--secondary-text-color); }
  .zero { stroke: var(--secondary-text-color); stroke-opacity: .35; }
  .cross { stroke: var(--primary-text-color); stroke-opacity: .35; stroke-dasharray: 3 3; }
  .tip { position: absolute; pointer-events: none; background: var(--card-background-color, #fff); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 10px; padding: 8px 10px; font: 12px/1.5 var(--paper-font-body1_-_font-family, system-ui); box-shadow: 0 6px 24px rgba(0,0,0,.12); white-space: nowrap; }
  .tip i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; margin-right: 6px; }
  .wrap { position: relative; }
  .empty { height: 240px; display: grid; place-items: center; color: var(--secondary-text-color); font: 13px var(--paper-font-body1_-_font-family, system-ui); }
`;

const SERIES = [
  { key: "solar", label: "Solar", color: PALETTE.solar },
  { key: "home", label: "Home", color: PALETTE.home },
  { key: "battery", label: "Battery", color: PALETTE.battery },
  { key: "grid", label: "Grid", color: PALETTE.grid },
];

class SungrowDayCard extends HTMLElement {
  setConfig(config) {
    this._cfg = { ...DEFAULTS, hours: 24, ...(config || {}) };
    this._fetched = 0;
  }

  getCardSize() { return 6; }
  getGridOptions() { return { columns: "full" }; }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      const r = this.attachShadow({ mode: "open" });
      r.innerHTML = `<style>${DAY_STYLE}</style><ha-card><header><h2>Last ${this._cfg.hours} hours</h2><div class="totals" id="totals"></div></header><div class="wrap" id="wrap"><div class="empty">Loading history…</div></div></ha-card>`;
    }
    if (Date.now() - this._fetched > 60000) {
      this._fetched = Date.now();
      this._load().catch((e) => { this.shadowRoot.getElementById("wrap").innerHTML = `<div class="empty">History unavailable (${e.message || e})</div>`; });
    }
  }

  async _load() {
    const c = this._cfg;
    const end = new Date();
    const start = new Date(end - c.hours * 3600e3);
    const ids = [...c.pv, c.home, c.battery, c.grid, c.soc];
    const res = await this._hass.callWS({
      type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
      entity_ids: ids, minimal_response: true, no_attributes: true, significant_changes_only: false,
    });
    const step = 5 * 60e3;
    const n = Math.ceil((end - start) / step);
    const bucket = (id) => {
      const rows = (res[id] || []).map((p) => [((p.lu ?? p.last_updated) * (p.lu ? 1000 : 1)) || Date.parse(p.last_updated), parseFloat(p.s ?? p.state)]).filter((p) => Number.isFinite(p[1]));
      const out = new Array(n).fill(null);
      let j = 0, last = null;
      for (let i = 0; i < n; i++) {
        const t = +start + (i + 1) * step;
        let acc = 0, cnt = 0;
        while (j < rows.length && rows[j][0] <= t) { last = rows[j][1]; acc += last; cnt++; j++; }
        out[i] = cnt ? acc / cnt : last;
      }
      return out;
    };
    const pv = c.pv.map(bucket);
    const data = {
      solar: Array.from({ length: n }, (_, i) => pv.every((a) => a[i] === null) ? null : pv.reduce((s, a) => s + (a[i] || 0), 0)),
      home: bucket(c.home), battery: bucket(c.battery), grid: bucket(c.grid), soc: bucket(c.soc),
    };
    this._render(data, start, step, n);
  }

  _render(d, start, step, n) {
    const W = 1000, H = 240, L = 56, R = 40, T = 10, B = 26;
    const all = [...d.solar, ...d.home, ...d.battery, ...d.grid].filter((v) => v !== null);
    if (!all.length) { this.shadowRoot.getElementById("wrap").innerHTML = `<div class="empty">No history yet</div>`; return; }
    let hi = Math.max(1, ...all), lo = Math.min(0, ...all);
    const nice = (v) => { const p = 10 ** Math.floor(Math.log10(Math.abs(v) || 1)); return Math.ceil(v / p) * p; };
    hi = nice(hi); lo = lo < 0 ? -nice(-lo) : 0;
    const x = (i) => L + (i / (n - 1)) * (W - L - R);
    const y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
    const ys = (v) => T + (100 - v) / 100 * (H - T - B);
    const line = (arr, f = y) => {
      let s = "", pen = false;
      arr.forEach((v, i) => { if (v === null) { pen = false; return; } s += `${pen ? "L" : "M"}${x(i).toFixed(1)},${f(v).toFixed(1)}`; pen = true; });
      return s;
    };
    const area = (arr) => {
      const segs = []; let cur = [];
      arr.forEach((v, i) => { if (v === null) { if (cur.length) segs.push(cur); cur = []; } else cur.push([i, v]); });
      if (cur.length) segs.push(cur);
      return segs.map((sg) => `M${x(sg[0][0])},${y(0)} ` + sg.map(([i, v]) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") + ` L${x(sg[sg.length - 1][0])},${y(0)} Z`).join(" ");
    };
    let g = `<g class="grid">`;
    const ticks = 4;
    for (let k = 0; k <= ticks; k++) {
      const v = lo + (hi - lo) * k / ticks;
      g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`;
    }
    g += `</g><g class="axis">`;
    for (let k = 0; k <= ticks; k++) {
      const v = lo + (hi - lo) * k / ticks;
      g += `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)}${k === ticks ? " kW" : ""}</text>`;
    }
    for (let k = 0; k <= 4; k++) g += `<text x="${W - R + 8}" y="${ys(k * 25) + 4}">${k * 25}%</text>`;
    for (let i = 0; i < n; i += Math.round(3 * 3600e3 / step)) {
      const t = new Date(+start + i * step);
      g += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${t.getHours().toString().padStart(2, "0")}:00</text>`;
    }
    g += `</g><line class="zero" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`;
    const defs = SERIES.map((s) => `<linearGradient id="g-${s.key}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".45"/><stop offset="1" stop-color="${s.color}" stop-opacity=".05"/></linearGradient>`).join("");
    const shapes =
      `<path d="${area(d.solar)}" fill="url(#g-solar)"/>` +
      `<path d="${area(d.battery)}" fill="url(#g-battery)"/>` +
      `<path d="${area(d.grid)}" fill="url(#g-grid)"/>` +
      SERIES.map((s) => `<path d="${line(d[s.key])}" fill="none" stroke="${s.color}" stroke-width="${s.key === "home" ? 2.2 : 1.6}" stroke-linejoin="round"/>`).join("") +
      `<path d="${line(d.soc, ys)}" fill="none" stroke="${PALETTE.export}" stroke-width="1.6" stroke-dasharray="5 4"/>`;
    const wrap = this.shadowRoot.getElementById("wrap");
    wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><defs>${defs}</defs>${g}${shapes}<line class="cross" id="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/></svg><div class="tip" id="tip" hidden></div>`;

    // totals (integrate the 5-minute means)
    const kwh = (arr, sign = 1) => arr.reduce((s, v) => s + (v !== null && v * sign > 0 ? v * sign : 0), 0) * step / 3600e3;
    const tot = [
      ["Solar", kwh(d.solar), PALETTE.solar], ["Home", kwh(d.home), PALETTE.home],
      ["Imported", kwh(d.grid), PALETTE.import], ["Exported", kwh(d.grid, -1), PALETTE.export],
      ["Battery out", kwh(d.battery), PALETTE.battery], ["Battery in", kwh(d.battery, -1), PALETTE.battery],
    ];
    this.shadowRoot.getElementById("totals").innerHTML = tot.map(([l, v, c]) => `<div class="t"><b>${v.toFixed(1)}<small>kWh</small></b><span><i style="background:${c}"></i>${l}</span></div>`).join("");

    const svg = wrap.querySelector("svg"), tip = wrap.querySelector("#tip"), cross = wrap.querySelector("#cross");
    svg.addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width * W;
      const i = Math.max(0, Math.min(n - 1, Math.round((px - L) / (W - L - R) * (n - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      const t = new Date(+start + (i + 1) * step);
      const v = (k) => d[k][i] === null ? "—" : `${d[k][i].toFixed(2)} kW`;
      tip.innerHTML = `<b>${t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</b><br>` + SERIES.map((s) => `<i style="background:${s.color}"></i>${s.label} ${v(s.key)}`).join("<br>") + `<br><i style="background:${PALETTE.export}"></i>Battery ${d.soc[i] === null ? "—" : d.soc[i].toFixed(0) + "%"}`;
      tip.hidden = false;
      const left = ev.clientX - r.left;
      tip.style.left = `${left > r.width - 180 ? left - 170 : left + 14}px`;
      tip.style.top = `8px`;
    });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
  }
}

customElements.get("sungrow-flow-card") || customElements.define("sungrow-flow-card", SungrowFlowCard);
customElements.get("sungrow-day-card") || customElements.define("sungrow-day-card", SungrowDayCard);
window.customCards = window.customCards || [];
window.customCards.push(
  { type: "sungrow-flow-card", name: "Sungrow power flow", description: "Live power through the house" },
  { type: "sungrow-day-card", name: "Sungrow day curve", description: "Solar, home, battery and grid over the day" },
);

/* ------------------------------------------------------------------ */
/* shared look for the detail cards                                    */
/* ------------------------------------------------------------------ */

const PANEL_STYLE = `
  :host { display: block; min-width: 0; max-width: 100%; }
  ha-card { display: block; overflow: hidden; border-radius: var(--ha-card-border-radius, 16px); padding: 20px 22px; background: var(--ha-card-background, var(--card-background-color)); color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, "Inter", system-ui, sans-serif); }
  h2 { margin: 0 0 14px; font-size: 13px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--secondary-text-color); display: flex; justify-content: space-between; align-items: center; }
  h2 span { text-transform: none; letter-spacing: 0; font-weight: 500; }
  .big { font-size: 38px; font-weight: 300; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1; }
  .big small { font-size: 13px; font-weight: 500; color: var(--secondary-text-color); margin-left: 3px; letter-spacing: 0; }
  .muted { color: var(--secondary-text-color); font-size: 12px; }
  .row { display: flex; gap: 28px; flex-wrap: wrap; align-items: flex-end; }
  .kv { display: grid; gap: 3px; }
  .kv b { font-size: 20px; font-weight: 400; font-variant-numeric: tabular-nums; }
  .kv b small { font-size: 11px; color: var(--secondary-text-color); font-weight: 500; margin-left: 2px; }
  .kv span { font-size: 12.5px; color: var(--secondary-text-color); }
  .track { background: var(--sg-track, rgba(127,127,127,.15)); border-radius: 999px; overflow: hidden; position: relative; }
  .fill { position: absolute; inset: 0 auto 0 0; border-radius: 999px; transition: width .6s, height .6s; }
  .pill { font-size: 11px; font-weight: 600; padding: 4px 9px; border-radius: 999px; letter-spacing: .02em; }
  .divider { height: 1px; background: var(--divider-color, rgba(127,127,127,.15)); margin: 18px 0; }
`;

const v = (hass, id, digits = 1) => {
  const n = num(hass, id);
  return n === null ? "—" : n.toFixed(digits);
};
const kw = (hass, id) => {
  const f = fmt(num(hass, id));
  return `${f.num}<small>${f.unit}</small>`;
};

class SungrowBase extends HTMLElement {
  setConfig(config) { this._cfg = config || {}; }
  getCardSize() { return 6; }
  getGridOptions() { return { columns: "full" }; }
  set hass(hass) {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${PANEL_STYLE}${this.css || ""}</style><ha-card>${this.render(hass)}</ha-card>`;
  }
}

/* ------------------------------------------------------------------ */
/* battery                                                             */
/* ------------------------------------------------------------------ */

class SungrowBatteryCard extends SungrowBase {
  get css() {
    return `
      .top { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 36px; align-items: center; }
      .kvs { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 16px 24px; }
      @media (max-width: 1100px) { .top { grid-template-columns: auto minmax(0, 1fr); } .top .towers { grid-column: 1 / -1; } }
      .ring { width: 132px; height: 132px; position: relative; }
      .ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
      .ring .c { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; }
      .ring .c > div { display: grid; gap: 6px; justify-items: center; }
      .towers { display: grid; grid-template-columns: repeat(4, 70px); gap: 14px; justify-content: end; }
      .tw { display: grid; gap: 8px; justify-items: center; text-align: center; }
      .stack { width: 40px; height: 84px; border-radius: 10px; background: var(--sg-track, rgba(127,127,127,.12)); position: relative; overflow: hidden; border: 1px solid var(--divider-color, rgba(127,127,127,.18)); }
      .stack .fill { inset: auto 0 0 0; border-radius: 0; background: linear-gradient(180deg, ${PALETTE.battery}cc, ${PALETTE.battery}); }
      .stack .seg { position: absolute; left: 0; right: 0; height: 1px; background: var(--card-background-color, #fff); opacity: .55; }
      .tw b { font-size: 16px; font-weight: 500; font-variant-numeric: tabular-nums; }
      .tw .muted { line-height: 1.5; }
      .tw .name { font-size: 12px; font-weight: 600; }
      @media (max-width: 560px) { .top { grid-template-columns: 1fr; justify-items: center; } }
    `;
  }

  render(hass) {
    const c = { soc: "sensor.sungrow_logger_battery_level", power: "sensor.sungrow_logger_battery_power", capacity: "sensor.sungrow_logger_total_battery_rated_capacity",
      max_charge: "sensor.sungrow_logger_battery_max_allowable_charge_power", max_discharge: "sensor.sungrow_logger_battery_max_allowable_discharge_power",
      day_in: "sensor.sungrow_logger_daily_battery_charge", day_out: "sensor.sungrow_logger_daily_battery_discharge", ...this._cfg };
    const soc = num(hass, c.soc) ?? 0;
    const p = num(hass, c.power);
    const state = p === null ? "—" : p > 0.02 ? "Discharging" : p < -0.02 ? "Charging" : "Idle";
    const col = p > 0.02 ? PALETTE.battery : p < -0.02 ? PALETTE.solar : "var(--secondary-text-color)";
    const r = 64, circ = 2 * Math.PI * r;
    const towers = (c.towers || []).map((t) => {
      const lvl = num(hass, `sensor.sungrow_battery_tower_${t}_battery_level`) ?? 0;
      const segs = [1, 2, 3, 4].map((k) => `<div class="seg" style="bottom:${k * 20}%"></div>`).join("");
      const model = hass.states[`sensor.sungrow_battery_tower_${t}_model`]?.state || "";
      return `<div class="tw">
        <div class="stack"><div class="fill" style="height:${lvl}%"></div>${segs}</div>
        <b>${lvl.toFixed(0)}%</b>
        <div class="name">Tower ${t}</div>
        <div class="muted">${model}</div>
      </div>`;
    }).join("");
    return `
      <h2>Battery <span class="pill" style="background:${col}22;color:${col}">${state}</span></h2>
      <div class="top">
        <div class="ring">
          <svg viewBox="0 0 150 150"><circle cx="75" cy="75" r="${r}" fill="none" stroke="var(--sg-track, rgba(127,127,127,.15))" stroke-width="12"/>
          <circle cx="75" cy="75" r="${r}" fill="none" stroke="${PALETTE.battery}" stroke-width="12" stroke-linecap="round" stroke-dasharray="${(circ * soc / 100).toFixed(1)} ${circ.toFixed(1)}"/></svg>
          <div class="c"><div><div class="big">${soc.toFixed(0)}<small>%</small></div><div class="muted">${v(hass, c.capacity, 1)} kWh rated</div></div></div>
        </div>
        <div class="kvs">
          <div class="kv"><b>${kw(hass, c.power)}</b><span>Power now</span></div>
          <div class="kv"><b>${kw(hass, c.max_charge)}</b><span>Can charge at</span></div>
          <div class="kv"><b>${kw(hass, c.max_discharge)}</b><span>Can discharge at</span></div>
          <div class="kv"><b>${v(hass, c.day_in)}<small>kWh</small></b><span>Charged today</span></div>
          <div class="kv"><b>${v(hass, c.day_out)}<small>kWh</small></b><span>Discharged today</span></div>
        </div>
        <div class="towers">${towers}</div>
      </div>`;
  }
}

/* ------------------------------------------------------------------ */
/* solar                                                               */
/* ------------------------------------------------------------------ */

class SungrowSolarCard extends SungrowBase {
  get css() {
    return `
      .invs { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr)); gap: 26px; }
      .inv h3 { margin: 0 0 12px; font-size: 14px; font-weight: 600; display: flex; justify-content: space-between; align-items: baseline; }
      .inv h3 .big { font-size: 26px; }
      .bar { display: grid; grid-template-columns: 64px 1fr 92px; gap: 10px; align-items: center; margin: 8px 0; font-size: 12.5px; }
      .bar .track { height: 10px; }
      .bar .fill { background: linear-gradient(90deg, ${PALETTE.solar}aa, ${PALETTE.solar}); }
      .bar b { font-weight: 500; font-variant-numeric: tabular-nums; text-align: right; }
      .bar .muted { grid-column: 2 / 4; margin-top: -4px; }
      .strings { display: flex; gap: 6px; margin-top: 12px; }
      .str { flex: 1; display: grid; gap: 4px; text-align: center; font-size: 11px; color: var(--secondary-text-color); }
      .str .track { height: 46px; border-radius: 6px; }
      .str .fill { inset: auto 0 0 0; border-radius: 0; background: ${PALETTE.solar}; opacity: .85; }
      .curt { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    `;
  }

  render(hass) {
    const inv = (n) => {
      const rated = (num(hass, `sensor.sungrow_inverter_${n}_rated_output_power`) || 25) / 3;
      const mppts = [1, 2, 3].map((m) => {
        const pw = num(hass, `sensor.sungrow_inverter_${n}_mppt${m}_power`) ?? 0;
        return `<div class="bar"><span>MPPT ${m}</span><div class="track"><div class="fill" style="width:${Math.min(100, pw / rated * 100)}%"></div></div><b>${kw(hass, `sensor.sungrow_inverter_${n}_mppt${m}_power`)}</b>
          <div class="muted">${v(hass, `sensor.sungrow_inverter_${n}_mppt${m}_voltage`)} V · ${v(hass, `sensor.sungrow_inverter_${n}_mppt${m}_current`)} A</div></div>`;
      }).join("");
      const sp = [1, 2, 3, 4, 5].map((k) => num(hass, `sensor.sungrow_inverter_${n}_string_${k}_power`) ?? 0);
      const smax = Math.max(0.5, ...sp);
      const strings = sp.map((p, i) => `<div class="str"><div class="track"><div class="fill" style="height:${p / smax * 100}%"></div></div>S${i + 1}<br>${fmt(p).num} ${fmt(p).unit}</div>`).join("");
      const lim = hass.states[`select.sungrow_inverter_${n}_pv_power_limitation`]?.state;
      const exp = hass.states[`select.sungrow_inverter_${n}_feed_in_limitation`]?.state;
      const apl = hass.states[`select.sungrow_inverter_${n}_active_power_limitation`]?.state;
      const pill = (on, text) => `<span class="pill" style="background:${on ? PALETTE.import + "22" : "var(--sg-track, rgba(127,127,127,.12))"};color:${on ? PALETTE.import : "var(--secondary-text-color)"}">${text}</span>`;
      return `<div class="inv">
        <h3><span>Inverter ${n} <span class="muted">${hass.states[`sensor.sungrow_inverter_${n}_model`]?.state || ""}</span></span><span class="big">${kw(hass, `sensor.sungrow_inverter_${n}_pv_power`)}</span></h3>
        ${mppts}
        <div class="strings">${strings}</div>
        <div class="curt">${pill(lim === "Limit PV", lim === "Limit PV" ? "Solar stopped" : "Solar allowed")}${pill(exp === "Enabled", exp === "Enabled" ? "Export limited" : "Export unlimited")}${pill(apl === "Enabled" && (num(hass, `number.sungrow_inverter_${n}_active_power_limit_ratio`) ?? 100) < 100, `Output ${v(hass, `number.sungrow_inverter_${n}_active_power_limit_ratio`, 0)}%`)}</div>
        <div class="row" style="margin-top:14px"><div class="kv"><b>${v(hass, `sensor.sungrow_inverter_${n}_daily_pv_generation`)}<small>kWh</small></b><span>Today</span></div><div class="kv"><b>${v(hass, `sensor.sungrow_inverter_${n}_total_pv_generation`, 0)}<small>kWh</small></b><span>Lifetime</span></div></div>
      </div>`;
    };
    const total = sum(hass, ["sensor.sungrow_inverter_1_pv_power", "sensor.sungrow_inverter_2_pv_power"]);
    const t = fmt(total);
    return `<h2>Solar <span class="big" style="font-size:22px">${t.num}<small>${t.unit}</small></span></h2><div class="invs">${inv(1)}${inv(2)}</div>`;
  }
}

/* ------------------------------------------------------------------ */
/* grid                                                                */
/* ------------------------------------------------------------------ */

class SungrowGridCard extends SungrowBase {
  get css() {
    return `
      .phases { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
      .ph { display: grid; gap: 8px; }
      .ph .track { height: 10px; }
      .ph .center { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--secondary-text-color); opacity: .4; }
      .ph .name { font-size: 12px; font-weight: 600; display: flex; justify-content: space-between; }
    `;
  }

  render(hass) {
    const g = num(hass, "sensor.sungrow_grid_meter_grid_power");
    const dir = g === null ? "—" : g > 0.02 ? "Importing" : g < -0.02 ? "Exporting" : "Balanced";
    const col = g > 0.02 ? PALETTE.import : g < -0.02 ? PALETTE.export : "var(--secondary-text-color)";
    const ps = ["a", "b", "c"].map((p) => num(hass, `sensor.sungrow_grid_meter_phase_${p}_power`) ?? 0);
    const scale = Math.max(5, ...ps.map(Math.abs));
    const phases = ["a", "b", "c"].map((p, i) => {
      const x = ps[i], w = Math.abs(x) / scale * 50;
      const c = x > 0 ? PALETTE.import : PALETTE.export;
      return `<div class="ph"><div class="name"><span>Phase ${p.toUpperCase()}</span><span>${kw(hass, `sensor.sungrow_grid_meter_phase_${p}_power`)}</span></div>
        <div class="track"><div class="fill" style="background:${c};width:${w}%;left:${x >= 0 ? 50 : 50 - w}%;right:auto"></div><div class="center"></div></div>
</div>`;
    }).join("");
    return `
      <h2>Grid <span class="pill" style="background:${col}22;color:${col}">${dir}</span></h2>
      <div class="row">
        <div class="kv"><b class="big">${kw(hass, "sensor.sungrow_grid_meter_grid_power")}</b><span>Grid power (+ import / − export)</span></div>
        <div class="kv"><b>${v(hass, "sensor.sungrow_grid_meter_frequency", 2)}<small>Hz</small></b><span>Frequency</span></div>
        <div class="kv"><b>${v(hass, "sensor.sungrow_grid_meter_power_factor", 3)}</b><span>Power factor</span></div>
        <div class="kv"><b>${v(hass, "sensor.sungrow_logger_grid_import_energy", 0)}<small>kWh</small></b><span>Imported, lifetime</span></div>
        <div class="kv"><b>${v(hass, "sensor.sungrow_logger_grid_export_energy", 0)}<small>kWh</small></b><span>Exported, lifetime</span></div>
      </div>
      <div class="divider"></div>
      <div class="phases">${phases}</div>`;
  }
}

customElements.get("sungrow-battery-card") || customElements.define("sungrow-battery-card", SungrowBatteryCard);
customElements.get("sungrow-solar-card") || customElements.define("sungrow-solar-card", SungrowSolarCard);
customElements.get("sungrow-grid-card") || customElements.define("sungrow-grid-card", SungrowGridCard);
window.customCards.push(
  { type: "sungrow-battery-card", name: "Sungrow battery", description: "Whole battery and each tower" },
  { type: "sungrow-solar-card", name: "Sungrow solar", description: "Each inverter's MPPTs, strings and curtailment" },
  { type: "sungrow-grid-card", name: "Sungrow grid", description: "Grid meter, per phase" },
);

/* ------------------------------------------------------------------ */
/* matrix: rows of one quantity, columns of devices or phases           */
/* ------------------------------------------------------------------ */

const MATRIX_STYLE = `
  :host { display: block; min-width: 0; max-width: 100%; }
  ha-card { display: block; background: none; box-shadow: none; border: none; padding: 0; color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, "Inter", system-ui, sans-serif); }
  .groups { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--sg-gap, 20px); align-items: stretch; }
  .group { min-width: 0; background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 16px); padding: 22px 24px 14px; border: 1px solid var(--divider-color, rgba(127,127,127,.12)); }
  .span-1 { grid-column: span 1; } .span-2 { grid-column: span 2; } .span-4 { grid-column: 1 / -1; }
  @media (max-width: 1399px) { .groups { grid-template-columns: repeat(2, minmax(0, 1fr)); } .span-2, .span-4 { grid-column: 1 / -1; } }
  @media (max-width: 759px) { .groups { grid-template-columns: minmax(0, 1fr); } .span-1, .span-2, .span-4 { grid-column: 1 / -1; } .group { padding: 18px 16px 10px; } }
  .group.dim { opacity: .55; }
  h3 { margin: 0 0 6px; font-size: 12.5px; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: var(--secondary-text-color); display: flex; gap: 8px; align-items: center; }
  h3 i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
  .note { font-size: 12px; color: var(--secondary-text-color); margin: 2px 0 8px; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; font-variant-numeric: tabular-nums; }
  th { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); text-align: right; padding: 8px 0 6px 10px; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.2)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  th:first-child { text-align: left; padding-left: 0; }
  td { padding: 9px 0 9px 10px; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.10)); text-align: right; font-size: 15px; vertical-align: middle; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  td:first-child { text-align: left; padding-left: 0; color: var(--secondary-text-color); font-size: 14px; white-space: normal; }
  tr:last-child td { border-bottom: none; }
  th.sep, td.sep { border-left: 1px solid var(--divider-color, rgba(127,127,127,.25)); padding-left: 14px; }
  .u { font-size: 11px; color: var(--secondary-text-color); margin-left: 2px; }
  .na { color: var(--disabled-text-color, rgba(127,127,127,.6)); }
  .sub { font-size: 10px; line-height: 1.2; color: var(--secondary-text-color); font-style: italic; }
  .on { color: ${PALETTE.export}; } .off { color: var(--secondary-text-color); }
  select.tone-on { color: ${PALETTE.export}; background: ${PALETTE.export}1f; font-weight: 600; }
  select.tone-off { color: ${PALETTE.import}; background: ${PALETTE.import}1a; font-weight: 600; }
  .pill { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 12.5px; background: var(--secondary-background-color, rgba(127,127,127,.12)); }
  .pill.tone-on { color: ${PALETTE.export}; background: ${PALETTE.export}1f; font-weight: 600; }
  .pill.tone-off { color: ${PALETTE.import}; background: ${PALETTE.import}1a; font-weight: 600; }
  select option { color: var(--primary-text-color); background: var(--card-background-color); font-weight: 400; }
  .bar { display: block; height: 3px; border-radius: 2px; background: var(--bar, ${PALETTE.solar}); margin: 4px 0 0 auto; opacity: .9; }
  select, input { font: inherit; font-size: 13px; color: var(--primary-text-color); background: var(--secondary-background-color, rgba(127,127,127,.12)); border: 1px solid transparent; border-radius: 8px; padding: 5px 8px; max-width: 100%; }
  select:hover, input:hover { border-color: var(--divider-color, rgba(127,127,127,.3)); }
  select:focus, input:focus { outline: none; border-color: var(--primary-color); }
  td.ctl { overflow: hidden; text-overflow: clip; }
  col.lab { width: 36%; }
  td.ctl select { max-width: 100%; }
  .num { display: inline-flex; align-items: center; justify-content: flex-end; background: var(--secondary-background-color, rgba(127,127,127,.12)); border-radius: 9px; padding: 2px; }
  .num input { width: 48px; text-align: right; background: transparent; padding: 4px 2px; -moz-appearance: textfield; }
  .num input::-webkit-outer-spin-button, .num input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .num .u { margin: 0 4px 0 1px; }
  .num button { width: 20px; height: 24px; border-radius: 7px; border: none; background: transparent; color: var(--secondary-text-color); cursor: pointer; font-size: 15px; line-height: 1; padding: 0; }
  .num button:hover { background: var(--secondary-background-color, rgba(127,127,127,.12)); color: var(--primary-text-color); }
  .busy { opacity: .5; pointer-events: none; }
  .err { color: ${PALETTE.import}; font-size: 11px; display: block; }
`;

/* green = a function is on, red = it is off; a row's own `tones` decides for its options */
const TONES = { Enabled: "on", "Enabled per phase": "on", On: "on", Disabled: "off", Off: "off" };
const tone = (row, state) => (row && row.tones && state in row.tones ? row.tones[state] : TONES[state]) || "";

class SungrowMatrixCard extends HTMLElement {
  setConfig(config) {
    if (!config || !Array.isArray(config.groups)) throw new Error("groups required");
    this._cfg = config;
    this._sig = "";
  }
  getCardSize() { return 8; }
  getGridOptions() { return { columns: "full" }; }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
      this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
      this.shadowRoot.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.target.blur(); });
    }
    // re-render only when one of our entities changed, and never under the user's cursor
    const ids = this._cfg.groups.flatMap((g) => g.rows.flatMap((r) => r.entities || [])).filter(Boolean);
    const sig = ids.map((id) => hass.states[id]?.state).join("|");
    if (sig === this._sig || this.shadowRoot.activeElement) return;
    this._sig = sig;
    this.shadowRoot.innerHTML = `<style>${MATRIX_STYLE}</style><ha-card><div class="groups">${this._cfg.groups.map((g) => this._group(g)).join("")}</div></ha-card>`;
  }

  _group(g) {
    const cols = g.columns || [""];
    const sep = (i) => (g.split_after && i === g.split_after ? ' class="sep"' : "");
    const head = `<tr><th>${g.corner || ""}</th>${cols.map((c, i) => `<th${sep(i)}>${c}</th>`).join("")}</tr>`;
    const rows = g.rows.map((r) => {
      if (r.sum) {  // a total across devices, worked out here from the entities it names
        const vals = r.sum.map((id) => num(this._hass, id));
        const total = vals.some((x) => x === null) ? null : vals.reduce((a, b) => a + b, 0);
        const unit = this._hass.states[r.sum[0]]?.attributes.unit_of_measurement || "";
        return `<tr><td>${r.label}</td><td colspan="${cols.length}">${total === null ? '<span class="na">—</span>' : `<b>${(+total.toFixed(3)).toString()}</b><span class="u">${unit}</span>`}</td></tr>`;
      }
      const max = r.bar ? Math.max(0.001, ...r.entities.map((id) => Math.abs(num(this._hass, id) ?? 0))) : 0;
      const subs = r.subs || [];
      return `<tr><td>${r.label}</td>${r.entities.map((id, i) => `<td${/^(number|select)\./.test(id || "") ? ' class="ctl"' : sep(i)}>${this._cell(id, r, max)}${subs[i] ? `<div class="sub">${subs[i]}</div>` : ""}</td>`).join("")}</tr>`;
    }).join("");
    const dot = `<i style="background:${g.color || "#8a93a3"}"></i>`;
    const n = (g.columns || [""]).length;
    const span = g.wide ? 4 : g.span || (n >= 4 ? 2 : n >= 3 ? 2 : 1);
    return `<div class="group span-${span}${g.dim ? " dim" : ""}" style="--bar:${g.color || PALETTE.solar}"><h3>${dot}${g.title}</h3>${g.note ? `<div class="note">${g.note}</div>` : ""}<table><colgroup><col class="lab" style="width:${cols.length > 1 ? 36 : 58}%">${cols.map(() => "<col>").join("")}</colgroup>${cols.length > 1 || g.corner ? `<thead>${head}</thead>` : ""}<tbody>${rows}</tbody></table></div>`;
  }

  _cell(id, row, max) {
    if (!id) return `<span class="na">—</span>`;
    const s = this._hass.states[id];
    if (!s) return `<span class="na">—</span>`;
    if (s.state === "unavailable" || s.state === "unknown") return `<span class="na">${s.state === "unknown" ? "not reported" : "unavailable"}</span>`;
    const domain = id.split(".")[0];
    if (domain === "select" && row.readonly) {
      const t = tone(row, s.state);
      return `<span class="pill${t ? ` tone-${t}` : ""}">${s.state}</span>`;
    }
    if (domain === "select") {
      const opts = (s.attributes.options || []).map((o) => `<option${o === s.state ? " selected" : ""}>${o}</option>`).join("");
      const t = tone(row, s.state);
      return `<select data-id="${id}"${t ? ` class="tone-${t}"` : ""}>${opts}</select>`;
    }
    if (domain === "number") {
      const a = s.attributes;
      return `<span class="num"><button data-step="-1" data-id="${id}" aria-label="Decrease">−</button><input data-id="${id}" type="number" value="${s.state}" min="${a.min ?? ""}" max="${a.max ?? ""}" step="${a.step ?? "any"}"><span class="u">${a.unit_of_measurement || ""}</span><button data-step="1" data-id="${id}" aria-label="Increase">+</button></span>`;
    }
    if (domain === "binary_sensor") return s.state === "on" ? `<span class="on">● on</span>` : `<span class="off">○ off</span>`;
    const unit = s.attributes.unit_of_measurement || "";
    const n = parseFloat(s.state);
    let text = s.state;
    if (Number.isFinite(n) && this._hass.formatEntityState) {
      text = this._hass.formatEntityState(s).replace(new RegExp(`\\s*${unit.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`), "");
    } else if (Number.isFinite(n)) {
      text = String(+n.toFixed(row.digits ?? 3));
    }
    const bar = max && Number.isFinite(n) ? `<span class="bar" style="width:${Math.min(100, Math.abs(n) / max * 100)}%"></span>` : "";
    return `${text}${unit ? `<span class="u">${unit}</span>` : ""}${bar}`;
  }

  async _set(domain, service, data, el) {
    el.classList.add("busy");
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      el.insertAdjacentHTML("afterend", `<span class="err">${err.message || err}</span>`);
    } finally {
      el.classList.remove("busy");
      this._sig = "";
    }
  }

  _onChange(e) {
    const t = e.target, id = t.dataset.id;
    if (!id) return;
    if (t.tagName === "SELECT") this._set("select", "select_option", { entity_id: id, option: t.value }, t);
    else if (t.tagName === "INPUT") this._set("number", "set_value", { entity_id: id, value: parseFloat(t.value) }, t);
  }

  _onClick(e) {
    const b = e.target.closest("button[data-step]");
    if (!b) return;
    const s = this._hass.states[b.dataset.id];
    const step = parseFloat(s.attributes.step) || 1;
    let v = parseFloat(s.state) + step * parseFloat(b.dataset.step);
    v = Math.min(s.attributes.max ?? v, Math.max(s.attributes.min ?? v, v));
    this._set("number", "set_value", { entity_id: b.dataset.id, value: +v.toFixed(6) }, b.parentElement);
  }
}


/* ------------------------------------------------------------------ */
/* page layout: deliberate rows of 4 tracks; an item is a column stack  */
/* ------------------------------------------------------------------ */

const LAYOUT_STYLE = `
  .rows { display: grid; gap: var(--sg-gap, 20px); }
  .lrow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--sg-gap, 20px); align-items: stretch; }
  .item { display: flex; flex-direction: column; gap: var(--sg-gap, 20px); min-width: 0; }
  .item > .group { flex: 1 1 auto; }
  .subrow { display: grid; grid-template-columns: repeat(var(--n, 2), minmax(0, 1fr)); gap: var(--sg-gap, 20px); flex: 1 1 auto; }
  .subrow > .group { height: 100%; box-sizing: border-box; grid-column: auto !important; }
  .group.dense td:first-child { white-space: nowrap; }
  @media (max-width: 759px) { .subrow { grid-template-columns: minmax(0, 1fr); } }
  .group.dense td { padding-top: 6px; padding-bottom: 6px; font-size: 14px; }
  .group.dense td:first-child { font-size: 13.5px; }
  .item.s1 { grid-column: span 1; } .item.s2 { grid-column: span 2; } .item.s3 { grid-column: span 3; } .item.s4 { grid-column: 1 / -1; }
  @media (max-width: 1399px) { .lrow { grid-template-columns: repeat(2, minmax(0, 1fr)); } .item.s2, .item.s3, .item.s4 { grid-column: 1 / -1; } }
  @media (max-width: 759px) { .lrow { grid-template-columns: minmax(0, 1fr); } .item.s1 { grid-column: 1 / -1; } }
  .kpis { display: flex; flex-wrap: wrap; gap: 14px 40px; align-items: flex-end; }
  .kpi { display: grid; gap: 4px; min-width: 110px; }
  .kpi b { font-size: 30px; font-weight: 300; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1.05; }
  .kpi b small { font-size: 13px; font-weight: 500; color: var(--secondary-text-color); margin-left: 3px; letter-spacing: 0; }
  .kpi span { font-size: 12.5px; color: var(--secondary-text-color); display: flex; gap: 6px; align-items: center; }
  .kpi span i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .kpi.text b { font-size: 18px; font-weight: 500; padding-bottom: 6px; }
`;

SungrowMatrixCard.prototype._kpis = function (g) {
  const items = g.kpis.map((k) => {
    const ids = k.sum || [k.entity];
    const st = this._hass.states[ids[0]];
    if (st && isNaN(parseFloat(st.state))) {  // a mode or status: show it as text
      const t = tone(k, st.state);
      return `<div class="kpi text"><b${t ? ` style="color:${t === "on" ? PALETTE.export : PALETTE.import}"` : ""}>${st.state}</b><span>${k.color ? `<i style="background:${k.color}"></i>` : ""}${k.label}</span></div>`;
    }
    const vals = ids.map((id) => num(this._hass, id));
    const v = vals.some((x) => x === null) ? null : vals.reduce((a, b) => a + b, 0);
    const unit = st?.attributes.unit_of_measurement || "";
    let shown = v === null ? "—" : String(+v.toFixed(k.digits ?? 2)), u = unit;
    if (unit === "kW" && v !== null && Math.abs(v) < 1) { shown = String(Math.round(v * 1000)); u = "W"; }
    return `<div class="kpi"><b>${shown}<small>${u}</small></b><span>${k.color ? `<i style="background:${k.color}"></i>` : ""}${k.label}</span></div>`;
  }).join("");
  return `<div class="group span-4"><h3><i style="background:${g.color || "#8a93a3"}"></i>${g.title}</h3><div class="kpis">${items}</div></div>`;
};

const _origGroup = SungrowMatrixCard.prototype._group;
SungrowMatrixCard.prototype._group = function (g) {
  return g.kpis ? this._kpis(g) : _origGroup.call(this, g);
};

const _origSet = Object.getOwnPropertyDescriptor(SungrowMatrixCard.prototype, "hass").set;
Object.defineProperty(SungrowMatrixCard.prototype, "hass", {
  set(hass) {
    if (!this._cfg.layout) return _origSet.call(this, hass);
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
      this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
      this.shadowRoot.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.target.blur(); });
    }
    const flat = (g) => (g.pair ? g.pair.flatMap(flat) : [g]);
    const all = this._cfg.layout.flatMap((r) => r.flatMap((it) => it.groups.flatMap(flat)));
    const ids = all.flatMap((g) => (g.rows || []).flatMap((r) => [...(r.entities || []), ...(r.sum || [])]).concat((g.kpis || []).flatMap((k) => k.sum || [k.entity]))).filter(Boolean);
    const sig = ids.map((id) => hass.states[id]?.state).join("|");
    if (sig === this._sig || this.shadowRoot.activeElement) return;
    this._sig = sig;
    const one = (g) => g.pair
      ? `<div class="subrow" style="--n:${g.pair.length}">${g.pair.map(one).join("")}</div>`
      : this._group(g).replace(/class="group span-\d/, `class="group span-4${g.dense ? " dense" : ""}`);
    const rows = this._cfg.layout.map((r) => `<div class="lrow">${r.map((it) => `<div class="item s${it.span || 4}">${it.groups.map(one).join("")}</div>`).join("")}</div>`).join("");
    this.shadowRoot.innerHTML = `<style>${MATRIX_STYLE}${LAYOUT_STYLE}</style><ha-card><div class="rows">${rows}</div></ha-card>`;
  },
  configurable: true,
});
const _origSetConfig = SungrowMatrixCard.prototype.setConfig;
SungrowMatrixCard.prototype.setConfig = function (config) {
  if (config && Array.isArray(config.layout)) { this._cfg = config; this._sig = ""; return; }
  return _origSetConfig.call(this, config);
};

customElements.get("sungrow-matrix-card") || customElements.define("sungrow-matrix-card", SungrowMatrixCard);
window.customCards.push({ type: "sungrow-matrix-card", name: "Sungrow table", description: "Values and settings laid out by quantity and device" });

/* ------------------------------------------------------------------ */
/* charts: one card for every history graph on the dashboard           */
/* ------------------------------------------------------------------ */
/*
 * config: { title, color, height, ranges: ["6h","24h","7d","60d","360d"], range,
 *           views: [{ name, unit, series: [...], bands: [...], refs: [...], zero, min, max }] }
 *   (or the view's fields directly on the card when it has one view)
 * series: { entity, label, color, area, step, dash, scale }
 * bands:  { entity, label, color }        an on/off entity drawn as a lane under the plot
 * refs:   { value, label, color }         a horizontal reference line
 *
 * Up to 24 h the recorder's history is drawn as recorded; from 7 days Home
 * Assistant's long-term statistics (hourly, then daily means with the min-max
 * range shaded) keep even a year quick. Entities without statistics (controls,
 * on/off flags) always come from history, and only for ranges up to 7 days.
 */

const RANGES = {
  "6h": { label: "6 h", hours: 6 },
  "24h": { label: "24 h", hours: 24 },
  "7d": { label: "7 d", hours: 168, period: "hour" },
  "60d": { label: "60 d", hours: 1440, period: "day" },
  "360d": { label: "360 d", hours: 8640, period: "day" },
};

const CHART_STYLE = `
  :host { display: block; min-width: 0; }
  ha-card { display: block; background: var(--card-background-color); border-radius: 16px; padding: 16px 18px 12px; box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.06)); }
  .head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  h3 { margin: 0; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; margin-right: auto; }
  h3 i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .seg { display: flex; gap: 2px; background: var(--secondary-background-color, rgba(127,127,127,.12)); padding: 3px; border-radius: 9px; }
  .seg button { border: none; background: transparent; color: var(--secondary-text-color); font: 500 12px/1 inherit; font-family: inherit; padding: 6px 9px; border-radius: 7px; cursor: pointer; white-space: nowrap; }
  .seg button:hover { color: var(--primary-text-color); }
  .seg button[aria-pressed="true"] { background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 1px 2px rgba(0,0,0,.15); }
  .tabs { margin-bottom: 6px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 2px 0 6px; }
  .note { font-size: 12px; color: var(--secondary-text-color); margin: -2px 0 6px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--secondary-text-color); cursor: pointer; user-select: none; border: none; background: none; padding: 2px 0; font-family: inherit; }
  .chip i { width: 10px; height: 3px; border-radius: 2px; display: inline-block; }
  .chip i.band { height: 8px; border-radius: 2px; opacity: .7; }
  .chip b { color: var(--primary-text-color); font-weight: 600; font-variant-numeric: tabular-nums; }
  .chip.off { opacity: .4; }
  .chip.off b { text-decoration: line-through; }
  .plot { position: relative; }
  svg { display: block; width: 100%; overflow: visible; }
  svg text { font-size: 10.5px; fill: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .grid line { stroke: var(--divider-color, rgba(127,127,127,.18)); stroke-width: 1; }
  .zero { stroke: var(--secondary-text-color); stroke-opacity: .45; stroke-width: 1; }
  .ref { stroke-width: 1; stroke-dasharray: 4 4; }
  .tip { position: absolute; top: 0; pointer-events: none; background: var(--card-background-color); border: 1px solid var(--divider-color, rgba(127,127,127,.25)); border-radius: 10px; padding: 8px 10px; font-size: 12px; box-shadow: 0 6px 18px rgba(0,0,0,.18); white-space: nowrap; z-index: 2; }
  .tip .t { color: var(--secondary-text-color); margin-bottom: 4px; }
  .tip div { display: flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
  .tip i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .tip b { margin-left: auto; padding-left: 12px; }
  .empty { position: absolute; inset: 0; display: grid; place-items: center; font-size: 12.5px; color: var(--secondary-text-color); pointer-events: none; }
`;

const niceStep = (span, n) => {
  const raw = span / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
};
const fmtNum = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)).replace(/\.0+$|(\.\d*?)0+$/, "$1");
const tsOf = (x) => (typeof x === "number" ? (x > 1e11 ? x : x * 1000) : Date.parse(x));

/* a smooth line that never overshoots (monotone cubic), or steps */
function pathOf(pts, step) {
  if (!pts.length) return "";
  if (step) {
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 1; i < pts.length; i++) d += `H${pts[i][0]}V${pts[i][1]}`;
    return d;
  }
  if (pts.length < 3) return "M" + pts.map((p) => p.join(",")).join("L");
  const n = pts.length, dx = [], m = [], t = [];
  for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; m[i] = dx[i] ? (pts[i + 1][1] - pts[i][1]) / dx[i] : 0; }
  t[0] = m[0]; t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], h = a * a + b * b;
    if (h > 9) { const k = 3 / Math.sqrt(h); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
  }
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += `C${pts[i][0] + h},${pts[i][1] + t[i] * h} ${pts[i + 1][0] - h},${pts[i + 1][1] - t[i + 1] * h} ${pts[i + 1][0]},${pts[i + 1][1]}`;
  }
  return d;
}

/* keep at most ~2 points per pixel: each bucket keeps its first and its extreme value */
function decimate(points, width) {
  if (points.length <= width * 2) return points;
  const t0 = points[0][0], span = points[points.length - 1][0] - t0 || 1, out = [];
  let bucket = -1, lo = null, hi = null;
  const flush = () => { if (lo) { if (lo[0] <= hi[0]) out.push(lo, hi); else out.push(hi, lo); } };
  for (const p of points) {
    const b = Math.floor(((p[0] - t0) / span) * width);
    if (b !== bucket) { flush(); bucket = b; lo = hi = p; continue; }
    if (p[1] < lo[1]) lo = p;
    if (p[1] > hi[1]) hi = p;
  }
  flush();
  return out;
}

class SungrowChartCard extends HTMLElement {
  setConfig(config) {
    const views = config.views || [{ name: "", series: config.series || [], bands: config.bands, refs: config.refs, unit: config.unit, zero: config.zero, min: config.min, max: config.max }];
    if (!views.every((v) => Array.isArray(v.series))) throw new Error("series required");
    this._cfg = { height: 220, ranges: ["24h", "7d"], ...config, views };
    this._range = this._cfg.range || this._cfg.ranges[0];
    this._view = 0;
    this._hidden = new Set();
    this._data = null;
    this._key = "";
  }
  getCardSize() { return 5; }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (e) => this._click(e));
      this._ro = new ResizeObserver(() => this._draw());
      this._ro.observe(this);
      this._timer = setInterval(() => this._load(true), 300000);
    }
    if (!this._skeleton) this._shell();
    this._legend();
    const key = `${this._view}|${this._range}`;
    if (key !== this._key) { this._key = key; this._load(); }
  }

  disconnectedCallback() { clearInterval(this._timer); this._timer = null; }
  connectedCallback() { if (this._hass && !this._timer) this._timer = setInterval(() => this._load(true), 300000); }

  get _v() { return this._cfg.views[this._view]; }

  _shell() {
    const c = this._cfg;
    const seg = (items, attr, cur) => `<div class="seg">${items.map(([id, label]) => `<button data-${attr}="${id}" aria-pressed="${id === cur}">${label}</button>`).join("")}</div>`;
    this.shadowRoot.innerHTML = `<style>${CHART_STYLE}</style><ha-card>
      <div class="head"><h3><i style="background:${c.color || "#8a93a3"}"></i>${c.title || ""}</h3>
        ${c.views.length > 1 ? seg(c.views.map((v, i) => [i, v.name]), "view", this._view) : ""}
        ${c.ranges.length > 1 ? seg(c.ranges.map((r) => [r, RANGES[r].label]), "range", this._range) : ""}</div>
      ${c.note ? `<div class="note">${c.note}</div>` : ""}<div class="legend" id="legend"></div>
      <div class="plot" id="plot"><svg id="svg"></svg><div class="tip" id="tip" hidden></div><div class="empty" id="empty" hidden></div></div></ha-card>`;
    const plot = this.shadowRoot.getElementById("plot");
    plot.addEventListener("pointermove", (e) => this._hover(e));
    plot.addEventListener("pointerleave", () => { this.shadowRoot.getElementById("tip").hidden = true; this._cursor(null); });
    this._skeleton = true;
  }

  _click(e) {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.range) this._range = b.dataset.range;
    else if (b.dataset.view !== undefined) { this._view = +b.dataset.view; this._hidden.clear(); }
    else if (b.dataset.toggle) { const k = b.dataset.toggle; this._hidden.has(k) ? this._hidden.delete(k) : this._hidden.add(k); this._legend(); this._draw(); return; }
    else return;
    this.shadowRoot.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.range === this._range || (x.dataset.view !== undefined && +x.dataset.view === this._view))));
    this._legend();
    this._key = `${this._view}|${this._range}`;
    this._load();
  }

  _legend() {
    const el = this.shadowRoot && this.shadowRoot.getElementById("legend");
    if (!el || !this._hass) return;
    const v = this._v;
    const now = (s) => {
      const st = this._hass.states[s.entity];
      const n = st ? parseFloat(st.state) : NaN;
      if (!Number.isFinite(n)) return "";
      return `<b>${fmtNum(n * (s.scale ?? 1))}</b>`;
    };
    el.innerHTML = v.series.map((s) => `<button class="chip${this._hidden.has(s.entity) ? " off" : ""}" data-toggle="${s.entity}"><i style="background:${s.color}${s.dash ? ";opacity:.7" : ""}"></i>${s.label} ${now(s)}</button>`).join("")
      + (v.bands || []).map((b) => `<button class="chip${this._hidden.has(b.entity) ? " off" : ""}" data-toggle="${b.entity}"><i class="band" style="background:${b.color}"></i>${b.label}</button>`).join("")
      + (v.unit ? `<span class="chip" style="cursor:default;margin-left:auto">${v.unit}</span>` : "");
  }

  async _load(quiet) {
    if (!this._hass) return;
    const v = this._v, r = RANGES[this._range], end = new Date(), start = new Date(end - r.hours * 3600e3);
    const want = this._key;
    const ids = v.series.map((s) => s.entity), bandIds = (v.bands || []).map((b) => b.entity);
    const stat = (id) => r.period && this._hass.states[id]?.attributes.state_class;
    const statIds = ids.filter(stat), histIds = [...ids.filter((id) => !stat(id)), ...(r.hours <= 168 ? bandIds : [])];
    if (!quiet) this._empty("Loading…");
    const data = { start: +start, end: +end, series: {}, bands: {}, env: !!r.period && r.period === "day", stats: new Set(statIds) };
    try {
      const [st, hi] = await Promise.all([
        statIds.length ? this._hass.callWS({ type: "recorder/statistics_during_period", start_time: start.toISOString(), end_time: end.toISOString(), statistic_ids: statIds, period: r.period, types: ["mean", "min", "max"] }) : {},
        histIds.length ? this._hass.callWS({ type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(), entity_ids: histIds, minimal_response: true, no_attributes: true, significant_changes_only: false }) : {},
      ]);
      for (const id of statIds) data.series[id] = (st[id] || []).filter((p) => p.mean != null).map((p) => [tsOf(p.start) + (r.period === "day" ? 43200e3 : 1800e3), p.mean, p.min, p.max]);
      for (const id of histIds) {
        const rows = (hi[id] || []).map((p) => [tsOf(p.lu ?? p.last_updated ?? p.lc), p.s ?? p.state]);
        if (bandIds.includes(id)) data.bands[id] = rows;
        else data.series[id] = rows.map(([t, s]) => [Math.max(t, +start), parseFloat(s)]).filter((p) => Number.isFinite(p[1]));
      }
      // the line runs to now at the entity's present value (the recorder only stores changes)
      for (const id of histIds) {
        const s = data.series[id], cur = parseFloat(this._hass.states[id]?.state);
        if (s && Number.isFinite(cur)) s.push([+end, cur]);
      }
    } catch (err) {
      if (want === this._key) this._empty(`Could not load the history: ${err.message || err}`);
      return;
    }
    if (want !== this._key) return;  // the range or tab changed meanwhile
    this._data = data;
    this._draw();
  }

  _empty(text) {
    const e = this.shadowRoot.getElementById("empty");
    e.textContent = text || "";
    e.hidden = !text;
  }

  _draw() {
    const d = this._data;
    if (!d || !this.shadowRoot) return;
    const v = this._v, svg = this.shadowRoot.getElementById("svg");
    const W = Math.max(240, this.shadowRoot.getElementById("plot").clientWidth), bandsShown = (v.bands || []).filter((b) => !this._hidden.has(b.entity) && d.bands[b.entity]);
    const lane = 9, laneGap = 3, laneH = bandsShown.length ? bandsShown.length * (lane + laneGap) + 4 : 0;
    const H = this._cfg.height, L = 44, R = 10, T = 8, B = 22 + laneH, ph = H - T - B, pw = W - L - R;
    const shown = v.series.filter((s) => !this._hidden.has(s.entity) && d.series[s.entity]?.length);
    // y range over what is visible
    let lo = Infinity, hi = -Infinity;
    for (const s of shown) for (const p of d.series[s.entity]) {
      const k = s.scale ?? 1;
      for (const y of [p[1], d.env ? p[2] : null, d.env ? p[3] : null]) if (y != null) { lo = Math.min(lo, y * k); hi = Math.max(hi, y * k); }
    }
    for (const r of v.refs || []) { lo = Math.min(lo, r.value); hi = Math.max(hi, r.value); }
    if (v.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (v.min != null) lo = Math.min(lo, v.min);
    if (v.max != null) hi = Math.max(hi, v.max);
    if (!Number.isFinite(lo)) { svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.height = `${H}px`; svg.innerHTML = ""; this._empty("No history yet for this range"); return; }
    this._empty("");
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const step = niceStep(hi - lo, Math.max(2, Math.round(ph / 46)));
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    const x = (t) => L + ((t - d.start) / (d.end - d.start)) * pw, y = (val) => T + (1 - (val - lo) / (hi - lo)) * ph;
    this._scale = { x, y, L, R, W, pw, T, ph, start: d.start, end: d.end };
    // grid, axes
    let g = `<g class="grid">`;
    for (let val = lo; val <= hi + step / 2; val += step) g += `<line x1="${L}" x2="${W - R}" y1="${y(val)}" y2="${y(val)}"/><text x="${L - 6}" y="${y(val) + 3.5}" text-anchor="end">${fmtNum(val)}</text>`;
    const hours = (d.end - d.start) / 3600e3, tick = hours <= 6 ? 1 : hours <= 24 ? 3 : hours <= 168 ? 24 : hours <= 1440 ? 24 * 7 : 24 * 30;
    const first = new Date(d.start); first.setMinutes(0, 0, 0);
    if (tick >= 24) first.setHours(0);
    if (tick >= 720) first.setDate(1);
    for (let t = +first; t <= d.end; ) {
      if (t >= d.start) {
        const dt = new Date(t);
        const label = tick < 24 ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : tick < 720 ? dt.toLocaleDateString([], { day: "numeric", month: "short" }) : dt.toLocaleDateString([], { month: "short" });
        g += `<line x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${T + ph}" style="stroke-opacity:.5"/><text x="${x(t)}" y="${H - laneH - 6}" text-anchor="middle">${label}</text>`;
      }
      const n = new Date(t);
      if (tick >= 720) n.setMonth(n.getMonth() + 1); else n.setHours(n.getHours() + tick);
      t = +n;
    }
    g += `</g>`;
    if (lo < 0 && hi > 0) g += `<line class="zero" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`;
    for (const r of v.refs || []) g += `<line class="ref" x1="${L}" x2="${W - R}" y1="${y(r.value)}" y2="${y(r.value)}" stroke="${r.color || "currentColor"}"/><text x="${W - R - 4}" y="${y(r.value) - 4}" text-anchor="end" style="fill:${r.color || "var(--secondary-text-color)"}">${r.label}</text>`;
    // series: envelope, area, line
    let defs = "", body = "";
    shown.forEach((s, i) => {
      const k = s.scale ?? 1, pts = decimate(d.series[s.entity].map((p) => [p[0], p[1] * k, p[2] != null ? p[2] * k : null, p[3] != null ? p[3] * k : null]), pw);
      const xy = pts.map((p) => [+x(p[0]).toFixed(1), +y(p[1]).toFixed(1)]);
      const gid = `g${this._view}_${i}`, stepped = s.step || !d.stats.has(s.entity);
      if (d.env && pts.some((p) => p[2] != null)) {
        const up = pts.map((p) => [x(p[0]), y(p[3])]), dn = pts.map((p) => [x(p[0]), y(p[2])]).reverse();
        body += `<path d="M${up.map((p) => p.join(",")).join("L")}L${dn.map((p) => p.join(",")).join("L")}Z" fill="${s.color}" opacity=".13"/>`;
      }
      if (s.area) {
        defs += `<linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".32"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient>`;
        const base = y(Math.max(lo, Math.min(hi, 0)));
        body += `<path d="${pathOf(xy, stepped)}L${xy[xy.length - 1][0]},${base}L${xy[0][0]},${base}Z" fill="url(#${gid})"/>`;
      }
      body += `<path d="${pathOf(xy, stepped)}" fill="none" stroke="${s.color}" stroke-width="${s.dash ? 1.5 : 2}" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ' stroke-dasharray="5 4"' : ""}/>`;
    });
    // on/off lanes under the plot
    bandsShown.forEach((b, i) => {
      const yy = T + ph + 22 + i * (lane + laneGap);
      body += `<rect x="${L}" y="${yy}" width="${pw}" height="${lane}" rx="3" fill="var(--secondary-background-color, rgba(127,127,127,.12))"/>`;
      const rows = d.bands[b.entity];
      rows.forEach(([t, s], j) => {
        if (s !== "on") return;
        const t1 = j + 1 < rows.length ? rows[j + 1][0] : d.end;
        const a = x(Math.max(t, d.start)), w = Math.max(1, x(Math.min(t1, d.end)) - a);
        body += `<rect x="${a}" y="${yy}" width="${w}" height="${lane}" rx="2" fill="${b.color}" opacity=".85"/>`;
      });
    });
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.height = `${H}px`;
    svg.innerHTML = `<defs>${defs}</defs>${g}${body}<g id="cursor"></g>`;
  }

  _cursor(t) {
    const c = this.shadowRoot.getElementById("cursor");
    if (!c) return;
    if (t == null) { c.innerHTML = ""; return; }
    const { x, y, T, ph } = this._scale, d = this._data, v = this._v;
    let html = `<line x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${T + ph}" stroke="var(--secondary-text-color)" stroke-opacity=".6" stroke-dasharray="3 3"/>`;
    for (const s of v.series) {
      if (this._hidden.has(s.entity)) continue;
      const p = this._at(d.series[s.entity], t);
      if (p) html += `<circle cx="${x(p[0])}" cy="${y(p[1] * (s.scale ?? 1))}" r="3.6" fill="${s.color}" stroke="var(--card-background-color)" stroke-width="1.5"/>`;
    }
    c.innerHTML = html;
  }

  _at(points, t) {
    if (!points || !points.length) return null;
    let a = 0, b = points.length - 1;
    while (b - a > 1) { const m = (a + b) >> 1; if (points[m][0] <= t) a = m; else b = m; }
    return Math.abs(points[a][0] - t) <= Math.abs(points[b][0] - t) ? points[a] : points[b];
  }

  _hover(e) {
    if (!this._scale || !this._data) return;
    const plot = this.shadowRoot.getElementById("plot"), box = plot.getBoundingClientRect();
    const px = e.clientX - box.left, { L, pw, start, end } = this._scale;
    const tip = this.shadowRoot.getElementById("tip");
    if (px < L || px > L + pw) { tip.hidden = true; this._cursor(null); return; }
    const t = start + ((px - L) / pw) * (end - start), v = this._v, d = this._data;
    const day = (end - start) > 26 * 3600e3;
    const when = new Date(t).toLocaleString([], day ? { day: "numeric", month: "short", hour: d.env ? undefined : "2-digit", minute: d.env ? undefined : "2-digit" } : { hour: "2-digit", minute: "2-digit" });
    const rows = v.series.filter((s) => !this._hidden.has(s.entity)).map((s) => {
      const p = this._at(d.series[s.entity], t);
      if (!p) return "";
      const k = s.scale ?? 1, range = d.env && p[2] != null ? ` <span style="color:var(--secondary-text-color);font-weight:400">${fmtNum(p[2] * k)}–${fmtNum(p[3] * k)}</span>` : "";
      return `<div><i style="background:${s.color}"></i>${s.label}<b>${fmtNum(p[1] * k)}${range}</b></div>`;
    }).join("");
    const lanes = (v.bands || []).filter((b) => d.bands[b.entity] && !this._hidden.has(b.entity)).map((b) => {
      const rows = d.bands[b.entity];
      let s = null;
      for (const [tt, st] of rows) { if (tt <= t) s = st; else break; }
      return s === "on" ? `<div><i style="background:${b.color}"></i>${b.label}</div>` : "";
    }).join("");
    tip.innerHTML = `<div class="t">${when}${v.unit ? ` · ${v.unit}` : ""}</div>${rows}${lanes}`;
    tip.hidden = false;
    const w = tip.offsetWidth;
    tip.style.left = `${px + 14 + w > box.width ? px - w - 14 : px + 14}px`;
    this._cursor(t);
  }
}

/* a row of charts, two to a line on a wide screen, one on a phone */
class SungrowCharts extends HTMLElement {
  setConfig(config) {
    if (!config || !Array.isArray(config.charts)) throw new Error("charts required");
    this._cfg = config;
  }
  getCardSize() { return 6; }
  set hass(hass) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>:host{display:block} .row{display:grid;gap:20px;grid-template-columns:repeat(4,minmax(0,1fr))} .row>*{grid-column:span 2;min-width:0} .row>.w4{grid-column:span 4} @media (max-width:1100px){.row{grid-template-columns:minmax(0,1fr)} .row>*,.row>.w4{grid-column:auto}}</style><div class="row"></div>`;
      const row = this.shadowRoot.querySelector(".row");
      this._charts = this._cfg.charts.map((c) => {
        const el = document.createElement("sungrow-chart-card");
        el.setConfig(c);
        if (c.span === 4) el.classList.add("w4");
        row.appendChild(el);
        return el;
      });
    }
    for (const c of this._charts) c.hass = hass;
  }
}

customElements.get("sungrow-chart-card") || customElements.define("sungrow-chart-card", SungrowChartCard);
customElements.get("sungrow-charts") || customElements.define("sungrow-charts", SungrowCharts);
window.customCards.push({ type: "sungrow-chart-card", name: "Sungrow chart", description: "History of any readings, from 6 hours to a year" });

/* ------------------------------------------------------------------ */
/* help: what every page and setting means (text from the dashboard)    */
/* ------------------------------------------------------------------ */

const HELP_STYLE = `
  :host { display: block; }
  .sections { display: grid; gap: 20px; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  section { grid-column: span 2; background: var(--card-background-color); border-radius: 16px; padding: 18px 20px; box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.06)); min-width: 0; }
  section.wide { grid-column: span 4; }
  h3 { margin: 0 0 10px; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
  h3 i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  p { margin: 0 0 10px; font-size: 13px; line-height: 1.55; color: var(--primary-text-color); }
  p:last-child { margin-bottom: 0; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-weight: 500; font-size: 11.5px; letter-spacing: .03em; text-transform: uppercase; color: var(--secondary-text-color); padding: 6px 10px 6px 0; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.18)); }
  td { padding: 7px 10px 7px 0; vertical-align: top; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.10)); line-height: 1.45; }
  td:first-child { font-weight: 600; white-space: nowrap; }
  td.reg { font-variant-numeric: tabular-nums; color: var(--secondary-text-color); white-space: nowrap; }
  .on { color: ${PALETTE.export}; font-weight: 600; } .off { color: ${PALETTE.import}; font-weight: 600; }
  code { font-size: 12px; background: var(--secondary-background-color, rgba(127,127,127,.12)); padding: 1px 5px; border-radius: 5px; }
  a { color: var(--primary-color); }
  @media (max-width: 1100px) { .sections { grid-template-columns: minmax(0, 1fr); } section, section.wide { grid-column: auto; } }
`;

class SungrowHelpCard extends HTMLElement {
  setConfig(config) {
    if (!config || !Array.isArray(config.sections)) throw new Error("sections required");
    this._cfg = config;
  }
  getCardSize() { return 12; }
  set hass(hass) {
    if (this.shadowRoot) return;  // text only: drawn once
    this.attachShadow({ mode: "open" });
    const table = (t) => `<div class="scroll"><table><thead><tr>${t.head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${t.rows.map((r) => `<tr>${r.map((c, i) => `<td${t.reg === i ? ' class="reg"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    this.shadowRoot.innerHTML = `<style>${HELP_STYLE}</style><div class="sections">${this._cfg.sections.map((s) =>
      `<section class="${s.wide ? "wide" : ""}"><h3><i style="background:${s.color || "#8a93a3"}"></i>${s.title}</h3>${(s.text || []).map((t) => `<p>${t}</p>`).join("")}${s.table ? table(s.table) : ""}</section>`).join("")}</div>`;
  }
}

customElements.get("sungrow-help-card") || customElements.define("sungrow-help-card", SungrowHelpCard);
window.customCards.push({ type: "sungrow-help-card", name: "Sungrow help", description: "What every page and setting means" });

/* ------------------------------------------------------------------ */
/* the app: one full-screen page with its own navigation               */
/* ------------------------------------------------------------------ */

const ICONS = {
  overview: "M3 12 12 4l9 8M5 10v10h5v-6h4v6h5V10",
  solar: "M4 17h16l-2-9H6zM8 8l-1 9M12 8v9M16 8l1 9M5 12.5h14M12 2v2M4.2 4.2l1.4 1.4M19.8 4.2l-1.4 1.4",
  battery: "M7 4h10v17H7zM10 2h4v2M10 10h4M10 14h4",
  grid: "M12 2 7 22M12 2l5 20M8 8h8M6.5 14h11M5 20h14",
  backup: "M12 3 4 7v5c0 5 3.5 8 8 9 4.5-1 8-4 8-9V7zM12 8v5M12 16v.5",
  controls: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4",
  system: "M12 8v5M12 16v.5M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0",
  help: "M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17v.5M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0",
};

const APP_STYLE = `
  :host { display: block; min-height: 100%; }
  .app { --gap: 20px; min-height: calc(100vh - var(--header-height, 56px)); background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, "Inter", system-ui, sans-serif); }
  header { position: sticky; top: 0; z-index: 2; backdrop-filter: blur(14px); background: color-mix(in srgb, var(--primary-background-color) 82%, transparent); border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.15)); }
  .bar { max-width: 1840px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
  .brand { display: flex; align-items: baseline; gap: 10px; margin-right: auto; }
  .brand b { font-size: 18px; font-weight: 600; letter-spacing: -.01em; }
  .brand span { font-size: 12.5px; color: var(--secondary-text-color); }
  nav { display: flex; gap: 4px; background: var(--secondary-background-color, rgba(127,127,127,.10)); padding: 4px; border-radius: 12px; overflow-x: auto; max-width: 100%; }
  nav button { display: flex; align-items: center; gap: 7px; border: none; background: transparent; color: var(--secondary-text-color); font: 500 13px/1 inherit; font-family: inherit; padding: 9px 13px; border-radius: 9px; cursor: pointer; white-space: nowrap; transition: background .15s, color .15s; }
  nav button:hover { color: var(--primary-text-color); }
  nav button[aria-current="page"] { background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,.12); }
  nav svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  main { max-width: 1840px; margin: 0 auto; padding: 24px; display: grid; gap: var(--gap); grid-template-columns: minmax(0, 1fr); }
  .live { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--secondary-text-color); }
  .live i { width: 8px; height: 8px; border-radius: 50%; background: ${PALETTE.export}; box-shadow: 0 0 0 3px ${PALETTE.export}33; }
  .live.stale i { background: ${PALETTE.import}; box-shadow: 0 0 0 3px ${PALETTE.import}33; }
  @media (max-width: 700px) { .bar { padding: 12px 16px; gap: 12px; } main { padding: 16px; } nav button span { display: none; } }
`;

class SungrowApp extends HTMLElement {
  setConfig(config) {
    if (!config) throw new Error("config required");
    this._cfg = config;
    this._alias = config.alias || {};
    // no pages: the integration lays the dashboard out for this site's devices (websocket sungrow_sh_t/app)
    this._auto = !Array.isArray(config.pages);
    this._built = null;
    if (!this._auto) this._pickPage();
  }

  _pickPage() {
    let saved = null;
    try { saved = localStorage.getItem("sungrow-app-page"); } catch (e) { /* storage blocked */ }
    this._page = this._cfg.pages.some((p) => p.id === saved) ? saved : this._cfg.pages[0].id;
  }

  async _fetch(hass) {
    this._loading = true;
    try {
      const res = await hass.callWS({ type: "sungrow_sh_t/app" });
      this._cfg = { ...res.config, title: this._cfg.title || res.config.title };
      this._alias = res.alias || {};
      if (!this._cfg.pages.length) throw new Error("nothing to show yet");
      this._pickPage();
      this._auto = false;
      this._built = null;
      this.hass = this._hass;
    } catch (err) {
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      root.innerHTML = `<style>${APP_STYLE}</style><div class="app"><main><p>Sungrow: ${err.message || err}. Is the Sungrow integration set up and running?</p></main></div>`;
      setTimeout(() => { this._loading = false; if (this._hass) this.hass = this._hass; }, 30000);
    }
  }

  /* hass as the cards see it: an entity the user renamed answers to the name the layout uses */
  _view(hass) {
    const alias = this._alias;
    if (!alias || !Object.keys(alias).length) return hass;
    if (this._wrapped && this._wrappedFrom === hass) return this._wrapped;
    const real = (id) => alias[id] || id;
    const back = Object.fromEntries(Object.entries(alias).map(([k, v]) => [v, k]));
    const view = Object.create(hass);
    Object.defineProperty(view, "states", { value: new Proxy(hass.states, { get: (t, k) => t[real(k)], has: (t, k) => real(k) in t }) });
    view.callService = (d, svc, data, ...rest) => hass.callService(d, svc, data && data.entity_id ? { ...data, entity_id: real(data.entity_id) } : data, ...rest);
    view.callWS = async (m) => {
      const msg = { ...m };
      if (msg.entity_ids) msg.entity_ids = msg.entity_ids.map(real);
      if (msg.statistic_ids) msg.statistic_ids = msg.statistic_ids.map(real);
      const res = await hass.callWS(msg);
      if (!res || typeof res !== "object" || Array.isArray(res) || !(m.entity_ids || m.statistic_ids)) return res;
      return Object.fromEntries(Object.entries(res).map(([k, v]) => [back[k] || k, v]));
    };
    this._wrapped = view;
    this._wrappedFrom = hass;
    return view;
  }
  getCardSize() { return 20; }

  _go(id) {
    this._page = id;
    try { localStorage.setItem("sungrow-app-page", id); } catch (e) { /* storage blocked */ }
    this._build();
    if (this._hass) this.hass = this._hass;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  _build() {
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    const page = this._cfg.pages.find((p) => p.id === this._page);
    const nav = this._cfg.pages.map((p) => `<button data-page="${p.id}" ${p.id === this._page ? 'aria-current="page"' : ""}><svg viewBox="0 0 24 24"><path d="${ICONS[p.icon || p.id] || ICONS.overview}"/></svg><span>${p.title}</span></button>`).join("");
    root.innerHTML = `<style>${APP_STYLE}</style><div class="app"><header><div class="bar"><div class="brand"><b>${this._cfg.title || "Sungrow Alive"}</b><span>${page.subtitle || ""}</span></div><div class="live" id="live"><i></i><span id="live-text">Live</span></div><nav>${nav}</nav></div></header><main id="main"></main></div>`;
    root.querySelector("nav").addEventListener("click", (e) => { const b = e.target.closest("button[data-page]"); if (b) this._go(b.dataset.page); });
    const main = root.getElementById("main");
    this._children = page.cards.map((c) => {
      const el = document.createElement(c.type.replace(/^custom:/, ""));
      el.setConfig(c);
      main.appendChild(el);
      return el;
    });
    this._built = this._page;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._auto) {
      if (!this._loading) this._fetch(hass);
      return;
    }
    if (this._built !== this._page) this._build();
    const view = this._view(hass);
    for (const c of this._children) c.hass = view;
    const liveId = (this._cfg.live || ["sensor.sungrow_logger_load_power"]).find((id) => view.states[id]);
    const s = liveId && view.states[liveId];
    const age = s ? (Date.now() - Date.parse(s.last_reported || s.last_updated)) / 1000 : 1e9;
    const live = this.shadowRoot.getElementById("live");
    live.classList.toggle("stale", age > 60);
    this.shadowRoot.getElementById("live-text").textContent = age > 60 ? `No data for ${Math.round(age / 60)} min` : "Live";
  }
}

customElements.get("sungrow-app") || customElements.define("sungrow-app", SungrowApp);
window.customCards.push({ type: "sungrow-app", name: "Sungrow app", description: "The whole Sungrow dashboard as one page" });

/*
 * A dashboard built before this file finished loading shows Home Assistant's
 * "Custom element doesn't exist: sungrow-app", and on Home Assistant 2026.10's
 * panel view it never builds the card again: its own "ll-rebuild" was ignored
 * (10 Nov 2026, a plain F5 at a wide window, about one load in seven; a resize,
 * which rebuilds, brought it back). Swapping the error card for the real card
 * worked for a moment, but its hui-card still holds the error card and puts it
 * back on the next update. So the card's hui-card is handed its own config
 * again, which makes it build the card itself, now that the element exists;
 * where there is no hui-card the error card is swapped. The error card's own
 * fields are renamed in production builds, so ours is recognised by its
 * hui-card's config or by its text ("... doesn't exist: sungrow-app.").
 * Looked for every second for 60 s after load and after each move between
 * dashboards.
 */
function sungrowFixMissing() {
  const ha = document.querySelector("home-assistant");
  if (!ha || !ha.hass) return 0;
  const host = (el) => {
    for (let n = el, hops = 0; n && hops < 12; hops += 1) {
      n = n.parentNode || (n.getRootNode && n.getRootNode().host);
      if (n && n.localName === "hui-card") return n;
    }
    return null;
  };
  const seen = new Set();
  let fixed = 0;
  const walk = (node) => {
    if (!node || seen.has(node)) return;
    seen.add(node);
    for (const el of node.querySelectorAll ? [...node.querySelectorAll("*")] : []) {
      if (el.localName === "hui-error-card") {
        const card = host(el);
        const cfg = card && card.config && typeof card.config.type === "string" ? card.config : null;
        const said = `${el.shadowRoot ? el.shadowRoot.textContent : ""} ${el.textContent || ""}`.match(/sungrow-[a-z-]+/);
        const type = cfg ? cfg.type : (said ? `custom:${said[0]}` : "");
        const tag = type.replace(/^custom:/, "");
        if (/^sungrow-/.test(tag) && customElements.get(tag)) {
          if (cfg) {
            card.config = { ...cfg };
          } else {
            const real = document.createElement(tag);
            real.setConfig({ type });
            real.hass = ha.hass;
            el.replaceWith(real);
          }
          fixed += 1;
        }
      }
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  return fixed;
}
function sungrowWatch(seconds) {
  let left = seconds;
  const tick = () => { sungrowFixMissing(); if (--left > 0) setTimeout(tick, 1000); };
  tick();
}
sungrowWatch(60);
window.addEventListener("location-changed", () => sungrowWatch(60));

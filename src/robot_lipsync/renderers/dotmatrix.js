// Robot LipSync dot-matrix lips — the single screen renderer for this project.
//
// Both profiles draw the dot-matrix mouth ("点阵口型") designed for the Lilyput chest OLED:
//   "oled"   — the exact 128x64 one-bit frames flashed into the board
//              (firmware/esp32_oled/mouth_frames.h), one designed frame per event.
//   "screen" — the same geometry rebuilt continuously at twice the resolution for
//              tablets and monitors, drawn as flat pixel art (lip liner, body,
//              shadowed parting and hard highlight blocks).
// Two palettes: "red" and "blue".
// Needs mouth_model.js (tables) and, for the "oled" profile, mouth_frames.js (bitmaps).
//
// Usage (browser):
//   const at = DotLips.track(events);          // once per timeline
//   DotLips.draw(ctx, x, y, width, at(ms), {profile: "screen", palette: "red", t: ms});
//   The panel is always 2:1, so its height is width / 2. draw() also accepts a
//   plain articulation object.
(function (root) {
  "use strict";

  const MODEL = root.MOUTH_MODEL;
  if (!MODEL) throw new Error("dotmatrix.js needs mouth_model.js loaded first");
  const CH = MODEL.channels;
  const REST = {jaw_open: 0, lip_separation: 0.01, mouth_width: 0.48, lip_round: 0.05, lip_press: 0.18,
    lip_protrusion: 0, lower_lip_tuck: 0, asymmetry: 0};
  const KEYS = Object.keys(REST);
  const PALETTES = {
    red:  {glow: "255,40,108", core: "255,196,222", off: "255,40,108"},    // Y2K lipstick rose, toned down
    blue: {glow: "56,152,255", core: "205,232,255", off: "56,152,255"},    // Aqua (Mac OS X, 2000)
  };
  const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
  const av = (a, k) => (a && a[k] != null ? a[k] : REST[k]);

  // ---- muscle model (same arithmetic as robot_lipsync/mouth.py and the firmware) ----
  function constrain(p) {
    let jaw = clamp(p.jaw_open), sep = clamp(p.lip_separation), width = clamp(p.mouth_width);
    const press = clamp(p.lip_press), rnd = clamp(p.lip_round), prot = clamp(p.lip_protrusion);
    if (jaw > 0.52) width = Math.min(width, 0.72 - 0.42 * ((jaw - 0.52) / 0.48));
    if (width > 0.72) jaw = Math.min(jaw, 0.48 - 0.24 * ((width - 0.72) / 0.28));
    sep *= 1 - 0.96 * press;
    jaw *= 1 - 0.80 * press;
    width = Math.min(width, 1 - 0.32 * rnd - 0.16 * prot);
    return {jaw_open: clamp(jaw), lip_separation: clamp(sep), mouth_width: clamp(width), lip_round: rnd,
      lip_protrusion: prot, upper_lip_raise: clamp(p.upper_lip_raise), lower_lip_depress: clamp(p.lower_lip_depress),
      lip_press: press, lower_lip_tuck: clamp(p.lower_lip_tuck), corner_raise: clamp(p.corner_raise, -1, 1),
      asymmetry: clamp(p.asymmetry, -1, 1)};
  }
  function muscleFromArticulation(a) {
    const jaw = av(a, "jaw_open"), sep = av(a, "lip_separation"), width = av(a, "mouth_width");
    const tuck = av(a, "lower_lip_tuck"), press = av(a, "lip_press"), prot = av(a, "lip_protrusion");
    return constrain({jaw_open: jaw, lip_separation: sep, mouth_width: width, lip_round: av(a, "lip_round"),
      lip_protrusion: prot, upper_lip_raise: clamp(0.40 * sep + 0.18 * tuck - 0.10 * press + 0.15 * prot),
      lower_lip_depress: clamp((jaw - 0.35) * 1.55), lip_press: press, lower_lip_tuck: tuck,
      corner_raise: clamp((width - 0.70) * 0.75, 0, 0.30), asymmetry: av(a, "asymmetry")});
  }
  function lookup(name) { return MODEL.targets[name] || MODEL.zhTargets[name] || (MODEL.langTargets || {})[name]; }
  function targetFor(viseme) {
    const name = MODEL.visemeTargets[viseme];
    return name ? lookup(name) : null;
  }
  function nearestFrame(m) {
    let best = 0, bestD = Infinity;
    const names = Object.keys(MODEL.targets);
    names.forEach((n, i) => {
      let d = 0;
      for (const c in MODEL.frameWeights) d += MODEL.frameWeights[c] * Math.pow(m[c] - MODEL.targets[n][c], 2);
      if (d < bestD) { bestD = d; best = i; }
    });
    return MODEL.v2First + best;
  }
  const REST_FRAME = MODEL.v2First;

  function legacyPose(m, big) {
    if (!big) return {
      openness: clamp(0.98 * m.jaw_open + 0.54 * m.lip_separation, 0, 1.76),
      width: clamp(0.74 + 0.48 * m.mouth_width - 0.10 * m.lip_round - 0.10 * m.lip_protrusion - 0.08 * m.jaw_open, 0.58, 1.18),
      pucker: clamp(0.88 * m.lip_round + 0.58 * m.lip_protrusion, 0, 1.40),
      smile: 0.88 * m.corner_raise, tilt: 2.6 * m.asymmetry, shift: 2.0 * m.asymmetry,
      upperBias: 1.1 * m.upper_lip_raise - 0.25 * m.lip_press,
      lowerBias: 1.2 * m.lower_lip_depress - 0.45 * m.lower_lip_tuck,
    };
    // Tablet: a bigger screen needs bigger gestures. The same muscle pose opens
    // further, rounds narrower and presses harder than on the OLED, and a pucker
    // squeezes the lips together into a fuller, taller kiss.
    const pk = clamp(0.88 * m.lip_round + 0.58 * m.lip_protrusion, 0, 1.40);
    const kiss = clamp((pk - 0.6) / 0.8);
    return {
      openness: clamp(1.10 * m.jaw_open + 0.62 * m.lip_separation, 0, 1.80) * (1 - 0.6 * kiss),
      width: clamp(0.70 + 0.56 * m.mouth_width - 0.16 * m.lip_round - 0.16 * m.lip_protrusion - 0.10 * m.jaw_open, 0.46, 1.20),
      pucker: clamp(pk * 1.1, 0, 1.55),
      smile: 1.05 * m.corner_raise, tilt: 2.6 * m.asymmetry, shift: 2.0 * m.asymmetry,
      upperBias: 1.4 * m.upper_lip_raise - 2.2 * m.lip_press + 3.2 * kiss,
      lowerBias: 1.5 * m.lower_lip_depress - 0.6 * m.lower_lip_tuck - 2.6 * m.lip_press + 3.0 * kiss,
    };
  }

  // ---- Mouth geometry (port of make_lips.py) ------------------------------------------
  const CX = 64, CY = 28, HALF = 49.0, OPEN_SCALE = 29.0;
  const UO_REST = [[-1, 0], [-0.93, -0.07], [-0.82, -0.14], [-0.70, -0.28], [-0.58, -0.48], [-0.47, -0.73], [-0.36, -1.00],
    [-0.25, -0.98], [-0.13, -0.78], [0, -0.56], [0.13, -0.78], [0.25, -0.98], [0.36, -1.00], [0.47, -0.73], [0.58, -0.48],
    [0.70, -0.28], [0.82, -0.14], [0.93, -0.07], [1, 0]];
  const UO_TENSE = [[-1, 0], [-0.93, -0.06], [-0.82, -0.13], [-0.70, -0.27], [-0.58, -0.46], [-0.47, -0.65], [-0.36, -0.82],
    [-0.25, -0.78], [-0.13, -0.70], [0, -0.67], [0.13, -0.70], [0.25, -0.78], [0.36, -0.82], [0.47, -0.65], [0.58, -0.46],
    [0.70, -0.27], [0.82, -0.13], [0.93, -0.06], [1, 0]];
  function chaikin(pts) {
    let c = pts;
    for (let r = 0; r < 3; r++) {
      const out = [c[0]];
      for (let i = 0; i < c.length - 1; i++) {
        const a = c[i], b = c[i + 1];
        out.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]], [0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
      }
      out.push(c[c.length - 1]);
      c = out;
    }
    return c;
  }
  function contours(P, connected, soft = 0) {
    const half = HALF * P.width;
    const stretch = clamp((P.width - 1) / 0.18), mass = 1 - 0.22 * stretch;
    const upperH = 24.5 * mass + P.upperBias + P.openness, lowerH = 29.0 * mass + P.lowerBias + 1.2 * P.openness;
    const opening = OPEN_SCALE * P.openness, lift = 7.0 * P.openness, drop = 15.0 * P.openness;
    const openF = clamp((P.openness - 0.55) / 0.65), narrowF = clamp((1.08 - P.width) / 0.28);
    const c = (connected ? 0 : 4.0 * openF * narrowF) / lowerH;
    const ot = clamp(P.openness / 1.40), lt = clamp((P.width - 1) / 0.18), pr = clamp(P.pucker / 1.30);
    const bead = (0.055 + 0.185 * Math.min(1.08, Math.max(0.12, 1 - 0.72 * ot - 0.55 * lt + 0.35 * pr))) * (1 - 0.35 * soft);
    const arch = -0.075 * Math.min(1.05, Math.max(0.28, 1 - 0.55 * ot - 0.42 * lt + 0.28 * pr));
    const sculpt = Math.min(1.06, Math.max(0.58, 1 - 0.34 * ot - 0.25 * lt + 0.18 * pr));
    // soft > 0 relaxes the Cupid's bow toward the gentler tension outline (tablet profile)
    const uo = UO_REST.map(([u, r], i) => [u, UO_TENSE[i][1] + sculpt * (1 - soft) * (r - UO_TENSE[i][1])]);
    const ui = [[-1, 0], [-0.82, -0.035], [-0.62, -0.015], [-0.48, -0.010], [-0.38, arch * 0.68], [-0.30, arch], [-0.22, arch * 0.62],
      [-0.14, bead * 0.23], [-0.07, bead * 0.72], [0, bead], [0.07, bead * 0.72], [0.14, bead * 0.23], [0.22, arch * 0.62],
      [0.30, arch], [0.38, arch * 0.68], [0.48, -0.010], [0.62, -0.015], [0.82, -0.035], [1, 0]];
    const li = [[-1, c], [-0.82, 0.06], [-0.62, 0.10], [-0.44, 0.17], [-0.27, 0.26], [-0.13, 0.32], [0, 0.35],
      [0.13, 0.32], [0.27, 0.26], [0.44, 0.17], [0.62, 0.10], [0.82, 0.06], [1, c]];
    const lo = [[-1, c], [-0.92, 0.20], [-0.80, 0.42], [-0.64, 0.66], [-0.47, 0.85], [-0.28, 0.99], [0, 1.06],
      [0.28, 0.99], [0.47, 0.85], [0.64, 0.66], [0.80, 0.42], [0.92, 0.20], [1, c]];
    const map = (pts, h, inner, motion) => chaikin(pts.map(([u, v]) => {
      const x = CX + P.shift + u * half;
      let y = CY + v * h;
      const ap = Math.pow(Math.max(0, 1 - u * u), 0.62 + 0.48 * P.pucker);
      if (inner < 0) y -= opening * 0.46 * ap; else if (inner > 0) y += opening * 0.54 * ap;
      if (motion < 0) y -= lift * ap; else if (motion > 0) y += drop * ap;
      y -= 4.2 * P.smile * Math.pow(Math.abs(u), 1.8);
      y += 2.4 * P.tilt * u;
      return [x, y];
    }));
    return [map(uo, upperH, 0, -1), map(ui, upperH, -1, 0), map(li, lowerH, 1, 0), map(lo, lowerH, 0, 1)];
  }

  // Vector outline of the screen-profile lips for a muscle pose, in 128x64 panel
  // units: {upper, lower, mouth} closed polygons (mouth = whole silhouette). For pen/vector renderers.
  function outline(m) {
    const P = legacyPose(m, true);
    const connected = P.width > 1.02 || Math.abs(P.tilt) > 0.3;
    const [uo, ui, li, lo] = contours(P, connected, 0.6);
    const up = -3.0 * m.upper_lip_raise + 2.4 * m.lip_press;
    const down = 3.0 * m.lower_lip_depress + 2.2 * m.jaw_open - 3.0 * m.lip_press;
    const shift = (pts, dy) => pts.map(([x, y]) => [x, y + dy]);
    return {upper: shift(uo.concat(ui.slice().reverse()), up), lower: shift(li.concat(lo.slice().reverse()), down),
      mouth: shift(uo, up).concat(shift(lo, down).reverse())};
  }

  // ---- offscreen helpers --------------------------------------------------------------
  const CACHE = {};
  function layer(key, w, h) {
    let c = CACHE[key];
    if (!c || c.width !== w || c.height !== h) {
      c = CACHE[key] = (typeof OffscreenCanvas !== "undefined") ? new OffscreenCanvas(w, h) : Object.assign(document.createElement("canvas"), {width: w, height: h});
      c._fresh = true;
    }
    return c;
  }

  // ---- "screen": continuous Mouth geometry at 2x, flat pixel-art tones ----------------
  const S = 2, GW = 128 * S, GH = 64 * S, PITCH = 4, FIT = 0.84;   // 64x32 LEDs
  function screenDots(m) {
    const P = legacyPose(m, true);
    const connected = P.width > 1.02 || Math.abs(P.tilt) > 0.3;
    const [uo, ui, li, lo] = contours(P, connected, 0.6);
    const up = Math.round((-3.0 * m.upper_lip_raise + 2.4 * m.lip_press) * S);
    const down = Math.round((3.0 * m.lower_lip_depress + 2.2 * m.jaw_open - 3.0 * m.lip_press) * S);
    const cv = layer("geom", GW, GH), g = cv.getContext("2d", {willReadFrequently: true});
    g.clearRect(0, 0, GW, GH);
    // fit: scale down only when a wide-open mouth would leave the panel, and centre it
    let y0 = Infinity, y1 = -Infinity;
    for (const pt of uo) y0 = Math.min(y0, pt[1] + up / S);
    for (const pt of lo) y1 = Math.max(y1, pt[1] + down / S);
    const fit = Math.min(FIT, 64 / Math.max(1, y1 - y0)), mid = (y0 + y1) / 2;
    const poly = (pts, rev, dy, color) => {
      g.fillStyle = color; g.beginPath();
      const all = pts.concat(rev.slice().reverse());
      // a touch smaller than the OLED crop, so strong vowels fit the tablet panel
      all.forEach(([x, y], i) => {
        const px = ((x - 64) * fit + 64) * S, py = ((y + dy / S - mid) * fit + 32) * S;
        if (i) g.lineTo(px, py); else g.moveTo(px, py);
      });
      g.closePath(); g.fill();
    };
    g.globalCompositeOperation = "lighter";
    poly(uo, ui, up, "rgb(255,0,0)");
    poly(li, lo, down, "rgb(0,255,0)");
    g.globalCompositeOperation = "source-over";
    const img = g.getImageData(0, 0, GW, GH).data;
    const tuck = m.lower_lip_tuck;
    const region = (x, y) => {            // 1 upper, 2 lower, 0 none
      if (x < 0 || x >= GW) return 0;
      const center = Math.max(0, 1 - Math.abs(x - CX * S) / (42 * S));
      const yl = Math.round(y + 3.2 * S * fit * tuck * center);   // F/V: the lower lip lifts and tucks
      if (yl >= 0 && yl < GH && img[(yl * GW + x) * 4 + 1] > 127) return 2;
      if (y >= 0 && y < GH && img[(y * GW + x) * 4] > 127) return 1;
      return 0;
    };
    const cols = Math.floor((GW - 1) / PITCH), rows = Math.floor((GH - 2) / PITCH);
    const cell = [];
    for (let r = 0; r < rows; r++) {
      cell.push(new Uint8Array(cols));
      for (let c = 0; c < cols; c++) cell[r][c] = region(c * PITCH + 1, r * PITCH + 2);
    }
    const at = (r, c) => (r < 0 || r >= rows || c < 0 || c >= cols ? 0 : cell[r][c]);
    // per-column extent of each lip, for highlight placement
    const ext = [1, 2].map(k => Array.from({length: cols}, (_, c) => {
      let top = -1, bot = -1;
      for (let r = 0; r < rows; r++) if (cell[r][c] === k) { if (top < 0) top = r; bot = r; }
      return [top, bot];
    }));
    const halfPx = HALF * P.width * S * fit, cxPx = ((CX + P.shift - 64) * fit + 64) * S;
    const dots = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const x = c * PITCH, y = r * PITCH + 1, k = cell[r][c];
      if (!k) { dots.push([x, y, 0, 0]); continue; }
      const xn = (x + 1 - cxPx) / halfPx, ax = Math.abs(xn);
      const [top, bot] = ext[k - 1][c];
      const t = bot > top ? (r - top) / (bot - top) : 0.5;
      let kind = 1, level = 0.94;                     // flat LED fill, like the OLED
      const rim = k === 1 ? at(r - 1, c) === 0 : at(r + 1, c) === 0;
      const side = at(r, c - 1) === 0 || at(r, c + 1) === 0;
      const part = k === 1 ? at(r + 1, c) !== 1 : at(r - 1, c) !== 2;
      if (rim || side) level = 0.80;                // a quiet lip line
      if (part) level = 0.62;
      if (!rim && !side && !part) {
        if (k === 2 && t > 0.20 && t < 0.36 && ax > 0.16 && ax < 0.36) { kind = 3; level = 1; }          // one small gloss mark
      }
      dots.push([x, y, kind, level]);
    }
    return {cols: GW, rows: GH, pitch: PITCH, cell: 2, dots};
  }

  // ---- "oled": the exact flashed frames ---------------------------------------------------
  let BITS = null;
  function frameBits(i) {
    const bank = root.MOUTH_BANK;
    if (!bank) throw new Error("the oled profile needs mouth_frames.js");
    if (!BITS) BITS = bank.frames.map(b64 => { const s = atob(b64), a = new Uint8Array(s.length); for (let j = 0; j < s.length; j++) a[j] = s.charCodeAt(j); return a; });
    return BITS[Math.max(0, Math.min(BITS.length - 1, i))];
  }
  function oledDots(frame) {
    const bits = frameBits(frame), dots = [];
    for (let y = 0; y < 64; y++) for (let x = 0; x < 128; x++) {
      const on = (bits[y * 16 + (x >> 3)] >> (7 - (x & 7))) & 1;
      if (on) dots.push([x, y, 1, 1]);
      else if (x % 3 !== 2 && y % 3 !== 0) dots.push([x, y, 0, 0]);      // the 2x2 cell grid, unlit
    }
    return {cols: 128, rows: 64, pitch: 1, cell: 1, dots};
  }

  // ---- drawing -------------------------------------------------------------------------
  function resolve(state) {
    if (state && state.__mouth) return state;
    if (state && state.jaw_open != null && state.upper_lip_raise != null) {   // a muscle pose
      const m = constrain(state);
      return {__mouth: true, muscle: m, frame: nearestFrame(m), label: state.label || ""};
    }
    const m = muscleFromArticulation(state || REST);
    return {__mouth: true, muscle: m, frame: nearestFrame(m), label: ""};
  }
  function draw(ctx, x0, y0, width, state, opts) {
    opts = opts || {};
    const pal = (opts.palette && typeof opts.palette === "object") ? opts.palette : (PALETTES[opts.palette] || PALETTES.red);
    const st = resolve(state);
    const prof = opts.profile === "oled" ? "oled" : "screen";
    const grid = prof === "oled" ? oledDots(st.frame) : screenDots(st.muscle);
    const W = Math.max(2, Math.round(width)), H = Math.max(1, Math.round(width / 2));
    const u = W / grid.cols;
    // the oled frame has its own gutters; the screen grid draws cells with a gap
    const size = prof === "oled" ? u * 0.9 : u * grid.pitch * 0.74;
    const flick = 0.94 + 0.06 * Math.sin((opts.t || 0) / 41);
    const off = prof === "oled" ? (x) => x * u : (x) => x * u;
    const base = layer("base:" + prof + pal.off + "|" + W, W, H);
    if (base._fresh) {
      const b = base.getContext("2d");
      b.fillStyle = `rgba(${pal.off},.07)`;
      const all = prof === "oled" ? oledDots(REST_FRAME).dots : grid.dots;
      for (const d of all) if (prof !== "oled" || true) b.fillRect(off(d[0]), off(d[1]), size, size);
      b.fillStyle = "rgba(0,0,0,.16)";
      const step = Math.max(2, u * (prof === "oled" ? 1.5 : 2.4));
      for (let yy = 0; yy < H; yy += step) b.fillRect(0, yy, W, Math.max(1, step * .35));
      base._fresh = false;
    }
    const lit = layer("lit", W, H), lc = lit.getContext("2d");
    lc.clearRect(0, 0, W, H);
    const buckets = new Map();
    for (const d of grid.dots) {
      if (!d[2]) continue;
      const b = Math.round(Math.min(1, d[3]) * 16);
      if (!buckets.has(b)) buckets.set(b, []);
      buckets.get(b).push(d);
    }
    for (const [b, list] of buckets) {
      lc.fillStyle = `rgba(${pal.glow},${(0.08 + 0.92 * b / 16) * flick})`;
      for (const d of list) lc.fillRect(off(d[0]), off(d[1]), size, size);
    }
    for (const [b, list] of buckets) {                    // hot cores: bright cells glow toward white
      const l = b / 16;
      for (const d of list) {
        const a = d[2] === 3 ? 0.45 : (prof === "oled" ? 0.22 : 0);
        if (a <= 0.03) continue;
        lc.fillStyle = `rgba(${pal.core},${a * flick})`;
        const s = size * (d[2] === 3 ? 0.78 : 0.6), ins = (size - s) / 2;
        lc.fillRect(off(d[0]) + ins, off(d[1]) + ins, s, s);
      }
    }
    let src = lit, sw = W, sh = H;                         // bloom: shrink by halves, re-expand
    for (let i = 1; i <= 4; i++) {
      const nw = Math.max(4, Math.round(sw / 2)), nh = Math.max(2, Math.round(sh / 2));
      const c = layer("bloom" + i, nw, nh), cc = c.getContext("2d");
      cc.clearRect(0, 0, nw, nh); cc.imageSmoothingEnabled = true; cc.drawImage(src, 0, 0, nw, nh);
      src = c; sw = nw; sh = nh;
    }
    ctx.save();
    ctx.drawImage(base, x0, y0);
    ctx.globalCompositeOperation = "lighter";
    ctx.imageSmoothingEnabled = true;
    ctx.globalAlpha = 0.6; ctx.drawImage(src, x0, y0, W, H);
    ctx.globalAlpha = 1; ctx.drawImage(lit, x0, y0);
    ctx.restore();
  }

  // ---- timeline: blended muscle poses (screen) and one frame per event (oled) ----------
  const CLOSE = new Set(["PRESS", "FV", "ZH_BPM", "ZH_F"]);
  const LIP = new Set(["ROUND_OW", "PUCKER_UW", "RHOTIC_ER", "SIDE_SH", "ES_ROUND_O", "ES_PUCKER_U", "ES_BH", "ES_CH", "ZH_RETROFLEX",
    "ZH_IR", "ZH_ER", "ZH_O", "ZH_U", "ZH_V", "ZH_OU", "ZH_AO", "EN_SH", "EN_LAX_U", "EN_OW", "EN_AW"]);
  const TONGUE = new Set(["SOFT", "TH", "SIDE_L", "ES_ALVEOLAR", "ZH_APICAL", "ZH_VELAR", "ZH_N", "ZH_NG", "EN_L"]);
  const SIB = new Set(["ZH_PALATAL", "ZH_DENTAL", "ZH_IZ", "EN_S"]);
  const JAW = new Set(["jaw_open", "lip_separation", "lower_lip_depress"]);
  // [lip strength, jaw strength]: JALI (Edwards et al. 2016) — tongue-only consonants move
  // the jaw but leave the lip shape to the neighbouring vowels; rounded sounds lead early.
  const STRENGTH = {vowel: [1, 1], lip: [1.6, 1], close: [1, 1], tongue: [0.2, 0.9], sib: [0.6, 1.1]};
  const cls = v => (CLOSE.has(v) ? "close" : LIP.has(v) ? "lip" : TONGUE.has(v) ? "tongue" : SIB.has(v) ? "sib" : "vowel");
  const smooth = p => p * p * (3 - 2 * p);
  function mixMuscle(a, b, p) { const o = {}; for (const c of CH) o[c] = a[c] * (1 - p) + b[c] * p; return o; }

  function track(events) {
    const keys = events.map(e => {
      const glide = (MODEL.glides || MODEL.zhGlides)[e.viseme];
      const target = targetFor(e.viseme) || muscleFromArticulation(e.articulation);
      const k = cls(e.viseme);
      const fixed = e.metadata && Number.isInteger(e.metadata.oled_frame) ? e.metadata.oled_frame : null;
      // stronger, longer syllables open further than weak ones (per-character variety)
      const g = clamp(0.80 + 1.5 * ((e.intensity == null ? 0.84 : e.intensity) - 0.70), 0.80, 1.25);
      const t2 = Object.assign({}, target);
      for (const c of ["jaw_open", "lip_separation", "lower_lip_depress"]) t2[c] = clamp(target[c] * g);
      return {s: e.start_ms, e: e.start_ms + e.duration_ms, d: e.duration_ms, v: e.viseme, target: t2, k,
        glide: glide ? [lookup(glide[0]), lookup(glide[1])] : null,
        lead: (k === "close" || k === "lip") ? 105 : 75, trail: k === "close" ? 60 : 85,
        frame: fixed != null ? fixed : nearestFrame(muscleFromArticulation(e.articulation))};
    });
    const rest = MODEL.targets.REST;
    // Each target peaks at the middle of its event and hands over quickly to the
    // next (flat-topped dominance, Cohen & Massaro), so every syllable reaches its
    // own shape instead of averaging with its neighbours.
    for (const q of keys) {
      q.c = q.s + q.d * 0.5;
      q.sig = Math.max(q.k === "close" ? 30 : 38, q.d * (q.k === "lip" ? 0.55 : 0.45));
    }
    return function at(t) {
      const lipSum = {}, jawSum = {};
      const r0 = 0.04;
      for (const c of CH) { lipSum[c] = r0 * rest[c]; jawSum[c] = r0 * rest[c]; }
      let wl = r0, wj = r0, lock = null;
      for (const q of keys) {
        const z = Math.abs(t - q.c) / q.sig;
        if (z > 3) continue;
        const w = Math.exp(-Math.pow(z, 4));
        let tm = q.target;
        if (q.glide) tm = mixMuscle(q.glide[0], q.glide[1], smooth(clamp(((t - q.s) / Math.max(1, q.d) - 0.25) / 0.6)));
        const [sl, sj] = STRENGTH[q.k];
        for (const c of CH) { if (JAW.has(c)) jawSum[c] += w * sj * tm[c]; else lipSum[c] += w * sl * tm[c]; }
        wl += w * sl; wj += w * sj;
        if (q.k === "close" && Math.abs(t - q.c) <= q.d * 0.4) lock = tm;
      }
      // silence: drift back to rest between phrases
      const first = keys.length ? keys[0].s : 0, last = keys.length ? keys[keys.length - 1].e : 0;
      const gapW = keys.every(q => Math.abs(t - q.c) > q.sig * 1.6) ? 1 : 0;
      if (gapW || t < first - 60 || t > last + 60) { for (const c of CH) { lipSum[c] += 2 * rest[c]; jawSum[c] += 2 * rest[c]; } wl += 2; wj += 2; }
      let m = {};
      for (const c of CH) m[c] = JAW.has(c) ? jawSum[c] / wj : lipSum[c] / wl;
      if (lock) m = mixMuscle(m, lock, 0.85);              // a closure is categorical, never averaged away
      m = constrain(m);
      // oled: like the board, one frame per event, short gaps hold the previous frame
      let i = -1;
      for (let j = 0; j < keys.length; j++) { if (keys[j].s <= t) i = j; else break; }
      let frame = REST_FRAME, label = "REST";
      if (i >= 0) {
        const q = keys[i], next = keys[i + 1];
        const hold = next && next.s >= q.e && next.s - q.e <= 90;
        if (t < q.e || hold) { frame = q.frame; label = q.v; }
      }
      return {__mouth: true, muscle: m, frame, label};
    };
  }

  // Kept for pages that still step a plain articulation timeline.
  function targetAt(events, ms) {
    let hit = null;
    for (const e of events) {
      if (e.start_ms <= ms) { if (ms < e.start_ms + e.duration_ms + 60) hit = e; }
      else break;
    }
    return hit ? hit.articulation : REST;
  }
  function makeSmoother() {
    const s = Object.assign({}, REST);
    return function (target, dtMs) {
      for (const k of KEYS) {
        const tau = (k === "lip_press" || k === "lip_separation") ? 34 : 52;
        s[k] += (av(target, k) - s[k]) * (1 - Math.exp(-dtMs / tau));
      }
      return s;
    };
  }

  root.DotLips = {REST, PALETTES, PROFILES: ["screen", "oled"], MODEL, draw, track, targetAt, makeSmoother,
    muscleFromArticulation, nearestFrame, targetFor, constrain, outline};
})(typeof window !== "undefined" ? window : globalThis);

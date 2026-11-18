// Asset foundry, step 1: render the 3D models of a manifest to transparent PNGs.
//
//   node render.mjs --manifest manifest.json --models <dir> --out <dir> [--only id,id]
//
// Each manifest entry is checked against the licence gate first
// (licences.mjs); a refused entry is reported and skipped, never rendered. An
// accepted one gets its verdict written next to its PNG (<id>.gate.json).
// Two looks:
//   - "sticker": the story stage's cartoon style. Toon shading in three flat
//     bands, colours mapped to the house palette, a thin inner outline in the
//     stage's outline colour (#3b2418). postprocess.py adds the thick
//     silhouette stroke.
//   - "closeup": a soft-lit, realistic render of chosen parts of a model (a
//     "Look closely" picture of an educational object), 960 px.
// Rendering runs in headless Chromium (software WebGL, no GPU needed).
// See README.md and docs/story-mode-3d-assets.md.

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { parseArgs } from "node:util";

import { gate } from "./licences.mjs";

const require = createRequire(import.meta.url);

function loadPlaywright() {
  // A machine with Playwright installed elsewhere (and its browser) can point
  // PLAYWRIGHT_MODULE at that copy instead of installing a second one.
  const spec = process.env.PLAYWRIGHT_MODULE || "playwright";
  return require(spec);
}

const { values: args } = parseArgs({
  options: {
    manifest: { type: "string" },
    models: { type: "string" },
    out: { type: "string" },
    only: { type: "string" },
  },
});
if (!args.manifest || !args.models || !args.out) {
  console.error("usage: node render.mjs --manifest manifest.json --models <dir> --out <dir> [--only id,id]");
  process.exit(2);
}

const manifest = JSON.parse(fs.readFileSync(args.manifest, "utf8"));
const only = args.only ? new Set(args.only.split(",")) : null;
const entries = (manifest.entries ?? []).filter((entry) => !only || only.has(entry.id));
const modelsRoot = path.resolve(args.models);
const rawDir = path.join(path.resolve(args.out), "raw");
fs.mkdirSync(rawDir, { recursive: true });
// three.js exports no package.json: its folder is the parent of build/.
const threeDir = path.resolve(path.dirname(require.resolve("three")), "..");

const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script>
</head><body style="margin:0;background:transparent">
<script type="module">
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { OutlineEffect } from "three/addons/effects/OutlineEffect.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);

// -- Sticker look -------------------------------------------------------------
const bands = new Uint8Array([120, 200, 255]);
const gradientMap = new THREE.DataTexture(bands, bands.length, 1, THREE.RedFormat);
gradientMap.minFilter = gradientMap.magFilter = THREE.NearestFilter;
gradientMap.needsUpdate = true;
// The stage's outline colour, in the linear space the outline shader expects.
const OUTLINE = new THREE.Color(0x3b2418).toArray();
const outline = new OutlineEffect(renderer, { defaultThickness: 0.007, defaultColor: OUTLINE, defaultAlpha: 1 });

// The house palette (story_art_service.STYLE_LINE: ochre, terracotta, golden
// yellow, leaf green, sky blue) widened with the neutrals a scene needs.
const PALETTE = {
  ochre: 0xcc8a2e, terracotta: 0xc8643c, laterite: 0xd6783e, golden: 0xf2b632,
  leaf: 0x5aa83c, leafDark: 0x3f7f34, sky: 0x7fc8f0, wood: 0x9a5b30, woodLight: 0xd9a066,
  stone: 0xa59a8e, cream: 0xf6e7c8, red: 0xd2452e, dark: 0x4a3426, white: 0xfaf3e6,
};
// Kenney and Quaternius name their materials by what they are.
const BY_NAME = [
  [/leaf|leaves|grass|foliage|green/i, "leaf"], [/bark|trunk|wood|log|plank/i, "wood"],
  [/inner|cut|light ?wood/i, "woodLight"], [/stone|rock/i, "stone"], [/dirt|soil|ground|sand/i, "laterite"],
  [/water|sky|blue/i, "sky"], [/metal|iron|steel/i, "stone"], [/black|dark|tire|rubber/i, "dark"],
];
const palette = Object.fromEntries(Object.entries(PALETTE).map(([k, v]) => [k, new THREE.Color(v)]));
function houseColour(name, color) {
  for (const [re, key] of BY_NAME) if (re.test(name || "")) return palette[key].clone();
  let best = null, bestD = Infinity;
  const a = color.clone().convertLinearToSRGB();
  for (const c of Object.values(palette)) {
    const b = c.clone().convertLinearToSRGB();
    const d = 2 * (a.r - b.r) ** 2 + 4 * (a.g - b.g) ** 2 + 3 * (a.b - b.b) ** 2;
    if (d < bestD) (bestD = d), (best = c);
  }
  return color.clone().lerp(best, 0.7);
}
function toon(material, snap) {
  const base = (material.color ?? new THREE.Color(1, 1, 1)).clone();
  // A textured material keeps its texture, warmed a little.
  const color = material.map || !snap ? base.lerp(new THREE.Color(0xffe2b8), 0.08) : houseColour(material.name, base);
  return new THREE.MeshToonMaterial({
    color, map: material.map ?? null, gradientMap, vertexColors: !!material.vertexColors,
    transparent: !!material.transparent, alphaTest: material.alphaTest ?? 0, side: material.side ?? THREE.FrontSide,
  });
}

function frame(object, fovDeg, lift, margin) {
  const sphere = new THREE.Box3().setFromObject(object).getBoundingSphere(new THREE.Sphere());
  const camera = new THREE.PerspectiveCamera(fovDeg, 1, 0.001, 1000);
  const dist = (sphere.radius / Math.sin(THREE.MathUtils.degToRad(fovDeg / 2))) * margin;
  camera.position.copy(sphere.center).add(new THREE.Vector3(0, lift, 1).normalize().multiplyScalar(dist));
  camera.lookAt(sphere.center);
  return camera;
}

window.renderSticker = async (url, yaw, snap) => {
  renderer.setSize(768, 768);
  renderer.toneMapping = THREE.NoToneMapping;
  const root = (await loader.loadAsync(url)).scene;
  root.traverse((o) => {
    if (o.isMesh) o.material = Array.isArray(o.material) ? o.material.map((m) => toon(m, snap)) : toon(o.material, snap);
  });
  root.rotation.y = yaw; // a 3/4 front view
  const scene = new THREE.Scene();
  scene.add(root, new THREE.HemisphereLight(0xfff4e0, 0xb86b3c, 1.6));
  const sun = new THREE.DirectionalLight(0xfff1d6, 2.4);
  sun.position.set(-2, 4, 3);
  scene.add(sun);
  outline.render(scene, frame(root, 28, 0.35, 1.08));
  return renderer.domElement.toDataURL("image/png");
};

// -- Close-up look ------------------------------------------------------------
window.renderCloseup = async (url, yaw, nodes, colors) => {
  renderer.setSize(960, 960); // PropPicture.src_large: at most 960 px
  renderer.toneMapping = THREE.NeutralToneMapping;
  const root = (await loader.loadAsync(url)).scene;
  root.updateMatrixWorld(true);
  const shown = new THREE.Group();
  const keep = nodes && nodes.length ? nodes.map((n) => root.getObjectByName(n)) : [root];
  if (keep.some((n) => !n)) throw new Error("missing node: " + nodes.filter((n, i) => !keep[i]).join(", "));
  keep.forEach((node, i) => node.traverse((o) => {
    if (!o.isMesh) return;
    const hex = nodes && nodes.length ? colors[nodes[i]] : null;
    const material = new THREE.MeshPhysicalMaterial({
      color: hex ? new THREE.Color(hex) : o.material.color, map: hex ? null : o.material.map ?? null,
      roughness: 0.45, clearcoat: 0.3, clearcoatRoughness: 0.4,
    });
    const mesh = new THREE.Mesh(o.geometry, material);
    mesh.applyMatrix4(o.matrixWorld);
    shown.add(mesh);
  }));
  shown.rotation.y = yaw;
  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(-1, 2, 2);
  scene.add(shown, key);
  renderer.render(scene, frame(shown, 26, 0.15, 1.05));
  return renderer.domElement.toDataURL("image/png");
};
window.ready = true;
</script></body></html>`;

// Only the page, three.js and the manifest's own model files are served.
const files = new Map(entries.map((entry) => [`/models/${entry.id}.glb`, path.resolve(modelsRoot, entry.file ?? "")]));
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split("?")[0]);
  if (url === "/") return res.end(PAGE);
  let file = files.get(url);
  if (!file && url.startsWith("/three/")) {
    file = path.resolve(threeDir, url.slice("/three/".length));
    if (!file.startsWith(threeDir + path.sep)) file = undefined;
  }
  if (!file || !fs.existsSync(file)) return (res.statusCode = 404), res.end();
  res.setHeader("content-type", file.endsWith(".js") ? "text/javascript" : "model/gltf-binary");
  fs.createReadStream(file).pipe(res);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage();
page.on("pageerror", (error) => console.error("page error:", error.message));
await page.goto(`http://127.0.0.1:${server.address().port}/`);
await page.waitForFunction(() => window.ready === true, null, { timeout: 30000 });

let failed = 0;
for (const entry of entries) {
  const verdict = gate(entry);
  if (!verdict.ok) {
    console.log(`refused ${entry.id}: ${verdict.reason}`);
    continue;
  }
  const modelFile = files.get(`/models/${entry.id}.glb`);
  if (!entry.file || !modelFile.startsWith(modelsRoot + path.sep) || !fs.existsSync(modelFile)) {
    console.log(`missing ${entry.id}: ${entry.file}`);
    failed += 1;
    continue;
  }
  try {
    const started = Date.now();
    const url = `/models/${entry.id}.glb`;
    const data =
      entry.kind === "closeup"
        ? await page.evaluate(([u, y, n, c]) => window.renderCloseup(u, y, n, c), [url, entry.yaw ?? 0, entry.nodes ?? [], entry.colors ?? {}])
        : await page.evaluate(([u, y, s]) => window.renderSticker(u, y, s), [url, entry.yaw ?? 0.6, entry.palette !== false]);
    fs.writeFileSync(path.join(rawDir, `${entry.id}.png`), Buffer.from(data.split(",")[1], "base64"));
    // postprocess.py publishes only what carries this verdict: one gate, here.
    fs.writeFileSync(path.join(rawDir, `${entry.id}.gate.json`), JSON.stringify(verdict));
    console.log(`ok ${entry.kind} ${entry.id} ${Date.now() - started}ms`);
  } catch (error) {
    console.log(`fail ${entry.id}: ${String(error.message).split("\n")[0]}`);
    failed += 1;
  }
}
await browser.close();
server.close();
process.exit(failed ? 1 : 0);

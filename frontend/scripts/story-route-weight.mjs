#!/usr/bin/env node
/**
 * Weight of the two story routes after a production build (#2738).
 *
 *   npm run build && npm run story:weight
 *
 * For each route it adds up, gzipped (level 9, close to what a CDN sends), the
 * JS a first view needs: the framework files every page loads (build-manifest
 * rootMainFiles and polyfills), the route's layout and page chunks, and the
 * chunks its client components reference. Chunks that only load on demand
 * (`import()`) are not in that list: they are shown on their own line.
 *
 * "Player chunk(s)" are the chunks holding the story player, found by a string
 * only the player renders (PLAYER_MARKER). With the player imported statically
 * they are part of the first view; once it is lazy they are listed apart.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { gzipSync } from "node:zlib";

const NEXT = join(process.cwd(), ".next");
const CHUNKS = join(NEXT, "static", "chunks");
const PLAYER_MARKER = "story-controls-bar";

const ROUTES = [
  { name: "modules/[moduleId]/story", app: "[locale]/(app)/modules/[moduleId]/story" },
  { name: "story/[slug]", app: "[locale]/(app)/story/[slug]" },
];

const gz = (file) => gzipSync(readFileSync(join(NEXT, file)), { level: 9 }).length;
const kb = (n) => (n / 1024).toFixed(1);

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

if (!existsSync(CHUNKS)) {
  console.error("No .next build here: run `npm run build` first.");
  process.exit(1);
}

const build = JSON.parse(readFileSync(join(NEXT, "build-manifest.json"), "utf8"));
const common = [...build.polyfillFiles, ...build.rootMainFiles].map((f) => `static/${f.replace(/^static\//, "")}`);
const allChunks = walk(CHUNKS).filter((f) => f.endsWith(".js")).map((f) => `static/chunks/${relative(CHUNKS, f)}`);
const playerChunks = allChunks.filter((f) => readFileSync(join(NEXT, f), "utf8").includes(PLAYER_MARKER));

function routeChunks(app) {
  const set = new Set(common);
  // Layout and page chunks on the way down to the route.
  const parts = app.split("/");
  for (let i = 0; i <= parts.length; i += 1) {
    const dir = join(CHUNKS, "app", ...parts.slice(0, i));
    if (!existsSync(dir)) continue;
    for (const name of readdirSync(dir)) {
      if (/^(layout|page|error|loading|not-found)-.*\.js$/.test(name)) {
        set.add(`static/chunks/${relative(CHUNKS, join(dir, name))}`);
      }
    }
  }
  // Chunks the route's client components reference.
  const manifest = readFileSync(
    join(NEXT, "server", "app", ...parts, "page_client-reference-manifest.js"),
    "utf8",
  );
  for (const m of manifest.matchAll(/"(static\/chunks\/[^"]+\.js)"/g)) set.add(decodeURIComponent(m[1]));
  return [...set];
}

console.log("| Route | First-view JS (gzip KB) | Player in first view | Player chunk(s) (gzip KB) |");
console.log("| --- | ---: | :---: | ---: |");
for (const { name, app } of ROUTES) {
  const chunks = routeChunks(app);
  const total = chunks.reduce((sum, f) => sum + gz(f), 0);
  const inView = playerChunks.filter((f) => chunks.includes(f));
  const playerSize = playerChunks.reduce((sum, f) => sum + gz(f), 0);
  console.log(
    `| ${name} | ${kb(total)} | ${inView.length ? "yes" : "no"} | ${kb(playerSize)} (${playerChunks.length}) |`,
  );
}
console.log(`\nPlayer chunks: ${playerChunks.join(", ") || "none found"}`);

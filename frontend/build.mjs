// Builds the React dashboard into dist/ (served by the FastAPI backend at http://127.0.0.1:8000).
import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";

const watch = process.argv.includes("--watch");
mkdirSync("dist/assets", { recursive: true });
copyFileSync("index.html", "dist/index.html");
const options = {
  entryPoints: { app: "src/main.jsx" },
  bundle: true,
  minify: !watch,
  sourcemap: watch,
  outdir: "dist/assets",
  jsx: "automatic",
  loader: { ".js": "jsx" },
  define: { "process.env.NODE_ENV": watch ? '"development"' : '"production"' },
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(":") : [],
  logLevel: "info",
};
if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("Watching src/ - reload the browser after changes.");
} else {
  await esbuild.build(options);
}

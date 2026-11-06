import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, "dist");
const apiBaseUrl = String(process.env.TASKVAULT_API_BASE_URL || "").trim().replace(/\/+$/, "");

if (apiBaseUrl) {
  const parsed = new URL(apiBaseUrl);
  const isLocal = ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !(isLocal && parsed.protocol === "http:")) {
    throw new Error("TASKVAULT_API_BASE_URL must use HTTPS outside local development.");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("TASKVAULT_API_BASE_URL must be an origin or path without credentials, query, or fragment.");
  }
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const file of ["index.html", "app.js", "styles.css"]) {
  await cp(path.join(root, file), path.join(output, file));
}
await cp(path.join(root, "assets"), path.join(output, "assets"), { recursive: true });
if (apiBaseUrl) {
  const apiOrigin = new URL(apiBaseUrl).origin;
  const policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
    `img-src 'self' data:; connect-src 'self' ${apiOrigin}; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`;
  const indexPath = path.join(output, "index.html");
  const html = await readFile(indexPath, "utf8");
  await writeFile(indexPath, html.replace("</head>", `  <meta http-equiv="Content-Security-Policy" content="${policy}">\n</head>`), "utf8");
}
await writeFile(
  path.join(output, "config.js"),
  `window.TASKVAULT_API_BASE_URL = ${JSON.stringify(apiBaseUrl)};\n`,
  "utf8",
);

console.log(`Built static frontend in dist/ (API: ${apiBaseUrl || "same origin"}).`);

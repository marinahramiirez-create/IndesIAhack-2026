// Agentic OS · servidor local del dashboard (sin dependencias)
// Ejecuta: node dashboard/server.js   y abre http://localhost:4747
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.env.PORT) || 4747;
const P = {
  map: path.join(ROOT, "os_map.json"),
  mcp: path.join(ROOT, ".mcp.json"),
  areas: path.join(ROOT, "areas"),
  skills: path.join(ROOT, ".claude", "skills"),
  agents: path.join(ROOT, ".claude", "agents"),
  trash: path.join(ROOT, "_papelera"),
  html: path.join(__dirname, "index.html"),
};
const ID_RE = /^[a-z0-9][a-z0-9_-]{0,48}$/;

const readJSON = (f, d) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return d; } };
const writeJSON = (f, o) => fs.writeFileSync(f, JSON.stringify(o, null, 2) + "\n", "utf8");
const readText = (f) => { try { return fs.readFileSync(f, "utf8"); } catch { return ""; } };

function loadMap() {
  const m = readJSON(P.map, {});
  m.areas ||= {}; m.conectores ||= {}; m.links ||= {};
  return m;
}

function frontmatter(txt) {
  const out = {};
  const m = txt.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) return out;
  for (const line of m[1].split(/\r?\n/)) {
    const i = line.indexOf(":");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}
function setFrontmatterField(txt, key, value) {
  const clean = String(value).replace(/\r?\n/g, " ").trim();
  const m = txt.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) return `---\n${key}: ${clean}\n---\n\n${txt}`;
  let body = m[1];
  const re = new RegExp(`^${key}:.*$`, "m");
  body = re.test(body) ? body.replace(re, `${key}: ${clean}`) : body + `\n${key}: ${clean}`;
  return txt.replace(m[0], `---\n${body}\n---`);
}

function countTasks(file) {
  const t = readText(file);
  return {
    pendientes: (t.match(/\[ \]/g) || []).length,
    hechos: (t.match(/\[[xX]\]/g) || []).length,
  };
}

function fileFor(key) {
  const [type, id] = key.split(":");
  if (!ID_RE.test(id || "")) return null;
  if (type === "area") return path.join(P.areas, id, "CLAUDE.md");
  if (type === "skill") return path.join(P.skills, id, "SKILL.md");
  if (type === "agent") return path.join(P.agents, id + ".md");
  if (type === "tasks") return path.join(P.areas, id, "pendientes.md");
  if (type === "project") { const p = listProjects().find((x) => x.id === id); return p ? path.join(ROOT, p.ruta) : null; }
  return null;
}

// Proyectos: notas con "tipo: proyecto" dentro de areas/ (hasta 3 niveles).
// Su área principal es la carpeta donde viven; "areas_relacionadas" y "conectores" (listas [a, b]) añaden más enlaces.
const listField = (v) => String(v || "").replace(/^\[|\]$/g, "").split(",").map((s) => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
const slugify = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "proyecto";
function listProjects() {
  const out = [];
  const walk = (dir, depth) => {
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const f = path.join(dir, e.name);
      if (e.isDirectory() && depth < 3) walk(f, depth + 1);
      else if (e.isFile() && e.name.endsWith(".md") && e.name !== "CLAUDE.md" && e.name !== "pendientes.md") {
        const fm = frontmatter(readText(f));
        if (fm.tipo !== "proyecto") continue;
        const rel = path.relative(P.areas, f).split(path.sep);
        let id = slugify(e.name.slice(0, -3));
        while (out.some((p) => p.id === id)) id += "-2";
        const areas = [rel[0], ...listField(fm.areas_relacionadas)].filter((a, i, arr) => ID_RE.test(a) && arr.indexOf(a) === i);
        out.push({ key: `project:${id}`, id, tipo: "project", nombre: e.name.slice(0, -3), descripcion: fm.resumen || "", estado: fm.estado || "", area: rel[0], areas, conectores: listField(fm.conectores), ruta: path.relative(ROOT, f) });
      }
    }
  };
  walk(P.areas, 0);
  return out;
}

function state() {
  const map = loadMap();
  const listDirs = (d) => { try { return fs.readdirSync(d, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name); } catch { return []; } };
  const areas = listDirs(P.areas).filter((id) => ID_RE.test(id)).map((id) => {
    const meta = map.areas[id] || {};
    const txt = readText(path.join(P.areas, id, "CLAUDE.md"));
    const desc = meta.descripcion || (txt.match(/^>\s*(.+)$/m) || [])[1] || "";
    return { key: `area:${id}`, id, tipo: "area", nombre: meta.nombre || id, descripcion: desc, color: meta.color || "#607D8B", ...countTasks(path.join(P.areas, id, "pendientes.md")) };
  });
  const skills = listDirs(P.skills).filter((id) => ID_RE.test(id)).map((id) => {
    const fm = frontmatter(readText(path.join(P.skills, id, "SKILL.md")));
    return { key: `skill:${id}`, id, tipo: "skill", nombre: fm.name || id, descripcion: fm.description || "" };
  });
  let agents = [];
  try {
    agents = fs.readdirSync(P.agents).filter((f) => f.endsWith(".md")).map((f) => f.slice(0, -3)).filter((id) => ID_RE.test(id)).map((id) => {
      const fm = frontmatter(readText(path.join(P.agents, id + ".md")));
      return { key: `agent:${id}`, id, tipo: "agent", nombre: fm.name || id, descripcion: fm.description || "" };
    });
  } catch {}
  const mcp = readJSON(P.mcp, { mcpServers: {} });
  const connIds = new Set([...Object.keys(map.conectores), ...Object.keys(mcp.mcpServers || {})]);
  const connectors = [...connIds].map((id) => {
    const meta = map.conectores[id] || {};
    const local = (mcp.mcpServers || {})[id];
    return {
      key: `connector:${id}`, id, tipo: "connector", nombre: meta.nombre || id,
      descripcion: meta.descripcion || (local ? "Servidor MCP definido en .mcp.json" : ""),
      origen: local ? "local (.mcp.json)" : (meta.origen || "claude.ai"),
      config: local || null,
    };
  });
  const links = {};
  for (const n of [...skills, ...agents, ...connectors]) {
    const l = map.links[n.key] || {};
    links[n.key] = { areas: (l.areas || []).filter((a) => areas.some((x) => x.id === a)), conectores: (l.conectores || []).filter((c) => connIds.has(c)) };
  }
  const projects = listProjects().filter((p) => areas.some((x) => x.id === p.area));
  for (const p of projects) links[p.key] = { areas: p.areas.filter((a) => areas.some((x) => x.id === a)), conectores: p.conectores.filter((c) => connIds.has(c)) };
  return { raiz: ROOT, areas, skills, agents, connectors, projects, links };
}

// ---------- plantillas ----------
const tpl = {
  area: (b) => `# ${b.nombre}\n\n> ${b.descripcion || ""}\n\n## Contexto\n${b.contenido || "Describe aquí el objetivo del área, las personas involucradas y las reglas de trabajo."}\n\n## Cómo trabajar aquí\n* Pendientes en \`pendientes.md\`.\n`,
  tasks: (b) => `# Pendientes · ${b.nombre}\n\n* [ ] Primer paso de ${b.nombre}\n`,
  skill: (b) => `---\nname: ${b.id}\ndescription: ${(b.descripcion || "Describe cuándo usar este skill.").replace(/\r?\n/g, " ")}\n---\n\n# ${b.nombre}\n\n${b.contenido || "1. Paso uno.\n2. Paso dos.\n3. Entrega el resultado a el usuario siguiendo las reglas del CLAUDE.md principal."}\n`,
  agent: (b) => `---\nname: ${b.id}\ndescription: ${(b.descripcion || "Describe cuándo delegar en este agente.").replace(/\r?\n/g, " ")}\n---\n\n${b.contenido || `Eres ${b.nombre}, un especialista del OS del usuario.\n\nTu trabajo:\n1. ...\n\nEscribe en español claro, sin guiones.`}\n`,
};

function create(b) {
  const id = String(b.id || "").toLowerCase();
  if (!ID_RE.test(id)) throw new Error("El id solo admite minúsculas, números, guion y guion bajo.");
  b.id = id; b.nombre ||= id;
  const map = loadMap();
  const key = `${b.tipo}:${id}`;
  if (b.tipo === "area") {
    const dir = path.join(P.areas, id);
    if (fs.existsSync(dir)) throw new Error("Ya existe un área con ese id.");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "CLAUDE.md"), tpl.area(b));
    fs.writeFileSync(path.join(dir, "pendientes.md"), tpl.tasks(b));
    const hub = String(b.nombre).replace(/[\\/:*?"<>|]/g, "").trim() || id;
    fs.writeFileSync(path.join(dir, hub + ".md"), `---\ntipo: area\narea_id: ${id}\nestado: activa\nprioridad: media\ntags: [area]\n---\n\n# ${hub}\n\n${b.descripcion || ""}\n\nVuelve al [[Inicio]].\n\n## Personas\n\n## Relacionado\n\n## Pendientes\n![[areas/${id}/pendientes]]\n\n## Contexto para Claude\n[[areas/${id}/CLAUDE|Abrir el contexto completo del área]]\n`);
    try { const ini = path.join(ROOT, "Inicio.md"); let t = readText(ini); if (t && !t.includes(`[[${hub}]]`)) { t = t.replace(/(## Áreas\n(?:\* .*\n)*)/, `$1* [[${hub}]]\n`); fs.writeFileSync(ini, t); } } catch {}
    map.areas[id] = { nombre: b.nombre, descripcion: b.descripcion || "", color: b.color || "#607D8B" };
  } else if (b.tipo === "skill") {
    const dir = path.join(P.skills, id);
    if (fs.existsSync(dir)) throw new Error("Ya existe un skill con ese id.");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "SKILL.md"), tpl.skill(b));
  } else if (b.tipo === "agent") {
    fs.mkdirSync(P.agents, { recursive: true });
    const f = path.join(P.agents, id + ".md");
    if (fs.existsSync(f)) throw new Error("Ya existe un agente con ese id.");
    fs.writeFileSync(f, tpl.agent(b));
  } else if (b.tipo === "connector") {
    if (map.conectores[id]) throw new Error("Ya existe un conector con ese id.");
    map.conectores[id] = { nombre: b.nombre, origen: b.origen || "claude.ai", descripcion: b.descripcion || "" };
    if (b.origen === "local") {
      const mcp = readJSON(P.mcp, { mcpServers: {} });
      mcp.mcpServers ||= {};
      if (b.url) mcp.mcpServers[id] = { type: "http", url: b.url };
      else if (b.comando) {
        const parts = String(b.comando).trim().split(/\s+/);
        mcp.mcpServers[id] = { command: parts[0], args: parts.slice(1) };
      } else throw new Error("Para un conector local indica un comando o una URL.");
      writeJSON(P.mcp, mcp);
    }
  } else throw new Error("Tipo no válido.");
  if (b.tipo !== "area") map.links[key] = { areas: b.areas || [], conectores: b.conectores || [] };
  writeJSON(P.map, map);
  return { ok: true, key };
}

function update(b) {
  const [tipo, id] = String(b.key || "").split(":");
  if (!ID_RE.test(id || "")) throw new Error("Clave no válida.");
  const map = loadMap();
  if (tipo === "area") {
    map.areas[id] ||= {};
    if (b.nombre != null) map.areas[id].nombre = b.nombre;
    if (b.descripcion != null) map.areas[id].descripcion = b.descripcion;
    if (b.color != null) map.areas[id].color = b.color;
  } else {
    if (b.areas || b.conectores) {
      const cur = map.links[b.key] || {};
      map.links[b.key] = { areas: b.areas ?? cur.areas ?? [], conectores: b.conectores ?? cur.conectores ?? [] };
    }
    if (tipo === "connector") {
      map.conectores[id] ||= {};
      if (b.nombre != null) map.conectores[id].nombre = b.nombre;
      if (b.descripcion != null) map.conectores[id].descripcion = b.descripcion;
    } else if (b.descripcion != null) {
      const f = fileFor(b.key);
      fs.writeFileSync(f, setFrontmatterField(readText(f), "description", b.descripcion));
    }
  }
  writeJSON(P.map, map);
  return { ok: true };
}

function remove(b) {
  const [tipo, id] = String(b.key || "").split(":");
  if (!ID_RE.test(id || "")) throw new Error("Clave no válida.");
  const map = loadMap();
  const stamp = new Date().toISOString().replace(/[:.]/g, "").slice(0, 15);
  fs.mkdirSync(P.trash, { recursive: true });
  const toTrash = (src, name) => { if (fs.existsSync(src)) fs.renameSync(src, path.join(P.trash, `${stamp}_${name}`)); };
  if (tipo === "area") {
    toTrash(path.join(P.areas, id), `area_${id}`);
    delete map.areas[id];
    for (const l of Object.values(map.links)) l.areas = (l.areas || []).filter((a) => a !== id);
  } else if (tipo === "skill") toTrash(path.join(P.skills, id), `skill_${id}`);
  else if (tipo === "agent") toTrash(path.join(P.agents, id + ".md"), `agent_${id}.md`);
  else if (tipo === "connector") {
    delete map.conectores[id];
    const mcp = readJSON(P.mcp, { mcpServers: {} });
    if (mcp.mcpServers && mcp.mcpServers[id]) {
      fs.writeFileSync(path.join(P.trash, `${stamp}_connector_${id}.json`), JSON.stringify(mcp.mcpServers[id], null, 2));
      delete mcp.mcpServers[id]; writeJSON(P.mcp, mcp);
    }
    for (const l of Object.values(map.links)) l.conectores = (l.conectores || []).filter((c) => c !== id);
  } else throw new Error("Tipo no válido.");
  delete map.links[b.key];
  writeJSON(P.map, map);
  return { ok: true };
}

// ---------- http ----------
function send(res, code, body, type = "application/json; charset=utf-8") {
  res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}
function readBody(req) {
  return new Promise((ok, ko) => {
    let d = ""; req.on("data", (c) => { d += c; if (d.length > 2e6) req.destroy(); });
    req.on("end", () => { try { ok(d ? JSON.parse(d) : {}); } catch (e) { ko(e); } });
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  try {
    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) return send(res, 200, readText(P.html), "text/html; charset=utf-8");
    if (req.method === "GET" && url.pathname === "/api/state") return send(res, 200, state());
    if (req.method === "GET" && url.pathname === "/api/file") {
      const f = fileFor(url.searchParams.get("key") || "");
      if (!f) return send(res, 400, { error: "Clave no válida." });
      return send(res, 200, { contenido: readText(f), ruta: path.relative(ROOT, f) });
    }
    if (req.method === "POST") {
      if (req.headers["content-type"]?.indexOf("application/json") !== 0) return send(res, 415, { error: "JSON requerido" });
      const b = await readBody(req);
      if (url.pathname === "/api/create") return send(res, 200, create(b));
      if (url.pathname === "/api/update") return send(res, 200, update(b));
      if (url.pathname === "/api/delete") return send(res, 200, remove(b));
      if (url.pathname === "/api/file") {
        const f = fileFor(b.key || "");
        if (!f || !fs.existsSync(path.dirname(f))) return send(res, 400, { error: "Clave no válida." });
        fs.writeFileSync(f, String(b.contenido ?? ""));
        return send(res, 200, { ok: true });
      }
    }
    send(res, 404, { error: "No encontrado" });
  } catch (e) {
    send(res, 400, { error: e.message });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`\n  Agentic OS dashboard listo en http://localhost:${PORT}\n  Carpeta: ${ROOT}\n  Cierra esta ventana para apagarlo.\n`);
});

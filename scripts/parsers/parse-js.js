#!/usr/bin/env node
/**
 * parse-js.js — Smith JS/JSX/TS/TSX parser.
 *
 * Reads a single source file and writes JSON to stdout matching the
 * shape declared in contracts/parser-output.schema.json.
 *
 * Hard constraints (per spec):
 *   - No external deps. acorn + acorn-jsx + acorn-typescript are vendored
 *     in scripts/parsers/vendor/acorn.min.js (single CJS bundle).
 *   - Never crash. On parse errors, emit partial JSON via a regex
 *     fallback and populate `errors`.
 *   - p95 latency < 200ms for files up to ~2000 lines.
 *
 * Usage:
 *   node parse-js.js <path>
 */

"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

// --- Stable method id (v2) -------------------------------------------------
function canonicalParam(p) {
  const name = (p && p.name) || "";
  let typ = p && p.type;
  if (typ === null || typ === undefined || typ === "") typ = "_";
  let def = p && p.default;
  if (def === null || def === undefined || def === "") def = "_";
  return name + ":" + typ + "=" + def;
}

function canonicalSignature(params, returnType) {
  const body = (params || []).map(canonicalParam).join(",");
  const rt =
    returnType === null || returnType === undefined || returnType === ""
      ? "_"
      : returnType;
  return body + "->" + rt;
}

function normalizeModulePath(p) {
  if (!p) return p;
  let s = p.split(path.sep).join("/");
  const cwd = process.cwd().split(path.sep).join("/").replace(/\/$/, "") + "/";
  if (s.startsWith(cwd)) s = s.slice(cwd.length);
  if (s.startsWith("./")) s = s.slice(2);
  return s;
}

function stableMethodId(modulePath, scopeChain, name, params, returnType) {
  const sig = canonicalSignature(params, returnType);
  const canon = modulePath + "::" + scopeChain + "::" + name + "::" + sig;
  return crypto
    .createHash("sha256")
    .update(canon, "utf8")
    .digest("hex")
    .slice(0, 16);
}

// --- Load vendored parsers --------------------------------------------------
let acorn = null;
let acornJsx = null;
let acornTypescript = null;
let VENDOR_LOAD_ERROR = null;
try {
  const vendorPath = path.join(__dirname, "vendor", "acorn.min.js");
  const bundle = require(vendorPath);
  acorn = bundle.acorn;
  acornJsx = bundle.acornJsx;
  acornTypescript = bundle.acornTypescript;
} catch (e) {
  VENDOR_LOAD_ERROR = e;
}

// --- Language detection -----------------------------------------------------
function detectLanguage(filepath) {
  const ext = path.extname(filepath).toLowerCase();
  if (ext === ".ts" || ext === ".tsx") return "typescript";
  return "javascript";
}

function isJsx(filepath) {
  const ext = path.extname(filepath).toLowerCase();
  return ext === ".jsx" || ext === ".tsx";
}

function isTs(filepath) {
  const ext = path.extname(filepath).toLowerCase();
  return ext === ".ts" || ext === ".tsx";
}

// --- Counting helpers -------------------------------------------------------
function countLines(source) {
  if (!source) return 0;
  let n = 0;
  for (let i = 0; i < source.length; i++) if (source.charCodeAt(i) === 10) n++;
  if (source.length && source[source.length - 1] !== "\n") n++;
  return n;
}

// --- Build parser configured for the target file ---------------------------
function buildParser(filepath) {
  if (!acorn) {
    throw new Error(
      "vendored acorn unavailable: " +
        (VENDOR_LOAD_ERROR && VENDOR_LOAD_ERROR.message),
    );
  }
  let Parser = acorn.Parser;
  if (isTs(filepath) && acornTypescript) {
    try {
      Parser = Parser.extend(
        acornTypescript({ jsx: { allowNamespaces: true } }),
      );
    } catch (e) {
      // Fall back to JSX-only if TS extension fails.
      Parser = acorn.Parser;
    }
  }
  if (isJsx(filepath) && acornJsx) {
    Parser = Parser.extend(acornJsx());
  }
  return Parser;
}

// --- AST walking -----------------------------------------------------------
/**
 * Tiny non-recursive walker. Visits every node in `node` (BFS-style),
 * invoking `visit(node, parent)` for each. Skips nulls and primitives.
 */
function walk(root, visit) {
  if (!root) return;
  const stack = [{ node: root, parent: null }];
  while (stack.length) {
    const { node, parent } = stack.pop();
    if (!node || typeof node !== "object" || !node.type) continue;
    visit(node, parent);
    for (const key in node) {
      if (key === "loc" || key === "parent" || key === "range") continue;
      const child = node[key];
      if (!child) continue;
      if (Array.isArray(child)) {
        for (let i = 0; i < child.length; i++) {
          const c = child[i];
          if (c && typeof c === "object" && c.type) {
            stack.push({ node: c, parent: node });
          }
        }
      } else if (typeof child === "object" && child.type) {
        stack.push({ node: child, parent: node });
      }
    }
  }
}

// --- Param extraction (best-effort, source text via slicing) ---------------
function paramName(p, source) {
  if (!p) return "?";
  if (p.type === "Identifier") return p.name;
  if (
    p.type === "AssignmentPattern" &&
    p.left &&
    p.left.type === "Identifier"
  ) {
    return p.left.name;
  }
  if (
    p.type === "RestElement" &&
    p.argument &&
    p.argument.type === "Identifier"
  ) {
    return "..." + p.argument.name;
  }
  if (p.type === "ObjectPattern") return "{...}";
  if (p.type === "ArrayPattern") return "[...]";
  return p.name || "?";
}

function paramDefault(p, source) {
  if (p && p.type === "AssignmentPattern" && p.right) {
    return source.slice(p.right.start, p.right.end);
  }
  return undefined;
}

function paramTypeAnnotation(p, source) {
  // TS annotation appears as `typeAnnotation` on the Identifier node.
  const target = p && p.type === "AssignmentPattern" ? p.left : p;
  if (target && target.typeAnnotation) {
    const ta = target.typeAnnotation.typeAnnotation || target.typeAnnotation;
    if (ta && typeof ta.start === "number") {
      return source.slice(ta.start, ta.end);
    }
  }
  return null;
}

function extractParams(fn, source) {
  const out = [];
  const params = fn.params || [];
  for (const p of params) {
    const entry = {
      name: paramName(p, source),
      type: paramTypeAnnotation(p, source),
    };
    const d = paramDefault(p, source);
    if (d !== undefined) entry.default = d;
    out.push(entry);
  }
  return out;
}

function fnReturnType(fn, source) {
  if (fn && fn.returnType) {
    const ta = fn.returnType.typeAnnotation || fn.returnType;
    if (ta && typeof ta.start === "number") {
      return source.slice(ta.start, ta.end);
    }
  }
  return null;
}

// --- Heuristics ------------------------------------------------------------
const PASCAL = /^[A-Z][A-Za-z0-9_]*$/;

function isPascalCase(name) {
  return typeof name === "string" && PASCAL.test(name);
}

function returnsJsx(fnBody) {
  // Body may be a BlockStatement or an expression (arrow).
  if (!fnBody) return false;
  if (fnBody.type === "JSXElement" || fnBody.type === "JSXFragment")
    return true;
  if (fnBody.type !== "BlockStatement") return false;
  let found = false;
  walk(fnBody, (node) => {
    if (found) return;
    if (node.type === "ReturnStatement" && node.argument) {
      const a = node.argument;
      if (a.type === "JSXElement" || a.type === "JSXFragment") found = true;
    }
  });
  return found;
}

// --- Extractors ------------------------------------------------------------
function extractExports(ast, source) {
  const out = [];

  function declName(d) {
    if (!d) return null;
    if (d.id && d.id.name) return d.id.name;
    return null;
  }

  function pushFunction(node, line, kind) {
    const name =
      node.id && node.id.name
        ? node.id.name
        : kind === "default"
          ? "default"
          : null;
    if (!name) return;
    const isComp = isPascalCase(name) && returnsJsx(node.body);
    out.push({
      name,
      line,
      kind: isComp ? "react-component" : kind,
    });
  }

  for (const node of ast.body || []) {
    if (!node) continue;
    if (node.type === "ExportNamedDeclaration") {
      const d = node.declaration;
      if (d) {
        if (d.type === "FunctionDeclaration" || d.type === "ClassDeclaration") {
          const name = declName(d);
          if (name) {
            const isComp =
              d.type === "FunctionDeclaration" &&
              isPascalCase(name) &&
              returnsJsx(d.body);
            out.push({
              name,
              line: (d.loc && d.loc.start.line) || node.loc.start.line,
              kind: isComp ? "react-component" : "named",
            });
          }
        } else if (d.type === "VariableDeclaration") {
          for (const decl of d.declarations) {
            if (!decl.id || !decl.id.name) continue;
            const name = decl.id.name;
            let isComp = false;
            if (
              decl.init &&
              (decl.init.type === "ArrowFunctionExpression" ||
                decl.init.type === "FunctionExpression")
            ) {
              isComp = isPascalCase(name) && returnsJsx(decl.init.body);
            }
            out.push({
              name,
              line: (decl.loc && decl.loc.start.line) || node.loc.start.line,
              kind: isComp ? "react-component" : "named",
            });
          }
        } else if (d.id && d.id.name) {
          out.push({
            name: d.id.name,
            line: (d.loc && d.loc.start.line) || node.loc.start.line,
            kind: "named",
          });
        }
      }
      // export { a, b }
      if (node.specifiers && node.specifiers.length) {
        for (const spec of node.specifiers) {
          if (spec.exported && spec.exported.name) {
            out.push({
              name: spec.exported.name,
              line: (spec.loc && spec.loc.start.line) || node.loc.start.line,
              kind: "named",
            });
          }
        }
      }
    } else if (node.type === "ExportDefaultDeclaration") {
      const d = node.declaration;
      const line = node.loc.start.line;
      if (d.type === "FunctionDeclaration") {
        const name = d.id && d.id.name ? d.id.name : "default";
        const isComp = isPascalCase(name) && returnsJsx(d.body);
        out.push({ name, line, kind: isComp ? "react-component" : "default" });
      } else if (d.type === "ClassDeclaration") {
        out.push({
          name: (d.id && d.id.name) || "default",
          line,
          kind: "default",
        });
      } else if (d.type === "Identifier") {
        out.push({ name: d.name, line, kind: "default" });
      } else if (
        d.type === "ArrowFunctionExpression" ||
        d.type === "FunctionExpression"
      ) {
        out.push({ name: "default", line, kind: "default" });
      } else {
        out.push({ name: "default", line, kind: "default" });
      }
    } else if (node.type === "VariableDeclaration") {
      // Module-level vars are not exports per se, but capture top-level
      // component declarations (assigned to PascalCase) so they show up.
      for (const decl of node.declarations) {
        if (!decl.id || !decl.id.name) continue;
        const name = decl.id.name;
        if (!isPascalCase(name)) continue;
        if (
          decl.init &&
          (decl.init.type === "ArrowFunctionExpression" ||
            decl.init.type === "FunctionExpression")
        ) {
          if (returnsJsx(decl.init.body)) {
            out.push({
              name,
              line: (decl.loc && decl.loc.start.line) || node.loc.start.line,
              kind: "react-component",
            });
          }
        }
      }
    } else if (node.type === "FunctionDeclaration") {
      const name = node.id && node.id.name;
      if (name && isPascalCase(name) && returnsJsx(node.body)) {
        out.push({
          name,
          line: node.loc.start.line,
          kind: "react-component",
        });
      }
    }
  }

  return out;
}

function extractImports(ast, source) {
  const out = [];
  for (const node of ast.body || []) {
    if (!node) continue;
    if (node.type === "ImportDeclaration") {
      const moduleName =
        node.source && typeof node.source.value === "string"
          ? node.source.value
          : null;
      if (!moduleName) continue;
      const imported = [];
      let alias = undefined;
      for (const spec of node.specifiers || []) {
        if (spec.type === "ImportSpecifier") {
          imported.push(
            (spec.imported && spec.imported.name) || spec.local.name,
          );
        } else if (spec.type === "ImportDefaultSpecifier") {
          imported.push("default");
          if (spec.local && spec.local.name) alias = spec.local.name;
        } else if (spec.type === "ImportNamespaceSpecifier") {
          imported.push("*");
          if (spec.local && spec.local.name) alias = spec.local.name;
        }
      }
      const entry = {
        line: node.loc.start.line,
        name: moduleName,
        kind: "import",
      };
      if (imported.length) entry.imported = imported;
      if (alias) entry.alias = alias;
      out.push(entry);
    }
  }
  // Walk for require() and dynamic import().
  walk(ast, (node) => {
    if (node.type === "CallExpression") {
      const callee = node.callee;
      if (
        callee.type === "Identifier" &&
        callee.name === "require" &&
        node.arguments[0] &&
        node.arguments[0].type === "Literal" &&
        typeof node.arguments[0].value === "string"
      ) {
        out.push({
          line: node.loc.start.line,
          name: node.arguments[0].value,
          kind: "require",
        });
      }
    } else if (node.type === "ImportExpression") {
      const src = node.source;
      if (src && src.type === "Literal" && typeof src.value === "string") {
        out.push({
          line: node.loc.start.line,
          name: src.value,
          kind: "dynamic",
        });
      }
    }
  });
  return out;
}

const HTTP_VERBS = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "head",
  "options",
]);

function extractRoutes(ast, source) {
  const out = [];
  walk(ast, (node) => {
    if (node.type !== "CallExpression") return;
    const callee = node.callee;
    if (!callee || callee.type !== "MemberExpression") return;
    if (callee.object.type !== "Identifier") return;
    const objName = callee.object.name;
    if (objName !== "app" && objName !== "router") return;
    if (!callee.property || callee.property.type !== "Identifier") return;
    const verb = callee.property.name.toLowerCase();
    if (!HTTP_VERBS.has(verb)) return;
    if (!node.arguments || node.arguments.length < 2) return;
    const first = node.arguments[0];
    if (!first || first.type !== "Literal" || typeof first.value !== "string")
      return;
    // Find handler name — last arg that is a function, or an identifier ref.
    let handler = "anonymous";
    for (let i = node.arguments.length - 1; i >= 1; i--) {
      const a = node.arguments[i];
      if (!a) continue;
      if (a.type === "Identifier") {
        handler = a.name;
        break;
      }
      if (
        a.type === "FunctionExpression" ||
        a.type === "ArrowFunctionExpression"
      ) {
        handler = (a.id && a.id.name) || "anonymous";
        break;
      }
    }
    out.push({
      method: verb.toUpperCase(),
      path: first.value,
      line: node.loc.start.line,
      function: handler,
      framework: "express",
    });
  });
  return out;
}

function extractFunctions(ast, source, modulePath) {
  // Top-level function declarations + arrow/function expressions bound
  // to a top-level const.
  modulePath = modulePath || "";
  const out = [];
  const push = (name, line, params, return_type, is_async) => {
    out.push({
      id: stableMethodId(modulePath, "", name, params, return_type),
      name,
      line,
      params,
      return_type,
      docstring: null,
      is_async,
    });
  };
  for (const node of ast.body || []) {
    if (!node) continue;
    if (node.type === "FunctionDeclaration") {
      push(
        (node.id && node.id.name) || "anonymous",
        node.loc.start.line,
        extractParams(node, source),
        fnReturnType(node, source),
        !!node.async,
      );
    } else if (
      node.type === "ExportNamedDeclaration" &&
      node.declaration &&
      node.declaration.type === "FunctionDeclaration"
    ) {
      const d = node.declaration;
      push(
        (d.id && d.id.name) || "anonymous",
        d.loc.start.line,
        extractParams(d, source),
        fnReturnType(d, source),
        !!d.async,
      );
    } else if (
      node.type === "ExportDefaultDeclaration" &&
      node.declaration &&
      node.declaration.type === "FunctionDeclaration"
    ) {
      const d = node.declaration;
      push(
        (d.id && d.id.name) || "default",
        d.loc.start.line,
        extractParams(d, source),
        fnReturnType(d, source),
        !!d.async,
      );
    } else if (node.type === "VariableDeclaration") {
      for (const decl of node.declarations) {
        if (!decl.id || !decl.id.name) continue;
        const init = decl.init;
        if (
          init &&
          (init.type === "ArrowFunctionExpression" ||
            init.type === "FunctionExpression")
        ) {
          push(
            decl.id.name,
            decl.loc.start.line,
            extractParams(init, source),
            fnReturnType(init, source),
            !!init.async,
          );
        }
      }
    } else if (
      node.type === "ExportNamedDeclaration" &&
      node.declaration &&
      node.declaration.type === "VariableDeclaration"
    ) {
      for (const decl of node.declaration.declarations) {
        if (!decl.id || !decl.id.name) continue;
        const init = decl.init;
        if (
          init &&
          (init.type === "ArrowFunctionExpression" ||
            init.type === "FunctionExpression")
        ) {
          push(
            decl.id.name,
            decl.loc.start.line,
            extractParams(init, source),
            fnReturnType(init, source),
            !!init.async,
          );
        }
      }
    }
  }
  return out;
}

function extractClasses(ast, source, modulePath) {
  modulePath = modulePath || "";
  const out = [];
  for (const node of ast.body || []) {
    if (!node) continue;
    let cls = null;
    if (node.type === "ClassDeclaration") cls = node;
    else if (
      (node.type === "ExportNamedDeclaration" ||
        node.type === "ExportDefaultDeclaration") &&
      node.declaration &&
      node.declaration.type === "ClassDeclaration"
    ) {
      cls = node.declaration;
    }
    if (!cls) continue;
    const clsName = (cls.id && cls.id.name) || "anonymous";
    const methods = [];
    if (cls.body && cls.body.body) {
      for (const m of cls.body.body) {
        if (m.type === "MethodDefinition" && m.key) {
          const name =
            m.key.name ||
            (m.key.value !== undefined ? String(m.key.value) : null);
          if (name) {
            const params = extractParams(m.value || {}, source);
            const ret = fnReturnType(m.value || {}, source);
            const mid = stableMethodId(modulePath, clsName, name, params, ret);
            methods.push({ id: mid, name, line: m.loc.start.line });
          }
        }
      }
    }
    const entry = {
      name: clsName,
      line: cls.loc.start.line,
      methods,
    };
    const bases = [];
    if (cls.superClass && cls.superClass.type === "Identifier") {
      bases.push(cls.superClass.name);
    }
    if (bases.length) entry.bases = bases;
    out.push(entry);
  }
  return out;
}

// --- Regex fallback (used when acorn fails) --------------------------------
function regexFallback(source) {
  const imports = [];
  const exports_ = [];
  const lines = source.split("\n");
  const importRe = /^\s*import\s+(?:(.+?)\s+from\s+)?["']([^"']+)["']/;
  const requireRe = /require\(["']([^"']+)["']\)/g;
  const exportNamedRe =
    /^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+(\w+)/;
  const exportDefaultRe =
    /^\s*export\s+default\s+(?:function\s+(\w+)|class\s+(\w+))?/;
  lines.forEach((line, i) => {
    const im = importRe.exec(line);
    if (im) {
      imports.push({ line: i + 1, name: im[2], kind: "import" });
    }
    let rm;
    requireRe.lastIndex = 0;
    while ((rm = requireRe.exec(line)) !== null) {
      imports.push({ line: i + 1, name: rm[1], kind: "require" });
    }
    const en = exportNamedRe.exec(line);
    if (en) {
      exports_.push({ name: en[1], line: i + 1, kind: "named" });
    }
    const ed = exportDefaultRe.exec(line);
    if (ed) {
      exports_.push({
        name: ed[1] || ed[2] || "default",
        line: i + 1,
        kind: "default",
      });
    }
  });
  return { imports, exports: exports_ };
}

// --- Main ------------------------------------------------------------------
function parse(filepath) {
  const result = {
    path: filepath,
    language: detectLanguage(filepath),
    lines: 0,
    functions: [],
    classes: [],
    imports: [],
    routes: [],
    exports: [],
    errors: [],
  };

  let source = "";
  try {
    source = fs.readFileSync(filepath, "utf8");
  } catch (e) {
    result.errors.push({ message: "read error: " + e.message });
    return result;
  }
  result.lines = countLines(source);
  const modulePath = normalizeModulePath(filepath);

  if (!acorn) {
    // Vendored parser missing — fall back to regex.
    result.errors.push({
      message:
        "vendored acorn unavailable: " +
        (VENDOR_LOAD_ERROR && VENDOR_LOAD_ERROR.message),
    });
    const fb = regexFallback(source);
    result.imports = fb.imports;
    result.exports = fb.exports;
    return result;
  }

  let Parser;
  try {
    Parser = buildParser(filepath);
  } catch (e) {
    result.errors.push({ message: "parser-build: " + e.message });
    const fb = regexFallback(source);
    result.imports = fb.imports;
    result.exports = fb.exports;
    return result;
  }

  let ast = null;
  try {
    ast = Parser.parse(source, {
      sourceType: "module",
      ecmaVersion: "latest",
      locations: true,
      allowReturnOutsideFunction: true,
      allowImportExportEverywhere: true,
      allowHashBang: true,
    });
  } catch (e) {
    // Try as script (no module).
    try {
      ast = Parser.parse(source, {
        sourceType: "script",
        ecmaVersion: "latest",
        locations: true,
        allowReturnOutsideFunction: true,
        allowHashBang: true,
      });
    } catch (e2) {
      result.errors.push({
        line: e.loc ? e.loc.line : 0,
        col: e.loc ? e.loc.column : 0,
        message: "SyntaxError: " + e.message,
      });
      const fb = regexFallback(source);
      result.imports = fb.imports;
      result.exports = fb.exports;
      return result;
    }
  }

  try {
    result.functions = extractFunctions(ast, source, modulePath);
  } catch (e) {
    result.errors.push({ message: "functions: " + e.message });
  }
  try {
    result.classes = extractClasses(ast, source, modulePath);
  } catch (e) {
    result.errors.push({ message: "classes: " + e.message });
  }
  try {
    result.imports = extractImports(ast, source);
  } catch (e) {
    result.errors.push({ message: "imports: " + e.message });
  }
  try {
    result.routes = extractRoutes(ast, source);
  } catch (e) {
    result.errors.push({ message: "routes: " + e.message });
  }
  try {
    result.exports = extractExports(ast, source);
  } catch (e) {
    result.errors.push({ message: "exports: " + e.message });
  }

  return result;
}

function main(argv) {
  if (argv.length < 3) {
    process.stderr.write("usage: parse-js.js <path>\n");
    process.exit(2);
  }
  const filepath = argv[2];
  let result;
  try {
    result = parse(filepath);
  } catch (e) {
    result = {
      path: filepath,
      language: detectLanguage(filepath),
      lines: 0,
      functions: [],
      classes: [],
      imports: [],
      routes: [],
      exports: [],
      errors: [{ message: "unhandled: " + e.message }],
    };
  }
  process.stdout.write(JSON.stringify(result) + "\n");
  process.exit(0);
}

if (require.main === module) {
  main(process.argv);
}

module.exports = { parse };

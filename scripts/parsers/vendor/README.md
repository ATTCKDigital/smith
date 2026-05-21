# Vendored acorn parser bundle

This directory ships a single-file CommonJS bundle of the JavaScript parsers
required by `parse-js.js`. It is intentionally vendored (not pulled at install
time) so that Smith parsers work on machines without internet access and with
zero npm install steps.

## Contents

- `acorn.min.js` — minified bundle of `acorn@8`, `acorn-jsx`, and
  `acorn-typescript`, produced by esbuild.
- `VERSION` — pinned upstream versions for reproducibility.

## Origin & License

| Package | Version | License |
|---|---|---|
| acorn | 8.x | MIT |
| acorn-jsx | 5.x | MIT |
| acorn-typescript | latest | MIT |

All three are MIT-licensed and freely redistributable. Original sources:

- https://github.com/acornjs/acorn
- https://github.com/acornjs/acorn-jsx
- https://github.com/TyrealHu/acorn-typescript

## Regeneration

To rebuild the bundle (when bumping versions, fixing a bug, or verifying
reproducibility), from a scratch directory with internet access:

```bash
cd /tmp/build-acorn-bundle
npm init -y
npm install --no-save acorn@8 acorn-jsx acorn-typescript esbuild

cat > entry.js << 'EOF'
const acorn = require('acorn');
const acornJsx = require('acorn-jsx');
const acornTypescript = require('acorn-typescript').default;
module.exports = { acorn, acornJsx, acornTypescript };
EOF

npx esbuild entry.js \
  --bundle \
  --minify \
  --platform=node \
  --format=cjs \
  --target=node18 \
  --outfile=/path/to/smith-repo/scripts/parsers/vendor/acorn.min.js
```

The resulting bundle should be roughly 150KB. Commit both the new
`acorn.min.js` and an updated `VERSION` file.

## Why vendor?

1. Parsers run in `manifest-updater.sh`, a PostToolUse hook on every file
   edit. We cannot tolerate a `node_modules/` lookup miss or a flaky network
   install at hook-time.
2. Users running `npx skills add attck/smith` should get a fully working
   manifest system from one command — no separate `npm install` step.
3. The bundle is small enough that the repo cost is negligible.

## Gitattributes

`.gitattributes` marks `acorn.min.js` as `linguist-vendored=true` and
`linguist-generated=true` so GitHub's language statistics ignore it.

---
name: vite
description: VITE_* env-prefix gotcha (non-prefixed vars are undefined in the browser), hardcoded fallback URLs masking misconfig, build-time vs runtime env substitution, public/ vs imported assets
triggers:
  package_json_dep: ["vite"]
  files: ["vite.config.ts", "vite.config.js", "vite.config.mjs"]
---

# Vite review playbook

Vite has a few client-vs-server boundary gotchas that are silent in dev and
break in production -- exactly the kind of bug a careful reviewer should
catch *before* merge.

## Only `VITE_*` env vars reach the client

This is the single biggest Vite footgun. Vite *only* exposes env vars
prefixed with `VITE_` to client-side code via `import.meta.env`:

```ts
// in src/supabase.ts
const url = import.meta.env.VITE_SUPABASE_URL;        // works
const key = import.meta.env.SUPABASE_ANON_KEY;        // always undefined!
```

Anything without the `VITE_` prefix evaluates to `undefined` at build time,
silently. The app may appear to work in dev (where the dev server provides
fallbacks) and explode (or quietly fail) in prod. Always grep diffs for
`import.meta.env\.[A-Z_]+` and check every match starts with `VITE_`.

## Hardcoded fallback URLs hide misconfig

```ts
const url = import.meta.env.VITE_SUPABASE_URL || "https://example.supabase.co";
```

Pattern: `||` fallback to a placeholder URL or `"localhost:..."` or `""`.
Production silently misbehaves instead of failing loudly. A reviewer
should ask: should this throw on missing config, or default to something
visibly wrong?

## `import.meta.env` is build-time, not runtime

Values are **substituted at build time** (string-replaced). You cannot
change them after `vite build`. Tools that change env at container start
(Docker, k8s ConfigMaps, Heroku) will not affect the bundle.

## Dev-only vs prod-only modules

`import.meta.env.MODE` is `"development"` or `"production"`. Using it for
*conditional* imports (`if (import.meta.env.DEV) { ... }`) tree-shakes the
branch in prod. Using it for runtime checks does not.

## Public dir vs imported assets

Files in `public/` are served as-is (no hashing, no fingerprinting).
Imported assets (`import logo from "./logo.png"`) get hashed and
fingerprinted. A diff that puts a runtime-cached asset in `public/` is
asking for stale-cache bugs.

## Sources

- [Vite docs: Env Variables and Modes](https://vite.dev/guide/env-and-mode.html)
- [Vite docs: HTML Env Replacement](https://vite.dev/guide/env-and-mode.html#html-env-replacement)
- [Vite docs: Static Asset Handling](https://vite.dev/guide/assets.html)

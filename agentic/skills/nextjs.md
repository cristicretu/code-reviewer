---
name: nextjs
description: server-vs-client component boundary, NEXT_PUBLIC_ prefix for client env vars, server actions need auth and validation, edge runtime API restrictions, missing revalidatePath after mutations
triggers:
  package_json_dep: ["next"]
  files: ["next.config.js", "next.config.ts", "next.config.mjs"]
---

# Next.js review playbook

Most Next.js bugs come from confusing where code runs (server vs client
vs edge) and which env vars / APIs are available where.

## Server vs client component boundary

In the App Router, a file is a **server component** by default. A file
becomes a **client component** only when its first non-comment line is
`"use client"`.

- Server components can `await` data, talk to the database, use
  `process.env.SECRET_KEY` -- they never reach the browser.
- Client components can use hooks (`useState`, `useEffect`), event
  handlers, browser APIs.

A common bug: `"use client"` is added to a parent component "to fix a
hooks error", which then forces every child to render on the client too.
Push `"use client"` as low in the tree as possible.

## Env vars: NEXT_PUBLIC_ prefix

Next.js exposes env vars to the browser only if prefixed `NEXT_PUBLIC_`.
`process.env.SUPABASE_ANON_KEY` is `undefined` in client code unless
renamed `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Same trap as Vite's `VITE_*`.

Conversely, *do not* prefix secrets with `NEXT_PUBLIC_` -- they get
inlined into the JS bundle and shipped to every visitor.

## Server actions: validate inputs

```ts
"use server";
async function deletePost(formData: FormData) {
  const id = formData.get("id");
  await db.posts.delete({ where: { id } });
}
```

Server actions are public HTTP endpoints. Anyone can POST to them with
any payload. Always validate types and authorize the caller -- they are
**not** automatically protected by being inside an authenticated page.

## Edge runtime restrictions

`export const runtime = "edge";` runs in V8 isolates, not Node. Many Node
APIs are unavailable: `fs`, `child_process`, native modules, most npm
packages that touch them. Common gotcha: importing a Node-only library
from an edge route silently bundles a stub that throws at runtime.

## `revalidatePath` / `revalidateTag` after mutations

After a server action mutates data, the cached pages still serve stale
HTML until the next revalidation. Forgetting `revalidatePath("/...")` is
a very common bug -- the user sees their action "didn't work" until a
hard refresh.

## Image optimization domains

`<Image src="https://other-domain.com/..."/>` requires the host to be
listed in `next.config.js` `images.remotePatterns`. Diffs that add new
external image sources without updating config will throw at build time.

## Sources

- [Next.js docs: Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components)
- [Next.js docs: Environment Variables](https://nextjs.org/docs/app/guides/environment-variables)
- [Next.js docs: Server Actions and Mutations](https://nextjs.org/docs/app/getting-started/updating-data)
- [Next.js docs: Edge Runtime](https://nextjs.org/docs/app/api-reference/edge)

---
name: supabase
description: realtime channels need removeChannel cleanup, RLS gaps on new tables, service-role key in client code, .toString() vs .toISOString() for timestamptz, getUser vs getSession for auth checks
triggers:
  package_json_dep_prefix: ["@supabase/"]
---

# Supabase review playbook

Supabase code is mostly thin wrappers around Postgres + Postgrest +
realtime, but each layer has gotchas a reviewer should check for.

## Realtime: every `.channel(...).subscribe()` needs a `removeChannel`

```ts
useEffect(() => {
  const channel = supabase
    .channel("my-channel")
    .on("postgres_changes", {...}, handler)
    .subscribe();

  return () => {
    supabase.removeChannel(channel);   // <-- required
  };
}, []);
```

Without `removeChannel` in the cleanup function, every re-mount stacks a
new subscription. Symptoms: handler fires 2× / 3× / N× per event,
client-side memory grows, server connection count climbs.

## Race conditions on `postgres_changes` re-fetches

A common pattern: each event triggers a fresh `select`. If events arrive
in a burst, an older slow `select` can land after a newer fast one and
overwrite state with stale rows. Fix with an `AbortController`, an
incrementing request id, or refetching in a `useDebounce`.

## Anon key safety

The anon key is **safe to ship to the client** as long as Row-Level
Security (RLS) is enabled on every table the client can reach. A diff
that adds a new table without an RLS policy + a permissive policy
effectively makes that table publicly read/write. Always check:

- Was a new table added? Is RLS enabled?
- Are policies scoped to `auth.uid()` or appropriate roles?
- Is the client using the anon key (safe) or the service role key
  (must never reach the browser)?

## Service role key in client code = critical bug

`SUPABASE_SERVICE_ROLE_KEY` (or any key marked "service" / "admin") must
never be referenced from `import.meta.env`, `process.env.NEXT_PUBLIC_*`,
or any other browser-reachable surface. If you see one in client-side
code, request changes immediately -- it grants full read/write to the DB.

## `.toString()` for timestamp columns

```ts
.insert({ at: new Date().toString() })   // bad
.insert({ at: new Date().toISOString() }) // good
```

`Date.prototype.toString()` returns a locale + timezone string
(`"Sat May 02 2026 18:21:42 GMT+0300 (EEST)"`). Postgres `timestamptz`
parses ISO 8601 reliably; locale strings parse inconsistently and break
ordering across regions and machines.

## Auth state on the client

`supabase.auth.getSession()` reads from local storage and is safe.
`supabase.auth.getUser()` makes a network call to verify the JWT. Use
`getUser()` whenever you're about to *trust* the user identity (e.g. for
authorization decisions), not just display it.

## Sources

- [Supabase docs: Realtime > Subscribing to changes](https://supabase.com/docs/guides/realtime/postgres-changes)
- [Supabase docs: Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase docs: API keys](https://supabase.com/docs/guides/api/api-keys)
- [Supabase docs: getUser vs getSession](https://supabase.com/docs/reference/javascript/auth-getuser)

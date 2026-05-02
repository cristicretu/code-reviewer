---
name: async-js
description: Race conditions, AbortController, missing await, unhandled rejections
triggers:
  diff_extensions: [".ts", ".tsx", ".js", ".jsx", ".mjs"]
---

# Async JS / TS review playbook

The bugs in this section are timing-dependent and almost never caught by
tests. A reviewer who can spot them before merge is doing high-leverage
work.

## Race conditions in user-driven fetches

Pattern: an input change or click triggers an async request, and the
response updates state.

```ts
function Search({ query }) {
  const [hits, setHits] = useState([]);
  useEffect(() => {
    fetch(`/api/search?q=${query}`).then(r => r.json()).then(setHits);
  }, [query]);
}
```

If `query` changes from `"foo"` to `"foob"` and the `"foo"` request is
slower, `hits` ends up showing results for `"foo"` even though the user
typed `"foob"`. Fix:

```ts
useEffect(() => {
  const ac = new AbortController();
  fetch(`/api/search?q=${query}`, { signal: ac.signal })
    .then(r => r.json())
    .then(setHits)
    .catch(e => { if (e.name !== "AbortError") throw e; });
  return () => ac.abort();
}, [query]);
```

Or an `isMounted` ref / incrementing request id.

## Missing `await` (silent dropped promise)

```ts
async function save() {
  api.post("/save", body);   // forgot await -- no error if it fails
  setDone(true);
}
```

If `api.post` rejects, you'll never know. Always `await` an async call
unless you explicitly mean fire-and-forget (and even then, attach
`.catch(...)` so the unhandled rejection doesn't blow up the process).

## Unhandled rejections in callbacks

`setTimeout`, `setInterval`, event listeners, and `Promise.then` callbacks
do **not** propagate exceptions to the surrounding async function. A
`throw` inside one becomes an unhandled rejection.

## `Promise.all` short-circuits on first reject

```ts
const [a, b, c] = await Promise.all([fetchA(), fetchB(), fetchC()]);
```

If `fetchB()` rejects, `fetchA()` and `fetchC()` keep running but their
results are discarded. Resources may leak. Use `Promise.allSettled` if
you need all results regardless of individual failure.

## `for ... of` vs `forEach` for async

```ts
items.forEach(async (item) => {
  await process(item);   // forEach ignores the returned promise
});
// "done" prints before processing finishes
console.log("done");
```

Use `for (const item of items) { await process(item); }` for sequential,
or `await Promise.all(items.map(process))` for concurrent.

## `JSON.parse` / `JSON.stringify` on unknown input

Both can throw on malformed input or circular references. Wrap user-
controlled JSON parsing in try/catch.

## Sources

- [MDN: AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController)
- [MDN: Promise.allSettled](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/allSettled)
- [MDN: Unhandled rejections](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises#error_propagation)

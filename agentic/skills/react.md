---
name: react
description: React lifecycle, hooks, closures, effects, and rendering gotchas
triggers:
  package_json_dep: ["react"]
  diff_extensions: [".tsx", ".jsx"]
---

# React review playbook

A careful reviewer of React code should check for the following bug classes
before approving. None are caught by ESLint defaults; most show up only at
runtime, sometimes only under specific timing.

## Stale closures in effects / callbacks

`useEffect`, `useCallback`, `useMemo`, `setInterval`, `setTimeout`, and event
listeners all *capture* the values of `useState` variables at the time the
function is created. If the state changes, the captured value does **not**
update -- you read a stale value forever.

- `setInterval(() => setCount(count + 1), 1000)` inside an effect with deps
  `[]` ticks once and then forever increments from 0. Fix: functional updater
  `setCount(c => c + 1)`.
- Adding the state to the deps array (e.g. `[count]`) "fixes" it by
  recreating the interval every tick, which is wasteful and reorders work.
  Functional updater is almost always correct.
- Same trap with event handlers added once via effect: the handler closes
  over the first render's state.

## Missing effect cleanup

Every `useEffect` that *attaches* something must `return () => detach()`:

- `window.addEventListener` → `removeEventListener`
- `subscribe()` (RxJS, Supabase channels, websockets) → `unsubscribe()` /
  `removeChannel()`
- `setInterval` / `setTimeout` → `clearInterval` / `clearTimeout`
- `IntersectionObserver`, `ResizeObserver` → `.disconnect()`

Without cleanup, re-mounts (HMR, route changes, parent re-renders) stack
listeners. Symptoms: spacebar fires N times, fetch fires once per stale
component, memory grows.

## useEffect dependency arrays

- Missing dep → stale value (linter `react-hooks/exhaustive-deps` catches
  most, but it can be silenced).
- Object/array/function literal in deps → effect re-runs every render
  because the reference changes. Wrap with `useMemo` / `useCallback` or
  move the literal inside the effect.

## Race conditions in async effects

```ts
useEffect(() => {
  fetch(url).then(setData);
}, [url]);
```

If `url` changes quickly, an older slow response can land after a newer
fast one and overwrite with stale data. Fix with `AbortController`, an
incrementing request id, or an `isMounted` flag.

## Controlled vs uncontrolled inputs

A `<input value={x} />` with no `onChange` is read-only and React will warn.
Switching from `value` to `defaultValue` mid-life flips between controlled
and uncontrolled and React will warn. Always pick one and stick to it.

## Hydration mismatches (SSR)

Anything that differs between server and first client render (`Date.now()`,
`window.innerWidth`, locale, time zone, `Math.random()`) causes a hydration
warning. Wrap in `useEffect` so it runs only on the client.

## Sources

- [React docs: Synchronizing with Effects](https://react.dev/learn/synchronizing-with-effects)
- [React docs: Updating state based on the previous state](https://react.dev/reference/react/useState#updating-state-based-on-the-previous-state)
- [React docs: You might not need an effect](https://react.dev/learn/you-might-not-need-an-effect)

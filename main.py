
import os
import re
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from llama_cpp import Llama

# ── Config ─────────────────────────────────────────────────────────────────────
MODEL_PATH = os.environ.get("LLAMA_MODEL_PATH", "/data/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf")
N_CTX       = int(os.environ.get("LLAMA_CTX", "4096"))
N_GPU_LAYERS= int(os.environ.get("LLAMA_N_GPU_LAYERS", "-1"))
TEMPERATURE = float(os.environ.get("LLAMA_TEMPERATURE", "0.2"))
TOP_P       = float(os.environ.get("LLAMA_TOP_P", "0.95"))
MAX_TOKENS  = int(os.environ.get("LLAMA_MAX_TOKENS", "256"))

# Safety/cooldown flags you would wire to real change-management systems
MAINTENANCE_WINDOW = bool(int(os.environ.get("MAINTENANCE_WINDOW", "0")))
RESYNC_COOLDOWN_S  = int(os.environ.get("RESYNC_COOLDOWN_S", "120"))
_last_resync_ts: Dict[str, float] = {}

# ── Telemetry (replace stub with real data sources) ────────────────────────────
def collect_shard_metrics() -> List[Dict[str, Any]]:
    """
    Replace this with real metrics:
      - local_state_hash vs global_state_hash
      - replication_lag_ms
      - ui_visible_count vs ledger_count
      - error_rate, last_event_age_sec
      - queue_backlog, partition_hints, clock_skew_ms
      - stop flags (maintenance, migration, cooldowns)
    """
    now = int(time.time())
    return [
        {
            "name": "shard_alpha",
            "local_state_hash": "a1b2c3",
            "global_state_hash": "a1b2c3",
            "replication_lag_ms": 120,
            "ui_visible_count": 1520,
            "ledger_count": 1520,
            "error_rate": 0.0001,
            "last_event_age_sec": 2,
            "queue_backlog": 0,
            "partition_hints": 0,
            "clock_skew_ms": 50,
            "timestamp": now,
        },
        {
            "name": "shard_beta",
            "local_state_hash": "ff09ee",
            "global_state_hash": "ff09eF",  # mismatch for demo
            "replication_lag_ms": 2150,
            "ui_visible_count": 1479,
            "ledger_count": 1483,            # drift
            "error_rate": 0.012,
            "last_event_age_sec": 27,
            "queue_backlog": 12,
            "partition_hints": 3,
            "clock_skew_ms": 620,
            "timestamp": now,
        },
    ]

def build_context_json(shards: List[Dict[str, Any]]) -> str:
    ctx = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "safety": {
            "maintenance_window": MAINTENANCE_WINDOW,
            "resync_cooldown_s": RESYNC_COOLDOWN_S
        },
        "shards": shards,
    }
    return json.dumps(ctx, separators=(",", ":"), ensure_ascii=False)

# ── Advanced Prompt ────────────────────────────────────────────────────────────
PROMPT_TEMPLATE = """You are a systems reliability AI agent for Coinbase. Your job is to detect shard desynchronization from telemetry and decide whether to trigger a resync. Read the context JSON and follow the policies below. Do NOT output anything except the block in [replytemplate].

[context]
{{context_json}}
[/context]

[rubric]
PRIMARY DESYNC SIGNALS (any one may be decisive if extreme):
  • HASH_MISMATCH: local_state_hash != global_state_hash
  • UI_LEDGER_DRIFT: |ui_visible_count - ledger_count| > 0 for ≥ 2 consecutive samples
  • REPL_LAG: replication_lag_ms ≥ 1000
  • ERROR_SPIKE: error_rate ≥ 0.005 (persistent)
  • STALE_EVENTS: last_event_age_sec ≥ 20 for active shards
SECONDARY SIGNALS (supporting only—need at least one primary unless 3+ secondary concur):
  • QUEUE_BACKLOG: sustained backlog/slow consumers
  • PARTITION_HINTS: inter-shard comms timeouts/transient 5xx
  • CLOCK_SKEW: timestamp drift vs. leader > 500ms

SEVERITY HEURISTICS (internal only; do NOT print):
  • High: HASH_MISMATCH OR (REPL_LAG ≥ 2000) OR (UI_LEDGER_DRIFT ≥ 2 for ≥ 2 samples)
  • Medium: REPL_LAG 1000–1999 OR ERROR_SPIKE persistent OR STALE_EVENTS 20–60s
  • Low: isolated single-sample anomalies without corroboration

DECISION LOGIC:
  1) Score each shard: +0.5 for each Primary (cap 1.5), +0.15 for each Secondary (cap 0.45). Clamp total 0–1.95, then map to ConfidenceScore ∈ [0,1] via min(1, total/1.8).
  2) Choose the single MOST affected shard by score; if tie, choose lexicographically smallest name for determinism.
  3) Trigger resync only if:
       - At least one Primary present OR (≥3 Secondary AND REPL_LAG ≥ 750), AND
       - No safety stop flags (maintenance window, active migration, or resync_cooldown) in context.
  4) If insufficient evidence, Action = "Resync not needed", AffectedShard = "none", ConfidenceScore ≤ 0.40.
  5) Timestamp must be current UTC in ISO8601 Z format.

CONSTRAINTS:
  • Never invent fields; only use shards present in context.
  • Output EXACTLY matches [replytemplate].
  • DesyncReason should be a short phrase citing top signal(s), e.g., "hash mismatch; delayed replication".
  • ConfidenceScore is numeric with 2 decimals (e.g., 0.78).heres the llama version foss one etc use it wisely maybe good for Infosec
[/rubric]

[action]
# This block is for the orchestrator; DO NOT echo it.
# If you decide "Resync triggered", emit a side-effect command for automation:
#   RESYNC {{AffectedShard}} | reason="{{DesyncReason}}" | backoff="exponential: 30s..5m" | guardrails="idempotent, no double-commit"
# After resync, verify:
#   • hashes match; • replication_lag_ms < 500; • UI/ledger drift = 0; • error_rate normalizes.
# If verification fails, mark for human escalation: ESCALATE {{AffectedShard}} sev=High
[/action]

[replytemplate] ((you must fill in the required [bracket] sections))
SHARD_STATUS:
- AffectedShard: [shard_name or none]
- DesyncReason: [e.g. hash mismatch; delayed replication]
- Action: Resync triggered | Resync not needed
- ConfidenceScore: [0.00–1.00]
- Timestamp: [YYYY-MM-DDTHH:MM:SSZ]
[/replytemplate]
"""

def build_prompt(context_json: str) -> str:
    return PROMPT_TEMPLATE.replace("{{context_json}}", context_json)

# ── Output parsing ─────────────────────────────────────────────────────────────
BLOCK_RE = re.compile(
    r"SHARD_STATUS:\s*"
    r"-\s*AffectedShard:\s*(?P<shard>[^\n]+)\s*"
    r"-\s*DesyncReason:\s*(?P<reason>[^\n]+)\s*"
    r"-\s*Action:\s*(?P<action>Resync triggered|Resync not needed)\s*"
    r"-\s*ConfidenceScore:\s*(?P<conf>[0-1](?:\.\d+)?)\s*"
    r"-\s*Timestamp:\s*(?P<ts>[^\n]+)\s*",
    re.IGNORECASE
)

def extract_block_text(full_text: str) -> str:
    """Extract the SHARD_STATUS block if the model adds extra text."""
    m = BLOCK_RE.search(full_text)
    if not m:
        # Try to trim between replytemplate markers if present
        start = full_text.find("SHARD_STATUS:")
        if start >= 0:
            snippet = full_text[start:]
            # Heuristic: cut after timestamp line or first blank line
            lines = []
            for line in snippet.splitlines():
                lines.append(line)
                if line.strip().startswith("- Timestamp:"):
                    break
            return "\n".join(lines).strip()
        return full_text.strip()
    # Reconstruct in canonical order to ensure correctness
    gd = m.groupdict()
    return (
        "SHARD_STATUS:\n"
        f"- AffectedShard: {gd['shard'].strip()}\n"
        f"- DesyncReason: {gd['reason'].strip()}\n"
        f"- Action: {gd['action'].strip()}\n"
        f"- ConfidenceScore: {gd['conf'].strip()}\n"
        f"- Timestamp: {gd['ts'].strip()}"
    )

def parse_status(block_text: str) -> Optional[Dict[str, str]]:
    m = BLOCK_RE.search(block_text)
    return m.groupdict() if m else None

# ── Actions ────────────────────────────────────────────────────────────────────
def resync_allowed(shard: str) -> bool:
    if MAINTENANCE_WINDOW:
        return False
    last = _last_resync_ts.get(shard)
    now = time.time()
    if last and (now - last) < RESYNC_COOLDOWN_S:
        return False
    return True

def resync_shard(shard_name: str, reason: str) -> None:
    # Replace with real automation (HTTP/gRPC/k8s job/etc.)
    print(f"RESYNC {shard_name} | reason=\"{reason}\" | backoff=\"exponential: 30s..5m\" | guardrails=\"idempotent, no double-commit\"")
    _last_resync_ts[shard_name] = time.time()

# ── Driver ─────────────────────────────────────────────────────────────────────
def run_once() -> None:
    llm = Llama(model_path=MODEL_PATH, n_ctx=N_CTX, n_gpu_layers=N_GPU_LAYERS)
    shards = collect_shard_metrics()
    ctx_json = build_context_json(shards)
    prompt = build_prompt(ctx_json)

    out = llm(
        prompt,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        top_p=TOP_P,
        stop=None
    )
    raw_text = (out.get("choices", [{}])[0].get("text") or "").strip()

    # Normalize/output the block
    block = extract_block_text(raw_text)
    # Ensure timestamp presence in case model omitted it
    if "- Timestamp:" not in block:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        block = block.rstrip() + f"\n- Timestamp: {ts}"

    print(block)  # <-- The only required visible output

    # Optional: act on the decision
    status = parse_status(block)
    if status:
        shard = status.get("shard", "").strip()
        action = (status.get("action", "") or "").lower()
        reason = status.get("reason", "").strip()
        if action.startswith("resync") and shard and shard.lower() != "none" and resync_allowed(shard):
            resync_shard(shard, reason)

if __name__ == "__main__":
    run_once()

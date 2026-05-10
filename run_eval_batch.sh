#!/usr/bin/env bash
# Overnight eval batch runner — generates predictions for all 3 models
# and scores them with deepeval. Safe to run unattended.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOGFILE="outputs/eval/batch_$(date +%Y%m%d_%H%M%S).log"
mkdir -p outputs/eval

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOGFILE"; }

log "=== OVERNIGHT EVAL BATCH STARTED ==="
log "Log file: $LOGFILE"

# ---- Ensure Ollama is up ----
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    log "Starting Ollama..."
    OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 \
        nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_eval.log 2>&1 &
    sleep 5
    for _ in $(seq 1 30); do
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            log "Ollama ready."
            break
        fi
        sleep 2
    done
else
    log "Ollama already running."
fi

# ---- Activate venv ----
source .venv/bin/activate

export API_BASE="http://localhost:11434/v1"

# ---- Models to evaluate ----
BASE_MODEL="qwen3:8b"
SFT_MODEL="code-reviewer-sft:latest"
RLHF_MODEL="hf.co/cretu-luca/code-reviewer-4-bit:Q4_K_M"

# ---- Phase 1: Generate predictions ----
log "=== PHASE 1: Generating predictions ==="

for pair in "base $BASE_MODEL" "sft $SFT_MODEL" "rlhf $RLHF_MODEL"; do
    VARIANT="${pair%% *}"
    MODEL_ID="${pair#* }"
    OUTFILE="outputs/eval/predictions_${VARIANT}.jsonl"

    if [ -f "$OUTFILE" ]; then
        COUNT=$(wc -l < "$OUTFILE" | tr -d ' ')
        if [ "$COUNT" -ge 100 ]; then
            log "Predictions for $VARIANT already exist ($COUNT examples). Skipping."
            continue
        fi
        log "Predictions for $VARIANT only have $COUNT/100 examples. Regenerating..."
    fi

    log "Generating predictions for $VARIANT ($MODEL_ID)..."
    START=$(date +%s)

    python -m sft.eval.generate_via_api \
        --model-label "$VARIANT" \
        --max-examples 100 \
        --api-base "$API_BASE" \
        --model-id "$MODEL_ID" \
        2>&1 | tee -a "$LOGFILE"

    ELAPSED=$(( $(date +%s) - START ))
    log "  $VARIANT done in ${ELAPSED}s"
done

# ---- Phase 2: Deepeval scoring ----
log "=== PHASE 2: Deepeval scoring ==="

for variant in base sft rlhf; do
    PRED_FILE="outputs/eval/predictions_${variant}.jsonl"
    OUT_FILE="outputs/eval/deepeval_${variant}.json"

    if [ -f "$OUT_FILE" ]; then
        log "Deepeval scores for $variant already exist. Skipping."
        continue
    fi

    if [ ! -f "$PRED_FILE" ]; then
        log "WARNING: No predictions for $variant at $PRED_FILE. Skipping."
        continue
    fi

    COUNT=$(wc -l < "$PRED_FILE" | tr -d ' ')
    log "Scoring $variant ($COUNT predictions)..."
    START=$(date +%s)

    python -m sft.eval.deepeval_judge \
        --predictions "$PRED_FILE" \
        --output "$OUT_FILE" \
        --max-examples "$COUNT" \
        2>&1 | tee -a "$LOGFILE"

    ELAPSED=$(( $(date +%s) - START ))
    log "  $variant done in ${ELAPSED}s"
done

# ---- Summary ----
log "=== BATCH COMPLETE ==="
log "Outputs:"
for variant in base sft rlhf; do
    METRICS="outputs/eval/deepeval_${variant}.json"
    if [ -f "$METRICS" ]; then
        python3 -c "
import json
d = json.load(open('$METRICS'))
print(f'  $variant: correctness={d[\"metrics\"].get(\"mean_correctness\",0):.3f} '
      f'specificity={d[\"metrics\"].get(\"mean_specificity\",0):.3f} '
      f'actionability={d[\"metrics\"].get(\"mean_actionability\",0):.3f} '
      f'relevancy={d[\"metrics\"].get(\"mean_answer_relevancy\",0):.3f} '
      f'(${d.get(\"n_total\",0)} examples)')
"
    else
        echo "  $variant: no results yet"
    fi
done | tee -a "$LOGFILE"

log "Log saved to $LOGFILE"

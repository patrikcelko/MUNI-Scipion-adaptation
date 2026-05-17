# Mock worker image for smoke / CI testing.

FROM alpine:3.19

COPY --chmod=755 <<'SCRIPT' /bin/bash
#!/bin/sh
echo "[MOCK-WORKER] Job started at $(date -Iseconds)"
echo "[MOCK-WORKER] Simulated args: $*"
sleep 1
echo "[MOCK-WORKER] Job completed successfully."
exit 0
SCRIPT

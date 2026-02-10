## 1. Scheduler Core
- [x] 1.1 Add scheduler config model (reset mode, window duration, wake delay)
- [x] 1.2 Create `src/scheduler.py` with per-provider worker loop and lifecycle (`start`, `stop`)
- [x] 1.3 Integrate scheduler startup/shutdown into `src/main.py`

## 2. Wake-Up Outcome Handling
- [x] 2.1 Extend provider wake-up result with structured failure classification
- [x] 2.2 Update Claude and Codex providers to populate normalized failure kind
- [x] 2.3 Implement scheduler decision logic for success/auth/rate-limit/transient outcomes

## 3. Persistence and Recovery
- [x] 3.1 Add `data/scheduler_state.json` persistence with atomic write/replace
- [x] 3.2 Load persisted state on startup and recover overdue providers immediately
- [x] 3.3 Add fallback behavior for missing/corrupt state files

## 4. Retry, Backoff, and Auth Pause
- [x] 4.1 Implement exponential backoff for transient wake-up failures
- [x] 4.2 Pause provider scheduling on auth failure and trigger device auth flow
- [x] 4.3 Resume scheduling automatically after auth is restored

## 5. Telegram UX
- [x] 5.1 Add `/schedule` command for scheduler state visibility
- [x] 5.2 Add `/wake <provider>` command for manual immediate wake-up
- [x] 5.3 Add Telegram alerts for pause/resume and repeated failure states

## 6. Testing
- [x] 6.1 Add unit tests for reset-time computation (rolling and clock-aligned)
- [x] 6.2 Add unit tests for retry/backoff and auth pause transitions
- [x] 6.3 Add tests for state persistence and restart recovery
- [x] 6.4 Add command-handler tests for `/schedule` and `/wake`

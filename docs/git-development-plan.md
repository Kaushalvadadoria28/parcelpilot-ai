# Git Development Plan

Status: **planning only — no code, no `git init`, no commits yet.** This converts Part R of `docs/system-design.md` into a real, incremental engineering roadmap. The architecture itself is treated as approved and is not revisited here except where this document surfaces a concrete data-handling/process decision that Part R didn't need to make.

## 0. Current repository state (checked before writing this plan)

```
$ git status
fatal: not a git repository (or any of the parent directories): .git
```

The working directory is **not yet a git repository**. It currently contains only `data/` (the supplied assessment pack, untracked) and `docs/` (the audit + design documents produced so far). There is no existing history to protect and no branch to reconcile — Milestone 0 below starts with `git init` on a single `main` branch.

## 1. Branch strategy

**Recommendation: trunk-based — commit directly to `main`, no per-milestone feature branches.**

This is a solo-authored, dependency-ordered build (each milestone in Part R explicitly depends on the previous one being correct). A branch-per-milestone-with-merge-commit workflow would add merge ceremony without adding review value, since there's no second reviewer and the milestones aren't developed concurrently. Short-lived branches are reserved for genuine exploratory spikes if one comes up (e.g., prototyping a LangGraph node shape before committing to it) and would be deleted after squashing into the milestone commit, not kept as permanent history. If you'd prefer visible PRs (e.g., to demonstrate a team-style review habit for the evaluator), that's a one-line change to this plan — flagging it as a decision point rather than assuming.

## 2. Data-handling policy — what is public, what stays local

This is the one place this plan makes a judgment call beyond pure engineering, so it's called out explicitly rather than buried in a `.gitignore` line.

**The problem:** the assessment's own README states the workbook is "a synthetic dataset created for a hiring assessment," so there's no real customer-privacy issue. The actual risk is different: several documents already produced during the audit phase (`docs/data-pack-analysis.md`, `docs/evaluation-cases.md`, `docs/conflict-analysis.md`) **quote the source PDFs verbatim and enumerate the exact hidden-test-shaped answers** (fee amounts, SLA numbers, which historical resolutions are wrong, and why). Submission requirement #1 says the repository must be **public**. Publishing those specific files verbatim would mean publishing a large fraction of CalQuity's own hidden-answer key on the public internet, discoverable by any future candidate who finds this repo — that's an assessment-integrity problem for CalQuity, independent of whether the data is "real." The raw PDFs/`xlsx` themselves have the same issue in a blunter form.

**Resolution adopted:**

| Category | Treatment | Rationale |
|---|---|---|
| Raw assessment pack (`data/documents/*.pdf`, `data/*.xlsx`) | **Never committed.** Gitignored. | These are CalQuity's proprietary assessment materials, not project source code. |
| Full-detail audit docs already written (`docs/data-pack-analysis.md`, `docs/evaluation-cases.md`, `docs/conflict-analysis.md`) | **Kept locally, not pushed to the public repo.** Moved under a git-ignored `docs/_internal/` at Milestone 0. | These quote real document text and enumerate exact hidden-test answers. They did their job (informing this design) and remain available to me locally, and can be shared with CalQuity directly/privately if useful, but don't belong in a public, permanently-indexed repository. |
| `docs/source-authority.md`, `docs/data-model.md` | Also moved to `docs/_internal/`, for consistency — they reference the same real numbers/IDs even though they're framed as methodology. | Treating all five audit docs the same way avoids a subjective line-by-line judgment call about which specific numbers are "too revealing." |
| `docs/system-design.md`, this file (`docs/git-development-plan.md`) | **Public.** | Architecture/process documents — describe the *mechanism* (tiers, state machine, layering) rather than reproducing the dataset's real numbers as an answer key. They already read this way; no rewrite needed. |
| Required deliverables (`README.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT_NOTE.md`, `docs/AI_TOOL_USAGE.md`, `docs/DEVELOPMENT_LOG.md`) | **Public**, written generically (illustrative examples, not the real dataset's exact figures). | These are the actual submission deliverables; they describe the approach, not reproduce the answer key. |
| `config/doc_manifest.yaml` (structural metadata: filename → type/version/status/effective date/tier) | **Public.** | Describes *shape*, not content — "this file is version 3, status current" isn't part of the hidden test. |
| `config/contract_overrides.yaml` (the real transcribed contract terms — fee amounts, thresholds) | **Never committed.** Gitignored, supplied/generated locally alongside the real pack. | This is a structured, even more exploitable form of the same answer-key concern as the raw PDFs. |
| `config/contract_overrides.example.yaml` | **Public**, populated with an obviously fictitious example account and made-up numbers. | Proves the schema and lets the rule engine run against fixtures without needing the real file. |
| `tests/fixtures/*` (synthetic accounts/orders/tickets/documents, fictional company names, made-up numbers, same *shape* as the real pack) | **Public.** | Lets the entire test suite and CI run without the proprietary pack ever being present — and doubles as proof the system is genuinely data-driven, not hard-coded, which is exactly what the brief warns evaluators will check. |
| `eval/run_eval_cases.py` (the harness code) | **Public.** | Just code — takes a data directory as input. |
| The *output* of running that harness against the real pack, and any locally-kept categorized real-case list used to drive it | **Local only.** | Same answer-key concern as above; the harness is judged by what it does, not by shipping the graded answers. |

**How the evaluator obtains/supplies the data:** the evaluator already possesses the original data pack (they issued it). `README.md`'s setup section will say, verbatim in spirit: *"This repository does not include CalQuity's ParcelPilot assessment data pack. Place the documents you were given under `data/documents/` and the workbook at `data/ParcelPilot_Assessment_Data.xlsx`, then run the ingestion scripts (Milestone 0 below) to generate the local database and document index."* This keeps the repo honest and reproducible for anyone who already has the pack (the evaluator, or the candidate re-cloning), without redistributing it. The **hosted demo** is a separate concern: I will run ingestion once against the real pack in the deployed environment (see Milestone 10) so the hosted app is fully functional out of the box for anyone clicking the demo link — the pack reaches the deployed instance through the hosting provider's file/secret mechanism, never through a public git commit.

## 3. `.gitignore` contents

```gitignore
# Environments / secrets
.env
.env.*
!.env.example

# Raw assessment data pack (never committed — see docs/git-development-plan.md §2)
/data/documents/*.pdf
/data/ParcelPilot_Assessment_Data.xlsx
/config/contract_overrides.yaml

# Internal audit docs kept local-only (see docs/git-development-plan.md §2)
/docs/_internal/

# Generated/build artifacts (rebuilt by ingestion scripts, not source)
/backend/**/*.db
/backend/**/*.sqlite3
app.db
*.sqlite3
/backend/data_index/
/backend/.doc_index_cache/

# Python
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.venv/
venv/
*.egg-info/

# Node / frontend
node_modules/
.next/
dist/
build/
frontend/.env.local

# Local eval output (may contain real-data specifics — see §2)
/eval/output/
/eval/local_cases/

# OS / editor
.DS_Store
Thumbs.db
```

## 4. Milestones

Each milestone below follows Part R's order exactly, with one addition (Milestone 12) justified in its own entry as a process step, not an architecture change.

---

### Milestone 0 — Repository scaffold, environment/configuration, idempotent ingestion

1. **Objective:** Stand up a runnable, empty-but-structured repository — config loading, dependency manifests, data-handling scaffolding — then implement the idempotent ingestion pipeline (structured workbook → SQLite, documents → metadata-tagged chunk index) proven against synthetic fixtures.
2. **Why here:** Everything else in the system reads from what ingestion produces. Building it first, and proving it's idempotent and fixture-driven before any business logic exists, directly answers the brief's warning that evaluator data may be substituted.
3. **Files created/modified:**
   - `.gitignore`, `.env.example`, `README.md` (stub), `pyproject.toml`/`requirements.txt`, `requirements-dev.txt`
   - `backend/config.py` (Pydantic settings: `DATA_DIR`, `DB_PATH`, `SNAPSHOT_TIME`, `ANTHROPIC_API_KEY`, etc.)
   - `backend/ingestion/build_db.py`, `backend/ingestion/build_doc_index.py`
   - `config/doc_manifest.yaml`, `config/contract_overrides.example.yaml`
   - `data/README.md`, `data/documents/.gitkeep`
   - `docs/_internal/` created and the five detailed audit docs moved into it (git-ignored)
   - `tests/fixtures/synthetic_dataset.py` (programmatic fixture accounts/orders/tickets + fixture "documents" as plain text with manifest-shaped metadata)
   - `tests/test_ingestion.py`
4. **Dependencies on earlier milestones:** none (first milestone).
5. **Acceptance criteria:** `pip install -r requirements.txt` succeeds; running the ingestion scripts against the fixture dataset produces a SQLite DB with the expected table shapes/row counts and a document-chunk index with correct metadata; running ingestion twice in a row produces identical output (true idempotency, not just "doesn't crash"); no raw pack files or `docs/_internal/*` are tracked by git.
6. **Tests that must pass:** `tests/test_ingestion.py` (schema shape, idempotency, snapshot-time sourced from config not wall clock, metadata attachment on fixture documents).
7. **Manual verification:** run both ingestion scripts once against the real local pack (already present in the working directory) and eyeball the resulting row counts (4 accounts / 6 orders / 7 tickets) and chunk count — confirms it isn't just fixture-shaped-correct but real-data-correct too. Nothing from this run is committed.
8. **Proposed commits:**
   - `chore: initialize ParcelPilot project scaffold` — repo layout, `.gitignore`, `.env.example`, README stub, dependency manifests, config module, data placeholders, internal-docs relocation.
   - `feat(data): add idempotent ingestion pipeline for structured and document sources` — `build_db.py`, `build_doc_index.py`, manifests, fixtures, `test_ingestion.py`.
9. **Out of scope for this milestone:** no FastAPI, no agent, no rule engine, no auth — ingestion only produces data, it does not yet serve or reason over it.

---

### Milestone 1 — Structured data access layer + deterministic rule engine

1. **Objective:** A typed, read-only query layer over the ingested SQLite tables, and a pure-Python rule engine implementing cancellation eligibility, service-credit eligibility/amount, and SLA target/breach math — all deterministic, all unit-tested without any LLM involved.
2. **Why here:** Per Part R, this is the highest-risk correctness surface in the whole system and must be proven correct in isolation before authorization, retrieval, actions, or the agent are layered on top of it. It depends only on Milestone 0's ingested DB.
3. **Files created/modified:**
   - `backend/db/connection.py`, `backend/db/queries.py` (read-only `get_account`, `get_order`, `list_orders`, `get_ticket`, `list_tickets`)
   - `backend/models.py` (Pydantic domain models: `Account`, `Order`, `Ticket`, `CancellationResult`, `CreditResult`, `SlaResult`)
   - `backend/rules/contract_overrides.py` (loads `config/contract_overrides.yaml` if present, else the example file — see §2)
   - `backend/rules/cancellation.py`, `backend/rules/service_credit.py`, `backend/rules/sla.py`
   - `tests/test_data_access.py`, `tests/test_rule_engine.py`
4. **Dependencies:** Milestone 0 (ingested DB + fixtures + config).
5. **Acceptance criteria:** query functions return typed, correctly-joined results with no cross-table leakage bugs; cancellation rules correctly cover all four order statuses × contract-waiver on/off; credit rules correctly cover the default threshold/amount, a fixture "fixed amount + different threshold" contract override, and the >INR 1,000 manager-approval boundary; SLA rules correctly compute elapsed-vs-target using the injected snapshot-time constant, never the system clock, for both plan-default and contract-override targets.
6. **Tests that must pass:** `test_data_access.py`, `test_rule_engine.py` — both fully parametrized over `tests/fixtures/synthetic_dataset.py` (fictional accounts/contracts mirroring the real pack's *pattern*, not its real names/numbers).
7. **Manual verification:** none required beyond the test suite (pure logic); optionally, a throwaway local script run against the real pack to sanity-check a couple of computed values, not committed.
8. **Proposed commits:**
   - `feat(data): add structured data access layer for accounts, orders, and tickets`
   - `feat(rules): implement deterministic cancellation, service-credit, and SLA rule engine`
9. **Out of scope:** no authorization checks yet (query functions are still unscoped/trusted callers only — enforced in Milestone 2), no document retrieval, no HTTP surface.

---

### Milestone 2 — Authorization / Principal layer

1. **Objective:** Introduce the single enforcement chokepoint — a `Principal` model and a scoped-repository wrapper around Milestone 1's query functions — so that account isolation and role permissions are structural, not optional.
2. **Why here:** Per Part R, this must exist before any tool (retrieval, action, or agent) is built on top of the data layer, so nothing is ever wired up in an unscoped state that would need retrofitting.
3. **Files created/modified:**
   - `backend/auth/principal.py` (`Principal`, `Role` enum: `customer` / `internal_agent` / `internal_admin`)
   - `backend/auth/authorize.py` (`ScopedRepository` wrapping Milestone 1's query functions; raises `AuthorizationError` before returning data, not after filtering it)
   - `backend/auth/permissions.py` (role → allowed action-type / tool matrix, used now for data scoping and later, unchanged, by Milestone 4/5)
   - `backend/auth/mock_sessions.py` (persona registry: a small fixed list of demo personas mapping to `Principal`s, consumed later by the API layer)
   - `tests/test_access_control.py`
4. **Dependencies:** Milestone 1 (wraps its query functions).
5. **Acceptance criteria:** a customer `Principal` requesting another account's order/ticket raises `AuthorizationError` *before* any row is fetched from storage (verified by asserting on the query layer, not just the returned value); same-account access succeeds; an internal `Principal` can read across accounts; sensitive fields (`historical_resolution`, `assigned_to`, `csm`) are stripped from any customer-role response even for their own account's rows.
6. **Tests that must pass:** `test_access_control.py` — cross-account denial, same-account success, internal cross-account success, sensitive-field stripping present/absent by role. (Adversarial "trick the LLM into asking for this" variants are deferred to Milestone 9, once there's an agent to try tricking — at this milestone, the authorization function itself is tested directly.)
7. **Manual verification:** none beyond tests (no UI/agent yet).
8. **Proposed commit:** `feat(auth): enforce account- and role-scoped data access`.
9. **Out of scope:** no session/token issuance over HTTP yet (that's Milestone 6's `/auth` route) — this milestone only builds the enforcement logic and an in-process persona registry.

---

### Milestone 3 — Document retrieval + metadata/precedence

1. **Objective:** A `search_documents` capability over the Milestone 0 document-chunk index that deterministically filters by status/version/customer scope before any ranking happens, and labels same-topic results by authority tier so conflicts are visible rather than silently adjudicated.
2. **Why here:** Depends on Milestone 0 (chunk index) and Milestone 2 (Principal, since a contract chunk must be scoped exactly like a data row). Built before the action layer and agent so retrieval is a proven, safe capability by the time anything else calls it.
3. **Files created/modified:**
   - `backend/retrieval/index.py` (BM25 index built from `doc_manifest.yaml` + ingested chunks)
   - `backend/retrieval/precedence.py` (deterministic filter: drop `status=deprecated` unless historical mode; drop chunks whose `customer_account_id` doesn't match the caller's scope; tag same-topic multi-tier results as `applicable_source` vs `overridden`/conflicting)
   - `backend/retrieval/search.py` (`search_documents(principal, query, ...)` — the tool-facing function combining the above)
   - `tests/test_retrieval.py`
4. **Dependencies:** Milestone 0 (index), Milestone 2 (Principal/scoping).
5. **Acceptance criteria:** a deprecated fixture document is excluded from default queries even when lexically the closest match; a customer principal never receives another fixture customer's contract chunk; a query touching a topic covered by both a contract-tier and policy-tier fixture chunk returns both, correctly labeled (one `applicable_source=true`, the other `overridden=true`), not silently dropped.
6. **Tests that must pass:** `test_retrieval.py`, parametrized over fixture documents mirroring the real corpus shape (current/deprecated pair, two fictional customer contracts, one SOP, one product-guide-with-known-issues fixture).
7. **Manual verification:** run `search_documents` once against the real local document index (built in Milestone 0's manual step) to confirm v2/deprecated exclusion and no cross-customer contract leakage on real data; not committed.
8. **Proposed commit:** `feat(retrieval): add metadata-filtered document search with deterministic precedence resolution`.
9. **Out of scope:** no agent-level "which document is relevant to this free-text question" reasoning yet — that's Milestone 5's job, calling into this capability.

---

### Milestone 4 — Action / state / confirmation layer

1. **Objective:** The propose → confirm/cancel → execute action lifecycle, with `execute` reachable only from `confirm`, never exposed as a directly callable capability — proven as a standalone, LLM-independent module.
2. **Why here:** Per Part R, this is built and proven safe *before* the agent exists, so the agent is later wired to a capability that is already incapable of unconfirmed execution, rather than trusting the agent layer to enforce that itself.
3. **Files created/modified:**
   - `backend/actions/models.py` (`Action`, `ActionStatus`: `PENDING` / `EXECUTED` / `CANCELLED`)
   - `backend/actions/store.py` (SQLite `actions` + `audit_log` tables, CRUD)
   - `backend/actions/service.py` (`propose_action`, `confirm_action`, `cancel_action`; `execute_action` is a private function called only from inside `confirm_action`)
   - `tests/test_actions.py`
4. **Dependencies:** Milestone 1 (shares the DB), Milestone 2 (role-restricted action types).
5. **Acceptance criteria:** `propose_action` never mutates business tables; `confirm_action` transitions `PENDING → EXECUTED` exactly once and writes an `audit_log` row; a second `confirm_action` call on an already-resolved id is rejected, not silently re-executed; `cancel_action` transitions `PENDING → CANCELLED`; a customer principal cannot propose an action type reserved for internal roles.
6. **Tests that must pass:** `test_actions.py` — propose→confirm happy path, propose→cancel, double-confirm rejected, confirm on unknown/already-resolved id rejected, role-restricted action type rejected.
7. **Manual verification:** none beyond tests (no UI/agent trigger yet).
8. **Proposed commit:** `feat(actions): add confirmation-gated action lifecycle with audit logging`.
9. **Out of scope:** no HTTP endpoints yet (Milestone 6), no agent-driven proposal yet (Milestone 5) — this milestone proves the state machine in isolation, called directly from tests.

---

### Milestone 5 — LangGraph agent orchestration

1. **Objective:** Wire Milestones 1–4 into the controlled multi-node agent workflow (classify → plan tools → execute tools → resolve conflicts → synthesize → check uncertainty → check escalation → propose action → checkpoint), including the LLM client wrapper and system prompt.
2. **Why here:** Only now that data access, rules, authorization, retrieval, and actions are each independently correct and tested does it make sense to assemble them — the agent is composed from already-trustworthy parts rather than being where bugs in those parts would first surface.
3. **Files created/modified:**
   - `backend/llm/client.py` (thin, provider-agnostic Anthropic client wrapper; injectable/mockable for tests)
   - `backend/agent/state.py` (typed graph state)
   - `backend/agent/graph.py` (node wiring, checkpoint before `propose_action`)
   - `backend/agent/tools.py` (LLM-callable tool wrappers around Milestones 1–4, always threading the current `Principal` server-side)
   - `backend/agent/prompts.py` (cite-only-given-sources / refuse-if-unsupported system prompt)
   - `tests/test_agent_workflow.py`
4. **Dependencies:** Milestones 1, 2, 3, 4.
5. **Acceptance criteria:** single-tool fixture questions answered correctly with citations; multi-tool fixture chains (order → account → contract override → rule engine) produce results matching Milestone 1's rule engine output exactly (no drift between standalone and agent-mediated results); an unsupported fixture request triggers escalation, not a fabricated answer; a fixture case with an unknown required fact (e.g., unresolved fault flag) triggers "needs verification," not a guess; the agent never calls a tool the current `Principal` isn't permitted to call.
6. **Tests that must pass:** `test_agent_workflow.py`, parametrized over fixtures for single-tool / multi-tool / missing-info / ambiguous / unsupported cases. Tests exercising the LLM call are split: most run against an injectable fake LLM client for deterministic, key-free CI; a smaller set marked `@pytest.mark.llm` run against the real Anthropic API only when a key is present (and are skipped otherwise), so public CI never requires a paid key to pass.
7. **Manual verification:** a small local CLI harness (`scripts/chat_cli.py`) run interactively against the real local data pack — first true end-to-end smoke test of the reasoning chain. Not committed as output.
8. **Proposed commits:**
   - `feat(agent): implement LangGraph state machine and tool bindings`
   - `feat(agent): add source-conflict resolution and escalation logic to the workflow`
9. **Out of scope:** no HTTP surface yet (Milestone 6), no proactive-insights tool yet (Milestone 7).

---

### Milestone 6 — FastAPI / API integration

1. **Objective:** Expose the agent, action confirmation, and mocked auth over HTTP, making the human-in-the-loop boundary real across a network call rather than only in-process.
2. **Why here:** The agent is proven as a callable Python component first; wrapping it in HTTP is now a comparatively low-risk integration step rather than where core correctness is first tested.
3. **Files created/modified:**
   - `backend/api/main.py`, `backend/api/deps.py` (`get_principal` dependency)
   - `backend/api/routes/auth.py`, `backend/api/routes/chat.py`, `backend/api/routes/actions.py`, `backend/api/routes/admin.py`
   - `tests/test_api.py` (FastAPI `TestClient`, fixture data, fake LLM client)
4. **Dependencies:** Milestones 2 (principal/session), 4 (actions), 5 (agent).
5. **Acceptance criteria:** a full HTTP chat round trip returns an answer, citations, tool trace, and an optional pending action; `/actions/{id}/confirm` and `/cancel` correctly gate execution over HTTP; a request scoped to one persona attempting another account's resources is rejected at the API layer using the same Milestone 2 authorization, not a new/weaker check; missing/invalid persona header returns a clean 401.
6. **Tests that must pass:** `test_api.py` — chat happy path, confirm/cancel over HTTP, cross-account HTTP denial, malformed-auth handling.
7. **Manual verification:** run `uvicorn` locally, exercise the API via curl/HTTPie against the real local pack, confirm the OpenAPI docs page renders sanely.
8. **Proposed commit:** `feat(api): expose chat, action confirmation, and admin trace endpoints via FastAPI`.
9. **Out of scope:** no frontend yet (Milestone 8), no insights endpoint yet (Milestone 7).

---

### Milestone 7 — Proactive issue detection

1. **Objective:** The four deterministic analytics from `system-design.md` Part K (SLA breach risk, known-issue correlation, multi-customer impact, ticket concentration), exposed as an internal-only endpoint.
2. **Why here:** Per Part R, deliberately after the core chatbot is solid and stable — this is an additive internal capability built on data/auth that already exist, and must not risk destabilizing the primary chat path.
3. **Files created/modified:**
   - `backend/insights/breach_risk.py`, `backend/insights/known_issue_correlation.py`, `backend/insights/multi_customer.py`, `backend/insights/concentration.py`, `backend/insights/service.py`
   - `backend/api/routes/insights.py` (`/insights`, internal-role only)
   - `tests/test_insights.py`
4. **Dependencies:** Milestones 1 (data), 2 (role gating), 6 (route wiring).
5. **Acceptance criteria:** each analytic is a pure, snapshot-time-aware function with a fixture scenario proving it fires correctly and a negative-fixture scenario proving it doesn't fire on unrelated data (mirroring the real "don't reuse a resolved known issue" rule); `/insights` returns 403 for a customer-role principal via the existing Milestone 2 chokepoint.
6. **Tests that must pass:** `test_insights.py` — one positive + one negative fixture case per analytic, plus the role-gating check.
7. **Manual verification:** hit `/insights` as an internal persona against the real local pack, confirm it surfaces the real breach-risk and known-issue-correlation findings identified during the audit. Not committed.
8. **Proposed commit:** `feat(ops): add deterministic proactive issue detection (SLA risk, known-issue correlation, multi-customer and concentration signals)`.
9. **Out of scope:** no LLM-narrated summary of insights yet — that can be a thin follow-up once the UI exists to show it meaningfully; not required for this milestone's acceptance.

---

### Milestone 8 — Frontend / UI

1. **Objective:** A Next.js chat interface — persona switcher, chat surface, tool-trace panel, sources panel, pending-action confirmation card, internal insights panel — built against the now-stable Milestone 6/7 API contract.
2. **Why here:** Deferred until the backend response shapes are proven and stable, so the UI is built against a real contract instead of a guessed one that would need rework.
3. **Files created/modified:**
   - `frontend/` Next.js + TypeScript + Tailwind scaffold
   - `frontend/app/*` pages, `frontend/components/ToolTracePanel.tsx`, `SourcesPanel.tsx`, `PendingActionCard.tsx`, `InsightsPanel.tsx`
   - `frontend/lib/api.ts` (typed API client)
4. **Dependencies:** Milestones 6, 7 (the API surface being rendered).
5. **Acceptance criteria:** persona switcher works for all mock personas; chat round trip renders answer + sources + tool trace; a pending action renders as a visually distinct card with working Confirm/Cancel buttons that call the real endpoints and disable themselves after use (no double-submit); internal persona sees the Insights panel, customer persona does not; `next build` succeeds; no horizontal scroll at reasonable widths.
6. **Tests that must pass:** a small, targeted set of component/integration tests focused on safety-relevant UI behavior — specifically that Confirm/Cancel call the correct endpoint exactly once and disable after use — rather than exhaustive UI snapshotting, which would be low-value here.
7. **Manual verification:** run frontend + backend together locally and manually walk the Part Q demo script beats end-to-end.
8. **Proposed commits:**
   - `feat(ui): scaffold chat interface with persona switcher and core chat flow`
   - `feat(ui): add tool trace, sources, pending-action confirmation, and insights panels`
9. **Out of scope:** no design-system polish beyond what's needed for legibility; no mobile-specific layout work.

---

### Milestone 9 — Full testing, adversarial testing, and evaluation harness

1. **Objective:** Close remaining coverage gaps, add the adversarial suite proving each attack is neutralized structurally, wire up public CI (fixture-based, key-free), and build the local-only evaluation harness that runs against the real pack before submission.
2. **Why here:** Only after every layer exists end-to-end (including UI) does it make sense to test breadth and adversarial depth as a dedicated pass, rather than trying to anticipate every attack while individual layers are still being built.
3. **Files created/modified:**
   - `tests/test_adversarial.py`
   - `eval/run_eval_cases.py` (harness code, public; consumes the real pack + a locally-kept case list, both gitignored per §2)
   - `pyproject.toml`/`pytest.ini` markers for `@pytest.mark.llm`
   - `.github/workflows/tests.yml` (fixture-based suite only, no secrets required)
4. **Dependencies:** all prior milestones.
5. **Acceptance criteria:** the full fixture-based pytest suite is green in CI with no API key or proprietary data present; each adversarial test asserts the structural mechanism that neutralizes the attack (e.g., an `AuthorizationError` raised before data access, independent of prompt phrasing) rather than asserting "the model happened to refuse this time"; the local eval harness, run against the real pack, produces a scorecard used to find and fix any real gaps before deployment.
6. **Tests that must pass:** `test_adversarial.py` — prompt injection via a crafted fixture chunk, chat-based role-escalation attempts, chat-based cross-account probing via social-engineering phrasing, attempts to elevate a fixture historical-resolution to authoritative status, attempts to invoke an action-execution capability that doesn't exist in the tool set. Plus the full existing suite, still green.
7. **Manual verification:** actually run the eval harness against the real local pack, read the scorecard, and fix any genuine findings before proceeding to deployment — this is the last correctness gate before the system is considered feature-complete.
8. **Proposed commits:**
   - `test(security): add adversarial tests for access control, action execution, and source authority bypass attempts`
   - `chore(ci): add automated test workflow and local evaluation harness`
9. **Out of scope:** load/performance testing (not relevant at this data scale); fuzzing beyond the specific adversarial patterns named in the brief.

---

### Milestone 10 — Deployment

1. **Objective:** Host the backend and frontend, with the real data pack reaching the deployed backend through a non-git mechanism, and secrets supplied via the host's environment/secret manager.
2. **Why here:** Only after the system is functionally complete and tested — deployment configuration shouldn't be built against a moving target.
3. **Files created/modified:**
   - `backend/Dockerfile` (or host-specific config, e.g. `render.yaml`/`fly.toml`)
   - `frontend` deploy config (e.g. `vercel.json` if needed)
   - `scripts/deploy_check.sh` (post-deploy smoke test: health check + one scripted chat call)
   - `docs/deployment.md` (how the real pack reaches the hosted backend without being in git)
4. **Dependencies:** all prior milestones (nothing to deploy before the system works).
5. **Acceptance criteria:** hosted backend responds to a health check and a real chat round trip; hosted frontend renders and talks to the hosted backend; the real pack is present in the deployed environment via the documented mechanism, not baked into the public image or repo; the Anthropic API key is supplied via the host's secret manager, never committed.
6. **Tests that must pass:** `scripts/deploy_check.sh` against the live URL (not part of the pytest suite).
7. **Manual verification:** click through the hosted app end-to-end, matching the Part Q demo beats, before recording the video.
8. **Proposed commit:** `chore(deploy): add production deployment configuration for backend and frontend`.
9. **Out of scope:** managed Postgres migration, multi-region hosting, autoscaling — not warranted at this scale (matches the "what not to over-engineer" call in Part A).

---

### Milestone 11 — Final documentation and demo preparation

1. **Objective:** Finalize all submission deliverables so they accurately describe the system as actually built.
2. **Why here:** Written last so documentation reflects reality rather than the original plan.
3. **Files created/modified:**
   - `README.md` (finalized, full structure per the assessment's requested contents)
   - `docs/ARCHITECTURE.md`, `docs/PRODUCT_NOTE.md`, `docs/AI_TOOL_USAGE.md`
   - `docs/DEVELOPMENT_LOG.md` (finalized — this is reviewed/tidied here, not written fresh; see §5 below on how it's actually maintained throughout)
   - Demo storyboard notes (not the video file itself)
4. **Dependencies:** all prior milestones.
5. **Acceptance criteria:** a fresh clone of the public repo, following only `README.md`, supplied with a local copy of the data pack, produces a working local instance; all links (hosted URL, repo) are correct; the AI-tool-usage statement is accurate.
6. **Tests that must pass:** a literal fresh-clone dry run is the closest thing to a test for documentation quality; full pytest suite still green.
7. **Manual verification:** full read-through of every doc against the actual final code; record the ~5-minute demo per Part Q of `system-design.md`.
8. **Proposed commit:** `docs: add architecture, product, and AI-tool-usage notes; finalize README`.
9. **Out of scope:** the recorded video file itself is not committed to the repo (linked from the README/submission form instead).

---

### Milestone 12 — Repository readiness & final security review *(added)*

1. **Objective:** A dedicated pass confirming the repository is genuinely clean before submission — no secrets, no proprietary raw content, coherent history, reproducible from a fresh clone.
2. **Why added, and why it doesn't count as an architecture change:** this is a process/checklist step explicitly requested under "GITHUB-READY STANDARD," which Milestone 11 (writing docs) doesn't fully cover on its own. It produces no new features and changes no design decisions from `system-design.md` — it's the final QA pass on the plan Part R already specified.
3. **Files created/modified:** none expected in the normal case; may produce small corrective diffs if the review finds something (e.g., a stray debug print, an under-scoped `.gitignore` entry).
4. **Dependencies:** all prior milestones.
5. **Acceptance criteria:** `git log -p` scan shows no secrets or proprietary raw pack content ever committed (not just "not present now" — checked across history, since Milestone 0 happens before this and mistakes there would still be in history); `.gitignore` covers every generated-artifact path actually produced by the running system; a second fresh-clone dry run succeeds; full test suite green; the commit history, read top to bottom, tells a coherent story matching Part R.
6. **Tests that must pass:** full suite, re-run once more.
7. **Manual verification:** manual `git log --oneline` read-through; fresh-clone dry run.
8. **Proposed commit:** `chore: repository cleanup and pre-submission security review` — **created only if the review actually finds something to fix.** A clean review that finds nothing legitimately produces zero commits at this milestone, and that's the correct outcome to report, not a reason to invent a no-op commit.
9. **Out of scope:** nothing new — this milestone only ever removes or tightens, never adds a feature.

## 5. Development log discipline

`docs/DEVELOPMENT_LOG.md` is created at Milestone 0 (empty, with its structure) and appended to **as decisions are actually made during implementation**, not written retroactively at Milestone 11. Entries will only be added when a real decision point comes up during a milestone (e.g., "chose BM25 over embeddings because X," "excluded the real contract-overrides file from git because Y") — Milestone 11 only reviews and tidies wording, it doesn't backfill invented history.

## 6. Summary: commit count and shape

Roughly 17–18 commits across 13 milestones (12 substantive + 1 conditional review pass), each tied to a milestone's tested, working functionality — no single "everything" commit, no batches of trivial ones. Total commit list in order:

```
chore: initialize ParcelPilot project scaffold
feat(data): add idempotent ingestion pipeline for structured and document sources
feat(data): add structured data access layer for accounts, orders, and tickets
feat(rules): implement deterministic cancellation, service-credit, and SLA rule engine
feat(auth): enforce account- and role-scoped data access
feat(retrieval): add metadata-filtered document search with deterministic precedence resolution
feat(actions): add confirmation-gated action lifecycle with audit logging
feat(agent): implement LangGraph state machine and tool bindings
feat(agent): add source-conflict resolution and escalation logic to the workflow
feat(api): expose chat, action confirmation, and admin trace endpoints via FastAPI
feat(ops): add deterministic proactive issue detection (SLA risk, known-issue correlation, multi-customer and concentration signals)
feat(ui): scaffold chat interface with persona switcher and core chat flow
feat(ui): add tool trace, sources, pending-action confirmation, and insights panels
test(security): add adversarial tests for access control, action execution, and source authority bypass attempts
chore(ci): add automated test workflow and local evaluation harness
chore(deploy): add production deployment configuration for backend and frontend
docs: add architecture, product, and AI-tool-usage notes; finalize README
chore: repository cleanup and pre-submission security review   # only if needed
```

---

*Next: awaiting your go-ahead to begin Milestone 0. Per your instructions, before each commit I will show you what was implemented, why, which files changed, what tests/checks were run, known limitations, and the proposed commit message — then commit only after you're satisfied.*

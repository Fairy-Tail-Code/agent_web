# Architecture Optimization Plan

**Date:** 2026-06-07  
**Scope:** Full project refactoring as a "turning point" for maintainable iteration

---

## Priority 1: CRITICAL Security Fixes

### S1. Path traversal in office tools (CRITICAL)
- **Files:** `config/office_config.py:77-82`, `Agents/tools/office_file_toolkit.py:52-63`
- **Fix:** Add path validation to reject absolute paths outside configured directories
- Validate `resolve_office_input_path` restricts to `OFFICE_BASE_DIR`
- Restrict `file_exists` to only probe within office directories

### S2. SQL injection via f-string DDL (HIGH)
- **Files:** `auth/kb_metadata.py:286-287`, `auth/official_kb.py:191,301,311`, `Agents/knowledge/processor.py:233`
- **Fix:** Use `psycopg.sql.Identifier` for safe identifier quoting in all DDL

### S3. Auth middleware blocks login endpoints (HIGH)
- **File:** `auth/middleware.py:12-21`
- **Fix:** Add `/auth/login`, `/auth/send-magic-link` to `PUBLIC_PATHS`

### S4. CAPTCHA bypass on error/missing key (HIGH)
- **File:** `auth/captcha.py:35-37,51-53`
- **Fix:** Return False on network error when CAPTCHA_ENABLED=true; warn on missing key

### S5. Legacy auth endpoint bypasses security (HIGH)
- **File:** `auth/login_router.py:315-349`
- **Fix:** Remove `/auth/login/supabase` or add same security controls

### S6. Path validation for docx tool filenames (HIGH)
- **Files:** All `Agents/server/docx_use_mcp/docx_use_server/tools/*.py`
- **Fix:** Add centralized path validator restricting to OFFICE_BASE_DIR

---

## Priority 2: Performance Fixes

### P1. Blocking sync DB calls in async handlers (HIGH)
- **File:** `api/knowledge_router.py` (all endpoints)
- **Fix:** Wrap sync calls with `asyncio.to_thread()` or use async psycopg

### P2. SQLite connection per call (HIGH)
- **Files:** `auth/login_security.py`, `auth/login_logs.py`
- **Fix:** Use persistent connection with thread-safety guard

### P3. ThreadPoolExecutor per docx tool call (HIGH)
- **File:** `Agents/tools/office_docx_toolkit.py:17-31`
- **Fix:** Since python-docx is sync, make underlying tools sync, remove async bridge

### P4. No timeout on ML/preprocessing futures (MEDIUM)
- **Files:** `Agents/server/data/data_process/router.py`, `machine_learning/router.py`
- **Fix:** Add `asyncio.wait_for` with configurable timeout

---

## Priority 3: Maintainability & Coupling

### M1. Duplicate file download hint string (HIGH)
- **Files:** `api/init_agent.py`, `api/init_team.py`, `api/utils.py`
- **Fix:** Extract to shared constant in `api/constants.py`

### M2. Dead TokenPayload model (HIGH)
- **File:** `auth/model.py:4-11`
- **Fix:** Remove dead code

### M3. Commented-out knowledge binding in agents (MEDIUM)
- **Files:** All `Agents/agent/office_*.py`
- **Fix:** Remove dead commented code

### M4. Config class name collision (MEDIUM)
- **Files:** `config/db_config.py`, `config/model_config.py`
- **Fix:** Rename to `DbConfig` and `ModelConfig`

### M5. Repeated inline imports in login_router (MEDIUM)
- **File:** `auth/login_router.py`
- **Fix:** Move to top-level import

### M6. Agent factory boilerplate (MEDIUM)
- **Files:** All agent factory functions
- **Fix:** Extract shared `_base_agent_config()` helper

### M7. Mixed import styles in official_kb (MEDIUM)
- **File:** `auth/official_kb.py`
- **Fix:** Standardize to top-level imports

### M8. Config typo BESE_URL (LOW)
- **File:** `config/model_config.py:21`
- **Fix:** Rename to BASE_URL

### M9. Empty init_workflow.py (LOW)
- **File:** `api/init_workflow.py`
- **Fix:** Remove if unused, or keep as placeholder with TODO

---

## Priority 4: Legacy Debt Cleanup

### L1. Dual storage paths (HIGH)
- **Files:** `data_preprocessing.py`, `hook/preprocess.py`
- **Fix:** Remove legacy fallback, keep only DataFileManager path

### L2. param.py module-level side effects (HIGH)
- **File:** `Agents/server/data/machine_learning/param.py:363-365`
- **Fix:** Make lazy, guard skopt import

### L3. print() instead of logging (MEDIUM)
- **Files:** `core/tables.py`, `param.py`
- **Fix:** Replace with logger calls

### L4. Error handling standardization (MEDIUM)
- **Files:** Multiple
- **Fix:** Map ValueError→400, FileNotFoundError→404 in data routers

### L5. Safe path check in file_router (MEDIUM)
- **File:** `api/file_router.py:60-65`
- **Fix:** Use `resolved.relative_to(BASE_DIR)` instead of `startswith`

---

## Implementation Order (Phase 6)

1. **Batch A - Security:** S1-S6 (path validation, SQL injection, auth fixes)
2. **Batch B - Cleanup:** M1-M9, L2-L3 (dedup, dead code, naming)
3. **Batch C - Performance:** P3 (docx toolkit async fix)
4. **Batch D - Legacy:** L1, L4, L5 (dual storage, error handling)

Items not implemented in Phase 6 will be documented as follow-up tasks:
- PostgreSQL connection pooling (requires psycopg_pool dependency)
- Full async migration of knowledge_router
- Agent ID user-scoping (requires framework changes)
- OfficeDocxToolkit splitting into domain toolkits

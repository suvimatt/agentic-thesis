# AGENTS.md

This file provides guidance to coding agents (such as Codex/ClaudeCode) when working with code in this repository.

## Language Rules

- All code, comments, and git commit messages MUST be in English.


### Configuration

All config is in `config.py` via `pydantic-settings` (`Settings` class), loaded from environment variables or `.env` file. Database URL falls back to AWS Secrets Manager if not set in env.

## Coding Principles

### Import Organization

**All imports MUST be at the top of the file.**

- Group imports in order: standard library, third-party, local modules
- Never use inline imports (e.g., `from main import ...` inside functions) unless absolutely necessary for circular dependency resolution
- If you need to import from the same project, add it to the top imports section

**Bad:**
```python
def some_function():
    from main import helper_function  # ❌ Inline import
    helper_function()
```

**Good:**
```python
from main import helper_function  # ✅ At top of file

def some_function():
    helper_function()
```

### DRY (Don't Repeat Yourself)

**Always eliminate code duplication by creating unified helper functions.**

**Example: Error Reporting Refactoring**

Before (duplicated code):
```python
# In _process_agent_report
all_reports = db.query(VerificationReport).filter(...).all()
agent_reports_data = [r.report_json for r in all_reports if r.type != "error"]
new_status, detailed_status = determine_verification_status(...)
if new_status in ["completed", "failed"]:
    verification.status = VerificationStatus[new_status.upper()]
    # ... more logic
response_data = build_verification_response(...)
await send_webhook(...)

# In report_error (DUPLICATE CODE)
all_reports = db.query(VerificationReport).filter(...).all()
agent_reports_data = [r.report_json for r in all_reports if r.type != "error"]
new_status, detailed_status = determine_verification_status(...)
if new_status in ["completed", "failed"]:
    verification.status = VerificationStatus[new_status.upper()]
    # ... more logic
response_data = build_verification_response(...)
await send_webhook(...)
```

After (unified functions):
```python
# Create unified helper functions
def _update_verification_status_and_build_response(verification, v_id, db, report_type):
    """Unified logic for status update and response building."""
    all_reports = db.query(VerificationReport).filter(...).all()
    agent_reports_data = [r.report_json for r in all_reports if r.type != "error"]
    new_status, detailed_status = determine_verification_status(...)
    if new_status in ["completed", "failed"]:
        verification.status = VerificationStatus[new_status.upper()]
        # ... more logic
    return build_verification_response(...)

async def _send_webhook_notification(v_id, response_data, context=""):
    """Unified webhook sending."""
    # ... webhook logic

# Both endpoints use unified functions
# In _process_agent_report
response_data = _update_verification_status_and_build_response(...)
await _send_webhook_notification(...)

# In report_error
response_data = _update_verification_status_and_build_response(...)
await _send_webhook_notification(...)
```

**Benefits:**
- 30% code reduction
- Single source of truth
- Easier to maintain and test
- Consistent behavior across endpoints

### Documentation Strategy

**Keep spec/ folder minimal and focused on feature design.**

- ✅ DO: Update existing feature docs (e.g., `spec/error-reporting.md`) with latest changes
- ❌ DON'T: Create separate docs for each refactoring or implementation detail
- ❌ DON'T: Create "summary" or "update" docs - integrate changes into main feature doc

**Example:**
- Good: Update `spec/error-reporting.md` with unified logic section
- Bad: Create `spec/refactoring-summary.md` or `spec/implementation-details.md`

### Code Review Checklist

Before completing a feature:
1. ✅ Check for duplicate code patterns
2. ✅ Extract common logic into helper functions
3. ✅ Update feature design doc in `spec/`
4. ✅ Add/update tests
5. ✅ Verify all tests pass
6. ❌ Don't create extra summary documents

## Development Principles

Prefer minimal code changes when refactoring or integrating features - avoid over-engineering solutions

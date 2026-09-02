# AGENTS.md

This file provides guidance to coding agents (such as Codex/ClaudeCode) when working with code in this repository.

## Language Rules

- All code, comments, and git commit messages MUST be in English.


### Configuration

All config is in `config.py` via `pydantic-settings` (`Settings` class), loaded from environment variables or `.env` file. Database URL falls back to AWS Secrets Manager if not set in env.


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

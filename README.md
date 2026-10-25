# Assurance Engine

A deterministic evidence-verification engine with an optional LLM-powered extraction layer.

The LLM extracts candidate facts from supplied source material. The deterministic verification engine evaluates those facts against an explicit verification policy and produces the final verdict.

**The LLM does not decide the final verdict.**

## Features

- Deterministic verification with `VERIFIED`, `FAILED`, and `INCONCLUSIVE` verdicts.
- Pydantic-validated evidence, policies, and extraction responses.
- Configurable evidence trust and freshness policies.
- Asynchronous LLM provider interface with a fake provider for testing.
- OpenAI integration using structured extraction responses.
- Source-quote and observation-timestamp checks.
- Fail-closed handling of provider failures, timeouts, and invalid extraction batches.

## Requirements

- Python 3.13 or later
- `uv`
- An OpenAI API key for live OpenAI extraction

## Installation

Clone or open the repository, then run these commands from the project root:

```powershell
uv sync
```

## Configuration

Set your API key in PowerShell for the current terminal session:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:OPENAI_MODEL = "gpt-4.1-mini"
```

`OPENAI_MODEL` is optional. The provider defaults to `gpt-4.1-mini` if no model is configured.

Never commit API keys or other secrets to Git.

## Project structure

```text
src/assurance_engine/
    schemas.py
    engine.py
    ai/
        schemas.py
        provider.py
        grounding.py
        orchestrator.py
        openai_provider.py

tests/
```

- `schemas.py`: Core evidence, policy, finding, and result models.
- `engine.py`: Deterministic verification logic.
- `ai/schemas.py`: Validated extraction request, fact, and response models.
- `ai/provider.py`: Provider protocol and fake provider.
- `ai/grounding.py`: Converts extracted facts into untrusted evidence after grounding checks.
- `ai/orchestrator.py`: Coordinates extraction, grounding, and deterministic verification.
- `ai/openai_provider.py`: OpenAI API adapter.

## Verification flow

1. The caller supplies a claim, source material, and verification policy.
2. The provider extracts candidate facts in a structured format.
3. The grounding layer checks source identity, quote presence, and observation time.
4. The orchestrator rejects an extraction batch if grounding or policy-field validation fails.
5. Candidate evidence remains untrusted.
6. The deterministic engine evaluates the evidence under the supplied policy and returns the final verdict.

## Example usage

The following illustrates the intended API shape. It assumes the supplied source explicitly establishes an observation timestamp and that the policy permits evaluation of untrusted evidence.

```python
import asyncio
from datetime import datetime, timezone

from assurance_engine.ai.openai_provider import OpenAIProvider
from assurance_engine.ai.orchestrator import verify_with_llm
from assurance_engine.ai.schemas import ExtractionRequest
from assurance_engine.schemas import VerificationPolicy


async def main():
    request = ExtractionRequest(
        claim="The service is operational",
        source_id="status-page",
        source_text=(
            "Service status: operational. "
            "Observed at: 2026-10-25T10:00:00+00:00"
        ),
    )

    policy = VerificationPolicy(
        policy_id="service-status",
        claim_field="status",
        expected_value="operational",
        require_trusted_evidence=False,
    )

    provider = OpenAIProvider()

    try:
        result = await verify_with_llm(
            request.claim,
            request,
            policy,
            provider,
            checked_at=datetime.now(timezone.utc),
        )
        print(result.model_dump_json(indent=2))
    finally:
        await provider.close()


asyncio.run(main())
```

**Important:** `require_trusted_evidence=False` is shown only to illustrate the pipeline. It allows untrusted evidence to participate in verification and must not be used for security-sensitive decisions without an independently justified trust model. An LLM-generated fact is not independently authenticated merely because its quote appears in the source.

## Running tests

Run the complete test suite:

```powershell
uv run pytest -v
```

## Validating the supplied deletion requests

The supplied request CSV can be validated without an OpenAI API key:

```powershell
uv run validate-deletion-requests
```

By default, the command reads `dataset/deletion_requests.csv`; pass another
CSV path as its positional argument to validate a different request file. It
checks the exact request columns, required values, timestamps, reported
statuses, and unique case IDs, and summarizes case-insensitive repeated email
identifiers and request chronology. Reported statuses are treated only as
claims in the request file, not as audit evidence. This command does not
produce `output.csv`: identity, audit-log, system-activity, deletion-rule,
evidence-index, and evidence files are required to make evidence-grounded
deletion decisions. It prints the exact missing audit and sample-oracle paths
for the directory containing the request CSV.

## Local deletion assurance application

The project includes a local web dashboard and JSON API. It uses the existing
deterministic verification engine and does not need an OpenAI key for audit
workflows.

### Prerequisites and startup

- Python 3.13 or later
- `uv`

From the `assurance-engine` directory in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "GhostDataStillExists\venv"
$env:UV_LINK_MODE = "copy"
uv sync --dev
uv run ghost-audit-web
```

Using a virtual environment under local AppData avoids OneDrive/cloud-sync
file-lock and hardlink issues when the project directory is synchronized.
Keep these environment variables set in the same PowerShell window when
running tests or commands.

Open <http://127.0.0.1:8000/>. The interactive API reference is at
<http://127.0.0.1:8000/api/docs>, and health is at
<http://127.0.0.1:8000/api/health>.

The server binds to loopback by default. Optional environment variables are
`ASSURANCE_HOST` (`127.0.0.1`), `ASSURANCE_PORT` (`8000`),
`ASSURANCE_DATASET_DIR` (`dataset`), and `ASSURANCE_LOG_LEVEL` (`INFO`).
No secret or API key is required.

### Dashboard workflow

The dashboard loads request rows from `dataset/deletion_requests.csv`, lists
available and missing audit sources, and provides request search, result-status
filters, pagination, and per-case detail. Importing a request CSV validates
the exact request schema and loads it in memory without replacing the input
file. Choose **Run verification** to create per-case results and
`dataset/output.csv`; the export endpoint downloads the same CSV.

The result schema is exactly `case_id,deletion_status,steps_json`. `steps_json`
is a JSON array of ordered remediation strings. Results use only
`COMPLETE`, `INCOMPLETE`, and `NOT_APPLICABLE`. A reported status is displayed
as a claim and is never evidence. With the currently supplied request CSV
alone, the deterministic engine has no trusted deletion evidence; cases are
therefore `INCOMPLETE`, with missing source files called out as evidence gaps.
No request is classified as `NOT_APPLICABLE` without supplied scope rules.
The application does not infer completion from request text or reported
timestamps.

Place future source files in the configured dataset directory using these
names: `user_identities.csv`, `user_audit_log.csv`, `system_activity.csv`,
`deletion_rules.csv`, and `evidence_files.csv`; place referenced evidence
under `evidence/`. The app discovers them at runtime. Until source schemas
and policy semantics are available and mapped to checks, their presence alone
does not establish a verified result. The sample oracle files
`sample_deletion_requests.csv` and `sample_output.csv` are not included in
the current workspace; sample acceptance comparison is consequently not
available.

### API endpoints

- `GET /api/health` — service health.
- `GET /api/dashboard` — totals, status breakdown, and readiness.
- `GET /api/datasets` — exact discovered dataset paths and availability.
- `POST /api/import/requests` — import UTF-8 CSV bytes; set `Content-Type:
  text/csv` and `X-Filename` headers.
- `GET /api/cases` — search, status filtering, and pagination.
- `GET /api/cases/{case_id}` — request and per-case result details.
- `POST /api/audits/run` — execute deterministic verification and write
  `dataset/output.csv`.
- `GET /api/results` — paginated verification results.
- `GET /api/results/export.csv` — download CSV with the exact required schema.
- `GET /api/docs` — interactive OpenAPI documentation.

### Tests

```powershell
uv run pytest -v
```

Run a specific test module:

```powershell
uv run pytest -v tests/test_ai_orchestrator.py
uv run pytest -v tests/test_openai_provider.py
```

Provider tests use mocks; passing them does not confirm that a live OpenAI API request succeeds.

## Security limitations

- LLM output is untrusted input and must never directly determine a verdict.
- Quote-presence validation checks that a quote occurs in the supplied source; it does not prove that the quote logically entails the extracted value.
- A source ID supplied in a request is a reference, not proof of source authenticity.
- Observation timestamps must be timezone-aware, but their authenticity depends on the source and ingestion process.
- The default policy requires trusted evidence. A policy that disables this requirement deliberately changes the trust boundary.
- Live API usage requires a valid API key, network access, and a supported model.

## Project status

The automated test suite currently passes in the development environment. Live API behavior, production deployment, and remaining security requirements must be verified separately before production use.

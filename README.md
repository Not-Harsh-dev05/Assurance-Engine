Ghost Data Still Exists
Evidence-First Deletion Assurance for Data Privacy Workflows
<p align="center">
  <strong>Deletion is a claim. Evidence is the proof.</strong><br/>
  A local-first assurance console for reviewing data-deletion requests, surfacing evidence gaps, and producing structured audit results.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white"/>
  <img alt="FastAPI" src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white"/>
  <img alt="Testing" src="https://img.shields.io/badge/Tests-102%20passing-brightgreen"/>
  <img alt="Mode" src="https://img.shields.io/badge/Mode-Local%20%26%20Private-168566"/>
</p>

✨ What is Ghost Data Still Exists?
When someone requests deletion of their personal data, a workflow may report success even though records remain in a database, an audit system, a backup, or an active synchronization path.

Ghost Data Still Exists is a deletion-assurance prototype designed to help reviewers distinguish a workflow's reported status from evidence-backed conclusions. It provides a dashboard to inspect deletion requests, run the available verification workflow, review case-level findings, identify missing audit sources, and export results.
Core principle: reported_status is a claim—not proof of deletion.

🎯 Why it matters
- 🔍 Evidence-first review: avoid treating a success flag as proof.
- 🧩 Cross-source assurance: designed to use identity history, audit logs, system activity, retention rules, and evidence records when supplied and mapped.
- 🚧 Transparent uncertainty: surface missing or insufficient evidence instead of inventing a successful outcome.
- 🧾 Actionable results: provide structured findings and ordered follow-up steps.
- 🔒 Local-first workflow: run the console on your own machine for development and review.
🖥️ Application preview
The console includes:
- 📊 Audit overview — request totals and outcome counters.
- 📥 Import requests — upload a CSV and validate its schema.
- 🗂️ Deletion request register — browse, search, filter, and paginate through cases.
- 🔎 Case review — inspect an individual request, its reported status, verification result, and evidence gaps.
- 🧭 Evidence sources — review which required data sources are available or missing.
- ▶️ Run verification — execute the verification workflow against the data currently available.
- 📤 CSV export — export results for downstream review or submission.
🧠 How the workflow works
Deletion request CSV
        │
        ▼
Schema validation & request inventory
        │
        ▼
Available source and evidence readiness checks
        │
        ▼
Deterministic verification workflow
        │
        ├── Evidence supports deletion ──► COMPLETE
        ├── Evidence shows work remains ─► INCOMPLETE
        └── Request is outside scope ────► NOT_APPLICABLE
        │
        ▼
Case review, evidence gaps, next steps
        │
        ▼
Structured CSV export
The intended assurance model considers:
1. The deletion request and its timestamps.
2. Current and historical identifiers, where provided.
3. Audit records and relevant system activity.
4. Applicable retention requirements and permitted tombstones.
5. Active synchronization, import, or restoration paths that could recreate data.
6. Supporting evidence and explicit gaps.
Important: the quality of the result depends on the source data and policy checks actually available to the application. Missing source files must not be interpreted as proof that deletion succeeded.
🧾 Result format
The required output CSV schema is:
case_id,deletion_status,steps_json
Field	Meaning
case_id	Identifier of the deletion request/case
deletion_status	COMPLETE, INCOMPLETE, or NOT_APPLICABLE
steps_json	JSON array of ordered follow-up or proof-check steps


Status semantics
- ✅ COMPLETE — sufficient mapped evidence and applicable rules support completion.
- ⚠️ INCOMPLETE — deletion is not complete, or the required evidence is insufficient to establish completion; inspect the case findings and evidence gaps.
- ➖ NOT_APPLICABLE — the request is outside deletion scope according to the available request intent and applicable rules.
Do not use these labels as substitutes for the underlying evidence. In particular, an INCOMPLETE result caused by missing evidence is not the same as proof that data definitely remains.
🚀 Quick start (Windows / PowerShell)
Prerequisites
- Python 3.13 or a compatible version supported by the project.
- uv for dependency and environment management.
- Git (optional, for cloning and version control).
1. Open the project directory
cd path\to\Ghost-Data-Still-Exists\assurance-engine
2. Create/sync the project environment
The following location avoids common OneDrive virtual-environment locking issues:
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "GhostDataStillExists\venv"
$env:UV_LINK_MODE = "copy"
uv sync --dev
3. Start the application
uv run ghost-audit-web
4. Open the console
- 🌐 Dashboard: http://127.0.0.1:8000/
- 📚 Interactive API documentation: http://127.0.0.1:8000/api/docs
- ❤️ Health endpoint: http://127.0.0.1:8000/api/health
Stop the development server with Ctrl+C.
🧪 Tests and quality checks
Run the automated test suite:
uv run pytest -v
Other checks used during development:
uv lock --check
git diff --check
uv build
The implementation report from the development run recorded 102 passing tests, a successful package build, and live checks of the dashboard, API, case review, import, filters, and export. Re-run these checks against your current checkout before relying on them as a fresh result.
📦 Dataset layout
The application expects the request CSV at dataset/deletion_requests.csv. The full evidence-oriented workflow can use these additional inputs when supplied and correctly mapped:
dataset/
├── deletion_requests.csv
├── sample_deletion_requests.csv
├── sample_output.csv
├── user_identities.csv
├── user_audit_log.csv
├── system_activity.csv
├── deletion_rules.csv
├── evidence_files.csv
├── evidence/
└── output.csv                 # generated audit output
The exact presence and contents of these files depend on your checkout and supplied challenge dataset. Check the dataset inventory in the application before running an evidence-grounded audit.
🔌 API overview
The local FastAPI application exposes the following routes (see /api/docs for the live OpenAPI specification):
Endpoint	Purpose
GET /api/health	Check application health
GET /api/dashboard	Read dashboard counts and readiness
GET /api/datasets	Inspect dataset/source availability
GET /api/docs	Interactive API documentation
GET /api/cases	Browse cases with supported query filters
GET /api/cases/{case_id}	Retrieve a case and its review details
GET /api/results	Browse verification results
POST /api/audits/run	Run the verification workflow
GET /api/results/export.csv	Download the results CSV


Use the running OpenAPI docs as the source of truth for request parameters, validation constraints, and response models.
🔐 Privacy and responsible use
- 🖥️ The documented setup binds to a local address (127.0.0.1) for local development.
- 🔑 The core workflow is designed not to require an external AI API key.
- 🧪 Treat this as a prototype until independently validated against your production schemas, deletion policies, and evidence systems.
- 🚫 Do not upload real personal data into a public repository or expose the local service to an untrusted network without appropriate security controls.
- 🧾 Keep an audit trail of the inputs, rules, and evidence used for consequential deletion decisions.
⚠️ Current limitations
The development run reported that the request CSV was available with 518 requests, but the following supporting inputs and sample oracle were missing at that time:
- sample_deletion_requests.csv
- sample_output.csv
- user_identities.csv
- user_audit_log.csv
- system_activity.csv
- deletion_rules.csv
- evidence_files.csv
- dataset/evidence/
Consequently, that run generated 518 INCOMPLETE results with explicit evidence gaps. These results indicate that completion could not be established from the available inputs; they do not establish that all 518 users' data definitely remains, and they do not prove the engine's full evidence-based decision logic against the missing sources.

Before presenting this project as a validated deletion auditor, supply the complete authorized dataset, map its schemas, compare against the provided sample output, and verify all decision paths.
🗺️ Roadmap
- [ ] Validate against the complete reference dataset and sample-output oracle.
- [ ] Map identity history, audit events, system activity, retention rules, and evidence artifacts.
- [ ] Add repeatable end-to-end tests for each status and evidence-gap scenario.
- [ ] Add authentication/authorization and deployment hardening before multi-user or network use.
- [ ] Record reproducible verification reports and source provenance.
🤝 Contributing
1. Create a branch for your change.
2. Make a focused change with tests.
3. Run uv run pytest -v.
4. Run git diff --check.
5. Open a pull request describing the change, tests, and any data assumptions.
📄 License
Add the license selected for this project before distributing it publicly. Until a license is added, do not assume that the repository grants permission for unrestricted reuse.
<p align="center">
  Built for a simple principle: <strong>Never confuse a deletion claim with deletion proof.</strong> 👻
</p>
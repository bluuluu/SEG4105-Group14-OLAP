# Development Methodology

This document defines the group's working rules for future changes and documentation updates. The project uses a hybrid predictive and iterative approach. The 12-week plan controls the main deliverables, while dashboard and query changes are developed in smaller increments with user feedback.

## 1. Software Development Lifecycle

| Planned period | Work | Completion check |
| --- | --- | --- |
| Weeks 1-2 | Gather requirements, agree on KPIs, and identify data sources. | Business requirements and scope reviewed |
| Weeks 3-4 | Design the schema, ETL mapping, interfaces, security, and dashboard layout. | Design agreed before dependent development |
| Weeks 5-7 | Develop the warehouse and OLAP queries in parallel. Integrate at least weekly. | Warehouse and analytical results available |
| Weeks 8-9 | Build dashboard increments and collect stakeholder feedback. | Core workflows available for testing |
| Weeks 10-11 | Test data reconciliation, functionality, permissions, performance, and business acceptance. | Results recorded against acceptance criteria |
| Week 12 | Prepare deployment, training, documentation, and handoff. | Release and handoff approved |

Use GitHub Issues for tasks, bugs, and change requests. Each issue should identify an owner, expected outcome, and acceptance check. Use a GitHub Project board to organize planned, active, review, and completed work. These are the workflow rules to follow, rather than a record of previously completed issue or board activity.

Review progress and integration risks weekly. Changes to scope, budget, or the approved schedule need a recorded decision by the project manager and business representative.

## 2. Version Control and Branching Strategy

Use GitHub Flow with short-lived branches from an updated `main`.

- `main` is the integration and release branch. Merge changes after review and relevant verification.
- `feature/*` contains a new capability, `fix/*` contains a correction, and `docs/*` contains documentation work.
- For this documentation update, use `docs/architecture-and-methodology`.
- Use descriptive commit prefixes such as `feat:`, `fix:`, `docs:`, `refactor:`, and `test:`. A message should explain the resulting change.
- Open a pull request into `main`. Explain the change, link its issue, and record how it was checked. Use `Closes #<issue-number>` when the PR fully resolves an existing issue.
- Have another group member review the diff. Resolve feedback before merging. Delete the merged feature/documentation branch and update the local `main`.

Typical branch setup follows these commands.

```sh
git checkout main
git pull --ff-only origin main
git checkout -b docs/architecture-and-methodology
```

After editing and checking the files, publish the documentation branch.

```sh
git add README.md docs/
git commit -m "docs: add components architecture and methodology"
git push -u origin docs/architecture-and-methodology
```

Open and review the PR on GitHub. After it is merged, synchronize locally.

```sh
git checkout main
git pull --ff-only origin main
git branch -d docs/architecture-and-methodology
```

## 3. Code Review and Definition of Done

A change is ready to merge when all applicable checks are complete.

1. The changed code runs and its expected behavior is demonstrated.
2. Relevant automated tests pass. Skipped database tests are reported as skipped.
3. Data changes preserve fact grains, constraints, reconciliation, and repeatable batch loading.
4. Authentication and account changes are checked with both manager and administrator roles, including denied requests.
5. The README and affected documentation describe the delivered behavior and setup.
6. The PR records the checks and any unresolved limitations. Another group member reviews and approves it.
7. Credentials, generated `.env` values, local data, and unrelated generated files are excluded from the commit.

For documentation changes, verify file paths, API names, Markdown links, command examples, and the rendered Mermaid diagram. Update the documentation when the implementation changes.

## 4. Testing and Quality Assurance Strategy

### Automated tests

Use Pytest for automated verification. The current suite in [`tests/test_warehouse.py`](../tests/test_warehouse.py) contains four PostgreSQL/API integration tests covering the following areas.

- Sales totals, slice/dice filters, roll-up, pivot, and transpose results.
- Inventory snapshot selection and strict reorder thresholds.
- Account roles and session revocation.
- Repeated batch loading, rejected rows, and recovery after failure.

Install test dependencies in the development environment. Supply a PostgreSQL connection to a dedicated test database whose account can create and remove temporary schemas.

```sh
python -m pip install -r requirements.txt pytest httpx
OLAP_TEST_DATABASE_URL=postgresql:///olap_test python -m pytest -q
```

The database must exist and be accessible before running this command. The fixture creates an isolated schema and removes it afterward. Without `OLAP_TEST_DATABASE_URL`, the tests skip. The inline environment-variable syntax above is for a POSIX shell. In Windows CMD, set the variable on its own line before running Pytest.

For new validation or calculation helpers, add focused unit tests in Pytest. The existing suite has no separately measured unit-test coverage percentage. A proposed target is at least 80% statement coverage of new or changed ETL/analytics logic, with invalid-input and recovery cases included. This target is a future quality goal, not a reported result.

### System and performance checks

Start the application using the [README instructions](../README.md#run-the-demo). Check sign-in, date/dimension filters, drill-down, roll-up, pivot, inventory snapshots, and administration through the browser.

Run the existing benchmark against the running application.

```sh
python scripts/benchmark.py --users 100
```

It prompts for the dashboard password and sends concurrent requests using independently authenticated sessions to the sales, inventory, and cube endpoints. Its pass condition is no failed requests and a maximum response time of five seconds or less for each endpoint. Save the request counts, p95, maximum, dataset, hardware, and date with the test results.

Verify daily extract delivery and worker history in the deployed environment. Measure availability over an agreed monitoring window. Have the business representative validate the KPIs and record UAT approval. Mark a criterion as passed only when the corresponding execution evidence or approval is available.

### Static review

Review SQL parameters, allowed dimension mappings, constraints, account permissions, configuration, and changed dependencies. Inspect diffs for secrets and unrelated files before pushing. Record the reviewer or scanner and its findings. The [GitHub Actions workflow](../.github/workflows/ci.yml) runs the PostgreSQL integration tests and checks that the demo starts in Docker. Record any separately run static analysis or coverage checks in the pull request.

# pobudka
Keep LLM providers awake and tokens ready

## Testing

Run the default test suite:

```bash
pytest -q
```

The Docker integration test is intentionally skipped by default and requires
`RUN_DOCKER_INTEGRATION=1` plus a reachable Docker daemon.

Run only the Docker integration check:

```bash
RUN_DOCKER_INTEGRATION=1 pytest -q tests/test_docker_integration.py
```

Run full suite including Docker integration:

```bash
RUN_DOCKER_INTEGRATION=1 pytest -q
```

## CI

CI should run two layers:

- `pytest -q` for fast default coverage
- `RUN_DOCKER_INTEGRATION=1 pytest -q tests/test_docker_integration.py` to verify
  image build and CLI availability (`claude`, `codex`) in-container

This repository includes a GitHub Actions workflow at
`.github/workflows/ci.yml` that runs both checks on pull requests and pushes to
`main`.

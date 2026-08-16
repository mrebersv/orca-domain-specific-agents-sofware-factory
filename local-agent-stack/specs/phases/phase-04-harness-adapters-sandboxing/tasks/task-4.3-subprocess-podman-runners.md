# TASK BRIEF: Task 4.3 - Subprocess & Podman Tiered Execution Sandboxes

---

## 1. Context References
- Read `specs/PRD.md` (Section 4.4: Tiered Sandboxing & Git Worktree Isolation).
- Read `specs/phases/phase-04-harness-adapters-sandboxing/tasks/task-4.1-harness-adapter-base.md`.

---

## 2. Objective
Implement `adapters/runners.py` providing isolated execution sandboxes for running harness commands across Tier 1 (local subprocess isolation) and Tier 2 (rootless Podman/Docker container isolation). Author the full Phase 4 pytest suite (`tests/phase_04/`).

---

## 3. Scope & Detailed Requirements

### 3.1 Base Runner Interface (`adapters/runners.py`)
```python
class ExecutionRunner(ABC):
    @abstractmethod
    async def execute(
        self,
        command: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: int = 60,
        read_only_paths: Optional[List[Path]] = None
    ) -> Tuple[int, str, str]: # (exit_code, stdout, stderr)
        pass
```

### 3.2 Tier 1: Subprocess Runner (`SubprocessRunner`)
1. **Process Management:**
   - Execute command using `asyncio.create_subprocess_exec`.
   - Wrap with `asyncio.wait_for(..., timeout=timeout_seconds)`.
   - On timeout: Kill process group (`os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`) to eliminate dangling children.
2. **Environment Sanitization:**
   - Whitelist safe environment variables (`PATH`, `HOME`, `USER`, `LANG`, `TMPDIR`).
   - Strip sensitive host variables; inject explicitly provided secret enclaves only.

### 3.3 Tier 2: Podman / Docker Container Runner (`ContainerRunner`)
1. **Container Isolation Configuration:**
   - Detect binary: `podman` (preferred rootless) or `docker`.
   - Flags enforced:
     - `--rm` (ephemeral lifecycle)
     - `--network none` (or specified host proxy bridge)
     - `--memory 2g` / `--cpus 2.0` (configurable resource bounds)
     - `-v {cwd}:/workspace:rw` (mount working tree / worktree)
     - `-w /workspace`
   - Maps read-only paths with `:ro` volume mount flags.
2. **Graceful Degradation:**
   - If container binary is unavailable on the host system, log a warning and fall back safely to `SubprocessRunner` with a security notice.

### 3.4 Phase 4 Integration Test Suite (`tests/phase_04/`)
- `tests/phase_04/test_harness_adapters.py`:
  - Test command generation across all adapter types.
  - Test turn execution with mock agent binaries.
  - Test `scratch.db` recording of turns and generated artifact records.
- `tests/phase_04/test_sandboxes.py`:
  - Test `SubprocessRunner` execution, timeout kill handling, and environment isolation.
  - Test `ContainerRunner` command generation and fallback logic.

---

## 4. Deliverables
- `adapters/runners.py`
- `tests/phase_04/test_harness_adapters.py`
- `tests/phase_04/test_sandboxes.py`

---

## 5. Verification Command
```bash
pytest tests/phase_04/ -v
```
- **Exit Condition:** All Phase 4 adapter and sandbox test assertions pass with exit code `0`.

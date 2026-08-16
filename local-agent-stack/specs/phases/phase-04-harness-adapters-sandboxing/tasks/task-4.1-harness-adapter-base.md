# TASK BRIEF: Task 4.1 - HarnessAdapter Base Abstract Class & Lifecycle Events

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 3: Pluggable Harness Adapter Interface).
- Read `specs/ARCHITECTURE.md` (Section 2.3: `scratch.db` Execution Turns & Artifacts).

---

## 2. Objective
Implement `adapters/base.py` containing the `HarnessAdapter` abstract base class, event data structures, execution lifecycle hooks, and asynchronous database persistence methods for recording execution steps to `scratch.db`.

---

## 3. Scope & Detailed Requirements

### 3.1 Data Structures & Event Models (`adapters/base.py`)
1. **Execution Models (Pydantic / Dataclasses):**
   - `AgentExecutionContext`:
     - `session_id: str`
     - `workflow_run_id: Optional[str]`
     - `task_prompt: str`
     - `worktree_path: Path`
     - `workspace_dir: Path`
     - `secrets: Dict[str, str]` (injected only into runtime memory)
     - `max_turns: int = 6`
     - `timeout_seconds: int = 60`
   - `ExecutionEvent`:
     - `event_type: str` (`"token"`, `"tool_call"`, `"tool_result"`, `"error"`, `"completed"`)
     - `timestamp: float`
     - `payload: Dict[str, Any]`
   - `TurnResult`:
     - `status: str` (`"success"`, `"error"`, `"timeout"`, `"retry"`)
     - `exit_code: int`
     - `output_text: str`
     - `tool_calls: List[Dict[str, Any]]`
     - `artifacts_created: List[Path]`
     - `execution_time_ms: int`
     - `error_message: Optional[str]`

### 3.2 Abstract Base Class (`HarnessAdapter`)
```python
class HarnessAdapter(ABC):
    def __init__(self, agent_config: Dict[str, Any], workspace_dir: Path):
        self.config = agent_config
        self.workspace_dir = workspace_dir
        self.agent_id = agent_config.get("agent_id", "unknown_agent")

    @abstractmethod
    def build_execution_command(self, context: AgentExecutionContext) -> List[str]:
        """Builds the CLI command list to launch the underlying harness."""
        pass

    @abstractmethod
    async def run_turn(self, context: AgentExecutionContext) -> TurnResult:
        """Executes a single agent task and records step outputs to scratch.db."""
        pass

    @abstractmethod
    async def stream_events(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """Streams real-time events, tool calls, and output chunks."""
        pass

    async def record_turn_to_scratch_db(self, context: AgentExecutionContext, result: TurnResult, scratch_db_path: Path) -> None:
        """Persists turn telemetry and generated artifacts to scratch.db."""
        pass
```

### 3.3 Scratchpad Persistence Hook
- `record_turn_to_scratch_db`:
  - Connects to `{scratch_db_path}`.
  - Inserts rows into `execution_turns` for each tool invocation and final turn status.
  - Scans `result.artifacts_created`, calculates SHA-256 checksums, and records entries into `artifacts` table.

---

## 4. Deliverables
- `adapters/base.py`

---

## 5. Verification Command
```bash
python3 -c "from adapters.base import HarnessAdapter, AgentExecutionContext, TurnResult; print('HarnessAdapter ABC verified')"
```
- **Exit Condition:** Base models and abstract class import cleanly without syntax or typing errors.

from fgops.agent_state import AgentState


def test_apply_failure_states_are_deduplicated() -> None:
    archive_hash = "a" * 64
    for status in ("PREPARED", "APPLIED", "APPLY_FAILED", "REVIEW_REQUIRED"):
        state = AgentState(archives={archive_hash: {"status": status}})
        assert state.has_successful_archive(archive_hash) is True


def test_unknown_or_preparation_failure_state_can_be_rebuilt() -> None:
    archive_hash = "b" * 64
    state = AgentState(archives={archive_hash: {"status": "PREPARATION_FAILED"}})
    assert state.has_successful_archive(archive_hash) is False

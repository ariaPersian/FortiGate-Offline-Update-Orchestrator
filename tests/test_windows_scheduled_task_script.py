from pathlib import Path


def test_windows_task_trigger_uses_constructor_repetition_parameters() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "install-scheduled-task.ps1"
    ).read_text(encoding="utf-8")

    assert "-RepetitionInterval" in script
    assert "-RepetitionDuration" in script
    assert ".Repetition.Interval" not in script
    assert ".Repetition.Duration" not in script

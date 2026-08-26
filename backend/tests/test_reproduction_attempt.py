from app.models import ReproductionAttempt


def test_reproduction_attempt_model():
    attempt = ReproductionAttempt(
        run_id=1,
        stack_trace="ZeroDivisionError: division by zero",
        diagnostic_path="backend/app/services/math.py",
        diagnostic_name="calculate",
        diagnostic_line=2,
        test_path="tests/autopatch_repro_test.py",
        test_source="def test_reproduces_calculate_failure(): pass",
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        reproduced=True,
    )

    assert attempt.run_id == 1
    assert attempt.diagnostic_path == "backend/app/services/math.py"
    assert attempt.diagnostic_name == "calculate"
    assert attempt.diagnostic_line == 2
    assert attempt.test_path == "tests/autopatch_repro_test.py"
    assert attempt.exit_code == 1
    assert attempt.reproduced is True
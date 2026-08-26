from app.services.harness import ReproductionResult


def test_reproduction_result_success_when_exit_code_is_nonzero():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
    )

    assert result.reproduced is True
    assert result.exit_code == 1


def test_reproduction_result_not_reproduced_when_exit_code_is_zero():
    result = ReproductionResult(
        exit_code=0,
        stdout="1 passed",
        stderr="",
    )

    assert result.reproduced is False
    assert result.exit_code == 0
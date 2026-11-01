"""Path conventions shared by the analyses."""

import os

_TEST_DIRECTORY_PARTS = frozenset({"test", "tests", "spec", "specs", "__tests__"})


def looks_like_test_path(path: str) -> bool:
    """
    Is this a test file, by the conventions test runners use?

    Three analyses need the same answer for different reasons: a test file is
    held to different size norms than product code, duplication between tests
    is expected rather than a refactor target, and a test referencing a symbol
    is what test coverage means in `score_risk`.

    Deliberately strict, because the callers want it that way: a wrong "yes"
    hides a finding in product code, which is worse than missing one in a
    test suite named unconventionally.
    """
    parts = path.replace(os.sep, "/").split("/")
    name = parts[-1].lower()
    if (
        name.startswith("test_")
        or name.startswith("test.")
        or "_test." in name
        or ".test." in name
        or ".spec." in name
        or "_spec." in name
    ):
        return True

    for part in parts[:-1]:
        if part.lower() in _TEST_DIRECTORY_PARTS:
            return True
        # Kotlin multiplatform names them jvmTest, commonTest, androidTest. The
        # capital is what separates those from a directory called "latest",
        # which also ends in "test".
        if part.endswith(("Test", "Tests")):
            return True
    return False

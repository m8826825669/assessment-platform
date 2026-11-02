"""Test runner options used by the roadmap acceptance gate."""


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres",
        action="store_true",
        default=False,
        help="Fail rather than skip PostgreSQL tests if the test admin URL is not configured.",
    )

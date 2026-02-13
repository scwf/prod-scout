"""
conftest.py - pytest 共享插件配置

提供 --run-integration 选项来控制集成测试的运行。
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require network and real credentials",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration test (requires network)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="需要 --run-integration 选项来运行集成测试")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)

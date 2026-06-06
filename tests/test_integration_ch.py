"""Optional integration test against live ClickHouse."""

import os

import pytest

from tlock_analyzer.analysis.pipeline import run_analysis
from tlock_analyzer.models import QueryFilters
from tlock_analyzer.sources.clickhouse import ClickHouseSource


@pytest.mark.integration
def test_clickhouse_victims_by_log_id():
    from tj_common.utils import apply_mcp_clickhouse_env, clickhouse_config_from_env

    apply_mcp_clickhouse_env()
    cfg = clickhouse_config_from_env()
    if not cfg["password"]:
        pytest.skip("CLICKHOUSE_PASSWORD not set (env or .cursor/mcp.json)")

    ch = ClickHouseSource(
        host=cfg["host"],
        port=cfg["port"],
        password=cfg["password"],
        database=cfg["database"],
    )

    log_ids = os.environ.get("CLICKHOUSE_TEST_LOG_ID", "teletrade_tj_logs").split(",")
    filters = QueryFilters(log_ids=[x.strip() for x in log_ids if x.strip()])

    result = run_analysis(ch, filters)
    assert isinstance(result.victims, list)

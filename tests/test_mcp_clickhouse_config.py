import json

from tj_common.utils import clickhouse_config_from_env, load_mcp_clickhouse_env


def test_load_mcp_clickhouse_env_from_repo(tmp_path, monkeypatch):
    mcp_dir = tmp_path / ".cursor"
    mcp_dir.mkdir()
    (mcp_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcp-clickhouse": {
                        "env": {
                            "CLICKHOUSE_HOST": "10.0.0.1",
                            "CLICKHOUSE_PORT": "18123",
                            "CLICKHOUSE_USER": "default",
                            "CLICKHOUSE_PASSWORD": "secret",
                            "CLICKHOUSE_DATABASE": "default",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for key in (
        "CLICKHOUSE_HOST",
        "CLICKHOUSE_PORT",
        "CLICKHOUSE_USER",
        "CLICKHOUSE_PASSWORD",
        "CLICKHOUSE_DATABASE",
        "CLICKHOUSE_LOG_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)
    env = load_mcp_clickhouse_env()
    assert env["CLICKHOUSE_PASSWORD"] == "secret"
    cfg = clickhouse_config_from_env()
    assert cfg["host"] == "10.0.0.1"
    assert cfg["password"] == "secret"
    assert cfg["database"] == "onec_logs"

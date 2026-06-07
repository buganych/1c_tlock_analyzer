---
name: call-analyzer
description: 1C CALL event analysis (duration, CPU, memory, disk tops). Use lock analyzers (tj/tlock) for lock problems, not this skill.
---

# CALL Analyzer (1C) — события CALL

## Routing

| User intent | Tool |
|-------------|------|
| **CALL** / performance tops / CPU / memory / disk | **`python -m call_analyzer`** (this skill) |
| Lock problems (TLOCK / TTIMEOUT / TDEADLOCK) | `tj-analyzer` or lock-specific skills |

Rule: [.cursor/rules/call-analyzer.mdc](../../rules/call-analyzer.mdc)

## When to use this skill

- Явно **CALL**: топ по длительности, CPU, памяти, диску
- Ключевые слова: CALL, CPUTime, MemoryPeak, InBytes, OutBytes, «нагрузка по контекстам»
- **Не** использовать для блокировок, виновников TLOCK, дедлоков

## Workflow

1. Убедиться, что пакет установлен:

   ```bash
   pip install -e .
   ```

2. Определить источник:
   - **click** — ClickHouse `tj_call`, нужен `--log-id`
   - **plain** / **json** — `--file`, для plain опционально `--base-date`

3. Запустить анализ:

   ```bash
   python -m call_analyzer --source click --log-id <LOG_ID> --report-dir reports
   ```

   Большой объём (порции + параллель):

   ```bash
   python -m call_analyzer --source click --log-id <LOG_ID> \
     --report-dir reports --chunk-size 50000 --parallel-workers 4 --top 20
   ```

4. Интерпретировать отчёт:
   - **6 таблиц:** длительность (сек), CPU (сек), память (МБ), диск всего / пишущая / читающая (МБ)
   - Все контексты в JSON/MD; в HTML — фильтр и сортировка по колонкам
   - Открывать **`analysis.html`** для интерактивного просмотра

## ClickHouse

Таблица: `onec_logs.tj_call`

```sql
SELECT count() FROM onec_logs.tj_call WHERE log_id = '<LOG_ID>';
```

Env: `.cursor/mcp.json` или `CLICKHOUSE_*`.

## Do not

- Писать одноразовые скрипты вместо `call_analyzer`
- Путать с `tj_analyzer` (блокировки)
- Использовать `tj_scall` — только **CALL**

## Reference

- [README.md](../../../README.md)
- [AGENTS.md](../../../AGENTS.md)

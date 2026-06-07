# Анализаторы техжурнала 1С

Python-пакет для анализа событий техжурнала (ТЖ) 1С из ClickHouse или файлов:

- **блокировки** — ожидания TLOCK, таймауты TTIMEOUT, взаимоблокировки TDEADLOCK;
- **производительность** — события CALL (длительность, CPU, память, диск);
- **настройка сбора ТЖ** — генерация `logcfg.xml` по наблюдаемым TLOCK.

Общая логика в `tj_common/`; эталоны BSL — в `bmp/CommonModules/` (не дублируются в Python).

## Инструменты

| Команда | Назначение | Таблица CH |
|---------|------------|------------|
| **`python -m tj_analyzer`** | **Все блокировки сразу** (рекомендуется) | `tj_tlock`, `tj_ttimeout`, `tj_tdeadlock` |
| `python -m tlock_analyzer` | Только ожидания TLOCK, поиск виновника | `tj_tlock` |
| `python -m ttimeout_analyzer` | Только таймауты TTIMEOUT | `tj_ttimeout` |
| `python -m tdeadlock_analyzer` | Только взаимоблокировки TDEADLOCK | `tj_tdeadlock` |
| `python -m call_analyzer` | Топ по CALL (не блокировки) | `tj_call` |
| `python -m tlock_logcfg` | Настройка ТЖ по regions TLOCK | `tj_tlock` |

Точки входа после установки: `tj-analyzer`, `tlock-analyzer`, `ttimeout-analyzer`, `tdeadlock-analyzer`, `call-analyzer`, `tlock-logcfg`.

## Установка

```bash
cd 1C_tj_analyzer
pip install -e .
# с тестами
pip install -e ".[dev]"
```

### ClickHouse

Переменные окружения (или `.cursor/mcp.json`):

| Переменная | Пример |
|------------|--------|
| `CLICKHOUSE_HOST` | `192.168.40.51` |
| `CLICKHOUSE_PORT` | `18123` |
| `CLICKHOUSE_USER` | `default` |
| `CLICKHOUSE_PASSWORD` | `…` |
| `CLICKHOUSE_DATABASE` | `onec_logs` |

## Как выбрать анализатор

| Задача | Команда |
|--------|---------|
| Все проблемы блокировок, сводный отчёт | `tj_analyzer` |
| Кто держит блокировку, WaitConnections | `tlock_analyzer` |
| Истёк таймаут ожидания | `ttimeout_analyzer` |
| Дедлок, цикл соединений | `tdeadlock_analyzer` |
| Топ по длительности / CPU / памяти / диску | `call_analyzer` |
| Собрать logcfg для мониторинга regions | `tlock_logcfg` |

Подробная маршрутизация для агентов Cursor: [AGENTS.md](AGENTS.md), [.cursor/rules/lock-analyzers.mdc](.cursor/rules/lock-analyzers.mdc).

## Общие параметры CLI

| Параметр | Назначение |
|----------|------------|
| `--source click` | ClickHouse `onec_logs` (по умолчанию) |
| `--source plain` / `json` | Файл ТЖ (`--file`, для plain — `--base-date`) |
| `--log-id` | Поток логов в CH (**обязателен** для click); через запятую |
| `--from` / `--to` | Период (ISO), опционально |
| `--database` | Фильтр `process_name` (имя ИБ) |
| `--hosts` | Список хостов через запятую |
| `--file-like` | Только click: `file LIKE`, напр. `%tlock_%` |
| `--min-duration` | Мин. длительность ожидания, сек (TLOCK/TTIMEOUT) или CALL |
| `--report-dir` | **Рекомендуется:** каталог отчётов `analysis.{json,md,html}` |
| `--output both` | JSON + markdown в stdout (если нет `--report-dir`) |
| `--config-catalog` | Выгрузка конфигурации 1С (TDEADLOCK: дерево контекста) |

### Отчёты (`--report-dir`)

В каталоге создаются:

| Файл | Содержимое |
|------|------------|
| `analysis.json` | Машиночитаемый результат |
| `analysis.md` | Текстовый отчёт |
| `analysis.html` | HTML с оглавлением; для CALL — фильтр и сортировка |
| `logcfg.xml` | Только TLOCK/tj_analyzer при неразобранных блокировках |

Примеры:

```bash
# автоподкаталог reports/<анализатор>_<log_id>_<timestamp>/
python -m tj_analyzer --source click --log-id <LOG_ID> --report-dir reports

# явный каталог
python -m tj_analyzer --source click --log-id <LOG_ID> --report-dir reports/<LOG_ID>
```

Каталог `reports/` в `.gitignore` — не коммитить отчёты.

## Сводный анализ блокировок (`tj_analyzer`)

Один запуск: TLOCK + TTIMEOUT + TDEADLOCK, общие фильтры, секции `summary`, `tlock`, `ttimeout`, `tdeadlock`.

```bash
python -m tj_analyzer --source click --log-id teletrade_tj_logs --report-dir reports

python -m tj_analyzer --source click --log-id teletrade_tj_logs --database UVI_UTD \
  --from "2026-05-27 00:00:00" --to "2026-05-27 12:00:00" --report-dir reports

# только часть анализаторов
python -m tj_analyzer --source click --log-id X --only tlock,ttimeout --report-dir reports

# из файла
python -m tj_analyzer --source plain --file tj.log --base-date "2026-05-27" --report-dir reports

# параллельный разбор при большом числе жертв
python -m tj_analyzer --source click --log-id X --report-dir reports --agent-chunk-size 1000
```

### Как анализировать результат

1. Откройте **`analysis.html`** — оглавление, сводные таблицы, детали по каждой жертве.
2. В JSON смотрите `summary`: число жертв TLOCK/TTIMEOUT и кейсов TDEADLOCK.
3. **TLOCK / TTIMEOUT:** для каждой жертвы — виновник, пересечение блокировок (`ПолноеСоответствие`, `Эскалация`, `РазныйНаборИзмерений`, `БольшаяТранзакция`).
4. **TDEADLOCK:** тип взаимоблокировки, таймлайн, граф цикла.
5. При неразобранных TLOCK рядом появится **`logcfg.xml`** — шаблон донастройки сбора ТЖ.

```sql
SELECT DISTINCT log_id FROM onec_logs.tj_tlock WHERE wait_connections != '';
SELECT DISTINCT log_id FROM onec_logs.tj_ttimeout WHERE wait_connections != '';
SELECT count() FROM onec_logs.tj_tdeadlock WHERE log_id = '<LOG_ID>';
```

## TLOCK — ожидания блокировок

Жертвы: `TLOCK` с непустым `wait_connections`. Для каждой — транзакция виновника и пересечение блокировок.

```bash
python -m tlock_analyzer --source click --log-id teletrade_tj_logs --report-dir reports

python -m tlock_analyzer --source click --log-id X --min-duration 3 --file-like "%tlock_%" --report-dir reports
```

## TTIMEOUT — таймауты ожидания

Жертвы из `tj_ttimeout`; виновник ищется в `tj_tlock` (как в BSL).

```bash
python -m ttimeout_analyzer --source click --log-id teletrade_tj_logs --report-dir reports
```

## TDEADLOCK — взаимоблокировки

Разбор `DeadlockConnectionIntersections`, участники, таймлайн, тип дедлока, матрица контекстов.

```bash
python -m tdeadlock_analyzer --source click --log-id teletrade_tj_logs --report-dir reports

python -m tdeadlock_analyzer --source click --log-id X --database UVI_UTD \
  --from "2026-05-27 00:00:00" --to "2026-05-27 12:00:00" --report-dir reports

# один кейс
python -m tdeadlock_analyzer --source click --log-id X \
  --at "2026-05-27 10:54:35.123456" --connect-id 518868 --session-id 100 --host vTerm02

# дерево контекста из выгрузки конфигурации
python -m tdeadlock_analyzer --source click --log-id X --config-catalog D:/cfg_export --report-dir reports
```

Статусы: `ok`, `incomplete_tx`, `too_few_events`.

Типы: «Повышение уровня блокировки в рамках одной транзакции», «Разный порядок захвата ресурсов».

## CALL — производительность вызовов

Группировка по контексту (каскад: `context` → `module.method` → `func` → `mname.iname`). Шесть таблиц:

1. ТОП по длительности (сек)
2. ТОП по CPU (сек)
3. ТОП по памяти (МБ)
4. ТОП по диску — всего нагрузка (МБ)
5. ТОП по диску — пишущая нагрузка (МБ)
6. ТОП по диску — читающая нагрузка (МБ)

Колонки: контекст, средняя, максимальная, минимальная, **всего**, кол-во. Все значения — **целые числа**.

```bash
python -m call_analyzer --source click --log-id 2teletrade_tglogs --report-dir reports

python -m call_analyzer --source click --log-id X \
  --from "2026-05-26" --to "2026-05-27" --min-duration 1 \
  --top 20 --chunk-size 50000 --parallel-workers 4 --report-dir reports

python -m call_analyzer --source plain --file call.log --base-date "2026-05-26" --report-dir reports
```

| Параметр | По умолчанию | Назначение |
|----------|--------------|------------|
| `--top` | 20 | Видимых строк; остальные — сворачиваемый блок |
| `--chunk-size` | 50000 | Событий на порцию при большом объёме |
| `--parallel-workers` | 4 | Параллельных агентов |

**HTML:** поле «Фильтр» (подстрока в контексте во всех таблицах), клик по заголовку — сортировка по колонке.

```sql
SELECT count() FROM onec_logs.tj_call WHERE log_id = '<LOG_ID>';
```

## Настройка ТЖ (`tlock_logcfg`)

Формирует `logcfg.xml` по уникальным `regions` из TLOCK с `wait_connections` (не отчёт о виновниках).

```bash
python -m tlock_logcfg --source click --log-id <LOG_ID> \
  --location-path "D:\TJ\locks" -o reports/<LOG_ID>_logcfg.xml

python -m tlock_logcfg --source click --log-id X \
  --min-duration 3 --platform-version 8.3.27 \
  --location-path "D:\TJ\locks" --report-dir reports/<LOG_ID>
```

Шаблон: `logcfg_шаблон.xml` / `tlock_logcfg/data/logcfg_шаблон.xml`.

## Тесты

```bash
# без live ClickHouse
python -m pytest --ignore=tests/test_integration_ch.py \
  --ignore=tests/test_integration_ch_ttimeout.py \
  --ignore=tests/test_integration_ch_tdeadlock.py

# интеграция с CH
python -m pytest -m integration
```

## Структура репозитория

```
tj_common/                 # общая логика
  analysis/                # pipeline блокировок и CALL
  sources/                 # ClickHouse, plain, json
  report/                  # json, md, html
call_analyzer/             # CLI CALL
tj_analyzer/               # сводный CLI
tlock_analyzer/
ttimeout_analyzer/
tdeadlock_analyzer/
tlock_logcfg/
bmp/CommonModules/         # эталоны BSL
.cursor/rules/             # правила для агентов Cursor
.cursor/skills/            # skills по каждому анализатору
tests/
reports/                   # отчёты (gitignore)
```

## Документация для агентов Cursor

| Тема | Файл |
|------|------|
| Маршрутизация | [AGENTS.md](AGENTS.md) |
| Все блокировки | [.cursor/rules/tj-analyzer.mdc](.cursor/rules/tj-analyzer.mdc) |
| TLOCK | [.cursor/rules/tlock-analyzer.mdc](.cursor/rules/tlock-analyzer.mdc) |
| TTIMEOUT | [.cursor/rules/ttimeout-analyzer.mdc](.cursor/rules/ttimeout-analyzer.mdc) |
| TDEADLOCK | [.cursor/rules/tdeadlock-analyzer.mdc](.cursor/rules/tdeadlock-analyzer.mdc) |
| CALL | [.cursor/rules/call-analyzer.mdc](.cursor/rules/call-analyzer.mdc) |
| logcfg | [.cursor/rules/tlock-logcfg.mdc](.cursor/rules/tlock-logcfg.mdc) |
| Отчёты | [.cursor/rules/report-output.mdc](.cursor/rules/report-output.mdc) |

# test_goreltech
Тестовое задание для ГОРЭЛТЕХ.

Скил `meeting-protocol` для LLM-ассистента (превращает заметки о встрече в протокол), реестр скилов с FastAPI и экспорт протокола в Word.

## Структура

```
skills/meeting-protocol/                 скил (часть 1)
  SKILL.md                               description для классификатора + системный промпт
  references/protocol_format.md          формальный контракт формата протокола
  routes/quick_summary.md                сценарий «кратко» / TL;DR
eval_queries.md                          10 eval-запросов и пример «заметки → протокол»
app/
  registry.py                            SkillRegistry: загрузка, валидация, поиск, reload
  protocol_parser.py                     строгий парсер протокола → Protocol
  docx_generator.py                      Protocol → .docx (python-docx) + CLI
  api.py                                 FastAPI-приложение
tests/                                   pytest
```

## Установка

Нужен Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Запуск API

```bash
uvicorn app.api:app --reload
```

Каталог скилов берётся из переменной окружения `SKILLS_DIR` (по умолчанию `skills`, относительно текущей директории):

```bash
SKILLS_DIR=/path/to/skills uvicorn app.api:app --reload
```

Swagger UI: http://127.0.0.1:8000/docs

## Эндпоинты

| Метод | Путь | Описание |
| --- | --- | --- |
| GET | `/skills?q=<подстрока>` | Список скилов: `name`, `caption`, `description`, `has_files`. `q` — поиск без учёта регистра по `name` и `caption` |
| GET | `/skills/{name}` | Метаданные скила + `body`; 404, если скил не найден |
| POST | `/skills/reload` | Перечитать каталог скилов; ответ `{"status": "ok", "count": N}` |
| POST | `/protocol/docx` | Тело `{"markdown": "..."}` → файл `protocol.docx`. 400 — нет или пустой `markdown`, невалидный JSON; 422 — markdown не соответствует формату протокола |

Примеры:

```bash
curl -G http://127.0.0.1:8000/skills --data-urlencode "q=протокол"
```

```bash
curl -X POST http://127.0.0.1:8000/skills/reload
```

```bash
python3 -c 'import json,sys; print(json.dumps({"markdown": open(sys.argv[1], encoding="utf-8").read()}))' protocol.md > body.json
```

```bash
curl -X POST http://127.0.0.1:8000/protocol/docx -H "Content-Type: application/json" --data @body.json -o protocol.docx
```

## Генерация .docx из CLI

```bash
python -m app.docx_generator protocol.md protocol.docx
```

При несоответствии формату команда печатает ошибку с номером строки и завершается с кодом 1.

## Тесты

```bash
pytest -q
```

## Правила валидации скилов

- `SKILL.md` с YAML-frontmatter между строками `---` (закрывающая строка — `---` или `...`); файл без frontmatter читается целиком как тело.
- `name` — kebab-case, не длиннее 64 символов; если не задан, берётся имя папки.
- `description` обязательна, не длиннее 1024 символов.
- Тело не может быть пустым.
- `caption` необязателен; если не задан, равен `name`.
- `has_files = true`, если в каталоге скила есть другие файлы, кроме `SKILL.md` (скрытые не учитываются).
- Невалидный скил, отсутствующий `SKILL.md` или повторяющееся имя → `logging.warning`, скил пропускается, остальные загружаются.

## Формат протокола

Строгий контракт описан в [skills/meeting-protocol/references/protocol_format.md](skills/meeting-protocol/references/protocol_format.md). Парсер следует ему без эвристик: любое отклонение даёт `ProtocolParseError` с номером строки.

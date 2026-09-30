# test_goreltech
Тестовое задание для ГОРЭЛТЕХ.

**Демо:** [веб-интерфейс](https://test-goreltech.onrender.com/) · [Swagger UI](https://test-goreltech.onrender.com/docs)
(бесплатный хостинг засыпает без запросов — первое открытие может занять до минуты)

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
  static/index.html                      веб-интерфейс
tests/                                   pytest
render.yaml                              конфиг деплоя на Render
```

## Эндпоинты

| Метод | Путь | Описание |
| --- | --- | --- |
| GET | `/skills?q=<подстрока>` | Список скилов: `name`, `caption`, `description`, `has_files`. `q` — поиск без учёта регистра по `name` и `caption` |
| GET | `/skills/{name}` | Метаданные скила + `body`; 404, если скил не найден |
| POST | `/skills/reload` | Перечитать каталог скилов; ответ `{"status": "ok", "count": N}` |
| POST | `/protocol/docx` | Тело `{"markdown": "..."}` → файл `protocol.docx`. 400 — нет или пустой `markdown`; 422 — markdown не соответствует формату протокола |

## Генерация .docx из CLI

```bash
python -m app.docx_generator protocol.md protocol.docx
```

## Тесты

```bash
pytest -q
```

## Правила валидации скилов

- `name` — kebab-case, не длиннее 64 символов; если не задан, берётся имя папки.
- `description` обязательна, не длиннее 1024 символов.
- Тело не может быть пустым; `caption` необязателен (по умолчанию равен `name`).
- `has_files = true`, если в каталоге скила есть другие файлы, кроме `SKILL.md`.
- Невалидный скил, отсутствующий `SKILL.md` или повторяющееся имя → `logging.warning`, скил пропускается, остальные загружаются.

## Формат протокола

Строгий контракт — [skills/meeting-protocol/references/protocol_format.md](skills/meeting-protocol/references/protocol_format.md). Парсер следует ему без эвристик: любое отклонение даёт `ProtocolParseError` с номером строки.

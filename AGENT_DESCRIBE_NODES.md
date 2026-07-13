# Инструкция для Cursor-агента: описания узлов графа

Задача: заполнить поле `description` у узлов в execution graph — коротким **человекочитаемым** объяснением роли узла в сценарии (бизнес-смысл, не пересказ кода).

**Не менять** tool-repo (`project-graph-tool/`). Исходники проекта — **read-only**.

---

## Куда класть результат

### Единственный файл для записи

```
<data-repo>/output/execution_graph.json
```

Например: `myapp-graph/output/execution_graph.json` (соседняя папка с `myapp/` и `project-graph-tool/`).

У каждого объекта в массиве `nodes` есть поле:

```json
"description": null
```

Заменить `null` на строку с описанием. **Ключ узла — поле `id`** (не менять `id`, `type`, `qualified_name` и остальные поля).

Пример после заполнения:

```json
{
  "id": "ROOT_create_order",
  "type": "ENTRY_POINT",
  "name": "create_order",
  "qualified_name": "myapp.views.orders.OrderViewSet.create",
  "description": "Trace root: создание заказа. Принимает JSON, валидирует схему, делегирует в сервис.",
  "source_file": "myapp/views/orders.py",
  "line_start": 42,
  "line_end": 68,
  "metadata": { "root_id": "create_order", ... }
}
```

### Что не трогать

| Файл | Действие |
|------|----------|
| `output/call_graph.json` | только читать при необходимости контекста |
| `config/trace_queue.yaml` | не менять без задания |
| `config/trace_done.yaml` | не менять (пишется `trace`) |
| Репозиторий проекта (`myapp/`) | **только read** |
| `project-graph-tool/` | не менять без отдельного задания |

---

## Откуда брать данные

### 1. Список узлов для описания

Файл: `<data-repo>/output/execution_graph.json` → массив `nodes`.

Описывать **все узлы этого файла**, у которых `"description": null`.

### 2. Метаданные узла

Брать из того же объекта node:

- `type` — ENTRY_POINT, VIEW, SERVICE, EXTERNAL_API, DATABASE…
- `name`, `qualified_name`
- `source_file`, `line_start`, `line_end`
- `metadata` — `root_id`, `resolved_qualified_name`, `pointer_kind` и т.д.

### 3. Исходный код узла

Путь на диске:

```
<корень проекта>/<source_file>
```

Корень проекта — из `workspace.yaml` → `project_path` (например `../myapp` относительно data-repo).

Читать строки `line_start` … `line_end`. Если `line_end` null — прочитать функцию/класс целиком по контексту (±30 строк).

### 4. CLI-помощник (опционально)

Из **data-repo**:

```powershell
.\run.ps1 describe-node <фрагмент id или qualified_name>
```

Выводит: metadata, фрагмент source, исходящие/входящие рёбра.

### 5. Связи узла (контекст сценария)

Файл: тот же `execution_graph.json` → массив `edges`.

- `from` → `to`, `type` (CALLS, WRITES, EMITS…)
- По рёбрам понять: куда ведёт узел (сервис, ORM, внешний API, Celery…)

### 6. Эталон сценария (опционально)

`<data-repo>/config/reference_scenarios.yaml` — ключ сценария: `root_id` и `required_nodes`.

---

## Какие узлы описывать в первую очередь

Если узлов много, приоритет:

1. `ENTRY_POINT` — trace root сценария  
2. `VIEW`, `METHOD`, `SERVICE` — бизнес-логика  
3. `ORM`, `EXTERNAL_API`, `DATABASE`, `TABLE`, `QUEUE`, `CACHE` — инфраструктура  
4. `UNKNOWN` из `.venv/` или `builtins.*` — **можно пропустить** или одной фразой: «Служебный/нерешённый вызов статического анализа»

**Дедупликация:** если два узла с одним `qualified_name` (разные `id`) — описание может быть одинаковым или чуть уточнённым по роли в графе.

---

## Правила текста description

- **Язык:** русский (или английский — единообразно для всего файла).  
- **Длина:** 1–3 предложения, ~15–40 слов.  
- **Содержание:** *зачем* узел в продукте / в этом сценарии, *что* делает на уровне ответственности.  
- **Не писать:** построчный пересказ кода, списки параметров, «эта функция вызывает X» без смысла.  
- **Писать:** «Валидирует тело запроса и создаёт заказ в БД без вызова платёжного API».  
- Если назначение неясно даже после чтения кода:  
  `"description": "Назначение не удалось определить по статическому анализу."`

### Примеры по типам

| type | Пример description |
|------|-------------------|
| ENTRY_POINT | «Trace root: обработчик создания заказа.» |
| VIEW / METHOD | «Парсит JSON, вызывает OrderService.create, возвращает id.» |
| SERVICE | «Оркестрация создания заказа: модель, оплата, post-save хуки.» |
| EXTERNAL_API | «Клиент платёжного провайдера для авторизации транзакции.» |
| DATABASE | «Основная PostgreSQL БД приложения.» |
| ORM | «Модель заказа, persist через .save().» |

---

## Алгоритм работы агента

1. Прочитать `<data-repo>/output/execution_graph.json`.  
2. Собрать список `nodes` с `"description": null`.  
3. Для каждого узла (или пакетами по 5–10):  
   - прочитать metadata + edges;  
   - прочитать исходник по `source_file` (read-only);  
   - при необходимости: `.\run.ps1 describe-node <id>` из data-repo.  
4. Сформулировать `description`.  
5. **Записать** обратно в `execution_graph.json`, сохранив валидный JSON (indent 2, как в файле).  
6. Не удалять и не переименовывать узлы/рёбра.  
7. После сохранения обновить страницу viewer (`.\serve.ps1` → F5) — граф подгрузится автоматически.

---

## Проверка

```powershell
cd myapp-graph
.\run.ps1 inspect --root-id create_order
```

Убедиться, что JSON валиден (парсится без ошибок).

---

## Типичные ошибки

| Ошибка | Как правильно |
|--------|----------------|
| Править `call_graph.json` | Только `execution_graph.json` в data-repo |
| Менять `id` / `qualified_name` | Только поле `description` |
| Описывать все узлы call graph | Только узлы в `execution_graph.json` |
| Писать код вместо смысла | Бизнес-роль в сценарии |
| Править tool-repo | Только data-repo `output/execution_graph.json` |

---

## Связанные файлы

| Файл | Назначение |
|------|------------|
| `graph_model.md` (tool-repo) | Контракт поля `description` |
| `config/reference_scenarios.yaml` (data-repo) | Эталон сценария по `root_id` |
| `README.md` (tool-repo) | Команды `trace` и viewer |

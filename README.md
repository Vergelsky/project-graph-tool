# Project Execution Map

Инструмент статического анализа Python-проектов, который строит **карту выполнения сценариев** — не дерево файлов, а цепочки вызовов от явно указанных trace roots до инфраструктуры (БД, внешние API, очереди).

```
myapp.views.OrderViewSet.create  (trace root)
  → OrderService.create
    → PaymentClient / ORM / Celery …
```

Результат — интерактивный граф в браузере и JSON-артефакты для валидации и AI-описаний.

---

## Что это и зачем

| Проблема | Решение |
|----------|---------|
| Сложно понять, что делает функция | Трассировка от явного trace root до листьев |
| Импорт-графы не показывают runtime | Граф **вызовов**, не зависимостей файлов |
| Документация устаревает | Детерминированная пересборка из кода |
| Нужен контекст для AI | `describe-node` + поле `description` в JSON |

Анализ **без LLM** — только AST, Jedi, эвристики. ИИ используется отдельно для заполнения текстовых описаний узлов ([`AGENT_DESCRIBE_NODES.md`](AGENT_DESCRIBE_NODES.md)).

---

## Архитектура: три репозитория

Система разделена на три независимых git-репозитория:

```
~/projects/
  myapp/                 # исходники Python-проекта
  project-graph-tool/    # этот репозиторий — pipeline + viewer
  myapp-graph/           # артефакты графа только для myapp
```

| Репозиторий | Содержимое | Кто имеет доступ |
|-------------|------------|------------------|
| **project** | Код приложения | Команда проекта |
| **tool** (здесь) | CLI, pipeline, viewer, общие правила | Все, кто использует систему |
| **data** | `output/*.json`, `workspace.yaml`, эталоны сценариев | Только владельцы этого проекта |

Команды не видят чужие графы: у каждого проекта свой data-repo с отдельными правами доступа.

---

## Требования

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** — управление зависимостями
- **Pyright** (опционально, для уточнения call graph): `npm i -g @microsoft/pyright`

---

## Установка

### 1. Клонировать tool

```powershell
git clone <url-project-graph-tool> project-graph-tool
cd project-graph-tool
uv sync
```

### 2. Подготовить data workspace

Если data-repo ещё нет — скопируйте шаблон:

```powershell
cd ..
xcopy /E /I project-graph-tool\templates\data-repo myapp-graph
```

Отредактируйте `myapp-graph/workspace.yaml`:

```yaml
project_path: ../myapp   # относительный путь к анализируемому проекту
name: myapp
```

Создайте отдельный git-репозиторий для `myapp-graph/`.

### 3. Расположение на диске

Tool и data-repo ожидают, что лежат **рядом** с проектом:

```
parent/
  myapp/
  project-graph-tool/
  myapp-graph/
```

Скрипты `run.ps1` / `serve.ps1` в data-repo ищут tool по пути `../project-graph-tool`.

---

## Использование

Все команды сборки и просмотра запускаются **из data-repo**, не из tool-repo.

### Трассировка roots

```powershell
cd ..\myapp-graph

# Очередь в config/trace_queue.yaml — обработать всё
.\run.ps1 trace

# Одна точка: определение или вызов
.\run.ps1 trace --def myapp/views/orders.py:42
.\run.ps1 trace --call myapp/services/checkout.py:88
.\run.ps1 trace --def myapp.views.orders.OrderViewSet.create --id create_order

# Битый Jedi/Parso cache или сброс накопительного call graph
.\run.ps1 trace --clear-jedi-cache --def myapp/views/orders.py:42
.\run.ps1 trace --reset-call-graph --def myapp/views/orders.py:42
```

### Просмотр в браузере

```powershell
.\serve.ps1
```

Откройте **http://127.0.0.1:8765/viewer/** — граф из `output/execution_graph.json` загрузится автоматически.

**Раскладка узлов:**
- перетаскивание и масштаб сохраняются в **localStorage** браузера (черновик);
- именованные раскладки — в `layouts/<name>.json` в data-repo (кнопка Save в sidebar viewer).

> Не используйте `python -m http.server` из папки viewer — пути к output будут неверными.

### Инспекция и валидация

```powershell
# Подграф от trace root
.\run.ps1 inspect --root-id create_order

# Сверка с эталонным сценарием
.\run.ps1 inspect --root-id create_order --check-scenario example_flow

# Контекст узла для AI-описания
.\run.ps1 describe-node create_order
```

### Прямой вызов CLI (без run.ps1)

```powershell
cd project-graph-tool
uv run python -m project_graph --workspace ../myapp-graph trace --def myapp/views/orders.py:42
```

---

## Команды CLI

| Команда | Описание |
|---------|----------|
| `trace` | Трассировка roots → `execution_graph.json` |
| `trace` (без args) | Обработать `config/trace_queue.yaml` |
| `trace --def …` | Root = определение (file:line или qname) |
| `trace --call …` | Root = вызов на строке (file:line) |
| `trace --file path` | Roots из YAML-файла |
| `trace --enqueue` | Дописать CLI-указатели в очередь |
| `trace --reset-call-graph` | Очистить накопительный `call_graph.json` перед запуском |
| `trace --clear-jedi-cache` | Очистить кэш Jedi/Parso на диске |
| `inspect --root-id ID` | Подграф и инфра-листья |
| `inspect --check-scenario KEY` | Валидация по `reference_scenarios.yaml` |
| `describe-node ID` | Метаданные + исходник + рёбра |
| `export -o path` | Переэкспорт JSON |

Глобальный флаг (до команды): `--workspace /path/to/data-repo`

---

## Артефакты (data-repo)

| Файл | Содержимое |
|------|------------|
| `config/trace_queue.yaml` | Очередь roots к обработке |
| `config/trace_done.yaml` | Обработанные roots (авто) |
| `output/call_graph.json` | Накопительный кэш call graph (расширяется при каждом trace) |
| `output/execution_graph.json` | Merged execution graph для viewer |
| `layouts/*.json` | Именованные раскладки viewer (позиции узлов, pan/zoom) |
| `output/.cache/` | Кэш AST (в `.gitignore`) |

---

## Конфигурация

### Tool-repo (общие правила)

| Файл | Назначение |
|------|------------|
| `config/node_rules.yaml` | Классификация узлов по пути и имени |
| `config/external_apis.yaml` | Реестр внешних API, БД, очередей |

### Data-repo (проектные настройки)

| Файл | Назначение |
|------|------------|
| `workspace.yaml` | Путь к проекту (`project_path`) |
| `config/trace_queue.yaml` | Очередь trace roots |
| `config/trace_done.yaml` | Обработанные trace roots |
| `config/reference_scenarios.yaml` | Эталоны для `--check-scenario` |

### Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `PROJECT_GRAPH_DATA` | Путь к data-repo (если не cwd) |
| `PROJECT_GRAPH_REPO` | Переопределить `project_path` из workspace |

Приоритет резолва data workspace:

1. `--workspace`
2. `PROJECT_GRAPH_DATA`
3. Текущая директория, если в ней есть `workspace.yaml`

---

## Новый проект

1. Скопируйте `templates/data-repo/` → `your-project-graph/`
2. Задайте `project_path` в `workspace.yaml`
3. Настройте `config/reference_scenarios.yaml`
4. Создайте отдельный git-репозиторий для data workspace
5. Добавьте roots в `config/trace_queue.yaml` и запустите `.\run.ps1 trace`

---

## Структура tool-repo

```
project-graph-tool/
  project_graph/       # Python-пакет (CLI, pipeline, trace_roots)
  viewer/              # Cytoscape UI
  serve.py             # HTTP-сервер (viewer + output)
  config/              # node_rules, external_apis
  templates/data-repo/ # Шаблон data workspace
  graph_model.md       # Контракт JSON-модели
  ARCHITECTURE.md      # Подробная архитектура
```

---

## Описания узлов (Cursor-агент)

Инструкция: [`AGENT_DESCRIBE_NODES.md`](AGENT_DESCRIBE_NODES.md)

Агент правит **только** `<data-repo>/output/execution_graph.json` — поле `description` у узлов. Исходники проекта — read-only.

---

## Устранение неполадок

| Симптом | Решение |
|---------|---------|
| `Data workspace not configured` | Запускайте из data-repo или задайте `PROJECT_GRAPH_DATA` |
| `Tool repo not found` | Положите `project-graph-tool/` рядом с data-repo |
| `Project path does not exist` | Проверьте `project_path` в `workspace.yaml` |
| Viewer пустой / ошибка загрузки | Сначала `.\run.ps1 trace`, затем `.\serve.ps1` |
| Граф не загружается в viewer | Используйте `serve.ps1`, не `http.server` из viewer/ |
| `EOFError` / падение Jedi на отдельном файле | `.\run.ps1 trace --clear-jedi-cache --def …` |

---

## Дополнительно

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — принципы, pipeline, типы узлов
- [`graph_model.md`](graph_model.md) — схема JSON
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — история реализации

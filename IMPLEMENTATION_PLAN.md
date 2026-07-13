# План реализации — статус

Реализовано в `project_graph/` (изолированно от анализируемого проекта).

## Готово

- [x] Фаза 0: `pyproject.toml`, `.gitignore`, `README.md`, `run.ps1`, `run.sh`, `pyrightconfig.json`
- [x] Фаза 1: Pydantic-модели Node/Edge/ExecutionGraph
- [x] Фаза 2: tree-sitter AST + cache
- [x] Фаза 3: Jedi call resolution + optional Pyright bridge
- [x] Фаза 4: Node classifier, scenario tracer, infra detector, NetworkX
- [x] Фаза 5: JSON export + CLI (`trace`, `export`, `inspect`, `describe-node`)
- [x] Фаза 6: Cytoscape viewer (`viewer/`)
- [x] Фаза 7: Явные trace roots (`trace_queue.yaml`, `trace_done.yaml`, `--def` / `--call`)
- [x] Фаза 8: Инкрементальный call graph (BFS от roots, без полного `analyze_all`)

## MVP

```bash
cd myapp-graph
.\run.ps1 trace --def myapp/views/orders.py:42 --id create_order
.\run.ps1 inspect --root-id create_order --check-scenario create_order
.\serve.ps1
```

## Человеку

- `uv sync` при первом запуске
- Pyright: `npm i -g @microsoft/pyright` (опционально)
- Review `config/external_apis.yaml`, `config/node_rules.yaml` в tool-repo
- Добавить roots в `config/trace_queue.yaml` или передать через CLI
- AI-описания через `AGENT_DESCRIBE_NODES.md`

## Масштабирование

Полный скан всего `project_path` больше не используется. `trace` расширяет накопительный `call_graph.json` только от переданных roots (BFS, глубина 15). Повторный trace другого root переиспользует общие узлы по стабильному `node.id`.

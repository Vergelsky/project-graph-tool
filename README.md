# Карта выполнения

Пакет `project_map` строит граф вызовов от явной точки входа и показывает его в браузере.

```powershell
.\.venv\Scripts\python -m project_map cabinet
```

Кабинет: http://127.0.0.1:8770/

Один репозиторий без кабинета:

```powershell
.\.venv\Scripts\python -m project_map create jobs\demo --source C:\path\to\repo --entry app\views.py:42
.\.venv\Scripts\python -m project_map trace jobs\demo
.\.venv\Scripts\python -m project_map serve jobs\demo
```

Тексты карточек пишутся отдельно, ключ берётся из `PROJECT_MAP_API_KEY`. Для закрытого git-адреса токен берётся из `PROJECT_MAP_GIT_TOKEN` и в файлы задания не записывается.

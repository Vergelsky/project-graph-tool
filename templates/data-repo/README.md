# Data workspace template

Скопируйте папку:

```powershell
xcopy /E /I templates\data-repo ..\your-project-graph
```

1. Отредактируйте `workspace.yaml`
2. Добавьте roots в `config/trace_queue.yaml`
3. Создайте git-репозиторий

## Быстрый старт

```powershell
cd your-project-graph
.\run.ps1 trace --def myapp/views/example.py:10
.\serve.ps1
```

Документация: [README](../README.md)

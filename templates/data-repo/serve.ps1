param(
    [int]$Port = 8765
)
$DataRoot = $PSScriptRoot
$ToolRoot = Resolve-Path (Join-Path $PSScriptRoot "..\project-graph-tool")
if (-not (Test-Path $ToolRoot)) {
    Write-Error "Tool repo not found at $ToolRoot. Clone project-graph-tool next to this folder."
    exit 1
}
uv run --directory $ToolRoot python serve.py --data-dir $DataRoot --port $Port

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)
$DataRoot = $PSScriptRoot
$ToolRoot = Resolve-Path (Join-Path $PSScriptRoot "..\project-graph-tool")
if (-not (Test-Path $ToolRoot)) {
    Write-Error "Tool repo not found at $ToolRoot. Clone project-graph-tool next to this folder."
    exit 1
}
$env:PROJECT_GRAPH_DATA = $DataRoot
Set-Location $DataRoot
uv run --directory $ToolRoot python -m project_graph @Args

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)
Write-Error "Run commands from a data workspace (e.g. myapp-graph/run.ps1), not from tool-repo."
exit 1

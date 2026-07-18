$ErrorActionPreference = "Stop"

$python = "C:\Users\lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseDir = Join-Path $projectRoot "standard_graph"
$graph = Join-Path $releaseDir "standard_graph_v2026.07.18.json"
$questions = Join-Path $releaseDir "questions_v2026.07.18.json"
$questionLinks = Join-Path $releaseDir "question_knowledge_links_v2026.07.18.json"

foreach ($requiredFile in @($graph, $questions, $questionLinks)) {
    if (-not (Test-Path -LiteralPath $requiredFile)) {
        throw "正式发布文件不存在：$requiredFile"
    }
}

$arguments = @(
    "api_server.py",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--graph", $graph,
    "--questions", $questions,
    "--question-links", $questionLinks
)

Set-Location -LiteralPath (Join-Path $PSScriptRoot "oop_kg_demo")
& $python @arguments

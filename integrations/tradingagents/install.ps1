param(
    [string]$Python = "python",
    [string]$Root = $PSScriptRoot
)
$ErrorActionPreference = "Stop"
$repository = "https://github.com/TauricResearch/TradingAgents.git"
$commit = "c95f83dfafa748801ab2be4855e6fcffc93804e4"
$upstream = Join-Path $Root "upstream"
$venv = Join-Path $Root ".venv"

if (-not (Test-Path $upstream)) {
    git clone $repository $upstream
}
git -C $upstream fetch --depth 1 origin $commit
git -C $upstream checkout --detach $commit
$resolved = (git -C $upstream rev-parse HEAD).Trim()
if ($resolved -ne $commit) { throw "Pinned TradingAgents commit verification failed" }

if (-not (Test-Path $venv)) { & $Python -m venv $venv }
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --disable-pip-version-check $upstream
& $venvPython -c "import tradingagents; print('TradingAgents import PASS')"

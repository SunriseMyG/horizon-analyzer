<#
.SYNOPSIS
  Lance toutes les suites contre la prod : smoke (headless), puis critical et engine (navigateur visible).

.DESCRIPTION
  Au premier lancement (ou avec -Setup), crée le venv, installe le paquet et Chromium.
  Il faut un fichier .env (copie de .env.example) avec le compte de test.
  Code de sortie : 0 si tout passe, 1 si une feature échoue ou est bloquée, 2 si un fichier
  est invalide.

.EXAMPLE
  .\run-all.ps1
  .\run-all.ps1 -Setup        # réinstalle les dépendances
  .\run-all.ps1 -SlowMo 300   # ralentit chaque action pour suivre à l'œil
#>
param(
    [switch]$Setup,
    [int]$SlowMo = 0
)

Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$cli = Join-Path $PSScriptRoot '.venv\Scripts\horizon-analyzer.exe'

if ($Setup -or -not (Test-Path $cli)) {
    Write-Host '== Installation (venv, dépendances, Chromium)'
    if (-not (Test-Path $python)) { python -m venv .venv }
    & $python -m pip install --quiet --upgrade pip
    & $python -m pip install --quiet -e '.[dev]'
    & $python -m playwright install chromium
}

if (-not (Test-Path '.env')) {
    Write-Host '.env manquant : copier .env.example en .env et renseigner le compte de test.' -ForegroundColor Red
    exit 2
}

Write-Host "`n== Smoke (headless, sans écriture)" -ForegroundColor Cyan
& $cli run scenarios\smoke.yaml --headless
$smoke = $LASTEXITCODE

Write-Host "`n== Parcours critique (navigateur visible, GPU)" -ForegroundColor Cyan
& $cli run scenarios\critical.yaml --slow-mo $SlowMo
$critical = $LASTEXITCODE

Write-Host "`n== Moteur : scripts, lumière, ombres, reflets, modèle importé (navigateur visible, GPU)" -ForegroundColor Cyan
& $cli run scenarios\engine.yaml --slow-mo $SlowMo
$engine = $LASTEXITCODE

Write-Host ''
$results = [ordered]@{ smoke = $smoke; critical = $critical; engine = $engine }
foreach ($name in $results.Keys) {
    $code = $results[$name]
    $label = if ($code -eq 0) { 'OK' } elseif ($code -eq 2) { 'FICHIER INVALIDE' } else { 'ÉCHEC' }
    $color = if ($code -eq 0) { 'Green' } else { 'Red' }
    Write-Host ("  {0,-9} {1}" -f $name, $label) -ForegroundColor $color
}
Write-Host '  engine : 2 KO attendus (modèle corrompu, texture en skybox), voir docs\scenarios.md' -ForegroundColor DarkGray
Write-Host '  Rapports : runs\<run id>\report.html'
exit (($smoke, $critical, $engine | Measure-Object -Maximum).Maximum)

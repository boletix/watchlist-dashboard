# commit_changes.ps1
# ─────────────────────────────────────────────────────────────────────────────
# 1) Copia el SKILL.md actualizado a su ubicación en Claude
# 2) Hace git add + commit + push de los nuevos archivos de scripts
#
# Ejecutar desde la raíz del repo (watchlist-dashboard\watchlist-dashboard):
#   .\data\raw\scripts\commit_changes.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path (Split-Path $PSScriptRoot))

Write-Host "📁 Repo root: $RepoRoot" -ForegroundColor Cyan

# ── 1) Instalar SKILL.md actualizado ─────────────────────────────────────────
Write-Host "`n🔧 Actualizando SKILL.md de update-watchlist-ticker..." -ForegroundColor Yellow
$SkillsBase  = "$env:APPDATA\Claude\local-agent-mode-sessions\skills-plugin"
$SkillSource = "$PSScriptRoot\update-watchlist-ticker-SKILL.md"

$Targets = Get-ChildItem -Path $SkillsBase -Recurse -Filter "SKILL.md" -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -like "*update-watchlist-ticker*" }

if ($Targets) {
    foreach ($t in $Targets) {
        Copy-Item -Path $SkillSource -Destination $t.FullName -Force
        Write-Host "  ✅ Copiado a: $($t.FullName)" -ForegroundColor Green
    }
} else {
    Write-Warning "No se encontró la carpeta del skill. Puedes copiar manualmente:`n  $SkillSource"
}

# ── 2) Git add, commit y push ─────────────────────────────────────────────────
Write-Host "`n🔀 Commiteando cambios en git..." -ForegroundColor Yellow
Set-Location $RepoRoot

# Archivos nuevos/modificados
$FilesToAdd = @(
    "data/raw/scripts/check_earnings_trigger.py",
    "data/raw/scripts/restore_column_a.py",
    "data/raw/scripts/update-watchlist-ticker-SKILL.md",
    "data/raw/scripts/install_skill_update.ps1",
    "data/raw/scripts/commit_changes.ps1"
)

foreach ($f in $FilesToAdd) {
    $fullPath = Join-Path $RepoRoot $f
    if (Test-Path $fullPath) {
        git add $f
        Write-Host "  + $f" -ForegroundColor Gray
    } else {
        Write-Warning "  Archivo no encontrado, omitiendo: $f"
    }
}

$Date = Get-Date -Format "yyyy-MM-dd"
git commit -m "feat: scan pendientes IR + restauración col A ($Date)

- check_earnings_trigger.py: detecta tickers con BO <= hoy y sin actualizar
- restore_column_a.py: restaura A4:última_fila desde el backup más reciente
- update-watchlist-ticker SKILL.md: Modo B (scan pendientes via IR) + paso F (restaurar col A)"

git push

Write-Host "`n✅ Push completado." -ForegroundColor Green

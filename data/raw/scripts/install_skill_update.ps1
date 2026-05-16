# install_skill_update.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Copia el SKILL.md actualizado de update-watchlist-ticker a su ubicación
# correcta en la carpeta de skills de Claude.
#
# Ejecutar UNA VEZ desde PowerShell (como usuario normal, sin admin):
#   .\install_skill_update.ps1
# ─────────────────────────────────────────────────────────────────────────────

$Source = "$PSScriptRoot\update-watchlist-ticker-SKILL.md"
$SkillsBase = "$env:APPDATA\Claude\local-agent-mode-sessions\skills-plugin"
$SkillName = "update-watchlist-ticker"

# Buscar la carpeta del skill (puede haber varias subcarpetas con IDs)
$Candidates = Get-ChildItem -Path $SkillsBase -Recurse -Filter "SKILL.md" -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -like "*$SkillName*" }

if (-not $Candidates) {
    Write-Error "No se encontró la carpeta del skill '$SkillName' bajo $SkillsBase"
    exit 1
}

foreach ($Candidate in $Candidates) {
    $Dest = $Candidate.FullName
    Write-Host "Copiando SKILL.md a: $Dest"
    Copy-Item -Path $Source -Destination $Dest -Force
    Write-Host "  ✅ Hecho." -ForegroundColor Green
}

Write-Host ""
Write-Host "✅ SKILL.md de '$SkillName' actualizado correctamente." -ForegroundColor Green
Write-Host "   Reinicia Claude para que los cambios surtan efecto." -ForegroundColor Yellow

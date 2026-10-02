# escribir_celdas.ps1 - escribe celdas sueltas en watchlist_ratings.xlsx con Excel COM.
#
# NUNCA editar el .xlsx con openpyxl: la columna A lleva tipos de datos vinculados
# (=A9.Precio) que openpyxl destruye. Este script lee data/celdas_payload.csv
# (fila,col,valor,tipo con tipo = num | text), escribe, recalcula, comprueba que los
# tipos vinculados siguen vivos y guarda.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\escribir_celdas.ps1 [filas a mostrar]
#
# Trampas que resuelve (ver memoria excel-sin-python-com-espanol):
#  - Workbooks.Open devuelve NULL si salta el dialogo de actualizar vinculos -> args explicitos
#  - Worksheets NULL justo despues de abrir -> reintento
#  - RPC_E_CALL_REJECTED con muchas escrituras -> calculo manual durante la escritura
#  - fechas: se escriben como TEXTO dd/mm/yyyy con NumberFormat "@" (COM parsea en en-US)
#  - rutas con acentos: se localiza el fichero por comodin, sin escribir la ruta
param([string]$Mostrar = "")

$ErrorActionPreference = "Stop"
$base = Join-Path $env:USERPROFILE "Cosas Roger"
$xlsx = Get-ChildItem -LiteralPath $base -Recurse -Filter "watchlist_ratings.xlsx" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*watchlist-dashboard*data*raw*" } | Select-Object -First 1
if (-not $xlsx) { throw "No encuentro watchlist_ratings.xlsx" }
$p = $xlsx.FullName
$csvPath = Join-Path $xlsx.Directory.Parent.FullName "celdas_payload.csv"
if (-not (Test-Path -LiteralPath $csvPath)) { throw "No encuentro data\celdas_payload.csv" }
$csv = Import-Csv -LiteralPath $csvPath -Encoding UTF8
Write-Output ("Excel  : " + $p)
Write-Output ("Payload: " + $csv.Count + " celdas")

$filas = @()
if ($Mostrar -ne "") { $filas = $Mostrar.Split(",") | ForEach-Object { [int]$_ } }
else { $filas = $csv | ForEach-Object { [int]$_.fila } | Sort-Object -Unique }

Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.AskToUpdateLinks = $false
$xl.AutomationSecurity = 3
$xl.ScreenUpdating = $false
$xl.EnableEvents = $false

$wb = $xl.Workbooks.Open($p, 0, $false, [Type]::Missing, [Type]::Missing, [Type]::Missing, $true, [Type]::Missing, [Type]::Missing, [Type]::Missing, $false)
if ($null -eq $wb) { $xl.Quit(); throw "Workbooks.Open devolvio NULL" }
$ws = $null
for ($i = 1; $i -le 15; $i++) {
  Start-Sleep -Milliseconds 1000
  try { $ws = $wb.Worksheets.Item("Watchlist Ratings") } catch { $ws = $null }
  if ($null -ne $ws) { break }
}
if ($null -eq $ws) { $xl.Quit(); throw "No se pudo obtener la hoja" }
$xl.Calculation = -4135

function Linea($f) {
  return ("  f" + $f + " " + ([string]$ws.Cells($f,2).Text).PadRight(8) +
          " AS=" + ([string]$ws.Cells($f,45).Text).PadLeft(10) +
          " rev=" + ([string]$ws.Cells($f,48).Text).PadLeft(10) +
          " BD=" + ([string]$ws.Cells($f,56).Text).PadLeft(9) +
          " BF=" + ([string]$ws.Cells($f,58).Text).PadLeft(9) +
          " EV/FCF=" + ([string]$ws.Cells($f,49).Text).PadLeft(8) +
          " BO=" + [string]$ws.Cells($f,67).Text + " BP=" + [string]$ws.Cells($f,68).Text)
}

Write-Output "--- ANTES ---"
foreach ($f in $filas) { Write-Output (Linea $f) }

$n = 0
foreach ($r in $csv) {
  $cell = $ws.Cells([int]$r.fila, [int]$r.col)
  if ($r.tipo -eq "text") { $cell.NumberFormat = "@"; $cell.Value2 = [string]$r.valor }
  else { $cell.Value2 = [double]$r.valor }
  $n = $n + 1
}
Write-Output ("Escritas " + $n + " celdas")

$xl.Calculation = -4105
$xl.CalculateFullRebuild()
Start-Sleep -Seconds 2

Write-Output "--- TIPOS DE DATOS VINCULADOS ---"
Write-Output ("  A9 HasRichDataType : " + $ws.Cells(9,1).HasRichDataType)
Write-Output ("  G4 / G8 / G9       : " + [string]$ws.Cells(4,7).Text + " / " + [string]$ws.Cells(8,7).Text + " / " + [string]$ws.Cells(9,7).Text)
Write-Output "--- DESPUES ---"
foreach ($f in $filas) { Write-Output (Linea $f) }

$wb.Save()
Write-Output "GUARDADO OK"
$wb.Close($false)
$xl.Quit()
Start-Sleep -Milliseconds 800
Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Output "Excel cerrado."

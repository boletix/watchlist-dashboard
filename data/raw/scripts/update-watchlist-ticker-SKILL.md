---
name: update-watchlist-ticker
description: "Debes actualizar el excel de watchlist_rating con las últimas noticias y resultados"
---

# Watchlist Ratings Updater (Local) — con Log de Updates

## Contexto fijo (NO preguntar)
- Archivo Excel (local):
  C:\Users\roger\Downloads\watchlist-dashboard\watchlist-dashboard\data\raw\watchlist_ratings.xlsx
- Hoja a actualizar: "Watchlist Ratings"
- Hoja de auditoría: "Updates Log" (si no existe, crearla)
- Script de restauración col A:
  C:\Users\roger\Downloads\watchlist-dashboard\watchlist-dashboard\data\raw\scripts\restore_column_a.py

---

## Dos modos de uso

### Modo A — Ticker específico (el usuario pide un ticker concreto)
El usuario escribe, por ejemplo: "Actualiza MSFT" o pega texto de resultados de NVDA.
→ Saltar al bloque "Flujo de actualización" directamente para ese ticker.

### Modo B — Scan completo (el usuario no especifica ticker, o pide "escanear" / "ver qué hay que actualizar")
→ Ejecutar primero el "Scan de pendientes" descrito a continuación, luego aplicar el flujo de actualización a cada empresa detectada.

---

## Scan de pendientes (Modo B)

### Lógica de detección
Abrir el Excel y, para cada fila de la hoja "Watchlist Ratings" a partir de la fila 4:

1. Leer **col BN** ("Última actualización") → fecha en que se actualizó por última vez el ticker.
2. Leer **col BO** ("Últimos resultados") → fecha en que la empresa presentó sus últimos resultados.
3. Leer **col B** ("Ticker") → identificador de la empresa.

**Condición para marcar como PENDIENTE de actualización:**
```
BO es una fecha válida (no N/D, no vacío)
  Y  BO <= hoy                          ← los resultados ya se han presentado
  Y  (BN está vacío/N/D  O  BN < BO)   ← no hemos actualizado desde esos resultados
```

En otras palabras: si la empresa presentó resultados en una fecha que ya ha pasado, y nuestra última actualización es anterior a esa presentación (o no existe), el ticker está pendiente.

### Salida del scan
Antes de actualizar nada, mostrar al usuario una tabla resumen:

| Ticker | Últimos resultados (BO) | Última actualización (BN) | Días sin actualizar |
|--------|------------------------|--------------------------|---------------------|
| MSFT   | 2026-01-28             | 2025-11-05               | 84                  |
| …      | …                      | …                        | …                   |

Y preguntar: **"¿Actualizo todos estos tickers o prefieres que empiece por alguno en concreto?"**

Esperar confirmación antes de arrancar el flujo de actualización.

---

## Flujo de actualización (para cada ticker)

### A) Inspect (interno)
- Abrir el Excel.
- Confirmar hojas "Watchlist Ratings" y "Updates Log".
- Detectar la fila de headers (fila con "Company Name" en col A).
- Localizar la fila del ticker en col B.

### B) Buscar datos en la página de Investor Relations
Ir a la página oficial de Investor Relations de la empresa:

1. Buscar en la web: `"{TICKER}" OR "{nombre empresa}" investor relations results {AÑO}`
2. Navegar directamente a la sección de resultados/earnings de su web IR.
3. Localizar la presentación, press release o earnings release más reciente.
4. Si la empresa es europea, buscar también en el idioma local (ej. "resultados trimestrales", "résultats", "Quartalsergebnisse", etc.).

**Prioridad de fuentes (de mayor a menor fiabilidad):**
1. Web IR oficial de la empresa (earnings release, press release, presentation PDF)
2. SEC EDGAR / EDGAR filing (para empresas US)
3. Bolsa local (BME, Euronext, LSE, etc.)
4. Bloomberg, Reuters solo para confirmar cifras (no como fuente primaria)

Extraer del documento encontrado los valores que correspondan a columnas editables del Excel.

### C) Extraer campos
Del texto/PDF encontrado, construir el mapa `extracted_fields`:
- `{NombreDeColumnaEnExcel: valor}`
- `source`: URL o referencia de la fuente
- `summary_1_2_lines`: 1–2 líneas con lo más relevante

Campos financieros prioritarios a extraer (si están disponibles):
- Cash & Equivalents (col AP)
- Total Debt (col AQ)
- FCF LTM unlevered (col AS)
- NOPAT LTM (col AT)
- EBITDA LTM (col AU)
- Revenue LTM (col AV)
- Capital Employed (col AZ)
- FCF @5y Min / Max (cols BD, BF) — solo si hay guidance nuevo
- Últimos resultados (col BO) → fecha de la presentación encontrada (DD/MM/YYYY)
- Próximos resultados (col BP) → si se anuncia la siguiente fecha (DD/MM/YYYY)
- Última actualización (col BN) → fecha de hoy (DD/MM/YYYY)

### D) Update — con Change Log
Para cada campo en `extracted_fields`:
- Si la columna está protegida → `SKIP_PROTECTED`
- Si la celda contiene una fórmula → `SKIP_FORMULA`
- Si el header no existe en el Excel → `NOT_FOUND_HEADER`
- Si se escribe el valor → `UPDATED`

**Columnas que NUNCA se modifican:**
- A a I (cols 1–9)
- R, S, AB, AC, AL, AM, AN, AO, AR, AW, AX, AY, BA, BB, BC, BE, BG, BH, BI, BJ, BK, BL, BM

**Regla de negocio — Capital Intensity (col AF, Rating 3):**
Más alto = más asset-light · Más bajo = más intensivo en capital.

### E) Guardado seguro
1. Crear backup ANTES de modificar:
   `watchlist_ratings.backup_YYYYMMDD_HHMM.xlsx` (misma carpeta)
2. Guardar el Excel actualizado en la ruta original.

### F) Restaurar Columna A (OBLIGATORIO tras cada guardado)
```bash
python "C:\Users\roger\Downloads\watchlist-dashboard\watchlist-dashboard\data\raw\scripts\restore_column_a.py"
```
- Copia A4:última_fila desde el backup más reciente al Excel principal.
- Si devuelve `"status": "error"`, informar al usuario inmediatamente.

### G) Audit Log (OBLIGATORIO)
En la hoja "Updates Log" (crearla si no existe con headers: Ticker | Fecha | Campos cambiados | Fuente | Resumen):
- **Ticker**: el ticker
- **Fecha**: hoy (YYYY-MM-DD)
- **Campos cambiados**: `"; ".join(changed_fields)` (o "Sin cambios aplicables" si todo protegido/fórmulas)
- **Fuente**: URL o referencia
- **Resumen**: `summary_1_2_lines`

---

## Salida obligatoria al usuario (siempre)

Para cada ticker procesado:
1. Resumen de 1–2 líneas (qué cambió y qué vigilar)
2. Change log (UPDATED / SKIP_PROTECTED / SKIP_FORMULA / NOT_FOUND_HEADER)
3. Confirmación de backup creado
4. Resultado JSON del script `restore_column_a.py`
5. Fila de auditoría añadida

Si se procesaron varios tickers (Modo B), mostrar también la tabla resumen final:

| Ticker | Estado | Campos actualizados | Fuente |
|--------|--------|---------------------|--------|
| MSFT   | ✅     | Revenue, FCF, EBITDA | microsoft.com/ir |
| GOOG   | ⚠️ Sin datos nuevos | — | — |

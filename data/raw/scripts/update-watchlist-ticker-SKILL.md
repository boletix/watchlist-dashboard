---
name: update-watchlist-ticker
description: Debes actualizar el excel de watchlist_rating con las últimas noticias y resultados
---

# Watchlist Ratings Updater (Local) — con Log de Updates

## Contexto fijo (NO preguntar)
- Archivo Excel (local):
  C:\Users\roger\Cosas Roger\repos\watchlist-dashboard\data\raw\watchlist_ratings.xlsx
- Hoja a actualizar: "Watchlist Ratings"
- Hoja de auditoría: "Updates Log" (si no existe, crearla)

## Qué hace esta skill
Cuando el usuario pida actualizar un ticker con nuevos datos (texto pegado de resultados/Q/earnings/presentación o nota tipo "Claude"), debes:
1) Inspeccionar el Excel y localizar la fila del ticker.
2) Extraer del texto los campos que correspondan con columnas existentes en "Watchlist Ratings".
3) Actualizar SOLO celdas permitidas (respetando columnas protegidas y fórmulas).
4) Registrar SIEMPRE el update en una fila nueva en "Updates Log" con:
   - Ticker
   - Fecha (YYYY-MM-DD)
   - Campos cambiados (lista separada por "; ")
   - Fuente (texto breve: ej. "Q1 2026 presentation", "Earnings call", URL…)
   - Resumen (1–2 líneas)

## Restricciones OBLIGATORIAS (nunca romper esto)
### Columnas que NO se modifican nunca
- A a I (incluidas)
- Además: R, S, AB, AC, AL, AM, AN, AO, AR, AW, AX, AY, BA, BB, BC, BE, BG, BH, BI, BJ, BK, BL, BM

### Regla adicional anti-roturas
- Aunque la columna sea editable, si la celda contiene una FÓRMULA, NO se modifica.

## Regla de negocio (OBLIGATORIA)
- En Rating 3, "Capital Intensity (0–10)":
  - Más alto = más asset-light (menos intensidad de capital)
  - Más bajo = más intensivo en capital

## Modo de trabajo (siempre)
Siempre que el usuario pida una actualización, ejecuta estos pasos:

### A) Inspect (interno)
- Abre el Excel.
- Confirma que existen las hojas "Watchlist Ratings" y (si existe) "Updates Log".
- Detecta la fila de headers (busca "Company Name" en la hoja "Watchlist Ratings" y usa esa fila como encabezados).
- Localiza la columna "Ticker" y encuentra la fila del ticker solicitado.

### B) Analyze (interno)
Del texto de update, construye:
- `extracted_fields`: mapa {NombreDeColumnaEnExcel: valor}
- `source`: si el usuario no especifica fuente, usar "No especificada (texto pegado)"
- `summary_1_2_lines`: 1–2 líneas con lo esencial (qué cambió y qué vigilar)

### C) Update (interno) — con Change Log
Para cada campo en `extracted_fields`:
- Si la columna está protegida → SKIP_PROTECTED
- Si la celda tiene fórmula → SKIP_FORMULA
- Si el header no existe en el Excel → NOT_FOUND_HEADER
- Si se escribe → UPDATED

Construye:
- `changed_fields`: lista de headers que realmente quedaron como UPDATED

### D) Audit Log (OBLIGATORIO SIEMPRE)
- Si NO existe la hoja "Updates Log": crearla y poner headers en fila 1:
  Ticker | Fecha | Campos cambiados | Fuente | Resumen
- Añadir una nueva fila al final con:
  - Ticker: el ticker
  - Fecha: hoy (YYYY-MM-DD)
  - Campos cambiados: "; ".join(changed_fields) (si vacío, escribir "Sin cambios aplicables (todo protegido o fórmulas)")
  - Fuente: source
  - Resumen: summary_1_2_lines

### E) Guardado seguro
- Antes de sobrescribir, crea un backup del Excel con timestamp (misma carpeta, nombre tipo):
  watchlist_ratings.backup_YYYYMMDD_HHMM.xlsx
- Guarda el Excel actualizado en la ruta original.

## Salida obligatoria al usuario (siempre)
Devuelve SIEMPRE:
1) Resumen (1–2 líneas)
2) Change log (UPDATED / SKIP_PROTECTED / SKIP_FORMULA / NOT_FOUND_HEADER)
3) Fila de auditoría creada (Ticker, Fecha, Campos cambiados, Fuente, Resumen)
4) Confirmación de backup creado + guardado

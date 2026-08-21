---
name: update-watchlist-ticker
description: Debes actualizar el excel de watchlist_rating con las últimas noticias y resultados
---

# Watchlist Ratings Updater (Local) — con Log de Updates

## Contexto fijo (NO preguntar)
- Archivo Excel (local):
  C:\Users\roger\Cosas Roger\BOLSA E INVERSIÓN\repos\watchlist-dashboard\data\raw\watchlist_ratings.xlsx
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

## Regla de DIVISA (OBLIGATORIA — alta de empresa nueva o cambio de listing)

Contexto: el 17/08/2026 se detectó que 11 de 63 empresas tenían las TIR "repriced" del dashboard sin sentido porque el pipeline dividía un valor por acción en la **moneda de reporte** entre un precio en la **moneda de cotización**. KSPI (reporta en tenge, cotiza en dólares) salía con una TIR de +588% y encabezaba el ranking de asimetría; HLMA, JDG, KIST y WOSG (cotizan en peniques, reportan en libras) salían con TIR del −57% al −69%. Ya está corregido en `src/fx.py`, pero la corrección **solo funciona si estas dos columnas del Excel son correctas**.

Al dar de alta un ticker nuevo, o si una empresa cambia de mercado, es OBLIGATORIO:

1. **Rellenar las dos columnas por separado y no darlas por iguales:**
   - `Currency` → moneda en la que **cotiza** la acción (la del precio).
   - `FX Reporting` → moneda en la que la empresa **publica sus cuentas** (la del FCF, la caja y la deuda de las columnas del Excel).

2. **Comprobarlo contra yfinance, no de memoria.** El símbolo tiene que estar en `src/tickers.py`:
   ```
   python -c "import yfinance as yf; fi=yf.Ticker('SIMBOLO').fast_info; print(fi['currency'], fi['lastPrice'])"
   ```
   Casos que engañan y que ya han fallado una vez:
   - Los tickers `.L` (Londres) devuelven **`GBp`** (peniques), no `GBP`. Se diferencian solo por la caja de la última letra.
   - **ADR y listings secundarios**: KSPI cotiza en el Nasdaq en USD pero reporta en KZT. Que el precio esté en dólares no quiere decir que las cuentas lo estén.
   - **El Excel puede estar desactualizado**: NTO tiene `Currency = EUR` pero el símbolo mapeado es `7974.T` y el precio llega en JPY. Manda siempre lo que devuelve yfinance; la columna del Excel es solo el respaldo para cuando no hay conexión.

3. **Verificar que el par se resuelve** antes de dar el alta por buena. Si `FX Reporting` ≠ `Currency`, el pipeline necesita un tipo de cambio:
   ```
   python -c "from src.fx import conversion_factor; print(conversion_factor('KZT','USD'))"
   ```
   Si devuelve `None`, el ticker entrará en el dashboard con las TIR repriced en NaN (a propósito: es preferible un hueco visible a un número falso). Anótalo en el resumen al usuario en vez de dejarlo pasar.

4. **Verificación de cordura del resultado.** Tras cualquier alta, la TIR "mejor" repriced debería quedar en un rango creíble (aproximadamente −30% a +60%). Si sale por encima del 100% o por debajo del −50%, la causa más probable NO es una oportunidad excepcional sino un desajuste de divisa o de unidades. Compárala con las columnas `irr_best` / `irr_worst` que ya trae el Excel: si las dos parejas discrepan mucho, hay un problema de datos.

5. **Nunca "arreglarlo"** metiendo el FCF ya convertido a mano en el Excel. El Excel guarda las cuentas en la moneda de reporte y la conversión la hace `src/fx.py` en cada build con el tipo de cambio del día. Convertir a mano congela un tipo de cambio viejo y rompe la trazabilidad.

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
5) **Solo en altas nuevas**: `Currency` y `FX Reporting` con los que queda el ticker, si coinciden o no, y si el par de divisas se resuelve. Una línea basta: `KSPI — cotiza USD / reporta KZT — par KZT→USD resuelto (0,0019)`.

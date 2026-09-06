# PROMPT PARA ANTIGRAVITY — COMPLETACIÓN DEL UNIVERSO ESPAÑOL (~200 EMISORES)
## STATER MOTOR ARGOS — MOD_01_INGESTION — Cierre del Catálogo Maestro

Este prompt es complementario a `PROMPT_ANTIGRAVITY_MOTOR_INSTITUCIONAL_CNMV.md`
(arquitectura ya implementada y validada: 55/55 tests, auditor forense y
remediación ejecutados sobre datos reales) y al prompt de clasificación
HITL/ML ya entregado. No repite esa arquitectura: la usa. Su único objetivo
es cerrar el hueco de cobertura verificada en `config/master_universe_es.json`.

---

## 0. DIAGNÓSTICO DE PARTIDA (VERIFICADO, NO ESTIMADO)

He inspeccionado `config/master_universe_es.json` tal y como está ahora mismo
en disco. Estado real:

```
"total_entities": 141   (objetivo: ~200)
"segments_breakdown": {
  "IBEX35": 34,             ← COMPLETO (objetivo 33-35, cerrado)
  "MERCADO_CONTINUO": 65,   ← INCOMPLETO (objetivo ~95, faltan ~30)
  "BME_GROWTH": 42          ← INCOMPLETO (objetivo ~72, faltan ~30)
}
```

El hueco es real y está concentrado en dos segmentos: Mercado Continuo
(mid/small caps fuera del IBEX35) y BME Growth (empresas en expansión). Este
prompt existe para cerrar exactamente ese hueco, con el mismo rigor anti-
Prosegur que ya protege al resto del catálogo — no para añadir 60 filas
rellenadas a bulto.

## 1. LEY FUNDAMENTAL — SE HEREDA SIN EXCEPCIONES

Todo lo establecido en `PROMPT_ANTIGRAVITY_MOTOR_INSTITUCIONAL_CNMV.md`
Sección 2 aplica aquí sin relajación:

1. **Prohibido fabricar entidades.** Ninguna fila nueva en
   `master_universe_es.json` puede añadirse sin CIF/NIF verificable y LEI
   resuelto contra GLEIF con `resolution_score >= 0.90` (o `null` explícito
   si el emisor no dispone de LEI, lo cual debe declararse, no omitirse).
2. **Prohibido inventar segmentación.** El `segment` (IBEX35 /
   MERCADO_CONTINUO / BME_GROWTH) y el `is_socimi` deben verificarse contra
   fuente oficial (BME, CNMV), nunca inferirse por el nombre.
3. **Toda entidad añadida debe ser auditable**: mismo esquema exacto que las
   141 ya existentes (`ticker`, `cif_nif`, `lei`, `name_legal`, `segment`,
   `sector`, `is_socimi`, `fiscal_year_end`, `historical_name_changes`,
   `resolution_score`, `resolved_at`).

## 2. FUENTES OFICIALES A USAR PARA CERRAR EL HUECO (EN ESTE ORDEN)

1. **BME (Bolsas y Mercados Españoles) — listados oficiales públicos**:
   - Mercado Continuo: listado de emisores del SIBE (Sistema de
     Interconexión Bursátil Español), excluyendo SICAVs y SOCIMIs.
   - BME Growth: listado oficial de "Empresas en Expansión" y "Empresas SOCIMI"
     — de este segundo grupo se excluyen explícitamente las SOCIMIs (deja
     constancia en `is_socimi: true` de las que sí se detecten, para que
     `master_universe_builder.py` las filtre, no las borres silenciosamente:
     regístralas con `segment: "BME_GROWTH_SOCIMI_EXCLUDED"` para trazabilidad,
     pero no las cuentes en el total de 200).
2. **CNMV — Registro Oficial de Emisores** (`cnmv.es`, registro de entidades
   supervisadas): fuente de verificación cruzada de CIF y razón social exacta.
3. **GLEIF API** (`api.gleif.org/api/v1/lei-records`) — resolución de LEI por
   nombre legal + CIF, reutilizando `entity_resolver.py` ya existente, con el
   mismo umbral `>= 0.90` que ya bloquea el caso Prosegur/ACS.
4. **`filings.xbrl.org`** — para verificar de paso si el emisor ya tiene
   histórico ESEF indexado (esto no es obligatorio para incluirlo en el
   catálogo, pero es información valiosa de cobertura documental futura;
   guárdala como campo adicional opcional `has_esef_filings_since` si quieres,
   sin romper el esquema base).

Si alguna fuente no es accesible por scraping desde este entorno (recuerda:
`cnmv.es` ya dio 403 en pruebas previas), documenta el bloqueo con precisión
técnica exacta (código HTTP, mensaje, cabeceras) en vez de simular una
respuesta. Es preferible dejar un hueco marcado como
`PENDING_MANUAL_SOURCE_VERIFICATION` que rellenarlo con una suposición.

## 3. TRABAJO CONCRETO SOBRE `master_universe_builder.py`

`master_universe_builder.py` ya existe y ya construyó las 141 entidades
actuales. No lo reescribas desde cero: extiéndelo con este comportamiento
nuevo, ejecutable de forma incremental y reanudable:

1. **Modo `--fill-gap`**: nuevo modo de ejecución
   (`python -m mod_01_ingestion.src.master_universe_builder --fill-gap
   --segment MERCADO_CONTINUO` / `--segment BME_GROWTH`) que:
   - Descarga/consulta el listado oficial del segmento indicado (Sección 2).
   - Compara contra las claves `ticker` ya presentes en
     `master_universe_es.json` para no duplicar.
   - Para cada emisor nuevo candidato, ejecuta `entity_resolver.py` para
     resolver LEI + CIF con el mismo umbral estricto que ya protege al resto
     del catálogo.
   - Solo añade la entidad si `resolution_score >= 0.90` **o** si el CIF
     coincide exactamente contra fuente oficial (regla ya establecida en el
     prompt madre). Si no se alcanza ese umbral, la entidad queda en un
     archivo separado `config/master_universe_es_PENDING_REVIEW.json` con el
     motivo exacto del fallo de resolución (score obtenido, candidatos
     alternativos encontrados en GLEIF), para revisión humana — nunca se
     descarta en silencio ni se fuerza su inclusión.
2. **Idempotencia**: ejecutar `--fill-gap` dos veces seguidas no debe generar
   duplicados ni sobrescribir entidades ya resueltas con `resolution_score`
   más alto por una resolución posterior más débil.
3. **Versionado**: cada ejecución que modifique `master_universe_es.json`
   incrementa el campo `version` (semver) y actualiza `generated_at`;
   conserva la versión anterior en
   `config/history/master_universe_es_v{N}.json` para poder revertir si una
   incorporación resulta errónea.
4. **Casos especiales conocidos que debes resolver explícitamente** (ya
   detectados en informes previos de este proyecto, no los ignores):
   - Empresas con cambios de nombre societario recientes (Red Eléctrica →
     Redeia, fusión Unicaja/Liberbank, Prosegur vs Prosegur Cash como
     entidades LEI distintas) — deben quedar en `historical_name_changes`
     con fecha del cambio, para que el `entity_resolver` no las confunda
     entre sí en descargas futuras.
   - Empresas con cierre de ejercicio fiscal no natural (ej. Logista, cierre
     a 30 de septiembre) — `fiscal_year_end` debe reflejar la fecha real, no
     asumir `12-31` por defecto.
   - Empresas que cambiaron de segmento (traslado de BME Growth a Mercado
     Continuo, o salida a otra jurisdicción como Ferrovial a Países Bajos/AFM)
     — documenta el segmento vigente a fecha de `resolved_at` y dónde
     reportaba antes, para que `source_router.py` no intente el canal
     equivocado en años previos al traslado.

## 4. CRITERIO DE EXCLUSIÓN ESTRICTO (NO RELAJAR)

Mantén exactamente el mismo criterio que ya dejó el catálogo en 0 SOCIMIs
contadas dentro del universo operativo:
- SOCIMIs (régimen fiscal especial, art. 9 Ley 11/2009): excluidas del total
  de 200, registradas aparte solo para trazabilidad si aparecen en el
  listado oficial de BME Growth o Continuo.
- SICAVs y vehículos de inversión colectiva pura: excluidos.
- Sociedades de cartera / cascarones sin actividad operativa real: excluidos,
  con nota del motivo de exclusión en el informe final (Sección 6).

No añadas una entidad "para llegar a 200" si no supera este filtro. El
objetivo no es la cifra 200, es la cobertura real y limpia del universo
operativo verificable.

## 5. IMPACTO EN EL RESTO DEL PIPELINE (VERIFICAR, NO ROMPER)

Tras ampliar el catálogo:

1. Ejecuta `source_router.py` sobre las nuevas entidades para confirmar que
   cada una recibe un canal de descarga válido según su segmento y años
   disponibles (Canal A/B/C/D ya definidos en el prompt madre).
2. Ejecuta `forensic_dataset_auditor.py --scope ES_CNMV` de nuevo tras la
   ampliación, para detectar si alguna de las nuevas entidades ya tenía
   archivos previos mal identificados en `data/raw/ES_CNMV/` que ahora, con
   identidad correctamente resuelta, deban re-clasificarse.
3. Confirma que la suite completa de tests sigue en verde:
   `python -m pytest -q mod_01_ingestion/tests/` (línea base actual: 55/55).
   Añade tests nuevos específicos:
   - Test de que `--fill-gap` no duplica entidades ya existentes.
   - Test de que una entidad con score < 0.90 termina en
     `master_universe_es_PENDING_REVIEW.json`, nunca en el catálogo activo.
   - Test de que el total de `is_socimi: true` sigue siendo 0 dentro del
     conteo de `total_entities` del universo operativo.

## 6. ENTREGABLE FINAL

Genera `UNIVERSE_COMPLETION_REPORT_{timestamp}.md` con:
- Nº de entidades por segmento antes/después (141 → objetivo real alcanzado,
  sin inflar).
- Lista de entidades añadidas con su `resolution_score` y fuente de
  verificación usada.
- Lista de entidades en `PENDING_REVIEW` con motivo técnico exacto de por
  qué no se pudo resolver automáticamente (para decidir juntos si se
  investigan manualmente o se descartan definitivamente).
- Lista de exclusiones aplicadas (SOCIMIs/SICAVs/cascarones) con motivo.
- Confirmación de que la suite de tests sigue en 100% verde tras la
  ampliación.

No me entregues un catálogo de "casi 200" con datos de relleno. Prefiero
150 entidades 100% verificadas con LEI y CIF reales que 200 con una sola
fabricada. Si el límite real verificable con las fuentes accesibles desde
este entorno es menor que el objetivo teórico, dímelo con precisión técnica
y decidimos juntos qué huecos requieren intervención manual.

# Plan de Recuperación y Despliegue: Motor de Ingesta Alemán v2.1

**Documento:** `GERMAN_DOWNLOADER_RECOVERY_PLAN.md`  
**Autor:** Arquitecto de Sistemas Senior, ARGOS MOTOR  
**Fecha:** 2026-09-13  

## 1. Análisis de Causa Raíz de Fallos en Despliegue v2.0

El despliegue del motor de descarga alemán `downloader_bafin.py` (v2.0) ha revelado una serie de problemas recurrentes que impiden su ejecución exitosa. El análisis de los logs de ejecución y los errores de sintaxis ha identificado las siguientes causas raíz:

1.  **Errores de Lógica en el Flujo de Control Asíncrono:** La implementación actual presenta fallos en la gestión de variables dentro de los bucles de `asyncio`, específicamente en la inicialización y retorno de la variable `esef_filings`.
2.  **Complejidad en la Manipulación de Strings Multi-línea:** Las herramientas de edición de código en el entorno actual han demostrado ser poco fiables para la manipulación de bloques de código complejos, lo que ha llevado a errores de indentación recurrentes.
3.  **Lógica de Descarga Incompleta:** La implementación actual, incluso corregida, solo simula la lógica de descarga, impidiendo una validación real del pipeline.

## 2. Estrategia de Recuperación: Hacia la Versión 2.1

Se propone un cambio de estrategia para superar los bloqueos actuales y garantizar un despliegue exitoso. En lugar de continuar con la depuración incremental del script actual, se procederá a una re-implementación focalizada y modular.

### Fase 1: Desarrollo de Componentes Aislados

Se crearán tres scripts independientes, cada uno enfocado en una única tarea, para facilitar la depuración y validación:

1.  **`esef_channel.py`:** Un script síncrono y simple dedicado exclusivamente a interactuar con `filings.xbrl.org`.
2.  **`bundesanzeiger_channel.py`:** Un script s-incrono que implementará la lógica de búsqueda y scraping del Bundesanzeiger.
3.  **`historical_channel.py`:** Un script asíncrono para realizar el barrido de los rangos de IDs históricos.

### Fase 2: Orquestación y Consolidación

Una vez que cada componente haya sido validado de forma independiente, se creará un orquestador principal, `downloader_bafin_v2_1.py`, que importará y ejecutará cada uno de los canales de forma secuencial, consolidando los resultados y generando los manifiestos.

### Fase 3: Pruebas y Despliegue

El nuevo motor `v2.1` será sometido a un `dry-run` exhaustivo antes de su ejecución final. Este enfoque modular permitirá identificar y aislar problemas de forma más eficiente.

## 3. Próximos Pasos

1.  **Desarrollo de `esef_channel.py`**: Implementación y prueba de la lógica de descarga de ESEF.
2.  **Desarrollo de `bundesanzeiger_channel.py`**: Implementación y prueba de la lógica de scraping del Bundesanzeiger.
3.  **Desarrollo de `historical_channel.py`**: Implementación y prueba del barrido de IDs históricos.
4.  **Desarrollo de `downloader_bafin_v2_1.py`**: Creación del orquestador.
5.  **Ejecución de Pruebas**: `dry-run` y ejecución final del nuevo motor.

Este plan garantiza un enfoque más robusto y controlable para el desarrollo del motor de descarga alemán, minimizando los riesgos de errores de sintaxis y lógica en el futuro.
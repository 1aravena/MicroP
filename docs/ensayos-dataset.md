# Ensayos y preparación del dataset · Grupo C

Estado: software implementado; **piloto, validación física y dataset real pendientes**. No hay modelo entrenado ni métricas de clasificación. Las pruebas utilizan bases temporales y transportes simulados que no se importan desde el arranque de producción.

## Abrir y usar

Desde la raíz de MicroP, con las dependencias existentes:

```powershell
.\.venv\Scripts\python.exe -m backend
```

Abrir `http://127.0.0.1:8001/`. En Raspberry: `.venv/bin/python -m backend --host 0.0.0.0`, y abrir su IP desde la red local de confianza. Página y API comparten origen. Continúa sin cuentas, CORS abierto ni recursos externos.

1. En **Sensores**, conectar cada placa al puerto correcto, revisar el cableado y aplicar su configuración con todos los sensores habilitados. Detener las capturas individuales antes de preparar el ensayo.
2. En **Ensayos y dataset**, crear una sesión: nombre, responsable, conjunto `train` o `test`, procedencia `real` o `simulated`, condiciones y notas. Registrar posiciones medidas, iluminación, estabilización, disposición y versiones del montaje. Conjunto y procedencia quedan fijados desde su creación; no existe una operación para trasladar datos a otro conjunto.
3. Preparar un ensayo con uno de los cuatro escenarios y sus notas. Cada ensayo pertenece a una sola sesión y mantiene un único escenario.
4. Pulsar **Iniciar ensayo**. El backend crea dos capturas nuevas y reserva ambas placas. Los controles individuales quedan bloqueados; el botón global **Detener ensayo activo** permanece disponible en ambas secciones. Los cambios de pines que no se aplicaron en Sensores son borradores del navegador, ajenos a la configuración confirmada del backend.
5. Mantener el escenario durante todas las ventanas. La detención es manual. El tiempo y las ventanas mostradas durante adquisición son provisionales, no observaciones aceptadas. Cerrar o recargar la página no envía STOP ni crea otro ensayo.
6. Detener. Si el escenario se realizó correctamente, marcar la confirmación, escribir notas y pulsar **Confirmar escenario**. Ante dudas o procedimiento distinto, **Excluir ensayo** y repetir con otro ensayo. La decisión queda fijada para conservar trazabilidad; no se edita silenciosamente una etiqueta anterior.
7. Esperar el análisis en segundo plano. Revisar ventanas aceptadas/excluidas, motivos, duración, fragmento final y cobertura. Ante un error técnico, **Reintentar análisis** repite la misma revisión, sin duplicar observaciones.
8. Terminar o cancelar los ensayos preparados y revisar todos los finalizados. **Cerrar sesión** fija su contenido cuando sus análisis estén listos. Una sesión cerrada es consultable y exportable; para continuar, crear otra.
9. Seleccionar las sesiones cerradas deseadas en **Incluir en ZIP** y descargar. La selección se conserva al paginar, hasta cien sesiones por petición; hay que hacer paquetes separados para reales y simuladas. Las sesiones abiertas no se exportan. Se puede entregar un paquete parcial, marcado como tal en el manifiesto.

Las capturas independientes anteriores conservan sus CSV y gráficos. No se incorporan automáticamente al dataset porque no conocemos su escenario ni su revisión. El diagnóstico `index.html` continúa separado y no administra ensayos remotos.

## Procedimiento experimental

| Escenario / ID | Clase | Procedimiento en cada ventana de 10 s |
| --- | --- | --- |
| Zona vacía / `zona_vacia` | `normal` | Mantener libre el área vigilada. |
| Paso breve / `paso_breve` | `normal` | Realizar un paso frente al acceso y retirarse. |
| Acercamientos repetidos / `acercamientos_repetidos` | `anomalo` | Al menos dos ciclos de acercamiento y retirada. |
| Permanencia próxima / `permanencia_proxima` | `anomalo` | Permanecer en la posición próxima durante la mayor parte de la ventana. |

Estas clases describen situaciones preparadas; no determinan intención ni autorizan accesos. El backend mantiene este catálogo, su clase y procedimiento; no deduce etiquetas a partir de sensores.

Antes de recolectar: confirmar modelos, tensiones, cableado y polaridad DO; comprobar sensores por separado; esperar calentamiento y retención observados; medir y marcar posiciones próximas/lejanas seguras; registrar condiciones; ejecutar un piloto. Registrar y resolver cualquier ajuste antes de la recolección definitiva. No se establecen distancias físicas a partir del nombre de un módulo.

Referencia inicial: dos sesiones de entrenamiento y una posterior de prueba independiente, cada una con los cuatro escenarios. Buscar 25 ventanas utilizables por escenario y sesión: 50 por escenario en entrenamiento (200) y 25 por escenario en prueba (100). Son 300 ventanas, **50 minutos netos** más preparación, estabilización y repeticiones. Añadir ensayos de la misma partición si hay exclusiones.

El requisito docente es al menos 100 observaciones **reales** de prueba/validación adicionales al entrenamiento. Las 200 de entrenamiento son una meta del proyecto. Los contadores reales excluyen simulación, ensayos interrumpidos y escenarios sin confirmar. La prueba se reserva para evaluación final. La futura validación usa solo sesiones de entrenamiento, agrupadas por sesión; nunca se reparten al azar ventanas del mismo ensayo entre conjuntos.

## Ventanas y calidad versión 1

Jerarquía: sesión → ensayos → capturas originales Uno/Nano → observaciones derivadas.

Cada ventana es `[inicio, fin)`, dura exactamente diez segundos y no se superpone con otra. El intervalo común comienza en el mayor `startedAt` de las capturas y termina en el menor `endedAt`. Se utiliza la recepción UTC de Raspberry. Los relojes `time_ms` y secuencias originales permanecen en las fuentes; filas de las dos placas no se consideran simultáneas. El fragmento final menor a diez segundos se informa y descarta.

Requisitos por ventana:

- Al menos ocho registros válidos de cada placa.
- Al menos ocho lecturas disponibles de luz y sonido en Uno, PIR y radar en Nano.
- Todos los sensores requeridos habilitados durante todo el ensayo; máscaras coherentes con configuración confirmada.
- Huecos de recepción no superiores a 3,5 s, incluidos inicio→primera y última→fin de ventana.
- Valores digitales 0/1, luz no negativa, distancia disponible dentro de 2..400 cm; control de fechas, secuencias y relojes.
- Ensayo completo y escenario confirmado. Interrupción, rechazo humano, configuración inconsistente, secuencias duplicadas/desordenadas o retroceso de recepción excluyen todo el ensayo. La falta de filas y los huecos se comprueban además por ventana.

El backend serial rechaza mensajes inválidos y duplicados antes de guardarlos, y conserva sus incidencias. El análisis revisa nuevamente las fuentes persistidas. No se crea ninguna fila para recuperar muestras perdidas.

La distancia ausente por falta de eco no se convierte en cero ni excluye por sí sola una ventana. Sus estadísticas son `null` en persistencia y `NA` en CSV si no hay valores disponibles. La disponibilidad será cero. Se conservan valores ausentes de los otros sensores; la ventana solo pasa si cumple sus mínimos.

La cobertura visible corresponde a las ventanas completas y presenta disponibles/filas y ausentes por sensor. Los contadores originales incluyen también los fragmentos descartados. Los motivos se acumulan: una ventana puede tener más de uno, por lo que su suma puede superar el total excluido.

## Diccionario de características versión 1

| Columna de entrada | Definición |
| --- | --- |
| `distance_mean_cm` | Media de distancias válidas, cm. |
| `distance_min_cm` | Mínimo válido, cm. |
| `distance_std_cm` | Desviación estándar poblacional, cm; cero si solo hay un valor. |
| `distance_valid_fraction` | Distancias disponibles / registros válidos de Uno. |
| `pir_high_fraction` | Lecturas PIR iguales a 1 / lecturas PIR disponibles. |
| `pir_rising_edges` | Transiciones observadas 0→1 en lecturas consecutivas dentro de la ventana. |
| `radar_high_fraction` | Lecturas radar iguales a 1 / lecturas radar disponibles. |
| `radar_rising_edges` | Transiciones observadas 0→1 en lecturas consecutivas dentro de la ventana. |
| `lux_mean` | Media de lux disponibles. |
| `sound_high_fraction` | Lecturas DO iguales a 1 / lecturas DO disponibles. No representa dB. |

Las transiciones no se interpolan a través de faltantes, saltos de secuencia, huecos ni fronteras de ventana. A ~1 Hz no se garantiza capturar todos los eventos físicos; la polaridad de sonido debe verificarse en el piloto.

Metadatos exportados: `observation_id`, `session_id`, `trial_id`, `capture_uno_id`, `capture_nano_id`, `scenario`, `window_start`, `window_end`, `label`. La partición, responsable, procedencia, condiciones y configuración se consultan en el manifiesto. **Ninguno de esos metadatos es una variable de entrada del futuro modelo.**

Esta rama no imputa, normaliza, entrena, genera predicciones ni calcula accuracy/F1. En la etapa de ML se elegirá un modelo compatible con faltantes o se ajustará la imputación exclusivamente con entrenamiento, sin consultar prueba.

## Coordinación y recuperación

Un coordinador reserva ambas placas y admite un solo ensayo activo. Usa los mismos trabajadores seriales y ACK del control independiente. La admisión se sincroniza con los controles individuales, sin serializar entre sí operaciones independientes de Uno y Nano fuera de ensayos.

Estados: `prepared → starting → running → stopping → completed`. Cancelación, inicio parcial, placa desconectada, reinicio, datos antiguos o fallo de supervisión llevan a `interrupted`, revisión negativa y exclusión completa. Un inicio parcial intenta detener ambas placas y conserva las capturas que alcanzó a crear. Ante una falla durante ensayo se intenta STOP de la otra placa. Fuera del ensayo, una falla de Nano sigue permitiendo la adquisición independiente de Uno.

Un cierre normal del servicio interrumpe el ensayo activo. Tras un cierre inesperado, las capturas y ensayos activos quedan interrumpidos al abrir SQLite; no se reconectan ni reanudan. El análisis usa un trabajador aparte, consultas de hasta 500 filas y acumuladores fijos por ventana. Al reiniciar se recuperan trabajos `pending/processing` revisados. La clave `trial_id:feature_version:window_index` y la sustitución de derivados hacen el reprocesamiento idempotente; los resúmenes solo cuentan trabajos `ready`.

Los comandos HTTP no se repiten automáticamente tras timeout. Se vuelve a consultar el estado del servidor. Varias pestañas comparten estado; una operación incompatible devuelve 409. No hay un propietario vinculado a la memoria del navegador.

## SQLite y migración

Esquema actual: **2**. Mantiene `captures`, `samples`, `incidents`; añade `collection_sessions`, `trials`, `trial_captures`, `observations` e índices. Una captura solo puede vincularse a un ensayo y cada ensayo tiene como máximo una captura por origen. No se altera el firmware, el protocolo ni las cabeceras de los CSV originales.

Al abrir una base de esquema 1, primero se respalda mediante SQLite backup a `<base>.schema1-<UTC>-<id>.bak` en la misma carpeta. La migración se ejecuta en una transacción; ante fallo revierte sin borrar ni recrear la base. Las bases nuevas se crean en 2 sin respaldo innecesario. Versiones desconocidas se rechazan. Se mantiene el bloqueo de instancia existente.

Detener el backend anterior y reiniciarlo con esta versión. **Una versión antigua que solo admite esquema 1 no abrirá el esquema 2.** Para volver atrás hay que detener el servicio y restaurar deliberadamente el respaldo, conservando primero cualquier dato nuevo. No sobrescribir una base en uso. `data/` y sus respaldos siguen fuera de Git y de los recursos públicos.

## API

Prefijo `/api/v1`; cuerpos estrictos, UUID en rutas, errores 404/409/422/503/504 con detalle. Sesiones y ensayos se paginan por ordinal descendente, `after_id=0` para recientes, `limit` de 1 a 500, respuesta `{items,nextCursor}`. La interfaz muestra veinte por página.

| Método y ruta | Contrato |
| --- | --- |
| `GET /scenarios` | Catálogo, política, versión de características y modo de adquisición. |
| `GET /sessions` | Sesiones recientes. |
| `POST /sessions` | `name`, `responsible`, `partition: train|test`, `source: real|simulated`, `conditions`, `notes` opcional. Devuelve 201. |
| `GET /sessions/{id}` | Detalle y cantidad de ensayos. |
| `POST /sessions/{id}/close` | Solo con todos los ensayos terminales, revisados y analizados; idempotente. |
| `POST /sessions/{id}/trials` | `scenario` del catálogo, `notes` opcional; devuelve 201. |
| `GET /trials?session_id=...` | Lista con capturas y resultados resumidos. |
| `GET /trials/active` | `{trial: objeto|null}`; consulta sin efectos sobre adquisición. |
| `GET /trials/{id}` | Estado, UUID de fuentes, revisión, análisis, calidad y estimación provisional. |
| `POST /trials/{id}/start` | Reserva, valida y crea las dos capturas; reiterar mientras está activo conserva UUID. |
| `POST /trials/{id}/stop` | Detiene; sobre preparado cancela; reiterar terminado no genera captura. |
| `POST /trials/{id}/review` | `confirmed` booleano estricto y `notes`; 202, análisis asíncrono. La misma decisión permite reintentar un análisis con error. |
| `GET /dataset/summary` | Grupos por clase/escenario/procedencia/partición; ventanas y metas reales. |
| `GET /dataset/export.zip?session_id=A&session_id=B` | Una o más sesiones cerradas de la misma procedencia; máximo 100. |

El estado de placas añade `trialId` para informar la reserva. Las rutas anteriores conservan cuerpos, paginación, orden y exportación. Un transporte simulado de pruebas no puede declarar sesiones reales; el servidor normal usa exclusivamente pySerial. Seleccionar `simulated` en una sesión de un servidor serial clasifica su procedencia, no genera datos artificiales.

## Contenido y reproducción del ZIP

- `train.csv`, `test.csv`: solo observaciones elegibles, diez características, clase y metadatos de trazabilidad.
- `quality.csv`: todas las ventanas completas, incluidas las excluidas, sus motivos y calidad por placa. Un ensayo sin ventana completa queda documentado en `manifest.json`.
- `captures/<uuid>.csv`: todas las filas originales de las capturas asociadas, incluso fragmentos finales y ensayos excluidos.
- `manifest.json`: sesiones/particiones/procedencia, responsables/condiciones/notas, ensayos/revisiones, configuración y fechas de capturas, catálogo/procedimientos, política, versiones de esquema/características, conteos/balance, tamaños y SHA-256 de cada archivo de contenido.
- `dictionary.json`, `README.txt`: variables, metadatos, unidades, ausentes y precauciones para ML.

`minimumMet` solo es verdadero con al menos 100 ventanas reales de prueba. `targetMet` requiere datos reales, al menos 50 ventanas de entrenamiento y 25 de prueba por cada escenario. `partial` es lo contrario de `targetMet`; una simulación siempre es parcial a efectos de la meta real. Revisar además que las sesiones de prueba sean posteriores e independientes según el procedimiento: esa independencia física no se puede certificar a partir de contadores.

El manifiesto no contiene un hash de sí mismo. Reexportar las mismas sesiones cerradas reproduce los CSV, diccionario, README y sus hashes; la fecha de generación y los bytes del ZIP pueden cambiar. La construcción usa archivo temporal y lecturas por bloques; el navegador solo descarga el resultado. Cerrar la respuesta libera el temporal.

Para verificar un paquete descargado sin dependencias adicionales:

```powershell
@'
import hashlib, json, zipfile
with zipfile.ZipFile('dataset-grupo-c.zip') as z:
    m = json.loads(z.read('manifest.json'))
    for name, digest in m['sha256'].items():
        assert hashlib.sha256(z.read(name)).hexdigest() == digest
        assert len(z.read(name)) == m['sizesBytes'][name]
    print(m['source'], m['counts'], 'parcial:', m['partial'])
'@ | .\.venv\Scripts\python.exe -
```

Para recalcular, conservar SQLite y la versión del extractor `backend/dataset.py`: `analyze_trial(store, ExperimentStore(store), trial_id)` reproduce derivados desde las fuentes. Esta operación es interna, sobre una copia de trabajo con el servicio detenido; no es una ruta pública que altere sesiones cerradas. Las fuentes CSV y configuración del manifiesto también permiten verificar manualmente intervalos y características. No usar la función sobre la base del servidor mientras otra instancia la utiliza.

## Validación y checklist

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
node --test
```

Las pruebas cubren respaldo/migración/rollback, preservación de datos, coordinación y exclusión mutua, compensación de inicio parcial, fallas/reinicio, confirmación humana, ventanas/límites/NA/huecos, separación por sesión, exportación, hashes/reproducción y regresión de funcionalidades anteriores. El fixture visual `python -m backend.tests.panel_browser_fixture --port 8012` usa una base temporal y presenta explícitamente su simulación.

Verificación local del 27 de octubre de 2026: **95 pruebas Python y 91 JavaScript aprobadas**, incluidas las dos pruebas de firmware con dobles nativos. Python mantiene un aviso de deprecación de Starlette sobre su integración de TestClient con httpx; no afectó los resultados y no se cambiaron dependencias en esta etapa.

En navegador se comprobó conexión/configuración de ambas placas simuladas, creación de sesiones separadas, inicio coordinado, recarga sin nuevo UUID, detención, confirmación, análisis y cierre. Un ZIP descargado desde el enlace del panel contenía dos ventanas de entrenamiento y doce de prueba simuladas, cuatro CSV originales y nueve hashes de contenido verificados; ninguna contó como observación real. La desconexión simulada de Nano interrumpió el ensayo completo, detuvo Uno y conservó las fuentes. Se revisaron escritorio, móvil de 390 px sin desbordamiento horizontal, ambos temas y navegación por teclado; la página USB independiente cargó sin errores de consola. La base de producción se comprobó mediante lectura únicamente: seguía vacía y en esquema 1; se migrará al próximo arranque normal.

- [x] Sesiones, catálogo, ensayos y asociaciones únicas.
- [x] Coordinación, reserva, compensación y recuperación.
- [x] Extractor puro, ventanas, calidad, ausentes y versiones.
- [x] Confirmación humana, cierre y particiones fijas.
- [x] Resúmenes y paquete con fuentes, diccionario, tamaños y hashes.
- [x] Gestión integrada en el panel y consulta después de recargar.
- [ ] Inventario físico y piloto documentados.
- [ ] Dos sesiones reales de entrenamiento con cuatro escenarios.
- [ ] Sesión real independiente posterior de prueba con cuatro escenarios.
- [ ] Revisión de exclusiones y meta 200/100 por escenario.
- [ ] Al menos 100 observaciones reales utilizables de prueba.
- [ ] Paquete real exportado, hashes verificados y limitaciones registradas.

Completar la [pauta física](validacion-hardware.md) con evidencias antes de marcar la recolección como terminada.

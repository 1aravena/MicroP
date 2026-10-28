# Acceso, señalización y fallas

Estado: software implementado; **montaje, dataset real, modelo real evaluado y demostración física pendientes**. El PIN es una credencial de maqueta. No hay cerradura, apertura real, cuentas ni login web.

## Preparar el PIN y abrir

Desde la raíz MicroP, configurar una credencial exclusiva de prueba en terminal:

```powershell
.\.venv\Scripts\python.exe -m backend.credentials
.\.venv\Scripts\python.exe -m backend
```

El primer comando pide dos veces un PIN de seis dígitos con entrada oculta. No tiene valor predeterminado y no se pasa por argumentos. Si el backend estaba ejecutándose, detenerlo normalmente y reiniciarlo después de configurar el PIN. En Raspberry se usa `.venv/bin/python` y el servidor se inicia con `--host 0.0.0.0` para acceso desde el PC de la misma red.

Abrir `http://127.0.0.1:8001/#acceso` en PC o `http://IP_DE_LA_RASPBERRY:8001/#acceso`. GitHub Pages muestra la interfaz y las instrucciones; las operaciones se realizan en el panel servido por Python. La portada estática tiene un acceso **Acceso y ML**.

El hash se guarda en `data/access-pin.json`, fuera de Git y de los directorios públicos. Se utiliza sal aleatoria de 16 bytes, PBKDF2-HMAC-SHA256 de 600.000 iteraciones y comparación en tiempo constante. En Linux se crea con permisos 0600; en Windows hereda además las restricciones del directorio del usuario. El archivo se sustituye de forma atómica. Un archivo ausente o inválido deshabilita acceso, conservando sensores y ensayos.

Se pueden configurar rutas privadas `pin_file` y `model_file` en `backend/config.local.json`, mediante `--config`, sin publicar esos archivos. Predeterminados: `data/access-pin.json` y `data/model.json`. Se cargan al iniciar el servicio; cambiarlos requiere reinicio.

## Recorrido de uso

1. Cargar el firmware Nano actualizado y confirmar físicamente su LED integrado. El Uno conserva su firmware.
2. En **Sensores**, conectar ambas placas, aplicar configuración con los cinco sensores habilitados e iniciar ambas capturas.
3. Esperar lecturas recientes. Distancia sin eco puede ser NA; luz, sonido, PIR y radar deben estar disponibles.
4. Terminar cualquier ensayo de recolección. En **Acceso y ML**, pulsar **Activar acceso y ML**.
5. Presentar el PIN. El formulario lo limpia inmediatamente tras enviar; el backend decide y solicita la señal al Nano.
6. Revisar por separado la autorización y la confirmación del comando. El historial y CSV permiten consultar el intento por UUID.
7. **Desactivar modo** libera la reserva y solicita apagar el LED; las capturas independientes continúan. Detener o desconectar desde Sensores desactiva el modo antes de operar la placa.

Cerrar o recargar el navegador no desactiva el modo, no vuelve a pedir acceso y no crea nuevas capturas. Todas las pestañas reflejan el mismo backend. Los ensayos pueden prepararse mientras existe acceso, pero no iniciarse hasta desactivarlo. Durante acceso se rechazan reconfiguraciones, nuevos START y cambios de sensores; STOP y desconexión del operador siguen disponibles.

## Qué se autoriza

La regla es PIN correcto + modo activo + ambas placas configuradas/capturando + sensores habilitados + datos recientes + almacenamiento disponible + capacidad de señalización del Nano.

No se exige una distancia no calibrada ni presencia previa. Los estados PIR/radar observados se registran por separado como eventos `ACCESS_SENSOR` con origen y muestra. Cada intento conserva las últimas observaciones, IDs de captura, configuración y timestamp UTC del receptor.

ML no participa en esa regla: PIN válido puede permitirse tanto con clasificación normal como anómala. PIN inválido se rechaza en ambos casos. Si únicamente ML falla o no tiene modelo, la regla del PIN continúa funcionando.

Este PIN no protege todas las API administrativas. Se mantiene el servicio en la red local de confianza, sin CORS abierto ni acceso desde Pages a otra API. Las solicitudes de acceso con Origin externo se rechazan. HTTP local no cifra el PIN; no usar credenciales reales ni exponer el servidor a internet.

## LED y protocolo

El Nano usa `LED_BUILTIN`, como salida activa en HIGH. Confirmar modelo, core y polaridad antes de cargar. No se conecta un GPIO de Raspberry ni se comparten los pines de los sensores. LED apagado al arrancar y al recibir STOP.

| Comando | Respuesta / comportamiento |
| --- | --- |
| `SIGNAL_CAPS` | `@OK,SIGNAL_CAPS,1` confirma la extensión. |
| `SIGNAL,<uuid>,ALLOW` | Un segundo encendido. |
| `SIGNAL,<uuid>,DENY` | Tres pulsos de 100 ms, separados por 100 ms. |
| `SIGNAL,<uuid>,FAULT` | Cinco pulsos de 100 ms, separados por 100 ms. |
| `SIGNAL,<uuid>,OFF` | Apagado inmediato. |

ACK de señal: `@OK,SIGNAL,<uuid>,<resultado>`. El backend compara comando, UUID y resultado completos. El firmware admite UUID canónico hexadecimal en minúsculas y rechaza formatos/resultados desconocidos. Conserva el último identificador para no repetir un patrón duplicado; reutilizarlo con otro resultado se rechaza.

La temporización usa `millis()` y no agrega `delay`: el Nano sigue leyendo PIR/radar y atendiendo comandos. Todos los patrones terminan antes de dos segundos, también si se retira USB. Un ACK confirma aceptación del comando, no demuestra que el LED físico haya sido observado.

Se mantienen `INFO` de protocolo 2, ocho columnas de sensores y CSV originales. La prueba de capacidad solo se hace al activar acceso. Un Nano anterior sigue adquiriendo; acceso informa que falta el firmware actualizado. No hay un endpoint público de señalización que omita el PIN. El diagnóstico USB conserva su función de adquisición y no presenta credenciales.

## Bloqueo, incertidumbre y recuperación

- Cinco PIN incorrectos dentro de sesenta segundos bloquean nuevos intentos durante sesenta segundos. El quinto rechazo inicia el bloqueo; el siguiente intento obtiene 429. Un PIN correcto fuera del bloqueo reinicia el contador.
- El límite es compartido por todas las pestañas, no por navegador. Su estado persiste en SQLite. Verificar la hora UTC del equipo antes de la demostración.
- Cada POST usa un UUID. Repetirlo consulta su resultado anterior sin reenviar la señal; para otro intento deliberado se utiliza uno nuevo.
- El intento se registra antes de señalizar. El PIN no se guarda, ni siquiera en forma de hash por intento, y nunca se transmite al Arduino.
- Ante timeout no se reenvía el POST. Se consulta el UUID anterior. Un resultado pendiente sigue bloqueando un envío simultáneo; un resultado sin confirmar se muestra como tal.
- Una pérdida de placa, dato antiguo, cambio de captura o lectura requerida ausente suspende acceso. Si Nano responde, se intenta señalizar la falla; si no, su patrón termina autónomamente. La otra captura independiente puede continuar.
- Un fallo de SQLite impide nuevos permisos. Si el fallo ocurrió después de enviar señal, el intento queda pendiente/no confirmado, con su decisión registrada previamente; no se informa un éxito sin confirmación final persistida.
- Al reiniciar, acceso empieza inactivo y los intentos pendientes quedan no confirmados. No se reconectan placas ni se repiten solicitudes automáticamente.
- Ante falla de ML, se indica ausencia/error/datos insuficientes y continúa la regla independiente del PIN.

## Persistencia y API

SQLite usa esquema 3. La migración desde 1 o 2 respalda la base original como `<base>.schema<version>-<UTC>-<id>.bak` y aplica todos los cambios en una transacción. Si falla, revierte sin recrear la base. Versiones desconocidas se rechazan. Los ejecutables antiguos pueden rechazar el nuevo esquema: conservar respaldo y datos nuevos antes de cualquier restauración deliberada, siempre con el servicio detenido.

Se agregan `access_attempts`, `access_policy` y `ml_predictions`. Las inferencias no se insertan en `observations` ni asignan etiquetas humanas.

Prefijo `/api/v1`:

| Método y ruta | Contrato |
| --- | --- |
| `GET /access/status` | Modo, disponibilidad, PIN configurado, bloqueo y última señal. Nunca devuelve hash o PIN. |
| `POST /access/enable` | Confirma condiciones y capacidad; reserva placas sin crear capturas. |
| `POST /access/disable` | Desactiva el modo sin detener capturas sanas. |
| `POST /access/attempts` | Cuerpo estricto `{requestId: UUID, pin: cadena de seis dígitos}`. |
| `GET /access/attempts` | Historial descendente con `after_id`, `limit` y `{items,nextCursor}`. |
| `GET /access/attempts/{id}` | Consulta el intento y su señal. |
| `GET /access/export.csv` | Exportación completa por bloques, sin perseguir intentos posteriores al corte. |
| `GET /ml/status` | Estado del modelo y resultado actual; separado del modo de acceso. |
| `GET /ml/predictions` | Historial descendente, incluidos motivos de ventanas no clasificadas. |

POST permite 200 con permiso confirmado, 403 con rechazo, 429 con bloqueo y `Retry-After`, 409 con conflicto, 422 con entrada inválida redactada, 503 sin condiciones esenciales y 504 con señal no confirmada. Las respuestas de error de un intento registrado incluyen `attempt` para recuperarlo. GET de un registro existente devuelve su estado aunque ese intento se haya rechazado.

## Comprobación y estado

Pruebas base: `.venv/Scripts/python.exe -m pytest backend/tests -q` (Windows). Las pruebas ML se ejecutan además en el entorno de entrenamiento; ver [guía ML](machine-learning.md). `node --test` incluye dobles nativos de firmware si existe compilador C++.

El fixture `python -m backend.tests.panel_browser_fixture --port 8014` es exclusivo de QA: genera datos y un PIN desechables en una carpeta temporal, usa periféricos simulados y no modifica la base ni el PIN de producción. Las rutas `/test/` solo existen allí.

Verificacion local del 27 de octubre de 2026:

- Entorno ML: **120 pruebas Python aprobadas**, incluidas entrenamiento, evaluacion, equivalencia JSON e inferencia sobre ventanas.
- Entorno base sin scikit-learn: **116 pruebas aprobadas y un archivo de entrenamiento omitido explicitamente**; ese archivo se ejecuto completo en el entorno ML.
- **97 pruebas JavaScript aprobadas**, incluidas las dos compilaciones con dobles nativos de Arduino.
- Se conserva un aviso de deprecacion de Starlette/TestClient sobre httpx; no afecto resultados.
- En navegador: permiso/rechazo con fixture desechable, PIN limpiado al enviar, recarga sin nuevos START, suspension por perdida de Nano, continuidad de Uno y reactivacion explicita tras reconectar.
- Ventanas sin modelo registradas sin etiqueta; el modelo entrenado con fixtures tambien se comprobo integrado con el monitor para dos patrones sinteticos, sin cambiar etiquetas del dataset.
- Escritorio, movil de 390 px sin desbordamiento, ambos temas y navegacion por teclado comprobados. La version estatica desactivo el PIN y registro **cero consultas a API**.

Estos resultados no acreditan hardware ni un modelo real. La base habitual se inspecciono en modo de solo lectura: continua sin muestras y en esquema 2; migrara con respaldo al proximo arranque de esta version. No se configuro un PIN de produccion ni se publico un modelo simulado.

- [x] Hash privado, autorización, bloqueo y recuperación.
- [x] Señalización Nano y compatibilidad de adquisición.
- [x] API y sección Acceso y ML.
- [x] Herramientas ML e inferencia independiente.
- [ ] Confirmar LED/modelo/core y funcionamiento físico de los patrones.
- [ ] Recolectar el dataset real, entrenar y evaluar sin fuga entre conjuntos.
- [ ] Comprobar al menos 100 observaciones reales de prueba.
- [ ] Ejecutar y documentar demostración física con falla y recuperación.

La rama no convierte el prototipo en un sistema autónomo de seguridad física.

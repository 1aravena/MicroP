# Backend Raspberry · Grupo C

## Que hace esta etapa

El backend es un programa Python que controla Uno y Nano por USB y guarda automaticamente sus mediciones e incidencias en SQLite. No necesita un navegador abierto para adquirir datos. Su API permite iniciar/detener, configurar, consultar y exportar CSV.

La pagina existente conserva su conexion USB directa al equipo donde se abre. El panel remoto de `feat/panel-web`, disponible en `/`, consulta esta API; el diagnostico USB mantiene su entrada independiente. Ver la [guia del panel](panel-web.md). Raspberry no necesita Node.js, interfaz grafica, GPIO, un servidor de base de datos adicional ni ML para ejecutar este backend.

Objetivo de despliegue confirmado: **Raspberry Pi Zero 2 W, 512 MB, Raspberry Pi OS Lite de 64 bits**. La instalacion y los ensayos fisicos en ese equipo siguen pendientes. Las pruebas actuales son de software, con perifericos simulados.

## Preparar la Raspberry

Trabajar desde la raiz del repositorio, donde estan las carpetas `backend`, `arduino` y `docs`.

1. Confirmar sistema y entorno sin modificar el montaje:

```sh
cat /proc/device-tree/model
getconf LONG_BIT
python3 --version
python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
hostname -I
```

Se requiere Python 3.11 o posterior y el modulo sqlite3. Registrar estas versiones, el espacio libre y la configuracion del reloj del sistema. La fecha/hora que se guarda es UTC del equipo receptor: verificar que la hora sea correcta antes de realizar ensayos.

2. Confirmar adaptador OTG, hub USB para las dos placas, cables de datos y alimentacion adecuada. La Zero 2 W tiene un puerto de datos USB OTG; su otro micro USB es de alimentacion. Cerrar cualquier Monitor Serial o pagina que este usando esos mismos puertos.
3. Identificar los modelos Arduino y cargar los firmwares nuevos de protocolo 2 segun la [pauta fisica](validacion-hardware.md). El backend no cambia el cableado ni carga sketches automaticamente.
4. Instalar soporte de entorno virtual si falta:

```sh
sudo apt install python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Las versiones, incluidas dependencias transitivas, estan fijadas. Se utiliza Uvicorn basico, sin sus extras. Se comprobo mediante descarga la disponibilidad de ruedas para todas las dependencias de ejecucion en Linux ARM64 con Python 3.11, incluido `pydantic-core`. La instalacion y el funcionamiento en la Raspberry real siguen pendientes; esa comprobacion no mide el uso de RAM ni reemplaza el ensayo fisico.

5. Comprobar permisos para el usuario que ejecutara el programa:

```sh
groups
.venv/bin/python -m serial.tools.list_ports -v
```

Si los dispositivos pertenecen al grupo `dialout` y el usuario no esta incluido, agregarlo y volver a iniciar sesion:

```sh
sudo usermod -a -G dialout "$USER"
```

Ejecutar el backend con el usuario habitual, no como root. Los puertos pueden ser `/dev/ttyACM*`, `/dev/ttyUSB*` o enlaces disponibles en `/dev/serial/by-id/`; **no se supone una asignacion fija Uno/Nano**. El rol se verifica con INFO despues de seleccionar un puerto.

## Arranque manual

Solo en la Raspberry:

```sh
.venv/bin/python -m backend
```

Para permitir consultas desde el PC en la misma red local:

```sh
.venv/bin/python -m backend --host 0.0.0.0
```

Desde Windows, para desarrollar o comprobar el mismo programa:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m backend
```

El valor predeterminado es `127.0.0.1:8001`. El puerto 8000 queda disponible para la pagina USB existente. Se pueden indicar `--port`, `--database` y `--config backend/config.example.json`. Las rutas relativas de SQLite se interpretan desde el directorio de ejecucion, por eso hay que iniciar desde la raiz del repositorio.

La configuracion de ejemplo corresponde al servidor, no al cableado. Puede copiarse a `backend/config.local.json` para ajustes propios. Por defecto no se conectan placas ni comienzan capturas. Ejecutar una sola instancia, sin `--reload` ni varios workers. Un bloqueo del archivo SQLite impide que otra instancia recupere o altere capturas de un servidor que sigue activo.

Mantener abierta la terminal de arranque. **Ctrl+C** solicita cierre normal: intenta STOP en ambas placas, cierra las capturas y libera SQLite/USB. El inicio automatico al encender la Raspberry no forma parte de esta entrega. La API esta destinada a la red local del montaje; no incluye autenticacion de usuarios ni el control de autorizacion del acceso fisico.

## Comprobacion desde el PC

Si el backend corre localmente, usar `http://127.0.0.1:8001`. Si corre en Raspberry, reemplazar esa direccion por su IP real. No usar `127.0.0.1` del PC para buscar un servicio instalado en otro equipo.

Ejemplo PowerShell para consultar:

```powershell
$api = 'http://IP_DE_LA_RASPBERRY:8001/api/v1'
Invoke-RestMethod "$api/health"
Invoke-RestMethod "$api/ports"
Invoke-RestMethod "$api/boards"
```

La IP es un marcador que debe reemplazarse. `/health` puede estar correcto aunque no haya placas conectadas: comprueba el servicio y el almacenamiento, no certifica el montaje.

### Controlar Uno

Reemplazar el puerto por uno que aparezca en `/ports`:

```powershell
$conexion = @{ port = '/dev/ttyACM0' } | ConvertTo-Json
Invoke-RestMethod "$api/boards/UNO/connect" -Method Post -ContentType 'application/json' -Body $conexion
```

Preparar la configuracion **segun el cableado confirmado**. Este ejemplo conserva los pines sugeridos anteriores, no conexiones verificadas:

```powershell
$config = @{
  origin = 'UNO'
  hcTrigger = 4
  hcEcho = 5
  pirPin = 6
  radarPin = 7
  soundPin = 8
  enabled = @{ hc = $true; pir = $false; radar = $false; lux = $true; sound = $true }
} | ConvertTo-Json -Depth 3
Invoke-RestMethod "$api/boards/UNO/config" -Method Put -ContentType 'application/json' -Body $config
Invoke-RestMethod "$api/boards/UNO/start" -Method Post
Invoke-RestMethod "$api/boards"
Invoke-RestMethod "$api/samples?origin=UNO&limit=5"
Invoke-RestMethod "$api/boards/UNO/stop" -Method Post
```

Para Nano, conectar su puerto al rol NANO y enviar `origin='NANO'`, con solo `pir` y `radar` activados. Todos los campos de configuracion se incluyen tambien en Nano; las funciones ajenas al rol quedan desactivadas. Un mismo numero de pin es independiente entre placas.

Activar/desactivar un sensor sin cambiar pines:

```powershell
Invoke-RestMethod "$api/boards/UNO/sensors/sound" -Method Put -ContentType 'application/json' -Body '{"enabled":false}'
```

Cada START confirmado crea un UUID distinto. Cerrar el navegador o dejar de consultar la API no detiene la captura; usar STOP de cada placa. Un nuevo START tras STOP mantiene las capturas anteriores en disco. No hay limite automatico de tiempo o muestras.

## Contrato HTTP

Base: `/api/v1`. El esquema generado se consulta en `/openapi.json`; no se incluye una pantalla Swagger dependiente de CDN. El panel de control se sirve en `/`, con recursos locales.

| Metodo | Ruta relativa | Funcion |
| --- | --- | --- |
| GET | `/health` | Servicio/SQLite; 503 si el almacenamiento tiene un fallo registrado |
| GET | `/ports` | Puertos disponibles, descripcion y metadatos USB si existen |
| GET | `/boards` | Dos estados: conexion, configuracion, ocupado, captura, contador y ultima muestra |
| POST | `/boards/{origin}/connect` | Cuerpo `{"port":"..."}`; INFO, identidad y STOP |
| POST | `/boards/{origin}/disconnect` | STOP y liberacion del puerto |
| PUT | `/boards/{origin}/config` | Objeto de configuracion compatible con JavaScript |
| POST | `/boards/{origin}/start` | START y creacion persistente de captura |
| POST | `/boards/{origin}/stop` | STOP y cierre de captura |
| PUT | `/boards/{origin}/sensors/{sensor}` | Cuerpo `{"enabled":true}`; ACK exacto de ENABLE |
| GET | `/captures` | Capturas paginadas y su configuracion inicial |
| GET | `/captures/{id}` | Metadatos de una captura |
| GET | `/samples` | Mediciones paginadas, valores ausentes como null |
| GET | `/incidents` | Incidencias paginadas |
| GET | `/captures/{id}/export.csv` | CSV compatible de una captura |
| GET | `/incidents/export.csv` | CSV de incidencias |

Origen: UNO/NANO. Sensor: hc/pir/radar/lux/sound. Las consultas aceptan `origin`, `after_id` y `limit` (100 por defecto, entre 1 y 500). Mediciones e incidencias tambien admiten `capture_id`. Las consultas admiten `order=asc|desc` (asc por defecto). En orden descendente, `after_id=0` comienza por los registros mas recientes y un cursor no cero busca IDs menores. Las paginas devuelven `items` y `nextCursor`; para continuar enviar ese cursor como `after_id`. En capturas el cursor es un ordinal interno, distinto del UUID.

El estado de placa incluye `phase`, `connected`, `configured`, `busy`, `port`, `config`, `captureId`, `sampleCount`, `latestSample`, `lastReceivedAt`, `lastError`, `ageMs` y `stale`. Ausencia de muestras por mas de 3,5 segundos durante captura se marca stale, incluso antes de la primera muestra; no se inventan lecturas. El backend es la autoridad del estado: el panel consulta estos datos, no crear una segunda captura local.

Errores: 422 para solicitudes/configuraciones invalidas o identidad incompatible; 409 para estado incompatible o puerto asignado; 404 para captura inexistente; 504 para timeout de comando; 503 para transporte o almacenamiento no disponible. Una operacion en curso rechaza otro comando simultaneo de esa placa sin bloquear la otra.

## SQLite y exportacion

Base predeterminada: `data/microp.sqlite3`, esquema 1. Tambien aparece un archivo `.lock`; es normal que permanezca tras cerrar. El bloqueo real lo administra el SO y se libera al terminar el proceso. No borrarlo para intentar ejecutar dos instancias sobre la misma base.

Tablas: capturas, mediciones e incidencias. Las filas preservan mensaje original, mascara de sensores vigente, tiempo de Arduino y fecha UTC de recepcion. Solo se incrementa el contador despues de confirmar la transaccion. El historial se consulta por bloques y no se acumula en RAM.

Cabecera de mediciones:

```text
fecha_hora_recepcion,captura_id,origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado
```

Cabecera de incidencias: `fecha_hora,origen,tipo,descripcion`. NA conserva el significado del protocolo; en JSON se representa como null. Nunca se completan datos con lecturas de la otra placa. Las descargas toman un corte al solicitarlas y no persiguen indefinidamente las muestras que siguen llegando.

Para descargar desde PowerShell:

```powershell
Invoke-RestMethod "$api/captures"
# Sustituir ID_CAPTURA por el UUID obtenido:
Invoke-WebRequest "$api/captures/ID_CAPTURA/export.csv" -OutFile 'mediciones.csv'
Invoke-WebRequest "$api/incidents/export.csv" -OutFile 'incidencias.csv'
```

## Fallas y recuperacion

- Desconexion de una placa: cierra su captura como interrumpida, conserva datos y deja la otra funcionando.
- Reinicio del Arduino: invalida configuracion; requiere aplicarla e iniciar una captura nueva.
- Timeout de control: no se afirma que el estado fisico sea conocido. Se intenta STOP y se requiere verificar/configurar antes de continuar.
- Error de lectura: NA y una incidencia, conservando las otras mediciones validas.
- Fallo al guardar: intenta STOP, libera el puerto y marca error de almacenamiento; no incrementa datos que no se guardaron. Corregir el problema y reiniciar antes de considerar el servicio sano.
- Cierre inesperado del proceso: las capturas inconclusas pasan a `interrupted` al reabrir la base. No hay reconexion ni reanudacion automatica.
- Base desconocida o version no compatible: se rechaza, no se borra para reemplazarla.

Una captura manualmente detenida o finalizada durante cierre normal queda `stopped`; una falla o reinicio queda `interrupted`. STOP durante el cierre del servicio es un intento de apagado, no una garantia de ACK si el enlace ya fallo.

## Pruebas de software

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm test
```

En Raspberry/Linux, utilizar `.venv/bin/python` en lugar del ejecutable de Windows. Node solo se necesita donde se ejecutan las pruebas JavaScript, no para operar el backend.

Los casos JSON compartidos en `tests/fixtures/protocol-v2.json` se ejecutan en JavaScript y Python. Cubren el contrato de comunicacion existente. El esquema de solicitudes HTTP agrega validacion estricta de tipos y campos, y solo serializa configuraciones completas compatibles con firmware.

Las pruebas Python cubren SQLite persistente, exclusividad de instancia/puerto, recuperacion, duplicados, NA, fragmentacion, errores USB, ACK intercalados, timeouts, captura sin peticiones HTTP, paginacion y exportacion. Los fakes viven exclusivamente en pruebas; no hay un modo de datos simulados habilitado por defecto en el servidor.

## Cierre de la rama

- [x] Paquete Python, dependencias y configuracion.
- [x] Protocolo equivalente con casos compartidos.
- [x] SQLite con recuperacion y exportacion por bloques.
- [x] Trabajador USB independiente para cada placa.
- [x] API y cierre de recursos.
- [x] Pruebas locales de software.
- [x] Backend incorporado en main y publicado por el usuario. El panel tiene su propia rama de trabajo.
- [ ] Instalacion y comprobacion en la Zero 2 W real.
- [ ] Confirmar modelos/cableado y firmwares en ambos Arduino.
- [ ] Captura real de 15 minutos, consulta/exportacion simultanea y registro de memoria.
- [ ] Desconexion aislada, reinicio del backend, conservacion del historial y captura nueva.
- [ ] Adjuntar CSV y resultados observados; completar la pauta fisica.

La validacion fisica continua pendiente. Los ensayos simulados no son datos reales del prototipo ni observaciones de validacion ML.

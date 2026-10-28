# Deteccion y seguridad de acceso · Grupo C · Solemne 2

Herramienta local para comprobar sensores conectados a **dos Arduino independientes**, configurar sus pines, consultar graficos y exportar mediciones e incidencias. Incluye el diagnostico USB desarrollado en `feat/arduino-uno-nano` y el backend de `feat/raspberry-backend`.

La pagina de diagnostico conecta los Arduino por USB al **PC donde esta abierto el navegador**. El backend Python recibe las placas y guarda en SQLite. El panel conecta con esa API, recupera capturas y permite organizar ensayos y exportar ventanas etiquetadas. Autorizacion, entrenamiento ML y recoleccion real siguen pendientes.

## Backend Raspberry

La Zero 2 W ejecuta Python, pySerial, FastAPI y SQLite, con arranque manual en el puerto 8001. Controla cada placa por API, conserva capturas e incidencias tras reiniciar y exporta CSV. El panel remoto se sirve en la entrada del backend; la pagina USB permanece independiente.

Ver la [guia de instalacion, API, pruebas y validacion pendiente](docs/raspberry-backend.md). Punto de entrada: `python -m backend`, desde la raiz del repositorio y usando su entorno virtual. No conecta ni inicia capturas automaticamente. La instalacion en la Raspberry y las comprobaciones con hardware real permanecen pendientes.

## Panel web Raspberry

Iniciar el backend y abrir `http://127.0.0.1:8001/` para comprobarlo en el PC. En Raspberry usar `.venv/bin/python -m backend --host 0.0.0.0` y abrir `http://IP_DE_LA_RASPBERRY:8001/` desde el PC de la misma red. La pagina y la API se sirven juntas, sin otro servidor de frontend.

Incluye seleccion de puertos, controles independientes, configuracion, lecturas y graficos de hasta 300 filas recientes por placa, capturas paginadas y descarga completa de CSV. Cerrar el navegador no detiene ni duplica capturas. No incluye login: se utiliza en la red local de confianza.

Ver la [guia del panel, contrato de consultas y validacion](docs/panel-web.md). `index.html` conserva el diagnostico USB directo mediante localhost del PC o HTTPS, con su funcionamiento anterior. Las pruebas de software y las pruebas fisicas mantienen estados separados.

## Ensayos y dataset

La seccion **Ensayos y dataset** permite crear sesiones de entrenamiento o prueba, coordinar ambas placas, confirmar humanamente uno de cuatro escenarios y obtener ventanas de diez segundos con diez caracteristicas y validacion de calidad. Las sesiones cerradas se exportan con CSV, fuentes, exclusiones, diccionario, configuraciones, versiones y hashes. Las metas son 200 observaciones reales de entrenamiento y 100 de prueba; los datos simulados no cuentan.

Ver la [guia de uso, API, migracion y procedimiento de recoleccion](docs/ensayos-dataset.md). SQLite pasa de esquema 1 a 2 con respaldo automatico previo y migracion transaccional. Reiniciar el backend para usar esta version. El piloto fisico y el dataset real aun no se han recolectado.

## Placas y montaje

| Rol | Sensores | Sketch nuevo | Dependencias |
| --- | --- | --- | --- |
| UNO | HC-SR04, BH1750 y salida digital del modulo de sonido | `arduino/uno/uno.ino` | Core de placa, Wire, BH1750 de Christopher Laws |
| NANO | HC-SR501 y RCWL-0516 | `arduino/nano/nano.ino` | Core de placa |

Modelos exactos, pinout conectado, tensiones de los modulos y polaridad de sonido **pendientes de confirmar con quien tiene los equipos**. El repositorio anterior utiliza un LM393 digital; eso no confirma el modulo fisico actual. El rol que informa el firmware tampoco identifica el microcontrolador real.

La pagina propone Uno: Trigger D4, Echo D5, sonido DO D8; Nano: PIR D6 y radar D7. **Son sugerencias editables, no conexiones verificadas.** BH1750 utiliza SDA/SCL del bus I2C de la placa real; los pines A4/A5 del Uno clasico no se presentan como universales. Completar la [pauta de inventario y pruebas fisicas](docs/validacion-hardware.md) antes de declarar el montaje validado.

## Estructura y decisiones

- `arduino/uno/` y `arduino/nano/`: dos sketches especificos; no inicializan sensores del otro rol. No requieren una biblioteca propia del proyecto.
- `js/protocol.js`: contrato de mensajes, configuracion, validacion y CSV.
- `js/serial.js`: una conexion Web Serial por placa, con aislamiento de comandos y errores.
- `js/board.js`: estado y capturas por placa; no depende del DOM y recibe el transporte por inyeccion.
- `js/app.js`: controles, lecturas y exportaciones USB.
- `js/panel.js`, `js/remote-panel.js` y `js/api-client.js`: vista y control remoto mediante la API.
- `js/sensor-ui.js`: tarjetas y tema compartidos.
- `js/experiments.js` y `js/experiments-view.js`: sesiones, ensayos, revision humana y exportacion en el panel.
- `backend/experiments.py`, `experiment_store.py`, `dataset.py`, `migrations.py`: coordinacion, persistencia, caracteristicas y migracion SQLite.
- `panel.html`: entrada remota servida por el backend, sin Web Serial.
- `js/charts.js`: graficos separados por origen; tiempo relativo en USB y fecha/hora de recepcion en el panel Raspberry.
- `tests/`: pruebas automatizadas y perifericos simulados exclusivos de prueba.
- `backend/`: protocolo Python, transporte serial, trabajadores independientes, SQLite y API.
- `requirements.txt` y `requirements-dev.txt`: dependencias fijadas del backend y sus pruebas.
- `docs/`: especificacion de protocolo y pauta fisica pendiente.

El firmware integrado anterior y los cinco programas individuales se conservan en `arduino/integrado/` y `arduino/individuales/` como referencia. **La pagina nueva requiere los firmwares nuevos con protocolo 2**; ya no controla el montaje anterior de cinco sensores en un solo Uno. `NewPing` sigue siendo dependencia de la prueba individual antigua del HC-SR04, no de los firmwares nuevos.

## Preparar los equipos y abrir la pagina

1. Confirmar el modelo exacto de cada placa, alimentacion, niveles logicos y cableado. No manipular conexiones energizadas de forma insegura.
2. En Arduino IDE, instalar el paquete de cada placa y `BH1750` de Christopher Laws desde el gestor de bibliotecas. Wire forma parte del core compatible.
3. Compilar y cargar `arduino/uno/uno.ino` en la placa que tiene distancia, luz y sonido; cargar `arduino/nano/nano.ino` en la que tiene PIR y radar. Seleccionar los modelos y puertos reales. Registrar consumo de memoria y versiones.
4. Cerrar los Monitores Serial y otras aplicaciones que ocupen los puertos.
5. Abrir una terminal en la raiz de este repositorio y ejecutar:

```powershell
python -m http.server 8000 --bind 127.0.0.1
```

6. Abrir `http://127.0.0.1:8000` en Chrome de escritorio. No abrir el HTML directamente. En sistemas que utilizan el comando `python3`, reemplazar `python` por `python3`.

La pagina tambien puede servirse por HTTPS, por ejemplo con GitHub Pages. En ese caso sigue leyendo los Arduino conectados al equipo de quien la abre: **no accede a los USB de otro computador ni envia las mediciones a GitHub**. Web Serial requiere un contexto seguro y permiso del usuario para cada puerto.

## Procedimiento de uso

1. Pulsar **Conectar UNO**, seleccionar su puerto y esperar la identificacion. Repetir con NANO si se probaran ambos. Se puede utilizar una sola placa.
2. Revisar los pines en las tarjetas de sus sensores y seleccionar cuales estaran activos. Los sensores solo pueden pertenecer a su rol. Un numero de pin puede repetirse en placas distintas.
3. Pulsar **Aplicar configuracion** de cada placa y comprobar la confirmacion. Si falta el BH1750 y esta activo, la configuracion se rechaza; revisar el cableado o desactivarlo explicitamente para una prueba parcial.
4. Pulsar **Iniciar captura** en cada placa que se quiera probar. Cada START confirmado crea una captura identificable, secuencia nueva y reloj relativo nuevo.
5. Observar lecturas y graficos. Los pines quedan bloqueados durante la captura; los interruptores permiten activar/desactivar sensores con ACK confirmado.
6. Pulsar **Detener** para cambiar pines y volver a configurar. Las capturas anteriores se conservan para exportacion. Cada grafico muestra solo la captura actual de la placa que le corresponde.
7. Descargar **mediciones CSV** e **incidencias CSV** antes de recargar o cerrar la pestaña. El registro visible muestra las ultimas 15 incidencias; su descarga incluye todas.
8. Ante desconexion, reinicio o comando sin respuesta, revisar el estado, reconectar si corresponde y aplicar configuracion nuevamente. La otra placa continua de forma independiente.

Se marca ausencia de datos recientes despues de 3,5 segundos sin muestras durante una captura, incluso si todavia no llego la primera. Las lecturas antiguas permanecen en el historial, pero no se muestran como lectura actual de una placa desconectada o detenida.

## Que representan los datos

La adquisicion es instantanea, aproximadamente una muestra por segundo y por placa, sin generar filas artificiales para recuperar intervalos perdidos.

- Distancia: cm entre 2 y 400; sin eco valido es NA, nunca cero centimetros.
- Luz: lux segun BH1750; un error no elimina el resto de la fila del Uno.
- PIR/radar: estados digitales de los modulos; respetar calentamiento, retencion y ajustes fisicos.
- Sonido: nivel DO bruto 0/1. Verificar su polaridad. No representa dB, volumen ni cantidad total de eventos. A 1 Hz pueden perderse pulsos breves.
- NA: sensor ajeno al rol, desactivado o lectura invalida. La pagina distingue esos estados mediante el origen y la configuracion confirmada. Las incidencias registran lecturas faltantes y errores.

No se inventan datos si falta una placa ni se completa una fila con valores anteriores de otra. Las pruebas automatizadas usan mensajes ilustrativos y **no alimentan la pagina de produccion**. Los contadores indican filas recibidas; no certifican observaciones de prueba ML ni un dataset etiquetado.

## Protocolo y archivos CSV

Los firmwares usan 115200 baudios. El navegador identifica version/rol con INFO, confirma STOP y solicita CONFIG antes de START. [Contrato completo, comandos, ejemplos y recuperacion](docs/protocolo-v2.md).

Mensaje emitido por la placa:

```text
origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado
```

Cabecera del CSV descargado:

```text
fecha_hora_recepcion,captura_id,origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado
```

`fecha_hora_recepcion` es UTC del PC receptor; `captura_id` identifica cada START confirmado. `tiempo_ms` mantiene el reloj original de la placa. Los graficos usan otro tiempo interno, monotono y comun de recepcion del PC, para no aparentar sincronizacion entre relojes Arduino.

CSV de incidencias: `fecha_hora,origen,tipo,descripcion`. Incluye configuraciones confirmadas, controles, errores, reinicios y saltos de secuencia. **En el diagnostico USB los datos viven en memoria hasta descargarlos**. El backend, por separado, guarda automaticamente en SQLite del equipo donde se ejecuta.

## Pruebas del diagnostico USB

Requiere Node.js 20 o posterior. No hay dependencias npm de ejecucion ni es necesario `npm install`.

```powershell
npm test
```

Las pruebas cubren validacion y parsing, transporte fragmentado, timeout, identificacion, doble asignacion de puerto, ACK de ENABLE, reinicios, capturas sucesivas, errores parciales, exportacion y graficos por origen.

Si se encuentra `g++` (o el compilador indicado en `CXX`), tambien se compilan y ejecutan los dos sketches **en modo nativo con dobles de Arduino, Wire y BH1750** para comprobar comportamiento del parser y adquisicion. Si no esta disponible, esas dos pruebas se omiten explicitamente. Estas pruebas no compilan el core real ni miden flash/RAM de las placas.

La interfaz se comprobo adicionalmente en Chrome de escritorio y vista movil, incluyendo dos puertos simulados, capturas independientes, desactivacion de un sensor, desconexion aislada y descarga. Esa comprobacion usa fixtures, no hardware real.

## Estado del diagnostico USB

- [x] Inventario de lo conocido y tabla de cableado pendiente.
- [x] Protocolo 2 documentado y ejemplos de prueba identificados.
- [x] Dos firmwares y manejo de lecturas parciales.
- [x] Transporte/controladores independientes y pruebas automatizadas.
- [x] Pagina para Uno, Nano o ambas placas; graficos y temas.
- [x] Exportacion de capturas e incidencias con origen y tiempos.
- [ ] Confirmar modelos, cableado y polaridad del sonido con los equipos.
- [ ] Compilar usando los cores de los modelos reales y registrar memoria/versiones.
- [ ] Completar y adjuntar evidencias de la pauta fisica.

La validacion fisica de Uno/Nano permanece pendiente hasta completar esos puntos. El backend y el panel incluyen gestion de ensayos y preparacion del dataset; la recoleccion real, autorizacion y ML siguen pendientes. La pagina USB conserva su funcionamiento independiente.

## Fuentes tecnicas

- [Arduino: estructura de sketches](https://docs.arduino.cc/arduino-cli/sketch-specification/).
- [Chrome: Web Serial](https://developer.chrome.com/docs/capabilities/serial).
- [Biblioteca BH1750 de Christopher Laws](https://github.com/claws/BH1750).
- [Hoja de datos HC-SR04 de ElecFreaks](https://cdn.sparkfun.com/datasheets/Sensors/Proximity/HCSR04.pdf).
- [HC-SR501: documentacion Joy-IT](https://joy-it.net/en/products/SEN-HC-SR501).
- [RCWL-0516: documentacion Arduino](https://store.arduino.cc/products/microwave-motion-radar).

Utilizar estas fuentes como referencia del componente y contrastarlas con el modelo y modulo realmente instalado.

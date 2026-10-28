# Integracion final: Uno R3 maestro, Nano 33 BLE esclavo y Zero 2 W

## Arquitectura y estado

El montaje confirmado es Nano 33 BLE TX -> Uno D2 (recepcion por software),
Nano RX <- Uno D3 (transmision por software), y Uno D0/D1 -> UART GPIO de
Raspberry. Raspberry sirve pagina/API, guarda SQLite y ejecuta el JSON de ML.
El PC abre el panel por una red USB y entrena/evalua offline. Ejecutar Python
en Windows sigue guardando en Windows; el cable USB no traslada el proceso.

Esta rama implementa el transporte compartido, los firmwares y la interfaz.
Los tests con perifericos simulados no son datos del prototipo. No hay dataset
real ni modelo real entrenado. Compilar un core no acredita cableado ni LED.

## Cableado de referencia

Las posiciones de Raspberry son **pines fisicos** del conector de 40 contactos.

| Conexion | Destino |
| --- | --- |
| Nano TX/D1 | Uno D2, adaptando niveles si corresponde |
| Uno D3 | Nano RX/D0, con reduccion de 5 V a un nivel valido de 3,3 V |
| Uno D1/TX | R1 de 1 kOhm -> punto B -> Raspberry GPIO15/RX, pin 10 |
| Punto B | R2 de 1 kOhm -> GND comun |
| Raspberry GPIO14/TX, pin 8 | Uno D0/RX, segun la adaptacion del montaje |
| GND Uno/Nano | GND Raspberry, pin 6 |

Dos resistencias iguales dejan B cerca de 2,5 V para una entrada de 5 V, no
3,3 V. Es un nivel alto valido para RP3A0. Comprobar con multimetro antes de
conectar la entrada de Raspberry. Las resistencias son para datos, nunca para
alimentar placas. Nano 33 BLE y Raspberry no admiten senales de 5 V en GPIO.
El Nano puede recibir 5 V regulados en VIN; no aplicar 5 V a su pin 3V3.
Cada placa conserva su alimentacion adecuada y todas comparten GND.
No unir salidas de reguladores de 3,3 V entre placas. Completar el esquema
fisico y verificar tambien las salidas de PIR y radar conectadas al Nano.

La foto del montaje no tenia cabecera GPIO instalada: usar una tira 2x20
correctamente soldada o un conector compatible, no cables sueltos en agujeros.
Hacer cambios sin alimentacion. Desconectar el enlace D0/D1 del Uno para
cargar su firmware; el puente USB del Uno comparte ese UART.

## Firmware y velocidades

1. Cargar `arduino/uno/uno.ino` como **Arduino Uno R3**, con BH1750 de
   Christopher Laws y el core AVR. `gateway.h` forma parte del mismo sketch.
2. Cargar `arduino/nano/nano.ino` como **Arduino Nano 33 BLE**, core Arduino
   Mbed OS Nano Boards. `slave.h` forma parte del sketch. No elegir Nano AVR.
3. Enlace Raspberry-Uno: **115200, 8N1**.
4. Enlace Uno-Nano: **9600, 8N1**, `SoftwareSerial(2,3)` en Uno y `Serial1`
   en Nano. La menor velocidad interna y las consultas evitan solapar
   recepciones SoftwareSerial con el UART hardware a 115200.

El Nano transmite muestras UART solo ante POLL del maestro, a un maximo de
una nueva muestra por segundo. El backend serializa controles y consultas;
el Uno inicia la transaccion con el esclavo y espera respuesta. No hace
lecturas bloqueantes de sus sensores mientras espera al Nano. Cada placa
mantiene secuencia, reloj, configuracion, captura y origen propios.

El diagnostico USB se conserva: INFO sin envoltura en el Uno utiliza protocolo
2 directo; Nano usa Serial para USB y Serial1 para el maestro. Un cliente USB
no puede modificar una captura UART activa del Nano ni a la inversa.
No conectar simultaneamente un Monitor Serial del Uno al enlace GPIO activo.
D2 y D3 del Uno quedan reservados en modo maestro, incluso en la API.

## Preparar Raspberry Pi OS de 64 bits

Instalar Raspberry Pi OS de **64 bits**, crear usuario y habilitar SSH.
No copiar los entornos Windows `.venv` y `.venv-ml`: crearlos en cada equipo.
Las dependencias se instalan una vez con internet compartido desde el PC por
USB o mediante un repositorio de paquetes preparado para la arquitectura.
El funcionamiento del panel no depende de internet ni recursos de CDN.

### Red por USB hacia Windows

En Zero 2 W el cable de **datos** va al conector marcado USB, cercano a HDMI,
no PWR IN. Ese puerto se usa como dispositivo de red, no como host del Uno.
Para imagenes Raspberry Pi OS Trixie compatibles, habilitar USB Gadget Mode
en Imager, o utilizar el paquete oficial `rpi-usb-gadget` en una instalacion
existente. Verificar primero `cat /etc/os-release`; no aplicar instrucciones
de Trixie a Bookworm sin consultar su procedimiento correspondiente.

```sh
# Solo Raspberry Pi OS Trixie; ejecutar en la Raspberry.
sudo apt update
sudo apt install rpi-usb-gadget
sudo rpi-usb-gadget on
sudo reboot
```

Windows puede requerir el instalador oficial del controlador de red USB.
Habilitar ICS en Windows si Raspberry necesita internet para instalar paquetes;
para usar pagina/API solo se necesita que ambos extremos tengan conectividad IP.
Usar el hostname configurado (por ejemplo `microp.local`) o la IP real:

```sh
hostname -I
ip -4 addr show usb0
```

Abrir en PC `http://HOSTNAME_O_IP_REAL:8001/`. `127.0.0.1` en el navegador del
PC accede al PC, no a Raspberry. Mantener el servicio en esta red de confianza.
No se publica por internet y GitHub Pages sigue siendo informativo.

### UART GPIO

En `sudo raspi-config`, habilitar hardware serial y responder **No** a la
consola de login por serial. Eliminar de la linea unica de
`/boot/firmware/cmdline.txt` cualquier consola que use serial0/ttyAMA0/ttyS0,
conservando los demas argumentos. Respaldar los archivos de arranque antes de
editarlos. Para usar PL011 estable a 115200 en Zero 2 W, en la seccion `[all]`
de `/boot/firmware/config.txt`, verificar:

```ini
enable_uart=1
dtoverlay=disable-bt
```

Esto reserva el UART para GPIO y deshabilita Bluetooth. Si existe el servicio
`hciuart`, deshabilitarlo (`sudo systemctl disable --now hciuart`). Agregar el
usuario del backend a dialout y reiniciar para aplicar permisos/configuracion:

```sh
sudo usermod -a -G dialout "$USER"
sudo reboot
ls -l /dev/serial0
```

### Ejecutar Python en Raspberry

Desde el checkout de MicroP en Raspberry:

```sh
sudo apt install python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.doctor --config backend/config.raspberry.json
.venv/bin/python -m backend.credentials
sh scripts/run-raspberry.sh
```

Doctor es de solo lectura: informa equipo, UART, permisos, consola, ubicacion
de SQLite, registros y disponibilidad del PIN/modelo sin imprimir secretos.
Que falte modelo o PIN genera aviso; no impide recolectar datos.
El servidor arranca sin abrir el UART ni iniciar capturas automaticamente.
`backend/config.raspberry.json` selecciona pasarela, `/dev/serial0`, escucha
HTTP en red y conserva rutas de datos privadas en `data/`.

## Operar el panel y recolectar

1. Abrir el panel servido por Raspberry. Comprobar su hostname y ubicacion de
   datos visibles bajo el estado de servicio. No debe mostrar el PC Windows.
2. Pulsar **Conectar maestro y esclavo**. Solo se abre un UART fisico. Si Nano
   no responde, se informa por separado; el Uno puede continuar funcionando.
3. Aplicar configuracion de cada placa; los pines de sensores siguen siendo
   los efectivamente cableados. Iniciar/detener capturas independientes, o
   usar Ensayos y dataset para la adquisicion coordinada.
4. Crear dos sesiones de entrenamiento y otra posterior de prueba. Mantener
   escenarios, etiquetas humanas y calidad segun `ensayos-dataset.md`.
5. Detener, revisar y cerrar sesiones; exportar su ZIP. La pagina no guarda
   SQLite: lo hace el backend en Raspberry, aun con la pestana cerrada.

## Entrenar en PC y cargar el modelo

Usar los comandos de `machine-learning.md` sobre el ZIP real descargado.
Entrenar con sesiones train; evaluar despues con test reservado. La meta es
200 ventanas train y 100 test; el minimo docente es 100 observaciones reales
adicionales al entrenamiento. No generar ni contar datos sinteticos para ello.
Conservar JSON, metricas, matriz de confusion y predicciones de prueba.

Copiar `model.json` a `data/model.json` del checkout Raspberry (por SCP sobre
la red USB o transferencia equivalente) y reiniciar el backend. Volver a
conectar/configurar/capturar; activar Acceso y ML y esperar una ventana de
10 segundos completa y la muestra posterior. El PIN y ML siguen separados:
la clasificacion no concede acceso. Sin modelo se informa Sin modelo.

## Contrato de pasarela 1

El mensaje original de ocho columnas y los CSV conservan protocolo 2.
La envoltura de transporte agrega rol e identificador de peticion:

```text
PC/Raspberry -> Uno: GATEWAY_INFO
Uno -> Raspberry: @OK,GATEWAY,1,UNO,NANO,9600
Raspberry -> Uno: @TO,NANO,42,INFO
Uno -> Nano: @CALL,42,INFO
Nano -> Uno: @REPLY,42,@OK,INFO,2,NANO
Uno -> Raspberry: @FROM,NANO,42,@OK,INFO,2,NANO
Muestra espontanea del Uno: @FROM,UNO,0,UNO,1,1000,50,NA,NA,120,0
Muestra del Nano ante POLL: @FROM,NANO,0,NANO,1,1000,NA,1,0,NA,NA
```

ID 0 identifica notificaciones/muestras. Los demas IDs son uint32 positivos
generados por el backend. Las respuestas de IDs vencidos no confirman otro
comando. No hay reintentos automaticos de controles. Un timeout del esclavo
se senala despues de 800 ms y afecta a Nano; perdida/reinicio del maestro
invalida ambos canales y requiere reconexion explicita. Las colas son acotadas
y receivedAt se toma al recibir la trama en el UART fisico.

API adicional: POST `/api/v1/gateway/connect` con `{ "port": "/dev/serial0" }`,
POST `/api/v1/gateway/disconnect`. Health agrega transport y runtime. Las
rutas anteriores de placas, capturas, ensayos y ML conservan sus contratos.
El modo USB independiente sigue disponible sin opciones o con `--transport usb`.

## Pauta final con equipos reales

- [ ] Verificar alimentacion, niveles y esquema individual/integrado.
- [ ] Cargar firmwares de los modelos correctos; probar sensor por sensor y LED.
- [ ] Confirmar captura de ambas fuentes por un solo UART y persistencia en Pi.
- [ ] Recargar/cerrar navegador sin duplicar ni detener capturas.
- [ ] Mantener adquisicion 15 minutos, consultando y exportando simultaneamente.
- [ ] Desconectar Nano de forma controlada: Uno continua; ensayo/acceso se suspenden.
- [ ] Interrumpir enlace maestro: ambos canales se invalidan, sin repetir comandos.
- [ ] Reiniciar backend: conservar datos, sin reanudar capturas o acceso automaticamente.
- [ ] Recolectar datos reales, entrenar, evaluar e instalar el JSON real.
- [ ] Demostrar PIN permitido/rechazado, dos patrones ML y falla con recuperacion.
- [ ] Adjuntar CSV, ZIP, modelo, metricas, esquema, video e informe individual/grupal.

## Verificacion de software del 28 de octubre de 2026

- Suite Python completa, incluido entrenamiento en `.venv-ml`: **131 pruebas aprobadas**.
- Suite JavaScript: **102 pruebas aprobadas**, incluidas cuatro compilaciones/ejecuciones nativas de firmware con dobles.
- Compilacion real Uno R3: AVR 1.8.8, BH1750 1.3.0; 13.502 bytes de flash y 1.079 bytes de RAM estatica (52%).
- Compilacion real Nano 33 BLE: Mbed Nano 4.6.0; 89.776 bytes de flash y 44.856 bytes de RAM estatica (17%).
- Arduino CLI portable 1.5.2-rc.1. El compilador ARM antiguo requirio una ruta corta en Windows para evitar su limite de longitud; no fue un cambio al firmware.
- Revision sintactica transversal de 43 archivos Python y 26 JavaScript; enlaces locales de documentacion sin destinos inexistentes.
- Navegador con perifericos simulados: una conexion para ambos roles, configuracion y captura, recarga conservando IDs/historial, PIN permitido con modelo ausente y suspension al perder Nano mientras Uno continua.
- El diagnostico local de solo lectura confirma que la base del PC sigue sin capturas ni mediciones reales. No se genero ni instalo un modelo simulado de produccion.

Estas comprobaciones no incluyen carga a las placas, medicion de niveles,
memoria/latencia reales en Zero 2 W, ni recoleccion del dataset academico.
Las advertencias observadas pertenecen al core Arduino (parametros sin usar/
reloj LF por defecto) y a la deprecacion preexistente Starlette/httpx; no hubo
fallos de compilacion en la verificacion final ni pruebas fallidas.

## Fuentes tecnicas

- [Raspberry Pi: GPIO y niveles](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
- [Raspberry Pi: UART](https://www.raspberrypi.com/documentation/computers/configuration.html#configuring-uarts).
- [Raspberry Pi: red USB oficial](https://www.raspberrypi.com/news/usb-gadget-mode-in-raspberry-pi-os-ssh-over-usb/).
- [Arduino Nano 33 BLE](https://docs.arduino.cc/resources/datasheets/ABX00030-datasheet.pdf).

# Validacion fisica pendiente · Grupo C

Esta pauta debe completarla quien tiene los equipos. Las pruebas automatizadas usan mensajes y perifericos simulados y **no acreditan que este montaje fisico haya sido probado**.

## Inventario antes de cargar

| Dato | Estado / resultado observado |
| --- | --- |
| Modelo exacto Uno y microcontrolador | Pendiente |
| Modelo exacto Nano y microcontrolador | Pendiente |
| Paquete/core de cada placa y version | Pendiente |
| Arduino IDE y version | Pendiente |
| Biblioteca BH1750 y version | Pendiente |
| Modelo del modulo de sonido | Pendiente |
| Nivel DO en reposo / estimulo acustico | Pendiente |
| Alimentacion, niveles logicos y tierra de cada modulo | Pendiente |
| Puertos USB y cables de datos | Pendiente |

## Cableado

No mover cables con el montaje energizado. Cada modulo debe compartir GND con la placa a la que pertenece. Confirmar tensiones segun las placas y modulos reales, especialmente si no son Uno R3/Nano clasico. No conectar estas senales de 5 V directamente a GPIO de Raspberry.

| Placa | Funcion | Sugerencia de la pagina | Conexion real confirmada |
| --- | --- | --- | --- |
| Uno | HC-SR04 Trigger | D4 | Pendiente |
| Uno | HC-SR04 Echo | D5 | Pendiente |
| Uno | Sonido DO | D8 | Pendiente |
| Uno | BH1750 SDA / SCL | Bus I2C del modelo real | Pendiente |
| Nano | PIR OUT | D6 | Pendiente |
| Nano | RCWL OUT | D7 | Pendiente |

## Compilacion y carga

- [ ] Identificar modelos, revisar pines y tensiones antes de cargar.
- [ ] Compilar el sketch `arduino/uno/uno.ino` para el modelo Uno confirmado.
- [ ] Compilar el sketch `arduino/nano/nano.ino` para el modelo Nano confirmado.
- [ ] Registrar paquete/core y consumo de flash/RAM que informa Arduino IDE.
- [ ] Registrar, si corresponde, la opcion de procesador/bootloader usada para el Nano. No asumir que es Old Bootloader.
- [ ] Cargar cada sketch en su placa correspondiente y cerrar Monitor Serial antes de usar el navegador.

## Ensayos de aceptacion

Registrar fecha, integrante, estimulo, resultado observado y archivo CSV en cada ensayo.

| Ensayo | Resultado esperado | Resultado observado / archivo |
| --- | --- | --- |
| Conectar Uno al boton UNO | Identifica protocolo 2 / UNO; pide CONFIG | Pendiente |
| Seleccionar Nano al boton UNO | Rechaza rol; libera puerto; no inicia captura | Pendiente |
| Configurar cada placa segun cableado | Confirma CONFIG; conserva roles independientes | Pendiente |
| Pin repetido entre funciones activas de una placa | Rechaza; no aplica configuracion defectuosa | Pendiente |
| Distancia a dos posiciones medidas con regla | Cambia de manera coherente; anotar error | Pendiente |
| HC-SR04 sin eco valido | NA y error; luz/sonido siguen llegando | Pendiente |
| BH1750 iluminado y sombreado | Cambia lux; registrar condiciones | Pendiente |
| Sonido DO en reposo y con estimulo seguro | Muestra 0/1; anotar polaridad real y pulsos perdidos | Pendiente |
| PIR sin y con movimiento | Cambia 0/1; anotar estabilizacion y retencion | Pendiente |
| RCWL sin y con movimiento | Cambia 0/1; contrastar con PIR | Pendiente |
| Capturar ambas placas | Dos secuencias independientes, cinco graficos por origen | Pendiente |
| Desactivar y activar un sensor | NA mientras desactivado; ACK y mascara correctos | Pendiente |
| Detener y comenzar otra captura | Secuencia reinicia; UUID cambia; historial anterior sigue descargable | Pendiente |
| Reiniciar una placa | Termina captura local de esa placa; exige CONFIG | Pendiente |
| Retirar solo el USB del Nano | Marca desconexion; Uno continua; datos anteriores conservados | Pendiente |
| Reconectar Nano | INFO, STOP, CONFIG y nueva captura | Pendiente |
| Descargar mediciones e incidencias | Fuentes, tiempos y capturas identificables; NA no inventa mediciones | Pendiente |

La falta de hardware o de un resultado observado debe permanecer marcada como pendiente. Esta rama puede quedar comprobada a nivel de software; su validacion fisica termina solo cuando esta pauta tenga evidencias reales.

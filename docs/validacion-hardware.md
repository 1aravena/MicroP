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

## Panel web y Raspberry: validacion fisica pendiente

La interfaz remota ya tiene pruebas de software. Completar estos ensayos con datos reales; las comprobaciones del servidor de QA no los sustituyen.

| Ensayo | Resultado esperado | Resultado observado / archivo |
| --- | --- | --- |
| Abrir el panel desde el PC en la IP de Raspberry | Pagina, API y recursos disponibles sin internet | Pendiente |
| Controlar Uno y Nano desde el panel | Puertos de Raspberry, roles y controles independientes | Pendiente |
| Capturar 15 minutos y consultar/descargar simultaneamente | Registros persistentes; anotar memoria y funcionamiento | Pendiente |
| Cerrar y reabrir el navegador durante captura | Mismo UUID, contador creciente y hasta 300 lecturas recientes | Pendiente |
| Abrir dos pestanas y operar una placa | Estado compartido; conflictos de control informados | Pendiente |
| Retirar solo Nano de forma controlada | Nano interrumpido; Uno continua; historial conservado | Pendiente |
| Reiniciar backend y volver al panel | Capturas inconclusas interrumpidas; requiere conectar/configurar/iniciar | Pendiente |
| Descargar captura de mas de 300 lecturas | CSV completo, aunque el grafico sea una ventana | Pendiente |

Ver el [procedimiento del panel](panel-web.md). Registrar fecha, integrante, versiones, memoria y CSV de cada ensayo.

## Recoleccion de ensayos y dataset real — pendiente

Seguir la [guia de ensayos](ensayos-dataset.md). Los resultados simulados de software no completan estos puntos.

- [ ] Registrar modelos, cableado, polaridad DO, configuracion y versiones reales.
- [ ] Medir posiciones proximas/lejanas y registrar iluminacion y disposicion.
- [ ] Medir estabilizacion/retencion PIR y radar; realizar piloto de los cuatro escenarios.
- [ ] Registrar ajustes del procedimiento antes de la recoleccion definitiva.
- [ ] Sesion entrenamiento A: cuatro escenarios, buscar 25 ventanas utilizables por escenario.
- [ ] Sesion entrenamiento B: cuatro escenarios, buscar otras 25 ventanas por escenario.
- [ ] Sesion posterior de prueba independiente: cuatro escenarios, 25 ventanas por escenario.
- [ ] Confirmar humanamente cada ensayo, revisar exclusiones y repetir dentro del mismo conjunto cuando falten observaciones.
- [ ] Comprobar recarga durante ensayo, detencion coordinada y fallas; conservar fuentes excluidas.
- [ ] Verificar al menos 100 ventanas reales de prueba adicionales al entrenamiento; revisar balance 200/100.
- [ ] Cerrar sesiones, exportar ZIP y verificar hashes y ausencia de sesiones compartidas entre conjuntos.
- [ ] Adjuntar manifiesto, CSV, resultados, condiciones, limitaciones y evidencias reales.

## Acceso, LED y ML — validacion real pendiente

Seguir [acceso y fallas](acceso-y-fallas.md) y [Machine Learning](machine-learning.md). No conectar cerraduras reales ni GPIO de Raspberry. Confirmar el LED integrado, su polaridad y el core de la placa antes de cargar el Nano actualizado.

| Ensayo | Resultado esperado | Resultado observado / evidencia |
| --- | --- | --- |
| Arranque, STOP y perdida USB del Nano | LED apagado o termina autonomamente su patron en menos de dos segundos | Pendiente |
| PIN correcto con ambas capturas sanas | Intento registrado, un segundo de LED y ACK correlacionado | Pendiente |
| PIN incorrecto | Rechazo registrado y tres destellos | Pendiente |
| Cinco errores en 60 s y reinicio | Bloqueo de 60 s conservado, sin repeticion de intentos | Pendiente |
| Recargar/abrir otra pestana durante acceso | Mismo modo y capturas; no se envia otra solicitud | Pendiente |
| Intentar ensayo durante acceso | Conflicto explicado; recoleccion disponible al desactivar modo | Pendiente |
| Perdida de una placa o datos antiguos | Acceso suspendido, fuentes conservadas; la otra captura independiente puede continuar | Pendiente |
| Modelo ausente o error exclusivo de ML | PIN conserva su regla, ML indica indisponibilidad | Pendiente |
| Modelo real sobre dos patrones en vivo | Clasificacion y ventana identificables, limitaciones registradas | Pendiente |
| PIN valido/invalido y ML normal/anomalo | La clase no concede ni cambia el permiso por PIN | Pendiente |
| Captura prolongada con inferencia y descargas | Registrar memoria, latencia, continuidad y archivos | Pendiente |

Adjuntar dataset real, al menos 100 observaciones utilizables de prueba, JSON del modelo, informes de validacion/evaluacion, CSV de intentos, incidencias, esquematicos y video. No completar resultados observados con salidas de los fixtures.

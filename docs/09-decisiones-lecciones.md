# 09 · Decisiones y lecciones

Dos partes: (1) **registro de decisiones de arquitectura** (ADR, formato corto: contexto → decisión → alternativas →
consecuencias) y (2) **catálogo de problemas reales** encontrados, con causa y solución. Fuentes `[ref]` en
[11](11-glosario-referencias.md). ⚠️ = decisión revisable o dato no verificado.

## Parte 1 · Decisiones de arquitectura

### ADR-01 · Un harness de AgentCore con herramientas en el cliente

- **Contexto.** Se pidió «un agente real de AgentCore que automatice flujos funcionales», no una llamada a un modelo.
- **Decisión.** Harness gestionado + 4 **funciones en línea** que ejecuta nuestra Lambda contra DynamoDB.
- **Alternativas.** (a) Llamar a Converse directamente: no es un agente. (b) Agente propio en **AgentCore Runtime**: tú escribes el
  bucle [A8]. (c) Herramientas vía **Gateway/MCP**: más infraestructura y autenticación; el harness las soporta pero la
  documentación marca las funciones en línea como «Custom» (código propio) [A8].
- **Consecuencias.** Cambiar modelo/prompt es configuración. Tenemos que escribir el bucle cliente (`ask`) y validar todo lo que el
  modelo pide. El estado de las herramientas está **bajo nuestro control**.

### ADR-02 · Lambda Function URL en lugar de API Gateway

- **Contexto.** Web + API simples, coste cero sin uso.
- **Decisión.** Una función con Function URL (`AuthType: NONE`) y autenticación **dentro de la app**.
- **Alternativas.** API Gateway HTTP + autorizador JWT de Cognito; CloudFront + WAF delante.
- **Consecuencias.** Un solo recurso y sin coste fijo; pero **sin WAF, sin límite de uso por usuario y sin autorizador gestionado** [L1].
  Las Function URL solo son accesibles por internet pública [L1]. Mitigación disponible: concurrencia reservada. ⚠️ Para uso
  público real convendría CloudFront + WAF.

### ADR-03 · Solo AWS: Cognito con OIDC directo (sin Entra ID ni Google)

- **Contexto.** Primero se planteó Microsoft Entra ID; luego se pidió **«solo AWS para no confundir entornos»**.
- **Decisión.** Cognito (login alojado clásico) + flujo de código con PKCE implementado en `auth.py` con la biblioteca estándar.
- **Alternativas.** Entra ID / Google (federación); Amplify; autorizador JWT de API Gateway (no existe en Function URL).
- **Consecuencias.** Sin cuentas externas. Google sería una adición posterior (requiere crear un cliente OAuth en su consola; no es
  automatizable por CLI) y habría que filtrar también por correo. Se mantiene el control del flujo a costa de ~200 líneas propias de
  seguridad que **hay que mantener y auditar** (de ahí las pruebas hostiles).

### ADR-04 · Sesión en cookie firmada, sin estado

- **Decisión.** `__Host-session` con HMAC-SHA256 y caducidad (8 h); clave en Secrets Manager.
- **Alternativas.** Sesiones en DynamoDB (revocables, +1 lectura por petición); tokens de Cognito en `localStorage` (expuestos a XSS).
- **Consecuencias.** Simple y barato, `HttpOnly`. **No revocable** hasta caducar (⚠️ riesgo en [04](04-autenticacion-seguridad.md#8-riesgos-residuales-y-hoja-de-ruta)).

### ADR-05 · No verificar la firma del `id_token`

- **Decisión.** Validar `iss`, `aud`, `token_use`, `nonce`, `exp`; no la firma.
- **Justificación.** OIDC Core §3.1.3.7 permite sustituir la comprobación de firma por la validación TLS del servidor cuando el token
  llega **directamente del endpoint de tokens** [R4]; además PKCE liga el código al verificador [R2, R3].
- **Condición de validez.** Nunca usar flujo implícito ni aceptar tokens por otro camino. ⚠️ Si cambia, hay que verificar JWKS.

### ADR-06 · Modelo: Nemotron Nano 9B v2 por Bedrock Mantle (`chat_completions`)

- **Contexto.** Claude no se pudo usar (suscripción de Marketplace), Nova estaba sin cuota; el *playground* funcionaba con Mantle.
- **Decisión.** `nvidia.nemotron-nano-9b-v2`, `apiFormat=chat_completions`.
- **Alternativas.** `converse_stream` por `bedrock-runtime` (recomendado por la documentación [A14]): **no respondió en 60 s** en la
  prueba; Claude/Nova: bloqueados por la cuenta.
- **Consecuencias.** Modelo pequeño y no determinista (errores, ruido, razonamiento visible). ⚠️ Etiqueta de ciclo de vida «EOL no
  antes del 18 ago 2026» ya superada [A12]. Cambiar de modelo es solo configuración.

### ADR-07 · `allowedTools` con `@nombre` y sin `shell`

- **Decisión.** Restringir en cada invocación a nuestras 4 funciones.
- **Justificación.** Mínima funcionalidad (OWASP LLM06 [O2]) y ≈ 900 tokens menos por petición [A2]; descubrimos el formato `@nombre`
  probando (no está documentado para funciones en línea).

### ADR-08 · Estado real adjunto + `actorId` (en vez de confiar en la memoria)

- **Contexto.** La memoria semántica contaminó respuestas entre sesiones (ver problema P-07).
- **Decisión.** Adjuntar el estado de DynamoDB a cada pregunta, prohibir en el prompt usar lo «recordado» y aislar por `actorId`.
- **Alternativas no aplicadas.** Quitar `SEMANTIC`, desactivar la memoria (⚠️ puede romper la continuidad entre turnos [A5]).

### ADR-09 · DynamoDB con `Scan` (sin índices)

- **Decisión.** Una tabla con clave `id` y `Scan` paginado con lectura consistente, ordenando en memoria.
- **Alternativa.** GSI por estado/fecha + `Query`. Se descartó por volumen (cientos de incidencias). La documentación avisa de que
  `Scan` empeora al crecer la tabla [D3]. Límite: miles, no millones.

### ADR-10 · Interfaz en un único HTML sin framework

- **Decisión.** HTML+CSS+JS en un archivo embebido en la Lambda.
- **Consecuencias.** Sin *build*, despliegue trivial, 31 KB; pero sin componentes ni tipos, y una CSP completa exige retirar scripts y
  estilos en línea. Todo el DOM se genera con `textContent` (sin XSS por datos).

### ADR-11 · Despliegue manual y rol OIDC de ámbito acotado

- **Decisión.** `deploy` solo con `workflow_dispatch`; rol `github-agent-aws-deploy` con confianza limitada a 2 ramas de un repositorio
  y permisos acotados a `incidencias*`.
- **Alternativas.** Despliegue automático al fusionar (descartado hasta tener todo configurado); rol de administrador (descartado).
- **Consecuencias.** Más seguro; un paso manual. Riesgo residual de escalada dentro del proyecto (ver [04 §7](04-autenticacion-seguridad.md#7-federación-oidc-de-github-con-aws)).

### ADR-12 · Registro propio acotado por lista

- **Decisión.** Cognito con registro propio **filtrado** por `AllowedSignups` (disparador pre-registro); vacío = nadie.
- **Alternativas.** Altas manuales por administrador (fricción); Google (entorno externo).
- **Consecuencias.** Sin intervención por alta, pero atado al límite de **50 correos/día** del envío por defecto [C4].

### ADR-13 · Dobles de prueba: moto + agente simulado

- **Decisión.** Pruebas rápidas con DynamoDB simulado y un `FakeRuntime` que reproduce el protocolo real; validación contra AWS real
  con un script manual (`smoke_live.py`) [T2].
- **Consecuencias.** Pruebas deterministas y gratuitas; **no detectan cambios del contrato de AWS** (⚠️).

### ADR-14 · `requires-python` explícito

- **Decisión.** `requires-python = ">=3.11"` fijado en `pyproject.toml`.
- **Justificación.** Sin él, `uv` toma el Python actual como mínimo al bloquear [P2] (incidente del CI).

### ADR-15 · El harness se gestiona con la API, no con CloudFormation ⚠️

- **Estado.** **Deuda técnica**, no decisión fundada: existe `AWS::BedrockAgentCore::Harness` [A16] y no se usó. Ver [02 §13](02-agentcore-harness.md#13-por-qué-el-harness-no-está-en-cloudformation).

## Parte 2 · Catálogo de problemas encontrados

Cada fila: **síntoma** → **causa** → **solución**. «V» = reproducido/verificado en la cuenta real.

| # | Síntoma | Causa | Solución |
|---|---------|-------|----------|
| P-01 | `AccessDeniedException` con Claude: faltan `aws-marketplace:Subscribe` (V; también con root) | Suscripción de Marketplace del modelo sin completar en la cuenta | Fuera de código: completar la suscripción; mientras, Nemotron por Mantle |
| P-02 | Nova: `ThrottlingException: Too many tokens per day` (V) | Cuota diaria de tokens nula/agotada **en ese endpoint** (cada endpoint tiene cuotas propias [A14]) | Pedir aumento de cuota; Mantle funcionaba |
| P-03 | Creación del harness: «Role validation failed for … trust policy» (V) | La confianza usaba `aws:SourceArn = …:harness/*`; AgentCore valida con otro ARN (el *runtime*) | `aws:SourceArn = …:bedrock-agentcore:<región>:<cuenta>:*` |
| P-04 | `AccessDeniedException … ListEvents` dentro de `InvokeHarness` (V) | Los harness creados por API traen **memoria administrada** y el rol no tenía permisos de memoria | Añadir `CreateEvent/DeleteEvent/GetEvent/ListEvents/RetrieveMemoryRecords` sobre `memory/<nombre>-*` |
| P-05 | `ResponseParserError: HarnessToolResultBlockDelta must have one and only one member set` (V) | El `toolResult` con `{"json":…}` se reenviaba con `text` y `json` a la vez | Enviar el resultado **solo como texto** (como muestra la documentación [A2]) |
| P-06 | El agente describía los pasos en vez de ejecutarlos (V) | `allowedTools` con nombres sueltos bloqueaba las funciones en línea | Formato **`@nombre`** (probado: lo permite y bloquea `shell`) |
| P-07 | El agente afirmó una incidencia que no existía (V) | Memoria **semántica** de largo plazo recuperada en sesiones nuevas [A5] | Estado real adjunto + prompt + `actorId` (ADR-08) |
| P-08 | «Necesito el ID de la nueva incidencia…» (V) | No había herramienta para crear | `crear_incidencia`; el id lo genera el servidor |
| P-09 | El agente llamaba a `shell` (V) | Herramienta integrada permitida por defecto [A2] | `allowedTools` + ignorar llamadas ajenas |
| P-10 | `session_id` de 101–128 caracteres aceptado por la app y rechazado por AWS | La validación local (≤128) no coincidía con el contrato (33–100) [A4] | `^[A-Za-z0-9][A-Za-z0-9_-]{32,99}$` + prueba |
| P-11 | `inputSchema` envuelto en `{"json": …}` | Se copió la forma de Converse | JSON Schema directo [A11] (ambos funcionaban) |
| P-12 | Lista truncada con muchos datos y lecturas posiblemente obsoletas | `Scan` sin paginar y eventual por defecto [D1, D3] | Paginación + `ConsistentRead` |
| P-13 | Callback roto (500) con `state` como `estado-ñ` (V) | `hmac.compare_digest` con `str` solo admite ASCII [P1] | `_same()` compara bytes |
| P-14 | «Salir» cerraba solo la sesión de la app; «volver a entrar» era automático | Quedaba la sesión de Cognito | Pasar por `/logout` de Cognito [C7] |
| P-15 | `/auth/logout` por GET | Operación que cambia estado con GET (OWASP [O3]) | Pasó a **POST** con comprobación de origen |
| P-16 | CI: «Python 3.12.3 no compatible con `>=3.14`» (V) | `requires-python` sin declarar → lock con el Python local [P2] | Declararlo; mover `boto3-stubs` a `dev` (ADR-14) |
| P-17 | `uv.lock` reescrito al ejecutar `uv run` | Sin `--frozen` | `--frozen` siempre |
| P-18 | `Not authorized to perform sts:AssumeRoleWithWebIdentity` (V) | Confianza con el `sub` antiguo; el repo usa el **inmutable** [G1] | `repo:<owner>@<id>/<repo>@<id>:ref:…` |
| P-19 | `setup.sh`: «Unable to load paramfile file:///tmp/…» (V) | `mktemp` de Git Bash crea rutas `/tmp` que el `aws` de Windows no ve | Carpeta temporal **relativa** |
| P-20 | Comandos pegados fallaban (`│`, `9 +`) | Se copiaron caracteres de la interfaz | Scripts en el repo; una sola línea para ejecutar |
| P-21 | Comando colgado | Un `python -` esperaba entrada estándar | No usar `python -` sin heredoc; herramienta de edición |
| P-22 | El panel del agente se salía de la pantalla (campo de escribir oculto) (V, prueba e2e) | `max-height: 100vh` con el panel empezando bajo la cabecera | `calc(100vh − 60px − 32px)` |
| P-23 | Botón flotante tapaba el aviso en móvil (V, prueba e2e) | Desplazamiento fijo (56 px) menor que el alto del aviso (146 px) | Medir el aviso y subir lo justo (`--toast-h`) |
| P-24 | Texto pequeño de la cabecera con contraste 4,27:1 / 3,68:1 | Carbón/hueso sobre terracota | Negro (5,10:1); hueso en «alto contraste» (prueba que mide) |
| P-25 | Conversaciones antiguas condicionaban al agente tras cambios | Historial guardado en el navegador + memoria de sesión | Versión de almacenamiento (`v`) que descarta lo obsoleto |
| P-26 | «User already exists» al registrarse de nuevo | Usuario **sin confirmar** (se salió antes de pegar el código) | Borrar el usuario (`admin-delete-user`) o confirmarlo |
| P-27 | `DescribeTable` mostraba 0 elementos con 7 reales | `ItemCount` se actualiza ~cada 6 h | No usarlo para contar |
| P-28 | `converse_stream` + Nemotron: lectura agotada a los 60 s (V) | **Causa no determinada** | Mantener `chat_completions` (⚠️ sin investigar) |
| P-29 | `curl …//` devolvía 400 | URL con doble barra (la salida de CloudFormation ya termina en `/`) | No añadir otra barra |
| P-30 | Respuestas del agente con fragmentos corruptos («חדא negotiate») | Ruido del modelo pequeño (V en `smoke_live`) | Sin solución en código; motivo para un modelo mayor |

## Lecciones transversales

1. **Probar contra el servicio real pronto.** Los formatos de la API (`@nombre`, texto en `toolResult`, `actorId`, ARN de confianza,
   `sub` inmutable) solo aparecieron al ejecutar contra AWS; los dobles de prueba no los habrían revelado.
2. **Leer la documentación oficial *después* de que algo funcione también paga.** Al contrastarla aparecieron cuatro defectos
   latentes (`session_id` ≤ 100, `Scan` paginado, `compare_digest` ASCII, `Sec-Fetch-Site`/POST) que ninguna prueba cubría.
3. **Todo lo que viene de un modelo es entrada no confiable:** validar, devolver errores que enseñen, limitar vueltas.
4. **No fiarse de la memoria del agente para hechos:** la fuente de verdad se adjunta en cada petición.
5. **Las pruebas de interfaz que miden (contraste, geometría) encuentran lo que el ojo no:** tres defectos reales.
6. **Scripts en el repo en vez de comandos pegados:** reproducibles, revisables e idempotentes.
7. **Distinguir hecho de suposición en la documentación** (⚠️): evita que una hipótesis se convierta en «verdad» del proyecto.

# 11 · Glosario y referencias

## 1. Glosario

### Agentes e IA

| Término | Significado |
|---------|-------------|
| **Agente** | Modelo de lenguaje en un **bucle** que razona, llama a herramientas, observa el resultado y repite hasta responder [S1, R1] |
| **LLM** | Modelo de lenguaje de gran tamaño (aquí, Nemotron Nano 9B v2) |
| **Tool use / function calling** | El modelo emite una petición estructurada (nombre + argumentos JSON); **el software que lo rodea la ejecuta**, no el modelo |
| **Harness (de AgentCore)** | Bucle de agente **gestionado** por AWS (basado en Strands Agents) configurado con modelo, prompt, herramientas, memoria y límites [A1] |
| **AgentCore Runtime** | Alojamiento *serverless* de agentes; cada sesión del harness corre en una **microVM** aislada [A1, A8] |
| **MicroVM** | Máquina virtual ligera (Firecracker) con su propio sistema de archivos y shell, una por sesión [A10] |
| **Función en línea (*inline function*)** | Herramienta cuyo esquema declara el harness pero que **ejecuta el cliente**; el harness se pausa y espera el resultado [A2] |
| **`allowedTools`** | Lista de herramientas que el agente puede usar en una invocación (`@nombre` para funciones en línea) [A2] |
| **Sesión (`runtimeSessionId`)** | Identificador (33–100 caracteres) que agrupa los turnos de una conversación [A4] |
| **`actorId`** | Identifica a la persona/entidad para **aislar su memoria** [A5] |
| **Memoria de corto / largo plazo** | Eventos de una sesión / conocimiento extraído por estrategias (`SEMANTIC`, `SUMMARIZATION`…) y recuperado en sesiones futuras [A5] |
| **Mantle (`bedrock-mantle`)** | Endpoint de Bedrock compatible con APIs de OpenAI y Anthropic [M1] |
| **Converse / Chat Completions** | APIs de inferencia de Bedrock (nativa / compatible con OpenAI) |
| **Token** | Unidad de texto que factura y limita el modelo (entrada y salida) |
| **`<think>…</think>`** | Razonamiento que emite Nemotron antes de su respuesta; se descarta en la app [N1] |
| **Inyección de prompt (LLM01)** | Texto de entrada que altera el comportamiento del modelo [O1] |
| **Agencia excesiva (LLM06)** | Dar al agente más funciones, permisos o autonomía de los necesarios [O2] |
| **Human-in-the-loop** | Aprobación humana antes de acciones de alto impacto |
| **Fuente de verdad** | Dato autoritativo (aquí, DynamoDB), frente a lo que el modelo «recuerda» |

### Identidad y seguridad

| Término | Significado |
|---------|-------------|
| **OAuth 2.0 / OIDC** | Autorización delegada / capa de autenticación sobre ella [R3, R4] |
| **Flujo de código + PKCE** | El navegador recibe un código de un solo uso que el servidor canjea; PKCE lo protege con un secreto aleatorio [R2] |
| **`state` / `nonce`** | Anti-CSRF del flujo / anti-repetición del ID token [R4] |
| **ID token / JWT** | Afirmación firmada de identidad (RFC 7519) |
| **HMAC** | Código de autenticación de mensajes con clave (RFC 2104) [R6] |
| **Cookie `__Host-`** | Prefijo que obliga `Secure`, `Path=/` y sin `Domain` [R5] |
| **`SameSite=Lax`** | La cookie no viaja en subpeticiones entre sitios [R5] |
| **CSRF** | Que otra web haga actuar a tu navegador contra un sitio donde tienes sesión [O3] |
| **Fetch Metadata (`Sec-Fetch-Site`)** | Cabeceras que el navegador añade e indican de dónde viene la petición [O3] |
| **XSS / CSP / HSTS** | Inyección de script / política de contenido / forzar HTTPS [O4] |
| **Falla cerrada (*fail-closed*)** | Ante la duda o falta de configuración, **denegar** |
| **Federación OIDC (GitHub→AWS)** | Credenciales temporales a cambio de un token OIDC, sin claves de larga vida [W2] |
| **Sujeto inmutable** | Formato del claim `sub` de GitHub con ids numéricos [G1] |
| **STRIDE** | Clasificación de amenazas: suplantación, manipulación, repudio, divulgación, denegación de servicio, elevación |
| **Confused deputy** | Un servicio engañado para actuar con permisos ajenos; se mitiga con `aws:SourceAccount`/`SourceArn` |
| **Mínimo privilegio** | Dar solo los permisos imprescindibles |

### AWS

| Término | Significado |
|---------|-------------|
| **ARN** | Identificador único de un recurso de AWS |
| **IAM, rol, política de confianza** | Permisos; identidad asumible; quién puede asumir el rol |
| **STS** | Servicio de credenciales temporales |
| **CloudFormation, pila, *change set*** | IaC; conjunto de recursos; vista previa de cambios |
| **Function URL / *payload format 2.0*** | Endpoint HTTPS de una Lambda / esquema de su evento y respuesta [L2] |
| **Arranque en frío** | Primera invocación de un entorno nuevo (más lenta) |
| **Concurrencia reservada** | Tope de ejecuciones simultáneas; `0` = apagado [L1] |
| **DynamoDB bajo demanda** | Facturación por petición, sin capacidad que dimensionar [D5] |
| **PITR** | Recuperación a un instante (copias continuas) |
| **`Scan` / `Query`** | Leer toda la tabla / leer por clave |
| **Escritura condicional** | `ConditionExpression`: solo escribe si se cumple [D1] |
| **Lectura consistente** | `ConsistentRead`: la versión más reciente (cuesta el doble) [D1] |
| **User pool / login alojado / plan** | Directorio de Cognito / pantallas de acceso de Cognito / *Lite·Essentials·Plus* [C1, C2, C3] |
| **Disparador pre-registro** | Lambda que Cognito invoca antes de crear un usuario [C5] |
| **MAU** | Usuario activo mensual (unidad de cobro de Cognito) [C3] |
| **Transaction Search** | Opción de CloudWatch necesaria para ver las trazas de AgentCore [A6] |

### Pruebas, entorno y experiencia de usuario

| Término | Significado |
|---------|-------------|
| **Pirámide de pruebas** | Muchas pruebas rápidas abajo, pocas lentas arriba [T1] |
| **Fake / stub / spy** | Dobles de prueba [T2] |
| **moto** | Biblioteca que simula servicios de AWS en memoria |
| **e2e** | Prueba de extremo a extremo (aquí, navegador real con Playwright) |
| **`uv`, lock, `--frozen`** | Gestor de paquetes de Python; archivo de versiones fijadas; instalar exactamente el lock |
| **WCAG 2.2** | Pautas de accesibilidad web del W3C [U4] |
| **Ley de Hick / Ley de Fitts** | Más opciones = más tiempo de decisión / objetivos grandes y cercanos se alcanzan antes [U2, U3] |
| **Divulgación progresiva** | Mostrar lo esencial y dejar el detalle a demanda [U6] |
| **Camino feliz** | El recorrido más común y sin fricción, convertido en un botón |
| ***Tile*, *chip*, *toast*, FAB** | Botón grande de acción; botón píldora; aviso temporal; botón flotante |
| **ADR** | Registro de decisión de arquitectura |
| **Mermaid** | Lenguaje de diagramas en texto (<https://mermaid.js.org/>); se renderiza en GitHub |

## 2. Referencias

> Todas las páginas se consultaron el 3 de octubre de 2026. Los precios y cuotas cambian: **comprobar siempre la fuente**.

### AWS — AgentCore (agente)

| Código | Fuente |
|--------|--------|
| A1 | [AgentCore harness](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html) |
| A2 | [Tools (herramientas, funciones en línea, `allowedTools`)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-tools.html) |
| A2b | [Environment and filesystem](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-environment.html) |
| A3 | [Models and instructions (`apiFormat`)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-models.html) |
| A4 | [API: InvokeHarness](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeHarness.html) |
| A5 | [Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html) |
| A6 | [Observability and cost controls](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-operations.html) |
| A7 | [Versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-versioning.html) |
| A8 | [Harness vs. Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-vs-runtime.html) |
| A9 | [Security: permisos y política del rol de ejecución](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-security.html#harness-execution-role-policy) |
| A10 | [Security: modelo de responsabilidad compartida y límite de confianza](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-security.html#harness-trust-boundary) |
| A11 | [API: HarnessInlineFunctionConfig](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_HarnessInlineFunctionConfig.html) |
| A12 | [Bedrock: NVIDIA Nemotron Nano 9B v2 (tarjeta del modelo)](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-nvidia-nvidia-nemotron-nano-9b-v2.html) |
| A13 | [Amazon Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/) |
| A14 | [Bedrock: Chat Completions API (bedrock-runtime y bedrock-mantle)](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions-mantle.html) |
| A15 | [Lifecycle hooks](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-lifecycle-hooks.html) |
| A16 | [CloudFormation: AWS::BedrockAgentCore::Harness](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-harness.html) |
| A17 | [Quotas for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) |
| AP1 | [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) |
| M1 | [Bedrock: métricas de CloudWatch para el endpoint Mantle](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-supports-cloudwatch-metrics-bedrock-mantle-endpoint/) |

### AWS — otros servicios

| Código | Fuente |
|--------|--------|
| L1 | [Lambda: crear y gestionar Function URL](https://docs.aws.amazon.com/lambda/latest/dg/urls-configuration.html) |
| L2 | [Lambda: invocar Function URL (formato de petición/respuesta)](https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html) |
| L3 | [Lambda: runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html) |
| L4 | [Lambda: precios](https://aws.amazon.com/lambda/pricing/) |
| L5 | [Lambda: cuotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) |
| D1, D2, D4 | [DynamoDB: trabajar con elementos (consistencia, escrituras condicionales, ReturnValues)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/WorkingWithItems.html) |
| D3 | [DynamoDB: buenas prácticas de Query y Scan](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-query-scan.html) |
| D5 | [DynamoDB: precios bajo demanda](https://aws.amazon.com/dynamodb/pricing/on-demand/) |
| C1 | [CloudFormation: AWS::Cognito::UserPool](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpool.html) |
| C2 | [CloudFormation: AWS::Cognito::UserPoolDomain (`ManagedLoginVersion`)](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-cognito-userpooldomain.html) |
| C3 | [Cognito: precios](https://aws.amazon.com/cognito/pricing/) |
| C4 | [Cognito: ajustes de correo (límite de 50/día)](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html) |
| C5 | [Cognito: disparador pre-registro](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-sign-up.html) |
| C6 | [Cognito: endpoint de tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html) |
| C7 | [Cognito: endpoint de cierre de sesión](https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html) |
| SM1 | [Secrets Manager: precios](https://aws.amazon.com/secrets-manager/pricing/) |

### Estándares y seguridad

| Código | Fuente |
|--------|--------|
| R1 | Yao et al., [*ReAct: Synergizing Reasoning and Acting in Language Models*](https://arxiv.org/abs/2210.03629) (2022) |
| R2 | [RFC 7636 — PKCE](https://datatracker.ietf.org/doc/html/rfc7636) |
| R3 | [RFC 9700 — Best Current Practice for OAuth 2.0 Security (BCP 240)](https://www.rfc-editor.org/rfc/rfc9700) y [RFC 6749 — OAuth 2.0](https://www.rfc-editor.org/rfc/rfc6749) |
| R4 | [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html) (§3.1.2.1 y §3.1.3.7) |
| R5 | [Cookies: RFC 6265bis (prefijos `__Host-`, `SameSite`)](https://datatracker.ietf.org/doc/html/draft-ietf-httpbis-rfc6265bis) |
| R6 | [RFC 2104 — HMAC](https://www.rfc-editor.org/rfc/rfc2104) |
| O1 | [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) |
| O2 | [OWASP LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) |
| O3 | [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) |
| O4 | [OWASP HTTP Headers Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html) |
| P1 | [Python: `hmac.compare_digest`](https://docs.python.org/3/library/hmac.html) |
| P2 | [uv: *Locking depends on the current Python version if `requires-python` isn't set* (issue #4050)](https://github.com/astral-sh/uv/issues/4050) y [uv: resolución](https://docs.astral.sh/uv/concepts/resolution/) |

### GitHub, agentes, modelo, pruebas y UX

| Código | Fuente |
|--------|--------|
| G1 | [GitHub Changelog: sujetos inmutables en tokens OIDC (23 abr 2026)](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/) |
| G2 | [GitHub Docs: OpenID Connect reference](https://docs.github.com/actions/reference/openid-connect-reference) |
| W1 | [GitHub Docs: eventos que disparan workflows (`workflow_dispatch`, `push`, `pull_request`)](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) |
| W2 | [GitHub Docs: OIDC en AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws) |
| S1 | [Strands Agents: *Agent Loop*](https://strandsagents.com/docs/user-guide/sdk/agents/agent-loop/) |
| N1 | NVIDIA, [*Nemotron Nano 2*](https://arxiv.org/abs/2508.14444) y [tarjeta del modelo](https://developer.nvidia.com/downloads/assets/ace/model_card/nemotron-nano-9b-v2.pdf) |
| T1 | Fowler, [*The Practical Test Pyramid*](https://martinfowler.com/articles/practical-test-pyramid.html) |
| T2 | Fowler, [*Test Double*](https://martinfowler.com/bliki/TestDouble.html) |
| U1 | NN/g, [*10 Usability Heuristics*](https://www.nngroup.com/articles/ten-usability-heuristics/) |
| U2 | [Laws of UX: Ley de Hick](https://lawsofux.com/hicks-law/) |
| U3 | [Laws of UX: Ley de Fitts](https://lawsofux.com/fittss-law/) |
| U4 | [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/) |
| U5 | [W3C: Understanding SC 2.5.8 Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) |
| U6 | NN/g, [*Progressive Disclosure*](https://www.nngroup.com/articles/progressive-disclosure/) |

## 3. Qué se verificó por cuenta propia (y no está en estas fuentes)

Hechos descubiertos **probando contra la cuenta real** y que la documentación **no** recoge o recoge distinto: formato `@nombre` de
`allowedTools` para funciones en línea; el eco de `toolResult` con `json` rompe el analizador de boto3; la confianza del rol de
ejecución necesita `aws:SourceArn = …:*`; los harness por API traen memoria administrada con `SEMANTIC` + `SUMMARIZATION`;
`converse_stream` con Nemotron no respondió en 60 s; el *runtime* usa su propio ARN para validar el rol; el tamaño de una
invocación mínima (7 622 tokens). Cada uno está marcado como «verificado» en su documento.

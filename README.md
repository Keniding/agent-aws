# Sistema de incidencias (AgentCore + Lambda + web)

Registro y seguimiento de incidencias con un asistente de IA que clasifica cada una (severidad, categoría,
resumen, próximos pasos) y responde dudas sobre las abiertas.

```
Navegador ──► Lambda (Function URL: web + API) ──► DynamoDB (bajo demanda)
                         └──► AgentCore harness (InvokeHarness) ──► Bedrock
```
Todo se paga por uso: Lambda, DynamoDB on-demand, harness de AgentCore (sin cargo propio; se factura el
runtime/memoria consumidos) y Bedrock. Sin tráfico no hay coste, salvo el bucket S3 con el zip.

## API
| Método y ruta | Qué hace |
|---|---|
| `GET /` | web |
| `GET /api/incidents` | lista (más recientes primero) |
| `POST /api/incidents` `{title, description}` | crea y clasifica con el asistente (si falla, se guarda igualmente) |
| `PATCH /api/incidents/{id}` `{status}` | `abierta` · `en_curso` · `resuelta` |
| `POST /api/chat` `{message, session_id?}` | pregunta al asistente con las incidencias abiertas como contexto |

## Versiones
Ninguna fijada a mano: `uv.lock` las resuelve (boto3 va dentro del zip porque el de Lambda puede no traer
`InvokeHarness`) y el runtime de Lambda se deduce del Python de uv (`build/runtime.txt`). Las actions de
GitHub usan los últimos tags existentes al crear el repo.

## Puesta en marcha
1. Rol IAM OIDC para GitHub (confía en `token.actions.githubusercontent.com`, repo `Keniding/agent-aws`) con
   permisos sobre CloudFormation, IAM, Lambda, DynamoDB, S3, Cognito, Secrets Manager y `bedrock-agentcore:*`.
2. Modelo: por defecto `nvidia.nemotron-nano-9b-v2` vía Bedrock Mantle (`chat_completions`), el mismo que usa el playground y que no requiere suscripción de Marketplace. Para otro, variables `MODEL_ID` y `API_FORMAT`.
3. GitHub → Settings: secret `AWS_ROLE_ARN`; variables `AWS_REGION` y `MODEL_ID`.
4. Push a `main` (o ejecutar `deploy` a mano): sube el zip, despliega `template.yaml`, crea/actualiza el
   harness e imprime la URL. `ci.yml` valida ramas y PRs; `destroy.yml` (manual) lo borra todo.

## Pruebas y ejecución local
- `uv sync && uv run pytest` — 10 pruebas de la API (Lambda real + DynamoDB simulado con moto + harness falso)
  y 8 e2e de navegador (Chromium vía Playwright): alta, clasificación, filtros, cambio de estado,
  persistencia, chat con sesión, escape de HTML, tres temas y móvil. Si Chromium está preinstalado en otra
  revisión, se detecta en `PLAYWRIGHT_BROWSERS_PATH` o con `CHROMIUM_PATH`.
- `uv run scripts/local.py` — la web completa en `http://127.0.0.1:8000` sin AWS (datos y agente simulados).
- `./scripts/package.sh` — genera `build/lambda.zip`.

Estas pruebas **no** llaman a Bedrock ni al harness reales: eso solo se valida desplegando.

## Diseño
La web sigue el sistema *Humanismo Editorial*: papel sin blanquear, tinta, terracota como campo, serif
(EB Garamond) para titulares, grotesca (Hanken Grotesk) para interfaz, mono (JetBrains Mono) para pasos,
rótulos `//`, esquinas rectas, sin sombras y cuadrícula milimétrica. Temas Papel / Tinta / Alto contraste
(automático por preferencias del sistema, o selector manual). Las fuentes vienen de Google Fonts con
fallback local.

## Pendiente de validar
- Validado contra AWS real (us-east-2, 2026-10-03): despliegue, harness, clasificación y chat. La política del rol del harness es un subconjunto de la que crea la consola.
  servicio de boto3 y la política del rol del harness es un punto de partida (ver *harness-security*).
- Autenticación hecha (ver abajo). Pendiente para uso real: MFA, WAF y límites de uso por usuario. Antes de uso
  real, añade autenticación (Cognito/IAM), WAF y límites.
- La lista usa `Scan` (válido para volúmenes pequeños); para muchos datos, añade un índice por estado/fecha.

## Experiencia de uso (poca carga cognitiva)
- **Inicio con acciones directas al agente:** «Atender la más urgente» (camino feliz, destacada), «¿Qué atiendo
  primero?», «Resumen del día» y «Reportar un problema». Un toque, sin escribir; el chat libre queda debajo.
- **Reporte guiado en dos pasos:** plantillas de problemas frecuentes + «¿a quién afecta?» (opcional); el detalle
  va plegado. El agente clasifica y la web avisa en lenguaje llano («la clasifiqué como crítica y la puse en curso»).
- **Lista priorizada:** solo «Pendientes» por defecto, ordenada por severidad, con la primera marcada como
  «Sugerida». Cada tarjeta tiene **un** botón principal según su estado (Empezar a atender → Marcar resuelta →
  Reabrir) más «Preguntar al agente», cuya respuesta aparece dentro de la tarjeta. Los cambios se pueden
  **deshacer** desde el aviso.
- Lo que hizo el agente se muestra en español («✓ Revisó las incidencias», «↻ … (reintentó)»), no como nombres
  de herramientas, y tras cada respuesta hay siguientes pasos sugeridos.

## Autenticación (solo AWS: Amazon Cognito)
La URL de la Function URL sigue siendo pública, pero **la app no sirve nada sin sesión** (`src/auth.py`):
`/` redirige al login de Cognito y la API responde `401`. Si Cognito no está configurado responde `503`
(falla cerrada). Sin dependencias ni servicios fuera de AWS.

- **Flujo:** código de autorización + PKCE con un cliente público; `state` y `nonce` en una cookie firmada de
  10 min; se validan emisor, audiencia, `token_use`, nonce y caducidad. La sesión es una cookie
  `__Host-session` firmada con HMAC (clave generada en Secrets Manager), `HttpOnly`, `Secure`, `SameSite=Lax`,
  8 h (`SESSION_HOURS`). Las escrituras también comprueban `Origin` contra CSRF.
- **Registro propio con código por correo (sin dar de alta a mano):** la persona pulsa «Sign up» en el login, recibe un código en su email y entra. Solo vale para los correos/dominios de `AllowedSignups` (`src/presignup.py`); **vacío = nadie se registra solo**, así nadie ajeno gasta tokens. Contraseña mínima de 12. Los administradores pueden seguir dando de alta a mano.
- **Salir** cierra la sesión de la app y la de Cognito.
- **Dar de alta a alguien:**
  ```
  POOL=$(aws cloudformation describe-stacks --stack-name incidencias --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
  aws cognito-idp admin-create-user --user-pool-id $POOL --username persona@empresa.com \
    --user-attributes Name=email,Value=persona@empresa.com Name=email_verified,Value=true
  ```
  Cognito le envía un correo con una contraseña temporal. Para quitar acceso: `admin-delete-user` o `admin-disable-user`.
- **Local y pruebas:** `AUTH_DISABLED=1` (lo fijan `scripts/local.py` y `tests/conftest.py`); nunca se define en AWS.
- Validado contra Cognito real: login, sesión, agente tras el login, salida y reentrada pidiendo credenciales.

### Quién puede registrarse solo
```
aws cloudformation deploy ... --parameter-overrides ... AllowedSignups="ana@empresa.com,@empresa.com"
```
En GitHub Actions: variable `ALLOWED_SIGNUPS` (ya se pasa al desplegar). Acepta correos exactos y dominios con `@`.

### Entrar con Google (opcional)
Cognito lo admite como proveedor federado, pero requiere crear un cliente OAuth en Google Cloud Console (no se
puede por CLI): con su `client_id` y `client_secret` se añade un `AWS::Cognito::UserPoolIdentityProvider` y
`SupportedIdentityProviders: [COGNITO, Google]`. `src/auth.py` no cambia (sigue validando el id_token de Cognito).
Ojo: con Google habría que filtrar también por correo/dominio (el control actual solo cubre el registro propio).

## Conversación y fiabilidad del agente
- **Hilo visible:** el panel del agente muestra cada pregunta («Tú») y cada respuesta («Agente») con los pasos que
  ejecutó; se conserva al recargar y se limpia con «Nueva conversación» o si entra otro usuario.
- **Solo sus herramientas:** `allowedTools=["@listar_incidencias", …]` (el formato `@nombre` es el que acepta
  AWS; con nombres sueltos el agente deja de llamar a las herramientas). Así no puede usar `shell` ni otras internas.
- **Fuente de verdad:** cada pregunta del chat lleva adjunto el estado real de lo pendiente, y el prompt del agente
  le prohíbe usar incidencias recordadas. La memoria a largo plazo del harness se aísla por usuario (`actorId` = sub
  de Cognito). Los resultados de las herramientas incluyen `proximos_pasos` para que pueda informar de ellos.

## Registrar incidencias conversando
El agente tiene la herramienta `crear_incidencia`: «Registra que la impresora no imprime» crea la incidencia al
primer mensaje. El id lo genera el sistema (nunca se le pide al usuario) y el agente deduce título, severidad,
categoría, resumen y pasos. La incidencia nueva aparece resaltada en la lista.

## «¿Ya lo registré?»
- **Fecha en cada incidencia:** «Registrada el 3 oct 2026, 03:15 · hace 6 min» (hora local del navegador).
- **Filtro por día:** el campo «Registradas el» limita la lista a una fecha; «Todas las fechas» lo quita.
- **Aviso de duplicados:** al escribir un reporte, si ya existe algo parecido (por palabras, ignorando acentos y
  mayúsculas) se muestra con su estado y cuándo se registró, con un botón «Verla». No bloquea: se puede reportar igual.
- El agente conoce la fecha de registro (`registrada`, en UTC) y puede responder «¿cuándo registré…?».
- **Versión del almacenamiento del navegador** (`v`): al cambiar, la web descarta las conversaciones guardadas de
  versiones anteriores, para que un historial antiguo no condicione al agente tras una actualización.

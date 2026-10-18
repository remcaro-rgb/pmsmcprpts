// Website text in English and Latin American Spanish. The language comes from the pms_lang
// cookie (set by the switcher in the header), else the browser's Accept-Language.

export type Locale = "en" | "es";
export const LOCALES: Locale[] = ["en", "es"];
export const LOCALE_COOKIE = "pms_lang";
/** BCP 47 tags for dates and numbers: Latin American Spanish. */
export const INTL_LOCALE: Record<Locale, string> = { en: "en-US", es: "es-419" };

const en = {
  appName: "PMS Reports",
  tagline: "Ask about occupancy, rates, revenue, bookings and guests",
  newChat: "New chat",
  signOut: "Sign out",
  language: "Language",
  darkMode: "Switch to dark mode",
  lightMode: "Switch to light mode",
  showConversations: "Show conversations",
  conversations: "Conversations",
  close: "Close",
  loading: "Loading…",
  noConversations: "Your conversations will appear here.",
  delete: "Delete",
  deleteNamed: (title: string) => `Delete “${title}”`,
  confirmDelete: (title: string) => `Delete “${title}”?`,
  emptyTitle: "What would you like to know?",
  emptyBody: "Answers come straight from the hotel database. Open a step to see the query and its results.",
  starters: [
    "How did occupancy, ADR and RevPAR compare across the three hotels last quarter?",
    "Which booking channels have the highest cancellation rates this year?",
    "Show monthly room revenue for Lisbon over the last 12 months.",
    "Who are our top 10 guests by total spend?",
  ],
  placeholder: "Ask about your hotels…",
  message: "Message",
  send: "Send",
  stop: "Stop",
  connectionClosed: "The connection closed before the answer finished.",
  assistantUnreachable: "Could not reach the assistant.",
  requestFailed: (status: number) => `Request failed (${status}).`,
  tools: {
    describe_schema: "Read the database schema",
    run_sql: "Ran a SQL query",
    get_kpis: "Fetched KPIs",
    get_dataset: "Read a stored result",
    make_chart: "Made a chart",
    make_spreadsheet: "Created a spreadsheet",
    make_presentation: "Created a presentation",
    make_report: "Created a report",
  } as Record<string, string>,
  rows: (n: string, one: boolean) => `${n} ${one ? "row" : "rows"}`,
  showingRows: (shown: string, total: string) => `Showing ${shown} of ${total} rows`,
  rowsCapped: " (result capped at 50,000 rows)",
  yes: "yes",
  no: "no",
  failed: "failed",
  running: "running",
  done: "done",
  schemaSummary: (n: number, date: string) => `${n} tables and views · business date ${date}`,
  thinking: "Thinking",
  working: "Working…",
  stopped: "Stopped.",
  somethingWrong: "Something went wrong.",
  notAdded: "This message was not added to the conversation.",
  usage: (input: string, pct: number, output: string) => `${input} tokens in (${pct}% cached) · ${output} out`,
  fileTypes: {
    xlsx: "Excel workbook",
    pptx: "PowerPoint deck",
    docx: "Word document",
    pdf: "PDF document",
    png: "PNG image",
    other: "File",
  },
  download: "Download",
  showData: "Show data",
  hideData: "Hide data",
  downloadPng: "Download PNG",
  chartHelp: (title: string) => `${title}. Use the left and right arrow keys to read values.`,
  // Server responses and pages
  rateLimited: (seconds: number) => `You've sent a lot of messages. Try again in ${seconds} seconds.`,
  serviceUnreachable: "The assistant service is not reachable.",
  fileNotFound: "File not found or expired.",
  conversationNotFound: "Conversation not found.",
  signInToContinue: "Sign in to continue.",
  signedOutTitle: "You're signed out",
  signedOutBody: "Close this tab, or sign in again to keep asking about your hotels.",
  signInAgain: "Sign in again",
  signInExpiredTitle: "Sign-in expired",
  signInExpiredBody: "This sign-in attempt expired. Please sign in again.",
  signInUnavailableTitle: "Sign-in unavailable",
  signInUnavailableBody: "The sign-in provider can't be reached right now. Try again shortly.",
  signInFailedTitle: "Sign-in failed",
  signInFailedBody: (reason: string) => `We could not verify your sign-in: ${reason}`,
  notAllowedTitle: "Access not allowed",
  notAllowedBody: (email: string) =>
    `${email} is not allowed to use this site. Ask the administrator to add your account.`,
  misconfiguredTitle: "Sign-in is misconfigured",
};

export type Messages = typeof en;

const es: Messages = {
  appName: "Reportes PMS",
  tagline: "Pregunta sobre ocupación, tarifas, ingresos, reservas y huéspedes",
  newChat: "Nuevo chat",
  signOut: "Cerrar sesión",
  language: "Idioma",
  darkMode: "Cambiar a modo oscuro",
  lightMode: "Cambiar a modo claro",
  showConversations: "Mostrar conversaciones",
  conversations: "Conversaciones",
  close: "Cerrar",
  loading: "Cargando…",
  noConversations: "Tus conversaciones aparecerán aquí.",
  delete: "Eliminar",
  deleteNamed: (title) => `Eliminar “${title}”`,
  confirmDelete: (title) => `¿Eliminar “${title}”?`,
  emptyTitle: "¿Qué te gustaría saber?",
  emptyBody:
    "Las respuestas salen directamente de la base de datos de los hoteles. Abre un paso para ver la consulta y sus resultados.",
  starters: [
    "¿Cómo se compararon la ocupación, el ADR y el RevPAR de los tres hoteles el trimestre pasado?",
    "¿Qué canales de reserva tienen las tasas de cancelación más altas este año?",
    "Muestra los ingresos mensuales por habitaciones de Lisboa en los últimos 12 meses.",
    "¿Quiénes son nuestros 10 principales huéspedes por gasto total?",
  ],
  placeholder: "Pregunta sobre tus hoteles…",
  message: "Mensaje",
  send: "Enviar",
  stop: "Detener",
  connectionClosed: "La conexión se cerró antes de que terminara la respuesta.",
  assistantUnreachable: "No se pudo conectar con el asistente.",
  requestFailed: (status) => `La solicitud falló (${status}).`,
  tools: {
    describe_schema: "Consultó el esquema de la base de datos",
    run_sql: "Ejecutó una consulta SQL",
    get_kpis: "Obtuvo los KPI",
    get_dataset: "Leyó un resultado guardado",
    make_chart: "Creó un gráfico",
    make_spreadsheet: "Creó una hoja de cálculo",
    make_presentation: "Creó una presentación",
    make_report: "Creó un reporte",
  },
  rows: (n, one) => `${n} ${one ? "fila" : "filas"}`,
  showingRows: (shown, total) => `Mostrando ${shown} de ${total} filas`,
  rowsCapped: " (resultado limitado a 50,000 filas)",
  yes: "sí",
  no: "no",
  failed: "falló",
  running: "en curso",
  done: "listo",
  schemaSummary: (n, date) => `${n} tablas y vistas · fecha de negocio ${date}`,
  thinking: "Razonamiento",
  working: "Trabajando…",
  stopped: "Detenido.",
  somethingWrong: "Algo salió mal.",
  notAdded: "Este mensaje no se agregó a la conversación.",
  usage: (input, pct, output) => `${input} tokens de entrada (${pct}% en caché) · ${output} de salida`,
  fileTypes: {
    xlsx: "Libro de Excel",
    pptx: "Presentación de PowerPoint",
    docx: "Documento de Word",
    pdf: "Documento PDF",
    png: "Imagen PNG",
    other: "Archivo",
  },
  download: "Descargar",
  showData: "Ver datos",
  hideData: "Ocultar datos",
  downloadPng: "Descargar PNG",
  chartHelp: (title) => `${title}. Usa las flechas izquierda y derecha para leer los valores.`,
  rateLimited: (seconds) => `Enviaste muchos mensajes. Intenta de nuevo en ${seconds} segundos.`,
  serviceUnreachable: "No se puede conectar con el servicio del asistente.",
  fileNotFound: "El archivo no existe o ya venció.",
  conversationNotFound: "No se encontró la conversación.",
  signInToContinue: "Inicia sesión para continuar.",
  signedOutTitle: "Cerraste sesión",
  signedOutBody: "Cierra esta pestaña o vuelve a iniciar sesión para seguir consultando sobre tus hoteles.",
  signInAgain: "Iniciar sesión de nuevo",
  signInExpiredTitle: "El inicio de sesión venció",
  signInExpiredBody: "Este intento de inicio de sesión venció. Vuelve a iniciar sesión.",
  signInUnavailableTitle: "Inicio de sesión no disponible",
  signInUnavailableBody: "No podemos conectar con el proveedor de inicio de sesión en este momento. Intenta de nuevo en unos minutos.",
  signInFailedTitle: "No se pudo iniciar sesión",
  signInFailedBody: (reason) => `No pudimos verificar tu inicio de sesión: ${reason}`,
  notAllowedTitle: "Acceso no permitido",
  notAllowedBody: (email) => `${email} no tiene permiso para usar este sitio. Pide al administrador que agregue tu cuenta.`,
  misconfiguredTitle: "El inicio de sesión está mal configurado",
};

const MESSAGES: Record<Locale, Messages> = { en, es };

export function messages(locale: Locale): Messages {
  return MESSAGES[locale];
}

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as string[]).includes(value);
}

/** The cookie's choice, else the first supported language in Accept-Language, else English. */
export function pickLocale(cookie: string | null | undefined, acceptLanguage: string | null | undefined): Locale {
  if (isLocale(cookie)) return cookie;
  const ranked = (acceptLanguage ?? "")
    .split(",")
    .map((part, i) => {
      const [tag, ...params] = part.trim().toLowerCase().split(";");
      const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
      return { lang: tag.split("-")[0], q: q ? Number(q.slice(2)) || 0 : 1, i };
    })
    .filter((x) => x.lang && x.q > 0)
    .sort((a, b) => b.q - a.q || a.i - b.i);
  return ranked.map((x) => x.lang).find(isLocale) ?? "en";
}

/** The locale of a request (route handlers and proxy). */
export function requestLocale(req: Request): Locale {
  const cookie = (req.headers.get("cookie") ?? "")
    .split(";")
    .map((c) => c.trim().split("="))
    .find(([k]) => k === LOCALE_COOKIE)?.[1];
  return pickLocale(cookie, req.headers.get("accept-language"));
}

export function formatNumber(n: number, locale: Locale, maximumFractionDigits = 0): string {
  return new Intl.NumberFormat(INTL_LOCALE[locale], { maximumFractionDigits }).format(n);
}

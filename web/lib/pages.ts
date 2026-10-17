const escape = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** Minimal standalone page for sign-in outcomes (shown outside the app shell). */
export function messagePage(title: string, message: string, status: number, retry = false): Response {
  const action = retry ? `<p><a href="/auth/login" style="color:#2563eb">Sign in again</a></p>` : "";
  const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escape(title)}</title><body style="font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem;color:#1c1917">
<h1 style="font-size:1.4rem">${escape(title)}</h1><p style="color:#57534e;line-height:1.5">${escape(message)}</p>${action}</body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8" } });
}

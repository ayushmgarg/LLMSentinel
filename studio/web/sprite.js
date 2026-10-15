/* The icon sprite, shared by every page.

   Injected here rather than pasted into each page so that one edit changes all of
   them. The markup is a literal in this file; no document content ever reaches
   innerHTML anywhere in the Studio. Loaded with `defer` before the page script, so
   the symbols exist before anything renders an icon. */

"use strict";

const SPRITE_MARKUP = `
<symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z"/></symbol>
<symbol id="i-shield-check" viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4.5"/></symbol>
<symbol id="i-shield-off" viewBox="0 0 24 24"><path d="M19 13c-.9 3.6-3.6 6.5-7 8-4-1.7-7-5.5-7-10V6l2-.9M9.5 4.1L12 3l7 3v4"/><path d="M3 3l18 18"/></symbol>
<symbol id="i-database" viewBox="0 0 24 24"><ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v6c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8v-6"/><path d="M4.5 11.5v6c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8v-6"/></symbol>
<symbol id="i-cpu" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2.5v3M15 2.5v3M9 18.5v3M15 18.5v3M2.5 9h3M2.5 15h3M18.5 9h3M18.5 15h3"/></symbol>
<symbol id="i-plug" viewBox="0 0 24 24"><path d="M9 2.5v5M15 2.5v5M6 7.5h12v3.5a6 6 0 0 1-12 0V7.5zM12 17v4.5"/></symbol>
<symbol id="i-file" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></symbol>
<symbol id="i-braces" viewBox="0 0 24 24"><path d="M8 3.5c-2 0-3 1-3 3v3c0 1.4-.8 2.5-2 2.5 1.2 0 2 1.1 2 2.5v3c0 2 1 3 3 3M16 3.5c2 0 3 1 3 3v3c0 1.4.8 2.5 2 2.5-1.2 0-2 1.1-2 2.5v3c0 2-1 3-3 3"/></symbol>
<symbol id="i-code" viewBox="0 0 24 24"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4.5l-4 15"/></symbol>
<symbol id="i-table" viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 10h18M3 15h18M9 4.5v15"/></symbol>
<symbol id="i-upload" viewBox="0 0 24 24"><path d="M12 15.5V4M7 8.5L12 3.5l5 5M4 15.5V19a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3.5"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="M7.5 4.5l12 7.5-12 7.5v-15z"/></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></symbol>
<symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 3.5l9.5 16.5h-19L12 3.5z"/><path d="M12 10v4.5M12 17.2h.01"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8h.01"/></symbol>
<symbol id="i-zap" viewBox="0 0 24 24"><path d="M13 2.5L4.5 13.5h7l-1 8 8.5-11h-7l1-8z"/></symbol>
<symbol id="i-scan" viewBox="0 0 24 24"><path d="M3.5 7.5V5.5a2 2 0 0 1 2-2h2M16.5 3.5h2a2 2 0 0 1 2 2v2M20.5 16.5v2a2 2 0 0 1-2 2h-2M7.5 20.5h-2a2 2 0 0 1-2-2v-2M7 12h10"/></symbol>
<symbol id="i-route" viewBox="0 0 24 24"><circle cx="6" cy="18.5" r="2.5"/><circle cx="18" cy="5.5" r="2.5"/><path d="M8.5 18.5H15a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h6.5"/></symbol>
<symbol id="i-gate" viewBox="0 0 24 24"><path d="M4 21V8.5l8-5 8 5V21"/><path d="M9 21v-7h6v7M2.5 21h19"/></symbol>
<symbol id="i-layers" viewBox="0 0 24 24"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5M3 17.5l9 5 9-5"/></symbol>
<symbol id="i-headset" viewBox="0 0 24 24"><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="2.5" y="13" width="4" height="6" rx="1.5"/><rect x="17.5" y="13" width="4" height="6" rx="1.5"/><path d="M19.5 19a3 3 0 0 1-3 3H14"/></symbol>
<symbol id="i-terminal" viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 9.5l3 2.5-3 2.5M13 15h4"/></symbol>
<symbol id="i-sparkle" viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16z"/></symbol>
<symbol id="i-chevron" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></symbol>
<symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.6M12 18.9v2.6M4.2 4.2l1.9 1.9M17.9 17.9l1.9 1.9M2.5 12h2.6M18.9 12h2.6M4.2 19.8l1.9-1.9M17.9 6.1l1.9-1.9"/></symbol>
<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></symbol>
`;

(() => {
  const host = document.createElement("div");
  host.className = "sprite-host";
  host.setAttribute("aria-hidden", "true");
  host.innerHTML = `<svg class="sprite" xmlns="http://www.w3.org/2000/svg">${SPRITE_MARKUP}</svg>`;
  document.body.prepend(host);
})();

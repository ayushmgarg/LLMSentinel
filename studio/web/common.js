/* Helpers shared by every page of the Studio.

   Every string that comes from a document, a model or the server is rendered with
   textContent / text nodes, never innerHTML: the context being inspected is hostile
   by assumption, and the server's CSP forbids inline script anyway. */

"use strict";

const $ = (selector, root = document) => root.querySelector(selector);

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  for (const [key, value] of Object.entries(options.attrs || {})) {
    if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  svg.append(use);
  return svg;
}

function tag(text, tone = "neutral", iconName = null, extra = "") {
  return el("span", { className: `tag tag--${tone} ${extra}`.trim() }, [iconName ? icon(iconName) : null, text]);
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

async function api(path, body) {
  const options = body === undefined
    ? { headers: { Accept: "application/json" } }
    : { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw Object.assign(new Error("The Studio server is not reachable."), { hint: "Is `python -m studio.server` still running?" });
  }
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) {
    throw Object.assign(new Error(data.error || `Request failed (HTTP ${response.status}).`), { hint: data.hint || "" });
  }
  return data;
}

function toast(title, message = "", tone = "neutral") {
  const region = $("#toast-region");
  if (!region) return;
  const node = el("div", { className: `toast toast--${tone}`, attrs: { role: tone === "danger" ? "alert" : "status" } }, [
    el("strong", { text: title }),
    message ? el("span", { text: message }) : null,
  ]);
  region.append(node);
  setTimeout(() => {
    node.classList.add("toast--out");
    setTimeout(() => node.remove(), 300);
  }, tone === "danger" ? 7000 : 4000);
}

/* ------------------------------------------------------------------- theme */
const THEME_KEY = "llmsentinel-studio-theme";

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch (error) {
    return null;
  }
}

function systemTheme() {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = $("#theme-toggle");
  if (!button) return;
  button.replaceChildren(icon(theme === "light" ? "i-moon" : "i-sun"));
  button.setAttribute("aria-label", theme === "light" ? "Switch to dark theme" : "Switch to light theme");
  button.setAttribute("title", theme === "light" ? "Dark theme" : "Light theme");
}

function initTheme() {
  let theme = storedTheme() || systemTheme();
  applyTheme(theme);
  const button = $("#theme-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    theme = theme === "light" ? "dark" : "light";
    applyTheme(theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (error) {
      /* storage unavailable */
    }
  });
}

/* Mark the current page in the navigation, so the three pages share one header. */
function initNav() {
  const here = window.location.pathname.replace(/\/$/, "/index.html").split("/").pop() || "index.html";
  document.querySelectorAll(".nav__links a").forEach((link) => {
    const href = link.getAttribute("href");
    if (href.includes("#")) return;  // an in-page jump is not "the page you are on"
    if (href === here) {
      link.classList.add("is-current");
      link.setAttribute("aria-current", "page");
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initNav();
});

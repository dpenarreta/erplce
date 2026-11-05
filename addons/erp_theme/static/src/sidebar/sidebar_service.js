import {reactive} from "@odoo/owl";
import {browser} from "@web/core/browser/browser";
import {registry} from "@web/core/registry";

/**
 * Shared state of the ERP LCE sidebar (US-018), used by the sidebar itself
 * and by the hamburger button of the top bar:
 * - collapsed: desktop "icons only" mode, remembered in the browser;
 * - drawerOpen: overlay panel open on screens < 992 px;
 * - lastMenuId: last menu chosen in the sidebar (tie-break when several menus
 *   open the same action).
 */
export const COLLAPSED_STORAGE_KEY = "erp_theme.sidebar_collapsed";

export function readCollapsedPreference() {
  try {
    return browser.localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1";
  } catch {
    // Storage unavailable (privacy mode, blocked): expanded by default.
    return false;
  }
}

export function writeCollapsedPreference(collapsed) {
  try {
    browser.localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    // Storage unavailable: the preference only lasts for this page.
  }
}

// Rest of the page while the overlay panel (modal) is open: not focusable
// nor reachable by screen readers.
export const INERT_SELECTORS = [".o_main_navbar", ".o_action_manager"];

export function setBackgroundInert(inert) {
  for (const selector of INERT_SELECTORS) {
    for (const el of document.querySelectorAll(selector)) {
      if (inert) {
        el.setAttribute("inert", "");
      } else {
        el.removeAttribute("inert");
      }
    }
  }
}

export const sidebarService = {
  start() {
    const state = reactive({
      collapsed: readCollapsedPreference(),
      drawerOpen: false,
      lastMenuId: null,
    });
    let opener = null;
    return {
      state,
      toggleCollapsed() {
        state.collapsed = !state.collapsed;
        writeCollapsedPreference(state.collapsed);
      },
      /**
       * @param {HTMLElement} [openerEl] element that gets the focus back
       *   when the panel is closed (the hamburger button)
       */
      openDrawer(openerEl) {
        opener = openerEl || null;
        state.drawerOpen = true;
        setBackgroundInert(true);
      },
      closeDrawer({restoreFocus = true} = {}) {
        if (!state.drawerOpen) {
          return;
        }
        state.drawerOpen = false;
        // Before giving the focus back: the opener is inside the navbar.
        setBackgroundInert(false);
        if (restoreFocus && opener && opener.isConnected) {
          opener.focus();
        }
        opener = null;
      },
    };
  },
};

registry.category("services").add("erp_theme_sidebar", sidebarService);

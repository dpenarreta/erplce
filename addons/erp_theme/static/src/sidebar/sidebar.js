import {
  Component,
  onMounted,
  onPatched,
  onWillUnmount,
  useEffect,
  useRef,
  useState,
} from "@odoo/owl";
import {browser} from "@web/core/browser/browser";
import {_t} from "@web/core/l10n/translation";
import {usePopover} from "@web/core/popover/popover_hook";
import {SIZES} from "@web/core/ui/ui_service";
import {useBus, useService} from "@web/core/utils/hooks";
import {getTabableElements} from "@web/core/utils/ui";
import {ErpSidebarFlyout} from "./sidebar_flyout";

const ICON_CLASS_RE = /^[\w\s-]+$/;
const ICON_COLOR_RE = /^(#[0-9a-f]{3,8}|[a-z]+)$/i;

/**
 * Icon of an application, from the menu data of the "menu" service:
 * - webIconData: image (data URL or path) computed by the server;
 * - webIcon "fa-class,color,background": font icon;
 * - otherwise a generic icon.
 * Font icon values come from ir.ui.menu (admin data): only plain class names
 * and colors are accepted.
 *
 * @param {Object} app
 * @returns {{type: "image", src: string}|{type: "font", iconClass: string,
 *   style: string}|{type: "default"}}
 */
export function getAppIcon(app) {
  if (app.webIconData) {
    return {type: "image", src: app.webIconData};
  }
  const [iconClass, color, backgroundColor] = (app.webIcon || "").split(",");
  if (iconClass && ICON_CLASS_RE.test(iconClass)) {
    const style = [
      ICON_COLOR_RE.test(color || "") ? `color: ${color};` : "",
      ICON_COLOR_RE.test(backgroundColor || "")
        ? `background-color: ${backgroundColor};`
        : "",
    ].join(" ");
    return {type: "font", iconClass: iconClass.trim(), style};
  }
  return {type: "default"};
}

// Memo of the visible children of each menu object. The "menu" service
// builds new objects when the menus are reloaded, so a WeakMap keyed by the
// object never returns stale data.
const visibleChildrenCache = new WeakMap();

/**
 * Children of a menu that lead somewhere: sections with children or menus
 * with an action. Only cached once the tree of the menu has been built
 * (menu.childrenTree, see menuService.getMenuAsTree).
 */
export function getVisibleChildren(menu) {
  if (visibleChildrenCache.has(menu)) {
    return visibleChildrenCache.get(menu);
  }
  const children = (menu.childrenTree || []).filter(
    (child) => child.actionID || getVisibleChildren(child).length
  );
  if (menu.childrenTree) {
    visibleChildrenCache.set(menu, children);
  }
  return children;
}

/**
 * Leaf menus of a tree (depth first) with their ancestors.
 *
 * @returns {Array<{menu: Object, ancestors: Object[]}>}
 */
export function getLeaves(menu, ancestors = []) {
  const children = getVisibleChildren(menu);
  if (!children.length) {
    return menu.actionID ? [{menu, ancestors}] : [];
  }
  return children.flatMap((child) => getLeaves(child, [...ancestors, menu]));
}

/**
 * Sidebar of the ERP LCE web client (US-018).
 *
 * - Lists the apps of the "menu" service (already filtered by groups on the
 *   server) with their icon; an app unfolds its sections and actions
 *   (accordion: one app unfolded at a time).
 * - Desktop (>= 992 px): fixed black bar of 240 px, can be collapsed to an
 *   icons-only bar of 64 px (preference kept in localStorage); in that mode
 *   the submenus of an app open in a popover next to its icon.
 * - Smaller screens: hidden; the hamburger button of the top bar opens it as
 *   a modal overlay panel (role="dialog", rest of the page inert, focus
 *   trapped inside, closed with Escape, the close button, a click outside or
 *   when an option is chosen; the focus goes back to the hamburger button).
 * - A "skip to content" link is the first focusable element of the page.
 */
export class ErpSidebar extends Component {
  static template = "erp_theme.Sidebar";
  static props = {};

  setup() {
    this.menuService = useService("menu");
    this.actionService = useService("action");
    this.sidebar = useService("erp_theme_sidebar");
    this.sidebarState = useState(this.sidebar.state);
    this.ui = useState(useService("ui"));
    this.root = useRef("root");
    this.state = useState({
      expanded: {},
      activeMenuId: null,
      // True when the active menu opens the displayed action; false when it
      // is only kept as context (action opened from a button of that page).
      activeIsExact: false,
      currentAppId: null,
      flyoutAppId: null,
    });
    this.labels = {
      mainMenu: _t("Main menu"),
      home: _t("Go to the home page"),
      collapse: _t("Collapse menu"),
      expand: _t("Expand menu"),
      close: _t("Close menu"),
      skip: _t("Skip to content"),
    };
    this.flyoutTarget = null;
    this.flyout = usePopover(ErpSidebarFlyout, {
      position: "right-start",
      popoverClass: "o_erp_sidebar_flyout_popover",
      onClose: () => this.onFlyoutClosed(),
    });

    useBus(this.env.bus, "MENUS:APP-CHANGED", () => {
      this.syncWithCurrentAction();
      // Also after menuService.reload(): the menus themselves changed.
      this.render();
    });
    useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () =>
      this.syncWithCurrentAction()
    );

    onMounted(() => {
      document.body.classList.add("o_erp_theme_has_sidebar");
      this.syncWithCurrentAction();
    });
    onWillUnmount(() => {
      this.flyout.close();
      this.sidebar.closeDrawer({restoreFocus: false});
      document.body.classList.remove(
        "o_erp_theme_has_sidebar",
        "o_erp_theme_sidebar_collapsed"
      );
    });

    // Body class used by the layout (padding of the web client).
    useEffect(
      (collapsed) => {
        document.body.classList.toggle("o_erp_theme_sidebar_collapsed", collapsed);
        if (!collapsed) {
          this.flyout.close();
        }
      },
      () => [this.sidebarState.collapsed]
    );

    // The overlay panel only exists on small screens: close it when the
    // window grows past the breakpoint (and the popover when it shrinks).
    useEffect(
      (isDesktop) => {
        if (isDesktop) {
          this.sidebar.closeDrawer({restoreFocus: false});
        } else {
          this.flyout.close();
        }
      },
      () => [this.isDesktop]
    );

    // Panel opened: move the focus inside (the close button).
    useEffect(
      (open) => {
        if (open && this.root.el) {
          const target =
            this.root.el.querySelector(".o_erp_sidebar_close") ||
            getTabableElements(this.root.el)[0];
          if (target) {
            target.focus();
          }
        }
      },
      () => [this.isDrawerOpen]
    );

    useEffect(
      (open) => {
        if (!open) {
          return;
        }
        const onKeydown = (ev) => {
          if (ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.closeDrawer();
          }
        };
        // Capture: before the hotkey service (it would close other things).
        window.addEventListener("keydown", onKeydown, true);
        return () => window.removeEventListener("keydown", onKeydown, true);
      },
      () => [this.isDrawerOpen]
    );

    // Keep the active option visible in the scrollable list. Checked after
    // every render (the accordion that contains it may be rendered after the
    // active menu is known, e.g. on the first load) and run on the next frame,
    // once laid out; only once per active option so that the user can scroll.
    this.scrolledKey = null;
    const scheduleScroll = () => {
      const key = `${this.state.activeMenuId}-${this.state.currentAppId}-${this.isDrawerOpen}`;
      if (key === this.scrolledKey || !this.root.el) {
        return;
      }
      // Wait for the active option itself when it is rendered in the list
      // (not in the icons-only mode).
      const target =
        this.state.activeMenuId && !this.isCollapsed
          ? this.root.el.querySelector(".o_erp_sidebar_active")
          : this.getActiveElement();
      if (!target) {
        return;
      }
      this.scrolledKey = key;
      // After the web font is applied (its metrics change the height of the
      // rows) and on the next frame, once laid out.
      const run = () => browser.requestAnimationFrame(() => this.scrollToActive());
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(run);
      } else {
        run();
      }
    };
    onMounted(scheduleScroll);
    onPatched(scheduleScroll);
  }

  /** Active option, or the current app (icons-only mode, no active
   * option). Two queries: a selector list would return the first one in
   * document order, i.e. always the app above the option. */
  getActiveElement() {
    if (!this.root.el) {
      return null;
    }
    return (
      this.root.el.querySelector(".o_erp_sidebar_active") ||
      this.root.el.querySelector(".o_erp_sidebar_current_app > .o_erp_sidebar_app")
    );
  }

  scrollToActive() {
    const el = this.getActiveElement();
    if (el && el.isConnected && el.scrollIntoView) {
      el.scrollIntoView({block: "nearest"});
    }
  }

  // -------------------------------------------------------------------------
  // Getters
  // -------------------------------------------------------------------------

  get isDesktop() {
    return this.ui.size >= SIZES.LG;
  }

  get isDrawerOpen() {
    return !this.isDesktop && this.sidebarState.drawerOpen;
  }

  /** Icons-only mode: desktop only (the overlay panel is always full). */
  get isCollapsed() {
    return this.isDesktop && this.sidebarState.collapsed;
  }

  get apps() {
    return this.menuService.getApps();
  }

  get collapseLabel() {
    return this.isCollapsed ? this.labels.expand : this.labels.collapse;
  }

  getChildren(menu) {
    return getVisibleChildren(this.menuService.getMenuAsTree(menu.id));
  }

  hasChildren(menu) {
    return this.getChildren(menu).length > 0;
  }

  isExpanded(menu) {
    return Boolean(this.state.expanded[menu.id]);
  }

  isCurrentApp(app) {
    return app.id === this.state.currentAppId;
  }

  /** aria-current of an action: "page" if it opens the displayed action,
   * "true" if it is only kept as the context of the displayed page. */
  getAriaCurrent(menu) {
    if (menu.id !== this.state.activeMenuId) {
      return false;
    }
    return this.state.activeIsExact ? "page" : "true";
  }

  getAppIcon(app) {
    return getAppIcon(app);
  }

  getMenuHref(menu) {
    return `/odoo/${menu.actionPath || "action-" + menu.actionID}`;
  }

  getSubmenuId(menu) {
    return `o_erp_sidebar_menu_${menu.id}`;
  }

  // -------------------------------------------------------------------------
  // Active menu
  // -------------------------------------------------------------------------

  /**
   * Marks as active the menu of the current app whose action is displayed
   * (the last one chosen in the sidebar if several open the same action) and
   * unfolds the current app (folding the others) and the sections leading to
   * it. When the displayed action has no menu (e.g. a smart button), the
   * previous active menu of the same app is kept as context.
   */
  syncWithCurrentAction() {
    const app = this.menuService.getCurrentApp();
    if (!app) {
      return;
    }
    const appChanged = app.id !== this.state.currentAppId;
    this.state.currentAppId = app.id;
    const controller = this.actionService.currentController;
    const actionId = controller && controller.action && controller.action.id;
    const leaves = getLeaves(this.menuService.getMenuAsTree(app.id));
    const matches = leaves.filter(({menu}) => actionId && menu.actionID === actionId);
    let active =
      matches.find(({menu}) => menu.id === this.sidebarState.lastMenuId) || matches[0];
    this.state.activeIsExact = Boolean(active);
    if (!active) {
      active = leaves.find(({menu}) => menu.id === this.state.activeMenuId);
    }
    this.state.activeMenuId = active ? active.menu.id : null;
    if (appChanged) {
      this.expandOnlyApp(app.id);
    }
    if (active) {
      for (const ancestor of active.ancestors) {
        this.state.expanded[ancestor.id] = true;
      }
    }
  }

  /** Accordion: unfold one app and fold the other ones. */
  expandOnlyApp(appId) {
    for (const app of this.apps) {
      this.state.expanded[app.id] = app.id === appId;
    }
  }

  // -------------------------------------------------------------------------
  // Handlers
  // -------------------------------------------------------------------------

  toggleApp(app) {
    if (this.isExpanded(app)) {
      this.state.expanded[app.id] = false;
    } else {
      this.expandOnlyApp(app.id);
    }
  }

  toggleMenu(menu) {
    this.state.expanded[menu.id] = !this.isExpanded(menu);
  }

  toggleCollapsed() {
    this.sidebar.toggleCollapsed();
  }

  closeDrawer() {
    this.sidebar.closeDrawer();
  }

  /**
   * Icons-only mode: opens (or closes) the popover with the submenus of an
   * app next to its icon.
   */
  toggleFlyout(ev, app) {
    if (this.flyout.isOpen && this.state.flyoutAppId === app.id) {
      this.flyout.close();
      return;
    }
    this.flyoutTarget = ev.currentTarget;
    this.state.flyoutAppId = app.id;
    this.flyout.open(ev.currentTarget, {
      app,
      title: app.name,
      getChildren: (menu) => this.getChildren(menu),
      getMenuHref: (menu) => this.getMenuHref(menu),
      getAriaCurrent: (menu) => this.getAriaCurrent(menu),
      onSelect: (selectEv, menu) => this.onFlyoutSelect(selectEv, menu),
    });
  }

  onFlyoutClosed() {
    this.state.flyoutAppId = null;
    const target = this.flyoutTarget;
    this.flyoutTarget = null;
    if (!target) {
      return;
    }
    // Focus back on the app icon unless the user moved it elsewhere (the
    // popover is closed on click away). Deferred: the popover (which may
    // still hold the focus) is removed after this callback.
    browser.setTimeout(() => {
      const active = document.activeElement;
      const lost =
        !active ||
        active === document.body ||
        !active.isConnected ||
        Boolean(active.closest(".o_erp_sidebar_flyout_popover"));
      if (target.isConnected && lost) {
        target.focus();
      }
    }, 0);
  }

  async onFlyoutSelect(ev, menu) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
      return;
    }
    ev.preventDefault();
    this.flyout.close();
    this.sidebarState.lastMenuId = menu.id;
    await this.menuService.selectMenu(menu);
  }

  /**
   * Opens a menu (app without submenus or action).
   * Ctrl/Cmd/Shift + click keep the browser behavior (new tab/window).
   */
  async onMenuClick(ev, menu) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
      return;
    }
    ev.preventDefault();
    this.sidebarState.lastMenuId = menu.id;
    if (this.isDrawerOpen) {
      this.closeDrawer();
    }
    await this.menuService.selectMenu(menu);
  }

  onLogoClick(ev) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
      return;
    }
    ev.preventDefault();
    if (this.isDrawerOpen) {
      this.closeDrawer();
    }
    this.env.bus.trigger("WEBCLIENT:LOAD_DEFAULT_APP");
  }

  /** "Skip to content": focus the work area of the current action. */
  onSkipToContent(ev) {
    ev.preventDefault();
    const target =
      document.querySelector(".o_action_manager .o_action .o_content") ||
      document.querySelector(".o_action_manager");
    if (!target) {
      return;
    }
    if (!target.hasAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
    }
    target.focus();
  }

  /** Focus trap of the overlay panel (Tab / Shift+Tab cycle inside). */
  onKeydown(ev) {
    if (!this.isDrawerOpen || ev.key !== "Tab" || !this.root.el) {
      return;
    }
    const tabable = getTabableElements(this.root.el);
    if (!tabable.length) {
      return;
    }
    const first = tabable[0];
    const last = tabable[tabable.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
      ev.preventDefault();
      first.focus();
    }
  }
}

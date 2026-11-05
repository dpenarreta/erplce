import {Component, onMounted, useRef} from "@odoo/owl";

/**
 * Popover with the submenus of an app, used by the sidebar in icons-only
 * mode (US-018). Sections are headings, actions are links; the first link
 * gets the focus when it opens, Escape closes it (popover service) and the
 * sidebar puts the focus back on the app icon.
 */
export class ErpSidebarFlyout extends Component {
  static template = "erp_theme.SidebarFlyout";
  static props = {
    app: Object,
    title: String,
    getChildren: Function,
    getMenuHref: Function,
    getAriaCurrent: Function,
    onSelect: Function,
    close: Function,
  };

  setup() {
    this.root = useRef("root");
    onMounted(() => {
      const link =
        this.root.el &&
        (this.root.el.querySelector("[aria-current]") ||
          this.root.el.querySelector("a"));
      if (link) {
        link.focus();
      }
    });
  }

  onKeydown(ev) {
    if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      this.props.close();
    }
  }
}

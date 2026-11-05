// Loaded first so that super.mailLayout() is the mail implementation.
import "@mail/chatter/web/form_renderer";
import {useState} from "@odoo/owl";
import {browser} from "@web/core/browser/browser";
import {MEDIAS_BREAKPOINTS, SIZES} from "@web/core/ui/ui_service";
import {patch} from "@web/core/utils/patch";
import {FormController} from "@web/views/form/form_controller";
import {FormRenderer} from "@web/views/form/form_renderer";

export const SIDEBAR_WIDTH = 240;
export const SIDEBAR_COLLAPSED_WIDTH = 64;
// Width from which Odoo puts the chatter on the side (XXL, 1534 px).
export const SIDE_CHATTER_MIN_WIDTH = MEDIAS_BREAKPOINTS[SIZES.XXL].minWidth;
// Layouts with the chatter on the side -> same layout with it at the bottom.
export const BOTTOM_LAYOUTS = {
  SIDE_CHATTER: "BOTTOM_CHATTER",
  EXTERNAL_COMBO_XXL: "EXTERNAL_COMBO",
  COMBO: "BOTTOM_CHATTER",
};
const XXL_CLASS = "o_xxl_form_view h-100";

/**
 * Chatter next to the form, taking the ERP LCE sidebar into account (US-018).
 *
 * Odoo decides "chatter on the side" from the WINDOW width (XXL, >= 1534 px):
 * mail's FormRenderer.mailLayout() and the "o_xxl_form_view" class of the
 * FormController (row layout). The fixed sidebar takes 240 px (64 px
 * collapsed) of that width: at 1536 px the form and the chatter would be
 * squeezed into 1296 px. Both are downgraded to the non-XXL behavior (chatter
 * below the form) while the useful width (window minus sidebar) is under the
 * threshold.
 */
export function getSidebarWidth(sidebarState, uiSize) {
  if (
    !sidebarState ||
    uiSize < SIZES.LG ||
    !document.body.classList.contains("o_erp_theme_has_sidebar")
  ) {
    return 0;
  }
  return sidebarState.collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH;
}

export function isUsefulWidthBelowXxl(windowWidth, sidebarWidth) {
  return Boolean(sidebarWidth) && windowWidth - sidebarWidth < SIDE_CHATTER_MIN_WIDTH;
}

/**
 * @param {string} layout layout computed by mail
 * @param {number} windowWidth
 * @param {number} sidebarWidth 0 when there is no sidebar on the side
 */
export function adaptMailLayout(layout, windowWidth, sidebarWidth) {
  if (
    !(layout in BOTTOM_LAYOUTS) ||
    !isUsefulWidthBelowXxl(windowWidth, sidebarWidth)
  ) {
    return layout;
  }
  return BOTTOM_LAYOUTS[layout];
}

function useSidebarState(env) {
  const sidebar = env.services.erp_theme_sidebar;
  // Read during the render: toggling "collapse" re-renders the form.
  return sidebar ? useState(sidebar.state) : null;
}

/**
 * "ui" service seen by the form renderer: same object, but its size is XL
 * instead of XXL while the useful width is under the XXL threshold. The form
 * compiler (row/column layout of the renderer) and mail's mailLayout() both
 * read __comp__.uiService.size, so they follow the useful width.
 */
export function makeEffectiveUi(ui, sidebarState) {
  return Object.create(ui, {
    size: {
      get() {
        const size = ui.size;
        if (size < SIZES.XXL) {
          return size;
        }
        const sidebarWidth = getSidebarWidth(sidebarState, size);
        return isUsefulWidthBelowXxl(browser.innerWidth, sidebarWidth)
          ? SIZES.XL
          : size;
      },
    },
  });
}

patch(FormRenderer.prototype, {
  setup() {
    super.setup(...arguments);
    this.erpSidebarState = useSidebarState(this.env);
    if (this.uiService && this.erpSidebarState) {
      this.uiService = makeEffectiveUi(this.uiService, this.erpSidebarState);
    }
  },

  mailLayout() {
    // Safety net if another module replaces uiService after this setup.
    const layout = super.mailLayout(...arguments);
    const sidebarWidth = getSidebarWidth(this.erpSidebarState, this.uiService.size);
    return adaptMailLayout(layout, browser.innerWidth, sidebarWidth);
  },
});

patch(FormController.prototype, {
  setup() {
    super.setup(...arguments);
    this.erpSidebarState = useSidebarState(this.env);
  },

  get className() {
    const result = super.className;
    if (result[XXL_CLASS]) {
      const sidebarWidth = getSidebarWidth(this.erpSidebarState, this.ui.size);
      if (isUsefulWidthBelowXxl(browser.innerWidth, sidebarWidth)) {
        delete result[XXL_CLASS];
      }
    }
    return result;
  },
});

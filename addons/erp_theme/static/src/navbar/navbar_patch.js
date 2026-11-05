import {useState} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";
import {useService} from "@web/core/utils/hooks";
import {NavBar} from "@web/webclient/navbar/navbar";

/**
 * Top bar (US-018): the apps grid button and the section menus are replaced
 * by the sidebar (see navbar_patch.xml); on screens < 992 px a hamburger
 * button opens the sidebar as an overlay panel.
 */
patch(NavBar.prototype, {
  setup() {
    super.setup(...arguments);
    this.erpSidebar = useService("erp_theme_sidebar");
    this.erpSidebarState = useState(this.erpSidebar.state);
    this.erpSidebarLabels = {open: _t("Open menu")};
  },

  onErpSidebarToggle(ev) {
    this.erpSidebar.openDrawer(ev.currentTarget);
  },
});

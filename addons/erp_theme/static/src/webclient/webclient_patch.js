import {patch} from "@web/core/utils/patch";
import {WebClient} from "@web/webclient/webclient";
import {ErpSidebar} from "../sidebar/sidebar";

/**
 * Web client (US-018): the ERP LCE sidebar is rendered next to the top bar
 * (see webclient_patch.xml), so it is hidden too in fullscreen actions.
 */
patch(WebClient, {
  components: {...WebClient.components, ErpSidebar},
});

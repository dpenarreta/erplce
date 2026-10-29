import {patch} from "@web/core/utils/patch";
import {session} from "@web/session";
import {titleService} from "@web/core/browser/title_service";

/**
 * Browser tab title: "<page> - <brand>" (or only "<brand>" when no page part
 * is set) instead of the core default "Odoo".
 * The brand name comes from session_info.erp_brand_name (ir.http.session_info,
 * system parameter "erp_branding.name").
 */
export const BRAND_TITLE_PART = "erp_branding";
export const DEFAULT_BRAND_NAME = "ERP LCE";

export function getBrandName() {
  return session.erp_brand_name || DEFAULT_BRAND_NAME;
}

patch(titleService, {
  start() {
    const service = super.start(...arguments);
    const brandName = getBrandName();
    const setParts = service.setParts;
    const getParts = service.getParts;

    // Re-add the brand part last so it always stays at the end of the title.
    service.setParts = (parts) => {
      setParts({...parts, [BRAND_TITLE_PART]: false});
      setParts({[BRAND_TITLE_PART]: brandName});
    };
    // Callers only see their own parts.
    service.getParts = () => {
      const parts = getParts();
      delete parts[BRAND_TITLE_PART];
      return parts;
    };
    service.setParts({});
    return service;
  },
});

"""US-018: ERP LCE theme (sidebar, light top bar, cards, typography)."""

import copy
import re

from lxml import etree

from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import file_open

from odoo.addons.erp_branding.tests.css_audit import (
    contrast,
    custom_property_values,
    find_contrast_issues,
    parse_color,
    parse_rgba,
    parse_rules,
    resolve_declarations,
    resolve_value,
)

from .theme_audit import (
    LIGHT_SURFACES,
    audit_flyout,
    audit_navbar,
    audit_sidebar,
    audit_sidebar_icons,
    audit_status_colors,
    solid,
)

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
YELLOW = (252, 226, 0)
CHATTER_BG = (248, 249, 250)  # gray-100, background of the chatter
OWN_PREFIX = "/erp_theme/static/src/"


def _backend_bundle(env, css=True, js=False):
    return env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=js, css=css)


def _declarations(css, target):
    declarations, rules = resolve_declarations(css, target)
    root = custom_property_values(rules)
    return {k: resolve_value(v, declarations, root) for k, v in declarations.items()}


@tagged("post_install", "-at_install")
class TestThemeAssets(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bundle = _backend_bundle(cls.env, css=True, js=True)
        cls.bundle = bundle
        cls.css = bundle.preprocess_css()
        cls.css_errors = list(bundle.css_errors)

    def test_module_installed(self):
        module = self.env["ir.module.module"].search([("name", "=", "erp_theme")])
        self.assertEqual(module.state, "installed")
        self.assertFalse(module.application)
        self.assertEqual(
            set(module.dependencies_id.mapped("name")), {"web", "mail", "erp_branding"}
        )

    def test_assets_registered(self):
        """SCSS, JS and XML of the theme are in the backend bundle and the
        SCSS compiles without errors."""
        self.assertFalse(self.css_errors, self.css_errors)
        js_urls = [asset.url for asset in self.bundle.javascripts]
        xml_urls = [asset.url for asset in self.bundle.templates]
        css_urls = [asset.url for asset in self.bundle.stylesheets]
        for name in (
            "sidebar/sidebar_service.js",
            "sidebar/sidebar.js",
            "sidebar/sidebar_flyout.js",
            "form/form_renderer_patch.js",
            "navbar/navbar_patch.js",
            "webclient/webclient_patch.js",
        ):
            self.assertIn(OWN_PREFIX + name, js_urls)
        for name in (
            "sidebar/sidebar.xml",
            "navbar/navbar_patch.xml",
            "webclient/webclient_patch.xml",
        ):
            self.assertIn(OWN_PREFIX + name, xml_urls)
        for name in ("scss/fonts.scss", "scss/theme.scss", "sidebar/sidebar.scss"):
            self.assertIn(OWN_PREFIX + name, css_urls)

    def test_javascript_transpiles(self):
        """The ES modules of the theme are transpiled to odoo.define()."""
        own = [a for a in self.bundle.javascripts if a.url.startswith(OWN_PREFIX)]
        self.assertEqual(len(own), 6)
        for asset in own:
            with self.subTest(asset=asset.url):
                code = asset.minify()
                self.assertIn("odoo.define(", code)
                self.assertNotIn("throw new Error", code)

    def _templates(self):
        """{name: element} of the primary templates and [(parent, element)]
        of the theme extensions."""
        primary = {}
        extensions = []
        for block in self.bundle.xml():
            if block["type"] == "templates":
                for element, _url, _inherit in block["templates"]:
                    primary[element.get("t-name")] = element
            else:
                for parent, elements in block["extensions"].items():
                    for element, url in elements:
                        if url.startswith(OWN_PREFIX):
                            extensions.append((parent, element))
        return primary, extensions

    def test_templates_and_patches(self):
        """The sidebar templates exist and every xpath of the theme matches
        exactly one node of the core template it extends (the client applies
        them at runtime: a broken xpath would only fail in the browser)."""
        primary, extensions = self._templates()
        for name in (
            "erp_theme.Sidebar",
            "erp_theme.Sidebar.AppIcon",
            "erp_theme.Sidebar.MenuItem",
            "erp_theme.SidebarFlyout",
            "erp_theme.SidebarFlyout.Item",
        ):
            self.assertIn(name, primary)
        self.assertEqual(
            sorted(parent for parent, _element in extensions),
            ["web.NavBar", "web.WebClient"],
        )
        for parent, element in extensions:
            core = etree.ElementTree(copy.deepcopy(primary[parent]))
            for xpath in element.iter("xpath"):
                with self.subTest(template=parent, expr=xpath.get("expr")):
                    self.assertEqual(len(core.xpath(xpath.get("expr"))), 1)

        sidebar = etree.tostring(primary["erp_theme.Sidebar"], encoding="unicode")
        # CA-5: navigation landmark, disclosure state, current page.
        self.assertIn('<nav id="o_erp_sidebar"', sidebar)
        self.assertIn('t-att-aria-label="labels.mainMenu"', sidebar)
        self.assertIn("aria-expanded", sidebar)
        self.assertIn("toggleCollapsed", sidebar)
        # M4 / M6: modal panel container and "skip to content" link.
        container = primary["erp_theme.Sidebar"].find(
            ".//div[@class='o_erp_sidebar_container']"
        )
        self.assertIsNotNone(container)
        self.assertIn("'dialog'", container.get("t-att-role"))
        self.assertIn("'true'", container.get("t-att-aria-modal"))
        self.assertIn("t-att-aria-modal", sidebar)
        self.assertIn("o_erp_skip_link visually-hidden-focusable", sidebar)
        # M3: icons-only mode opens the submenus in a popover.
        self.assertIn("toggleFlyout", sidebar)
        self.assertIn("'o_erp_sidebar_flyout' : false", sidebar)
        self.assertNotIn("aria-haspopup", sidebar)
        item = etree.tostring(primary["erp_theme.Sidebar.MenuItem"], encoding="unicode")
        self.assertIn("getAriaCurrent(menu)", item)
        with file_open("erp_theme/static/src/sidebar/sidebar.js") as js_file:
            self.assertIn('this.state.activeIsExact ? "page" : "true"', js_file.read())
        # CA-2 / CA-4: apps grid and section menus not rendered; hamburger.
        navbar = dict(extensions)["web.NavBar"]
        navbar_xml = etree.tostring(navbar, encoding="unicode")
        self.assertEqual(
            navbar_xml.count('<attribute name="t-if">false</attribute>'), 2
        )
        self.assertIn("o_erp_sidebar_toggle d-lg-none", navbar_xml)
        self.assertIn("erpSidebarLabels.open", navbar_xml)

    def test_font_files(self):
        """CA-7: Inter hosted in the module (no CDN) with its OFL license."""
        with file_open("erp_theme/static/fonts/InterVariable.woff2", "rb") as font:
            self.assertEqual(font.read(4), b"wOF2")
        with file_open("erp_theme/static/fonts/LICENSE.txt") as license_file:
            self.assertIn("SIL Open Font License", license_file.read())
        self.assertIn("/erp_theme/static/fonts/InterVariable.woff2", self.css)
        self.assertNotRegex(self.css, r"fonts\.(googleapis|gstatic)\.com")
        body = _declarations(self.css, "body.o_web_client")
        self.assertTrue(body["font-family"].startswith('"Inter"'), body["font-family"])
        self.assertIn("system-ui", body["font-family"])


@tagged("post_install", "-at_install")
class TestThemeContrast(TransactionCase):
    """CA-8 / CA-9: measured contrast of the sidebar, the top bar, the work
    area and the cards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bundle = _backend_bundle(cls.env)
        cls.css = bundle.preprocess_css()
        assert not bundle.css_errors, bundle.css_errors

    def test_sidebar_contrast(self):
        surfaces, issues = audit_sidebar(self.css)
        self.assertIn(BLACK, surfaces)
        self.assertGreaterEqual(len(surfaces), 3, surfaces)  # base, hover, active
        self.assertFalse(issues, "\n".join(map(str, issues)))

    def test_sidebar_states(self):
        """Normal, hover, active and focus states with the brand colors."""
        base = _declarations(self.css, ".o_erp_sidebar")
        self.assertEqual(parse_color(base["background-color"]), BLACK)
        text = parse_color(base["color"])
        self.assertGreaterEqual(contrast(text, BLACK), 4.5)

        active = _declarations(self.css, ".o_erp_sidebar_link.o_erp_sidebar_active")
        active_bg = parse_color(active["background-color"])
        active_text = parse_color(active["color"])
        self.assertGreaterEqual(contrast(active_text, active_bg), 4.5)
        indicator = _declarations(
            self.css, ".o_erp_sidebar_link.o_erp_sidebar_active::before"
        )
        self.assertEqual(parse_color(indicator["background-color"]), YELLOW)
        self.assertGreaterEqual(contrast(YELLOW, active_bg), 3)

        hover = _declarations(self.css, ".o_erp_sidebar_link:hover")
        hover_bg = parse_color(hover["background-color"])
        self.assertGreaterEqual(contrast(parse_color(hover["color"]), hover_bg), 4.5)

        focus = _declarations(self.css, ".o_erp_sidebar a:focus-visible")
        outline = parse_color(focus["outline"].split("solid", 1)[1])
        self.assertEqual(outline, YELLOW)
        for bg in (BLACK, hover_bg, active_bg):
            self.assertGreaterEqual(contrast(outline, bg), 3)

    def test_navbar_light_and_contrast(self):
        """CA-2: light top bar; every text >= 4.5:1, focus outline >= 3:1."""
        navbar = _declarations(self.css, ".o_main_navbar")
        background = solid(navbar["background"])
        self.assertEqual(background, WHITE)
        hover_bg = solid("#ededed")
        issues = audit_navbar(self.css, background, hover_bg)
        self.assertFalse(issues, "\n".join(map(str, issues)))
        toggle = _declarations(self.css, ".o_main_navbar .o_erp_sidebar_toggle")
        self.assertEqual(toggle["width"], "44px")
        self.assertEqual(toggle["height"], "44px")
        self.assertGreaterEqual(contrast(parse_color(toggle["color"]), background), 4.5)

    def test_work_area_and_cards(self):
        """CA-6: neutral light gray work area; white rounded cards; text and
        muted text readable on the work area."""
        body = _declarations(self.css, "body.o_web_client")
        surface = parse_color(body["background-color"])
        self.assertTrue(surface[0] == surface[1] == surface[2], surface)
        self.assertGreater(surface[0], 230)
        root = custom_property_values(parse_rules(self.css))
        body_text = parse_color(root.get("--body-color"))
        muted = parse_rgba(_declarations(self.css, ".text-muted")["color"])
        self.assertEqual(muted[1], 1.0)
        for color in (body_text, muted[0]):
            self.assertGreaterEqual(contrast(color, surface), 4.5)

        list_card = _declarations(
            self.css,
            "body.o_web_client .o_action_manager .o_list_view > .o_content"
            " > .o_list_renderer",
        )
        search_card = _declarations(
            self.css, "body.o_web_client .o_action_manager .o_content > .o_search_panel"
        )
        for card in (list_card, search_card):
            self.assertEqual(parse_color(card["background-color"]), WHITE)
            self.assertIn("box-shadow", card)
            self.assertGreaterEqual(int(card["border-radius"].rstrip("px")), 8)
        sheet = _declarations(
            self.css, "body.o_web_client .o_action_manager .o_form_view .o_form_sheet"
        )
        # parse_rules() lowercases property names.
        self.assertEqual(sheet["--formview-sheet-border-radius-md"], "12px")

    def test_chatter_follow_contrast(self):
        """CA-9 (pending from US-017): every state of the follow button
        ("Follow", "Following", hover "Unfollow") >= 4.5:1, and the mail
        template still uses the classes these rules target."""
        with file_open("mail/static/src/chatter/web/chatter.xml") as template:
            chatter_xml = template.read()
        for needle in (
            "o-mail-Chatter-topbar",
            "o-mail-Chatter-follow btn btn-link  px-0 text-600",
            "'text-success': !unfollowHover.isHover",
            "'text-warning': unfollowHover.isHover",
        ):
            self.assertIn(needle, chatter_xml)
        found, issues = audit_status_colors(self.css)
        for status in (".text-success", ".text-warning", ".text-danger"):
            selector = f".o_web_client .o-mail-Chatter-topbar {status}"
            self.assertIn(selector, found)
            self.assertTrue(found[selector][1], f"{selector} must be !important")
        self.assertFalse(issues, "\n".join(map(str, issues)))
        declarations, _rules = resolve_declarations(
            self.css, ".o_web_client .o-mail-Chatter-follow.text-600"
        )
        self.assertIn(
            "!important", self._raw(".o_web_client .o-mail-Chatter-follow.text-600")
        )
        color = parse_color(declarations["color"])
        surface = parse_color(
            _declarations(self.css, "body.o_web_client")["background-color"]
        )
        for bg in (CHATTER_BG, WHITE, surface):
            self.assertGreaterEqual(contrast(color, bg), 4.5, f"{color} on {bg}")

    def test_smart_buttons_status_colors(self):
        """A1: status colors of the smart buttons (control panel, gray
        surface) >= 4.5:1 on every light surface; white card background."""
        found, issues = audit_status_colors(self.css)
        for status in (".text-success", ".text-warning", ".text-danger"):
            selector = f".o_web_client .o-form-buttonbox {status}"
            self.assertIn(selector, found)
            self.assertTrue(found[selector][1], f"{selector} must be !important")
        self.assertFalse(issues, "\n".join(map(str, issues)))
        # Only the buttons are white (not the box nor the "More" wrapper).
        box = _declarations(
            self.css, ".o_web_client .o_control_panel .o-form-buttonbox"
        )
        self.assertNotIn("background-color", box)
        button = _declarations(
            self.css,
            ".o_web_client .o_control_panel .o-form-buttonbox"
            " button.btn.oe_stat_button",
        )
        self.assertEqual(parse_color(button["background-color"]), WHITE)

    def test_chatter_topbar_links_contrast(self):
        """Search, attachments and followers counter of the chatter top bar
        (.text-action) >= 4.5:1 on every light surface; on phones the top bar
        wraps instead of scrolling."""
        selector = ".o_web_client .o-mail-Chatter-topbar .text-action"
        self.assertIn("!important", self._raw(selector))
        color = parse_color(_declarations(self.css, selector)["color"])
        for surface in LIGHT_SURFACES:
            self.assertGreaterEqual(contrast(color, surface), 4.5, f"on {surface}")
        with file_open("mail/static/src/chatter/web/chatter.xml") as template:
            self.assertIn("o-mail-Followers-button btn btn-link", template.read())
        self.assertRegex(
            self.css,
            r"@media \(max-width: 767\.98px\)\s*\{\s*\.o_web_client "
            r"\.o-mail-Chatter-topbar\s*\{[^}]*flex-wrap: wrap",
        )

    def test_mobile_touch_targets(self):
        """Save / discard of an edited form and main control panel buttons
        of at least 44 x 44 px on phones, with a gap between them."""
        buttons = _declarations(
            self.css, "body.o_web_client .o_form_status_indicator_buttons .btn"
        )
        self.assertEqual(buttons["min-width"], "44px")
        self.assertEqual(buttons["min-height"], "44px")
        box = _declarations(
            self.css, "body.o_web_client .o_form_status_indicator_buttons"
        )
        self.assertEqual(box["gap"], "8px")
        kanban = _declarations(
            self.css, "body.o_web_client .o_action_manager .o_kanban_renderer"
        )
        self.assertEqual(kanban["padding-left"], "16px")

    def test_sidebar_icons_and_flyout(self):
        """CA-8: app icon plates stand out on black; popover of the
        icons-only mode readable (text >= 4.5:1, focus and indicator >= 3:1)."""
        surfaces, _issues = audit_sidebar(self.css)
        plates, issues = audit_sidebar_icons(self.css, surfaces)
        self.assertTrue(plates)
        self.assertFalse(issues, "\n".join(map(str, issues)))
        issues = audit_flyout(self.css)
        self.assertFalse(issues, "\n".join(map(str, issues)))
        active = _declarations(
            self.css, ".o_erp_sidebar_flyout_link.o_erp_sidebar_flyout_active"
        )
        self.assertEqual(parse_color(active["background-color"]), YELLOW)
        self.assertEqual(parse_color(active["color"]), BLACK)
        bar = _declarations(
            self.css, ".o_erp_sidebar_flyout_link.o_erp_sidebar_flyout_active::before"
        )
        self.assertGreaterEqual(
            contrast(parse_color(bar["background-color"]), WHITE), 3
        )
        skip = _declarations(self.css, ".o_erp_skip_link:focus")
        self.assertGreaterEqual(
            contrast(parse_color(skip["color"]), parse_color(skip["background-color"])),
            4.5,
        )

    def test_search_panel_selection_brand(self):
        """M5: selected value of the search panel with the brand gray."""
        panel = _declarations(self.css, ".o_web_client .o_search_panel .list-group")
        bg = parse_color(panel["--list-group-active-bg"])
        text = parse_color(panel["--list-group-active-color"])
        self.assertEqual(bg, (225, 225, 225))
        self.assertGreaterEqual(contrast(text, bg), 4.5)
        self.assertNotIn(bg, LIGHT_SURFACES)  # visible on the white panel

    def _raw(self, selector):
        pattern = re.escape(selector) + r"\s*\{([^}]*)\}"
        match = re.search(pattern, self.css)
        return match.group(1) if match else ""

    def test_no_light_yellow_text_in_theme(self):
        """Never light-yellow text on light backgrounds in the theme rules."""
        issues = find_contrast_issues(
            self.css,
            lambda selector: "o_erp_" in selector
            or selector.startswith("body.o_web_client"),
        )
        self.assertFalse(issues, "\n".join(" | ".join(issue) for issue in issues))


@tagged("post_install", "-at_install")
class TestThemeHttp(HttpCase):
    def test_web_client_loads_theme_bundle(self):
        """The web client page loads and its JS bundle contains the sidebar
        templates, the patches and no template error."""
        self.authenticate("admin", "admin")
        response = self.url_open("/odoo")
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'src="(/web/assets/[^"]*web\.assets_web[^"]*\.js)"', response.text
        )
        self.assertTrue(match, "web.assets_web script not found")
        bundle = self.url_open(match.group(1), timeout=120)
        self.assertEqual(bundle.status_code, 200)
        js = bundle.text
        self.assertIn('registerTemplate("erp_theme.Sidebar"', js)
        self.assertIn('registerTemplateExtension("web.NavBar", `/erp_theme/', js)
        self.assertIn('registerTemplateExtension("web.WebClient", `/erp_theme/', js)
        self.assertIn("@erp_theme/sidebar/sidebar_service", js)
        self.assertNotIn("Missing (extension) parent templates", js)

    def test_spanish_translations(self):
        """New texts translated to Spanish (es_EC falls back on es.po)."""
        self.env["res.lang"]._activate_lang("es_EC")
        response = self.url_open(
            "/web/webclient/translations/1?mods=erp_theme&lang=es_EC"
        )
        self.assertEqual(response.status_code, 200)
        messages = {
            m["id"]: m["string"]
            for m in response.json()["modules"]["erp_theme"]["messages"]
        }
        self.assertEqual(messages.get("Main menu"), "Menú principal")
        self.assertEqual(messages.get("Open menu"), "Abrir menú")
        self.assertEqual(messages.get("Collapse menu"), "Contraer menú")

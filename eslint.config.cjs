// ESLint 9 (flat config) para el JS propio de los módulos Odoo 18 (OWL, módulos ES).
// Lo ejecuta pre-commit (scripts/check.sh) con versiones fijadas en
// .pre-commit-config.yaml: eslint@9.39.5, @eslint/js@9.39.5, globals@16.5.0.
//
// - sourceType "module": Odoo 18 transpila los módulos ES de static/src.
// - Los imports "@web/...", "@odoo/owl", "@mail/..." son alias del bundler de
//   Odoo: ESLint core no resuelve imports, así que no hace falta configurarlos
//   (no se usa eslint-plugin-import).
// - Globals: navegador + los que el cliente web de Odoo expone en window.
const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
    {
        ignores: ["**/static/lib/**", "**/static/src/lib/**"],
    },
    {
        files: ["addons/**/static/src/**/*.js"],
        ...js.configs.recommended,
        languageOptions: {
            ecmaVersion: 2024,
            sourceType: "module",
            globals: {
                ...globals.browser,
                odoo: "readonly",
                owl: "readonly",
                luxon: "readonly",
                Chart: "readonly",
            },
        },
        rules: {
            ...js.configs.recommended.rules,
            "no-console": "warn",
            "no-debugger": "error",
            "no-eval": "error",
            "no-implied-eval": "error",
            "no-var": "error",
            "prefer-const": "warn",
            eqeqeq: ["error", "smart"],
            // Los parámetros no usados son habituales en overrides/patch de OWL.
            "no-unused-vars": ["error", {args: "none"}],
        },
    },
];

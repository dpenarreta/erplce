/** @type {import('prettier').Config} */
// Configuración de prettier estilo OCA (rama 18.0), usada por pre-commit.
const config = {
  plugins: [require.resolve("@prettier/plugin-xml")],
  bracketSpacing: false,
  printWidth: 88,
  proseWrap: "always",
  semi: true,
  trailingComma: "es5",
  xmlWhitespaceSensitivity: "preserve",
};

module.exports = config;

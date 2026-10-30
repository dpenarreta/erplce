import {unaccent} from "@web/core/utils/strings";

/**
 * Lógica pura de la entrada "Sin instructor" del desplegable del Instructor
 * (US-010). Sin dependencias de OWL para poder probarla de forma aislada
 * (static/tests/coach_no_coach_options.test.js).
 */

/**
 * Texto comparable: sin tildes, en minúsculas y con espacios normalizados.
 * @param {String} text
 * @returns {String}
 */
export function normalizeSearchText(text) {
  return unaccent(String(text || ""), false)
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * ¿El texto buscado coincide por inicio de palabra con la etiqueta?
 * "sin", "instr" o "sin inst" coinciden con "Sin instructor"; "structor" no.
 * @param {String} label
 * @param {String} request
 * @returns {Boolean}
 */
export function matchesWordStart(label, request) {
  const query = normalizeSearchText(request);
  if (!query) {
    return true;
  }
  const words = normalizeSearchText(label).split(" ");
  return words.some((_word, index) => words.slice(index).join(" ").startsWith(query));
}

/**
 * Inserta la entrada "Sin instructor" en las opciones del autocompletado.
 *
 * Siempre al final de la lista (US-017, CA-7; sustituye la regla de US-010
 * que la ponía primera con la búsqueda vacía): después de los empleados, de
 * "Buscar más..." y de las opciones de crear. Así nunca es la primera opción
 * activa y Tab/Intro al abrir el campo no la selecciona.
 *
 * - Con texto: solo aparece si coincide por inicio de palabra ("sin",
 *   "instr").
 * - Si no hay ninguna otra opción, va precedida de ``noResultOption`` (no
 *   seleccionable, "Sin registros"), para que tampoco entonces sea la
 *   primera opción activa.
 *
 * @param {Object[]} options opciones del núcleo (los empleados llevan ``value``)
 * @param {Object} noCoachOption entrada "Sin instructor" (con ``label``)
 * @param {Object} params
 * @param {String} [params.request] texto escrito
 * @param {Object} [params.noResultOption] línea no seleccionable para una
 *   lista sin otras opciones
 * @returns {Object[]}
 */
export function insertNoCoachOption(
  options,
  noCoachOption,
  {request = "", noResultOption = null} = {}
) {
  const hasRequest = Boolean(normalizeSearchText(request));
  if (hasRequest && !matchesWordStart(noCoachOption.label, request)) {
    return options;
  }
  const result = [...options];
  if (!result.length && noResultOption) {
    result.push(noResultOption);
  }
  result.push(noCoachOption);
  return result;
}

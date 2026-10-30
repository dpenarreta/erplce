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
 * - Búsqueda vacía y campo sin instructor (CA-1): primera.
 * - Búsqueda vacía y campo con instructor: al final, para que Tab/Intro sobre
 *   la primera opción activa no marque "Sin instructor".
 * - Con texto: solo si coincide por inicio de palabra, y después de los
 *   empleados (así "in" + Tab elige "Inés", no "Sin instructor").
 *
 * Cuando la entrada aparece, se quita "Sin resultados" (sobraría).
 *
 * @param {Object[]} options opciones del núcleo (los empleados llevan ``value``)
 * @param {Object} noCoachOption entrada "Sin instructor" (con ``label``)
 * @param {Object} params
 * @param {String} [params.request] texto escrito
 * @param {Boolean} [params.hasValue] el campo ya tiene instructor
 * @returns {Object[]}
 */
export function insertNoCoachOption(
  options,
  noCoachOption,
  {request = "", hasValue = false} = {}
) {
  const hasRequest = Boolean(normalizeSearchText(request));
  if (hasRequest && !matchesWordStart(noCoachOption.label, request)) {
    return options;
  }
  const result = options.filter(
    (option) => !(option.classList || "").includes("o_m2o_no_result")
  );
  if (!hasRequest) {
    return hasValue ? [...result, noCoachOption] : [noCoachOption, ...result];
  }
  let lastRecord = -1;
  result.forEach((option, index) => {
    if ("value" in option) {
      lastRecord = index;
    }
  });
  result.splice(lastRecord + 1, 0, noCoachOption);
  return result;
}

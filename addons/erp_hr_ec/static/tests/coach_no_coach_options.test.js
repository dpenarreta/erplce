import {describe, expect, test} from "@odoo/hoot";
import {
  insertNoCoachOption,
  matchesWordStart,
  normalizeSearchText,
} from "@erp_hr_ec/fields/coach_many2one/coach_no_coach_options";

/**
 * US-010 / US-017 (CA-7): posición de la entrada "Sin instructor" en el
 * desplegable del Instructor: siempre al final. Se ejecuta en /web/tests
 * (hoot, requiere navegador).
 */
describe.current.tags("headless");

const NO_COACH = {label: "Sin instructor", erpNoCoach: true};
const INES = {value: 1, label: "Inés Andrade"};
const MARINA = {value: 2, label: "Marina Insuasti"};
const SEARCH_MORE = {
  label: "Buscar más...",
  classList: "o_m2o_dropdown_option o_m2o_dropdown_option_search_more",
};
const CREATE = {
  label: 'Crear "sin"',
  classList: "o_m2o_dropdown_option o_m2o_dropdown_option_create",
};
const NO_RESULT = {label: "Sin registros", classList: "o_m2o_no_result"};

function labels(options) {
  return options.map((option) => option.label);
}

test("normaliza tildes, mayúsculas y espacios", () => {
  expect(normalizeSearchText("  SÍN   Instrúctor ")).toBe("sin instructor");
  expect(normalizeSearchText(undefined)).toBe("");
});

test("coincide solo por inicio de palabra", () => {
  for (const text of ["sin", "Sín", "instr", "INSTRUCTOR", "sin inst", "in"]) {
    expect(matchesWordStart("Sin instructor", text)).toBe(true, {message: text});
  }
  for (const text of ["structor", "ines", "sin x", "n instructor"]) {
    expect(matchesWordStart("Sin instructor", text)).toBe(false, {message: text});
  }
});

const NO_RESULT_PLACEHOLDER = {
  label: "Sin registros",
  classList: "o_m2o_no_result",
  unselectable: true,
};

test("búsqueda vacía: al final, después de «Buscar más» (US-017 CA-7)", () => {
  const result = insertNoCoachOption([INES, MARINA, SEARCH_MORE], NO_COACH, {
    request: "",
    noResultOption: NO_RESULT_PLACEHOLDER,
  });
  expect(labels(result)).toEqual([
    "Inés Andrade",
    "Marina Insuasti",
    "Buscar más...",
    "Sin instructor",
  ]);
  // Tab/Intro al abrir el campo: la primera opción activa es un empleado.
  expect(result[0]).toBe(INES);
});

test("con texto que coincide: al final, después de «Buscar más»", () => {
  const result = insertNoCoachOption([INES, MARINA, SEARCH_MORE], NO_COACH, {
    request: "in",
  });
  expect(labels(result)).toEqual([
    "Inés Andrade",
    "Marina Insuasti",
    "Buscar más...",
    "Sin instructor",
  ]);
  // "in" + Tab: la primera opción sigue siendo un empleado.
  expect(result[0]).toBe(INES);
});

test("sin empleados: «Sin registros» primero, nunca «Sin instructor»", () => {
  expect(labels(insertNoCoachOption([NO_RESULT], NO_COACH, {request: "sin"}))).toEqual([
    "Sin registros",
    "Sin instructor",
  ]);
  expect(labels(insertNoCoachOption([CREATE], NO_COACH, {request: "sin"}))).toEqual([
    'Crear "sin"',
    "Sin instructor",
  ]);
  const empty = insertNoCoachOption([], NO_COACH, {
    request: "",
    noResultOption: NO_RESULT_PLACEHOLDER,
  });
  expect(empty).toEqual([NO_RESULT_PLACEHOLDER, NO_COACH]);
  expect(empty[0].unselectable).toBe(true);
});

test("con texto que no coincide: no aparece", () => {
  const options = [INES, SEARCH_MORE];
  expect(insertNoCoachOption(options, NO_COACH, {request: "ines"})).toBe(options);
  expect(insertNoCoachOption([NO_RESULT], NO_COACH, {request: "zz"})).toEqual([
    NO_RESULT,
  ]);
});

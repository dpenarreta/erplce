import {describe, expect, test} from "@odoo/hoot";
import {
  insertNoCoachOption,
  matchesWordStart,
  normalizeSearchText,
} from "@erp_hr_ec/fields/coach_many2one/coach_no_coach_options";

/**
 * US-010: posición de la entrada "Sin instructor" en el desplegable del
 * Instructor. Se ejecuta en /web/tests (hoot, requiere navegador).
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

test("búsqueda vacía y campo sin instructor: primera (CA-1)", () => {
  const result = insertNoCoachOption([INES, MARINA, SEARCH_MORE], NO_COACH, {
    request: "",
    hasValue: false,
  });
  expect(labels(result)).toEqual([
    "Sin instructor",
    "Inés Andrade",
    "Marina Insuasti",
    "Buscar más...",
  ]);
});

test("búsqueda vacía y campo con instructor: al final", () => {
  const result = insertNoCoachOption([INES, MARINA, SEARCH_MORE], NO_COACH, {
    request: "",
    hasValue: true,
  });
  expect(labels(result)).toEqual([
    "Inés Andrade",
    "Marina Insuasti",
    "Buscar más...",
    "Sin instructor",
  ]);
});

test("con texto que coincide: después de los empleados", () => {
  const result = insertNoCoachOption([INES, MARINA, SEARCH_MORE], NO_COACH, {
    request: "in",
    hasValue: false,
  });
  expect(labels(result)).toEqual([
    "Inés Andrade",
    "Marina Insuasti",
    "Sin instructor",
    "Buscar más...",
  ]);
  // "in" + Tab: la primera opción sigue siendo un empleado.
  expect(result[0]).toBe(INES);
});

test("con texto que coincide y sin empleados: sustituye 'Sin registros'", () => {
  expect(labels(insertNoCoachOption([NO_RESULT], NO_COACH, {request: "sin"}))).toEqual([
    "Sin instructor",
  ]);
  expect(labels(insertNoCoachOption([CREATE], NO_COACH, {request: "sin"}))).toEqual([
    "Sin instructor",
    'Crear "sin"',
  ]);
});

test("con texto que no coincide: no aparece", () => {
  const options = [INES, SEARCH_MORE];
  expect(insertNoCoachOption(options, NO_COACH, {request: "ines"})).toBe(options);
  expect(insertNoCoachOption([NO_RESULT], NO_COACH, {request: "zz"})).toEqual([
    NO_RESULT,
  ]);
});

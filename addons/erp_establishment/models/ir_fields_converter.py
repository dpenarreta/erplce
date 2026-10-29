import unicodedata

from odoo import _, api, models


def _normalize_state_name(value):
    """Clave de comparación de nombres de provincia: sin tildes, sin
    distinguir mayúsculas y con los espacios colapsados.

    ``"Santo Domingo de los Tsáchilas"`` -> ``"santo domingo de los tsachilas"``;
    ``"Cañar"`` -> ``"canar"``.
    """
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


# Valores adicionales de la columna Activo que se aceptan como verdadero en
# la importación de establecimientos (comparados sin mayúsculas): "Si" sin
# tilde es habitual en hojas de cálculo; "Sí" se acepta aunque el usuario
# importe en otro idioma.
_ESTABLISHMENT_ACTIVE_EXTRA_TRUE = {"si", "sí"}


class IrFieldsConverter(models.AbstractModel):
    _inherit = "ir.fields.converter"

    @api.model
    def for_model(self, model, fromtype=str):
        """Columna *Activo* de la importación de establecimientos:

        - celda vacía -> establecimiento activo (el estándar la convierte en
          ``False`` y lo archivaría);
        - ``Si``/``si``/``SI`` sin tilde (y ``Sí`` en cualquier idioma) ->
          activo.

        El resto de valores (``Sí``, ``No``, ``1``, ``0``, ``True``...) siguen
        el conversor estándar. Alcance: solo ``erp.establishment`` y su campo
        ``active``; los booleanos de los demás modelos no cambian.
        """
        convert = super().for_model(model, fromtype=fromtype)
        if model._name != "erp.establishment" or fromtype is not str:
            return convert

        def convert_establishment(record, log):
            value = record.get("active")
            if "active" in record and (value is None or isinstance(value, str)):
                key = (value or "").strip().casefold()
                if not key or key in _ESTABLISHMENT_ACTIVE_EXTRA_TRUE:
                    record = dict(record, active="1")
            return convert(record, log)

        return convert_establishment

    @api.model
    def db_id_for(self, model, field, subfield, value):
        """Resuelve la columna *Provincia* de la importación de
        establecimientos SIEMPRE a una provincia de Ecuador.

        Los nombres de las provincias de Ecuador en el núcleo están sin tildes
        (``Bolivar``, ``Canar``, ``Los Rios``...) y algunos coinciden con
        provincias de otros países (``Bolívar`` con tilde es de Colombia), por
        lo que la búsqueda estándar por nombre (``name_search`` con ``=``)
        fallaría o elegiría la de otro país. Aquí se compara el valor, sin
        tildes ni mayúsculas, con el nombre y el código de las provincias de
        Ecuador.

        Alcance: solo ``erp.establishment.state_id`` referenciado por nombre
        (columna ``Provincia``); por ID externo (``/id``) o de BD (``/.id``),
        otros campos y otros modelos siguen el comportamiento estándar. Si el
        valor no es una provincia de Ecuador se delega en el estándar: o no
        encuentra nada (error de fila "no se encontró ningún registro
        coincidente") o encuentra una provincia de otro país, que rechaza la
        validación del establecimiento (error de fila con la provincia).
        """
        if (
            model._name == "erp.establishment"
            and field.name == "state_id"
            and subfield is None
            and isinstance(value, str)
            and value.strip()
        ):
            state_id = self._erp_find_ecuador_state(value)
            if state_id:
                return state_id, _("name"), []
        return super().db_id_for(model, field, subfield, value)

    @api.model
    def _erp_find_ecuador_state(self, value):
        """Id de la provincia de Ecuador cuyo nombre o código coincide con
        ``value`` sin tildes ni mayúsculas, o ``None``."""
        key = _normalize_state_name(value)
        cache = self.env.context.get("import_cache")
        cache_key = ("erp_establishment.ec_states",)
        index = cache.get(cache_key) if cache is not None else None
        if index is None:
            states = self.env["res.country.state"].search_fetch(
                [("country_id.code", "=", "EC")], ["name", "code"]
            )
            index = {}
            for state in states:
                index.setdefault(_normalize_state_name(state.name), state.id)
                index.setdefault(_normalize_state_name(state.code), state.id)
            if cache is not None:
                cache[cache_key] = index
        return index.get(key)

# ==========================================
# REGISTRO DE INGRESOS Y EGRESOS (SQLite)
# ==========================================
"""
Cada vehículo que entra genera un registro "abierto" (sin hora de egreso).
Cuando sale, se busca su registro abierto por la patente, se calcula el
tiempo y el importe, y se cierra.

SQLite es una base de datos que vive en un solo archivo (estacionamiento.db):
no hay que instalar ningún servidor. La app de cámara y el panel de control
la usan al mismo tiempo.

Protecciones contra errores de lectura:
  - Una patente no puede estar "adentro" dos veces.
  - Si la cámara vuelve a ver un vehículo que se acaba de registrar (o una lectura
    parecida de la misma chapa), no se crea otro registro: se informa como repetición.
  - Al salir, si la patente leída no coincide exacto con ninguna de adentro pero se
    parece a UNA sola (1 o 2 caracteres distintos), se toma esa (el OCR leyó distinto).
  - El operador puede corregir la patente o la categoría, o anular un registro, desde el panel.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from .tarifas import calcular_cobro, minutos_entre, formato_duracion, formato_dinero

ESQUEMA = """
CREATE TABLE IF NOT EXISTS registros (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patente         TEXT NOT NULL,
    categoria       TEXT NOT NULL,
    clase_detectada TEXT,
    ingreso         TEXT NOT NULL,
    egreso          TEXT,
    minutos         REAL,
    importe         REAL,
    detalle         TEXT,
    conf_ingreso    REAL,
    conf_egreso     REAL,
    foto_ingreso    TEXT,
    foto_egreso     TEXT,
    origen_ingreso  TEXT DEFAULT 'camara',
    origen_egreso   TEXT,
    patente_salida  TEXT,            -- patente leída en la salida, si fue distinta a la de entrada
    observaciones   TEXT
);
-- Una patente no puede estar "adentro" dos veces a la vez
CREATE UNIQUE INDEX IF NOT EXISTS una_vez_adentro ON registros(patente) WHERE egreso IS NULL;

CREATE TABLE IF NOT EXISTS eventos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    momento  TEXT NOT NULL,
    tipo     TEXT NOT NULL,      -- INGRESO, EGRESO, RECHAZO, CORRECCION, ANULACION
    patente  TEXT,
    mensaje  TEXT
);
"""
COLUMNAS_NUEVAS = {"patente_salida": "TEXT", "observaciones": "TEXT"}   # para bases creadas con la versión anterior

VENTANA_REPETICION_SEG = 300    # una relectura del mismo vehículo dentro de 5 min no es un error
VENTANA_PARECIDA_SEG = 45       # lectura PARECIDA (hasta 3 caracteres) mientras el auto sigue frente a la cámara


def _ahora():
    return datetime.now().replace(microsecond=0)


def _fecha(texto):
    return datetime.fromisoformat(texto) if texto else None


def distancia(a, b):
    """Caracteres distintos entre dos patentes del mismo largo (99 si tienen distinto largo)."""
    if not a or not b or len(a) != len(b):
        return 99
    return sum(x != y for x, y in zip(a, b))


class BaseEstacionamiento:
    def __init__(self, ruta_db, tarifas, reglas, factor_tiempo=1.0, max_dif_salida=2):
        self.ruta_db = str(ruta_db)
        self.tarifas = tarifas
        self.reglas = reglas
        self.factor_tiempo = factor_tiempo
        self.max_dif_salida = max_dif_salida
        self.ultimo_estado = None    # "ok", "repetido" o "rechazo": la app lo usa para elegir el color del aviso
        with self._conexion() as con:
            con.executescript(ESQUEMA)
            existentes = {f["name"] for f in con.execute("PRAGMA table_info(registros)")}
            for columna, tipo in COLUMNAS_NUEVAS.items():
                if columna not in existentes:
                    con.execute(f"ALTER TABLE registros ADD COLUMN {columna} {tipo}")

    @contextmanager
    def _conexion(self):
        """Abre la base, guarda los cambios al terminar (o los deshace si hubo un error) y la cierra."""
        con = sqlite3.connect(self.ruta_db, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")   # permite leer mientras otra app escribe
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _evento(self, con, tipo, patente, mensaje, momento=None):
        con.execute("INSERT INTO eventos (momento, tipo, patente, mensaje) VALUES (?, ?, ?, ?)",
                    ((momento or _ahora()).isoformat(sep=" "), tipo, patente, mensaje))

    @staticmethod
    def _abiertos(con):
        return [dict(f) for f in con.execute("SELECT * FROM registros WHERE egreso IS NULL")]

    def registro_abierto(self, patente):
        with self._conexion() as con:
            fila = con.execute("SELECT * FROM registros WHERE patente = ? AND egreso IS NULL",
                               (patente,)).fetchone()
        return dict(fila) if fila else None

    def registro(self, id_registro):
        with self._conexion() as con:
            fila = con.execute("SELECT * FROM registros WHERE id = ?", (id_registro,)).fetchone()
        return dict(fila) if fila else None

    # ---------- Ingreso ----------
    def registrar_ingreso(self, patente, categoria, clase_detectada=None, confianza=None,
                          foto=None, origen="camara", momento=None):
        """Devuelve (ok, mensaje, registro)."""
        momento = momento or _ahora()
        if categoria not in self.tarifas:
            self.ultimo_estado = "rechazo"
            return False, f"Categoría '{categoria}' sin tarifa configurada", None
        with self._conexion() as con:
            abiertos = self._abiertos(con)
            exacto = next((r for r in abiertos if r["patente"] == patente), None)
            if exacto:
                reciente = (momento - _fecha(exacto["ingreso"])).total_seconds() < VENTANA_REPETICION_SEG
                if reciente and origen == "camara":
                    self.ultimo_estado = "repetido"
                    return False, f"{patente} ya está registrado (ingresó a las {exacto['ingreso'][11:16]})", exacto
                msg = f"{patente} ya figura adentro desde {exacto['ingreso']}"
                self._evento(con, "RECHAZO", patente, msg, momento)
                self.ultimo_estado = "rechazo"
                return False, msg, exacto
            if origen == "camara":   # otra lectura (con algún carácter distinto) de un vehículo que acaba de entrar
                parecido = next((r for r in abiertos if distancia(r["patente"], patente) <= 3 and
                                 (momento - _fecha(r["ingreso"])).total_seconds() < VENTANA_PARECIDA_SEG), None)
                if parecido:
                    self.ultimo_estado = "repetido"
                    return False, (f"{patente} parece el mismo vehículo que {parecido['patente']}, "
                                   f"registrado a las {parecido['ingreso'][11:16]}"), parecido
            cur = con.execute(
                "INSERT INTO registros (patente, categoria, clase_detectada, ingreso, conf_ingreso, "
                "foto_ingreso, origen_ingreso) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (patente, categoria, clase_detectada, momento.isoformat(sep=" "), confianza, foto, origen))
            msg = f"Ingreso {patente} ({categoria}) a las {momento:%H:%M}" + (" [manual]" if origen != "camara" else "")
            self._evento(con, "INGRESO", patente, msg, momento)
            fila = con.execute("SELECT * FROM registros WHERE id = ?", (cur.lastrowid,)).fetchone()
        self.ultimo_estado = "ok"
        return True, msg, dict(fila)

    # ---------- Egreso ----------
    def cotizar(self, registro, momento=None):
        """Cuánto debería pagar ahora (sin cerrar el registro)."""
        momento = momento or _ahora()
        minutos = minutos_entre(_fecha(registro["ingreso"]), momento, self.factor_tiempo)
        return calcular_cobro(minutos, self.tarifas[registro["categoria"]], self.reglas)

    def buscar_para_egreso(self, patente):
        """Registro abierto que corresponde a la patente leída en la salida.
        Devuelve (registro, coincidencia) con coincidencia 'exacta', 'aproximada' o None."""
        with self._conexion() as con:
            abiertos = self._abiertos(con)
        exacto = next((r for r in abiertos if r["patente"] == patente), None)
        if exacto:
            return exacto, "exacta"
        candidatos = [(distancia(r["patente"], patente), r) for r in abiertos]
        candidatos = sorted((c for c in candidatos if c[0] <= self.max_dif_salida), key=lambda c: c[0])
        # solo si hay UN candidato claramente más parecido que los demás
        if candidatos and (len(candidatos) == 1 or candidatos[0][0] < candidatos[1][0]):
            return candidatos[0][1], "aproximada"
        return None, None

    def registrar_egreso(self, patente, confianza=None, foto=None, origen="camara", momento=None, id_registro=None):
        """Cierra el registro y devuelve (ok, mensaje, ticket).
        Con `id_registro` se cierra ese registro puntual (egreso manual desde el panel)."""
        momento = momento or _ahora()
        if id_registro is not None:
            abierto = self.registro(id_registro)
            abierto = abierto if abierto and not abierto["egreso"] else None
            coincidencia = "exacta" if abierto else None
        else:
            abierto, coincidencia = self.buscar_para_egreso(patente)
        with self._conexion() as con:
            if not abierto:
                desde = (momento - timedelta(seconds=VENTANA_REPETICION_SEG)).isoformat(sep=" ")
                recientes = con.execute("SELECT * FROM registros WHERE egreso IS NOT NULL AND egreso >= ? "
                                        "ORDER BY egreso DESC", (desde,)).fetchall()
                ultimo = next((r for r in recientes if patente in (r["patente"], r["patente_salida"])
                               or distancia(r["patente"], patente) <= self.max_dif_salida), None)
                if ultimo and origen == "camara":
                    self.ultimo_estado = "repetido"
                    return False, f"{patente} ya salió a las {ultimo['egreso'][11:16]} (ticket emitido)", None
                msg = f"{patente} no tiene un ingreso registrado: avisar al personal"
                self._evento(con, "RECHAZO", patente, msg, momento)
                self.ultimo_estado = "rechazo"
                return False, msg, None
            cobro = self.cotizar(abierto, momento)
            patente_salida = patente if coincidencia == "aproximada" else None
            con.execute("UPDATE registros SET egreso = ?, minutos = ?, importe = ?, detalle = ?, "
                        "conf_egreso = ?, foto_egreso = ?, origen_egreso = ?, patente_salida = ? WHERE id = ?",
                        (momento.isoformat(sep=" "), cobro.minutos, cobro.importe,
                         json.dumps(cobro.detalle, ensure_ascii=False), confianza, foto, origen,
                         patente_salida, abierto["id"]))
            msg = (f"Egreso {abierto['patente']}: {formato_duracion(cobro.minutos)} -> "
                   f"{formato_dinero(cobro.importe, self.reglas.moneda)}")
            if patente_salida:
                msg += f" (en la salida se leyó {patente_salida})"
            if origen != "camara":
                msg += " [manual]"
            self._evento(con, "EGRESO", abierto["patente"], msg, momento)
            fila = dict(con.execute("SELECT * FROM registros WHERE id = ?", (abierto["id"],)).fetchone())
        self.ultimo_estado = "ok"
        return True, msg, self.ticket(fila)

    def ticket(self, registro):
        detalle = json.loads(registro["detalle"]) if registro.get("detalle") else []
        return {
            "id": registro.get("id"),
            "patente": registro["patente"],
            "patente_salida": registro.get("patente_salida"),
            "categoria": registro["categoria"],
            "ingreso": registro["ingreso"],
            "egreso": registro["egreso"],
            "permanencia": formato_duracion(registro["minutos"] or 0),
            "detalle": detalle,
            "importe": registro["importe"],
            "importe_texto": formato_dinero(registro["importe"] or 0, self.reglas.moneda),
            "foto_ingreso": registro.get("foto_ingreso"),
            "foto_egreso": registro.get("foto_egreso"),
        }

    # ---------- Correcciones del operador ----------
    def corregir_registro(self, id_registro, patente=None, categoria=None, motivo=""):
        """Corrige la patente y/o la categoría de un registro. Si ya salió, recalcula el importe."""
        reg = self.registro(id_registro)
        if not reg:
            return False, "Registro inexistente"
        patente = patente or reg["patente"]
        categoria = categoria or reg["categoria"]
        if categoria not in self.tarifas:
            return False, f"Categoría '{categoria}' sin tarifa configurada"
        if patente == reg["patente"] and categoria == reg["categoria"]:
            return False, "No hay cambios"
        with self._conexion() as con:
            if not reg["egreso"] and patente != reg["patente"]:
                otro = con.execute("SELECT id FROM registros WHERE patente = ? AND egreso IS NULL AND id <> ?",
                                   (patente, id_registro)).fetchone()
                if otro:
                    return False, f"{patente} ya figura adentro en otro registro"
            importe, detalle = reg["importe"], reg["detalle"]
            if reg["egreso"] and categoria != reg["categoria"]:
                cobro = calcular_cobro(reg["minutos"] or 0, self.tarifas[categoria], self.reglas)
                importe, detalle = cobro.importe, json.dumps(cobro.detalle, ensure_ascii=False)
            con.execute("UPDATE registros SET patente = ?, categoria = ?, importe = ?, detalle = ?, "
                        "observaciones = TRIM(COALESCE(observaciones, '') || ' ' || ?) WHERE id = ?",
                        (patente, categoria, importe, detalle, f"[corregido: {motivo}]" if motivo else "[corregido]",
                         id_registro))
            cambios = []
            if patente != reg["patente"]:
                cambios.append(f"patente {reg['patente']} -> {patente}")
            if categoria != reg["categoria"]:
                cambios.append(f"categoría {reg['categoria']} -> {categoria}")
            msg = f"Corrección registro #{id_registro}: " + ", ".join(cambios) + (f" ({motivo})" if motivo else "")
            self._evento(con, "CORRECCION", patente, msg)
        return True, msg

    def anular_registro(self, id_registro, motivo=""):
        """Elimina un registro cargado por error (queda constancia en los eventos)."""
        reg = self.registro(id_registro)
        if not reg:
            return False, "Registro inexistente"
        with self._conexion() as con:
            con.execute("DELETE FROM registros WHERE id = ?", (id_registro,))
            msg = (f"Anulado registro #{id_registro} {reg['patente']} (ingreso {reg['ingreso'][5:16]})"
                   + (f": {motivo}" if motivo else ""))
            self._evento(con, "ANULACION", reg["patente"], msg)
        return True, msg

    # ---------- Consultas para el panel ----------
    def vehiculos_dentro(self, momento=None):
        momento = momento or _ahora()
        with self._conexion() as con:
            filas = [dict(f) for f in con.execute(
                "SELECT * FROM registros WHERE egreso IS NULL ORDER BY ingreso")]
        for f in filas:
            cobro = self.cotizar(f, momento)
            f["minutos_actuales"] = cobro.minutos
            f["permanencia"] = formato_duracion(cobro.minutos)
            f["a_pagar"] = cobro.importe
        return filas

    def historial(self, limite=200):
        with self._conexion() as con:
            return [dict(f) for f in con.execute(
                "SELECT * FROM registros ORDER BY COALESCE(egreso, ingreso) DESC LIMIT ?", (limite,))]

    def historial_entre(self, desde, hasta, patente=None):
        """Registros con ingreso o egreso entre dos fechas (incluidas). `patente` filtra por texto parcial."""
        d, h = f"{desde:%Y-%m-%d} 00:00:00", f"{hasta:%Y-%m-%d} 23:59:59"
        sql = ("SELECT * FROM registros WHERE ((ingreso BETWEEN ? AND ?) OR (egreso BETWEEN ? AND ?))")
        params = [d, h, d, h]
        if patente:
            sql += " AND (patente LIKE ? OR patente_salida LIKE ?)"
            params += [f"%{patente}%", f"%{patente}%"]
        with self._conexion() as con:
            return [dict(f) for f in con.execute(sql + " ORDER BY ingreso DESC", params)]

    def ultimo_egreso(self):
        with self._conexion() as con:
            fila = con.execute("SELECT * FROM registros WHERE egreso IS NOT NULL ORDER BY egreso DESC LIMIT 1").fetchone()
        return dict(fila) if fila else None

    def eventos(self, limite=50):
        with self._conexion() as con:
            return [dict(f) for f in con.execute("SELECT * FROM eventos ORDER BY momento DESC, id DESC LIMIT ?", (limite,))]

    def resumen_del_dia(self, dia=None):
        dia = (dia or _ahora()).strftime("%Y-%m-%d")
        with self._conexion() as con:
            ingresos = con.execute("SELECT COUNT(*) FROM registros WHERE ingreso LIKE ?", (dia + "%",)).fetchone()[0]
            egresos, recaudado = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(importe), 0) FROM registros WHERE egreso LIKE ?",
                (dia + "%",)).fetchone()
            dentro = con.execute("SELECT COUNT(*) FROM registros WHERE egreso IS NULL").fetchone()[0]
            rechazos = con.execute("SELECT COUNT(*) FROM eventos WHERE tipo = 'RECHAZO' AND momento LIKE ?",
                                   (dia + "%",)).fetchone()[0]
        return {"ingresos": ingresos, "egresos": egresos, "recaudado": recaudado, "dentro": dentro,
                "rechazos": rechazos}

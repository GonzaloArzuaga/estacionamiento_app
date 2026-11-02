# ==========================================
# PANEL DE GESTIÓN DEL ESTACIONAMIENTO (Streamlit)
# ==========================================
"""
Uso (mientras la app de cámara está abierta, o desde "Iniciar estacionamiento.bat"):

    streamlit run panel.py

Pestañas:
  En vivo       cupos libres, vehículos adentro con lo que pagarían ahora, última salida y actividad
  Movimientos   historial con filtros, fotos de cada movimiento, corrección y anulación de registros
  Caja          recaudación del día por categoría y por hora, ocupación, exportación a CSV
  Operaciones   registro manual de ingresos y salidas (patente sucia, tapada o ilegible)
  Tarifas       precios vigentes y calculadora
"""
import html
import os
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from estacionamiento import (abrir_base, cargar_config, calcular_cobro, cargar_tarifas,
                             formato_dinero, formato_duracion, validar_patente)

st.set_page_config(page_title="Panel del estacionamiento", page_icon="🅿️", layout="wide")

config = cargar_config()
base = abrir_base(config)
tarifas, reglas = cargar_tarifas(config)
CAPACIDAD = int(config.get("capacidad", 60))
ALERTA_HORAS = float(config.get("alerta_horas", 12))
NOMBRE = config.get("nombre_estacionamiento", "Estacionamiento")

AZUL, ASFALTO, MUTED = "#1D4E9E", "#262B31", "#66707A"
COLOR_EVENTO = {"INGRESO": "#2E7D4F", "EGRESO": "#B85C12", "RECHAZO": "#B3261E",
                "CORRECCION": "#4F6F99", "ANULACION": "#66707A"}
NOMBRE_EVENTO = {"INGRESO": "Ingreso", "EGRESO": "Salida", "RECHAZO": "Rechazo",
                 "CORRECCION": "Corrección", "ANULACION": "Anulación"}


def dinero(v):
    return formato_dinero(v or 0, reglas.moneda)


def nombre_categoria(c):
    return str(c).replace("_", " ").capitalize()


def esc(t):
    return html.escape(str(t))


def avisar_y_recargar(ok, msg):
    """Guarda el resultado de una operación para mostrarlo después de recargar la página."""
    st.session_state["aviso"] = (ok, msg)
    st.rerun()


def mostrar_aviso():
    if "aviso" in st.session_state:
        ok, msg = st.session_state.pop("aviso")
        (st.success if ok else st.error)(msg)


# ---------------------------------------------------------------- estilos
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap');
body, .stMarkdown, .stMarkdown p, label, input, textarea, .stCaption, [data-testid="stMetricLabel"] { font-family: 'Barlow', 'Segoe UI', sans-serif; }
h1, h2, h3, h4, [data-testid="stMetricValue"] *, .stTabs [role="tab"] p { font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif !important; letter-spacing: .01em; }
.block-container { padding-top: 3.4rem; max-width: 1400px; }
[data-testid="stToolbar"], [data-testid="stHeaderActionElements"] { display: none !important; }
.stTabs [role="tab"] p { font-size: 1.25rem !important; font-weight: 600; }
.stTabs [role="tablist"] { gap: 22px; }

.encabezado { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }
.marca { display: flex; align-items: center; gap: 14px; }
.letra-e { width: 52px; height: 52px; border-radius: 8px; background: #1D4E9E; color: #fff; display: grid; place-items: center;
  font: 700 38px/1 'Barlow Condensed', sans-serif; border: 3px solid #fff; outline: 2px solid #1D4E9E; }
.marca h1 { margin: 0; padding: 0; font-size: 2.1rem; line-height: 1; color: #262B31; }
.marca .sub { color: #66707A; font-size: .95rem; margin-top: 2px; }
.reloj { text-align: right; color: #262B31; font: 600 1.6rem/1 'Barlow Condensed', sans-serif; }
.reloj small { display: block; color: #66707A; font: 400 .9rem 'Barlow', sans-serif; margin-top: 4px; }

.franja { display: grid; grid-template-columns: minmax(250px, 330px) 1fr; gap: 18px; align-items: stretch; margin-bottom: 8px; }
@media (max-width: 760px) { .franja { grid-template-columns: 1fr; } }
.cartel { background: #262B31; border-radius: 10px; padding: 14px 20px; display: flex; align-items: center; gap: 18px; color: #fff;
  box-shadow: inset 0 0 0 3px #3A414A; }
.cartel .e { width: 46px; height: 46px; border-radius: 6px; background: #1D4E9E; display: grid; place-items: center;
  font: 700 32px/1 'Barlow Condensed', sans-serif; border: 2px solid #fff; flex: none; }
.cartel .numero { font: 700 4.4rem/0.9 'Barlow Condensed', sans-serif; color: #F5C518; font-variant-numeric: tabular-nums;
  text-shadow: 0 0 14px rgba(245,197,24,.35); }
.cartel .texto { font: 600 1.35rem/1.1 'Barlow Condensed', sans-serif; letter-spacing: .08em; }
.cartel .texto small { display: block; font: 400 .85rem 'Barlow', sans-serif; letter-spacing: 0; color: #B9C0C7; margin-top: 3px; }
.cartel.completo .numero { color: #FF5A4E; text-shadow: 0 0 14px rgba(255,90,78,.35); }

.ocupacion { background: #fff; border-radius: 10px; padding: 14px 20px; display: flex; flex-direction: column; justify-content: center; gap: 12px;
  border: 1px solid #DADDD8; }
.barra { height: 14px; border-radius: 7px; background: #E3E6E2; overflow: hidden; }
.barra > div { height: 100%; border-radius: 7px; background: #1D4E9E; }
.barra.alta > div { background: #B85C12; }
.cifras { display: flex; flex-wrap: wrap; gap: 8px 34px; }
.cifra b { display: block; font: 600 1.7rem/1 'Barlow Condensed', sans-serif; color: #262B31; font-variant-numeric: tabular-nums; }
.cifra span { color: #66707A; font-size: .9rem; }

.chapa { display: inline-flex; flex-direction: column; border-radius: 5px; overflow: hidden; min-width: 142px; vertical-align: middle;
  border: 2px solid #262B31; background: #fff; line-height: 1; box-shadow: 0 1px 0 rgba(0,0,0,.18); }
.chapa .banda { background: #1D4E9E; color: #fff; font: 600 7.5px/1 'Barlow', sans-serif; letter-spacing: .08em; text-align: center; padding: 3px 6px 2px; }
.chapa .num { font: 600 1.45rem/1 'Barlow Condensed', sans-serif; letter-spacing: .07em; text-align: center; padding: 4px 10px 5px; color: #000; white-space: nowrap; }
.chapa.vieja { background: #1C1C1C; border-color: #8C9298; }
.chapa.vieja .banda { background: transparent; color: #BFC4C9; padding-top: 4px; }
.chapa.vieja .num { color: #F4F4F4; }
.chapa.grande { min-width: 200px; }
.chapa.grande .num { font-size: 2.2rem; padding: 6px 14px 8px; }
.chapa.grande .banda { font-size: 9px; }

.tabla { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; border: 1px solid #DADDD8; }
.tabla th { text-align: left; font: 500 .85rem 'Barlow', sans-serif; color: #66707A; padding: 10px 14px; border-bottom: 1px solid #E3E6E2; background: #F7F8F6; }
.tabla td { padding: 9px 14px; border-bottom: 1px solid #EEF0ED; color: #262B31; font-variant-numeric: tabular-nums; }
.tabla tr:last-child td { border-bottom: 0; }
.tabla td.monto { font: 600 1.15rem 'Barlow Condensed', sans-serif; text-align: right; }
.tabla th.monto { text-align: right; }
.tabla tr.demorado td:first-child { box-shadow: inset 4px 0 0 #F5C518; }
.aviso { color: #8A6A00; font-size: .85rem; display: block; margin-top: 2px; }
.vacio { background: #fff; border: 1px dashed #C9CEC8; border-radius: 10px; padding: 26px; color: #66707A; text-align: center; }

.ticket { background: #fff; border-radius: 4px; padding: 18px 20px 16px; border: 1px solid #DADDD8; position: relative;
  background-image: radial-gradient(circle at 8px 0, #EDEFEC 6px, transparent 6.5px), radial-gradient(circle at 8px 100%, #EDEFEC 6px, transparent 6.5px);
  background-size: 16px 8px, 16px 8px; background-repeat: repeat-x; background-position: top left, bottom left; }
.ticket .fila { display: flex; justify-content: space-between; gap: 10px; padding: 3px 0; color: #262B31; }
.ticket .fila span:first-child { color: #66707A; }
.ticket .detalle { border-top: 1px dashed #C9CEC8; margin-top: 10px; padding-top: 8px; color: #44505B; font-size: .92rem; }
.ticket .total { border-top: 2px solid #262B31; margin-top: 10px; padding-top: 8px; display: flex; justify-content: space-between; align-items: baseline; }
.ticket .total b { font: 700 2.1rem/1 'Barlow Condensed', sans-serif; color: #262B31; }
.ticket .nota { background: #FFF6D6; color: #6B5300; border-radius: 4px; padding: 6px 8px; font-size: .85rem; margin-top: 8px; }

.actividad { display: flex; flex-direction: column; gap: 2px; }
.evento { display: grid; grid-template-columns: 62px 1fr; gap: 10px; padding: 7px 10px; background: #fff; border-left: 4px solid #999; border-radius: 3px; }
.evento time { color: #66707A; font-variant-numeric: tabular-nums; font-size: .9rem; }
.evento b { font-weight: 600; margin-right: 6px; }
.evento p { margin: 0; color: #262B31; font-size: .92rem; line-height: 1.35; }
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- piezas visuales
def chapa(patente, grande=False):
    """Dibuja la patente como chapa: Mercosur (blanca con franja azul) o del formato anterior (negra)."""
    v = validar_patente(patente, max_correcciones=0)
    texto = v.legible if v else patente
    mercosur = bool(v and v.formato.endswith("MERCOSUR"))
    clase = "chapa" + ("" if mercosur else " vieja") + (" grande" if grande else "")
    banda = "REPÚBLICA ARGENTINA" if mercosur else "ARGENTINA"
    return f'<span class="{clase}"><span class="banda">{banda}</span><span class="num">{esc(texto)}</span></span>'


def encabezado():
    ahora = datetime.now()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    demo = ""
    if config.get("factor_tiempo", 1) != 1:
        demo = f". Modo demostración: el cobro corre {config['factor_tiempo']} veces más rápido"
    st.markdown(
        f'<div class="encabezado"><div class="marca"><div class="letra-e">E</div><div><h1>{esc(NOMBRE)}</h1>'
        f'<div class="sub">Panel de gestión{esc(demo)}</div></div></div>'
        f'<div class="reloj">{ahora:%H:%M}<small>{dias[ahora.weekday()]} {ahora:%d/%m/%Y}</small></div></div>',
        unsafe_allow_html=True)


def franja_superior(resumen):
    dentro = resumen["dentro"]
    libres = max(CAPACIDAD - dentro, 0)
    pct = min(dentro / CAPACIDAD, 1) if CAPACIDAD else 0
    completo = libres == 0
    cartel = (f'<div class="cartel{" completo" if completo else ""}">'
              f'<div class="numero">{libres}</div><div class="texto">{"COMPLETO" if completo else "LIBRES"}'
              f'<small>de {CAPACIDAD} cocheras</small></div></div>')
    cifras = "".join(f'<div class="cifra"><b>{v}</b><span>{t}</span></div>' for t, v in [
        ("vehículos adentro", dentro), ("ingresos hoy", resumen["ingresos"]),
        ("salidas hoy", resumen["egresos"]), ("recaudado hoy", dinero(resumen["recaudado"])),
        ("rechazos hoy", resumen["rechazos"])])
    ocupacion = (f'<div class="ocupacion"><div class="barra{" alta" if pct >= .85 else ""}">'
                 f'<div style="width:{pct * 100:.1f}%"></div></div><div class="cifras">{cifras}</div></div>')
    st.markdown(f'<div class="franja">{cartel}{ocupacion}</div>', unsafe_allow_html=True)


def tabla_adentro(dentro):
    if not dentro:
        st.markdown('<div class="vacio">No hay vehículos adentro. Cada ingreso aparece acá apenas la cámara '
                    'de entrada confirma una patente, o cuando se registra a mano en Operaciones.</div>',
                    unsafe_allow_html=True)
        return
    filas = []
    for d in dentro:
        demorado = d["minutos_actuales"] >= ALERTA_HORAS * 60
        aviso = f'<span class="aviso">Más de {ALERTA_HORAS:g} h adentro</span>' if demorado else ""
        origen = " (manual)" if d.get("origen_ingreso") == "manual" else ""
        filas.append(
            f'<tr class="{"demorado" if demorado else ""}"><td>{chapa(d["patente"])}</td>'
            f'<td>{esc(nombre_categoria(d["categoria"]))}{aviso}</td><td>{d["ingreso"][11:16]}{origen}</td>'
            f'<td>{esc(d["permanencia"])}</td><td class="monto">{dinero(d["a_pagar"])}</td></tr>')
    st.markdown('<table class="tabla"><thead><tr><th>Patente</th><th>Categoría</th><th>Entró</th>'
                '<th>Tiempo adentro</th><th class="monto">Pagaría ahora</th></tr></thead><tbody>'
                + "".join(filas) + "</tbody></table>", unsafe_allow_html=True)


def ticket_html(t):
    nota = (f'<div class="nota">En la salida se leyó {esc(t["patente_salida"])}: se asoció a este ingreso '
            f'por ser la patente más parecida. Verificar.</div>') if t.get("patente_salida") else ""
    detalle = "".join(f"<div>{esc(l)}</div>" for l in t["detalle"])
    return (f'<div class="ticket"><div style="margin-bottom:10px">{chapa(t["patente"], grande=True)}</div>'
            f'<div class="fila"><span>Categoría</span><span>{esc(nombre_categoria(t["categoria"]))}</span></div>'
            f'<div class="fila"><span>Entró</span><span>{esc(t["ingreso"][:16])}</span></div>'
            f'<div class="fila"><span>Salió</span><span>{esc((t["egreso"] or "")[:16])}</span></div>'
            f'<div class="fila"><span>Tiempo</span><span>{esc(t["permanencia"])}</span></div>'
            f'<div class="detalle">{detalle}</div>{nota}'
            f'<div class="total"><span>Total a pagar</span><b>{esc(t["importe_texto"])}</b></div></div>')


def texto_evento(e):
    """Mensaje del evento sin repetir el tipo al principio ('Ingreso AB123CD...' -> 'AB123CD...')."""
    m = e["mensaje"]
    for prefijo in ("Ingreso ", "Egreso "):
        if m.startswith(prefijo):
            m = m[len(prefijo):]
    for c in tarifas:
        m = m.replace(f"({c})", f"({nombre_categoria(c).lower()})")
    return m.replace(" -> ", ", cobrado ")


def actividad(eventos):
    if not eventos:
        st.markdown('<div class="vacio">Todavía no hay movimientos.</div>', unsafe_allow_html=True)
        return
    items = []
    for e in eventos:
        color = COLOR_EVENTO.get(e["tipo"], "#999")
        items.append(f'<div class="evento" style="border-left-color:{color}"><time>{e["momento"][11:16]}</time>'
                     f'<p><b style="color:{color}">{NOMBRE_EVENTO.get(e["tipo"], e["tipo"])}</b>{esc(texto_evento(e))}</p></div>')
    st.markdown(f'<div class="actividad">{"".join(items)}</div>', unsafe_allow_html=True)


def mostrar_fotos(registro):
    columnas = st.columns(2)
    for col, campo, titulo in [(columnas[0], "foto_ingreso", "Cámara de entrada"),
                               (columnas[1], "foto_egreso", "Cámara de salida")]:
        ruta = registro.get(campo)
        with col:
            if ruta and os.path.exists(ruta):
                st.image(ruta, caption=titulo, width="stretch")
            else:
                st.caption(f"{titulo}: sin foto" + (" (registro manual)" if ruta is None else ""))


def tabla_registros(registros):
    filas = []
    for r in registros:
        filas.append({
            "N°": r["id"], "Patente": r["patente"], "Categoría": nombre_categoria(r["categoria"]),
            "Entró": r["ingreso"][:16], "Salió": (r["egreso"] or "")[:16] or "adentro",
            "Tiempo": formato_duracion(r["minutos"]) if r["minutos"] is not None else "",
            "Importe": r["importe"], "Leída en salida": r.get("patente_salida") or "",
            "Origen": "manual" if "manual" in (r.get("origen_ingreso"), r.get("origen_egreso")) else "cámara",
        })
    return pd.DataFrame(filas)


FUENTE = "Barlow, Segoe UI, sans-serif"
ETIQUETA_PESOS = "replace(format(datum.value, ',.0f'), regexp(',', 'g'), '.')"


def estilo(grafico, alto):
    """Tipografía, colores de ejes y grilla comunes a todos los gráficos."""
    return (grafico.properties(height=alto)
            .configure(font=FUENTE)
            .configure_axis(labelFont=FUENTE, titleFont=FUENTE, labelColor=MUTED, titleColor=MUTED, labelFontSize=12,
                            titleFontSize=12, titleFontWeight=500, gridColor="#E3E6E2", domainColor="#C9CEC8", tickColor="#C9CEC8")
            .configure_view(strokeWidth=0))


# ---------------------------------------------------------------- página
encabezado()


@st.fragment(run_every="3s")
def franja_en_vivo():
    franja_superior(base.resumen_del_dia())


franja_en_vivo()

mostrar_aviso()
tab_vivo, tab_mov, tab_caja, tab_ops, tab_tarifas = st.tabs(
    ["En vivo", "Movimientos", "Caja", "Operaciones", "Tarifas"])

# ---------- En vivo
with tab_vivo:
    @st.fragment(run_every="3s")
    def en_vivo():
        izquierda, derecha = st.columns([3, 2], gap="large")
        with izquierda:
            st.subheader("Adentro ahora")
            tabla_adentro(base.vehiculos_dentro())
        with derecha:
            st.subheader("Última salida")
            ultimo = base.ultimo_egreso()
            if ultimo:
                st.markdown(ticket_html(base.ticket(ultimo)), unsafe_allow_html=True)
                with st.expander("Ver fotos de entrada y salida"):
                    mostrar_fotos(ultimo)
            else:
                st.markdown('<div class="vacio">Todavía no salió ningún vehículo.</div>', unsafe_allow_html=True)
            st.subheader("Actividad")
            actividad(base.eventos(10))

    en_vivo()

# ---------- Movimientos
with tab_mov:
    st.subheader("Historial de movimientos")
    f1, f2, f3, f4 = st.columns([1, 1, 1.2, 1])
    hoy = date.today()
    desde = f1.date_input("Desde", hoy - timedelta(days=6), format="DD/MM/YYYY")
    hasta = f2.date_input("Hasta", hoy, format="DD/MM/YYYY")
    buscar = f3.text_input("Buscar patente", placeholder="Ej.: AB123 o FIN").replace(" ", "").upper()
    estado = f4.selectbox("Mostrar", ["Todos", "Adentro", "Ya salieron", "Corregidos o leídos distinto"])

    registros = base.historial_entre(desde, hasta, buscar or None)
    if estado == "Adentro":
        registros = [r for r in registros if not r["egreso"]]
    elif estado == "Ya salieron":
        registros = [r for r in registros if r["egreso"]]
    elif estado == "Corregidos o leídos distinto":
        registros = [r for r in registros if r.get("patente_salida") or (r.get("observaciones") or "")]

    if not registros:
        st.markdown('<div class="vacio">No hay movimientos con esos filtros. Probá ampliar las fechas o borrar la búsqueda.</div>',
                    unsafe_allow_html=True)
    else:
        df = tabla_registros(registros)
        st.caption(f"{len(df)} {'movimiento' if len(df) == 1 else 'movimientos'}. Seleccioná una fila para ver las fotos, corregir o anular el registro.")
        seleccion = st.dataframe(
            df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="tabla_mov",
            column_config={"Importe": st.column_config.NumberColumn(f"Importe ({reglas.moneda})", format="localized"),
                           "N°": st.column_config.NumberColumn(width="small")})
        st.download_button("Descargar CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"movimientos_{desde:%Y%m%d}_{hasta:%Y%m%d}.csv", mime="text/csv")

        filas_sel = seleccion.selection.rows if seleccion else []
        if filas_sel:
            reg = base.registro(int(df.iloc[filas_sel[0]]["N°"]))
            if reg:
                st.divider()
                c1, c2 = st.columns([2, 3], gap="large")
                with c1:
                    if reg["egreso"]:
                        st.markdown(ticket_html(base.ticket(reg)), unsafe_allow_html=True)
                    else:
                        cobro = base.cotizar(reg)
                        st.markdown(f'{chapa(reg["patente"], grande=True)}', unsafe_allow_html=True)
                        st.write(f"Adentro desde {reg['ingreso'][:16]}, hace {formato_duracion(cobro.minutos)}. "
                                 f"Pagaría ahora **{dinero(cobro.importe)}**")
                    if reg.get("observaciones"):
                        st.caption(f"Observaciones: {reg['observaciones']}")
                with c2:
                    mostrar_fotos(reg)
                    with st.form(f"corregir_{reg['id']}"):
                        st.markdown("**Corregir registro**")
                        k1, k2 = st.columns(2)
                        nueva_patente = k1.text_input("Patente", value=reg["patente"])
                        cats = list(tarifas)
                        nueva_cat = k2.selectbox("Categoría", cats, index=cats.index(reg["categoria"]) if reg["categoria"] in cats else 0,
                                                 format_func=nombre_categoria)
                        motivo = st.text_input("Motivo", placeholder="Ej.: el OCR leyó mal una letra")
                        if st.form_submit_button("Guardar corrección"):
                            v = validar_patente(nueva_patente, max_correcciones=0)
                            if not v:
                                st.error("La patente no tiene un formato argentino válido (ABC 123, AB 123 CD, 123 ABC o A 123 BCD).")
                            else:
                                ok, msg = base.corregir_registro(reg["id"], v.texto, nueva_cat, motivo)
                                if ok:
                                    avisar_y_recargar(ok, msg)
                                st.warning(msg)
                    with st.expander("Anular este registro"):
                        st.caption("Usalo solo para registros cargados por error. Queda constancia en la actividad.")
                        motivo_anul = st.text_input("Motivo de la anulación", key=f"motivo_anul_{reg['id']}")
                        confirmar = st.checkbox("Confirmo que quiero anularlo", key=f"conf_anul_{reg['id']}")
                        if st.button("Anular registro", type="primary", disabled=not confirmar, key=f"anular_{reg['id']}"):
                            avisar_y_recargar(*base.anular_registro(reg["id"], motivo_anul))

# ---------- Caja
with tab_caja:
    st.subheader("Caja y ocupación")
    dia = st.columns([1, 3])[0].date_input("Día", date.today(), format="DD/MM/YYYY", key="dia_caja")
    del_dia = base.historial_entre(dia, dia)
    salidas = [r for r in del_dia if r["egreso"] and r["egreso"].startswith(f"{dia:%Y-%m-%d}")]
    total = sum(r["importe"] or 0 for r in salidas)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Recaudado", dinero(total))
    m2.metric("Salidas cobradas", len(salidas))
    m3.metric("Ticket promedio", dinero(total / len(salidas)) if salidas else "—")
    m4.metric("Tiempo promedio", formato_duracion(sum(r["minutos"] or 0 for r in salidas) / len(salidas)) if salidas else "—")

    if not del_dia:
        st.markdown('<div class="vacio">Ese día no hubo movimientos.</div>', unsafe_allow_html=True)
    else:
        g1, g2 = st.columns(2, gap="large")
        with g1:
            st.markdown("**Recaudación por categoría**")
            if salidas:
                por_cat = (pd.DataFrame([{"Categoría": nombre_categoria(r["categoria"]), "Importe": r["importe"] or 0} for r in salidas])
                           .groupby("Categoría", as_index=False).agg(Importe=("Importe", "sum"), Salidas=("Importe", "size")))
                por_cat["Texto"] = por_cat["Importe"].map(dinero)
                barras = alt.Chart(por_cat).mark_bar(color=AZUL, cornerRadiusEnd=4, size=20).encode(
                    y=alt.Y("Categoría:N", sort="-x", title=None, axis=alt.Axis(ticks=False, domain=False)),
                    x=alt.X("Importe:Q", title=f"Recaudado ({reglas.moneda})",
                            axis=alt.Axis(labelExpr=ETIQUETA_PESOS, tickCount=4)),
                    tooltip=[alt.Tooltip("Categoría:N"), alt.Tooltip("Texto:N", title="Recaudado"), alt.Tooltip("Salidas:Q")])
                etiquetas = barras.mark_text(align="left", dx=6, color=ASFALTO, fontSize=13).encode(text="Texto:N")
                st.altair_chart(estilo(barras + etiquetas, max(140, 46 * len(por_cat))), width="stretch")
            else:
                st.caption("Todavía no hubo salidas cobradas ese día.")
        with g2:
            st.markdown("**Ingresos por hora**")
            ingresos_dia = [r for r in del_dia if r["ingreso"].startswith(f"{dia:%Y-%m-%d}")]
            horas = pd.DataFrame({"Hora": range(24), "Ingresos": 0})
            for r in ingresos_dia:
                horas.loc[int(r["ingreso"][11:13]), "Ingresos"] += 1
            horas = horas[(horas["Hora"] >= min(7, horas.loc[horas.Ingresos > 0, "Hora"].min() if ingresos_dia else 7))]
            horas["Franja"] = horas["Hora"].map(lambda h: f"{h:02d}:00 a {h:02d}:59")
            st.altair_chart(estilo(alt.Chart(horas).mark_bar(color=AZUL, cornerRadiusEnd=4).encode(
                x=alt.X("Hora:O", title="Hora del día", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Ingresos:Q", title="Vehículos que entraron", axis=alt.Axis(tickMinStep=1)),
                tooltip=[alt.Tooltip("Franja:N", title="Horario"), alt.Tooltip("Ingresos:Q")]), 230), width="stretch")

        st.markdown("**Ocupación a lo largo del día**")
        primer = min(r["ingreso"] for r in del_dia if r["ingreso"].startswith(f"{dia:%Y-%m-%d}")) \
            if any(r["ingreso"].startswith(f"{dia:%Y-%m-%d}") for r in del_dia) else f"{dia:%Y-%m-%d} 00:00:00"
        inicio = max(datetime.combine(dia, datetime.min.time()),
                     datetime.fromisoformat(primer).replace(minute=0, second=0) - timedelta(hours=1))
        fin = min(datetime.combine(dia, datetime.max.time()), datetime.now()) if dia == date.today() else datetime.combine(dia, datetime.max.time())
        momentos = pd.date_range(inicio, fin, freq="10min")
        ing = pd.to_datetime([r["ingreso"] for r in del_dia], format="ISO8601")
        egr = pd.to_datetime([r["egreso"] or "2100-01-01 00:00:00" for r in del_dia], format="ISO8601")
        ocup = pd.DataFrame({"Momento": momentos, "Vehículos": [int(((ing <= m) & (egr > m)).sum()) for m in momentos]})
        ocup["Hora"] = ocup["Momento"].dt.strftime("%H:%M")
        linea = alt.Chart(ocup).mark_line(color=AZUL, strokeWidth=2, interpolate="step-after").encode(
            x=alt.X("Momento:T", title=None, axis=alt.Axis(format="%H:%M")),
            y=alt.Y("Vehículos:Q", title="Vehículos adentro", scale=alt.Scale(domain=[0, max(CAPACIDAD, int(ocup["Vehículos"].max()) + 1)])),
            tooltip=[alt.Tooltip("Hora:N"), alt.Tooltip("Vehículos:Q")])
        capacidad = alt.Chart(pd.DataFrame({"y": [CAPACIDAD]})).mark_rule(color="#B85C12", strokeDash=[5, 4]).encode(y="y:Q")
        texto_cap = alt.Chart(pd.DataFrame({"y": [CAPACIDAD], "t": [f"Capacidad: {CAPACIDAD}"]})).mark_text(
            align="left", dx=4, dy=-7, color="#B85C12", fontSize=12).encode(y="y:Q", x=alt.value(0), text="t:N")
        st.altair_chart(estilo(linea + capacidad + texto_cap, 220), width="stretch")

        if salidas:
            st.download_button("Descargar cierre de caja (CSV)", tabla_registros(salidas).to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"caja_{dia:%Y%m%d}.csv", mime="text/csv")

# ---------- Operaciones
with tab_ops:
    st.caption("Para cuando la cámara no puede leer la patente: sucia, tapada, dañada o de otro país.")
    o1, o2 = st.columns(2, gap="large")
    with o1:
        st.subheader("Registrar ingreso")
        with st.form("ingreso_manual", clear_on_submit=True):
            patente_txt = st.text_input("Patente", placeholder="AB 123 CD")
            categoria = st.selectbox("Categoría", list(tarifas), format_func=nombre_categoria)
            if st.form_submit_button("Registrar ingreso", type="primary"):
                v = validar_patente(patente_txt, max_correcciones=0)
                if not v:
                    st.error("La patente no tiene un formato argentino válido (ABC 123, AB 123 CD, 123 ABC o A 123 BCD).")
                else:
                    ok, msg, _ = base.registrar_ingreso(v.texto, "moto" if v.es_moto and "moto" in tarifas else categoria,
                                                        origen="manual")
                    (st.success if ok else st.error)(msg)
    with o2:
        st.subheader("Registrar salida")
        caja_salida = st.container(border=True)
        dentro = base.vehiculos_dentro()
        with caja_salida:
            if not dentro:
                st.markdown('<div class="vacio">No hay vehículos adentro para dar salida.</div>', unsafe_allow_html=True)
            else:
                opciones = {f"{d['patente']} ({nombre_categoria(d['categoria'])}, entró {d['ingreso'][11:16]})": d for d in dentro}
                elegido = opciones[st.selectbox("Vehículo", list(opciones))]
                cobro = base.cotizar(elegido)
                st.markdown(f"{chapa(elegido['patente'])}&nbsp;&nbsp; {formato_duracion(cobro.minutos)} adentro",
                            unsafe_allow_html=True)
                for linea in cobro.detalle:
                    st.write("• " + linea)
                st.markdown(f"### A pagar: {dinero(cobro.importe)}")
                if st.button("Registrar salida y cobrar", type="primary"):
                    ok, msg, _ = base.registrar_egreso(elegido["patente"], origen="manual", id_registro=elegido["id"])
                    avisar_y_recargar(ok, msg)

# ---------- Tarifas
with tab_tarifas:
    t1, t2 = st.columns([3, 2], gap="large")
    with t1:
        st.subheader("Tarifas vigentes")
        st.dataframe(pd.DataFrame([{"Categoría": nombre_categoria(c), "Primera hora": t.hora,
                                    f"Cada {reglas.fraccion_min} min": t.fraccion, "Estadía 24 h": t.tope_24h}
                                   for c, t in tarifas.items()]),
                     hide_index=True, width="stretch",
                     column_config={k: st.column_config.NumberColumn(f"{k} ({reglas.moneda})", format="localized")
                                    for k in ["Primera hora", f"Cada {reglas.fraccion_min} min", "Estadía 24 h"]})
        st.markdown(
            f"- La **primera hora** se cobra completa.\n"
            f"- Después, cada **fracción de {reglas.fraccion_min} minutos** que se empieza.\n"
            f"- **Tolerancia** de {reglas.tolerancia_min} minutos antes de cobrar la fracción siguiente.\n"
            f"- Cada 24 horas el importe no supera el valor de la **estadía**."
            + (f"\n- Las salidas antes de los {reglas.minutos_gratis} minutos no pagan." if reglas.minutos_gratis else "")
            + "\n\nLos precios se cambian en `config.yaml`.")
    with t2:
        st.subheader("Calculadora")
        cat = st.selectbox("Categoría", list(tarifas), format_func=nombre_categoria, key="calc_cat")
        h1, h2 = st.columns(2)
        horas = h1.number_input("Horas", 0, 200, 1)
        minutos = h2.number_input("Minutos", 0, 59, 30)
        cobro = calcular_cobro(horas * 60 + minutos, tarifas[cat], reglas)
        st.markdown(f"### {dinero(cobro.importe)}")
        for linea in cobro.detalle:
            st.write("• " + linea)

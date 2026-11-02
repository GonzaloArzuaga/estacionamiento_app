"""Sistema de estacionamiento con reconocimiento de vehículos y patentes."""
import os

import yaml

from .patentes import validar_patente, PatenteValidada
from .tarifas import calcular_cobro, cargar_tarifas, formato_dinero, formato_duracion, Tarifa, ReglasCobro
from .base_datos import BaseEstacionamiento

CARPETA_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ruta(relativa):
    """Rutas del config.yaml relativas a la carpeta del proyecto."""
    return relativa if os.path.isabs(relativa) else os.path.join(CARPETA_PROYECTO, relativa)


def cargar_config(archivo=None):
    with open(archivo or ruta("config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def abrir_base(config):
    tarifas, reglas = cargar_tarifas(config)
    ruta_db = ruta(config["base_datos"])
    os.makedirs(os.path.dirname(ruta_db), exist_ok=True)
    return BaseEstacionamiento(ruta_db, tarifas, reglas, config.get("factor_tiempo", 1))


def crear_reconocedor(config):
    from .reconocimiento import Reconocedor
    m, r = config["modelos"], config["reconocimiento"]
    ruta_vehiculos = ruta(m["vehiculos"]) if m.get("vehiculos") else None
    if ruta_vehiculos and not os.path.exists(ruta_vehiculos):
        print(f"⚠️ No se encontró el modelo de vehículos ({ruta_vehiculos}): se usará la categoría por defecto")
        ruta_vehiculos = None
    ruta_patentes = ruta(m["patentes"])
    if not os.path.exists(ruta_patentes):
        raise FileNotFoundError(f"No se encontró el detector de patentes: {ruta_patentes}\n"
                                "Entrénalo con el notebook y copia el best.pt como modelos/patentes.pt")
    return Reconocedor(ruta_vehiculos, ruta_patentes, m["ocr"], config["mapa_clases"],
                       r["conf_vehiculo"], r["conf_patente"], r["tam_imagen"],
                       max_correcciones=r["max_correcciones"])


def crear_confirmador(config):
    from .reconocimiento import Confirmador
    r = config["reconocimiento"]
    return Confirmador(r["min_lecturas"], r["ventana_seg"], r["conf_min_ocr"], r["espera_seg"],
                       config.get("categoria_por_defecto", "auto"))

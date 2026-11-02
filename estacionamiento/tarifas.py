# ==========================================
# CÁLCULO DE LA TARIFA
# ==========================================
"""
Esquema típico de un estacionamiento:

  - Se cobra la PRIMERA HORA completa, aunque el vehículo esté 10 minutos.
  - Después, cada FRACCIÓN (por defecto 15 minutos) que se empieza se cobra entera.
  - TOLERANCIA: si se pasa de una hora o fracción por pocos minutos (por defecto 5),
    no se cobra la fracción siguiente. Evita cobrar 15 minutos por pasarse 2.
  - TOPE DIARIO (estadía): cada 24 horas el importe nunca supera el valor de la estadía.
  - MINUTOS GRATIS (opcional): si sale antes de esos minutos, no paga (ej. alguien que
    entró por error y salió enseguida).

Ejemplo (auto: hora $3000, fracción $750, tolerancia 5 min):
  0:40 -> 1 hora                    = $3000
  1:04 -> 1 hora (dentro de la tolerancia) = $3000
  1:30 -> 1 hora + 2 fracciones     = $4500
  3:00 -> 1 hora + 8 fracciones     = $9000
"""
import math
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Tarifa:
    hora: float          # precio de la primera hora
    fraccion: float      # precio de cada fracción siguiente
    tope_24h: float      # precio máximo por cada 24 horas (estadía)


@dataclass
class ReglasCobro:
    primera_hora_min: int = 60
    fraccion_min: int = 15
    tolerancia_min: int = 5
    minutos_gratis: int = 0
    moneda: str = "$"


@dataclass
class Cobro:
    minutos: float
    importe: float
    detalle: list = field(default_factory=list)   # líneas legibles para el ticket


def formato_duracion(minutos):
    minutos = int(math.floor(minutos))
    dias, resto = divmod(minutos, 1440)
    horas, mins = divmod(resto, 60)
    texto = f"{horas}h {mins:02d}min"
    return f"{dias}d {texto}" if dias else texto


def formato_dinero(valor, moneda="$"):
    return f"{moneda} {valor:,.0f}".replace(",", ".")


def importe_tramo(minutos, tarifa: Tarifa, reglas: ReglasCobro):
    """Importe de un tramo de menos de 24 horas. Devuelve (importe, fracciones, se_aplicó_tope)."""
    if minutos <= 0:
        return 0.0, 0, False
    excedente = minutos - reglas.primera_hora_min
    fracciones = 0
    if excedente > reglas.tolerancia_min:
        fracciones = math.ceil((excedente - reglas.tolerancia_min) / reglas.fraccion_min)
    importe = tarifa.hora + fracciones * tarifa.fraccion
    if importe > tarifa.tope_24h:
        return tarifa.tope_24h, fracciones, True
    return importe, fracciones, False


def calcular_cobro(minutos, tarifa: Tarifa, reglas: ReglasCobro) -> Cobro:
    """Calcula cuánto debe pagar un vehículo que estuvo `minutos` minutos."""
    m = reglas.moneda
    dinero = lambda v: formato_dinero(v, m)
    if minutos <= reglas.minutos_gratis:
        return Cobro(minutos, 0.0, [f"Permanencia {formato_duracion(minutos)}: dentro de los "
                                    f"{reglas.minutos_gratis} min sin cargo"])

    dias, resto = divmod(minutos, 1440)
    dias = int(dias)
    detalle, total = [], 0.0
    if dias:
        total += dias * tarifa.tope_24h
        detalle.append(f"{dias} estadía(s) de 24 h x {dinero(tarifa.tope_24h)} = {dinero(dias * tarifa.tope_24h)}")
        # el sobrante de menos de 5 minutos después de un día completo no se cobra
        if resto <= reglas.tolerancia_min:
            resto = 0

    importe, fracciones, tope = importe_tramo(resto, tarifa, reglas)
    if resto > 0:
        if tope:
            detalle.append(f"{formato_duracion(resto)}: se aplica el tope de estadía {dinero(tarifa.tope_24h)}")
        else:
            detalle.append(f"Primera hora: {dinero(tarifa.hora)}")
            if fracciones:
                detalle.append(f"{fracciones} fracción(es) de {reglas.fraccion_min} min x "
                               f"{dinero(tarifa.fraccion)} = {dinero(fracciones * tarifa.fraccion)}")
        total += importe
    return Cobro(minutos, round(total, 2), detalle)


def minutos_entre(ingreso: datetime, egreso: datetime, factor_tiempo=1.0):
    """Minutos transcurridos. `factor_tiempo` acelera el reloj para demostraciones
    (con 60, cada minuto real cuenta como una hora)."""
    return max(0.0, (egreso - ingreso).total_seconds() / 60.0) * factor_tiempo


def cargar_tarifas(config):
    """Arma los objetos Tarifa y ReglasCobro desde el diccionario de configuración."""
    reglas = ReglasCobro(**config["cobro"])
    tarifas = {cat: Tarifa(**valores) for cat, valores in config["tarifas"].items()}
    return tarifas, reglas

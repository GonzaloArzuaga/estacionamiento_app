# ==========================================
# VALIDACIÓN Y CORRECCIÓN DE PATENTES ARGENTINAS
# ==========================================
"""
El OCR lee caracteres, pero no sabe nada de patentes argentinas. Este módulo
usa el conocimiento del formato para:
  1. Rechazar lecturas imposibles (ruido, carteles, otras cosas con letras).
  2. Corregir confusiones típicas según la posición: en un lugar donde va un
     número, una "O" seguramente es un "0"; donde va una letra, un "8" es una "B".

Formatos vigentes (L = letra, N = número):
  AUTO_VIEJA     LLL NNN     ej. ABC 123    (1995-2016)
  AUTO_MERCOSUR  LL NNN LL   ej. AB 123 CD  (2016 en adelante)
  MOTO_VIEJA     NNN LLL     ej. 123 ABC    (1995-2016)
  MOTO_MERCOSUR  L NNN LLL   ej. A 123 BCD  (2016 en adelante)
"""
import re
from dataclasses import dataclass

FORMATOS = {
    "AUTO_MERCOSUR": "LLNNNLL",
    "AUTO_VIEJA":    "LLLNNN",
    "MOTO_MERCOSUR": "LNNNLLL",
    "MOTO_VIEJA":    "NNNLLL",
}
# Cómo se escribe cada formato con espacios
AGRUPACION = {
    "AUTO_MERCOSUR": (2, 3, 2),
    "AUTO_VIEJA":    (3, 3),
    "MOTO_MERCOSUR": (1, 3, 3),
    "MOTO_VIEJA":    (3, 3),
}

# Confusiones típicas del OCR
NUMERO_A_LETRA = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B"}
LETRA_A_NUMERO = {"O": "0", "D": "0", "Q": "0", "U": "0", "I": "1", "L": "1", "J": "1",
                  "Z": "2", "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}


@dataclass
class PatenteValidada:
    texto: str            # sin espacios, ej. "AB123CD"
    formato: str          # ej. "AUTO_MERCOSUR"
    correcciones: int     # cuántos caracteres hubo que corregir
    texto_original: str   # lo que leyó el OCR

    @property
    def legible(self):
        """Con espacios, como se ve en la chapa: 'AB 123 CD'."""
        partes, i = [], 0
        for n in AGRUPACION[self.formato]:
            partes.append(self.texto[i:i + n])
            i += n
        return " ".join(partes)

    @property
    def es_moto(self):
        return self.formato.startswith("MOTO")


def limpiar(texto):
    """Mayúsculas y solo letras y números: 'ab-123 cd_' -> 'AB123CD'."""
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def ajustar_a_formato(texto, patron, max_correcciones=2):
    """Intenta encajar el texto en un patrón (ej. 'LLNNNLL') corrigiendo caracteres
    según su posición. Devuelve (texto_corregido, correcciones) o None si no encaja."""
    if len(texto) != len(patron):
        return None
    resultado, correcciones = [], 0
    for caracter, tipo in zip(texto, patron):
        if tipo == "L":
            if caracter.isalpha():
                resultado.append(caracter)
            elif caracter in NUMERO_A_LETRA:
                resultado.append(NUMERO_A_LETRA[caracter])
                correcciones += 1
            else:
                return None
        else:
            if caracter.isdigit():
                resultado.append(caracter)
            elif caracter in LETRA_A_NUMERO:
                resultado.append(LETRA_A_NUMERO[caracter])
                correcciones += 1
            else:
                return None
    if correcciones > max_correcciones:
        return None
    return "".join(resultado), correcciones


def validar_patente(texto_ocr, max_correcciones=2, solo_autos=False):
    """Devuelve una PatenteValidada si el texto corresponde a una patente argentina, o None.
    Si encaja en más de un formato, elige el que necesita menos correcciones
    (en empate, gana el formato más nuevo, que es el más común hoy)."""
    texto = limpiar(texto_ocr)
    candidatos = []
    for prioridad, (formato, patron) in enumerate(FORMATOS.items()):
        if solo_autos and formato.startswith("MOTO"):
            continue
        ajuste = ajustar_a_formato(texto, patron, max_correcciones)
        if ajuste:
            candidatos.append((ajuste[1], prioridad, formato, ajuste[0]))
    if not candidatos:
        return None
    correcciones, _, formato, corregido = min(candidatos)
    return PatenteValidada(corregido, formato, correcciones, texto)

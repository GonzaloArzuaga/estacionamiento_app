# ==========================================
# PATENTES ARGENTINAS SINTÉTICAS
# ==========================================
"""
Genera imágenes de patentes argentinas con un texto CONOCIDO. Sirven para:
  - Medir la exactitud del OCR (sabemos qué debería leer).
  - Armar una demostración completa del sistema sin tener fotos de autos argentinos:
    se "pega" una patente sintética sobre la patente real de una foto.

No reemplazan a las fotos reales (la tipografía y el desgaste no son idénticos),
pero permiten comparar modelos de OCR de forma objetiva y reproducible.
"""
import random
import string

import cv2
import numpy as np

LETRAS = string.ascii_uppercase
NUMEROS = string.digits
PATRONES = {"AUTO_MERCOSUR": "LLNNNLL", "AUTO_VIEJA": "LLLNNN", "MOTO_MERCOSUR": "LNNNLLL", "MOTO_VIEJA": "NNNLLL"}


def texto_aleatorio(formato, rng=random):
    return "".join(rng.choice(LETRAS if c == "L" else NUMEROS) for c in PATRONES[formato])


def _centrar(img, texto, y, escala, grosor, color, fuente=cv2.FONT_HERSHEY_DUPLEX, espaciado=0):
    W = img.shape[1]
    anchos = [cv2.getTextSize(c, fuente, escala, grosor)[0][0] for c in texto]
    total = sum(anchos) + espaciado * (len(texto) - 1)
    x = (W - total) // 2
    for c, a in zip(texto, anchos):
        cv2.putText(img, c, (x, y), fuente, escala, color, grosor, cv2.LINE_AA)
        x += a + espaciado


def dibujar_patente(texto, formato):
    """Imagen BGR limpia (sin ruido) de una patente."""
    if formato == "AUTO_MERCOSUR":
        img = np.full((100, 300, 3), 250, np.uint8)
        cv2.rectangle(img, (0, 0), (299, 24), (150, 70, 10), -1)                 # franja azul
        _centrar(img, "REPUBLICA ARGENTINA", 18, 0.45, 1, (255, 255, 255), cv2.FONT_HERSHEY_SIMPLEX)
        cv2.rectangle(img, (2, 2), (297, 97), (20, 20, 20), 3)
        _centrar(img, f"{texto[:2]} {texto[2:5]} {texto[5:]}", 84, 1.5, 4, (15, 15, 15), espaciado=3)
    elif formato == "AUTO_VIEJA":
        img = np.full((100, 300, 3), 25, np.uint8)                              # fondo negro
        cv2.rectangle(img, (4, 4), (295, 95), (220, 220, 220), 2)
        _centrar(img, "ARGENTINA", 24, 0.5, 1, (220, 220, 220), cv2.FONT_HERSHEY_SIMPLEX)
        _centrar(img, f"{texto[:3]} {texto[3:]}", 82, 1.9, 4, (235, 235, 235), espaciado=4)
    elif formato == "MOTO_MERCOSUR":
        img = np.full((160, 200, 3), 250, np.uint8)
        cv2.rectangle(img, (0, 0), (199, 26), (150, 70, 10), -1)
        _centrar(img, "ARGENTINA", 19, 0.5, 1, (255, 255, 255), cv2.FONT_HERSHEY_SIMPLEX)
        cv2.rectangle(img, (2, 2), (197, 157), (20, 20, 20), 3)
        _centrar(img, f"{texto[0]} {texto[1:4]}", 82, 1.5, 4, (15, 15, 15), espaciado=3)
        _centrar(img, texto[4:], 140, 1.5, 4, (15, 15, 15), espaciado=3)
    else:  # MOTO_VIEJA
        img = np.full((160, 200, 3), 25, np.uint8)
        cv2.rectangle(img, (4, 4), (195, 155), (220, 220, 220), 2)
        _centrar(img, texto[:3], 75, 1.6, 4, (235, 235, 235), espaciado=4)
        _centrar(img, texto[3:], 138, 1.6, 4, (235, 235, 235), espaciado=4)
    return img


def degradar(img, rng=random, intensidad=1.0):
    """Simula condiciones reales: perspectiva, rotación, desenfoque, ruido, luz y baja resolución."""
    h, w = img.shape[:2]
    d = 0.06 * intensidad
    origen = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    destino = np.float32([[rng.uniform(0, d) * w, rng.uniform(0, d) * h],
                          [w - rng.uniform(0, d) * w, rng.uniform(0, d) * h],
                          [w - rng.uniform(0, d) * w, h - rng.uniform(0, d) * h],
                          [rng.uniform(0, d) * w, h - rng.uniform(0, d) * h]])
    img = cv2.warpPerspective(img, cv2.getPerspectiveTransform(origen, destino), (w, h),
                              borderMode=cv2.BORDER_REPLICATE)
    escala = rng.uniform(0.35, 0.9) if intensidad > 0 else 1
    chica = cv2.resize(img, (max(20, int(w * escala)), max(10, int(h * escala))), interpolation=cv2.INTER_AREA)
    img = cv2.resize(chica, (w, h), interpolation=cv2.INTER_LINEAR)
    k = rng.choice([1, 1, 3, 3, 5]) if intensidad > 0 else 1
    if k > 1:
        img = cv2.GaussianBlur(img, (k, k), 0)
    alfa, beta = rng.uniform(0.6, 1.3), rng.uniform(-40, 40) * intensidad
    img = cv2.convertScaleAbs(img, alpha=alfa, beta=beta)
    ruido = np.random.normal(0, 8 * intensidad, img.shape)
    return np.clip(img.astype(np.float32) + ruido, 0, 255).astype(np.uint8)


def generar(n, semilla=0, formatos=None, intensidad=1.0):
    """Devuelve una lista de (imagen_bgr, texto, formato)."""
    rng = random.Random(semilla)
    np.random.seed(semilla)
    formatos = formatos or ["AUTO_MERCOSUR", "AUTO_MERCOSUR", "AUTO_VIEJA", "MOTO_MERCOSUR", "MOTO_VIEJA"]
    salida = []
    for _ in range(n):
        formato = rng.choice(formatos)
        texto = texto_aleatorio(formato, rng)
        salida.append((degradar(dibujar_patente(texto, formato), rng, intensidad), texto, formato))
    return salida


def pegar_patente(imagen_bgr, caja, texto, formato="AUTO_MERCOSUR"):
    """Reemplaza la zona `caja` (x1, y1, x2, y2) de una foto por una patente sintética."""
    x1, y1, x2, y2 = [int(v) for v in caja]
    w, h = max(2, x2 - x1), max(2, y2 - y1)
    chapa = cv2.resize(dibujar_patente(texto, formato), (w, h), interpolation=cv2.INTER_AREA)
    salida = imagen_bgr.copy()
    salida[y1:y1 + h, x1:x1 + w] = chapa[:salida[y1:y1 + h, x1:x1 + w].shape[0], :salida[y1:y1 + h, x1:x1 + w].shape[1]]
    return salida

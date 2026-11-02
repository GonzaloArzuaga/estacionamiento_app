# ==========================================
# RECONOCIMIENTO: VEHÍCULO + PATENTE + OCR
# ==========================================
"""
Por cada cuadro de video:
  1. El modelo de VEHÍCULOS (el del proyecto anterior) encuentra los vehículos y su tipo.
  2. El modelo de PATENTES (entrenado en este proyecto) encuentra las patentes.
  3. Cada patente se asigna al vehículo que la contiene.
  4. Se recorta cada patente y el OCR lee sus caracteres.
  5. El texto se valida y corrige con el formato argentino (patentes.py).

Como un solo cuadro puede salir borroso, el Confirmador acumula lecturas de varios
cuadros y solo "confirma" una patente cuando se leyó igual varias veces.
"""
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass

import cv2
import numpy as np

from .patentes import validar_patente


@dataclass
class Lectura:
    caja_patente: tuple            # (x1, y1, x2, y2) en píxeles
    conf_patente: float            # confianza del detector de patentes
    texto_ocr: str                 # lo que leyó el OCR
    conf_ocr: float                # confianza promedio de los caracteres
    patente: str = None            # texto validado (None si no es una patente argentina)
    patente_legible: str = None
    formato: str = None
    caja_vehiculo: tuple = None
    clase_vehiculo: str = None     # lo que dijo el modelo de vehículos (ej. "auto")
    conf_vehiculo: float = None
    categoria: str = None          # categoría tarifaria (ej. "auto", "moto")


def _contiene(caja_grande, caja_chica):
    cx = (caja_chica[0] + caja_chica[2]) / 2
    cy = (caja_chica[1] + caja_chica[3]) / 2
    return caja_grande[0] <= cx <= caja_grande[2] and caja_grande[1] <= cy <= caja_grande[3]


def _area(c):
    return max(0, c[2] - c[0]) * max(0, c[3] - c[1])


class Reconocedor:
    def __init__(self, modelo_vehiculos, modelo_patentes, modelo_ocr="cct-s-v2-global-model",
                 mapa_clases=None, conf_vehiculo=0.4, conf_patente=0.4, tam_imagen=640,
                 ancho_min_patente=30, max_correcciones=2, dispositivo=None):
        from ultralytics import YOLO
        from fast_plate_ocr import LicensePlateRecognizer

        self.modelo_vehiculos = YOLO(str(modelo_vehiculos)) if modelo_vehiculos else None
        self.modelo_patentes = YOLO(str(modelo_patentes))
        self.ocr = LicensePlateRecognizer(modelo_ocr, device="cpu")
        self.ocr_en_gris = self.ocr.config.image_color_mode == "grayscale"
        self.mapa_clases = {str(k).lower(): v for k, v in (mapa_clases or {}).items()}
        self.conf_vehiculo = conf_vehiculo
        self.conf_patente = conf_patente
        self.tam_imagen = tam_imagen
        self.ancho_min_patente = ancho_min_patente
        self.max_correcciones = max_correcciones
        self.dispositivo = dispositivo

    def categoria_de(self, clase):
        """Traduce la clase del modelo de vehículos a una categoría tarifaria (o None si no se admite)."""
        return self.mapa_clases.get(str(clase).lower()) if clase else None

    def leer_patentes(self, recortes_bgr):
        """OCR sobre una lista de recortes BGR. Devuelve [(texto, confianza)]."""
        if not recortes_bgr:
            return []
        conv = cv2.COLOR_BGR2GRAY if self.ocr_en_gris else cv2.COLOR_BGR2RGB
        imagenes = [cv2.cvtColor(r, conv) for r in recortes_bgr]
        predicciones = self.ocr.run(imagenes, return_confidence=True)
        salida = []
        for p in predicciones:
            texto = p.plate.replace(self.ocr.config.pad_char, "")
            probs = np.asarray(p.char_probs).reshape(-1)[:max(len(texto), 1)] if p.char_probs is not None else [0]
            salida.append((texto, float(np.mean(probs))))
        return salida

    def procesar(self, cuadro_bgr):
        """Analiza un cuadro y devuelve una lista de Lectura (una por patente encontrada)."""
        H, W = cuadro_bgr.shape[:2]
        kw = dict(imgsz=self.tam_imagen, verbose=False)
        if self.dispositivo is not None:
            kw["device"] = self.dispositivo

        # 1) Vehículos
        vehiculos = []
        if self.modelo_vehiculos is not None:
            r = self.modelo_vehiculos.predict(cuadro_bgr, conf=self.conf_vehiculo, **kw)[0]
            for caja, cls, conf in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(),
                                       r.boxes.conf.cpu().numpy()):
                clase = r.names[int(cls)]
                categoria = self.categoria_de(clase)
                if categoria:                       # se ignoran aviones, trenes, etc.
                    vehiculos.append((tuple(caja.tolist()), clase, float(conf), categoria))

        # 2) Patentes
        r = self.modelo_patentes.predict(cuadro_bgr, conf=self.conf_patente, **kw)[0]
        cajas, recortes, confs = [], [], []
        for caja, conf in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
            x1, y1, x2, y2 = caja
            if x2 - x1 < self.ancho_min_patente:    # demasiado chica para leerla
                continue
            mx, my = (x2 - x1) * 0.04, (y2 - y1) * 0.08   # pequeño margen alrededor de la chapa
            a = (int(max(0, x1 - mx)), int(max(0, y1 - my)), int(min(W, x2 + mx)), int(min(H, y2 + my)))
            recortes.append(cuadro_bgr[a[1]:a[3], a[0]:a[2]])
            cajas.append(tuple(caja.tolist()))
            confs.append(float(conf))

        # 3) OCR + validación + asignación al vehículo
        lecturas = []
        for caja, conf, (texto, conf_ocr) in zip(cajas, confs, self.leer_patentes(recortes)):
            lec = Lectura(caja, conf, texto, conf_ocr)
            valida = validar_patente(texto, self.max_correcciones)
            if valida:
                lec.patente, lec.patente_legible, lec.formato = valida.texto, valida.legible, valida.formato
            candidatos = [v for v in vehiculos if _contiene(v[0], caja)]
            if candidatos:
                v = min(candidatos, key=lambda v: _area(v[0]))   # el vehículo más chico que la contiene
                lec.caja_vehiculo, lec.clase_vehiculo, lec.conf_vehiculo, lec.categoria = v
            if valida and valida.es_moto:
                lec.categoria = "moto"              # el formato de la chapa confirma que es moto
            lecturas.append(lec)
        return lecturas, vehiculos


def dibujar(cuadro_bgr, lecturas, vehiculos=()):
    """Dibuja vehículos (azul) y patentes (verde si es válida, rojo si no)."""
    img = cuadro_bgr.copy()
    for caja, clase, conf, categoria in vehiculos:
        x1, y1, x2, y2 = map(int, caja)
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 140, 0), 2)
        _etiqueta(img, f"{clase} {conf:.0%}", x1, y1, (255, 140, 0))
    for lec in lecturas:
        x1, y1, x2, y2 = map(int, lec.caja_patente)
        color = (0, 200, 0) if lec.patente else (0, 0, 230)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        texto = f"{lec.patente_legible} {lec.conf_ocr:.0%}" if lec.patente else f"? {lec.texto_ocr}"
        _etiqueta(img, texto, x1, y2 + 26, color)
    return img


def _etiqueta(img, texto, x, y, color):
    (tw, th), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    y = max(y, th + 8)
    cv2.rectangle(img, (x, y - th - 8), (x + tw + 8, y + 2), color, -1)
    cv2.putText(img, texto, (x + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def distancia(a, b):
    """Cantidad de caracteres distintos entre dos patentes del mismo largo (distancia de Hamming).
    Si tienen distinto largo, se consideran completamente distintas."""
    if not a or not b or len(a) != len(b):
        return 99
    return sum(x != y for x, y in zip(a, b))


def parecidas(a, b, max_dif=2):
    """True si dos lecturas probablemente son la MISMA patente leída con algún error."""
    return distancia(a, b) <= max_dif


class Confirmador:
    """Junta las lecturas de varios cuadros y confirma UNA patente por vehículo.

    Problema que resuelve: frente a la cámara, el OCR puede leer la misma chapa de formas
    levemente distintas según el cuadro (FIN678, FKM678, FIM678...). Si se confirmara cada
    variante por separado, un solo auto generaría varios ingresos.

    Cómo funciona:
      1. Agrupa las lecturas de los últimos `ventana_seg` segundos que se parecen entre sí
         (mismo largo y como máximo `max_dif` caracteres distintos): son el mismo vehículo.
      2. Cuando un grupo junta `min_lecturas` lecturas, arma la patente final votando
         CARÁCTER POR CARÁCTER (cada posición toma la letra o número más leído, ponderado
         por la confianza del OCR).
      3. Durante `espera_seg` segundos ignora cualquier lectura parecida a una patente ya
         confirmada (hasta `max_dif_bloqueo` caracteres distintos), para no registrar dos veces
         el mismo vehículo mientras sigue frente a la cámara. El criterio es más amplio que el de
         agrupación porque con reflejos o poca luz el OCR puede errar hasta 3 caracteres.
    """

    def __init__(self, min_lecturas=3, ventana_seg=4.0, conf_min_ocr=0.6, espera_seg=30.0,
                 categoria_por_defecto="auto", max_dif=2, max_dif_bloqueo=3):
        self.min_lecturas = min_lecturas
        self.ventana_seg = ventana_seg
        self.conf_min_ocr = conf_min_ocr
        self.espera_seg = espera_seg
        self.categoria_por_defecto = categoria_por_defecto
        self.max_dif = max_dif
        self.max_dif_bloqueo = max_dif_bloqueo
        self.historial = deque()                     # (tiempo, Lectura)
        self.confirmadas = {}                        # patente -> momento de confirmación

    def reiniciar(self):
        self.historial.clear()
        self.confirmadas.clear()

    def _ya_confirmada(self, patente):
        return any(parecidas(patente, p, self.max_dif_bloqueo) for p in self.confirmadas)

    def _agrupar(self):
        """Agrupa las lecturas del historial por similitud, empezando por las más leídas."""
        conteo = Counter(l.patente for _, l in self.historial)
        grupos = []                                  # [(representante, [lecturas])]
        for patente, _ in conteo.most_common():
            for rep, miembros in grupos:
                if parecidas(patente, rep, self.max_dif):
                    miembros.extend(l for _, l in self.historial if l.patente == patente)
                    break
            else:
                grupos.append((patente, [l for _, l in self.historial if l.patente == patente]))
        return grupos

    @staticmethod
    def _votar(lecturas):
        """Patente final: en cada posición gana el carácter con más votos (ponderados por confianza)."""
        largo = Counter(len(l.patente) for l in lecturas).most_common(1)[0][0]
        validas = [l for l in lecturas if len(l.patente) == largo]
        caracteres = []
        for i in range(largo):
            votos = defaultdict(float)
            for l in validas:
                votos[l.patente[i]] += max(l.conf_ocr, 0.05)
            caracteres.append(max(votos, key=votos.get))
        return "".join(caracteres)

    def actualizar(self, lecturas, ahora=None):
        """Agrega las lecturas del cuadro actual. Devuelve una lista de confirmaciones nuevas:
        dicts con patente, patente_legible, categoria, clase_vehiculo, confianza, lecturas, variantes."""
        ahora = time.time() if ahora is None else ahora
        for p in [p for p, t in self.confirmadas.items() if ahora - t > self.espera_seg]:
            del self.confirmadas[p]
        for lec in lecturas:
            if lec.patente and lec.conf_ocr >= self.conf_min_ocr and not self._ya_confirmada(lec.patente):
                self.historial.append((ahora, lec))
        while self.historial and ahora - self.historial[0][0] > self.ventana_seg:
            self.historial.popleft()

        nuevas = []
        for _, lecs in self._agrupar():
            if len(lecs) < self.min_lecturas:
                continue
            patente = self._votar(lecs)
            valida = validar_patente(patente, max_correcciones=0)
            if not valida:                           # el voto armó algo inválido: se usa la lectura más repetida
                patente = Counter(l.patente for l in lecs).most_common(1)[0][0]
                valida = validar_patente(patente, max_correcciones=0)
            if self._ya_confirmada(patente):
                continue
            categorias = Counter(l.categoria for l in lecs if l.categoria)
            clases = Counter(l.clase_vehiculo for l in lecs if l.clase_vehiculo)
            if valida and valida.es_moto:
                categorias = Counter({"moto": 1})
            nuevas.append({
                "patente": patente,
                "patente_legible": valida.legible if valida else patente,
                "categoria": categorias.most_common(1)[0][0] if categorias else self.categoria_por_defecto,
                "clase_vehiculo": clases.most_common(1)[0][0] if clases else None,
                "confianza": float(np.mean([l.conf_ocr for l in lecs])),
                "lecturas": len(lecs),
                "variantes": sorted({l.patente for l in lecs}),
            })
            self.confirmadas[patente] = ahora
        if nuevas:                                   # se descartan del historial las lecturas ya usadas
            self.historial = deque((t, l) for t, l in self.historial if not self._ya_confirmada(l.patente))
        return nuevas

    def progreso(self):
        """Grupo más leído en la ventana actual y cuántas lecturas lleva (para mostrar en pantalla)."""
        grupos = self._agrupar()
        if not grupos:
            return None
        rep, lecs = max(grupos, key=lambda g: len(g[1]))
        return self._votar(lecs), len(lecs)

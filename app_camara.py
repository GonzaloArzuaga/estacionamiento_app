# ==========================================
# APP DE CÁMARA: registra ingresos y egresos por patente
# ==========================================
"""
Uso (desde una terminal, dentro de la carpeta del proyecto):

  python app_camara.py                      # webcam, empieza en modo ENTRADA
  python app_camara.py --modo salida        # webcam, empieza en modo SALIDA
  python app_camara.py --video autos.mp4    # procesa un video en vez de la webcam

Con dos cámaras reales (una en cada pasarela) se abren dos ventanas:
  python app_camara.py --camara 0 --modo entrada --fijo
  python app_camara.py --camara 1 --modo salida  --fijo

Teclas:  E = modo entrada | S = modo salida | C = limpiar mensaje | Q o ESC = salir
"""
import argparse
import os
import time
import unicodedata
from datetime import datetime

import cv2

from estacionamiento import (abrir_base, cargar_config, crear_confirmador, crear_reconocedor,
                             formato_dinero, ruta)
from estacionamiento.reconocimiento import dibujar

VERDE, NARANJA, ROJO, BLANCO, NEGRO = (60, 180, 60), (0, 140, 255), (40, 40, 220), (255, 255, 255), (0, 0, 0)


def ascii(texto):
    """OpenCV no dibuja tildes: 'fracción' -> 'fraccion'."""
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()


def texto(img, t, x, y, escala=0.7, color=BLANCO, grosor=2):
    cv2.putText(img, ascii(t), (x, y), cv2.FONT_HERSHEY_SIMPLEX, escala, NEGRO, grosor + 3, cv2.LINE_AA)
    cv2.putText(img, ascii(t), (x, y), cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)


def panel(img, x, y, ancho, alto, color, opacidad=0.75):
    h, w = img.shape[:2]
    x2, y2 = min(w, x + ancho), min(h, y + alto)
    zona = img[y:y2, x:x2]
    fondo = zona.copy()
    fondo[:] = color
    img[y:y2, x:x2] = cv2.addWeighted(fondo, opacidad, zona, 1 - opacidad, 0)


def dibujar_interfaz(img, nombre, modo, fps, progreso, mensaje, fijo, min_lecturas):
    h, w = img.shape[:2]
    color_modo = VERDE if modo == "entrada" else NARANJA
    panel(img, 0, 0, w, 50, color_modo, 0.85)
    texto(img, f"{nombre}  |  {modo.upper()}", 12, 34, 0.9)
    texto(img, f"{fps:4.1f} FPS", w - 130, 34, 0.7)
    ayuda = "Q salir" if fijo else "E entrada | S salida | Q salir"
    texto(img, ayuda, 12, h - 14, 0.55)
    if progreso:
        patente, n = progreso
        texto(img, f"Leyendo {patente} ({min(n, min_lecturas)}/{min_lecturas})", 12, 80, 0.7, (200, 255, 255))
    if mensaje:
        lineas, color = mensaje["lineas"], mensaje["color"]
        alto = 28 + 34 * len(lineas)
        y0 = h - alto - 40
        panel(img, 10, y0, min(w - 20, 620), alto, color, 0.85)
        for i, linea in enumerate(lineas):
            destacada = linea.startswith("A PAGAR")
            texto(img, linea, 24, y0 + 34 + 34 * i, 0.95 if destacada or i == 0 else 0.7,
                  (80, 255, 255) if destacada else BLANCO)


def guardar_foto(carpeta, cuadro, modo, patente):
    os.makedirs(carpeta, exist_ok=True)
    archivo = os.path.join(carpeta, f"{datetime.now():%Y%m%d_%H%M%S}_{modo}_{patente}.jpg")
    cv2.imwrite(archivo, cuadro)
    return archivo


GRIS = (110, 110, 110)


def procesar_confirmacion(base, conf, modo, cuadro, carpeta_fotos, moneda):
    foto = guardar_foto(carpeta_fotos, cuadro, modo, conf["patente"])
    if modo == "entrada":
        ok, msg, reg = base.registrar_ingreso(conf["patente"], conf["categoria"], conf["clase_vehiculo"],
                                              conf["confianza"], foto)
        if ok:
            lineas = [f"BIENVENIDO  {conf['patente_legible']}",
                      f"{conf['categoria']}  -  ingreso {datetime.now():%H:%M}",
                      "Barrera abierta"]
            return {"lineas": lineas, "color": VERDE}
    else:
        ok, msg, ticket = base.registrar_egreso(conf["patente"], conf["confianza"], foto)
        if ok:
            lineas = [f"{ticket['patente']}  -  {ticket['categoria']}",
                      f"Ingreso {ticket['ingreso'][11:16]}  Egreso {ticket['egreso'][11:16]}  ({ticket['permanencia']})"]
            if ticket.get("patente_salida"):
                lineas.append(f"(en la salida se leyo {ticket['patente_salida']})")
            lineas += ticket["detalle"][:3]
            lineas.append(f"A PAGAR: {ticket['importe_texto']}")
            return {"lineas": lineas, "color": (90, 60, 20)}
    # No se registró: una relectura del mismo vehículo es informativa (gris); lo demás es una alerta (rojo)
    if base.ultimo_estado == "repetido":
        try:
            os.remove(foto)                  # no se guarda la foto de una relectura
        except OSError:
            pass
        return {"lineas": [f"YA REGISTRADO  {conf['patente_legible']}", msg[:64]], "color": GRIS}
    return {"lineas": [f"ATENCION  {conf['patente_legible']}", msg[:64]], "color": ROJO}


def main():
    p = argparse.ArgumentParser(description="Cámara de entrada/salida del estacionamiento")
    p.add_argument("--modo", choices=["entrada", "salida"], default="entrada")
    p.add_argument("--fijo", action="store_true", help="no permite cambiar de modo con el teclado")
    p.add_argument("--camara", type=int, default=0, help="número de cámara (0 = la de la notebook)")
    p.add_argument("--video", help="procesar un archivo de video en vez de la cámara")
    p.add_argument("--config", help="archivo de configuración (por defecto config.yaml)")
    p.add_argument("--sin-ventana", action="store_true", help="no muestra ventana (pruebas)")
    p.add_argument("--max-cuadros", type=int, default=0)
    args = p.parse_args()

    config = cargar_config(args.config)
    base = abrir_base(config)
    print("Cargando modelos...")
    reconocedor = crear_reconocedor(config)
    confirmador = crear_confirmador(config)
    carpeta_fotos = ruta(config["carpeta_fotos"])
    nombre = config.get("nombre_estacionamiento", "Estacionamiento")
    moneda = config["cobro"].get("moneda", "$")
    min_lect = config["reconocimiento"]["min_lecturas"]

    fuente = args.video if args.video else args.camara
    captura = cv2.VideoCapture(fuente)
    if not captura.isOpened():
        raise SystemExit(f"No se pudo abrir {'el video' if args.video else 'la cámara'} {fuente}. "
                         "Cierra Zoom/Meet/Teams o prueba con --camara 1.")
    ventana = f"{nombre} - camara {fuente}"
    if not args.sin_ventana:
        cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)

    modo, mensaje, hasta, fps, anterior, cuadros = args.modo, None, 0, 0.0, time.time(), 0
    print(f"Listo. Modo {modo.upper()}.")
    while True:
        ok, cuadro = captura.read()
        if not ok:
            break
        lecturas, vehiculos = reconocedor.procesar(cuadro)
        for conf in confirmador.actualizar(lecturas):
            anotado = dibujar(cuadro, lecturas, vehiculos)
            mensaje = procesar_confirmacion(base, conf, modo, anotado, carpeta_fotos, moneda)
            hasta = time.time() + 8
            print(" | ".join(ascii(l) for l in mensaje["lineas"]))

        ahora = time.time()
        fps = 0.9 * fps + 0.1 * (1 / max(ahora - anterior, 1e-6))
        anterior = ahora
        if mensaje and ahora > hasta:
            mensaje = None

        if not args.sin_ventana:
            img = dibujar(cuadro, lecturas, vehiculos)
            dibujar_interfaz(img, nombre, modo, fps, confirmador.progreso(), mensaje, args.fijo, min_lect)
            cv2.imshow(ventana, img)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            if not args.fijo and tecla in (ord("e"), ord("E"), ord("s"), ord("S")):
                nuevo = "entrada" if tecla in (ord("e"), ord("E")) else "salida"
                if nuevo != modo:
                    modo = nuevo
                    confirmador.reiniciar()
                    mensaje = None
                    print(f"Modo {modo.upper()}")
            if tecla in (ord("c"), ord("C")):
                mensaje = None
        cuadros += 1
        if args.max_cuadros and cuadros >= args.max_cuadros:
            break

    captura.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

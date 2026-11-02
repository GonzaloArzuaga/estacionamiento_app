   @echo off
   title Estacionamiento Inteligente
   cd /d "%~dp0"
   echo Abriendo el panel de control en el navegador...
   start "Panel del estacionamiento" cmd /k python -m streamlit run panel.py
   echo Abriendo la camara (E = entrada, S = salida, Q = salir)...
   python app_camara.py
   echo.
   echo La camara se cerro. Para cerrar el panel, cierra su ventana negra.
   pause
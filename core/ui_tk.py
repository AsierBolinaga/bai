"""
Ventana de chat de B.A.I con tkinter (fase 8): zona de conversación, entrada,
barra de estado y botones de modo. Toda la lógica vive en ControladorChat; aquí
sólo se dibuja. Los mensajes se procesan en un hilo para no congelar la ventana
y el resultado vuelve al hilo de Tk por una cola, nunca llamando a Tk desde el hilo.
"""
import math
import queue
import threading
import sys
from time import monotonic
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from tkinter import messagebox

from core.config import nombre_ia, master_name
from core.ayuda import DESCRIPCION_BAI
from core.ui_controlador import ControladorChat, MENSAJE_CANCELADO
from core.voz import VozLocal
from core.escucha import EscuchaLocal
from core.audio_operaciones import OperacionesAudio

INTERVALO_COLA_MS = 100
PLAZO_CIERRE_SEGUNDOS = 3
ANCHO_BARRA_ESTRECHA = 640
IDIOMAS_ESCUCHA = {"Automático": None, "Castellano": "es", "Euskera": "eu", "Inglés": "en"}

# Paleta oscura inspirada en VS Code.
COLORES = {
    "fondo": "#1e1e1e", "barra": "#252526", "entrada": "#3c3c3c", "borde": "#454545",
    "texto": "#ffffff", "texto_suave": "#d4d4d4", "tenue": "#8a8a8a", "boton": "#3a3d41", "hover": "#505357",
    "acento": "#0e639c", "acento_texto": "#4fc1ff", "usuario": "#4ec9b0", "aviso": "#e5c07b",
    "seleccion": "#264f78",
}
FUENTE_UI = ("TkDefaultFont", 10)
FUENTE_CHAT = ("TkFixedFont", 11)
FUENTE_NEGRITA = ("TkFixedFont", 11, "bold")


def _rect_redondeado(canvas, x1, y1, x2, y2, r, **kw):
    puntos = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
              x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(puntos, smooth=True, **kw)


class BotonRedondo(tk.Canvas):
    """Botón de esquinas redondeadas con estados normal/disabled y resalte al pasar el ratón."""

    RADIO = 10

    def __init__(self, padre, texto, comando, color, **kw):
        fuente = tkfont.Font(font=FUENTE_UI)
        ancho = fuente.measure(texto) + 28
        alto = fuente.metrics("linespace") + 14
        super().__init__(padre, width=ancho, height=alto, bg=padre.cget("bg"), highlightthickness=0,
                         borderwidth=0, cursor="hand2", **kw)
        self._color, self._comando, self._estado, self._encima = color, comando, "normal", False
        self._forma = _rect_redondeado(self, 1, 1, ancho - 1, alto - 1, self.RADIO, fill=color, outline=color)
        self._texto = self.create_text(ancho // 2, alto // 2, text=texto, fill=COLORES["texto_suave"],
                                       font=FUENTE_UI)
        self.bind("<Enter>", lambda _e: self._resaltar(True))
        self.bind("<Leave>", lambda _e: self._resaltar(False))
        self.bind("<ButtonRelease-1>", self._soltar)

    def _resaltar(self, encima):
        self._encima = encima
        self._pintar()

    def _pintar(self):
        color = COLORES["hover"] if self._encima and self._estado == "normal" else self._color
        self.itemconfigure(self._forma, fill=color, outline=color)
        self.itemconfigure(self._texto, fill=COLORES["texto_suave"] if self._estado == "normal" else COLORES["tenue"])
        super().configure(cursor="hand2" if self._estado == "normal" else "arrow")

    def _soltar(self, evento):
        if self._estado == "normal" and 0 <= evento.x <= self.winfo_width() and 0 <= evento.y <= self.winfo_height():
            self._comando()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._estado = kw.pop("state")
            self._pintar()
        return super().configure(cnf, **kw) if (cnf or kw) else None

    config = configure

    def cget(self, clave):
        return self._estado if clave == "state" else super().cget(clave)


class EsferaActividad(tk.Canvas):
    """Indicador local de actividad; no representa audio ni progreso del motor."""

    INTERVALO_MS = 40

    def __init__(self, padre):
        super().__init__(padre, width=220, height=44, bg=COLORES["fondo"],
                         highlightthickness=0, borderwidth=0, takefocus=0)
        self._temporizador = None
        self._fase = 0
        self._halo = self.create_oval(5, 5, 39, 39, fill="#233746", outline="")
        self._bola = self.create_oval(12, 12, 32, 32, fill=COLORES["acento"], outline="")
        self.create_oval(16, 15, 21, 20, fill=COLORES["acento_texto"], outline="")
        self._etiqueta = self.create_text(
            52, 22, text="B.A.I en reposo", anchor="w", fill=COLORES["texto_suave"], font=FUENTE_UI)
        self.bind("<Destroy>", self._al_destruir)

    def activar(self, activo, hablando=False):
        if self._temporizador is not None:
            self.after_cancel(self._temporizador)
            self._temporizador = None
        self._fase = 0
        texto = "B.A.I hablando…" if hablando else "B.A.I preparando respuesta…"
        self.itemconfigure(self._etiqueta, text=texto if activo else "B.A.I en reposo")
        if activo:
            self._animar()
        else:
            self.coords(self._halo, 5, 5, 39, 39)
            self.coords(self._bola, 12, 12, 32, 32)
            self.itemconfigure(self._bola, fill=COLORES["acento"])

    def _animar(self):
        self._fase += 0.22
        pulso = (math.sin(self._fase) + 1) / 2
        radio = 9 + 3 * pulso
        halo = 15 + 5 * pulso
        self.coords(self._bola, 22 - radio, 22 - radio, 22 + radio, 22 + radio)
        self.coords(self._halo, 22 - halo, 22 - halo, 22 + halo, 22 + halo)
        self.itemconfigure(self._bola, fill=COLORES["acento_texto"])
        self._temporizador = self.after(self.INTERVALO_MS, self._animar)

    def _al_destruir(self, evento):
        if evento.widget is self and self._temporizador is not None:
            self.after_cancel(self._temporizador)
            self._temporizador = None


class VentanaBai:
    def __init__(self, controlador=None, raiz=None, voz=None, escucha=None):
        self.controlador = controlador or ControladorChat()
        self.raiz = raiz or tk.Tk()
        self._cola = queue.Queue()
        self._cola_cierre = queue.Queue()
        self._cerrando = False
        self._cerrada = False
        self._plazo_cierre = None
        self._hilo_audio_cierre = None
        self._cola_audio_cierre = queue.Queue()
        self._resultado_audio_cierre = None
        self._resultado_cierre = None
        self._audio = OperacionesAudio()
        self._version_voz = self._version_escucha = self._version_turno = 0
        self._sondeo_audio_pendiente = False
        self._hilo_turno = None
        self._reinicio = None
        self._voz = voz if voz is not None else VozLocal()
        self._voz_activada = False
        self._hablando = False
        self._escucha = escucha if escucha is not None else EscuchaLocal()
        self._escucha_activada = False
        self._escucha_en_curso = False
        self._turno_pendiente = False
        self._construir()
        self._mostrar(nombre_ia, f"Hola, {master_name}. Memoria de sesión cargada.")
        self._actualizar_carga_local()
        self.raiz.protocol("WM_DELETE_WINDOW", self.cerrar)
        self._temporizador_cola = self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)
        self.raiz.bind("<Destroy>", self._al_destruir, add="+")

    def _construir(self):
        self.raiz.title(f"{nombre_ia} — asistente")
        self.raiz.geometry("860x600")
        self.raiz.minsize(360, 320)
        self.raiz.configure(bg=COLORES["fondo"])
        self._estilo_scroll()

        # Barra superior: la descripción ocupa el espacio sobrante y los botones pasan a una
        # segunda fila cuando la ventana es estrecha.
        self.barra = tk.Frame(self.raiz, bg=COLORES["barra"], padx=10, pady=8)
        self.barra.pack(fill="x")
        self.barra.columnconfigure(0, weight=1)
        self.etiqueta_estado = tk.Label(
            self.barra, text=DESCRIPCION_BAI, anchor="w", justify="left", bg=COLORES["barra"], fg=COLORES["texto_suave"],
            font=FUENTE_UI)
        self.etiqueta_estado.grid(row=0, column=0, sticky="ew")
        self.etiqueta_estado.bind(
            "<Configure>", lambda e: self.etiqueta_estado.configure(wraplength=max(e.width - 4, 50)))
        self.fila_botones = tk.Frame(self.barra, bg=COLORES["barra"])
        self.fila_botones.grid(row=0, column=1, sticky="e")
        self.botones_barra = []
        for texto, orden in (("Offline", "pasa a modo offline"), ("Online", "pasa a modo online"),
                             ("Estado", "estado"), ("Limpiar", "limpiar"), ("Ayuda", "ayuda")):
            boton = self._boton(self.fila_botones, texto, lambda o=orden: self.enviar(o), COLORES["boton"])
            self.botones_barra.append(boton)
        self.barra.bind("<Configure>", self._reordenar_barra)
        self.fila_carga = tk.Frame(self.barra, bg=COLORES["barra"])
        self.fila_carga.columnconfigure(0, weight=1)
        self.estado_carga = tk.Label(
            self.fila_carga, anchor="w", justify="left", wraplength=220,
            bg=COLORES["barra"], fg=COLORES["aviso"], font=FUENTE_UI)
        self.estado_carga.grid(row=0, column=0, sticky="ew")
        self.estado_carga.bind(
            "<Configure>", lambda e: self.estado_carga.configure(wraplength=max(e.width - 4, 50)))
        self.boton_cancelar_carga = self._boton(
            self.fila_carga, "Cancelar carga", self.controlador.cancelar_carga_local, COLORES["boton"])
        self.boton_cancelar_carga.grid(row=0, column=1, padx=(6, 0))

        # El pie se empaqueta antes que el chat para conservarse al encoger la ventana.
        pie = tk.Frame(self.raiz, bg=COLORES["fondo"], padx=10, pady=6)
        pie.pack(side="bottom", fill="x")
        pie.columnconfigure(0, weight=1)
        self.esfera = EsferaActividad(pie)
        self.esfera.grid(row=0, column=0, sticky="w")
        self.boton_voz = self._boton(pie, "Voz: ON" if self._voz_activada else "Voz: OFF",
                                    self._alternar_voz, COLORES["boton"])
        self.boton_voz.grid(row=0, column=1, padx=(8, 0), pady=(0, 4))
        self.boton_escucha = self._boton(pie, "Escucha: OFF", self._alternar_escucha, COLORES["boton"])
        self.boton_escucha.grid(row=1, column=1, padx=(8, 0), pady=(0, 4))
        fila_escucha = tk.Frame(pie, bg=COLORES["fondo"])
        fila_escucha.grid(row=1, column=0, sticky="ew")
        self.idioma_escucha = ttk.Combobox(
            fila_escucha, values=list(IDIOMAS_ESCUCHA), state="readonly", width=10, style="Bai.TCombobox")
        self.idioma_escucha.set("Automático")
        self.idioma_escucha.pack(side="left", padx=(0, 6))
        self.idioma_escucha.bind("<<ComboboxSelected>>", self._cambiar_idioma_escucha)
        self.estado_escucha = tk.Label(
            fila_escucha, text="Escucha OFF", width=1, anchor="w",
            bg=COLORES["fondo"], fg=COLORES["texto_suave"], font=FUENTE_UI)
        self.estado_escucha.pack(side="left", fill="x", expand=True)
        alto_entrada = tkfont.Font(font=FUENTE_UI).metrics("linespace") + 16
        self.marco_entrada = tk.Canvas(
            pie, bg=COLORES["fondo"], width=100, height=alto_entrada,
            highlightthickness=0, borderwidth=0, takefocus=0)
        self.marco_entrada.grid(row=2, column=0, sticky="ew")
        self._borde_entrada = _rect_redondeado(
            self.marco_entrada, 2, 2, 98, alto_entrada - 2, 10,
            fill=COLORES["entrada"], outline=COLORES["borde"])
        self.entrada = tk.Entry(
            self.marco_entrada, bg=COLORES["entrada"], fg=COLORES["texto"], insertbackground=COLORES["texto"],
            disabledbackground=COLORES["entrada"], disabledforeground=COLORES["tenue"], relief="flat",
            highlightthickness=0, borderwidth=0,
            font=FUENTE_UI)
        self._ventana_entrada = self.marco_entrada.create_window(
            12, alto_entrada / 2, window=self.entrada, anchor="w", width=76)
        self.marco_entrada.bind("<Configure>", self._ajustar_entrada)
        self.marco_entrada.bind("<Button-1>", lambda _e: self.entrada.focus_set())
        self.entrada.bind("<FocusIn>", lambda _e: self.marco_entrada.itemconfigure(
            self._borde_entrada, outline=COLORES["acento"]))
        self.entrada.bind("<FocusOut>", lambda _e: self.marco_entrada.itemconfigure(
            self._borde_entrada, outline=COLORES["borde"]))
        self.entrada.bind("<Return>", lambda _e: self.enviar())
        self.boton_enviar = self._boton(pie, "Enviar", self.enviar, COLORES["acento"])
        self.boton_enviar.grid(row=2, column=1, padx=(8, 0), sticky="ns")
        self.boton_cancelar = self._boton(pie, "Cancelar", self.cancelar, COLORES["boton"])
        self.boton_cancelar.grid(row=2, column=1, padx=(8, 0), sticky="ns")
        self.boton_cancelar.grid_remove()
        self.raiz.bind("<Escape>", lambda _e: self.cancelar())

        centro = tk.Frame(self.raiz, bg=COLORES["fondo"])
        centro.pack(fill="both", expand=True)
        self.chat = tk.Text(
            centro, wrap="word", state="disabled", padx=14, pady=10, bg=COLORES["fondo"],
            fg=COLORES["texto"], insertbackground=COLORES["texto"], relief="flat", borderwidth=0,
            highlightthickness=0, font=FUENTE_CHAT, spacing3=2, selectbackground=COLORES["seleccion"])
        scroll = ttk.Scrollbar(centro, command=self.chat.yview, style="Bai.Vertical.TScrollbar")
        self.chat.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)
        self.chat.tag_configure("autor", font=FUENTE_NEGRITA, foreground=COLORES["acento_texto"])
        self.chat.tag_configure("autor_usuario", font=FUENTE_NEGRITA, foreground=COLORES["usuario"])
        self.chat.tag_configure("aviso", foreground=COLORES["aviso"])
        self.entrada.focus_set()

    def _boton(self, padre, texto, comando, color):
        return BotonRedondo(padre, texto, comando, color)

    def _ajustar_entrada(self, evento):
        temporal = _rect_redondeado(
            self.marco_entrada, 2, 2, evento.width - 2, evento.height - 2, 10)
        self.marco_entrada.coords(self._borde_entrada, *self.marco_entrada.coords(temporal))
        self.marco_entrada.delete(temporal)
        self.marco_entrada.coords(self._ventana_entrada, 12, evento.height / 2)
        self.marco_entrada.itemconfigure(self._ventana_entrada, width=max(1, evento.width - 24))

    def _estilo_scroll(self):
        estilo = ttk.Style(self.raiz)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure(
            "Bai.Vertical.TScrollbar", background=COLORES["boton"], troughcolor=COLORES["fondo"],
            bordercolor=COLORES["fondo"], arrowcolor=COLORES["texto"], lightcolor=COLORES["boton"],
            darkcolor=COLORES["boton"], gripcount=0)
        estilo.map("Bai.Vertical.TScrollbar", background=[("active", COLORES["hover"])])
        estilo.map("Bai.TCombobox",
                   fieldbackground=[("readonly", COLORES["entrada"])],
                   foreground=[("readonly", COLORES["texto"])])

    def _reordenar_barra(self, evento):
        estrecha = evento.width < ANCHO_BARRA_ESTRECHA
        columnas = 3 if evento.width < 500 else 5
        disposicion = (estrecha, columnas)
        if disposicion == getattr(self, "_disposicion_barra", None):
            return
        self._disposicion_barra = disposicion
        for i, boton in enumerate(self.botones_barra):
            boton.grid(row=i // columnas, column=i % columnas, padx=(6, 0), pady=2)
        if estrecha:
            self.fila_botones.grid_configure(row=1, column=0, sticky="ew", pady=(6, 0))
        else:
            self.fila_botones.grid_configure(row=0, column=1, sticky="e", pady=0)

    # ---------------------------------------------------------------- acciones
    def enviar(self, texto=None):
        if self._cerrando or self.controlador.ocupado or self._turno_pendiente:
            return
        if texto is None:
            texto = self.entrada.get().strip()
            if texto:
                self.entrada.delete(0, "end")
        if not texto:
            return
        from core.reinicio import aviso_reinicio, modo_reinicio
        modo = modo_reinicio(texto)
        if modo is not None:
            self._pausar_escucha()
            if messagebox.askyesno("Cambiar de modo", aviso_reinicio(modo), parent=self.raiz):
                self._reinicio = modo
                self.cerrar()
            return
        if texto.lower() in ("salir", "exit", "quit", "irten", "atera", "amaitu"):
            self.cerrar()
            return
        self._marcar_pausa_escucha()
        self._version_voz += 1
        self._hablando = False
        self._mostrar(master_name, texto)
        self._bloquear(True)
        self._turno_pendiente = True
        self._version_turno += 1
        version = self._version_turno

        def enviar_tras_pausa(_valor, error):
            if version != self._version_turno:
                return
            if error:
                self._turno_pendiente = False
                self._bloquear(False)
                self._mostrar("aviso", f"No he podido preparar el audio para enviar: {error}", "aviso")
                self._voz_activada = self._hablando = False
                self.boton_voz.itemconfigure(self.boton_voz._texto, text="Voz: OFF")
                self._desactivar_escucha()
                self._limpiar_error_audio("voz")
                return
            self._hilo_turno = self.controlador.enviar_en_hilo(texto, self._cola.put)

        def preparar():
            self._escucha.pausar()
            self._voz.pausar()

        self._audio.enviar(preparar, enviar_tras_pausa)

    def cancelar(self):
        if self._cerrando:
            return
        if not self.controlador.ocupado:
            if self._turno_pendiente:
                self._version_turno += 1
                self._turno_pendiente = False
                self._bloquear(False)
                self._mostrar("aviso", MENSAJE_CANCELADO, "aviso")
                return
            self.controlador.cancelar_carga_local()
            return
        self.controlador.cancelar()
        self.boton_cancelar.configure(state="disabled")
        self._mostrar("aviso", "Cancelando la generación…", "aviso")

    def cerrar(self):
        if self._cerrando:
            return
        self._cerrando = True
        self._version_turno += 1
        self._turno_pendiente = False
        self._plazo_cierre = monotonic() + PLAZO_CIERRE_SEGUNDOS
        self.controlador.cancelar()
        self.controlador.cancelar_carga_local()
        self.boton_cancelar_carga.configure(state="disabled")
        self._escucha_activada = self._escucha_en_curso = False
        self._voz_activada = self._hablando = False
        self.boton_escucha.itemconfigure(self.boton_escucha._texto, text="Escucha: OFF")
        self.boton_voz.itemconfigure(self.boton_voz._texto, text="Voz: OFF")
        self.estado_escucha.configure(text="Escucha OFF")
        self.esfera.activar(False)
        self.entrada.configure(state="disabled")
        self.boton_enviar.configure(state="disabled")
        self.boton_cancelar.configure(state="disabled")
        for boton in self.botones_barra + [self.boton_voz, self.boton_escucha]:
            boton.configure(state="disabled")
        self.idioma_escucha.configure(state="disabled")
        self._mostrar("aviso", "Cerrando: cancelo la generación, cierro el audio y guardo los turnos completados.", "aviso")
        if self._resultado_audio_cierre is not None and not self._resultado_audio_cierre[0]:
            self._hilo_audio_cierre = None
            self._resultado_audio_cierre = None
        self._iniciar_cierre_audio()
        self._resultado_cierre = None
        cola_cierre = self._cola_cierre = queue.Queue()

        # Esperar el cerrojo o el disco nunca debe bloquear el hilo de Tk.
        def guardar():
            try:
                guardado = self.controlador.cerrar()
            except Exception as error:
                cola_cierre.put((False, str(error)))
            else:
                cola_cierre.put((bool(guardado), None))

        threading.Thread(target=guardar, name="bai-ui-cierre", daemon=True).start()

    def _iniciar_cierre_audio(self):
        if self._hilo_audio_cierre is not None:
            return
        voz, escucha = self._voz, self._escucha
        cola = self._cola_audio_cierre

        def limpiar():
            errores = []
            for nombre, recurso in (("micrófono", escucha), ("voz", voz)):
                try:
                    recurso.detener()
                except Exception as error:
                    errores.append(f"{nombre}: {error}")
            detalle = "; ".join(errores) or None
            if detalle:
                print(f"[B.A.I] No se pudo cerrar el audio: {detalle}", file=sys.stderr)
            cola.put((not errores, detalle))

        self._hilo_audio_cierre = self._audio.cerrar(limpiar)

    def _al_destruir(self, evento):
        if evento.widget is self.raiz:
            self._cerrada = True
            self.controlador.cancelar()
            self.controlador.cancelar_carga_local()
            self._iniciar_cierre_audio()
            self.raiz.after_cancel(self._temporizador_cola)

    def _alternar_voz(self):
        if self._cerrando:
            return
        self._voz_activada = not self._voz_activada
        self._version_voz += 1
        version = self._version_voz
        self.boton_voz.itemconfigure(self.boton_voz._texto, text="Voz: ON" if self._voz_activada else "Voz: OFF")
        if self._voz_activada:
            def activar():
                if not self._voz.disponible:
                    raise RuntimeError(f"Voz local no disponible. {self._voz.motivo_no_disponible}")
                self._voz.activar()
            self._operar_audio(activar, "voz", version)
        else:
            self._hablando = False
            self._operar_audio(self._voz.detener, "voz", version)
            self.esfera.activar(self.controlador.ocupado)

    def _operar_audio(self, operacion, recurso, version):
        def terminado(_valor, error):
            if error:
                self._mostrar("aviso", f"Error de {recurso}: {error}", "aviso")
                if version == getattr(self, f"_version_{recurso}"):
                    if recurso == "voz":
                        self._voz_activada = self._hablando = False
                        self.boton_voz.itemconfigure(self.boton_voz._texto, text="Voz: OFF")
                        self.esfera.activar(self.controlador.ocupado)
                    else:
                        self._escucha_activada = self._escucha_en_curso = False
                        self.boton_escucha.itemconfigure(self.boton_escucha._texto, text="Escucha: OFF")
                        self.estado_escucha.configure(text="Escucha OFF")
                    if operacion != getattr(self, f"_{recurso}").detener:
                        self._limpiar_error_audio(recurso)
        self._audio.enviar(operacion, terminado)

    def _limpiar_error_audio(self, recurso):
        def terminado(_valor, error):
            if error:
                self._mostrar("aviso", f"No he podido liberar {recurso} tras el error: {error}", "aviso")
        self._audio.enviar(getattr(self, f"_{recurso}").detener, terminado)

    def _detener_voz(self):
        self._version_voz += 1
        self._hablando = False
        self._operar_audio(self._voz.pausar, "voz", self._version_voz)

    def _leer(self, texto):
        self._marcar_pausa_escucha()
        self._version_voz += 1
        version = self._version_voz

        def leer():
            self._escucha.pausar()
            if (version == self._version_voz and self._voz_activada
                    and not self._cerrando and not self._cerrada):
                self._voz.hablar(texto)

        self._operar_audio(leer, "voz", self._version_voz)
        self._hablando = True
        self.esfera.activar(True, hablando=True)

    def _alternar_escucha(self):
        if self._cerrando:
            return
        if self._escucha_activada:
            self._desactivar_escucha()
        else:
            self._escucha_activada = True
            self.boton_escucha.itemconfigure(self.boton_escucha._texto, text="Escucha: ON")
            self.estado_escucha.configure(text="Pausada")
            self._actualizar_escucha()

    def _cambiar_idioma_escucha(self, _evento=None):
        if self._cerrando:
            return
        if self._escucha_en_curso:
            self._mostrar("aviso", "Idioma del micrófono cambiado; se ha descartado la frase en curso.", "aviso")
        self._pausar_escucha()
        self._actualizar_escucha()

    def _pausar_escucha(self):
        self._marcar_pausa_escucha()
        self._operar_audio(self._escucha.pausar, "escucha", self._version_escucha)

    def _marcar_pausa_escucha(self):
        self._version_escucha += 1
        self._escucha_en_curso = False
        if self._escucha_activada:
            self.estado_escucha.configure(text="Pausada")

    def _desactivar_escucha(self):
        self._escucha_activada = False
        self._version_escucha += 1
        self._escucha_en_curso = False
        self._operar_audio(self._escucha.detener, "escucha", self._version_escucha)
        self.boton_escucha.itemconfigure(self.boton_escucha._texto, text="Escucha: OFF")
        self.estado_escucha.configure(text="Escucha OFF")

    def _actualizar_escucha(self):
        if not self._escucha_activada or self._cerrando:
            return
        if self.controlador.ocupado or self._turno_pendiente or self._hablando:
            if self._escucha_en_curso:
                self._pausar_escucha()
            return
        if not self._escucha_en_curso:
            idioma = IDIOMAS_ESCUCHA[self.idioma_escucha.get()]
            self._version_escucha += 1
            version = self._version_escucha

            def iniciar():
                if (version == self._version_escucha and self._escucha_activada
                        and not self._cerrando and not self._cerrada):
                    self._escucha.pausar()
                    if version == self._version_escucha:
                        self._escucha.iniciar(idioma)

            self._operar_audio(iniciar, "escucha", version)
            self._escucha_en_curso = True
            self.estado_escucha.configure(text="Preparando micrófono…")

    def _eventos_escucha(self, eventos):
        for tipo, texto in eventos:
            if tipo == "estado":
                self.estado_escucha.configure(text=texto)
            elif tipo == "error":
                self._desactivar_escucha()
                self._mostrar("aviso", texto, "aviso")
                return
            elif tipo == "texto":
                self.enviar(texto)
                return
            elif tipo == "fin":
                self._desactivar_escucha()
                self._mostrar("aviso", "La escucha terminó sin una transcripción. Vuelve a activarla.", "aviso")
                return

    def _sondear_audio(self):
        if self._sondeo_audio_pendiente or self._cerrando:
            return
        voz, escucha = self._voz_activada, self._escucha_activada and self._escucha_en_curso
        if not voz and not escucha:
            return
        versiones = self._version_voz, self._version_escucha
        self._sondeo_audio_pendiente = True

        def consultar():
            return (self._voz.comprobar() if voz else None,
                    self._voz.recoger_avisos() if voz else [],
                    self._escucha.comprobar() if escucha else [])

        def recibido(valor, error):
            self._sondeo_audio_pendiente = False
            if error:
                self._mostrar("aviso", f"No he podido consultar el audio: {error}", "aviso")
                self._desactivar_escucha()
                self._voz_activada = self._hablando = False
                self._operar_audio(self._voz.detener, "voz", self._version_voz)
                self.boton_voz.itemconfigure(self.boton_voz._texto, text="Voz: OFF")
                return
            estado_voz, avisos, eventos = valor
            if versiones[0] == self._version_voz and self._voz_activada and estado_voz is not None:
                for aviso in avisos:
                    self._mostrar("aviso", aviso, "aviso")
                activo, error_voz = estado_voz
                if not activo:
                    self._hablando = False
                    self.esfera.activar(self.controlador.ocupado)
                    if error_voz:
                        self._mostrar("aviso", error_voz, "aviso")
                        self._voz_activada = False
                        self.boton_voz.itemconfigure(self.boton_voz._texto, text="Voz: OFF")
                        self._operar_audio(self._voz.detener, "voz", self._version_voz)
            if versiones[1] == self._version_escucha and self._escucha_activada:
                self._eventos_escucha(eventos)

        self._audio.enviar(consultar, recibido)

    def ejecutar(self):
        self.raiz.mainloop()

    # ------------------------------------------------------------- presentación
    def _actualizar_carga_local(self):
        if self._cerrando:
            return
        estado = self.controlador.estado_carga_local()
        for aviso in self.controlador.avisos_carga_local():
            self._mostrar("aviso", aviso, "aviso")
        if estado is None:
            self.fila_carga.grid_remove()
            return
        self.fila_carga.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        textos = {
            "preparando": "Preparando motor local… Ayuda y memoria disponibles.",
            "cancelando": "Cancelando la preparación local…",
            "listo": "Motor local disponible.",
            "error": "Motor local no disponible. Consulta Estado.",
        }
        self.estado_carga.configure(text=textos[estado["estado"]])
        if estado["estado"] == "preparando":
            self.boton_cancelar_carga.configure(state="normal")
            self.boton_cancelar_carga.grid()
        else:
            self.boton_cancelar_carga.grid_remove()

    def _vaciar_cola(self):
        if not self._cerrando:
            try:
                while True:
                    callback, valor, error = self._audio.resultados.get_nowait()
                    callback(valor, error)
                    if self._cerrando:
                        break
            except queue.Empty:
                pass
        self._actualizar_carga_local()
        try:
            self._resultado_audio_cierre = self._cola_audio_cierre.get_nowait()
        except queue.Empty:
            pass
        try:
            self._resultado_cierre = self._cola_cierre.get_nowait()
        except queue.Empty:
            pass
        if (self._cerrando and self._resultado_cierre is not None
                and self._resultado_audio_cierre is not None):
            guardado, error = self._resultado_cierre
            audio_cerrado, error_audio = self._resultado_audio_cierre
            if guardado and audio_cerrado:
                self.raiz.destroy()
                return
            self._cerrando = False
            self._plazo_cierre = None
            self._reinicio = None
            if not guardado:
                self._mostrar("aviso", "No he podido guardar el historial al cerrar"
                              + (f": {error}" if error else ". Revisa la consola.")
                              + " La ventana sigue abierta; puedes reintentar el cierre.", "aviso")
            if not audio_cerrado:
                self._mostrar("aviso", f"No he podido cerrar el audio: {error_audio}. "
                              "La ventana sigue abierta; puedes reintentar el cierre.", "aviso")
            # La ventana vuelve a poder activar audio: el proximo cierre debe limpiarlo.
            self._hilo_audio_cierre = None
            self._resultado_audio_cierre = None
            self._cola_audio_cierre = queue.Queue()
            self._audio = OperacionesAudio()
            self._sondeo_audio_pendiente = False
            for boton in self.botones_barra + [self.boton_voz, self.boton_escucha]:
                boton.configure(state="normal")
            self.idioma_escucha.configure(state="readonly")
            self._bloquear(self.controlador.ocupado)
        if self._cerrando and self._plazo_cierre is not None and monotonic() >= self._plazo_cierre:
            self._plazo_cierre = None
            if messagebox.askyesno(
                    "Cierre sin confirmar",
                    "El guardado o la limpieza de audio no han confirmado el cierre "
                    f"en {PLAZO_CIERRE_SEGUNDOS:g} segundos. "
                    "¿Cerrar igualmente? Podrían perderse cambios o quedar recursos sin cerrar. "
                    "Si eliges No, seguiré esperando.",
                    parent=self.raiz):
                self._reinicio = None
                self.raiz.destroy()
                return
        try:
            while True:
                self._pintar_turno(self._cola.get_nowait())
        except queue.Empty:
            pass
        self._actualizar_escucha()
        self._sondear_audio()
        self._temporizador_cola = self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)

    def _pintar_turno(self, turno):
        self._turno_pendiente = False
        if turno.limpiado:
            self._borrar_chat()
        for aviso in turno.avisos:
            self._mostrar("aviso", aviso, "aviso")
        self._mostrar(nombre_ia, turno.texto)
        if not turno.guardado:
            self._mostrar("aviso", "No he podido guardar el historial en disco; revisa la consola.", "aviso")
        if not self._cerrando:
            self._bloquear(False)
        if self._voz_activada and not self._cerrando and turno.texto != MENSAJE_CANCELADO:
            self._leer(turno.texto)

    def _mostrar(self, autor, texto, etiqueta=None):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{autor}: ", "autor_usuario" if autor == master_name else "autor")
        self.chat.insert("end", f"{texto}\n\n", etiqueta or ())
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _borrar_chat(self):
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")

    def _bloquear(self, ocupado):
        self.esfera.activar(ocupado)
        estado = "disabled" if ocupado else "normal"
        self.boton_enviar.configure(state=estado)
        self.boton_cancelar.configure(state="normal" if ocupado and not self._cerrando else "disabled")
        if ocupado:
            self.boton_enviar.grid_remove()
            self.boton_cancelar.grid()
        else:
            self.boton_cancelar.grid_remove()
            self.boton_enviar.grid()
        self.entrada.configure(state=estado)
        if not ocupado:
            self.entrada.focus_set()

def crear_raiz():
    """Abre la conexión con la pantalla. Debe hacerse ANTES del aislamiento de red del
    proceso: una conexión ya abierta sigue funcionando dentro del namespace."""
    return tk.Tk()


def iniciar_ui(controlador=None, raiz=None, aviso_arranque=None):
    from core.reinicio import codigo_modo
    ventana = VentanaBai(controlador, raiz)
    if aviso_arranque:
        ventana._mostrar("aviso", aviso_arranque, "aviso")
    try:
        ventana.ejecutar()
    finally:
        if not ventana._cerrada:
            ventana.raiz.destroy()
        if ventana._hilo_audio_cierre is not None:
            ventana._hilo_audio_cierre.join(timeout=3)
            if ventana._hilo_audio_cierre.is_alive():
                ventana._reinicio = None
                print("[B.A.I] La limpieza de audio sigue sin confirmar su cierre.", file=sys.stderr)
    return codigo_modo(ventana._reinicio) if ventana._reinicio is not None else 0

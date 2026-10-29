"""
Ventana de chat de B.A.I con tkinter (fase 8): zona de conversación, entrada,
barra de estado y botones de modo. Toda la lógica vive en ControladorChat; aquí
sólo se dibuja. Los mensajes se procesan en un hilo para no congelar la ventana
y el resultado vuelve al hilo de Tk por una cola, nunca llamando a Tk desde el hilo.
"""
import queue
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from core.config import nombre_ia, master_name
from core.ayuda import DESCRIPCION_BAI
from core.ui_controlador import ControladorChat

INTERVALO_COLA_MS = 100
ANCHO_BARRA_ESTRECHA = 640

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


class VentanaBai:
    def __init__(self, controlador=None, raiz=None):
        self.controlador = controlador or ControladorChat()
        self.raiz = raiz or tk.Tk()
        self._cola = queue.Queue()
        self._construir()
        self._mostrar(nombre_ia, f"Hola, {master_name}. Memoria de sesión cargada.")
        self.raiz.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)

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

        # El pie se empaqueta antes que el chat para conservarse al encoger la ventana.
        pie = tk.Frame(self.raiz, bg=COLORES["fondo"], padx=10, pady=10)
        pie.pack(side="bottom", fill="x")
        pie.columnconfigure(0, weight=1)
        alto_entrada = tkfont.Font(font=FUENTE_UI).metrics("linespace") + 16
        self.marco_entrada = tk.Canvas(
            pie, bg=COLORES["fondo"], width=100, height=alto_entrada,
            highlightthickness=0, borderwidth=0, takefocus=0)
        self.marco_entrada.grid(row=0, column=0, sticky="ew")
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
        self.boton_enviar.grid(row=0, column=1, padx=(8, 0), sticky="ns")

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
        if self.controlador.ocupado:
            return
        if texto is None:
            texto = self.entrada.get().strip()
            if texto:
                self.entrada.delete(0, "end")
        if not texto:
            return
        if texto.lower() in ("salir", "exit", "quit", "irten", "atera", "amaitu"):
            self.cerrar()
            return
        self._mostrar(master_name, texto)
        self._bloquear(True)
        self.controlador.enviar_en_hilo(texto, self._cola.put)

    def cerrar(self):
        self.controlador.cerrar()
        self.raiz.destroy()

    def ejecutar(self):
        self.raiz.mainloop()

    # ------------------------------------------------------------- presentación
    def _vaciar_cola(self):
        try:
            while True:
                self._pintar_turno(self._cola.get_nowait())
        except queue.Empty:
            pass
        self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)

    def _pintar_turno(self, turno):
        if turno.limpiado:
            self._borrar_chat()
        for aviso in turno.avisos:
            self._mostrar("aviso", aviso, "aviso")
        self._mostrar(nombre_ia, turno.texto)
        if not turno.guardado:
            self._mostrar("aviso", "No he podido guardar el historial en disco; revisa la consola.", "aviso")
        self._bloquear(False)

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
        estado = "disabled" if ocupado else "normal"
        self.boton_enviar.configure(state=estado)
        self.entrada.configure(state=estado)
        if not ocupado:
            self.entrada.focus_set()

def crear_raiz():
    """Abre la conexión con la pantalla. Debe hacerse ANTES del aislamiento de red del
    proceso: una conexión ya abierta sigue funcionando dentro del namespace."""
    return tk.Tk()


def iniciar_ui(controlador=None, raiz=None):
    VentanaBai(controlador, raiz).ejecutar()

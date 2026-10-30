"""
Controlador de la interfaz gráfica (core/ui_controlador.py) y ventana tkinter
(core/ui_tk.py). El controlador se prueba sin pantalla, con ask() y el selector
reales sobre motores fake y almacenamiento temporal. La ventana sólo se prueba
si hay pantalla disponible (ver `ventana_tk`).
"""
import gc
import json
import threading
import time

import pytest

import core.ai_engine as ai
import core.memory_engine as memoria
from core.ui_controlador import ControladorChat, MENSAJE_LIMPIADO, MENSAJE_OCUPADO
from tests.conftest import config_local


@pytest.fixture
def entorno(monkeypatch, tmp_path, selector_fake):
    historial_dir = tmp_path / "history"
    historial_dir.mkdir()
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(historial_dir))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(historial_dir / "historial.json"))
    monkeypatch.setattr(memoria, "MEMORY_PATH", str(tmp_path / "perfil.yaml"))
    monkeypatch.setattr(memoria, "FACTS_PATH", str(tmp_path / "facts.yaml"))
    cfg = config_local("offline")
    cfg["mostrar_motor"] = False
    sel = selector_fake.crear(cfg)
    monkeypatch.setattr(ai, "_selector", sel)
    monkeypatch.setattr(ai, "ultima_respuesta", None)

    class E:
        pass
    e = E()
    e.sel, e.fake, e.dir, e.tmp = sel, selector_fake, historial_dir, tmp_path
    e.guardado = lambda: json.loads((historial_dir / "historial.json").read_text(encoding="utf-8"))
    e.facts = tmp_path / "facts.yaml"
    return e


def test_mensaje_normal_responde_y_guarda_el_historial(entorno):
    c = ControladorChat(historial=[])
    t = c.enviar("hola")
    assert t.texto == "respuesta de off_a" and t.guardado and not t.limpiado and t.avisos == []
    esperado = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "respuesta de off_a"}]
    assert c.historial == esperado and entorno.guardado() == esperado


def test_texto_vacio_no_hace_nada(entorno):
    c = ControladorChat(historial=[])
    assert c.enviar("") is None and c.enviar("   ") is None and c.enviar(None) is None
    assert c.historial == [] and not (entorno.dir / "historial.json").exists()
    assert entorno.fake.motores.todos["off_a"].llamadas == []


def test_limpiar_y_reset_guardan_inmediatamente_historial_vacio(entorno):
    c = ControladorChat(historial=[])
    c.enviar("hola")
    for orden in ("limpiar", "RESET"):
        t = c.enviar(orden)
        assert t.texto == MENSAJE_LIMPIADO and t.limpiado and c.historial == []
        assert t.guardado and entorno.guardado() == []
        assert ControladorChat().historial == []
    assert len(entorno.fake.motores.todos["off_a"].llamadas) == 1      # limpiar no llega al motor


@pytest.mark.parametrize("orden", ["limpiar", "reset"])
def test_limpiar_informa_fallo_guardado(entorno, orden):
    guardados = []

    def guardar(historial):
        guardados.append(list(historial))
        return False

    c = ControladorChat(historial=[{"role": "user", "content": "previo"}], guardar=guardar)
    turno = c.enviar(orden)
    assert turno.limpiado and not turno.guardado
    assert guardados == [[]] and c.historial == []


def test_cambio_de_modo_y_estado_usan_los_comandos_reales(entorno):
    c = ControladorChat(historial=[])
    assert c.estado_barra().startswith("Modo: OFFLINE · Motor activo: off_a")
    assert "Modo cambiado a ONLINE" in c.enviar("pasa a modo online").texto
    assert c.estado_barra().startswith("Modo: ONLINE")
    assert "Modo cambiado a OFFLINE" in c.enviar("pasa a modo offline").texto
    assert "Modo actual: OFFLINE" in c.enviar("estado").texto and "Modo actual: OFFLINE" in c.estado_completo()
    assert c.historial == []                                           # los comandos no llegan al historial
    assert all(m.llamadas == [] for m in entorno.fake.motores.todos.values())


def test_online_no_se_activa_por_frases_que_no_son_la_orden(entorno):
    c = ControladorChat(historial=[])
    c.enviar("no quiero pasar a modo online")
    assert entorno.sel.modo == "offline"


def test_memoria_local_desde_la_ventana_no_toca_motor_ni_historial(entorno):
    c = ControladorChat(historial=[])
    assert "Hecho guardado: coche = rojo" in c.enviar("recuerda que mi coche es rojo").texto
    antes = entorno.facts.read_bytes()
    for frase in ("mi coche ahora es azul", "cambia el fondo a azul"):
        assert c.enviar(frase).texto == "respuesta de off_a"           # conversación: no cambia hechos
    assert entorno.facts.read_bytes() == antes
    assert "coche es rojo" in c.enviar("¿cuál es mi coche?").texto


def test_aviso_de_respaldo_va_al_turno_y_no_a_la_consola(entorno, capsys):
    entorno.fake.motores.todos["off_a"].disponible_ok = False
    entorno.fake.motores.todos["off_a"].motivo = "sin modelo"
    c = ControladorChat(historial=[])
    t = c.enviar("hola")
    assert t.texto == "respuesta de off_b" and len(t.avisos) == 1 and "off_a" in t.avisos[0]
    assert capsys.readouterr().out == ""
    assert ai._avisador is print                                       # destino restaurado


def test_sin_motor_informa_y_no_guarda_turno(entorno):
    for m in entorno.fake.motores.todos.values():
        m.disponible_ok, m.motivo = False, "caído"
    c = ControladorChat(historial=[])
    t = c.enviar("hola")
    assert "Ningún motor ha podido responder" in t.texto and c.historial == []


@pytest.mark.parametrize("peticion", ["ayuda", " AYUDA! ", "¿Cómo funcionas?",
                                     "explícame cómo funcionas", "help"])
def test_ayuda_local_sin_selector_ni_cambios_de_memoria(entorno, monkeypatch, peticion):
    from core.ayuda import AYUDA_BAI
    c = ControladorChat(historial=[])
    c.enviar("recuerda que mi apodo es Boli")
    antes = entorno.facts.read_bytes()

    def selector_prohibido():
        pytest.fail("la ayuda no debe consultar motores")

    monkeypatch.setattr(ai, "get_selector", selector_prohibido)
    assert c.enviar(peticion).texto == AYUDA_BAI
    assert entorno.facts.read_bytes() == antes
    assert c.historial == [] and entorno.sel.modo == "offline"
    assert all(m.llamadas == [] for m in entorno.fake.motores.todos.values())


def test_frase_ordinaria_sobre_ayuda_no_es_comando(entorno):
    assert ControladorChat(historial=[]).enviar("necesito ayuda con mi coche").texto == "respuesta de off_a"


def test_ayuda_identifica_bai_y_explica_las_transiciones():
    from core.ayuda import AYUDA_BAI, DESCRIPCION_BAI
    assert "Boli Artificial Intelligence" in DESCRIPCION_BAI
    assert "Boli Artificial Intelligence" in AYUDA_BAI
    for texto in ("DE OFFLINE A ONLINE", "DE ONLINE A OFFLINE", "pasa a modo online",
                  "pasa a modo offline", "online: tu pregunta", "namespace sin red",
                  "python bai.py --ui --online", "no cubre subprocesos ni código nativo",
                  "no\nretira información"):
        assert texto in AYUDA_BAI


def test_error_inesperado_se_muestra_y_el_hilo_no_muere(entorno):
    def preguntar(texto, historial):
        raise RuntimeError("fallo simulado")
    c = ControladorChat(historial=[], preguntar=preguntar)
    recibido = []
    hilo = c.enviar_en_hilo("hola", recibido.append)
    hilo.join(5)
    assert [t.texto for t in recibido] == ["Error interno: fallo simulado"]
    assert not c.ocupado                                               # el cerrojo se libera siempre
    assert ai._avisador is print


def test_envio_en_hilo_y_un_solo_mensaje_a_la_vez(entorno):
    entra, sale = threading.Event(), threading.Event()

    def preguntar(texto, historial):
        entra.set()
        sale.wait(5)
        historial.append({"role": "user", "content": texto})
        return "lenta"
    c = ControladorChat(historial=[], preguntar=preguntar, guardar=lambda h: True)
    recibido = []
    hilo = c.enviar_en_hilo("uno", recibido.append)
    assert entra.wait(5) and c.ocupado
    assert c.enviar("dos").texto == MENSAJE_OCUPADO                    # no se encola ni se pierde
    sale.set()
    hilo.join(5)
    assert [t.texto for t in recibido] == ["lenta"] and len(c.historial) == 1 and not c.ocupado


def test_fallo_al_guardar_se_comunica(entorno):
    c = ControladorChat(historial=[], preguntar=lambda t, h: "ok", guardar=lambda h: False)
    assert c.enviar("hola").guardado is False


def test_cerrar_guarda_el_historial(entorno):
    c = ControladorChat(historial=[{"role": "user", "content": "x"}])
    assert c.cerrar() is True and entorno.guardado() == [{"role": "user", "content": "x"}]


def test_carga_el_historial_de_disco_por_defecto(entorno):
    (entorno.dir / "historial.json").write_text(json.dumps([{"role": "user", "content": "previo"}]), encoding="utf-8")
    assert ControladorChat().historial == [{"role": "user", "content": "previo"}]


# --------------------------------------------------------------------------- ventana tkinter
@pytest.fixture
def ventana_tk(entorno):
    tk = pytest.importorskip("tkinter", reason="tkinter no instalado")
    # Tk debe liberar las ventanas anteriores en el hilo principal, no en un worker.
    gc.collect()
    try:
        raiz = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no hay pantalla disponible para tkinter: {e}")
    from core.ui_tk import VentanaBai
    v = VentanaBai(ControladorChat(historial=[]), raiz)
    yield v
    try:
        for identificador in raiz.tk.call("after", "info"):
            raiz.after_cancel(identificador)
        raiz.destroy()
    except tk.TclError:
        pass


@pytest.mark.parametrize("disponible", [True, False])
def test_voz_inicial_siempre_desactivada(ventana_tk, disponible):
    from types import SimpleNamespace
    from core.ui_tk import VentanaBai
    lector = SimpleNamespace(
        disponible=disponible, motivo_no_disponible="modelo ausente",
        modelo=None, modelos_instalados=lambda: [], detener=lambda: None)
    v = VentanaBai(ventana_tk.controlador, voz=lector)
    try:
        assert not v._voz_activada
        assert v.boton_voz.itemcget(v.boton_voz._texto, "text") == "Voz: OFF"
        assert "Voz local no disponible" not in _chat(v)
        if not disponible:
            v._alternar_voz()
            assert "modelo ausente" in _chat(v)
    finally:
        v.raiz.destroy()


def _esperar(ventana, condicion, segundos=5):
    limite = time.time() + segundos
    while time.time() < limite:
        ventana.raiz.update()
        if condicion():
            return
        time.sleep(0.01)
    raise AssertionError("la ventana no se actualizó a tiempo")


def _chat(v):
    return v.chat.get("1.0", "end")


def test_ventana_envia_y_muestra_la_respuesta(ventana_tk):
    v = ventana_tk
    assert "asistente personal" in v.etiqueta_estado.cget("text")
    v.entrada.insert(0, "hola")
    v.enviar()
    assert v.entrada.get() == ""
    _esperar(v, lambda: "respuesta de off_a" in _chat(v))
    assert str(v.entrada.cget("state")) == "normal" and str(v.boton_enviar.cget("state")) == "normal"
    assert v.controlador.historial[-1]["content"] == "respuesta de off_a"


def test_ventana_botones_de_modo_y_limpiar(ventana_tk):
    v = ventana_tk
    v.enviar("pasa a modo online")
    _esperar(v, lambda: "Modo cambiado a ONLINE" in _chat(v))
    v.enviar("pasa a modo offline")
    _esperar(v, lambda: "Modo cambiado a OFFLINE" in _chat(v))
    v.enviar("hola")
    _esperar(v, lambda: "respuesta de off_a" in _chat(v))
    v.enviar("limpiar")
    _esperar(v, lambda: MENSAJE_LIMPIADO in _chat(v) and "hola" not in _chat(v))
    assert v.controlador.historial == []


def test_ventana_cierra_guardando(ventana_tk, entorno):
    v = ventana_tk
    v.enviar("hola")
    _esperar(v, lambda: "respuesta de off_a" in _chat(v))
    v.cerrar()
    _esperar(v, lambda: v._cerrada)
    assert entorno.guardado()[-1]["content"] == "respuesta de off_a"


@pytest.mark.parametrize("confirmar", [False, True])
def test_cambio_online_ofrece_reinicio_guardando_sin_enviar_contexto(
        ventana_tk, entorno, monkeypatch, confirmar):
    import core.ui_tk as ui
    v = ventana_tk
    entorno.sel.config["aislamiento_offline"] = "proceso"
    v.enviar("hola")
    _esperar(v, lambda: len(v.controlador.historial) == 2 and not v.controlador.ocupado)
    avisos = []
    monkeypatch.setattr(ui.messagebox, "askyesno",
                        lambda titulo, mensaje, **kw: avisos.append(mensaje) or confirmar)
    v.enviar("pasa a modo online")
    assert len(avisos) == 1 and "memoria" in avisos[0]
    assert entorno.sel.modo == "offline"
    assert entorno.fake.motores.todos["on_a"].llamadas == []
    if confirmar:
        _esperar(v, lambda: v._cerrada)
        assert v._reinicio == "online" and len(entorno.guardado()) == 2
    else:
        assert not v._cerrando and v._reinicio is None


def test_reinicio_se_anula_si_no_se_guarda(ventana_tk, entorno, monkeypatch):
    import core.ui_tk as ui
    v = ventana_tk
    entorno.sel.config["aislamiento_offline"] = "proceso"
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *args, **kw: True)
    v.controlador._guardar = lambda historial: False
    v.enviar("pasa a modo online")
    _esperar(v, lambda: not v._cerrando)
    assert not v._cerrada and v._reinicio is None and entorno.sel.modo == "offline"


def test_boton_ayuda_y_peticion_escrita_muestran_la_misma_guia(ventana_tk):
    from core.ayuda import AYUDA_BAI, DESCRIPCION_BAI
    v = ventana_tk
    v.raiz.update()
    v.botones_barra[-1].event_generate("<ButtonRelease-1>", x=5, y=5)
    _esperar(v, lambda: AYUDA_BAI in _chat(v) and not v.controlador.ocupado
             and str(v.entrada.cget("state")) == "normal")
    v.entrada.insert(0, "explícame cómo funcionas")
    v.enviar()
    _esperar(v, lambda: _chat(v).count(AYUDA_BAI) == 2)
    assert v.etiqueta_estado.cget("text") == DESCRIPCION_BAI


def test_ventana_botones_visibles_con_estado_largo_y_ventana_minima(ventana_tk):
    from core.ui_tk import BotonRedondo
    v = ventana_tk
    v.raiz.geometry("480x360")
    v.etiqueta_estado.configure(text="Modo: OFFLINE — " + "motor " * 40)
    v.raiz.update()
    assert v.fila_botones.winfo_y() > v.etiqueta_estado.winfo_y()  # en ventana estrecha los botones pasan a otra fila
    botones = [w for w in v.fila_botones.winfo_children() if isinstance(w, BotonRedondo)]
    assert len(botones) == 5
    for b in botones:
        assert b.winfo_ismapped()
        assert b.winfo_x() + b.winfo_width() <= v.raiz.winfo_width()


def test_ventana_es_responsive_y_mantiene_la_entrada_visible(ventana_tk):
    v = ventana_tk
    for ancho, alto in ((900, 600), (360, 320), (500, 330), (900, 330)):
        v.raiz.geometry(f"{ancho}x{alto}")
        v.raiz.update()
        assert v.entrada.winfo_ismapped() and v.boton_enviar.winfo_ismapped()
        assert v.entrada.winfo_y() + v.entrada.winfo_height() <= v.raiz.winfo_height()
        assert v.chat.winfo_width() > 100
        assert v.chat.winfo_ismapped() and v.chat.winfo_height() > 20
        assert v.boton_voz.winfo_rooty() + v.boton_voz.winfo_height() <= (
            v.raiz.winfo_rooty() + v.raiz.winfo_height())
        assert v.boton_escucha.winfo_rooty() >= v.boton_voz.winfo_rooty() + v.boton_voz.winfo_height()
        assert v.boton_escucha.winfo_rooty() + v.boton_escucha.winfo_height() <= (
            v.raiz.winfo_rooty() + v.raiz.winfo_height())
        for boton in v.botones_barra:
            assert boton.winfo_rootx() >= v.raiz.winfo_rootx()
            assert boton.winfo_rootx() + boton.winfo_width() <= v.raiz.winfo_rootx() + v.raiz.winfo_width()
    v.raiz.geometry("900x600")
    v.raiz.update()
    assert v.fila_botones.grid_info()["row"] == v.etiqueta_estado.grid_info()["row"] == 0


def test_botones_redondeados_y_texto_suave(ventana_tk):
    from core.ui_tk import BotonRedondo
    v = ventana_tk
    b = v.boton_enviar
    assert isinstance(b, BotonRedondo) and b.itemcget(b._forma, 'smooth') in ('1', 'true')
    assert b.itemcget(b._texto, 'fill') == '#d4d4d4' and v.etiqueta_estado.cget('fg') == '#d4d4d4'
    b.configure(state='disabled')
    assert b.cget('state') == 'disabled'
    llamadas = []
    b._comando = lambda: llamadas.append(1)
    v.raiz.update()
    b.event_generate('<ButtonRelease-1>', x=5, y=5)
    assert llamadas == []
    b.configure(state='normal')
    b.event_generate('<ButtonRelease-1>', x=5, y=5)
    assert llamadas == [1]


def test_ventana_usa_tema_oscuro_con_texto_blanco(ventana_tk):
    v = ventana_tk
    assert v.chat.cget("bg") == "#1e1e1e" and v.chat.cget("fg") == "#ffffff"
    assert v.entrada.cget("fg") == "#ffffff"


def test_entrada_redondeada_se_adapta_y_conserva_el_texto(ventana_tk):
    v = ventana_tk
    v.entrada.insert(0, "Mensaje de prueba")
    for ancho in (860, 360, 640):
        v.raiz.geometry(f"{ancho}x400")
        v.raiz.update()
        marco = v.marco_entrada
        assert marco.itemcget(v._borde_entrada, "smooth") in ("1", "true")
        assert marco.bbox(v._borde_entrada)[2] <= marco.winfo_width()
        assert v.entrada.winfo_width() == marco.winfo_width() - 24
        assert v.entrada.get() == "Mensaje de prueba"
    v.entrada.event_generate("<FocusIn>")
    assert marco.itemcget(v._borde_entrada, "outline") == "#0e639c"
    v.entrada.event_generate("<FocusOut>")
    assert marco.itemcget(v._borde_entrada, "outline") == "#454545"
    v._bloquear(True)
    assert str(v.entrada.cget("state")) == "disabled"
    v._bloquear(False)
    assert str(v.entrada.cget("state")) == "normal"


@pytest.mark.parametrize("fallo", [False, True])
def test_esfera_anima_durante_respuesta_y_para_al_terminar(ventana_tk, fallo):
    v = ventana_tk
    entra, sale = threading.Event(), threading.Event()

    def preguntar(texto, historial):
        entra.set()
        assert sale.wait(5)
        if fallo:
            raise RuntimeError("error de prueba")
        return "respuesta animada"

    v.controlador._preguntar = preguntar
    esfera = v.esfera
    assert esfera._temporizador is None
    v.enviar("hola")
    try:
        assert entra.wait(5)
        assert esfera._temporizador is not None
        antes = esfera.coords(esfera._bola)
        _esperar(v, lambda: esfera.coords(esfera._bola) != antes)
        assert "preparando respuesta" in esfera.itemcget(esfera._etiqueta, "text")
    finally:
        sale.set()
    esperado = "Error interno: error de prueba" if fallo else "respuesta animada"
    _esperar(v, lambda: esperado in _chat(v))
    assert esfera._temporizador is None
    assert esfera.itemcget(esfera._etiqueta, "text") == "B.A.I en reposo"
    assert esfera.coords(esfera._bola) == [12, 12, 32, 32]


def test_esfera_cancela_animacion_al_destruir(ventana_tk):
    esfera = ventana_tk.esfera
    esfera.activar(True)
    identificador = esfera._temporizador
    esfera.destroy()
    assert esfera._temporizador is None
    assert identificador not in ventana_tk.raiz.tk.call("after", "info")


@pytest.fixture
def voz_fake(ventana_tk):
    class Voz:
        disponible = True
        motivo_no_disponible = "Instala Piper para activarla."
        activo = False
        error = None
        textos = []
        avisos = []
        cierres = 0
        pausas = 0

        def hablar(self, texto):
            self.textos.append(texto)
            self.activo = True

        def activar(self):
            pass

        def comprobar(self):
            return self.activo, self.error

        def recoger_avisos(self):
            avisos, self.avisos = self.avisos, []
            return avisos

        def detener(self):
            self.cierres += 1
            self.activo = False

        def pausar(self):
            self.pausas += 1
            self.activo = False

    voz = Voz()
    ventana_tk._voz = voz
    return voz


def test_aviso_de_voz_alternativa_se_muestra_sin_apagar_voz(ventana_tk, voz_fake):
    v = ventana_tk
    v._alternar_voz()
    voz_fake.activo = True
    voz_fake.avisos = ["Falta la voz de euskera. Uso la voz de castellano como alternativa."]
    _esperar(v, lambda: "castellano como alternativa" in _chat(v))
    assert v._voz_activada and voz_fake.activo and voz_fake.cierres == 0
    assert _chat(v).count("castellano como alternativa") == 1


def test_voz_opcional_anima_hasta_fin_audio_y_se_puede_silenciar(ventana_tk, voz_fake):
    v = ventana_tk
    v.enviar("hola")
    _esperar(v, lambda: "respuesta de off_a" in _chat(v))
    assert voz_fake.textos == []
    v._alternar_voz()
    v.enviar("ayuda")
    _esperar(v, lambda: v._hablando)
    assert voz_fake.textos and voz_fake.activo
    assert v.esfera.itemcget(v.esfera._etiqueta, "text") == "B.A.I hablando…"
    voz_fake.activo = False
    _esperar(v, lambda: not v._hablando)
    assert v.esfera._temporizador is None
    v.enviar("estado")
    _esperar(v, lambda: v._hablando)
    v._alternar_voz()
    assert not voz_fake.activo and not v._voz_activada
    assert v.esfera._temporizador is None


def test_voz_se_corta_con_nuevo_mensaje_y_al_cerrar(ventana_tk, voz_fake):
    v = ventana_tk
    v._alternar_voz()
    v.enviar("ayuda")
    _esperar(v, lambda: v._hablando)
    v.enviar("estado")
    assert not voz_fake.activo
    _esperar(v, lambda: v._hablando)
    v.cerrar()
    _esperar(v, lambda: v._cerrada)
    assert not voz_fake.activo


def test_cierre_no_espera_backend_y_no_guarda_respuesta_tardia(ventana_tk, entorno):
    v = ventana_tk
    entra, sale = threading.Event(), threading.Event()

    def preguntar(texto, historial):
        entra.set()
        assert sale.wait(5)
        historial.extend([{"role": "user", "content": texto},
                          {"role": "assistant", "content": "respuesta final"}])
        return "respuesta final"

    v.controlador._preguntar = preguntar
    v.enviar("lenta")
    assert entra.wait(5)
    try:
        inicio = time.monotonic()
        v.cerrar()
        v.cerrar()
        assert time.monotonic() - inicio < 0.5
        _esperar(v, lambda: v._cerrada, segundos=1)
        assert not sale.is_set()
        assert entorno.guardado() == [] and v.controlador.historial == []
    finally:
        sale.set()
        v._hilo_turno.join(2)
    assert entorno.guardado() == [] and v.controlador.historial == []


def test_cancelar_desde_boton_descarta_turno_y_permite_siguiente(ventana_tk, entorno):
    from core.ui_controlador import MENSAJE_CANCELADO
    v = ventana_tk
    entra, sale = threading.Event(), threading.Event()
    original = v.controlador._preguntar

    def preguntar(texto, historial):
        entra.set()
        assert sale.wait(5)
        historial.append({"role": "assistant", "content": "tardia"})
        return "tardia"

    v.controlador._preguntar = preguntar
    v.enviar("bloquear")
    assert entra.wait(2)
    v.raiz.update()
    assert v.boton_cancelar.winfo_ismapped()
    v.boton_cancelar._comando()
    sale.set()
    _esperar(v, lambda: MENSAJE_CANCELADO in _chat(v))
    assert not v.controlador.historial and "tardia" not in _chat(v)
    assert not (entorno.dir / "historial.json").exists()
    v.controlador._preguntar = original
    v.enviar("nueva")
    _esperar(v, lambda: "respuesta de off_a" in _chat(v))
    assert len(v.controlador.historial) == 2


def test_cierre_acotado_ofrece_salir_si_guardado_no_responde(ventana_tk, monkeypatch):
    from core import ui_tk
    v = ventana_tk
    entra, sale = threading.Event(), threading.Event()
    confirmaciones = []

    def guardar(historial):
        entra.set()
        assert sale.wait(5)
        return True

    v.controlador._guardar = guardar
    monkeypatch.setattr(ui_tk, "PLAZO_CIERRE_SEGUNDOS", 0.1)
    monkeypatch.setattr(ui_tk.messagebox, "askyesno",
                        lambda *a, **kw: confirmaciones.append(a) or True)
    try:
        v.cerrar()
        assert entra.wait(1)
        _esperar(v, lambda: v._cerrada, segundos=1)
        assert len(confirmaciones) == 1 and not sale.is_set()
        assert v._reinicio is None
    finally:
        sale.set()


@pytest.mark.parametrize("excepcion", [False, True])
def test_cierre_fallido_mantiene_ventana_y_permite_reintentar(ventana_tk, excepcion):
    v = ventana_tk

    def fallar(historial):
        if excepcion:
            raise OSError("disco inaccesible")
        return False

    v.controlador._guardar = fallar
    v.cerrar()
    _esperar(v, lambda: not v._cerrando)
    assert not v._cerrada
    assert "No he podido guardar el historial al cerrar" in _chat(v)
    assert str(v.entrada.cget("state")) == "normal"
    v.controlador._guardar = lambda historial: True
    v.cerrar()
    _esperar(v, lambda: v._cerrada)


def test_voz_informa_dependencia_ausente_y_fallo_audio(ventana_tk, voz_fake):
    v = ventana_tk
    voz_fake.disponible = False
    v._alternar_voz()
    assert "Instala Piper" in _chat(v) and not v._voz_activada
    voz_fake.disponible = True
    v._alternar_voz()
    v.enviar("ayuda")
    _esperar(v, lambda: v._hablando)
    voz_fake.error = "No se ha podido reproducir la voz: sin altavoz"
    voz_fake.activo = False
    _esperar(v, lambda: "sin altavoz" in _chat(v))
    assert not v._hablando and v.esfera._temporizador is None


def test_sin_selector_ni_boton_de_prueba(ventana_tk):
    v = ventana_tk
    assert not hasattr(v, "selector_voz")
    assert not hasattr(v, "boton_probar_voz")
    assert not hasattr(v, "_probar_voz")
    assert not v._voz_activada


def test_ui_presenta_aviso_de_arranque_degradado_antes_del_bucle(ventana_tk, monkeypatch):
    from core import ui_tk
    v = ventana_tk
    monkeypatch.setattr(ui_tk, "VentanaBai", lambda controlador, raiz: v)
    textos = []
    monkeypatch.setattr(v, "ejecutar", lambda: textos.append(_chat(v)))
    assert ui_tk.iniciar_ui(raiz=v.raiz, aviso_arranque="Modo degradado: modelo corrupto") == 0
    assert "Modo degradado: modelo corrupto" in textos[0]
    assert v._cerrada


@pytest.fixture
def escucha_fake(ventana_tk):
    class Escucha:
        activa = False
        inicios = 0
        eventos = []
        error = None
        cierres = 0
        pausas = 0

        def iniciar(self, idioma=None):
            if self.error:
                raise RuntimeError(self.error)
            self.activa = True
            self.inicios += 1
            self.idioma = idioma

        def detener(self):
            self.cierres += 1
            self.activa = False
            self.eventos = []

        def pausar(self):
            self.pausas += 1
            self.activa = False
            self.eventos = []

        def comprobar(self):
            eventos, self.eventos = self.eventos, []
            return eventos

    micro = Escucha()
    ventana_tk._escucha = micro
    return micro


def test_escucha_arranca_off_y_toggle_controla_microfono(ventana_tk, escucha_fake):
    v = ventana_tk
    assert not v._escucha_activada and escucha_fake.inicios == 0
    assert v.boton_escucha.itemcget(v.boton_escucha._texto, "text") == "Escucha: OFF"
    v._alternar_escucha()
    assert v._escucha_activada and escucha_fake.activa
    escucha_fake.eventos = [("estado", "Escuchando")]
    v._actualizar_escucha()
    assert v.estado_escucha.cget("text") == "Escuchando"
    v._alternar_escucha()
    assert not v._escucha_activada and not escucha_fake.activa
    v._actualizar_escucha()
    assert escucha_fake.inicios == 1


def test_escucha_envia_una_frase_y_pausa_hasta_terminar_voz(ventana_tk, escucha_fake, voz_fake):
    v = ventana_tk
    v._alternar_voz()
    v._alternar_escucha()
    escucha_fake.eventos = [("texto", "hola"), ("fin", "")]
    v._actualizar_escucha()
    assert "Boli: hola" in _chat(v)
    assert not escucha_fake.activa and v._escucha_activada
    _esperar(v, lambda: v._hablando)
    assert not escucha_fake.activa
    assert escucha_fake.inicios == 1
    voz_fake.activo = False
    _esperar(v, lambda: escucha_fake.inicios == 2)
    assert escucha_fake.activa
    assert _chat(v).count("Boli: hola") == 1
    assert escucha_fake.pausas > 0 and escucha_fake.cierres == 0
    assert voz_fake.pausas > 0 and voz_fake.cierres == 0
    v._alternar_escucha()
    v._alternar_voz()
    assert escucha_fake.cierres == 1 and voz_fake.cierres == 1


def test_escucha_sin_tts_se_reanuda_tras_respuesta(ventana_tk, escucha_fake):
    v = ventana_tk
    v._alternar_escucha()
    escucha_fake.eventos = [("texto", "hola")]
    v._actualizar_escucha()
    _esperar(v, lambda: escucha_fake.inicios == 2)
    assert not v._hablando and escucha_fake.activa


def test_envio_manual_descarta_audio_pendiente(ventana_tk, escucha_fake):
    v = ventana_tk
    v._alternar_escucha()
    escucha_fake.eventos = [("texto", "audio antiguo")]
    v.enviar("estado")
    assert not escucha_fake.activa and escucha_fake.eventos == []
    _esperar(v, lambda: escucha_fake.inicios == 2)
    assert "audio antiguo" not in _chat(v)


@pytest.mark.parametrize("tipo", ["inicio", "error", "fin"])
def test_error_de_escucha_desactiva_sin_reintentos_infinitos(ventana_tk, escucha_fake, tipo):
    v = ventana_tk
    if tipo == "inicio":
        escucha_fake.error = "sin micrófono"
    v._alternar_escucha()
    if tipo != "inicio":
        escucha_fake.eventos = [(tipo, "sin micrófono")]
        v._actualizar_escucha()
    assert not v._escucha_activada and not escucha_fake.activa
    assert "sin micrófono" in _chat(v) or "sin una transcripción" in _chat(v)
    inicios = escucha_fake.inicios
    v._actualizar_escucha()
    assert escucha_fake.inicios == inicios


def test_cierre_y_destruccion_detienen_microfono(ventana_tk, escucha_fake):
    v = ventana_tk
    v._alternar_escucha()
    assert escucha_fake.activa
    v.cerrar()
    assert not escucha_fake.activa and not v._escucha_activada
    _esperar(v, lambda: v._cerrada)


def test_activar_escucha_durante_voz_espera_a_que_termine(ventana_tk, escucha_fake, voz_fake):
    v = ventana_tk
    v._alternar_voz()
    v._leer("Hola")
    v._alternar_escucha()
    assert v._escucha_activada and not escucha_fake.activa
    voz_fake.activo = False
    _esperar(v, lambda: escucha_fake.activa)


def test_idioma_de_microfono_no_cambia_voces_y_descarta_frase_anterior(ventana_tk, escucha_fake):
    v = ventana_tk
    v._alternar_escucha()
    assert escucha_fake.idioma is None
    escucha_fake.eventos = [("texto", "frase antigua")]
    v.idioma_escucha.set("Euskera")
    v._cambiar_idioma_escucha()
    assert escucha_fake.idioma == "eu" and escucha_fake.inicios == 2
    assert escucha_fake.eventos == []
    assert "se ha descartado la frase en curso" in _chat(v)
    assert not v._voz_activada

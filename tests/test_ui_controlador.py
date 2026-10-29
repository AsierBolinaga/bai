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


def test_limpiar_vacia_el_historial_y_lo_guarda_vacio_en_el_siguiente_turno(entorno):
    c = ControladorChat(historial=[])
    c.enviar("hola")
    for orden in ("limpiar", "RESET"):
        t = c.enviar(orden)
        assert t.texto == MENSAJE_LIMPIADO and t.limpiado and c.historial == []
    assert len(entorno.fake.motores.todos["off_a"].llamadas) == 1      # limpiar no llega al motor


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
    assert entorno.guardado()[-1]["content"] == "respuesta de off_a"


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

"""
Pruebas con librerías REALES (llama-cpp-python y/o gpt4all) sobre un modelo GGUF
minúsculo generado localmente (tests/helpers/gguf_minimo.py). No descargan nada
ni necesitan credenciales. Se omiten automáticamente si la librería no está
instalada. Verifican que los adaptadores offline pueden inicializar y usar
ficheros de modelo reales y que no abren la red.
"""
import pytest

from core.motors.base import libreria_instalada
from core.network_guard import GuardiaRed
from tests.conftest import config_base

HAY_GGUF = libreria_instalada("gguf") and libreria_instalada("numpy")
HAY_LLAMA = libreria_instalada("llama_cpp")
HAY_GPT4ALL = libreria_instalada("gpt4all")

pytestmark = pytest.mark.skipif(not HAY_GGUF, reason="se necesita 'pip install gguf numpy' para generar el modelo de prueba")

MENSAJES = [
    {"role": "system", "content": "Eres B.A.I, un asistente modular."},
    {"role": "system", "content": "El usuario se llama Test."},
    {"role": "user", "content": "hola"},
    {"role": "assistant", "content": "buenas"},
    {"role": "user", "content": "que tal"},
]


@pytest.fixture(scope="module")
def modelo_real(tmp_path_factory):
    from tests.helpers.gguf_minimo import crear_gguf
    return crear_gguf(tmp_path_factory.mktemp("modelos") / "bai-tiny.gguf")


def _cfg(modelo_real, **extra):
    cfg = {"model_path": modelo_real, "n_ctx": 256, "max_tokens": 6, "verbose": False}
    cfg.update(extra)
    return cfg


@pytest.mark.skipif(not HAY_LLAMA, reason="llama-cpp-python no instalado")
class TestLlamaCppReal:
    def test_worker_precarga_y_genera_con_adaptador_real(self, modelo_real):
        from core.generacion_worker import ProcesoMotor
        from core.motors import llama_cpp_engine
        proceso = ProcesoMotor()
        try:
            proceso.ejecutar(llama_cpp_engine.__name__, _cfg(modelo_real), offline=True)
            for _ in range(2):
                texto = proceso.ejecutar(
                    llama_cpp_engine.__name__, _cfg(modelo_real), MENSAJES, offline=True)
                assert isinstance(texto, str) and texto
        finally:
            proceso.cerrar()

    def test_disponible_y_responde_sin_red(self, modelo_real, monkeypatch):
        from core.motors import llama_cpp_engine as motor
        monkeypatch.setattr(motor, "_modelos", {})
        assert motor.disponible(_cfg(modelo_real)) == (True, "")
        with GuardiaRed() as bloqueo:
            texto = motor.responder(MENSAJES, _cfg(modelo_real))
            texto2 = motor.responder(MENSAJES, _cfg(modelo_real))
        assert isinstance(texto, str) and texto and isinstance(texto2, str)
        assert bloqueo.intentos == []
        assert len(motor._modelos) == 1  # el modelo se reutiliza
        motor.liberar_modelos()
        assert motor._modelos == {}

    def test_chat_format_llama2_conserva_sistema(self):
        """La config usa 'llama-2' porque 'mistral-instruct' descarta los mensajes
        de sistema (identidad + memoria). Se comprueba contra la librería real."""
        from llama_cpp import llama_chat_format as f
        assert "Eres B.A.I" in f.format_llama2(messages=MENSAJES).prompt
        assert "Eres B.A.I" not in f.format_mistral_instruct(messages=MENSAJES).prompt

    def test_regresion_formateador_llama2_solo_lee_el_primer_system(self):
        """Hallazgo reproducido en la frontera del formateador: sin consolidar, la
        memoria y la instrucción de idioma desaparecen del prompt final."""
        from llama_cpp import llama_chat_format as f
        from tests.test_base import MENSAJES_BAI
        crudo = f.format_llama2(messages=MENSAJES_BAI).prompt
        assert "Eres B.A.I" in crudo
        assert "furgoneta camper" not in crudo and "idioma del usuario" not in crudo

    def test_prompt_final_consolidado_preserva_todo_el_contexto(self):
        """Con consolidar_sistema (lo que hace el adaptador) el prompt final de
        llama-2 contiene identidad, memoria, idioma y todos los turnos en orden."""
        from llama_cpp import llama_chat_format as f
        from core.motors.base import consolidar_sistema
        from tests.test_base import MENSAJES_BAI
        prompt = f.format_llama2(messages=consolidar_sistema(MENSAJES_BAI)).prompt
        posiciones = [prompt.index(x) for x in ("Eres B.A.I", "furgoneta camper", "idioma del usuario",
                                                 "<</SYS>>", "hola", "buenas", "mi vehículo")]
        assert posiciones == sorted(posiciones)          # todo presente y en orden
        assert prompt.count("<<SYS>>") == 1

    def test_adaptador_real_acepta_varios_system(self, modelo_real, monkeypatch):
        """El adaptador real con varios mensajes 'system' genera sin error (llama.cpp
        recibiría un prompt con todo el contexto)."""
        from core.motors import llama_cpp_engine as motor
        from tests.test_base import MENSAJES_BAI
        monkeypatch.setattr(motor, "_modelos", {})
        with GuardiaRed() as g:
            texto = motor.responder(MENSAJES_BAI, _cfg(modelo_real))
        assert isinstance(texto, str) and texto and g.intentos == []
        motor.liberar_modelos()

    def test_error_de_generacion_es_motor_error(self, modelo_real, monkeypatch):
        from core.motors import llama_cpp_engine as motor
        from core.motors.base import MotorError
        monkeypatch.setattr(motor, "_modelos", {})
        # n_ctx demasiado pequeño para el prompt -> llama.cpp lanza; el adaptador lo traduce
        cfg = _cfg(modelo_real, n_ctx=8, max_tokens=4)
        with pytest.raises(MotorError):
            motor.responder(MENSAJES, cfg)
        motor.liberar_modelos()


@pytest.mark.skipif(not HAY_GPT4ALL, reason="gpt4all no instalado")
class TestGPT4AllReal:
    def test_regresion_carga_y_responde_sin_red(self, modelo_real, monkeypatch):
        """Con allow_download=True (por defecto en GPT4All) la carga consultaba
        gpt4all.io y fallaba sin conexión. Ahora debe cargar sin tocar la red."""
        from core.motors import gpt4all_engine as motor
        monkeypatch.setattr(motor, "_modelos", {})
        assert motor.disponible(_cfg(modelo_real)) == (True, "")
        with GuardiaRed() as bloqueo:
            texto = motor.responder(MENSAJES, _cfg(modelo_real))
        assert isinstance(texto, str) and texto
        assert bloqueo.intentos == []


@pytest.mark.skipif(not (HAY_LLAMA and HAY_GPT4ALL), reason="se necesitan llama-cpp-python y gpt4all")
def test_fallback_real_entre_motores_offline(modelo_real, monkeypatch, ai_engine_aislado):
    """Flujo completo ai_engine -> selector -> adaptadores reales, con la red
    bloqueada: responde llama.cpp; si falla al generar, responde GPT4All."""
    from core.model_selector import ModelSelector
    from core.motors import llama_cpp_engine

    monkeypatch.setattr(llama_cpp_engine, "_modelos", {})
    cfg = config_base("offline")
    cfg["mostrar_motor"] = True
    cfg["offline"] = {"motor": "llama_cpp", "fallback": ["gpt4all"], "max_mensajes_contexto": 6,
                      "motores": {"llama_cpp": _cfg(modelo_real), "gpt4all": _cfg(modelo_real)}}

    def sin_conectividad(host):
        raise AssertionError("modo offline no debe comprobar conectividad")

    sel = ModelSelector(config=cfg, comprobar_conexion=sin_conectividad)
    ai_engine_aislado.set_selector(sel)
    hist = []
    with GuardiaRed() as bloqueo:
        r1 = ai_engine_aislado.ask("hola", hist)
        assert r1.endswith("[llama_cpp · bai-tiny.gguf · offline]")

        def roto(**kwargs):
            raise RuntimeError("fallo simulado en llama.cpp")

        llama_cpp_engine._modelos[modelo_real].create_chat_completion = roto
        r2 = ai_engine_aislado.ask("otra", hist)
        assert r2.endswith("[gpt4all · bai-tiny.gguf · offline · fallback]")
    assert bloqueo.intentos == []
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    llama_cpp_engine.liberar_modelos()


@pytest.mark.skipif(not HAY_GPT4ALL, reason="gpt4all no instalado")
def test_regresion_real_gpt4all_con_allow_download_true_no_toca_la_red(modelo_real, monkeypatch):
    """GPT4All REAL con una configuración que pide descargas: debe cargar el
    modelo local sin contactar con gpt4all.io (antes la carga fallaba sin red)."""
    from core.model_selector import ModelSelector
    from core.motors import gpt4all_engine
    monkeypatch.setattr(gpt4all_engine, "_modelos", {})
    cfg = config_base("offline")
    cfg["offline"] = {"motor": "gpt4all", "fallback": [], "max_mensajes_contexto": None,
                      "motores": {"gpt4all": _cfg(modelo_real, allow_download=True)}}
    sel = ModelSelector(config=cfg, comprobar_conexion=lambda h: (_ for _ in ()).throw(AssertionError("red")))
    with GuardiaRed() as guardia:
        r = sel.responder(MENSAJES)
    assert r.motor == "gpt4all" and r.texto
    assert guardia.intentos == []

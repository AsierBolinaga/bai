"""
Genera un modelo GGUF de arquitectura `llama` minúsculo (pesos aleatorios) para
probar los adaptadores offline contra llama.cpp / GPT4All REALES sin descargar
nada. El modelo no dice nada coherente: sólo sirve para comprobar que el fichero
se carga, se tokeniza, se aplica el formato de chat y se genera texto.

Uso:  python -m tests.helpers.gguf_minimo <ruta_destino.gguf>
Requiere: pip install gguf numpy
"""
import sys

N_VOCAB_BASE = 3 + 256  # <unk>, <s>, </s> + bytes <0x00>..<0xFF>
PIEZAS = ["▁hola", "▁que", "▁tal", "▁B", ".", "A", "I", "▁soy", "▁un", "▁asistente", "▁modular",
          "▁[", "INST", "]", "▁<<", "SYS", ">>", "<<", "/", "▁", "\n", "▁responde", "▁usuario"]

N_EMBD, N_HEAD, N_FF, N_LAYER, N_CTX = 32, 4, 64, 1, 512


def crear_gguf(destino, semilla=0):
    import numpy as np
    import gguf

    rng = np.random.default_rng(semilla)
    tokens = ["<unk>", "<s>", "</s>"] + [f"<0x{i:02X}>" for i in range(256)] + PIEZAS
    tipos = ([gguf.TokenType.UNKNOWN, gguf.TokenType.CONTROL, gguf.TokenType.CONTROL]
             + [gguf.TokenType.BYTE] * 256 + [gguf.TokenType.NORMAL] * len(PIEZAS))
    scores = [0.0] * N_VOCAB_BASE + [-float(i) for i in range(len(PIEZAS))]
    n_vocab = len(tokens)

    w = gguf.GGUFWriter(str(destino), "llama")
    w.add_name("bai-test-tiny-llama")
    w.add_context_length(N_CTX)
    w.add_embedding_length(N_EMBD)
    w.add_block_count(N_LAYER)
    w.add_feed_forward_length(N_FF)
    w.add_head_count(N_HEAD)
    w.add_head_count_kv(N_HEAD)
    w.add_rope_dimension_count(N_EMBD // N_HEAD)
    w.add_layer_norm_rms_eps(1e-5)
    w.add_file_type(gguf.LlamaFileType.ALL_F32)

    w.add_tokenizer_model("llama")
    w.add_tokenizer_pre("default")
    w.add_token_list(tokens)
    w.add_token_types(tipos)
    w.add_token_scores(scores)
    w.add_bos_token_id(1)
    w.add_eos_token_id(2)
    w.add_unk_token_id(0)
    w.add_add_bos_token(True)
    w.add_add_eos_token(False)

    def rand(*shape, escala=0.05):
        return (rng.standard_normal(shape) * escala).astype(np.float32)

    w.add_tensor("token_embd.weight", rand(n_vocab, N_EMBD))
    w.add_tensor("output_norm.weight", np.ones(N_EMBD, dtype=np.float32))
    w.add_tensor("output.weight", rand(n_vocab, N_EMBD))
    for i in range(N_LAYER):
        p = f"blk.{i}."
        w.add_tensor(p + "attn_norm.weight", np.ones(N_EMBD, dtype=np.float32))
        w.add_tensor(p + "attn_q.weight", rand(N_EMBD, N_EMBD))
        w.add_tensor(p + "attn_k.weight", rand(N_EMBD, N_EMBD))
        w.add_tensor(p + "attn_v.weight", rand(N_EMBD, N_EMBD))
        w.add_tensor(p + "attn_output.weight", rand(N_EMBD, N_EMBD))
        w.add_tensor(p + "ffn_norm.weight", np.ones(N_EMBD, dtype=np.float32))
        w.add_tensor(p + "ffn_gate.weight", rand(N_FF, N_EMBD))
        w.add_tensor(p + "ffn_up.weight", rand(N_FF, N_EMBD))
        w.add_tensor(p + "ffn_down.weight", rand(N_EMBD, N_FF))

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()
    return str(destino)


if __name__ == "__main__":
    print(crear_gguf(sys.argv[1] if len(sys.argv) > 1 else "bai-test-tiny.gguf"))

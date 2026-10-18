# The Ryzen run: raw evidence

Evidence for `eval/results/extraction_ft-e4b-q4km-ryzen-test100.json` (F1 0.644 after the HPO check, 100 test diaries).

| File | What it is |
|---|---|
| `system.txt` | CPU, RAM and OS of the machine, the llama.cpp build, the exact server command and the SHA-256 of the GGUF that was served |
| `llama-server.log` | The server's own log for the whole session, unedited except that the Windows user name in paths is replaced by `<user>` |
| `load-check-verbose.log` | The same GGUF and the same command, started again with `-v` (verbose) after the run so that llama.cpp logs where it puts each layer, then 3 test requests. Request bodies are left out; the load section and the timing lines are complete |

What the log shows:

- The server was started with `--device none -ngl 0` (command in `system.txt`), so no layer was offloaded to a GPU; the log shows the threadpool starting with 8 threads (`n_threads = 8`), one per core of the Ryzen 7 7700. The machine also has an NVIDIA card and an AMD Radeon iGPU; `system.txt` lists both, and this run used neither.
- Every request has its own `print_timing` lines. Generation speed per request: median 12.6 tokens per second (range 2.9 to 14.2, over 104 requests), with 2 requests in parallel; the result file's 22.4 tokens per second is the total across both. The verbose load check runs at 14.6 to 14.9 tokens per second with one request at a time.
- `load-check-verbose.log` shows llama.cpp's own placement: every one of the 43 layers is `assigned to device CPU`, none to a Vulkan device, then `offloaded 0/43 layers to GPU` and the weights in `CPU_Mapped` buffers (2,782 MiB). It was taken after the eval, not during it, with the same file and flags.
- The session starts with a 4-row smoke test (`smoke-v3`, not a result) before the 100-row eval.

The GGUF in `system.txt` has the same SHA-256 as `clario-e4b-v3-q4_k_m.gguf` on [m0rtyddd/clario-gemma4-e4b-v3-gguf](https://huggingface.co/m0rtyddd/clario-gemma4-e4b-v3-gguf), so anyone can serve the same file and rerun the eval with the command in the main README.

On the same run, JSON was valid for 99 of 100 diaries and strictly schema-valid for 88. Family-history mentions were missed (0 of 22), as in the bf16 run on the same 100 rows.

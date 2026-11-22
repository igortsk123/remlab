You are an independent senior software-engineering reviewer. Independently analyse the following problem. Do not assume another agent's hypothesis is correct. Do not modify, create, or delete files. Answer in Russian, concise.

USER OBJECTIVE:
Paint an existing TRELLIS.2 mesh (GLB) with the Pixal3D texture flow on a rented RTX 4090 (Salad). Backend `pixal3d-tex`, class `PixalTexBackend` and function `texture_on_shape` in `tools/scout/salad/trellis/worker_trellis.py` (git worktree `.claude/worktrees/pixtex-1119`, branch trial/trellis2-pixtex). Upstream code: Pixal3D clone at `~/ext-src/pixal3d-1911/repo` (commit f7cf3842; inside the image it lives at /opt/Pixal3D), ComfyUI-Trellis2 clone at `~/ext-src/comfyui-trellis2-1911/repo` (has `texture_mesh_pixal3d`, trellis2/pipelines/trellis2_image_to_3d.py:~3705).

TECHNICAL QUESTION:
Both jobs failed inside `pipe.encode_shape_slat(mesh, 1024)` (Trellis2TexturingPipeline.encode_shape_slat → shape encoder `microsoft/TRELLIS.2-4B/ckpts/shape_enc_next_dc_f16c32_fp16` loaded via `pixal3d.models.from_pretrained`, sparse conv backend flex_gemm). What is the most likely root cause, and what exactly should change before the next (and last affordable, ~30 min of GPU) attempt so that it either succeeds or yields a decisive diagnosis?

OBSERVED FACTS:
- Container: torch 2.6.0+cu124, CUDA 12.4, driver 610.88, flex_gemm 1.0.0, o_voxel 0.0.1, cumesh 0.0.1, flash_attn 2.7.3, natten 0.21.0, python 3.10. Env `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (set by our worker before torch import).
- After warm-up (weights: tex_slat_flow_model_1024, tex_slat_decoder, shape encoder, DINOv3 tex_1024 extractor + NAF, MoGe-2; all .cuda()) nvidia-smi used 7539 MiB of 24564. `pipe.low_vram=False`.
- Job 1 traceback ends: encode_shape_slat (trellis2_texturing.py:219) → fdg_vae.py:50 → sparse_unet_vae.py:378 block → :204 `h.replace(self.norm2(h.feats))` → norm.py:9 manual_cast → utils.py:73 `tensor.type(dtype)` → `RuntimeError: CUDA driver error: device not ready` (82.8 s after submit).
- Job 2 (same process, next job, different variant, same mesh) traceback: same path → sparse_unet_vae.py:201 `self.conv1(h)` → conv_flex_gemm.py:46 → flex_gemm submanifold_conv3d.py:88 `_compute_neighbor_cache` → `kernels.cuda.neighbor_map_post_process_for_masked_implicit_gemm_1(neighbor_map)` → `RuntimeError: !handles_.at(i) INTERNAL ASSERT FAILED at CUDACachingAllocator.cpp:400`.
- Our code calls torch.cuda.empty_cache() between stages (hooks 'free'). Before encode_shape_slat nothing heavy ran in that job except mesh prep on CPU.
- A sibling run of full Pixal3D image→3D (different backend, low_vram=True) in the same image passed three stages and then OOM'd in decode_tex_slat (sparse_unet_vae.py:498) — so flex_gemm sparse convs do work in this image in some conditions.
- The input mesh is TRELLIS.2 output at 1024 ("clean.glb", dense).

Inspect the repository and the upstream clones directly (encode_shape_slat, the shape encoder config, how ComfyUI-Trellis2 calls it: resolution, mesh preprocessing/decimation, dtype, any env/allocator settings). Return:
1. conclusion (ranked hypotheses with probability);
2. evidence (file:line);
3. concrete changes for the next attempt (env vars, resolution, mesh simplification, CUDA_LAUNCH_BLOCKING for diagnosis, sync points), and which to combine in ONE run to maximise information;
4. risks/edge cases; 5. what evidence would change your conclusion.

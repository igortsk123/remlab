## 1. Conclusion

The two defects have different primary causes:

- **A, bed:** a BiRefNet false negative. The headboard is absent in the raw mask. Your hybrid recovery is deliberately limited to six pixels for beds, so no later operation can reconstruct a large externally connected panel.
- **B, lamp:** BiRefNet starts slightly oversized, but the visible beading is predominantly created by `close_edge_gaps`. It adds 1,876 opaque pixels—6.1% of its input foreground—including many source locations that are pure/near-white background. The following cleaners recognize the dirty edge but roll back because their safety limits fire.

A known-background rule is worthwhile, but **“foreground = everything not reached by white flood-fill” is not safe as a universal union**. It also classifies shadows, JPEG islands, gradients and white-product ambiguities as foreground. Use it as:

1. a conservative, border-connected **subtractor at the current silhouette**, and  
2. a strongly gated proposal generator for large missed bodies.

For soft edges, known-background inversion is the first choice here: deterministic, much faster on CPU, and directly attacks B. ViTMatte is worth an A/B test as a trimap refiner, but not as the first production change.

---

## 2. Evidence

### Actual executed chain

The run was produced by `cutout_redo → cutout_sync.chain`: [cutout_redo.py:521](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_redo.py:521), [cutout_redo.py:538](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_redo.py:538).

`cutout_page30.py` only renders the review page from saved artifacts: [cutout_page30.py:93](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_page30.py:93).

The actual order is:

1. hybrid: [cutout_sync.py:200](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_sync.py:200)
2. components clean: [cutout_sync.py:204](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_sync.py:204)
3. fill unlike-background holes: [cutout_sync.py:208](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_sync.py:208)
4. fill body holes: [cutout_sync.py:211](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_sync.py:211)
5. close edge gaps: [cutout_sync.py:214](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_sync.py:214)
6. `defringe`, containing halo/island/speck cleaning and RGB foreground estimation: [cutout_sync.py:220](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/cutout_sync.py:220), [preprocess.py:111](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/preprocess.py:111).

I replayed these operations in memory. The replayed trimmed RGBA was pixel-identical to the saved final cut for both examples.

### A — bed

BiRefNet is computed at a stretched 1024×1024 input, then resized back: [preprocess.py:44](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/preprocess.py:44), [preprocess.py:99](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/preprocess.py:99).

Measured on the 800×600 photo:

| Stage | Solid pixels, α > 0.5 | Change |
|---|---:|---:|
| Raw BiRefNet | 165,587 | — |
| Hybrid | 169,669 | +4,082 |
| Components clean | 169,669 | 0 |
| Hole filling | 169,694 | +25 |
| Edge-gap closing | 169,821 | +127 |
| Defringe/cleaning | 169,483 | −338 |

Outside the raw mask:

- 41,831 pixels, **8.715% of the frame**, differ from white by more than 6/channel.
- 40,865 pixels, **8.514%**, differ by more than 10/channel.
- 40,000 pixels, **8.333%**, meet the latter test and have raw α below 0.15.

The hybrid recognizes the background correctly, but only searches a six-pixel dilation around BiRefNet support: [hybrid_mask.py:98](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/hybrid_mask.py:98), [hybrid_mask.py:116](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/hybrid_mask.py:116). Full connected growth is enabled only for rugs: [hybrid_mask.py:66](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/hybrid_mask.py:66), [hybrid_mask.py:112](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/hybrid_mask.py:112).

The headboard is not an enclosed hole, so `binary_fill_holes` cannot reach it: [components.py:47](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/components.py:47). Beds are also intentionally absent from `SOLID_BODY_ROLES`: [components.py:228](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/components.py:228), [components.py:262](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/components.py:262).

**Root cause:** BiRefNet.  
**Why it remains:** the hybrid’s six-pixel search limit and the topology of the later fill operations.

### B — floor lamp

Measured on the 906×906 photo:

| Stage | Solid pixels | Change |
|---|---:|---:|
| Raw BiRefNet | 29,455 | — |
| Hybrid | 30,779 | +1,324 |
| Components clean | 30,772 | −7 |
| Hole filling | 30,772 | 0 |
| `close_edge_gaps` | 32,648 | **+1,876** |
| Defringe/cleaning | 32,520 | −128 |

`close_edge_gaps` performs binary closing and sets every accepted added pixel to α=1: [components.py:199](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/components.py:199), [components.py:210](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/components.py:210), [components.py:223](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/components.py:223).

Of its 1,876 additions:

- 958 lie at source locations within 6/channel of white.
- With a border-connected flood, 536 are reached at threshold 6 and 1,196 at threshold 10.
- The additions are 6.1% of the pre-closing foreground, far beyond a small notch correction.

The next stages detect the problem but retain it:

- `edge_halo` proposed removing 1,287 pixels, then rolled back because that exceeded 35% of the perimeter: [edge_halo.py:147](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/edge_halo.py:147).
- `clean_bg_like_specks` proposed 392 pixels, then skipped because that exceeded 1% of the body: [clean_islands.py:146](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/clean_islands.py:146).
- The final audit still reported 891 light-edge pixels, **28.7% of the perimeter**, and status `dirty`.

The foreground-estimation step cannot fix geometry: it explicitly changes RGB but not alpha: [fg_estimate.py:32](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/fg_estimate.py:32). The simple defringe equation likewise modifies color only: [preprocess.py:158](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/preprocess.py:158).

**Root cause:** slightly fat BiRefNet/hybrid support is the starting condition, but `close_edge_gaps` is the dominant creator of the final beads.  
**Why they remain:** both downstream cleaners hit their rollback caps.

### Full-run background evidence

The folder contains 1,295 product references but 1,244 unique photo/mask artifacts.

- The current hybrid gate accepts 1,186/1,244 unique photos, **95.3%**. Its criterion is loose: up to 35% foreign border pixels and background Euclidean distance up to 60 from white: [hybrid_mask.py:89](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/hybrid_mask.py:89).
- A stricter constant-background gate—median channels ≥245, channel spread ≤5, and 4%-ring Δ∞ percentiles p80≤6, p90≤10, p95≤18—accepts 979/1,244 unique images, **78.7%**, representing 1,015/1,295 products.
- An outermost-border version accepts 1,119/1,244, but is less protective against gradients and frame-touching products.
- The existing run classified 415/1,295 products as “light product on white” using its brightness heuristic.

Within the strict-background subset, raw-mask near-background contamination is usually tiny but has dangerous outliers: at Δ∞≤10, the median is zero, p95 is 0.80% of the mask, p99 is 8.36%, and the maximum is 55.37%. That tail is why unconditional color subtraction is unsafe for glass and genuinely white surfaces.

---

## 3. Recommended general rule

### A. Strict background eligibility

Estimate `B` from a robust cluster in the outer 4% ring. Enable analytic background processing only when:

- `min(B) ≥ 245`
- `max(B)-min(B) ≤ 5`
- ring residual `D∞ = max_c |I_c-B_c|` has:
  - p80 ≤ 6
  - p90 ≤ 10
  - p95 ≤ 18
- at least 70% of the perimeter supplies background-like seed pixels.

For a linear gradient, fit one plane per RGB channel using border inliers and require residuals to pass the same limits and predicted corner-to-corner range ≤18. Skip nonlinear vignettes rather than guessing.

Use adaptive thresholds:

```text
t_core = clip(max(6, 3 × border_MAD), 6, 10)
t_soft = min(t_core + 10, 20)
```

- `Rcore`: border flood-fill through `D∞ ≤ t_core`
- `Rsoft`: border flood-fill through `D∞ ≤ t_soft`

This handles ordinary JPEG noise without treating every non-exact-white pixel as product.

### B. Subtraction, especially for B

Apply this **after all alpha-growing operations**, so no later closing/filling can reintroduce background.

- Hard-zero `Rcore` only in an exterior band extending at most two pixels inside the pre-postprocessing α=0.5 boundary.
- In the `Rsoft` transition band, estimate local foreground color `F` from a nearby confident interior pixel and solve:

```text
alpha_color =
    clamp(((I-B) · (F-B)) / (||F-B||² + ε), 0, 1)
```

Then use `alpha = min(alpha, alpha_color)`.

If `||F-B||∞ < 20`, the object is too similar to the background; retain the model alpha instead of color-keying it. This protects white product highlights.

### C. Guard `close_edge_gaps`

Keep its useful behavior on chunky light furniture, but constrain it globally:

1. Proposed additions inside `Rcore` are forbidden.
2. Roll back the whole closing step when both:
   - additions exceed 1% of the input foreground, and
   - more than 20% of additions are in `Rcore`.

For the lamp: 6.1% growth and roughly 29% border-connected core-background hits at threshold 6, so the step is rejected.  
For the bed: 0.075% growth and about 0.8% core-background hits, so it remains allowed.

This is image-derived, not role- or product-specific.

### D. Conservative union for missed bodies such as A

Do not union the complete complement of `Rcore`. Instead form proposals from strong non-background pixels:

```text
P = (~Rsoft) & (raw_alpha < 0.15)
```

Keep only 8-connected components satisfying all of:

- touches a 3-pixel dilation of existing α≥0.5 support;
- area ≥ `max(0.25% of frame, 2% of current foreground)`;
- total addition ≤15% of the frame and ≤50% of current foreground;
- touches no more than 20% of the perimeter;
- is not predominantly a low-chroma region below the model’s per-column floor.

The existing shadow test already expresses the useful part of the last condition: [hybrid_mask.py:129](/home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout/salad/hybrid_mask.py:129).

At `t_soft=18`, the bed produces a roughly 39,600-pixel dominant proposal and passes. The lamp’s largest outside-mask proposal is only about 103 pixels and fails.

Add accepted pixels with a soft color-derived alpha, not α=1.

### E. Soft edges

For this catalog, prefer known-background matting first:

- Simple known-white inversion measured **0.035–0.041 s** for 1000×1000 on the local i5-13400F.
- Your current two-pass blur foreground estimation measured **0.446–0.494 s** at 1000×1000.

ViTMatte-S is a 25.8M-parameter trimap model; the official model reports strong SAD/MSE/gradient/connectivity results and requires image plus trimap. The official code is MIT and the official Hugging Face weights are Apache-2.0, both generally compatible with commercial use: [official repository](https://github.com/hustvl/ViTMatte), [official weights](https://huggingface.co/hustvl/vitmatte-small-composition-1k). The model card does not publish a CPU latency, so an honest 1000-pixel CPU number requires a local benchmark; plan for seconds, not the sub-second cost of the analytic path.

ViTMatte is likely better where optical transparency, hair-like structures or complex mixed edges matter. It will not solve A if the trimap declares the missing headboard definite background. Use:

- foreground: eroded high-confidence combined mask;
- background: `Rcore` farther than three pixels from any proposal;
- unknown: a 6–10-pixel boundary band plus all analytic/model disagreement regions.

---

## 4. Risks and edge cases

- **Drop shadows:** the fundamental union failure. Strong shadows can be connected, non-white and large. The lower/low-chroma veto helps but cannot cover every side shadow.
- **White product touching white background:** color alone is mathematically ambiguous. When `F≈B`, neither difference matting nor flood-fill can distinguish them. Preserve the model and flag disagreement.
- **Highlights reaching 255:** restrict subtraction to border-connected pixels and a two-pixel inward band; never flood arbitrarily through a solid mask.
- **Glass and transparent furniture:** optical alpha and mesh occupancy are different targets. A perfect matte can erase transparent glass even though the 3D generator needs occupied silhouette.
- **JPEG blocks:** adaptive 6–10 thresholds handle ordinary noise; the minimum-component rule prevents isolated JPEG residuals becoming product.
- **Gradient/vignetted backgrounds:** fit and validate a spatial background plane or skip. A constant-white rule should not be stretched to these images.
- **Products touching the frame:** seed only background-like border pixels. If fewer than 70% exist, disable union; local subtraction can still operate on reachable sides.
- **Morphological closing:** the run’s roughness metric improved for 240/415 light products, was unchanged for 68, and worsened for 107. Removing the step globally would discard real benefit; guarding it is preferable.
- **Background detection is not ground truth:** in the strict subset, some masks contain over 50% near-white pixels—likely glass/white products—so raw color similarity cannot be treated as proof of background.

---

## 5. Alternatives

- **SAM 2.1 with an automatically padded box:** useful as an independent body detector and disagreement signal, particularly for A. Use its confident interior only; its binary edge should not replace the final matte. The official implementation/checkpoints are Apache-2.0, but published speeds are A100 GPU speeds, not CPU: [SAM 2 repository](https://github.com/facebookresearch/sam2).
- **BiRefNet Dynamic or BiRefNet-matting:** the most relevant model variants to test. Dynamic resolution avoids the current forced square resize; the matting variant targets soft alpha. The official project lists dynamic, matting, HR and HR-matting variants under its MIT project: [BiRefNet repository](https://github.com/ZhengPeng7/BiRefNet). Test 50–100 hard cases, not another complete run first.
- **BiRefNet-HR:** deprioritize. Your 5–9× slowdown/no-gain result is stronger evidence for this dataset than the general benchmark. The official HR card itself shows resolution-dependent results rather than universal improvement: [BiRefNet-HR card](https://huggingface.co/ZhengPeng7/BiRefNet_HR).
- **BEN2:** MIT model card and a confidence-guided refiner, but your shadow-trail result directly conflicts with the mesh objective. Keep only as a disagreement model: [official BEN2 card](https://huggingface.co/PramaLLC/BEN2).
- **InSPyReNet:** MIT and aimed at high-resolution salient-object boundaries, but your observed torn edges disqualify it as the primary model here: [official repository](https://github.com/plemeri/InSPyReNet).
- **RMBG:** exclude under the stated requirement. RMBG 2.0’s self-hosted weights are explicitly non-commercial without a separate agreement: [official model card](https://huggingface.co/briaai/RMBG-2.0).

---

## 6. Objective measurement over all 1,295 products

Report both **1,244 unique images** and **1,295 product-weighted results**.

Without human ground truth:

- **Border-connected background retention:** alpha mass at `Rcore` source positions, especially in a three-pixel boundary band.
- **Post-step pollution:** for every step, count added alpha pixels that lie in `Rcore`/`Rsoft`. This metric immediately exposes the lamp.
- **Strong-miss proposal share:** accepted/rejected `P` area outside α, with component size and shadow score. This exposes the bed.
- **Edge halo energy:** alpha-weighted background likelihood along the silhouette.
- **Topology:** connected-component count, thin-structure survival, new bridges and holes.
- **Model/analytic disagreement:** BiRefNet versus analytic proposal and, if tested, SAM2.

For a real accuracy claim, build a locked human-annotated trimap/alpha subset. Measure:

- foreground false-negative mass: lost body;
- background false-positive mass: leftover background;
- IoU at α=0.5;
- SAD and MSE;
- gradient and connectivity errors—the same metric families reported by ViTMatte;
- boundary F-score at 1, 2 and 4 pixels;
- component/topology errors for rods, wires and slats.

Review by eye:

- all 34 lighting items;
- stratified sample from the 415 light-on-white items;
- all transparent/glass items;
- top 30 strong-miss proposals;
- top 30 retained-background scores;
- top 30 per-step growth scores;
- gradient/vignette and frame-touching skips;
- shadow-heavy photos;
- a blind random 100-image sample.

Tune on one partition, freeze thresholds, and evaluate once on a held-out partition.

---

## 7. Uncertainties and evidence that would change the conclusion

Current uncertainties:

- There is no true alpha/body ground truth in the run.
- Shadow versus pale product is not resolvable from a single RGB image and a background color in every case.
- ViTMatte CPU latency has not been measured on your deployment CPU.
- ViTMatte’s code/weights licenses permit commercial use, but training-dataset provenance should still receive normal legal review.
- The proposed union thresholds are supported by these two cases and full-run distributions, not yet by a held-out labeled set.

I would change the recommendation if:

- A held-out trimap set showed the analytic union adding more than 0.1% frame background or materially retaining shadows.
- The closing guard reduced thin-structure recall or failed to reduce the lamp-class background-retention metric.
- ViTMatte-S reduced boundary SAD/gradient error by at least ~20% over analytic matting at an acceptable measured CPU latency.
- SAM2 consistently recovered large missed bodies while excluding shadows on the low-contrast subset.
- BiRefNet Dynamic or matting variants recovered A-type bodies and reduced B-type halos without your observed HR cost.

No files were created, modified or deleted.
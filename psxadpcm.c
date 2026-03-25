/*
 * PS-ADPCM Encoder for Burnout 3: Takedown — Optimized HQ
 * Tests 5 filters × 3 smart shifts = 15 combos (vs 65 brute force)
 * LLRR layout, LO-first nibbles, flags=0x02
 * 
 * Compile: gcc -O3 -march=native -shared -fPIC -o libpsxenc.so psxadpcm.c -lm
 */
#include <math.h>
#include <string.h>

static const double COEFS[5][2] = {
    { 0.0,       0.0      },
    { 0.9375,    0.0      },
    { 1.796875, -0.8125   },
    { 1.53125,  -0.859375 },
    { 1.90625,  -0.9375   },
};

/* Precomputed shift scales */
static const double SCALES[13] = {
    4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1
};

static inline int calc_ideal_shift(const double *samples, int n,
                                    double c1, double c2,
                                    double p1, double p2)
{
    double max_d = 0, d, tp1 = p1, tp2 = p2;
    int i;
    for (i = 0; i < 8 && i < n; i++) {
        d = fabs(samples[i] - (tp1 * c1 + tp2 * c2));
        if (d > max_d) max_d = d;
        tp2 = tp1;
        tp1 = samples[i];
    }
    if (max_d < 7.0) return 12;
    int s = 12 - (int)(log2(max_d / 7.0));
    if (s < 0) return 0;
    if (s > 12) return 12;
    return s;
}

static double try_encode(const double *samples, int n,
                         double c1, double c2, double scale,
                         double p1, double p2,
                         int nibs_out[28],
                         double *out_p1, double *out_p2)
{
    double err = 0, pred, raw, dec, s;
    int i, nib;
    double tp1 = p1, tp2 = p2;

    for (i = 0; i < 28; i++) {
        s = (i < n) ? samples[i] : 0.0;
        pred = tp1 * c1 + tp2 * c2;
        raw = (s - pred) / scale;
        nib = (int)(raw + (raw >= 0 ? 0.5 : -0.5));
        if (nib < -8) nib = -8;
        if (nib > 7) nib = 7;
        nibs_out[i] = nib;
        dec = nib * scale + pred;
        if (dec > 32767.0) dec = 32767.0;
        if (dec < -32768.0) dec = -32768.0;
        err += (s - dec) * (s - dec);
        tp2 = tp1;
        tp1 = dec;
    }
    *out_p1 = tp1;
    *out_p2 = tp2;
    return err;
}

static void encode_block(const double *samples, int n,
                         unsigned char *out, double *p1, double *p2)
{
    int best_filt = 0, best_shift = 0;
    double best_err = 1e30;
    double best_p1 = *p1, best_p2 = *p2;
    int best_nibs[28];
    int filt, shift, ideal, nibs[28], lo, hi;
    double err, np1, np2;

    for (filt = 0; filt < 5; filt++) {
        double c1 = COEFS[filt][0], c2 = COEFS[filt][1];
        
        /* Calculate ideal shift for this filter */
        ideal = calc_ideal_shift(samples, n, c1, c2, *p1, *p2);
        
        /* Try ideal and ±2 (5 shifts per filter = 25 total, good quality/speed balance) */
        lo = ideal - 2; if (lo < 0) lo = 0;
        hi = ideal + 2; if (hi > 12) hi = 12;
        
        for (shift = lo; shift <= hi; shift++) {
            err = try_encode(samples, n, c1, c2, SCALES[shift],
                             *p1, *p2, nibs, &np1, &np2);

            if (err < best_err) {
                best_err = err;
                best_filt = filt;
                best_shift = shift;
                best_p1 = np1;
                best_p2 = np2;
                memcpy(best_nibs, nibs, sizeof(best_nibs));
                
                /* Early exit on near-perfect match */
                if (err < 1.0) goto done;
            }
        }
    }

done:
    out[0] = (best_filt << 4) | best_shift;
    out[1] = 0x02;
    memset(out + 2, 0, 14);

    {
        int i, j;
        for (i = 0; i < 28; i++) {
            j = i / 2;
            if (i % 2 == 0)
                out[2 + j] = best_nibs[i] & 0xF;
            else
                out[2 + j] |= (best_nibs[i] & 0xF) << 4;
        }
    }

    *p1 = best_p1;
    *p2 = best_p2;
}

int encode_burnout3_adpcm(const short *pcm, int n_samples,
                          unsigned char *out, int slot_size)
{
    int n_per_ch = n_samples / 2;
    double p1_l = 0, p2_l = 0, p1_r = 0, p2_r = 0;
    double samps[28];
    int l_idx = 0, r_idx = 0;
    int sblock, sub, block_i, boff, i, idx;

    /* Fill with silence */
    for (i = 0; i < slot_size; i += 16) {
        out[i] = 0x0C;
        out[i + 1] = 0x02;
        memset(out + i + 2, 0, 14);
    }

    /* LLRR super-blocks of 8192 bytes */
    for (sblock = 0; sblock < slot_size; sblock += 8192) {
        /* LEFT: 2 × 2048 at offset 0 and 2048 */
        for (sub = 0; sub < 2; sub++) {
            for (block_i = 0; block_i < 2048; block_i += 16) {
                boff = sblock + sub * 2048 + block_i;
                if (boff + 16 > slot_size) return slot_size;
                for (i = 0; i < 28; i++) {
                    idx = l_idx + i;
                    samps[i] = (idx < n_per_ch) ? (double)pcm[idx * 2] : 0.0;
                }
                l_idx += 28;
                encode_block(samps, 28, out + boff, &p1_l, &p2_l);
            }
        }
        /* RIGHT: 2 × 2048 at offset 4096 and 6144 */
        for (sub = 0; sub < 2; sub++) {
            for (block_i = 0; block_i < 2048; block_i += 16) {
                boff = sblock + 4096 + sub * 2048 + block_i;
                if (boff + 16 > slot_size) return slot_size;
                for (i = 0; i < 28; i++) {
                    idx = r_idx + i;
                    samps[i] = (idx < n_per_ch) ? (double)pcm[idx * 2 + 1] : 0.0;
                }
                r_idx += 28;
                encode_block(samps, 28, out + boff, &p1_r, &p2_r);
            }
        }
    }
    return slot_size;
}

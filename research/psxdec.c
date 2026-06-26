/*
 * PS-ADPCM decoder for Burnout 3 (reference / debugging).
 *
 * Decodes the exact LLRR super-block layout the encoder (psxadpcm.c) produces:
 *   8192-byte super-block = L[2048] L[2048] R[2048] R[2048]
 * so each channel's stream is the concatenation of its 4096-byte halves.
 *
 * The decode is the canonical integer PS-ADPCM math, which the encoder models
 * exactly (round(nibble*scale + predictor) == nibble*scale + round(predictor)
 * since nibble*scale is integral). So a round-trip is bit-faithful to what the
 * PS2 SPU reconstructs — letting us isolate "encoder vs game" for audio glitches.
 *
 * reset_mode: 0 = predictor carries across the whole channel (what the encoder
 * assumes / standard streaming), 1 = reset per super-block (4096 B), 2 = reset
 * per 2048-byte sub-block — to test whether the game resets the predictor at a
 * boundary (which would make a carried-predictor encode click on loud boundaries).
 *
 * Compile: gcc -O3 -shared -fPIC -o libpsxdec.so psxdec.c -lm
 */
#include <math.h>

static const double COEFS[5][2] = {
    { 0.0,      0.0      },
    { 0.9375,   0.0      },
    { 1.796875, -0.8125  },
    { 1.53125,  -0.859375},
    { 1.90625,  -0.9375  },
};
static const double SCALES[13] = {4096,2048,1024,512,256,128,64,32,16,8,4,2,1};

/* Decode one channel; out is interleaved stereo (step 2), starting at out+ch. */
static void decode_channel(const unsigned char *slot, int nsb, int ch,
                           short *out, int reset_mode)
{
    double p1 = 0.0, p2 = 0.0;
    long oi = ch;
    for (int sb = 0; sb < nsb; sb++) {
        int base = sb * 8192 + (ch ? 4096 : 0);   /* L at 0, R at 4096 */
        if (reset_mode == 1) { p1 = 0; p2 = 0; }    /* reset per super-block */
        for (int half = 0; half < 4096; half += 16) {
            if (reset_mode == 2 && (half % 2048) == 0) { p1 = 0; p2 = 0; }
            const unsigned char *b = slot + base + half;
            int header = b[0];
            int shift = header & 0x0F;
            int filt  = (header >> 4) & 0x0F;
            if (filt > 4) filt = 0;
            double c1 = COEFS[filt][0], c2 = COEFS[filt][1];
            double scale = (shift <= 12) ? SCALES[shift] : 1.0;
            for (int i = 0; i < 28; i++) {
                int byte = b[2 + i / 2];
                int nib = (i & 1) ? ((byte >> 4) & 0xF) : (byte & 0xF);  /* LO first */
                if (nib >= 8) nib -= 16;                                  /* sign-extend */
                double s = nib * scale + p1 * c1 + p2 * c2;
                s = round(s);
                if (s > 32767.0)  s = 32767.0;
                if (s < -32768.0) s = -32768.0;
                out[oi] = (short)s;
                oi += 2;
                p2 = p1; p1 = s;
            }
        }
    }
}

/* Returns samples-per-channel. out must hold nsb*7168*2 shorts. */
int decode_llrr(const unsigned char *slot, int slot_size, short *out, int reset_mode)
{
    int nsb = slot_size / 8192;
    decode_channel(slot, nsb, 0, out, reset_mode);
    decode_channel(slot, nsb, 1, out, reset_mode);
    return nsb * 7168;
}

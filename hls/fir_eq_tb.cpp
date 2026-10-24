#include "ap_int.h"
#include "ap_axi_sdata.h"
#include "hls_stream.h"
#include <cstdio>

#define NTAPS 64

void fir_eq(hls::stream<ap_axis<32,0,0,0> > &in_stream,
            hls::stream<ap_axis<32,0,0,0> > &out_stream,
            ap_int<16> coeffs[NTAPS]);

int main() {
    // Coefficients: 64 x 1/64 in Q15 (32768/64 = 512) -> moving average = low-pass
    ap_int<16> coeffs[NTAPS];
    for (int i = 0; i < NTAPS; i++) coeffs[i] = 512;

    hls::stream<ap_axis<32,0,0,0> > in_s, out_s;

    // Feed 128 complex samples: sample 0 has an impulse (32767) on the REAL
    // part only (low 16 bits), imaginary part stays 0.
    for (int n = 0; n < 128; n++) {
        ap_axis<32,0,0,0> w;
        w.data = (n == 0) ? 32767 : 0;   // real impulse, imag = 0
        w.last = (n == 127);
        in_s.write(w);
        fir_eq(in_s, out_s, coeffs);     // run DUT in software
        ap_axis<32,0,0,0> r = out_s.read();
        int got_re = (int)r.data.range(15, 0);
        int got_im = (int)r.data.range(31, 16);
        // Expected impulse response: real = 512 for first 64, then 0; imag always 0
        int exp_re = (n < NTAPS) ? 512 : 0;
        if (got_re != exp_re || got_im != 0) {
            printf("FAIL @%d: got (%d, %d) expect (%d, 0)\n", n, got_re, got_im, exp_re);
            return 1;
        }
    }
    printf("ALL TESTS PASSED! Complex FIR impulse response is correct.\n");
    return 0;
}

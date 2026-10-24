#include "ap_int.h"
#include "ap_axi_sdata.h"
#include "hls_stream.h"

#define NTAPS 64   // 64-tap FIR: remembers the last 64 samples

// Top function: 32-bit COMPLEX samples on AXI-Stream (low 16 = real, high 16 = imag)
// Coefficients come in through AXI-Lite (the "drawer cabinet")
void fir_eq(hls::stream<ap_axis<32,0,0,0> > &in_stream,
            hls::stream<ap_axis<32,0,0,0> > &out_stream,
            ap_int<16> coeffs[NTAPS]) {
#pragma HLS INTERFACE axis port=in_stream
#pragma HLS INTERFACE axis port=out_stream
#pragma HLS INTERFACE s_axilite port=coeffs
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL
#pragma HLS INTERFACE ap_ctrl_none port=return

    static ap_int<16> shift_re[NTAPS];  // shift register for REAL part
    static ap_int<16> shift_im[NTAPS];  // shift register for IMAG part
#pragma HLS ARRAY_PARTITION variable=shift_re complete dim=1
#pragma HLS ARRAY_PARTITION variable=shift_im complete dim=1

    ap_axis<32,0,0,0> in_word, out_word;

    // STREAMING FIX: hardware runs this loop FOREVER (one sample per round).
    // Without the loop the module processed exactly ONE sample and retired.
    while (true) {
        // Read one complex sample and split it
        in_stream.read(in_word);
        ap_int<16> x_re = in_word.data.range(15, 0);    // low 16 bits  = real
        ap_int<16> x_im = in_word.data.range(31, 16);   // high 16 bits = imag

        // Shift both registers one slot
        for (int i = NTAPS - 1; i > 0; i--) {
            shift_re[i] = shift_re[i - 1];
            shift_im[i] = shift_im[i - 1];
        }
        shift_re[0] = x_re;
        shift_im[0] = x_im;

        // 64 multiplications in parallel for EACH part (128 MACs total)
        ap_int<32> acc_re = 0;
        ap_int<32> acc_im = 0;
        for (int i = 0; i < NTAPS; i++) {
#pragma HLS UNROLL
            acc_re += shift_re[i] * coeffs[i];
            acc_im += shift_im[i] * coeffs[i];
        }

        // Q15 with ROUNDING: add half LSB before shifting back
        out_word.data.range(15, 0)  = (ap_int<16>)((acc_re + (1 << 14)) >> 15);
        out_word.data.range(31, 16) = (ap_int<16>)((acc_im + (1 << 14)) >> 15);
        out_word.last = in_word.last;
        out_stream.write(out_word);
    }
}

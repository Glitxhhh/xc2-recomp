// Decodes a voice along the same sample path as the voice clock (advance_voice in audren.c). A header so that
// tests/audren_check.c can run the decoder and the clock together without SDL; audio_mixer.c is its only runtime user.
#pragma once

#include <stdint.h>
#include <string.h>

#include "audren.h"

#define MAX_FRAME 1024

/* ---------- voice decoding along the voice clock's sample path ---------- */
typedef struct { ServerVoice *v; unsigned index; uint64_t offset; int32_t loops; uint8_t valid[4]; int16_t h1, h2; int32_t abuf; uint64_t aat; } Walk;
static int fmt_bytes(int f) { return f == FMT_PCM8 ? 1 : f == FMT_PCM16 ? 2 : f==FMT_PCM24?3:f == FMT_PCM32 || f == FMT_PCMF32 ? 4 : 0; }
/* DSP-ADPCM: 8-byte frames of a predictor/scale byte and 14 4-bit samples; the history runs across samples. */
static int16_t adpcm_next(Walk *w, const AudrenWaveBuffer *b, const int16_t *coef, uint64_t i) {
    const uint8_t *d = (const uint8_t *)(uintptr_t)b->address;
    uint64_t frame = i / 14, nib = i % 14;
    if ((frame + 1) * 8 > b->size) return 0;
    uint8_t ps = d[frame * 8]; int scale = 1 << (ps & 15), pred = (ps >> 4) & 7;
    int n = (d[frame * 8 + 1 + nib / 2] >> ((nib & 1) ? 0 : 4)) & 15; if (n >= 8) n -= 16;
    int64_t s = (int64_t)n * scale * 2048 + 1024 + (int64_t)coef[pred * 2] * w->h1 + (int64_t)coef[pred * 2 + 1] * w->h2;
    s >>= 11; if (s > 32767) s = 32767; if (s < -32768) s = -32768;
    w->h2 = w->h1; w->h1 = (int16_t)s; return (int16_t)s;
}
static float sample_at(Walk *w, int ch) {
    if (!w->valid[w->index]) return 0;
    ServerVoice *v = w->v; const AudrenWaveBuffer *b = &v->buffers[w->index];
    uint64_t i = (uint64_t)b->start + w->offset; int f = v->in.sample_format, cc = (int)v->in.channel_count;
    if (f == FMT_ADPCM) {
        if (cc != 1 || !v->in.extra_address || v->in.extra_size < 32) return 0;
        const int16_t *coef = (const int16_t *)(uintptr_t)v->in.extra_address;
        if (w->abuf != (int32_t)w->index || w->aat > i + 1) {   /* (re)start this buffer: from its context, else from the frame boundary with carried history */
            w->abuf = (int32_t)w->index;
            if (b->context_address && b->context_size >= 6) { const int16_t *c = (const int16_t *)(uintptr_t)b->context_address; w->h1 = c[1]; w->h2 = c[2]; w->aat = (uint64_t)b->start; }
            else w->aat = (uint64_t)b->start - (uint64_t)b->start % 14;
            if (i < w->aat) w->aat = i;
        }
        while (w->aat <= i) adpcm_next(w, b, coef, w->aat++);
        return w->h1 / 32768.0f;
    }
    int bytes = fmt_bytes(f); if (!bytes || ch >= cc) return 0;
    uint64_t at = (i * (uint64_t)cc + (uint64_t)ch) * (uint64_t)bytes;
    if (at + (uint64_t)bytes > b->size) return 0;
    const uint8_t *p = (const uint8_t *)(uintptr_t)b->address + at;
    switch (f) {
    case FMT_PCM8: return (int8_t)p[0] / 128.0f;
    case FMT_PCM16: { int16_t s; memcpy(&s, p, 2); return s / 32768.0f; }
    case FMT_PCM24: {uint32_t word=(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16;return ((int32_t)(word<<8)>>8)/8388608.f;}
    case FMT_PCM32: { int32_t s; memcpy(&s, p, 4); return (float)(s / 2147483648.0); }
    default: { float s; memcpy(&s, p, 4); return s; }
    }
}
static void walk_skip_empty(Walk *w) {   /* the same as skip_empty in audren.c: no samples, played on arrival */
    while (w->valid[w->index] && audio_buffer_empty(&w->v->buffers[w->index])) {
        const AudrenWaveBuffer *b = &w->v->buffers[w->index];
        if (b->loop && b->loop_count < 0) break;
        w->valid[w->index] = 0; w->offset = 0; w->loops = 0; w->index = (w->index + 1) & 3;
    }
}
static void walk_step(Walk *w) {   /* the same transitions as advance_voice in audren.c */
    if (!w->valid[w->index]) return;
    const AudrenWaveBuffer *b = &w->v->buffers[w->index];
    uint64_t length = (uint64_t)(b->end - b->start);
    if (++w->offset < length) return;
    if (b->loop && (b->loop_count < 0 || w->loops < b->loop_count)) { w->loops++; w->offset = b->loop_start > b->start && b->loop_start < b->end ? (uint64_t)(b->loop_start - b->start) : 0; return; }
    w->valid[w->index] = 0; w->offset = 0; w->loops = 0; w->index = (w->index + 1) & 3;
    walk_skip_empty(w);
}
/* Decodes `frames` output samples per channel into out[c][k]; the renderer advances the voice afterwards by the same amount. */
static void voice_render(AudioRenderer *r, ServerVoice *v, float out[6][MAX_FRAME], int frames) {
    const double step = v->in.sample_rate * (v->in.pitch > 0 ? v->in.pitch : 1.0) / r->param.sample_rate;
    Walk w = {v, v->index, v->offset, v->loops_done, {0}, v->adpcm.history[0], v->adpcm.history[1], v->adpcm.buffer, v->adpcm.at};
    memcpy(w.valid, v->valid, sizeof w.valid);
    walk_skip_empty(&w);
    int cc = (int)v->in.channel_count; double frac = v->fraction;
    for (int k = 0; k < frames; k++) {
        Walk next = w; walk_step(&next);
        for (int c = 0; c < cc; c++) { float s0 = sample_at(&w, c), s1 = sample_at(&next, c); out[c][k] = (float)(s0 + (s1 - s0) * frac); }
        frac += step;
        while (frac >= 1.0) { frac -= 1.0; walk_step(&w); }
    }
    v->adpcm.history[0] = w.h1; v->adpcm.history[1] = w.h2; v->adpcm.buffer = w.abuf; v->adpcm.at = w.aat;
}

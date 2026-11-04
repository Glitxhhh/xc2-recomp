// Exercise runtime/ov_movie.c worker with synthetic decoded images and a deterministic single-thread scheduler.
#include <assert.h>
#include <stdio.h>
#include "../runtime/host.h"
#undef HOST_OVERRIDE
#define HOST_OVERRIDE(sym, fn)
#include "../runtime/ov_movie.c"

static Movie *active;
static vpx_image_t frames[2];
static int nframes, locked;
static vpx_codec_err_t decode_result;
void rt_log(const char *fmt, ...) { (void)fmt; }
void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
uint64_t kern_now_ns(void) { return 0; }
void plat_mutex_lock(PlatMutex *m) { (void)m; assert(!locked); locked = 1; }
void plat_mutex_unlock(PlatMutex *m) { (void)m; assert(locked); locked = 0; }
void plat_cond_wait(PlatCond *c, PlatMutex *m) {
    (void)c; (void)m;
    assert(locked && !active->npending);
    active->quit = 1;
}
void plat_cond_broadcast(PlatCond *c) { (void)c; assert(locked); }
vpx_codec_err_t vpx_codec_decode(vpx_codec_ctx_t *ctx, const uint8_t *data, unsigned int size, void *user, long deadline) {
    (void)ctx; (void)data; (void)size; (void)user; (void)deadline;
    assert(!locked && active->busy && active->out_held[0]);
    return decode_result;
}
vpx_image_t *vpx_codec_get_frame(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *it) {
    (void)ctx;
    uintptr_t i = (uintptr_t)*it;
    *it = (void *)(i + 1);
    return i < (uintptr_t)nframes ? &frames[i] : NULL;
}
const char *vpx_codec_error_detail(const vpx_codec_ctx_t *ctx) { (void)ctx; return "injected error"; }
const char *vpx_codec_err_to_string(vpx_codec_err_t e) { (void)e; return "injected error"; }

static uint8_t output[8], pixels[6] = {1, 2, 3, 4, 5, 6}, input;
static void setup(Movie *m) {
    *m = (Movie){.started = 1, .vpx_live = 1, .w = 2, .h = 2, .npending = 1};
    m->pending[0] = (Pending){.index = 0, .size = 1};
    m->in[0] = &input; m->out[0] = output;
    memset(output, 0xcc, sizeof output);
    frames[0] = (vpx_image_t){.fmt = VPX_IMG_FMT_I420, .d_w = 2, .d_h = 2,
                             .planes = {pixels, pixels + 4, pixels + 5}, .stride = {2, 1, 1}};
    frames[1] = frames[0];
    nframes = 1; decode_result = VPX_CODEC_OK; active = m;
}
static void rejected(Movie *m, int eos) {
    worker(m);
    assert(!locked && !m->busy && m->nin_free == 1 && m->in_free[0] == 0);
    assert(m->st.errors == 1 && m->last_error == ST_ERROR && m->st.frames == 0);
    assert((m->owed & ((1u << MOVIE_EV_INPUT) | (1u << MOVIE_EV_ERROR))) ==
                      ((1u << MOVIE_EV_INPUT) | (1u << MOVIE_EV_ERROR)));
    assert(!(m->owed & (1u << MOVIE_EV_FORMAT)) && !m->format_sent);
    assert(m->ndecoded == eos && m->out_held[0] == eos);
    if (eos) assert(m->decoded[0].flags == MOVIE_FLAG_EOS && m->out_bytes[0] == 0);
    assert(output[6] == 0xcc && output[7] == 0xcc);
}
int main(void) {
    Movie m;
    for (int kind = 0; kind < 4; kind++) {
        setup(&m);
        if (kind == 0) frames[0].fmt = VPX_IMG_FMT_I444;
        if (kind == 1) frames[0].d_w = 4;
        if (kind == 2) frames[0].d_h = 4;
        if (kind == 3) decode_result = VPX_CODEC_CORRUPT_FRAME;
        rejected(&m, 0);
        for (int i = 0; i < 8; i++) assert(output[i] == 0xcc);
        // The released slot can carry the next valid frame without Reset or Configure.
        frames[0].fmt = VPX_IMG_FMT_I420; frames[0].d_w = frames[0].d_h = 2;
        decode_result = VPX_CODEC_OK;
        m.quit = 0; m.npending = 1; m.nin_free = 0;
        worker(&m);
        assert(m.ndecoded == 1 && m.st.frames == 1 && m.st.errors == 1 && m.out_held[0]);
        assert(!memcmp(output, pixels, 6) && output[6] == 0xcc && output[7] == 0xcc);
    }
    setup(&m); frames[1].d_w = 4; nframes = 2;
    rejected(&m, 0);   // a later incompatible frame invalidates the whole packet
    setup(&m); frames[0].d_h = 4; m.pending[0].flags = MOVIE_FLAG_EOS;
    rejected(&m, 1);
    setup(&m); nframes = 0;
    worker(&m);
    assert(!m.st.errors && !m.ndecoded && !m.out_held[0] && m.nin_free == 1);
    puts("movie worker: layout errors, slot recovery, EOS and empty decode passed");
    return 0;
}

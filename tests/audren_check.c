// Synthetic RequestUpdate and voice-clock checks; no game files or audio device.
// Include the implementation to exercise its private wire parser and frame transitions.
#include <assert.h>
#include "../runtime/audren.c"
#include "../runtime/audio_voice_walk.h"

unsigned rt_trace;
void rt_log(const char *fmt, ...) { (void)fmt; }
void rt_fatal(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    abort();
}
void ipc_backtrace(void) {}
void plat_mutex_lock(PlatMutex *lock) { (void)lock; }
void plat_mutex_unlock(PlatMutex *lock) { (void)lock; }
void audio_mixer_update_effects(AudioRenderer *r) { (void)r; }
void audio_mixer_update_routing(AudioRenderer *r, const uint8_t *s, uint32_t sn,
                              const uint8_t *m, uint32_t mn, int mc) {
    (void)r; (void)s; (void)sn; (void)m; (void)mn; (void)mc;
}
void audio_mixer_effect_result(AudioRenderer *r, int id, void *out, unsigned size) {
    (void)r; (void)id; (void)out; (void)size;
}
uint32_t audio_mixer_sink_written(AudioRenderer *r, int id) { (void)r; (void)id; return 0; }

typedef struct {
    AudioRenderer r;
    AudrenHeader h;
    uint8_t *input, *output;
    size_t voice_at, output_size;
} Fixture;

static Fixture fixture(int count, unsigned revision) {
    Fixture f = {0};
    f.r.param = (AudrenParameter){.sample_rate = 48000, .sample_count = 240,
        .voice_count = count, .sink_count = 1, .effect_count = 3, .submix_count = 4};
    f.r.voices = calloc(count, sizeof *f.r.voices);
    f.r.pools = calloc(4 * count + 3, sizeof *f.r.pools);
    f.r.channels = calloc(6 * count, sizeof *f.r.channels);
    f.r.sinks = calloc(1, sizeof *f.r.sinks);
    f.r.effects = calloc(3, sizeof *f.r.effects);
    f.h = (AudrenHeader){.revision = AUDREN_REV(revision), .behavior = 16,
        .memory_pools = (4 * count + 3) * sizeof(AudrenPoolIn),
        .voice_resources = count * sizeof(AudrenChannelIn),
        .voices = count * (revision >= 15 ? sizeof(AudrenVoiceInV2) : sizeof(AudrenVoiceIn)),
        .effects = 3 * sizeof(AudrenEffectIn), .mixes = 5 * sizeof(AudrenMixIn),
        .sinks = sizeof(AudrenSinkIn), .performance = 16};
    f.h.total = sizeof f.h + f.h.behavior + f.h.memory_pools + f.h.voice_resources + f.h.voices +
        f.h.effects + f.h.mixes + f.h.sinks + f.h.performance;
    f.input = calloc(1, f.h.total);
    memcpy(f.input, &f.h, sizeof f.h);
    f.voice_at = sizeof f.h + f.h.behavior + f.h.memory_pools + f.h.voice_resources;
    // Leave room for the separately tested render-info reply on older revisions.
    f.output_size = sizeof(AudrenHeader) + (4 * count + 3) * sizeof(AudrenPoolOut) +
        count * sizeof(AudrenVoiceOut) + 3 * (revision >= 9 ? 0x90 : 0x10) + sizeof(AudrenSinkOut) +
        16 + AUDREN_BEHAVIOR_OUT + AUDREN_RENDER_INFO_OUT;
    f.output = calloc(1, f.output_size);
    return f;
}

static void dispose(Fixture *f) {
    free(f->input); free(f->output);
    free(f->r.voices); free(f->r.pools); free(f->r.channels); free(f->r.sinks);
    free(f->r.effects);
}

static void put_voice(Fixture *f, unsigned slot, AudrenVoiceIn v) {
    if (revision_number(f->h.revision) >= 15) {
        AudrenVoiceInV2 v2 = {0};
        memcpy(v2.prefix, &v, sizeof v2.prefix);
        memcpy(v2.tail, (uint8_t *)&v + 0x3c, sizeof v2.tail);
        memcpy(f->input + f->voice_at + slot * sizeof v2, &v2, sizeof v2);
    } else {
        memcpy(f->input + f->voice_at + slot * sizeof v, &v, sizeof v);
    }
}

static void update(Fixture *f) {
    request_update(&f->r, f->input, f->h.total, f->output, f->output_size, 0);
}

static AudrenVoiceIn voice(unsigned id) {
    AudrenVoiceIn v = {.id = id, .is_new = 1, .in_use = 1, .play_state = PLAY_STARTED,
        .sample_format = FMT_PCM16, .sample_rate = 48000, .channel_count = 1,
        .pitch = 1, .volume = 1, .wave_buffer_count = 1};
    for (int i = 0; i < 4; i++) v.wave_buffers[i].sent = 1;
    // The clock never dereferences the synthetic PCM address; mixing is stubbed out.
    v.wave_buffers[0] = (AudrenWaveBuffer){.address = 0x10000, .size = 960, .end = 480};
    return v;
}

static void tick(Fixture *f) {
    voices_prepare(&f->r);
    for (int i = 0; i < f->r.param.voice_count; i++) advance_voice(&f->r, &f->r.voices[i], .005);
}

static void inactive_entries(unsigned revision) {
    Fixture f = fixture(4, revision);
    AudrenVoiceIn v = voice(0);
    put_voice(&f, 0, v);
    // Unused wire entries have only in_use defined. Zero-filled entries have id 0.
    update(&f);
    tick(&f);
    assert(f.r.voices[0].in.in_use && f.r.voices[0].played == 240);
    v.is_new = 0;
    v.wave_buffers[0].sent = 1;
    put_voice(&f, 0, v);
    // A stale ID may also be outside the renderer's voice range.
    put_voice(&f, 1, (AudrenVoiceIn){.id = UINT32_MAX});
    update(&f);
    tick(&f);
    assert(f.r.voices[0].played == 480 && f.r.voices[0].consumed == 1);
    put_voice(&f, 0, (AudrenVoiceIn){.id = UINT32_MAX});
    update(&f);
    tick(&f);
    assert(!f.r.voices[0].in.in_use && f.r.voices[0].state == SV_STOPPED);
    assert(f.r.voices[0].played == 0 && f.r.voices[0].consumed == 0);
    dispose(&f);
}

static void stream_resume(void) {
    Fixture f = fixture(4, 3);
    AudrenVoiceIn v = voice(2);
    put_voice(&f, 2, v);
    update(&f);
    for (int i = 0; i < 100; i++) tick(&f);
    ServerVoice *s = &f.r.voices[2];
    assert(s->state == SV_STARTED && s->played == 480 && s->consumed == 1);
    v.is_new = 0;
    v.wave_buffers[1] = v.wave_buffers[0];
    v.wave_buffers[0].sent = 1;
    v.wave_buffer_index = 1;
    put_voice(&f, 2, v);
    update(&f);
    tick(&f);
    assert(s->played == 720 && s->offset == 240);
    v.wave_buffers[1].sent = 1;
    v.play_state = PLAY_PAUSED;
    put_voice(&f, 2, v);
    update(&f);
    tick(&f);
    assert(s->played == 720);
    v.play_state = PLAY_STARTED;
    put_voice(&f, 2, v);
    update(&f);
    tick(&f);
    assert(s->played == 960 && s->consumed == 2);
    dispose(&f);
}

// End of stream on a buffer that finishes mid-frame: as in Ryujinx DataSourceHelper.Decode and yuzu DecodeFromWaveBuffers,
// the played count resets and the rest of the frame comes from the next queued buffer. XC2 flags every streamed buffer,
// so silencing the frame there cut voices (issue #29). The decoder and the clock must stay on one sample path.
static void end_of_stream_continues(void) {
    enum { LEN = 300 };
    static int16_t pcm[2][LEN];
    for (int i = 0; i < LEN; i++) { pcm[0][i] = (int16_t)(1000 + i); pcm[1][i] = (int16_t)(2000 + i); }
    Fixture f = fixture(4, 3);
    AudrenVoiceIn v = voice(0);
    for (int b = 0; b < 2; b++)
        v.wave_buffers[b] = (AudrenWaveBuffer){.address = (uint64_t)(uintptr_t)pcm[b], .size = sizeof pcm[b], .end = LEN,
                                               .end_of_stream = 1};
    v.wave_buffer_count = 2;
    put_voice(&f, 0, v);
    update(&f);
    ServerVoice *s = &f.r.voices[0];
    static float out[6][MAX_FRAME];
    voices_prepare(&f.r);
    voice_render(&f.r, s, out, 240);
    for (int k = 0; k < 240; k++) assert(out[0][k] == (1000 + k) / 32768.0f);
    advance_voice(&f.r, s, .005);
    assert(s->played == 240 && s->consumed == 0);
    voices_prepare(&f.r);
    voice_render(&f.r, s, out, 240);
    for (int k = 0; k < 60; k++) assert(out[0][k] == (1240 + k) / 32768.0f);
    for (int k = 60; k < 240; k++) assert(out[0][k] == (2000 + k - 60) / 32768.0f);
    advance_voice(&f.r, s, .005);
    assert(s->consumed == 1 && s->index == 1 && s->offset == 180 && s->played == 180);
    // The last buffer runs dry: silence after its samples, the clock stops, and played resets on the flagged end.
    voices_prepare(&f.r);
    voice_render(&f.r, s, out, 240);
    for (int k = 0; k < 120; k++) assert(out[0][k] == (2180 + k) / 32768.0f);
    for (int k = 120; k < 240; k++) assert(out[0][k] == 0);
    advance_voice(&f.r, s, .005);
    assert(s->consumed == 2 && s->played == 0 && s->state == SV_STARTED);
    dispose(&f);
}

static void full_voice_table(void) {
    Fixture f = fixture(96, 3);
    for (unsigned i = 0; i < 96; i++) {
        AudrenVoiceIn v = voice(i);
        v.priority = (int)i;
        put_voice(&f, i, v);
    }
    update(&f);
    tick(&f);
    for (unsigned i = 0; i < 96; i++)
        assert(f.r.voices[i].played == 240 && f.r.voices[i].drops == 0);
    dispose(&f);
}

static void reply_bounds(unsigned revision) {
    Fixture f = fixture(96, revision);
    if (revision < 5) f.output_size -= AUDREN_RENDER_INFO_OUT;
    // Match the 96-voice REV3 request and reply sizes in issue #29's log.
    if (revision == 3) assert(f.h.total == 71216 && f.output_size == 8064);
    free(f.output);
    f.output = malloc(f.output_size + 16);
    memset(f.output, 0xa5, f.output_size + 16);
    f.r.elapsed_frames = 123;
    update(&f);
    AudrenHeader reply;
    memcpy(&reply, f.output, sizeof reply);
    assert(reply.total == f.output_size);
    assert(reply.render_info == (revision < 5 ? 0 : AUDREN_RENDER_INFO_OUT));
    for (size_t i = f.output_size; i < f.output_size + 16; i++) assert(f.output[i] == 0xa5);
    if (reply.render_info) {
        uint64_t frames;
        memcpy(&frames, f.output + reply.total - reply.render_info, sizeof frames);
        assert(frames == 123);
    }
    dispose(&f);
}

int main(void) {
    inactive_entries(3);
    inactive_entries(15);
    stream_resume();
    end_of_stream_continues();
    full_voice_table();
    reply_bounds(3);
    reply_bounds(5);
    reply_bounds(15);
    puts("audren: inactive entries, REV3/REV15, stream resume, pause, end of stream and 96 voices passed");
    puts("audren: exact-size REV3/REV5/REV15 replies preserve the trailing guard");
    return 0;
}

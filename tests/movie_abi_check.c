// Constructor ABI and cold-fallback regression without game files or the full runtime.
// Build on Linux: clang -std=gnu11 -mavx2 -Iruntime tests/movie_abi_check.c runtime/ov_movie.c -lvpx -o /tmp/movie_abi_check
// Run each in a fresh process: /tmp/movie_abi_check buffer | mode | off
// Guest calls and the idle worker are stand-ins; libvpx is real, but no video is decoded here.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#include "cfg.h"
#include "movie.h"
#include "platform/platform.h"

extern const RtHostEntry __start_xc2_ovr[], __stop_xc2_ovr[];
static int buffer_abi, disabled, calls;
static uint64_t last_fn, forwarded[8];
static const uint64_t original_base = 0x1000, helper_base = 0x2000, vtable = 0x3000;
static const char *const helpers[] = {
    "_ZN2nn2os11SignalEventEPNS0_9EventTypeE", "_ZN5movie6Buffer8SetRangeEii",
    "_ZN5movie6Buffer18SetDataAndCapacityEPvm", "_ZNK5movie6Buffer4BaseEv", "_ZNK5movie6Buffer8CapacityEv",
    "_ZNK5movie9MediaData9FindInt32EPKcPi", "_ZNK5movie9MediaData10FindStringEPKcPS2_",
    "_ZN5movie9MediaData8SetInt32EPKci", "_ZN5movie9MediaData7SetRectEPKciiii", "_ZN5movie9MediaData9SetStringEPKcS2_"
};

uint64_t ldr_symbol(const char *name) {
    for (int i = 0; i < MOVIE_ENTRIES; i++) {
        if (strcmp(name, movie_symbols[i])) continue;
        if ((buffer_abi && i == MOVIE_CTOR) || (!buffer_abi && i == MOVIE_CTOR_BUFFER)) return 0;
        return original_base + 16 * i;
    }
    for (unsigned i = 0; i < sizeof helpers / sizeof *helpers; i++)
        if (!strcmp(name, helpers[i])) return helper_base + 16 * i;
    if (!strcmp(name, "_ZTVN5movie7DecoderE")) return vtable;
    abort();
}

GuestFn hostfn_override(const char *name) {
    for (const RtHostEntry *p = __start_xc2_ovr; p < __stop_xc2_ovr; p++)
        if (!strcmp(p->name, name)) return p->fn;
    return NULL;
}

uint64_t rt_call(Cpu *c, uint64_t fn, int n, ...) {
    assert(n >= 0 && n <= 8);
    va_list ap;
    va_start(ap, n);
    for (int i = 0; i < n; i++) c->x[i] = va_arg(ap, uint64_t);
    va_end(ap);
    if (fn >= original_base && fn < original_base + 16 * MOVIE_ENTRIES) {
        last_fn = fn;
        memcpy(forwarded, c->x, sizeof forwarded);
        calls++;
        return c->x[0] = 0x55;
    }
    assert(fn >= helper_base && fn < helper_base + sizeof helpers / sizeof *helpers * 16);
    if (fn == helper_base + 5 * 16) {   // MediaData::FindInt32: synthetic configuration
        const char *key = arg_p(c, 1);
        assert(!strcmp(key, "width") || !strcmp(key, "height"));
        *(int *)arg_p(c, 2) = 4;
    } else if (fn == helper_base + 6 * 16) {
        *(const char **)arg_p(c, 2) = "video/x-vnd.on2.vp9";
    }
    return c->x[0] = 1;
}

const char *cfg_get(const char *name) { return disabled && !strcmp(name, "XC2_MOVIE_HOST") ? "0" : NULL; }
void rt_log(const char *fmt, ...) { (void)fmt; }
void rt_fatal(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    abort();
}
uint64_t kern_now_ns(void) { return 1; }
int kern_core_away(void) { return 0; }
void kern_core_back(int *away) { (void)away; }
void *mem_kernel_alloc(uint64_t size, uint64_t align) { (void)align; return calloc(1, (size_t)size); }
void mem_kernel_free(void *p, uint64_t size) { (void)size; free(p); }
void plat_mutex_init(PlatMutex *m) { (void)m; }
void plat_mutex_lock(PlatMutex *m) { (void)m; }
void plat_mutex_unlock(PlatMutex *m) { (void)m; }
void plat_mutex_lock_shared(PlatMutex *m) { (void)m; }
void plat_mutex_unlock_shared(PlatMutex *m) { (void)m; }
void plat_cond_init(PlatCond *c) { (void)c; }
void plat_cond_signal(PlatCond *c) { (void)c; }
void plat_cond_broadcast(PlatCond *c) { (void)c; }
void plat_cond_wait(PlatCond *c, PlatMutex *m) { (void)c; (void)m; abort(); }
PlatThread *plat_thread_new(PlatThreadFn fn, void *arg, const char *name) {
    (void)fn; (void)arg; (void)name;
    return (PlatThread *)(uintptr_t)1;   // no input is queued in this test
}
void plat_thread_join(PlatThread *t) { (void)t; }

static void entry(Cpu *c, const char *name) {
    GuestFn f = hostfn_override(name);
    assert(f);
    f(c);
}

static void fallback(Cpu *c, int which) {
    uint64_t args[8];
    memcpy(args, c->x, sizeof args);
    int before = calls;
    entry(c, movie_symbols[which]);
    assert(calls == before + 1 && last_fn == original_base + 16 * which);
    assert(!memcmp(args, forwarded, sizeof args) && c->x[0] == 0x55);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    assert(!strcmp(argv[1], "buffer") || !strcmp(argv[1], "mode") || !strcmp(argv[1], "off"));
    buffer_abi = strcmp(argv[1], "mode") != 0;
    disabled = !strcmp(argv[1], "off");
    Cpu c = {0};
    // RegisterClientEvents must also work before any host constructor or movie_set_guest call.
    for (int i = 0; i < 8; i++) c.x[i] = 0x4000 + i;
    fallback(&c, MOVIE_REGISTER_EVENTS);
    for (int which = MOVIE_D2; which <= MOVIE_GET_OUTPUT_BUFFER_FORMAT; which++) {
        for (int i = 0; i < 8; i++) c.x[i] = 0x4000 + i;
        fallback(&c, which);
    }
    int ctor = buffer_abi ? MOVIE_CTOR_BUFFER : MOVIE_CTOR;
    int format = buffer_abi ? MOVIE_FORMAT_NV12_BUFFER : MOVIE_FORMAT_NV12;
    // A software audio decoder stays in the guest, with all registers preserved.
    for (int i = 0; i < 8; i++) c.x[i] = 0x5000 + i;
    c.x[1] = 4;
    fallback(&c, ctor);
    if (disabled) {
        c.x[1] = MOVIE_TYPE_VP9;
        c.x[2] = (uint64_t)format;
        fallback(&c, ctor);
        puts("movie ABI: host-off fallback passed");
        return 0;
    }
    if (!buffer_abi) {
        c.x[1] = MOVIE_TYPE_VP9;
        c.x[2] = (uint64_t)format;
        c.x[3] = 0;   // a non-buffer decoder still uses its original four-argument constructor
        fallback(&c, ctor);
    }
    // C1 and C2 must both construct host objects. Poison x3 for the ABI that has no mode argument.
    for (int alias = 0; alias < 2; alias++) {
        char name[160];
        snprintf(name, sizeof name, "%s", movie_symbols[ctor]);
        if (alias) strstr(name, "C1")[1] = '2';
        uint64_t object[2] = {0}, events[4] = {0};
        c.x[0] = (uintptr_t)object;
        c.x[1] = MOVIE_TYPE_VP9;
        c.x[2] = (uint64_t)format;
        c.x[3] = buffer_abi ? 0xdeadbeef : MOVIE_MODE_BUFFER;
        int before = calls;
        entry(&c, name);
        assert(calls == before && object[0] == vtable + 16 && object[1]);
        assert(movie_playing());
        c.x[0] = (uintptr_t)object;
        c.x[1] = (uintptr_t)events;
        entry(&c, movie_symbols[MOVIE_REGISTER_EVENTS]);
        assert(c.x[0] == 0);
        c.x[0] = (uintptr_t)object;
        c.x[1] = 1;   // the MediaData stand-in only uses the requested keys
        entry(&c, movie_symbols[MOVIE_CONFIGURE]);
        assert(c.x[0] == 0);
        int size = 0, count = 0;
        c.x[0] = (uintptr_t)object;
        c.x[1] = (uintptr_t)&size;
        c.x[2] = (uintptr_t)&count;
        entry(&c, movie_symbols[MOVIE_GET_OUTPUT_SIZE]);
        assert(c.x[0] == 0 && size == 24 && count == 1);
        c.x[0] = (uintptr_t)object;
        entry(&c, movie_symbols[MOVIE_D0]);
        assert(!movie_playing() && !object[1] && last_fn == original_base + 16 * MOVIE_D0);
    }
    // The other ABI's NV12 enum must not silently select a different guest pixel format.
    uint64_t object[2] = {0};
    c.x[0] = (uintptr_t)object;
    c.x[1] = MOVIE_TYPE_VP9;
    c.x[2] = buffer_abi ? MOVIE_FORMAT_NV12 : MOVIE_FORMAT_NV12_BUFFER;
    c.x[3] = MOVIE_MODE_BUFFER;
    entry(&c, movie_symbols[ctor]);
    c.x[0] = (uintptr_t)object;
    c.x[1] = 1;
    entry(&c, movie_symbols[MOVIE_CONFIGURE]);
    assert(c.x[0] == 0x2001);   // ST_UNSUPPORTED
    c.x[0] = (uintptr_t)object;
    entry(&c, movie_symbols[MOVIE_D2]);
    assert(!movie_playing() && !object[1]);
    puts("movie ABI: constructors, NV12 configuration and all method fallbacks passed");
    return 0;
}

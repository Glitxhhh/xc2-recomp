// Descriptor pool lifetimes without a renderer or game files.
// Run with tests/nvn_pools_test.py (uses the real NVN entry points and a recording back end).
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "../runtime/nvn_api_obj.c"

unsigned rt_trace;
void nvn_called(uint8_t *seen, const char *name) { (void)seen; (void)name; }
void rt_log(const char *fmt, ...) { (void)fmt; }
_Noreturn void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
void plat_mutex_lock(PlatMutex *m) { assert(!m->p); m->p = m; }
void plat_mutex_unlock(PlatMutex *m) { assert(m->p == m); m->p = NULL; }
void nvn_guest_written(uint64_t addr, uint64_t size) { (void)addr; (void)size; }
uint64_t nvn_new_serial(void) { static uint64_t n; return ++n; }

static int registrations, last_slot;
static void texture_register(int id, const tex_t *t, const view_t *v) {
    (void)t; (void)v; registrations++; last_slot = id;
}
static void sampler_register(int id, const samp_par *p) { (void)p; registrations++; last_slot = id; }
const GfxBackend *gfx_backend(void) {
    static const GfxBackend b = {.texture_register = texture_register, .sampler_register = sampler_register};
    return &b;
}

typedef void (*Api)(Cpu *);
static int init(Api fn, dpool_t *p, int n) {
    Cpu c = {.x = {(uintptr_t)p, 0, 0, (uint32_t)n}};
    fn(&c);
    return (int)c.x[0];
}
static void fini(Api fn, dpool_t *p) { Cpu c = {.x = {(uintptr_t)p}}; fn(&c); }
static void reg(Api fn, dpool_t *p, int id) {
    samp_t s = {0};
    Cpu c = {.x = {(uintptr_t)p, (uint32_t)id, (uintptr_t)&s, 0}};
    fn(&c);
}

static void pools(Api initialize, Api finalize, Api register_slot, int limit, int first, int second) {
    dpool_t a, b, c, d;
    for (int i = 0; i < 1000; i++) {
        assert(init(initialize, &a, first) && a.base == 0);
        assert(init(initialize, &b, second) && b.base == first);
        fini(finalize, &a);
        assert(init(initialize, &c, first) && c.base == 0);
        assert(b.base == first && b.n == second);
        fini(finalize, &b);
        fini(finalize, &c);
        fini(finalize, &c);
    }
    // Adjacent holes merge in both free orders; splitting a hole preserves the live neighbours.
    for (int reverse = 0; reverse < 2; reverse++) {
        assert(init(initialize, &a, 100) && init(initialize, &b, 200) && init(initialize, &c, 300));
        fini(finalize, reverse ? &b : &a);
        fini(finalize, reverse ? &a : &b);
        assert(init(initialize, &d, 250) && d.base == 0);
        assert(init(initialize, &a, 50) && a.base == 250);
        assert(c.base == 300);
        fini(finalize, &d); fini(finalize, &a); fini(finalize, &c);
    }
    assert(!init(initialize, &a, -1) && !init(initialize, &a, INT_MAX));
    assert(init(initialize, &a, limit) && a.base == 0);
    assert(!init(initialize, &b, 1));
    fini(finalize, &a);
    assert(init(initialize, &a, 0)); fini(finalize, &a);
    assert(init(initialize, &a, 8) && a.base == 0);
    assert(init(initialize, &b, 8) && b.base == 8);
    int before = registrations;
    reg(register_slot, &b, 0); assert(last_slot == 8);
    reg(register_slot, &b, 7); assert(last_slot == 15);
    reg(register_slot, &b, -1); reg(register_slot, &b, 8); reg(register_slot, &b, INT_MAX);
    assert(registrations == before + 2);
    fini(finalize, &b);
    reg(register_slot, &b, 0); assert(registrations == before + 2);
    fini(finalize, &a);
}

int main(void) {
    pools(nvnp_nvnSamplerPoolInitialize, nvnp_nvnSamplerPoolFinalize, nvnp_nvnSamplerPoolRegisterSampler,
          1 << 14, 4096, 2048);
    pools(nvnp_nvnTexturePoolInitialize, nvnp_nvnTexturePoolFinalize, nvnp_nvnTexturePoolRegisterTexture,
          1 << 20, 40960, 2048);
    pools(nvnp_nvnTexturePoolInitialize, nvnp_nvnTexturePoolFinalize, nvnp_nvnTexturePoolRegisterImage,
          1 << 20, 40960, 2048);
    puts("pools: 3000 reuse cycles, coalescing, splitting, capacity and registration bounds passed");
}

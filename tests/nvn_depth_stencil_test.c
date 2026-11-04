// The depth stencil mode getters of the texture builder and the texture, without a renderer or game files.
// Run with tests/nvn_depth_stencil_test.py (uses the real NVN entry points and a stub back end).
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn_api_obj.c"

void nvnp_nvnTextureBuilderGetDepthStencilMode(Cpu *c);
void nvnp_nvnTextureGetDepthStencilMode(Cpu *c);

unsigned rt_trace;
const char *cfg_get(const char *key) { (void)key; return NULL; }
void nvn_called(uint8_t *seen, const char *name) { (void)seen; (void)name; }
void rt_log(const char *fmt, ...) { (void)fmt; }
_Noreturn void rt_fatal(const char *fmt, ...) { (void)fmt; abort(); }
void plat_mutex_lock(PlatMutex *m) { assert(!m->p); m->p = m; }
void plat_mutex_unlock(PlatMutex *m) { assert(m->p == m); m->p = NULL; }
void nvn_guest_written(uint64_t addr, uint64_t size) { (void)addr; (void)size; }
uint64_t nvn_new_serial(void) { static uint64_t n; return ++n; }

static void texture_release(const tex_t *t) { (void)t; }
const GfxBackend *gfx_backend(void) {
    static const GfxBackend b = {.texture_release = texture_release};
    return &b;
}

int main(void) {
    tex_builder_t b = {0};
    tex_t t = {0};
    Cpu c = {.x = {(uintptr_t)&b}};
    nvnp_nvnTextureBuilderSetDefaults(&c);
    c.x[0] = (uintptr_t)&b; nvnp_nvnTextureBuilderGetDepthStencilMode(&c);
    assert(c.x[0] == NVN_TEXTURE_DEPTH_STENCIL_MODE_DEPTH);
    c.x[0] = (uintptr_t)&b; c.x[1] = NVN_TEXTURE_DEPTH_STENCIL_MODE_STENCIL;
    nvnp_nvnTextureBuilderSetDepthStencilMode(&c);
    c.x[0] = (uintptr_t)&b; nvnp_nvnTextureBuilderGetDepthStencilMode(&c);
    assert(c.x[0] == NVN_TEXTURE_DEPTH_STENCIL_MODE_STENCIL);
    c.x[0] = (uintptr_t)&t; c.x[1] = (uintptr_t)&b; nvnp_nvnTextureInitialize(&c);
    assert(c.x[0] == 1);
    c.x[0] = (uintptr_t)&b; nvnp_nvnTextureBuilderSetDefaults(&c);
    c.x[0] = (uintptr_t)&t; nvnp_nvnTextureGetDepthStencilMode(&c);
    assert(c.x[0] == NVN_TEXTURE_DEPTH_STENCIL_MODE_STENCIL);
    c.x[0] = (uintptr_t)&t; nvnp_nvnTextureFinalize(&c);
    c.x[0] = (uintptr_t)&t; c.x[1] = (uintptr_t)&b; nvnp_nvnTextureInitialize(&c);
    c.x[0] = (uintptr_t)&t; nvnp_nvnTextureGetDepthStencilMode(&c);
    assert(c.x[0] == NVN_TEXTURE_DEPTH_STENCIL_MODE_DEPTH);
    c.x[0] = (uintptr_t)&t; nvnp_nvnTextureFinalize(&c);
    puts("depth stencil getters: defaults and stored modes passed");
}

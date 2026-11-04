// A function run on a new fiber gets the stack alignment the System V ABI promises: at a call the stack pointer is
// a multiple of 16, so a 16-byte aligned local sits at a 16-byte aligned address and clang's aligned spills
// (vmovaps [rsp]) do not fault. Linux only (runtime/platform/linux.c plat_fiber_new). linux.c needs the SDL3 headers
// and SDL_SetClipboardText (SDL3 itself, or a one-line stub).
//
//     clang -O1 -Iruntime -Iruntime/platform tests/fiber_align_check.c runtime/platform/linux.c \
//         runtime/platform/common.c -lSDL3 -lpthread -o build/fiber_align_check && build/fiber_align_check
#include <stdint.h>
#include <stdio.h>

#include "platform.h"

static PlatFiber *main_fiber;
static uintptr_t seen;

__attribute__((noinline)) static void probe(void) {
    _Alignas(16) volatile char local[16];
    local[0] = 0;
    seen = (uintptr_t)local;
}

static void on_fiber(void *arg) {
    (void)arg;
    probe();
    plat_fiber_switch(main_fiber);
}

int main(void) {
    main_fiber = plat_fiber_self();
    PlatFiber *f = plat_fiber_new(256 * 1024, on_fiber, NULL);
    if (!f) {
        puts("fiber_align_check: plat_fiber_new failed");
        return 2;
    }
    plat_fiber_switch(f);
    plat_fiber_free(f);
    int ok = (seen & 15) == 0;
    printf("fiber_align_check: aligned local at %#llx: %s\n", (unsigned long long)seen, ok ? "ok" : "MISALIGNED");
    return !ok;
}

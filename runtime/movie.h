// Adapted from MacNativeGames games/totk/runtime/movie_host.h @ b75be8cf (MIT, Copyright (c) 2026 MacNativeGames
// contributors).
// What ov_movie.c (the host movie::Decoder) and movie_probe.c share. The game reaches the decoder through the
// HOST_OVERRIDE entries named in movie_symbols; the probe calls the same entries with a Cpu of its own and stand-ins for
// the guest functions the decoder calls.
#pragma once
#include <stdint.h>

#include "host.h"

// Entries in the order of movie_symbols[]: the constructor taking mode and priority, the 19 slots of the vtable for
// movie::Decoder, then the two-argument constructor used by 3.0.1 (buffer mode, with a different output-format enum).
enum { MOVIE_CTOR, MOVIE_D2, MOVIE_D0, MOVIE_CONFIGURE, MOVIE_REGISTER_EVENTS, MOVIE_GET_OUTPUT_FORMAT, MOVIE_START,
       MOVIE_STOP, MOVIE_RESET, MOVIE_FLUSH, MOVIE_ACQUIRE_INPUT, MOVIE_GET_INPUT, MOVIE_SEND_INPUT, MOVIE_ACQUIRE_OUTPUT,
       MOVIE_GET_OUTPUT, MOVIE_GET_OUTPUT_SIZE, MOVIE_RELEASE_OUTPUT, MOVIE_GET_LAST_ERROR, MOVIE_GET_OUTPUT_MD,
       MOVIE_GET_OUTPUT_BUFFER_FORMAT, MOVIE_CTOR_BUFFER, MOVIE_ENTRIES };
extern const char *const movie_symbols[MOVIE_ENTRIES];

// Guest addresses of the functions the decoder calls with rt_call: nn::os::SignalEvent, movie::Buffer and
// movie::MediaData methods, the vtable address the constructor stores (vtable + 0x10), and the original code of every
// entry for decoders left to the library (an absent constructor ABI has address 0). Filled from the loaded modules
// at the first constructor or fallback call, or by the probe.
typedef struct {
    uint64_t signal_event, buf_set_range, buf_set_data, buf_base, buf_capacity;
    uint64_t md_find_int32, md_find_string, md_set_int32, md_set_rect, md_set_string;
    uint64_t vptr;
    uint64_t orig[MOVIE_ENTRIES];
} MovieGuest;

enum { MOVIE_EV_INPUT, MOVIE_EV_OUTPUT, MOVIE_EV_FORMAT, MOVIE_EV_ERROR };   // DecoderEvents: EventType * per event
enum { MOVIE_TYPE_VP9 = 3, MOVIE_MODE_BUFFER = 1, MOVIE_FORMAT_NV12 = 4, MOVIE_FLAG_EOS = 4 };
enum { MOVIE_FORMAT_NV12_BUFFER = 3 };   // two-argument constructor ABI

typedef struct { uint64_t frames, decode_ns, max_ns, errors, dropped, handed; } MovieStats;

void movie_set_guest(const MovieGuest *g);                 // probe: stand-ins instead of the modules
void movie_set_clock(uint64_t (*clock)(void));             // probe: a fake clock (ns) for the pacing; NULL = real
void movie_set_pace(int on);                               // probe: 0 hands every decoded frame over at the next tick
int movie_stats(uint64_t obj, MovieStats *out);            // counters of the decoder at guest object obj; 0 if none
int movie_quiet(uint64_t obj);                             // 1 when its worker is idle and cannot take more input now

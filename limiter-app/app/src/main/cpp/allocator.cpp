#include <jni.h>
#include <sys/mman.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <android/log.h>

#define LOG_TAG "LimiterExp"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)

static jlong* g_addrs = nullptr;
static jlong* g_sizes = nullptr;
static size_t g_count = 0;
static size_t g_capacity = 0;

static void store(jlong addr, jlong size) {
    if (g_count >= g_capacity) {
        g_capacity = g_capacity ? g_capacity * 2 : 16;
        g_addrs = (jlong*)realloc(g_addrs, g_capacity * sizeof(jlong));
        g_sizes = (jlong*)realloc(g_sizes, g_capacity * sizeof(jlong));
    }
    g_addrs[g_count] = addr;
    g_sizes[g_count] = size;
    g_count++;
}

extern "C" JNIEXPORT void JNICALL
Java_com_returnzero_limiter_Allocator_nativeAllocate(JNIEnv* env, jobject thiz, jint mb) {
    jlong target = (jlong)mb * 1024L * 1024L;
    jlong chunk = 64L * 1024 * 1024; // 64 MB
    jlong remaining = target;
    jlong allocated = 0;
    long page = sysconf(_SC_PAGESIZE);
    while (remaining > 0) {
        jlong size = chunk < remaining ? chunk : remaining;
        void* p = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (p == MAP_FAILED) {
            LOGW("mmap failed at %lldMB", (long long)(allocated / (1024*1024)));
            return;
        }
        store((jlong)p, size);
        for (jlong off = 0; off < size; off += page) {
            ((char*)p)[off] = 1;
        }
        remaining -= size;
        allocated += size;
        LOGI("mmap %lldMB at %p total=%lldMB", (long long)(size/(1024*1024)), p, (long long)(allocated/(1024*1024)));
    }
    LOGI("allocated %dMB total=%lldMB chunks=%zu", mb, (long long)(allocated/(1024*1024)), g_count);
}

extern "C" JNIEXPORT void JNICALL
Java_com_returnzero_limiter_Allocator_nativeFree(JNIEnv* env, jobject thiz) {
    for (size_t i = 0; i < g_count; i++) {
        munmap((void*)g_addrs[i], g_sizes[i]);
    }
    g_count = 0;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_returnzero_limiter_Allocator_nativeRssKb(JNIEnv* env, jobject thiz) {
    FILE* f = fopen("/proc/self/status", "r");
    if (!f) return -1;
    char line[256];
    long rss = -1;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "VmRSS:", 6) == 0) {
            rss = atol(line + 6);
            break;
        }
    }
    fclose(f);
    return rss;
}
from pathlib import Path
p = Path('libs/manymesh/src/Streaming.cpp')
s = p.read_text(encoding='utf-8')
def rep(old, new):
    global s
    assert old in s, old[:100]
    s = s.replace(old, new, 1)
rep('''#include <algorithm>
#include <chrono>
#include <cstring>
#include <iterator>
#include <set>
#include <utility>

#if defined(_WIN32)
''', '''#include <algorithm>
#include <chrono>
#include <cstring>
#include <iterator>
#include <mutex>
#include <set>
#include <utility>

#if defined(MANYMESH_HTTP_CIVETWEB)
#include <civetweb.h>
#endif

#if defined(_WIN32)
''')
rep('''struct HttpByteRangeFetcher::Impl {
    std::string url;
    std::string error;
    unsigned timeoutMs = 5000;
    bool valid = false;
    HttpByteRangeFetcher::RangeFetcher platformFetcher;

#if defined(_WIN32)
''', '''struct HttpByteRangeFetcher::Impl {
    std::string url;
    std::string error;
    unsigned timeoutMs = 5000;
    bool valid = false;
    HttpByteRangeFetcher::RangeFetcher platformFetcher;

#if defined(MANYMESH_HTTP_CIVETWEB)
    bool civetwebHttps = false;
    int civetwebPort = 80;
    std::string civetwebHost;
    std::string civetwebPath;
#endif

#if defined(_WIN32)
''')
rep('''namespace {

#if defined(_WIN32)
''', '''namespace {

#if defined(MANYMESH_HTTP_CIVETWEB)

struct ParsedCivetUrl {
    bool https = false;
    int port = 80;
    std::string host;
    std::string path;
};

bool parseCivetUrl(std::string const& url, ParsedCivetUrl* parsed, std::string* error) {
    std::string rest;
    if (url.rfind("https://", 0) == 0) {
        parsed->https = true;
        parsed->port = 443;
        rest = url.substr(8);
    } else if (url.rfind("http://", 0) == 0) {
        parsed->https = false;
        parsed->port = 80;
        rest = url.substr(7);
    } else {
        *error = "URL must start with http:// or https://";
        return false;
    }

    size_t const tailIndex = rest.find_first_of("/?#");
    std::string const authority = rest.substr(0, tailIndex);
    std::string tail = tailIndex == std::string::npos ? std::string() : rest.substr(tailIndex);
    if (tail.empty() || tail[0] == '?' || tail[0] == '#') {
        tail = "/" + tail;
    }
    parsed->path = std::move(tail);
    if (authority.empty()) {
        *error = "URL has no host";
        return false;
    }

    std::string host = authority;
    std::string portText;
    if (authority.front() == '[') {
        size_t const close = authority.find(']');
        if (close == std::string::npos) {
            *error = "URL has an unterminated IPv6 host";
            return false;
        }
        host = authority.substr(1, close - 1);
        if (close + 1 < authority.size()) {
            if (authority[close + 1] != ':') {
                *error = "URL has an invalid port";
                return false;
            }
            portText = authority.substr(close + 2);
        }
    } else {
        size_t const colon = authority.rfind(':');
        if (colon != std::string::npos) {
            if (authority.find(':') != colon) {
                *error = "IPv6 hosts must be wrapped in brackets";
                return false;
            }
            host = authority.substr(0, colon);
            portText = authority.substr(colon + 1);
        }
    }
    if (!portText.empty()) {
        int port = 0;
        for (char c: portText) {
            if (c < '0' || c > '9') {
                *error = "URL has an invalid port";
                return false;
            }
            port = port * 10 + int(c - '0');
            if (port > 65535) {
                *error = "URL has an invalid port";
                return false;
            }
        }
        if (port == 0) {
            *error = "URL has an invalid port";
            return false;
        }
        parsed->port = port;
    }
    if (host.empty()) {
        *error = "URL has no host";
        return false;
    }
    parsed->host = std::move(host);
    return true;
}

void initializeCivetweb() {
    static std::once_flag once;
    std::call_once(once, []() { mg_init_library(0); });
}

#endif

#if defined(_WIN32)
''')
rep('''    mImpl->url = std::move(url);
    mImpl->timeoutMs = std::max(timeoutMs, 1u);
#if defined(_WIN32)
    ParsedHttpUrl parsed;
''', '''    mImpl->url = std::move(url);
    mImpl->timeoutMs = std::max(timeoutMs, 1u);
#if defined(MANYMESH_HTTP_CIVETWEB)
    ParsedCivetUrl parsed;
    mImpl->valid = parseCivetUrl(mImpl->url, &parsed, &mImpl->error);
    if (mImpl->valid) {
        mImpl->civetwebHttps = parsed.https;
        mImpl->civetwebPort = parsed.port;
        mImpl->civetwebHost = std::move(parsed.host);
        mImpl->civetwebPath = std::move(parsed.path);
    }
#elif defined(_WIN32)
    ParsedHttpUrl parsed;
''')
rep('''#if defined(_WIN32)
    mImpl->error.clear();
    DWORD const accessType = isLoopbackHost(mImpl->host) ? WINHTTP_ACCESS_TYPE_NO_PROXY
''', '''#if defined(MANYMESH_HTTP_CIVETWEB)
    mImpl->error.clear();
    initializeCivetweb();
    char connectionError[256] = {};
    mg_connection* connection = mg_connect_client(mImpl->civetwebHost.c_str(),
            mImpl->civetwebPort, mImpl->civetwebHttps ? 1 : 0, connectionError,
            sizeof(connectionError));
    if (connection == nullptr) {
        mImpl->error = connectionError[0] != '\0' ? connectionError
                                                  : "mg_connect_client failed";
        return false;
    }

    std::string hostHeader = mImpl->civetwebHost;
    if (hostHeader.find(':') != std::string::npos) {
        hostHeader = "[" + hostHeader + "]";
    }
    if ((mImpl->civetwebHttps && mImpl->civetwebPort != 443) ||
            (!mImpl->civetwebHttps && mImpl->civetwebPort != 80)) {
        hostHeader += ":" + std::to_string(mImpl->civetwebPort);
    }
    unsigned long long const end = offset + (size - 1);
    int const written = mg_printf(connection,
            "GET %s HTTP/1.1\\r\\nHost: %s\\r\\nRange: bytes=%llu-%llu\\r\\n"
            "Accept-Encoding: identity\\r\\nConnection: close\\r\\n\\r\\n",
            mImpl->civetwebPath.c_str(), hostHeader.c_str(), offset, end);
    if (written <= 0) {
        mImpl->error = "mg_printf failed";
        mg_close_connection(connection);
        return false;
    }

    char responseError[256] = {};
    int const response = mg_get_response(connection, responseError, sizeof(responseError),
            int(std::min(mImpl->timeoutMs, unsigned(INT_MAX))));
    mg_response_info const* info = mg_get_response_info(connection);
    if (response < 0 || info == nullptr) {
        mImpl->error = responseError[0] != '\0' ? responseError : "mg_get_response failed";
        mg_close_connection(connection);
        return false;
    }
    if (info->status_code != 206 && !(info->status_code == 200 && offset == 0)) {
        mImpl->error = "server did not honor the byte range (status " +
                       std::to_string(info->status_code) + ")";
        mg_close_connection(connection);
        return false;
    }

    bytes->reserve(size);
    while (bytes->size() < size) {
        uint8_t chunk[64 * 1024];
        size_t const want = std::min(size - bytes->size(), sizeof(chunk));
        int const read = mg_read(connection, chunk, want);
        if (read < 0) {
            mImpl->error = "mg_read failed";
            bytes->clear();
            mg_close_connection(connection);
            return false;
        }
        if (read == 0) {
            break;
        }
        bytes->insert(bytes->end(), chunk, chunk + read);
    }
    mg_close_connection(connection);
    if (bytes->size() != size) {
        mImpl->error = "short read: expected " + std::to_string(size) + ", got " +
                       std::to_string(bytes->size());
        bytes->clear();
        return false;
    }
    return true;
#elif defined(_WIN32)
    mImpl->error.clear();
    DWORD const accessType = isLoopbackHost(mImpl->host) ? WINHTTP_ACCESS_TYPE_NO_PROXY
''')
p.write_text(s, encoding='utf-8')
print('civetweb transport added')

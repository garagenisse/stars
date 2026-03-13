# api.py — Lättviktig HTTP-server för stjärnhimmel-styrning (MicroPython)
#
# Endpoints:
#   GET  /         → serverar www/index.html (kontrollpanel)
#   GET  /params   → returnerar parametrar som JSON
#   POST /params   → uppdaterar parametrar, sparar till flash
#   GET  /status   → returnerar aktiv stjärnbild och t_ms
#
# Exempel:
#   curl http://<PICO-IP>/params
#   curl -X POST http://<PICO-IP>/params \
#        -H "Content-Type: application/json" \
#        -d '{"fade_ms": 3000, "flicker_pct": 20}'

import json
import uasyncio as asyncio
import os


def _html_response(writer, filepath):
    """Streama en HTML-fil direkt till klienten i 512-bytes-bitar."""
    try:
        size = os.stat(filepath)[6]
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).format(size)
        return header, filepath
    except OSError:
        return None, None


def _json_response(data, status="200 OK"):
    body = json.dumps(data)
    return (
        "HTTP/1.1 {}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Connection: close\r\n"
        "\r\n"
        "{}"
    ).format(status, len(body), body)


def _options_response():
    """CORS pre-flight — tillåter anrop från simulation.html (GitHub Pages)."""
    return (
        "HTTP/1.1 204 No Content\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
        "Access-Control-Allow-Headers: Content-Type\r\n"
        "Connection: close\r\n"
        "\r\n"
    )


async def _read_request(reader):
    """Läser request-line + headers + body. Returnerar (method, path, body_str)."""
    request_line = (await reader.readline()).decode("utf-8").strip()
    if not request_line:
        return None, None, None

    parts = request_line.split(" ")
    method = parts[0].upper() if len(parts) >= 1 else "GET"
    path   = parts[1]         if len(parts) >= 2 else "/"

    headers = {}
    while True:
        line = (await reader.readline()).decode("utf-8").strip()
        if not line:
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    body = ""
    content_length = int(headers.get("content-length", 0))
    if content_length > 0:
        raw = await reader.read(content_length)
        body = raw.decode("utf-8")

    return method, path, body


async def handle_client(reader, writer, controller):
    try:
        method, path, body = await _read_request(reader)

        if method is None:
            return

        # CORS pre-flight
        if method == "OPTIONS":
            writer.write(_options_response().encode())
            await writer.drain()
            return

        # GET / — servera kontrollpanel-HTML
        if method == "GET" and path == "/":
            header, filepath = _html_response(writer, "www/index.html")
            if header is None:
                writer.write(_json_response({"error": "index.html saknas"}, "404 Not Found").encode())
            else:
                writer.write(header.encode())
                await writer.drain()
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(512)
                        if not chunk:
                            break
                        writer.write(chunk)
                        await writer.drain()
            return

        # GET /params — returnera parametrar som JSON
        if method == "GET" and path == "/params":
            response = _json_response(controller.params)

        # POST /params — uppdatera parametrar
        elif method == "POST" and path == "/params":
            try:
                new_params = json.loads(body)
                controller.update_params(new_params)
                response = _json_response({"ok": True, "params": controller.params})
            except Exception as e:
                response = _json_response(
                    {"ok": False, "error": str(e)}, "400 Bad Request"
                )

        # GET /status — aktiv LED och tid
        elif method == "GET" and path == "/status":
            response = _json_response(controller.get_status())

        else:
            response = _json_response({"error": "Not found"}, "404 Not Found")

        writer.write(response.encode())
        await writer.drain()

    except Exception as e:
        print("API error:", e)
    finally:
        writer.close()
        await writer.wait_closed()


async def start_server(controller, port=80):
    print("HTTP API lyssnar på port", port)

    async def client_handler(reader, writer):
        await handle_client(reader, writer, controller)

    server = await asyncio.start_server(client_handler, "0.0.0.0", port)
    async with server:
        await asyncio.sleep(0)           # håller servern igång via main-loopens gather
